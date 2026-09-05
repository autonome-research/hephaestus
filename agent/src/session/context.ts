// Context policy: image eviction, compaction trigger, budget escalation.
//
// STAGE2_DIGEST §1 (context policy — exact numbers):
//  - Image eviction K=3: keep image blocks only for the most recent 3
//    inspect_part results; evicted images become a text stub of the exact form
//    `[render: <name> <view>/<channel>, superseded — re-run inspect_part to view]`.
//    The immutable render artifact stays on disk.
//  - Compaction trigger T=70% of the context window: request Pi compaction with
//    a CAD-aware pinned summary (design intent, decisions, open problems, current
//    params, check status).
//  - Budget escalation at 90%: raise an ask_user escalation.
//
// This module decides WHAT should happen from usage numbers, inspect history
// and the session's own recorded entries. The manager/event pump performs the
// side effects (session.compact, py.ask_user, transcript rewrite); nothing here
// calls the bridge, and the pinned summary in particular is derived from the
// transcript the sidecar already owns rather than from a new wire method.

import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
  readSessionActivity,
  type RecordedActivity,
  type RecordedToolCall,
} from "./history.js";

export const IMAGE_EVICTION_K = 3;
export const COMPACTION_TRIGGER_FRACTION = 0.7;
export const BUDGET_ESCALATION_FRACTION = 0.9;

// ── image eviction ───────────────────────────────────────────────────────────

export interface RenderRef {
  readonly name: string;
  readonly view: string;
  readonly channel: string;
}

/** One inspect_part result: a tool call whose output holds render image blocks. */
export interface InspectResult {
  readonly toolCallId: string;
  readonly renders: readonly RenderRef[];
}

export interface EvictedRender {
  readonly toolCallId: string;
  readonly ref: RenderRef;
  readonly stub: string;
}

/** The exact stub text that replaces an evicted render image in model context. */
export function renderStub(ref: RenderRef): string {
  return `[render: ${ref.name} ${ref.view}/${ref.channel}, superseded — re-run inspect_part to view]`;
}

/**
 * Keeps image blocks for only the most recent K=3 inspect_part results. Recording
 * a 4th distinct result evicts the oldest and returns a stub for each of its
 * renders; the caller swaps those image blocks for the stubs in the transcript.
 */
export class ImageEvictionTracker {
  private readonly recent: InspectResult[] = [];

  constructor(private readonly k: number = IMAGE_EVICTION_K) {
    if (k < 1) throw new Error("image eviction K must be >= 1");
  }

  /** Record an inspect result; return stubs for any result evicted past K. */
  record(result: InspectResult): EvictedRender[] {
    this.recent.push(result);
    const evicted: EvictedRender[] = [];
    while (this.recent.length > this.k) {
      const dropped = this.recent.shift();
      if (dropped === undefined) break;
      for (const ref of dropped.renders) {
        evicted.push({ toolCallId: dropped.toolCallId, ref, stub: renderStub(ref) });
      }
    }
    return evicted;
  }

  /** Tool-call IDs whose images are still live in context (most recent K). */
  liveToolCallIds(): string[] {
    return this.recent.map((r) => r.toolCallId);
  }

  get size(): number {
    return this.recent.length;
  }
}

// ── pinned CAD summary ───────────────────────────────────────────────────────

export interface PinnedCadSummary {
  readonly designIntent: string;
  readonly decisions: readonly string[];
  readonly openProblems: readonly string[];
  readonly params: Readonly<Record<string, number | null>>;
  readonly checkStatus: string;
}

export const PINNED_SUMMARY_OPEN = "<<HEPHAESTUS_PINNED_SUMMARY>>";
export const PINNED_SUMMARY_CLOSE = "<</HEPHAESTUS_PINNED_SUMMARY>>";

/**
 * Render the pinned summary handed to Pi compaction as its instruction. The
 * delimiters make it recoverable in the post-compaction transcript (the G2 test
 * checks a pre-compaction decision survives).
 */
export function formatPinnedSummary(summary: PinnedCadSummary): string {
  const decisions = summary.decisions.length > 0 ? summary.decisions.map((d) => `- ${d}`).join("\n") : "- (none)";
  const problems = summary.openProblems.length > 0 ? summary.openProblems.map((p) => `- ${p}`).join("\n") : "- (none)";
  const params = Object.keys(summary.params).length > 0
    ? Object.entries(summary.params).map(([k, v]) => `${k}=${v === null ? "null" : v}`).join(", ")
    : "(none)";
  return [
    PINNED_SUMMARY_OPEN,
    `Design intent: ${summary.designIntent}`,
    "Decisions:",
    decisions,
    "Open problems:",
    problems,
    `Current params: ${params}`,
    `Check status: ${summary.checkStatus}`,
    PINNED_SUMMARY_CLOSE,
  ].join("\n");
}

// ── the pinned summary's producer ────────────────────────────────────────────
//
// STAGE2_DIGEST §1 and architecture.md §4.4 require the compaction request to
// carry a CAD-AWARE summary: design intent, decisions, open problems, current
// params and check status. The type, the formatter and the policy's
// summary-supplier seam were built for it; the producer never was, so until
// audit-2026-09-04 B-12 every field arrived empty and the one artifact designed
// to survive compaction survived carrying nothing.
//
// EVERY INPUT IS ALREADY IN THE TRANSCRIPT. The session's own recorded entries
// hold the operator's first prompt, every answered question, and the newest
// `set_params`/`build_part`/`run_checks`/requirement result — so this is derived
// from `session/history.ts`'s readers and needs NO bridge call and NO new wire
// method. Reaching for Python here would extend the wire vocabulary for data the
// sidecar already owns.
//
// DETERMINISTIC BY CONSTRUCTION: no timestamps, no map-iteration order (every
// map is walked over sorted keys), so the same entries always render the same
// block — which is what makes the summary restart-stable for the same reason a
// history cursor is.

/**
 * Identity of the session being summarized.
 *
 * Structural rather than `ManagedSession` so this module keeps its policy-only
 * dependency surface — a `ManagedSession` satisfies it, and nothing here can
 * reach the live Pi session even by accident.
 */
export interface SummarySession {
  readonly id: string;
  readonly profile: string;
}

/**
 * Maximum items rendered in the `decisions` and `open problems` lists.
 *
 * The block is PREPENDED to a compaction request, so it competes for the very
 * context the compaction is reclaiming. Every cap is exported so tests read the
 * number rather than duplicating it.
 */
export const MAX_SUMMARY_ITEMS = 8;

/** Maximum UTF-8 bytes of any one rendered string (a sentence budget). */
export const MAX_SUMMARY_ITEM_BYTES = 240;

/** Maximum UTF-8 bytes of the whole formatted block, delimiters included. */
export const MAX_SUMMARY_BYTES = 4096;

/** Collapse whitespace and clamp to a UTF-8 byte budget. */
function clamp(text: string, maxBytes: number = MAX_SUMMARY_ITEM_BYTES): string {
  // Newlines would break `formatPinnedSummary`'s one-item-per-line lists, so a
  // rendered item is always a single line.
  const flat = text.replace(/\s+/g, " ").trim();
  if (Buffer.byteLength(flat, "utf8") <= maxBytes) return flat;
  const ellipsis = "…";
  const room = Math.max(0, maxBytes - Buffer.byteLength(ellipsis, "utf8"));
  let decoded = new TextDecoder("utf-8").decode(Buffer.from(flat, "utf8").subarray(0, room));
  // A cut through a multi-byte code point decodes to U+FFFD; drop it rather
  // than hand the model a replacement character.
  if (decoded.endsWith("\uFFFD")) decoded = decoded.slice(0, -1);
  return decoded + ellipsis;
}

function parsed(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    // A result whose text was truncated at the §5 budget (`tools/proxy.ts`) is
    // not JSON any more. It contributes nothing rather than failing the summary.
    return null;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function asStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const out: string[] = [];
  for (const item of value as unknown[]) {
    if (typeof item === "string" && item.trim() !== "") out.push(item);
  }
  return out;
}

/**
 * A parameter map projected onto the summary's `number | null`.
 *
 * Sorted, because `formatPinnedSummary` renders insertion order and a summary
 * that reorders itself between two identical transcripts is not restart-stable.
 * A non-numeric value becomes `null` (rendered `name=null`): every declared
 * parameter is numeric (`core/params.py`), so anything else is unknown, and
 * unknown is a claim the block is allowed to make where a guess is not.
 */
function numberMap(source: Record<string, unknown>): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const key of Object.keys(source).sort()) {
    const value = source[key];
    out[key] = typeof value === "number" && Number.isFinite(value) ? value : null;
  }
  return out;
}

/** The newest check run, projected onto pass/fail. */
interface CheckSnapshot {
  readonly status: string;
  readonly total: number;
  readonly failing: readonly string[];
}

function checkSnapshot(payload: Record<string, unknown>): CheckSnapshot {
  const status = typeof payload.status === "string" ? payload.status : "unknown";
  const checks = asRecord(payload.checks);
  const failing: string[] = [];
  let total = 0;
  if (checks !== null) {
    for (const name of Object.keys(checks).sort()) {
      total += 1;
      // The canonical payload is one `{"pass", "measured"}` record per check
      // (core `CheckResult.to_json`). Anything that is not an explicit `true`
      // fails closed — the same reading `workflows/cad_workflow.ts` applies.
      const entry = asRecord(checks[name]);
      if (entry === null || entry.pass !== true) failing.push(name);
    }
  }
  return { status, total, failing };
}

function renderCheckStatus(snapshot: CheckSnapshot | null): string {
  // "unknown" is the honest word for a session that has not run checks, and it
  // is what a fresh session rendered before this producer existed.
  if (snapshot === null) return "unknown";
  // A run that reported per-check verdicts reported EVIDENCE, and the tally is
  // that evidence — a part-scope run whose `status` is "error" is one whose
  // build failed, and such a run carries no verdicts at all (worker.py writes
  // `checks: {}`), so this branch never overstates a degraded run.
  if (snapshot.total === 0) {
    return snapshot.status === "ok" ? "no checks" : `unavailable (${snapshot.status})`;
  }
  const passing = snapshot.total - snapshot.failing.length;
  if (snapshot.failing.length === 0) return `${passing} passing`;
  const named = snapshot.failing.slice(0, MAX_SUMMARY_ITEMS).join(", ");
  return `${passing} passing, ${snapshot.failing.length} failing (${named})`;
}

/** One operator answer, rendered from the label the server sent. */
function renderSelection(value: unknown): string | null {
  if (typeof value === "string") return value.trim() === "" ? null : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = (value as unknown[])
      .map(renderSelection)
      .filter((part): part is string => part !== null);
    return parts.length === 0 ? null : parts.join(", ");
  }
  return null;
}

function buildFailure(
  call: RecordedToolCall | undefined,
  payload: Record<string, unknown> | null,
  text: string,
): string {
  const part = (call === undefined ? null : asText(call.arguments.name)) ?? "part";
  // A failed call with no JSON envelope — a thrown `execute`, or a result
  // truncated at the §5 text budget — still has a reason, and §B-12 asks for
  // "the reason or failing line of the newest failed build". Its own words are
  // the best reason available, so they are what the block carries.
  if (payload === null) return clamp(`build ${part} failed: ${text}`);
  // The canonical §8 error record: line/col/type/message/… (`core/types.py`).
  const error = asRecord(payload.error);
  const line = error !== null && typeof error.line === "number" ? error.line : null;
  const why = (error === null ? [] : [asText(error.type), asText(error.message)])
    .filter((piece): piece is string => piece !== null)
    .join(": ");
  const where = line === null ? "" : ` at line ${line}`;
  return clamp(`build ${part} failed${where}${why === "" ? "" : `: ${why}`}`);
}

/** Requirement entries that carry a recorded resolution (VALIDATION.md §3). */
function requirementResolutions(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const out: string[] = [];
  for (const item of value as unknown[]) {
    const entry = asRecord(item);
    if (entry === null) continue;
    const id = asText(entry.id);
    const resolution = asText(entry.resolution);
    if (id === null || resolution === null) continue;
    out.push(clamp(`${id} resolved: ${resolution}`));
  }
  return out;
}

/** Keep the first occurrence of each item, in the order given. */
function unique(items: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    if (seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

/**
 * Shrink a summary until its formatted block fits the byte budget.
 *
 * The lists are already newest-first, so dropping from the tail drops the
 * OLDEST claim — a block that has to shed content sheds the least recent one.
 * Parameters go last and always leave one behind, because the block is more
 * useful naming some current state than none. Shrinking never touches the
 * formatter, so the delimiters the post-compaction assertions read stay intact.
 */
function fit(summary: PinnedCadSummary): PinnedCadSummary {
  const decisions = [...summary.decisions];
  const openProblems = [...summary.openProblems];
  const keys = Object.keys(summary.params);
  let current = summary;
  while (Buffer.byteLength(formatPinnedSummary(current), "utf8") > MAX_SUMMARY_BYTES) {
    if (decisions.length > 1) decisions.pop();
    else if (openProblems.length > 1) openProblems.pop();
    else if (keys.length > 1) keys.pop();
    else break;
    const params: Record<string, number | null> = {};
    for (const key of keys) params[key] = summary.params[key] ?? null;
    current = {
      designIntent: summary.designIntent,
      decisions: [...decisions],
      openProblems: [...openProblems],
      params,
      checkStatus: summary.checkStatus,
    };
  }
  return current;
}

/**
 * The pinned CAD summary of one session, derived from its recorded entries.
 *
 * `entries` is the session's own transcript (`sessionManager.getEntries()`).
 * With none — a fresh session, or an unreadable entry list — the result is
 * byte-identical to the stub this replaced, so nothing regresses on day one.
 *
 * Never throws. A compaction must not fail over the bookkeeping about it, the
 * same posture the turn marker takes (`main.ts`, INTERFACE.md §2.8(3)).
 */
export function summarize(
  entries: readonly SessionEntry[],
  session: SummarySession,
): PinnedCadSummary {
  const fallback: PinnedCadSummary = {
    designIntent: `session ${session.id} (${session.profile})`,
    decisions: [],
    openProblems: [],
    params: {},
    checkStatus: "unknown",
  };
  try {
    return fit(derive(readSessionActivity(entries), fallback));
  } catch {
    return fallback;
  }
}

function derive(activity: RecordedActivity, fallback: PinnedCadSummary): PinnedCadSummary {
  const calls = new Map<string, RecordedToolCall>();
  for (const call of activity.toolCalls) calls.set(call.toolCallId, call);

  // Chronological while collecting; reversed to newest-first when rendered.
  const answers: string[] = [];
  let resolutions: string[] = [];
  let setParams: Record<string, number | null> | null = null;
  let builtParams: Record<string, number | null> | null = null;
  let checks: CheckSnapshot | null = null;
  let unresolved: string[] = [];
  const failedBuilds = new Map<string, string>();

  for (const result of activity.toolResults) {
    const payload = asRecord(parsed(result.text));
    const call = calls.get(result.toolCallId);
    if (result.toolName === "build_part") {
      const part = (call === undefined ? null : asText(call.arguments.name)) ?? "part";
      const failed = payload === null ? result.isError === true : payload.status === "error";
      if (failed) {
        failedBuilds.set(part, buildFailure(call, payload, result.text));
      } else if (payload !== null && payload.status === "ok") {
        // A later good build of ONE part clears that part's failure and no
        // other's, which is why the failures are keyed by part at all.
        failedBuilds.delete(part);
      }
      if (payload !== null) {
        const effective = asRecord(payload.effective_params);
        if (effective !== null) builtParams = numberMap(effective);
        const material = asStringList(payload.unresolved_material);
        if (material !== null) unresolved = material;
      }
      continue;
    }
    if (payload === null) continue;
    switch (result.toolName) {
      case "ask_user": {
        // A refused question (`clarification_question_shape`) is not an answer.
        if (payload.status === "invalid_question" || call === undefined) break;
        const question = asText(call.arguments.question);
        const selection = renderSelection(payload.selection);
        if (question !== null && selection !== null) {
          answers.push(clamp(`${question} → ${selection}`));
        }
        break;
      }
      case "set_params": {
        const effective = asRecord(payload.effective);
        if (effective !== null) setParams = numberMap(effective);
        break;
      }
      case "run_checks": {
        checks = checkSnapshot(payload);
        break;
      }
      case "record_requirements":
      case "update_requirement": {
        // Both return the WHOLE ledger, so the newest result is the current
        // state of every requirement rather than a delta to be accumulated.
        const material = asStringList(payload.unresolved_material);
        if (material !== null) unresolved = material;
        const resolved = requirementResolutions(payload.entries);
        if (resolved !== null) resolutions = resolved;
        break;
      }
      default:
        break;
    }
  }

  // The operator's own first sentence — the prompt extractor already isolates
  // it from §7A.3's workspace-context envelope, which is what the turn marker
  // was added for. The sidecar's own retry continuation (`origin: "agent"`) is
  // not the operator speaking and can never be the design intent.
  const opening = activity.prompts.find(
    (prompt) => prompt.origin !== "agent" && prompt.text !== null,
  );
  const designIntent =
    opening?.text != null ? clamp(opening.text) : fallback.designIntent;

  // Newest first: under the item cap and the byte budget the TAIL is what gets
  // dropped, so the most recent decision has to be the one that survives.
  // Reversing the concatenation puts the answered questions newest-first ahead
  // of the ledger's recorded resolutions, which is the right precedence: an
  // answer is a decision the operator made in this session, a resolution is the
  // durable record of one and is a `read_requirements` call away.
  const decisions = unique([...resolutions, ...answers].reverse()).slice(0, MAX_SUMMARY_ITEMS);

  const problems = unique([
    ...(checks?.failing ?? []).map((name) => clamp(`check ${name} is failing`)),
    ...failedBuilds.values(),
    ...unresolved.map((id) => clamp(`unresolved requirement ${id}`)),
  ]).slice(0, MAX_SUMMARY_ITEMS);

  return {
    designIntent,
    decisions,
    openProblems: problems,
    // The newest `set_params` wins even over a LATER build, and deliberately:
    // `set_params` is the durable parameter store, while a build's effective
    // map folds in that call's transient overrides, which were never persisted
    // and are not "current params". The build map is the fallback for a session
    // that has only ever built.
    params: setParams ?? builtParams ?? {},
    checkStatus: renderCheckStatus(checks),
  };
}

// ── usage-driven policy ──────────────────────────────────────────────────────

export type ContextAction =
  | { readonly kind: "compact"; readonly instructions: string }
  | { readonly kind: "escalate"; readonly reason: "budget"; readonly percent: number };

export interface ContextPolicyOptions {
  /** Supplies the current pinned CAD summary at compaction time. */
  readonly summary: () => PinnedCadSummary;
  readonly compactionFraction?: number;
  readonly escalationFraction?: number;
}

/**
 * Latching policy over fractional context usage. Emits a `compact` action the
 * first time usage crosses T=70% and an `escalate` action the first time it
 * crosses 90%. Latches prevent repeated firing until `reset()` (called after a
 * successful compaction shrinks the window).
 */
export class ContextPolicy {
  private compacted = false;
  private escalated = false;
  private readonly compactionFraction: number;
  private readonly escalationFraction: number;

  constructor(private readonly opts: ContextPolicyOptions) {
    this.compactionFraction = opts.compactionFraction ?? COMPACTION_TRIGGER_FRACTION;
    this.escalationFraction = opts.escalationFraction ?? BUDGET_ESCALATION_FRACTION;
  }

  /**
   * Evaluate a usage fraction in [0,1] (or null when unknown, e.g. right after
   * compaction). Returns the actions to perform now, in order.
   */
  evaluate(fraction: number | null): ContextAction[] {
    if (fraction === null) return [];
    const actions: ContextAction[] = [];
    if (fraction >= this.compactionFraction && !this.compacted) {
      this.compacted = true;
      actions.push({ kind: "compact", instructions: formatPinnedSummary(this.opts.summary()) });
    }
    if (fraction >= this.escalationFraction && !this.escalated) {
      this.escalated = true;
      actions.push({ kind: "escalate", reason: "budget", percent: fraction });
    }
    return actions;
  }

  /** Clear the compaction latch after context has been reclaimed. */
  reset(): void {
    this.compacted = false;
  }

  /** Clear the budget-escalation latch (e.g. after the user raises the budget). */
  clearEscalation(): void {
    this.escalated = false;
  }
}
