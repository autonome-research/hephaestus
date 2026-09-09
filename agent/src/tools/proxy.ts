// Tool proxy: validate model arguments, dispatch across the bridge with trusted
// invocation metadata, validate the result, and render Pi tool content
// (architecture §4.1, digest §1/§6/§7).
//
// Pipeline per call:
//   1. Base-shape validation with the generated TypeBox (Value.Check).
//   2. JSON-Schema CONDITIONAL enforcement (if/then/else, allOf, not) — TypeBox
//      Value.Check ignores these, so the proxy evaluates them itself with parity
//      to the Python jsonschema validator.
//   3. x-hephaestus-maxUtf8Bytes enforcement (exact UTF-8 bytes; lone surrogate
//      -> invalid_unicode_scalar; oversize -> prompt_too_large; never truncated).
//   4. Bridge request: py.tool_dispatch (generic) / py.delegate / py.ask_user,
//      carrying the trusted invocation for mutation idempotency.
//   5. Result validation against the tool's result schema. A malformed result
//      FAILS CLOSED — the model receives a generic error, never the raw payload.
//   6. Rendering to Pi content: bounded text plus inline images within the §5
//      image/text budgets; artifact refs are preserved in the text.
//
// Recognized structured capability errors surfaced as RPC errors
// (e.g. export nested_sheet -> capability_not_available) are passed THROUGH to
// the model as a discriminated tool result rather than failing closed.

import { Value } from "@sinclair/typebox/value";
import type { AgentToolResult } from "@earendil-works/pi-coding-agent";
import type { JsonValue } from "../framing.js";
import {
  CAD_BUILD_TIMEOUT_MS,
  DELEGATION_GRACE_MS,
  LIMITS,
  MAX_IMAGES_PER_RESULT,
  TOOL_TIMEOUT_MS,
  enforceBinaryBudget,
  enforceMaxUtf8Bytes,
  parseImageHeader,
  LimitError,
} from "../limits.js";
import { TOOLS } from "./schema.gen.js";
import { clarificationRefusal } from "./clarify.js";
import type { TrustedInvocation } from "./invocation.js";

/**
 * Minimal bridge request surface (RpcPeer.request); rejects with RpcError.
 *
 * The third parameter is the per-call deadline in milliseconds, and it is the
 * seam audit-2026-09-04 J-http-limits-11 found missing: `RpcPeer.request` has
 * always taken one, but this type erased it, so the layer that KNOWS which tool
 * is running structurally could not ask for a different deadline. Every tool
 * therefore ran on the peer's default, which is why the 300-second CAD-build
 * class three documents state as fact was unreachable.
 */
export type RpcRequest = (
  method: string,
  params: { [k: string]: JsonValue },
  timeoutMs?: number,
) => Promise<JsonValue>;

/**
 * The tools whose Python handler carries an inner ceiling of
 * `timeouts.cad_build_seconds`.
 *
 * THE PREDICATE IS THE DEADLINE'S, NOT THE EXECUTOR'S, and the difference
 * matters: what J-http-limits-8 is about is a layer above giving up before the
 * layer below, so what belongs in this class is every tool whose Python side
 * may legitimately still be working after the ordinary 120-second deadline —
 * not merely the ones that happen to enter `CadOps._run`. Naming it after the
 * sandboxed executor (as this set did when it first landed) is a *different*
 * predicate, and it silently left three tools with 300-second Python ceilings
 * being killed at the RPC layer at 120.
 *
 * Members, each with the ceiling that puts it here:
 *   - `build_part` (`cad_ops/_build.py`), `run_checks` (`_checks.py`) and
 *     `set_params` (`_params.py`, which rebuilds to report effective
 *     parameters) reach `CadOps._run`, whose wall clock is
 *     `executor/runner.py`'s `DEFAULT_WALL_CLOCK_S`;
 *   - `compare_solids` (`core/project_compare.py` `COMPARE_TIMEOUT_S`) and
 *     `compare_to_scan` (`core/scan_compare.py` `SCAN_TIMEOUT_S`) run their
 *     kernel work in a killable subprocess under that same 300;
 *   - `check_motion` (`core/motion.py` `MOTION_TIMEOUT_S`) sweeps under it too,
 *     and reports hitting it as the named `motion_timeout` refusal — a refusal
 *     the model can only ever see if the RPC layer waits long enough for it.
 *
 * Deliberately NOT here, so the omission is a decision and not an oversight:
 * `solve_pose` and `propose_placement` have no single wall clock to match —
 * `core/placement.py` bounds them by iteration count, a 60-second per-iteration
 * backstop and a 240-build budget, so a long solve can exceed *any* of these
 * classes and putting it on the 300 would be picking a number rather than
 * matching one. That is a real gap, recorded for the ledger rather than
 * papered over here.
 *
 * WRITTEN HERE UNDER PROTEST, and recorded so the next reader does not mistake
 * it for the intended shape. J-http-limits-11 asks for the timeout class to be
 * *declared data* — a `timeout_class` field on the tool declaration
 * (`contract/src/hephaestus/contract/tools_decl.py`) flowing through the
 * existing generator into `schema.gen.ts`'s `ToolMeta` and the committed
 * schemas — precisely so a closed set is never transcribed by hand. That
 * declaration is owned by the tool-results lane and did not land in this pass;
 * until it does this set is the one place the mapping exists, and
 * `selectTimeout` below reads `meta.timeoutClass` first so the switch to
 * declared data is a deletion rather than a rewrite.
 */
const CAD_BUILD_TOOLS: ReadonlySet<string> = new Set([
  "build_part",
  "run_checks",
  "set_params",
  "compare_solids",
  "compare_to_scan",
  "check_motion",
]);

/**
 * Per-call trusted context supplied by the session layer.
 *
 * Per CALL, and therefore per RUN: with turns overlapping in one sidecar
 * process, `sessionId`/`runId` here are the identity of the run that INVOKED
 * this tool, resolved by the session layer from that run's own scope
 * (main.ts `resolveContext`) rather than from a shared "current run" slot. The
 * proxy never reads ambient state to fill these in — everything it stamps onto
 * a bridge request comes from this object, which is what keeps one run's tool
 * call from crossing the bridge under another run's identity.
 */
export interface ProxyContext {
  readonly sessionId: string;
  readonly runId: string;
  readonly invocation: TrustedInvocation;
  /**
   * Whether the model that will read this tool result can consume image blocks.
   * `false` turns an image-bearing result into the discriminated
   * `image_model_required` refusal instead of shipping blocks the model would
   * silently drop. Omitted (undefined) means "unknown" and is treated as capable
   * — image capability is negotiated by the session layer, not guessed here.
   */
  readonly imagesSupported?: boolean;
}

export interface ProxyDetails {
  readonly tool: string;
  readonly result: JsonValue;
  readonly images: number;
  readonly capability?: string;
}

export type ProxyToolResult = AgentToolResult<ProxyDetails>;

/** Input-validation failure the model should see and correct. */
export class ProxyValidationError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ProxyValidationError";
  }
}

/** Result-validation failure: fails closed; the raw payload never reaches the model. */
export class ProxyResultError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ProxyResultError";
  }
}

// Structured capability codes that are legitimate discriminated outcomes rather
// than malformed results — passed through to the model when raised as RPC errors.
const CAPABILITY_CODES: ReadonlySet<string> = new Set([
  "capability_not_available",
  "image_model_required",
]);

// -- minimal JSON-Schema conditional evaluator ------------------------------
// Evaluates only the keyword subset present in the generated schemas'
// conditionals: properties, required, const, enum, type, pattern, not,
// if/then/else, allOf. Base shape is already guaranteed by Value.Check, so this
// runs ONLY over the conditional keywords of the params schema.

type SchemaNode = { [k: string]: unknown };

function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null) return a === b;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (typeof a === "object" && typeof b === "object") {
    const ak = Object.keys(a as object);
    const bk = Object.keys(b as object);
    if (ak.length !== bk.length) return false;
    return ak.every(
      (k) => k in (b as object) && jsonEqual((a as SchemaNode)[k], (b as SchemaNode)[k]),
    );
  }
  return false;
}

function matchesType(type: string, value: unknown): boolean {
  switch (type) {
    case "string":
      return typeof value === "string";
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "number":
      return typeof value === "number";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "array":
      return Array.isArray(value);
    case "object":
      return value !== null && typeof value === "object" && !Array.isArray(value);
    default:
      return true;
  }
}

function isPresent(obj: unknown, key: string): boolean {
  return (
    obj !== null &&
    typeof obj === "object" &&
    !Array.isArray(obj) &&
    key in (obj as object) &&
    (obj as SchemaNode)[key] !== undefined
  );
}

function satisfies(schema: SchemaNode, value: unknown): boolean {
  if ("const" in schema && !jsonEqual(value, schema.const)) return false;
  if ("enum" in schema) {
    const options = schema.enum as unknown[];
    if (!options.some((o) => jsonEqual(o, value))) return false;
  }
  if ("type" in schema) {
    const type = schema.type;
    const types = Array.isArray(type) ? (type as string[]) : [type as string];
    if (!types.some((t) => matchesType(t, value))) return false;
  }
  if ("pattern" in schema) {
    if (typeof value !== "string" || !new RegExp(schema.pattern as string).test(value)) {
      return false;
    }
  }
  if ("required" in schema) {
    for (const key of schema.required as string[]) {
      if (!isPresent(value, key)) return false;
    }
  }
  if ("properties" in schema && value !== null && typeof value === "object") {
    const props = schema.properties as Record<string, SchemaNode>;
    for (const [key, sub] of Object.entries(props)) {
      if (isPresent(value, key) && !satisfies(sub, (value as SchemaNode)[key])) return false;
    }
  }
  if ("not" in schema && satisfies(schema.not as SchemaNode, value)) return false;
  if ("if" in schema) {
    if (satisfies(schema.if as SchemaNode, value)) {
      if ("then" in schema && !satisfies(schema.then as SchemaNode, value)) return false;
    } else if ("else" in schema && !satisfies(schema.else as SchemaNode, value)) {
      return false;
    }
  }
  if ("allOf" in schema) {
    for (const sub of schema.allOf as SchemaNode[]) {
      if (!satisfies(sub, value)) return false;
    }
  }
  return true;
}

/** True when the value satisfies every conditional keyword of the params schema. */
export function checkConditionals(paramsSchema: SchemaNode, value: unknown): boolean {
  const conditional: SchemaNode = {};
  for (const kw of ["allOf", "if", "then", "else", "not"] as const) {
    if (kw in paramsSchema) conditional[kw] = paramsSchema[kw];
  }
  return satisfies(conditional, value);
}

// ---------------------------------------------------------------------------

/**
 * Downgrade an image-bearing result to `image_model_required` when the reading
 * model is text-only. Returns `undefined` when the result carries no images or
 * the model can read them (the overwhelmingly common path).
 *
 * Stage 2 has no vision-model fallback wired: with a text-only active model and
 * no configured image model the refusal IS the outcome, and it is discriminated
 * so a client can branch on it. Routing to a configured vision model would land
 * here as an alternative branch.
 */
function imageCapabilityRefusal(
  result: JsonValue,
  ctx: ProxyContext,
): { [k: string]: JsonValue } | undefined {
  if (ctx.imagesSupported !== false) return undefined;
  if (result === null || typeof result !== "object" || Array.isArray(result)) return undefined;
  const obj = result as { [k: string]: JsonValue };
  if (!Array.isArray(obj.images) || obj.images.length === 0) return undefined;
  const refusal: { [k: string]: JsonValue } = {
    status: "capability_error",
    code: "image_model_required",
    message:
      "the active model cannot read image blocks and no vision model is configured; " +
      "the renders are on disk and readable by artifact ref",
  };
  if (typeof obj.source_artifact_ref === "string") {
    refusal.source_artifact_ref = obj.source_artifact_ref;
  }
  if (Array.isArray(obj.render_artifact_refs)) {
    refusal.render_artifact_refs = obj.render_artifact_refs;
  }
  return refusal;
}

export class ToolProxy {
  constructor(private readonly request: RpcRequest) {}

  /** Validate, dispatch, validate the result, and render Pi tool content. */
  async execute(toolName: string, rawArgs: unknown, ctx: ProxyContext): Promise<ProxyToolResult> {
    const tool = TOOLS[toolName];
    if (!tool) {
      throw new ProxyValidationError("unknown_tool", `no such tool: ${toolName}`);
    }

    // 1. Base shape.
    if (!Value.Check(tool.params, rawArgs)) {
      throw new ProxyValidationError("invalid_arguments", `arguments failed schema for ${toolName}`);
    }
    const args = rawArgs as { [k: string]: JsonValue };

    // 2. Conditionals (if/then/else, allOf, not) that Value.Check ignores.
    if (!checkConditionals(tool.params as unknown as SchemaNode, args)) {
      throw new ProxyValidationError(
        "invalid_arguments",
        `arguments violate a conditional constraint for ${toolName}`,
      );
    }

    // 3. x-hephaestus-maxUtf8Bytes (exact bytes; surrogate/oversize rejection).
    for (const [field, limit] of Object.entries(tool.meta.maxUtf8Fields)) {
      const v = args[field];
      if (typeof v === "string") {
        try {
          enforceMaxUtf8Bytes(v, limit, field);
        } catch (err) {
          if (err instanceof LimitError) throw new ProxyValidationError(err.code, err.message);
          throw err;
        }
      }
    }

    // 3b. VALIDATION.md §3 question shaping: a question raised against ledger
    //     requirement ids is a clarification and must offer 2-4 concrete options
    //     that each state their geometric consequence. A malformed one is
    //     refused HERE — no human is disturbed by "what did you mean?" — as a
    //     discriminated result the model corrects and re-asks.
    if (toolName === "ask_user") {
      const refusal = clarificationRefusal(args);
      if (refusal !== undefined) return this.render(toolName, refusal);
    }

    // 4. Dispatch across the bridge.
    let result: JsonValue;
    try {
      const [method, params, timeoutMs] = this.buildRequest(toolName, args, ctx);
      result = await this.request(method, params, timeoutMs);
    } catch (err) {
      return this.handleRpcError(toolName, err);
    }

    // 5. Result validation (fail closed on malformed payloads).
    if (!Value.Check(tool.result, result)) {
      throw new ProxyResultError(
        "invalid_tool_result",
        `result from ${toolName} failed its result schema`,
      );
    }

    // 6. Capability negotiation: a result whose images the active model cannot
    //    read becomes a discriminated refusal rather than a silently-dropped
    //    payload (digest §1 "capability tests"). The render artifacts are still
    //    named so the operator/model can read them another way.
    const refusal = imageCapabilityRefusal(result, ctx);
    if (refusal !== undefined) return this.render(toolName, refusal);

    // 7. Render.
    return this.render(toolName, result);
  }

  /**
   * The deadline this tool's dispatch is issued with (J-http-limits-8/-11).
   *
   * Three classes, and every one of them reads the shared limits document:
   * the CAD-build class for a tool whose Python side may still be working
   * after the ordinary deadline (see `CAD_BUILD_TOOLS` — the predicate is
   * "its inner ceiling is `cad_build_seconds`", not "it enters the sandboxed
   * executor"), the ordinary tool class for everything else, and — on
   * `ask_user` alone — no timer at all, because the question stays open until
   * a human answers and Python owns that interaction deadline.
   */
  private selectTimeout(toolName: string): number {
    const declared = (TOOLS[toolName]?.meta as { timeoutClass?: string } | undefined)?.timeoutClass;
    if (declared === "cad_build" || (declared === undefined && CAD_BUILD_TOOLS.has(toolName))) {
      return CAD_BUILD_TIMEOUT_MS;
    }
    return TOOL_TIMEOUT_MS;
  }

  private buildRequest(
    toolName: string,
    args: { [k: string]: JsonValue },
    ctx: ProxyContext,
  ): [string, { [k: string]: JsonValue }, number] {
    if (toolName === "delegate_part_agent") {
      const params: { [k: string]: JsonValue } = {
        parent_run_id: ctx.runId,
        part: args.part ?? null,
        prompt: args.prompt ?? null,
        invocation: ctx.invocation as unknown as JsonValue,
      };
      if (args.delivery !== undefined) params.delivery = args.delivery;
      if (args.deadline_seconds !== undefined) params.deadline_seconds = args.deadline_seconds;
      // A synchronous delegation holds this request open for as long as the
      // child runs, so its deadline is the CHILD's plus the documented grace
      // (INTERFACE.md §2.6). Bounded by the peer default it was rejected here
      // long before the child's own deadline could produce a `timed_out`
      // terminal, which is the outcome the state machine is built to give.
      // A `follow_up` delegation returns immediately and takes the ordinary
      // class.
      const deadlineSeconds =
        typeof args.deadline_seconds === "number"
          ? args.deadline_seconds
          : LIMITS.timeouts.delegation.deadline_default_seconds;
      const synchronous = args.delivery === undefined || args.delivery === "prompt";
      return [
        "py.delegate",
        params,
        synchronous ? deadlineSeconds * 1000 + DELEGATION_GRACE_MS : TOOL_TIMEOUT_MS,
      ];
    }
    if (toolName === "ask_user") {
      // `run_id` is the INVOKING run's — `ctx` is per call — and it is load
      // bearing twice over: Python matches the human's answer to the pending
      // question by it, and the sidecar's transport brackets the suspension with
      // `question`/`answer` events on the run this field names (main.ts's
      // `py.ask_user` handler resolves the run from it). A stale or ambient id
      // here would suspend one run and narrate it on another's event sequence.
      const params: { [k: string]: JsonValue } = {
        run_id: ctx.runId,
        question: args.question ?? null,
        options: args.options ?? [],
      };
      if (args.allow_free_text !== undefined) params.allow_free_text = args.allow_free_text;
      if (args.multi !== undefined) params.multi = args.multi;
      // The ledger ids travel with the question so the runtime — not the model —
      // records the answer against them (VALIDATION.md §3).
      if (args.requirement_ids !== undefined) params.requirement_ids = args.requirement_ids;
      // The third timeout class: NONE. A question is open until a human
      // answers it, and Python owns that interaction deadline — a timer here
      // would abandon a turn a person is still reading. `main.ts` re-states the
      // zero on the request it actually issues for the `question`/`answer`
      // bracket; this is the same decision at the layer that chooses classes.
      return ["py.ask_user", params, 0];
    }
    return [
      "py.tool_dispatch",
      {
        session_id: ctx.sessionId,
        run_id: ctx.runId,
        tool: toolName,
        arguments: args,
        invocation: ctx.invocation as unknown as JsonValue,
      },
      this.selectTimeout(toolName),
    ];
  }

  /**
   * Structured capability RPC errors pass through to the model; everything else
   * (transport, busy, internal) rethrows and surfaces as an ordinary tool error.
   */
  private handleRpcError(toolName: string, err: unknown): ProxyToolResult {
    const data = (err as { data?: unknown }).data;
    const code =
      data !== null && typeof data === "object" && typeof (data as SchemaNode).code === "string"
        ? ((data as SchemaNode).code as string)
        : undefined;
    if (code && CAPABILITY_CODES.has(code)) {
      const payload: JsonValue = { status: "capability_error", code };
      return {
        content: [{ type: "text", text: JSON.stringify(payload) }],
        details: { tool: toolName, result: payload, images: 0, capability: code },
      };
    }
    // Structured refusals (scope_denied, invalid_part, already_exists, …) carry a
    // stable machine `reason`. Prefix it onto the thrown message so the model can
    // discriminate on the token instead of parsing prose; the error still fails
    // the call (only capability codes become successful discriminated results).
    const reason =
      data !== null && typeof data === "object" && typeof (data as SchemaNode).reason === "string"
        ? ((data as SchemaNode).reason as string)
        : undefined;
    if (reason !== undefined && err instanceof Error && !err.message.startsWith(reason)) {
      err.message = `${reason}: ${err.message}`;
    }
    throw err;
  }

  private render(toolName: string, result: JsonValue): ProxyToolResult {
    const images: { type: "image"; data: string; mimeType: string }[] = [];
    let renderable: JsonValue = result;
    let capability: string | undefined;

    if (result !== null && typeof result === "object" && !Array.isArray(result)) {
      const obj = result as { [k: string]: JsonValue };
      if (typeof obj.code === "string" && CAPABILITY_CODES.has(obj.code)) {
        capability = obj.code;
      }
      if (Array.isArray(obj.images)) {
        const extracted = this.extractImages(toolName, obj.images);
        images.push(...extracted.images);
        // Strip base64 from the text rendering; keep lightweight descriptors so
        // the model still sees that images were returned (artifact refs remain).
        renderable = { ...obj, images: extracted.descriptors };
      }
    }

    const text = this.renderText(renderable);
    const content: ProxyToolResult["content"] = [{ type: "text", text }, ...images];
    const details: ProxyDetails = capability
      ? { tool: toolName, result, images: images.length, capability }
      : { tool: toolName, result, images: images.length };
    return { content, details };
  }

  private extractImages(
    toolName: string,
    raw: JsonValue[],
  ): {
    images: { type: "image"; data: string; mimeType: string }[];
    descriptors: JsonValue[];
  } {
    if (raw.length > MAX_IMAGES_PER_RESULT) {
      throw new ProxyResultError(
        "too_many_images",
        `${toolName} returned ${raw.length} images (max ${MAX_IMAGES_PER_RESULT})`,
      );
    }
    const images: { type: "image"; data: string; mimeType: string }[] = [];
    const descriptors: JsonValue[] = [];
    let totalBytes = 0;
    for (const entry of raw) {
      if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
        throw new ProxyResultError("invalid_image", `${toolName} image entry is not an object`);
      }
      const img = entry as { [k: string]: JsonValue };
      const data = img.data;
      const mime = (typeof img.mime_type === "string" ? img.mime_type : img.mimeType) ?? null;
      if (typeof data !== "string" || typeof mime !== "string") {
        throw new ProxyResultError("invalid_image", `${toolName} image missing data/mime_type`);
      }
      let buffer: Buffer;
      try {
        buffer = Buffer.from(data, "base64");
      } catch {
        throw new ProxyResultError("invalid_image", `${toolName} image is not valid base64`);
      }
      let dims;
      try {
        dims = parseImageHeader(buffer);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        throw new ProxyResultError("invalid_image", `${toolName} image rejected: ${message}`);
      }
      // J-http-limits-9: the AGGREGATE binary budget, accumulated across the
      // result's images. The per-image cap is checked inside
      // `parseImageHeader`; nothing summed them, so four maximal images passed
      // four per-image checks and no aggregate one.
      totalBytes += buffer.length;
      try {
        enforceBinaryBudget(totalBytes, `${toolName} result`);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        throw new ProxyResultError("binary_too_large", message);
      }
      images.push({ type: "image", data, mimeType: mime });
      descriptors.push({
        mime_type: mime,
        bytes: buffer.length,
        width: dims.width,
        height: dims.height,
      });
    }
    return { images, descriptors };
  }

  /** Render a JSON result to text under the §5 dual cap (bytes AND lines). */
  private renderText(value: JsonValue): string {
    const maxBytes = LIMITS.text_result.max_bytes;
    const maxLines = LIMITS.text_result.max_lines;
    let text = JSON.stringify(value);
    const marker = "\n[truncated: result exceeded text budget]";

    const lines = text.split("\n");
    if (lines.length > maxLines) {
      text = lines.slice(0, maxLines).join("\n") + marker;
    }
    if (Buffer.byteLength(text, "utf8") > maxBytes) {
      // Trim to a byte budget that leaves room for the explicit marker.
      const room = Math.max(0, maxBytes - Buffer.byteLength(marker, "utf8"));
      const buf = Buffer.from(text, "utf8").subarray(0, room);
      // Avoid splitting a multi-byte code point at the boundary.
      text = new TextDecoder("utf-8").decode(buf) + marker;
    }
    return text;
  }
}
