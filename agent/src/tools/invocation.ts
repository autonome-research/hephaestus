// Trusted invocation identity for mutation idempotency (architecture §4.1, digest §1).
//
// The mutation idempotency key is derived from four trusted, non-model-visible
// facts: the session UUID, the persisted assistant-message entry ID, the
// tool-call ordinal within that entry, and the provider tool-call ID. The key
// MUST stay unique when a provider reuses a call ID (e.g. `call_0`) across
// distinct persisted assistant entries — an explicit G2 fixture — and MUST stay
// STABLE for the same logical call so a lost-response retry reconciles to the
// same opstore opkey rather than duplicating work.
//
// The key lives only in the trusted `invocation` bridge metadata; it is never
// placed into model-visible tool arguments.

/** The four trusted facts that identify a single tool-call attempt. */
export interface InvocationParts {
  /** Pi session UUID (the persistent per-part / orchestrator session). */
  readonly sessionId: string;
  /** Persisted assistant-message entry ID that carried this tool call. */
  readonly entryId: string;
  /** Zero-based tool-call ordinal within the assistant entry. */
  readonly ordinal: number;
  /** Provider-assigned tool-call ID (may repeat across entries, e.g. `call_0`). */
  readonly providerCallId: string;
}

/**
 * Wire-facing trusted invocation metadata (snake_case for the Python bridge).
 * Carries the derived `invocation_id` plus its four components so the Python
 * dispatcher can re-derive / audit the key.
 */
export interface TrustedInvocation {
  readonly invocation_id: string;
  readonly session_id: string;
  readonly entry_id: string;
  readonly ordinal: number;
  readonly provider_call_id: string;
}

// Length-prefixed, self-delimiting segment encoding. Because each segment is
// written as `<utf8ByteLength>:<value>`, the concatenation is injective for any
// segment contents (a value may itself contain ':' or '|' without ambiguity),
// so distinct (session, entry, ordinal, providerCall) tuples never collide and
// identical tuples always produce the identical id.
function seg(value: string): string {
  return `${Buffer.byteLength(value, "utf8")}:${value}`;
}

/**
 * Deterministic, injective idempotency key for a tool-call attempt.
 * Stable across retries of the same logical call; distinct for every distinct
 * (sessionId, entryId, ordinal, providerCallId) tuple.
 */
export function buildInvocationId(parts: InvocationParts): string {
  return (
    "inv1:" +
    seg(parts.sessionId) +
    seg(parts.entryId) +
    seg(String(parts.ordinal)) +
    seg(parts.providerCallId)
  );
}

/** Build the wire-facing trusted invocation metadata for a tool-call attempt. */
export function makeInvocation(parts: InvocationParts): TrustedInvocation {
  return {
    invocation_id: buildInvocationId(parts),
    session_id: parts.sessionId,
    entry_id: parts.entryId,
    ordinal: parts.ordinal,
    provider_call_id: parts.providerCallId,
  };
}

/**
 * Tracks issued invocations within a process so uniqueness is observable and
 * retries are idempotent. Registering the same tuple twice returns the same
 * invocation (a lost-response retry); registering a colliding id from a
 * different tuple is impossible by construction and surfaces as an error.
 */
export class InvocationTracker {
  private readonly byId = new Map<string, TrustedInvocation>();

  /** Register (or re-register) an attempt; idempotent on the same tuple. */
  register(parts: InvocationParts): TrustedInvocation {
    const inv = makeInvocation(parts);
    const existing = this.byId.get(inv.invocation_id);
    if (existing) {
      if (
        existing.session_id !== inv.session_id ||
        existing.entry_id !== inv.entry_id ||
        existing.ordinal !== inv.ordinal ||
        existing.provider_call_id !== inv.provider_call_id
      ) {
        throw new Error(`invocation id collision for ${inv.invocation_id}`);
      }
      return existing;
    }
    this.byId.set(inv.invocation_id, inv);
    return inv;
  }

  has(invocationId: string): boolean {
    return this.byId.has(invocationId);
  }

  get size(): number {
    return this.byId.size;
  }
}
