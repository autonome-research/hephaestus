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
  LIMITS,
  MAX_IMAGES_PER_RESULT,
  enforceMaxUtf8Bytes,
  parseImageHeader,
  LimitError,
} from "../limits.js";
import { TOOLS } from "./schema.gen.js";
import type { TrustedInvocation } from "./invocation.js";

/** Minimal bridge request surface (RpcPeer.request); rejects with RpcError. */
export type RpcRequest = (
  method: string,
  params: { [k: string]: JsonValue },
) => Promise<JsonValue>;

/** Per-call trusted context supplied by the session layer. */
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

    // 4. Dispatch across the bridge.
    let result: JsonValue;
    try {
      result = await this.request(...this.buildRequest(toolName, args, ctx));
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

  private buildRequest(
    toolName: string,
    args: { [k: string]: JsonValue },
    ctx: ProxyContext,
  ): [string, { [k: string]: JsonValue }] {
    if (toolName === "delegate_part_agent") {
      const params: { [k: string]: JsonValue } = {
        parent_run_id: ctx.runId,
        part: args.part ?? null,
        prompt: args.prompt ?? null,
        invocation: ctx.invocation as unknown as JsonValue,
      };
      if (args.delivery !== undefined) params.delivery = args.delivery;
      if (args.deadline_seconds !== undefined) params.deadline_seconds = args.deadline_seconds;
      return ["py.delegate", params];
    }
    if (toolName === "ask_user") {
      const params: { [k: string]: JsonValue } = {
        run_id: ctx.runId,
        question: args.question ?? null,
        options: args.options ?? [],
      };
      if (args.allow_free_text !== undefined) params.allow_free_text = args.allow_free_text;
      if (args.multi !== undefined) params.multi = args.multi;
      return ["py.ask_user", params];
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
