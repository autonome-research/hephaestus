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
// This module is pure policy: it decides WHAT should happen from usage numbers
// and inspect history. The manager/event pump performs the side effects
// (session.compact, py.ask_user, transcript rewrite).

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
