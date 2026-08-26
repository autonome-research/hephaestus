// Transient-fault retry for errored assistant turns (EXTERNAL_EVAL.md §5).
//
// An assistant turn that errors (Pi stopReason "error") is a FAILED run — the
// loud-failure rule main.ts documents. But two archived CADGenBench runs
// (bench/results/gpt-5.6-sol/2026-08-02, tasks 214/218) died on exactly one
// transient provider fault each ("WebSocket error", diagnostics type
// provider_transport_failure) with correct geometry already built. A single
// transient network blip should not discard a run's worth of good work, and a
// harness fault is never the model's failure to pay for (§5: harness faults
// are not charged).
//
// So: on an errored assistant turn whose error message matches a NAMED
// transient class, the run gets exactly ONE automatic retry — the session is
// re-prompted with a continuation prompt, and an audit event
// (kind "audit", event "turn_retry") records the fault in the archive. The
// retry turn's tool calls are charged normally (the model is working); only
// the fault itself is uncharged. A second errored turn — or a first whose
// error is not a named transient class — fails the run exactly as before.

/** The continuation prompt the single automatic retry re-prompts with. */
export const RETRY_CONTINUATION_PROMPT =
  "Your previous turn failed with a transient provider error; continue.";

interface TransientErrorClass {
  readonly name: string;
  readonly pattern: RegExp;
}

/**
 * The named transient classes, calibrated from the archived faults (the
 * 2026-08-02 pair was "WebSocket error") plus the transport/availability
 * shapes the provider SDKs surface. Anything else — auth failures, content
 * filters, invalid requests — is NOT transient and never retried.
 */
const TRANSIENT_ERROR_CLASSES: readonly TransientErrorClass[] = [
  { name: "websocket", pattern: /websocket/i },
  {
    name: "connection",
    pattern:
      /(connection\s+(reset|refused|closed|error)|ECONNRESET|ECONNREFUSED|EPIPE|socket hang up|fetch failed|network[_\s]?error|premature close|terminated)/i,
  },
  { name: "timeout", pattern: /(timed?\s?out|ETIMEDOUT|deadline exceeded)/i },
  {
    name: "provider_unavailable",
    pattern:
      /(\b(500|502|503|504|529)\b|overloaded|rate.?limit|too many requests|internal server error|bad gateway|service unavailable|server error)/i,
  },
];

/**
 * The name of the transient class an errored turn's message belongs to, or
 * undefined when the error is not transient (and must not be retried).
 */
export function transientErrorClass(message: string): string | undefined {
  for (const cls of TRANSIENT_ERROR_CLASSES) {
    if (cls.pattern.test(message)) return cls.name;
  }
  return undefined;
}

/**
 * The errored-turn signal from a raw Pi session event, or undefined. Pi does
 * not reject `session.prompt` on a provider/auth/stream failure — it records
 * stopReason "error" on the persisted assistant message and resolves — so the
 * watcher reads it off the event stream (see main.ts).
 */
export function turnErrorOf(ev: unknown): string | undefined {
  const raw = ev as {
    type?: string;
    message?: { role?: string; stopReason?: string; errorMessage?: string };
  };
  if (
    raw.type === "message_end" &&
    raw.message?.role === "assistant" &&
    raw.message.stopReason === "error"
  ) {
    return raw.message.errorMessage ?? "assistant turn failed (no error message)";
  }
  return undefined;
}

export interface PromptRunDeps {
  /** Run one assistant turn (`managed.session.prompt`). */
  readonly prompt: (text: string) => Promise<void>;
  /** Read-and-clear the errored-turn message the event watcher captured. */
  readonly takeTurnError: () => string | undefined;
  /** Whether the run's abort controller fired (cancellation wins). */
  readonly aborted: () => boolean;
  /** Record the audit event for the one retry (never called twice). */
  readonly onRetry: (errorMessage: string, transientClass: string) => void;
}

export interface PromptRunOutcome {
  readonly state: "completed" | "cancelled" | "failed";
  readonly errorMessage?: string;
}

/**
 * Run the prompt with at most ONE automatic retry for a named transient
 * provider fault. A second errored turn fails the run with the second turn's
 * message; a non-transient error fails immediately, exactly as before the
 * retry existed.
 */
export async function promptWithTransientRetry(
  promptText: string,
  deps: PromptRunDeps,
): Promise<PromptRunOutcome> {
  await deps.prompt(promptText);
  if (deps.aborted()) return { state: "cancelled" };
  let turnError = deps.takeTurnError();
  if (turnError !== undefined) {
    const transient = transientErrorClass(turnError);
    if (transient !== undefined) {
      deps.onRetry(turnError, transient);
      await deps.prompt(RETRY_CONTINUATION_PROMPT);
      if (deps.aborted()) return { state: "cancelled" };
      turnError = deps.takeTurnError();
    }
  }
  if (turnError !== undefined) return { state: "failed", errorMessage: turnError };
  return { state: "completed" };
}
