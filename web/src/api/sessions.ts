// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The three session reads — the list, the thread, the paged history — and the
// one session **write** this build makes (INTERFACE.md §2.3, §2.8, §8, §7A.7).
//
// Read types, transcribed from `http/sessions.py` and
// `agent_bridge/session_edges.py`. Three properties of these routes are
// load-bearing and are stated here so a caller cannot forget them:
//
// * `GET /sessions` lists only the sessions **this runtime owns** — the ones
//   whose `.heph/locks/` leases it holds. A persisted Pi JSONL nobody has opened
//   is not listed, because finding one would mean parsing Pi's format outside
//   the sidecar. §7.1's "attach" affordance lists live sessions, exactly that.
// * `GET /sessions/{id}/history` takes a cursor and **no page size** (§2.8): the
//   cursor is opaque, forwarded and returned unmodified, and page 1 freezes a
//   high-water mark. Rewriting it — or asking for a different size — would break
//   both restart-stability and the frozen mark.
// * `GET /sessions/{id}/thread` returns the subtree rooted at `id` and carries
//   the root's own `parent_session_id` so a client handed a child id can walk
//   *up*. `loadThreadTree` is that walk; the client never infers an edge.
//
// `GET /sessions`, history and prompt refuse `503 agent_unavailable` with no
// agent runtime attached; `…/thread` deliberately does not, because threading is
// durable in `state.db` and readable long after the process that wrote it.
//
// **The write is `answerQuestion` (§7A.7, §19.18), and it carries no
// idempotency key on purpose.** `POST /sessions/{id}/answer` is idempotent on
// the **question id** — `PendingQuestions` records the first answer and tells
// every later one that it lost — and §2.5's header ladder over the top of that
// would be a second idempotency mechanism over a stronger existing one, which
// mission rule 6 forbids. `http/app.py::post_session_answer` says the same in
// its own comment; this is the client half of that decision.

import { apiJson } from "./client";
import type { HistoryEventFrame } from "./events";

/** §2.4's two refusal reasons a session route now names (2026-09-03). */
export const UNREADABLE_REASONS = ["unknown_session", "agent_unavailable"] as const;
export type UnreadableReason = (typeof UNREADABLE_REASONS)[number];

/** `agent_bridge/app.py::sessions` + the two fields `list_sessions` joins on. */
export interface SessionRow {
  readonly session_id: string;
  readonly profile: string;
  readonly part: string | null;
  /** From `tp_session_edges`; `null` when this session has no recorded parent. */
  readonly parent_session_id: string | null;
  readonly thread_state: ThreadState;
  /**
   * §2.3 (2026-09-03, additive): `true` means NOT KNOWN TO BE UNREADABLE — the
   * listing never probes, so this is a cache of a past failure, not a live
   * fact. `undefined` from an older server, which never marks a row; treat
   * that the same as `true`.
   */
  readonly readable?: boolean;
  /** Non-null exactly when `readable` is `false`; the same string §2.4 refuses by. */
  readonly unreadable_reason?: UnreadableReason | null;
}

/**
 * One row of `GET /sessions`'s `profiles` — the §7A.2 **server projection**.
 *
 * "The profile is never chosen silently. The create affordance shows the
 * profile it will use and what that profile can do, in one line, **from a
 * server projection** — not from a client-side copy of the table above. A user
 * who does not know their session cannot delegate reads `scope_denied` as a
 * broken product."
 *
 * So these booleans are read off `agent_bridge/sessions.py::_SPECS`, the same
 * table `ToolDispatcher._authorize` enforces. What this client owns is the
 * *sentence* (`copy.composer.profileWhat`), because house style keeps every
 * workspace string in one file; what it does **not** own — and what §7A.2
 * forbids it owning — is the table of which profile can delegate.
 */
export interface ProfileCapability {
  readonly profile: SessionProfile;
  readonly can_delegate: boolean;
  readonly part_scoped: boolean;
  readonly requires_part: boolean;
}

export interface SessionsDocument {
  readonly status: "ok";
  readonly sessions: readonly SessionRow[];
  /** The creatable profiles and what each can do (§7A.2). */
  readonly profiles: readonly ProfileCapability[];
}

/** `SESSION_PROFILES` (`http/sessions.py`), closed at three. */
export const SESSION_PROFILES = ["orchestrator", "part", "quick_edit"] as const;
export type SessionProfile = (typeof SESSION_PROFILES)[number];

/** `THREAD_LINKED` / `THREAD_UNLINKED` — a closed pair (`session_edges.py`). */
export const THREAD_STATES = ["linked", "unlinked"] as const;
export type ThreadState = (typeof THREAD_STATES)[number];

/** `EDGE_KINDS` (`session_edges.py`), closed at two. `null` at a tree root. */
export const EDGE_KINDS = ["quick_edit", "delegation"] as const;
export type EdgeKind = (typeof EDGE_KINDS)[number];

/** One `ThreadNode.as_dict()`. */
export interface ThreadNode {
  readonly session_id: string;
  readonly parent_session_id: string | null;
  readonly kind: string | null;
  readonly origin: Readonly<Record<string, unknown>>;
  readonly created_at: number | null;
  readonly depth: number;
}

/** `GET /sessions/{id}/thread` — `thread_projection`. */
export interface ThreadDocument {
  readonly status: "ok";
  readonly session_id: string;
  readonly thread_state: ThreadState;
  readonly parent_session_id: string | null;
  readonly nodes: readonly ThreadNode[];
}

/**
 * `GET /sessions/{id}/history` — `history.page` passthrough.
 *
 * `cursor` is `null` exactly when `done` is true; both are the sidecar's own
 * fields (`agent/src/session/history.ts::HistoryPage`) and neither is rewritten
 * anywhere between there and here.
 */
/** §2.8's closed `outcome.state` vocabulary for a non-`stop` turn. */
export const TURN_OUTCOME_STATES = ["cancelled", "error", "interrupted"] as const;
export type TurnOutcomeState = (typeof TURN_OUTCOME_STATES)[number];

/** §2.8(4): present for a turn that did not complete; absent means completed. */
export interface TurnOutcome {
  readonly state: TurnOutcomeState;
  readonly message?: string;
}

/**
 * One operator turn restored from history (§2.8(2), amended 2026-09-03).
 *
 * `turn` is THE IDENTITY — 0-based, unique, strictly increasing — present
 * whenever the sidecar stamps it. `seq` keeps its original, pre-amendment
 * meaning (the ordinal of the turn's first event) and stays on the wire, but
 * is explicitly NOT unique: two prompts around a zero-event turn can share
 * one. A page from a sidecar that predates this amendment carries neither
 * `turn` nor `envelope` nor `outcome` — see `stream/history.ts` for the
 * per-turn legacy fallback this client must not skip.
 */
export interface HistoryUserPrompt {
  /** THE IDENTITY when present (§2.8(2)). Absent from a pre-amendment sidecar. */
  readonly turn?: number;
  readonly seq: number;
  /** The operator's typed sentence alone; `null` when unrecoverable (§2.8(3)). */
  readonly text: string | null;
  /** §7A.3's workspace-context block, verbatim, when one was sent. */
  readonly envelope?: string | null;
  readonly outcome?: TurnOutcome;
  /** §2.8(3): who wrote `text`. Absent means the operator; `"agent"` is the
   *  sidecar's own transient-retry continuation sentence. */
  readonly origin?: "operator" | "agent";
}

export interface HistoryPageDocument {
  readonly status: "ok";
  readonly session_id: string;
  /**
   * §2.8(1): each event additively carries `turn` — `null` before the
   * session's first user message, absent entirely from a pre-amendment
   * sidecar's page. Never present on a LIVE frame; that is §2.8(1)'s other
   * half, enforced in `stream/live.ts` rather than in a type.
   */
  readonly events: readonly (HistoryEventFrame & { readonly turn?: number | null })[];
  /**
   * Additive field: operator turns recorded beside the event page. Omitted by
   * older sidecars; never shifts event identities (G4.11).
   */
  readonly user_prompts?: readonly HistoryUserPrompt[];
  readonly cursor: string | null;
  readonly done: boolean;
  /**
   * §2.8(5): ALWAYS present and NEVER null on a page from an amended sidecar
   * — names the ordinal after this page's last event, hand it back as
   * `after` for a tail read. Optional here because a pre-amendment sidecar
   * sends no such field at all.
   */
  readonly end_cursor?: string;
}

/** `MAX_THREAD_DEPTH` (`session_edges.py`), mirrored so the upward walk is bounded. */
export const MAX_THREAD_DEPTH = 32;

export function sessionPath(sessionId: string, suffix: string): string {
  return `/sessions/${encodeURIComponent(sessionId)}${suffix}`;
}

export function fetchSessions(): Promise<SessionsDocument> {
  return apiJson<SessionsDocument>("/sessions");
}

export function fetchThread(sessionId: string): Promise<ThreadDocument> {
  return apiJson<ThreadDocument>(sessionPath(sessionId, "/thread"));
}

/**
 * One history page. `cursor` and `after` are forwarded **verbatim** — never
 * decoded, never re-encoded, and never accompanied by a page size (§2.8).
 *
 * `encodeURIComponent` is percent-encoding for the query string, not a rewrite:
 * a base64url cursor (`[A-Za-z0-9_-]`) passes through it unchanged byte for
 * byte, and the escape exists so a cursor shape that ever gained another
 * character still arrives as the server minted it rather than as URL syntax.
 *
 * `after` is §2.8(5)'s TAIL read — a caller retaining a prior page's
 * `end_cursor` and asking to resume from it passes it here instead of
 * `cursor`. The two are mutually exclusive on the wire (the server refuses
 * `invalid_cursor` when both are given, §2.4); this function does not enforce
 * that itself; a caller passes at most one. `null` (as well as omitting the
 * argument) means "no tail read" — matching `stream/history.ts`'s
 * `PageFetcher`, whose own `after` is `string | null | undefined` because a
 * bounded walk's later pages pass `null` once the tail token is consumed.
 */
export function fetchHistoryPage(
  sessionId: string,
  cursor: string | null,
  after?: string | null,
): Promise<HistoryPageDocument> {
  const query =
    after !== undefined && after !== null
      ? `?after=${encodeURIComponent(after)}`
      : cursor === null
        ? ""
        : `?cursor=${encodeURIComponent(cursor)}`;
  return apiJson<HistoryPageDocument>(sessionPath(sessionId, `/history${query}`));
}

/**
 * `answer_question`'s projection (`http/sessions.py`), field for field.
 *
 * `answer` is the **winner's** recorded selection, returned unchanged to every
 * client so a loser renders what the run was actually told rather than what it
 * tried to say. `accepted` is this request's own outcome and `answered_by` is
 * the same fact spelled for the DOM (§7.3, §7A.7).
 */
export interface AnswerDocument {
  readonly status: "ok";
  readonly question_id: string;
  readonly session_id: string;
  readonly run_id: string;
  readonly answer: unknown;
  readonly accepted: boolean;
  readonly answered_by: AnsweredBy;
  /** The id in the path; `session_id` above is the question's own (§2.7). */
  readonly requested_session_id: string;
}

/** The route's `answered_by`, closed at two — "self" is the winner (§7.3). */
export const ANSWERED_BY = ["self", "other"] as const;
export type AnsweredBy = (typeof ANSWERED_BY)[number];

/**
 * `POST /sessions/{id}/answer` — the one thing this workspace tells a run.
 *
 * `answer` is the value the question's own params admit: an option's
 * server-sent `label`, an array of them for a `multi` question, or free text
 * when the question allowed it (§7A.7). The caller decides which; this function
 * never inspects or rewrites it, because a client that "corrected" an answer on
 * the way out would be a second answer namespace.
 *
 * A refusal arrives as a `WorkspaceError` with its reason intact —
 * `unknown_question` (404) is the one every caller must render, because the
 * question may have been answered elsewhere, abandoned with its run, or never
 * asked at all, and those are one state to this route.
 */
export function answerQuestion(
  sessionId: string,
  questionId: string,
  answer: unknown,
): Promise<AnswerDocument> {
  return apiJson<AnswerDocument>(sessionPath(sessionId, "/answer"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question_id: questionId, answer }),
  });
}

// ---------------------------------------------------------------------------
// the composer's three writes (INTERFACE.md §7A, §19.18)
// ---------------------------------------------------------------------------
//
// `createSession`, `sendPrompt` and `cancelRun` join `answerQuestion` above.
// **None of them carries an `Idempotency-Key`, and that is the spec's decision
// rather than an omission** (§2.3's second table): session control is not a
// source/config/output mutation, and §2.5's byte-for-byte replay is incoherent
// for a route whose whole meaning is a side effect on a live run. The
// consequences are carried in the UI rather than routed around — see
// `sendPrompt` for the one that matters most.

/**
 * The context envelope (§7A.3) — **references, never facts**.
 *
 * Every member is either a closed-vocabulary token this client already owns as
 * §4.5 workspace state, or an opaque server-minted identifier it is echoing
 * back unmodified. There is no free-form field, no number this client computed,
 * and no string it authored. Three of them are where a careless implementation
 * would smuggle in a fact, and each is spelled to make that impossible:
 *
 * * `explode_t` is the **parameter**, never a displacement. §1 already puts
 *   `offset · t` in the client's scene graph; a distance in this envelope would
 *   be the browser asserting a measurement.
 * * `hidden_labels` reports **the toggles**, not what is visible. The namespace
 *   is the geometry-entry label from `GET /parts/{part}/build`, the only
 *   namespace this client has. Camera framing and occlusion are claimed by
 *   neither side.
 * * `selection` carries the **ids**; the server resolves them against the
 *   pinned ref and refuses `stale_selection` if they do not resolve. It never
 *   falls back to current geometry (§15.3).
 *
 * The server validates the whole envelope against its own state, which is the
 * only structural difference between *carrying context* and *letting the
 * browser write the brief*. A member outside this set is refused by name.
 */
export interface ContextEnvelope {
  readonly part?: string | null;
  readonly artifact_ref?: string | null;
  readonly pin_mode?: string;
  readonly stage_tab?: string;
  readonly inspector_tab?: string;
  readonly view?: string;
  readonly explode_t?: number;
  readonly section_plane?: string | null;
  readonly hidden_labels?: readonly string[];
  readonly selection?: { readonly selection_id: string; readonly bundle_ref: string } | null;
  readonly focus?: string | null;
}

/** The **closed** member set, mirrored so a chip row cannot invent a key. */
export const CONTEXT_MEMBERS = [
  "part",
  "artifact_ref",
  "pin_mode",
  "stage_tab",
  "inspector_tab",
  "view",
  "explode_t",
  "section_plane",
  "hidden_labels",
  "selection",
  "focus",
] as const;
export type ContextMember = (typeof CONTEXT_MEMBERS)[number];

/** `POST /context/preview`'s body, and the prompt response's echo (§7A.3). */
export interface ContextDocument {
  readonly status: "ok";
  /** What the agent is told. Empty string for the blank canvas. */
  readonly block: string;
  /** Marked, never silent: the block was cut to the `text_result` caps. */
  readonly truncated: boolean;
  /** The resolved projections the block was composed from. */
  readonly sources: readonly string[];
}

/** `POST /sessions` — `WorkspaceSessions.create`'s projection. */
export interface CreatedSessionDocument {
  readonly status: "ok";
  readonly session_id: string;
  readonly profile: SessionProfile;
  readonly part: string | null;
  readonly resumed: boolean;
}

/** `POST /sessions/{id}/prompt` — `run_prompt`'s projection (§2.3, §7A.6). */
export interface PromptDocument {
  readonly status: "ok";
  readonly session_id: string;
  readonly run_id: string;
  /** The turn's outcome. §7A.6 makes THIS the authority that the turn is over. */
  readonly run_status: string;
  readonly events: readonly HistoryEventFrame[];
  readonly terminal: Readonly<Record<string, unknown>> | null;
  /** The block actually sent, echoed; `null` when none was (§7A.3). */
  readonly context: ContextDocument | null;
}

/** `POST /runs/{run_id}/cancel` — `cancel_run`'s projection (§7A.6). */
export interface CancelDocument {
  readonly status: "ok";
  readonly run_id: string;
  readonly session_id: string | null;
  /** Questions released with the run; the widget learns from this or a 404. */
  readonly abandoned_questions: number;
}

/**
 * `POST /sessions` — §7A.2's two affordances, and only those two.
 *
 * `quick_edit` is deliberately not offered and is refused server-side by name:
 * a quick-edit session's entire meaning is the seeding
 * `POST /parts/{part}/quick_edit` performs, and a bare create would produce
 * that profile's restrictions with none of its context.
 *
 * **At-least-once is the stated consequence and the UI carries it** (§2.3): a
 * duplicate create is an extra *idle* session. So this is called **only on an
 * explicit operator action** — never on focus, never on first keystroke, never
 * as recovery from a failed prompt. There is no route that closes a session and
 * none is invented; an orphan is idle and harmless, `GET /sessions` lists it,
 * and the panel says it can be left rather than offering a close button no
 * route backs.
 */
export function createSession(
  profile: Exclude<SessionProfile, "quick_edit">,
  part?: string | null,
): Promise<CreatedSessionDocument> {
  const body: Record<string, unknown> = { profile };
  if (part !== undefined && part !== null) body["part"] = part;
  return apiJson<CreatedSessionDocument>("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * `POST /sessions/{id}/prompt` — one turn, blocking for its whole duration.
 *
 * **This function is never retried automatically** (§7A.5's TIGHTENING, binding
 * §2.3's prompt row). The route carries no idempotency key and a supplied one
 * is ignored, so an auto-retry over it is a duplicate-turn generator with a
 * spinner on it. A failed or lost POST leaves the operator's text in the box
 * and marks the turn `data-send-state="unknown"`: the turn may have started,
 * and the stream is the authority.
 *
 * **The run id is not read from here** (§7A.5). The response arrives *after*
 * the run is over, so it cannot be the source of a mid-run cancel target; the
 * composer learns its run id from the first `/events` frame whose envelope
 * `session_id` matches the tab. What the response IS authoritative for is that
 * the turn is over (§7A.6) — `run_status` and `terminal` come back on it,
 * precisely so a tab that resynced across the end of its own run does not need
 * the live-only `terminal` event.
 *
 * `context` is the §7A.3 envelope. It travels **beside** the text and never
 * inside it: the server binds `text` alone as the request every `VALIDATION.md`
 * §4 rung judges against, so a block full of the build's own extents cannot
 * come back `matched: true` against itself.
 */
export function sendPrompt(
  sessionId: string,
  text: string,
  context: ContextEnvelope | null = null,
): Promise<PromptDocument> {
  return apiJson<PromptDocument>(sessionPath(sessionId, "/prompt"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, context }),
  });
}

/**
 * `POST /runs/{run_id}/cancel` — idempotent by construction, not by a key.
 *
 * A repeated cancel on an already-cancelled run changes nothing, so a key here
 * would record a replay of a no-op (§2.3). Every question suspended on the run
 * is released, and `abandoned_questions` says how many — the only signal a
 * cancelling client gets, because there is no `question_abandoned` event and
 * minting one would extend the closed vocabulary (§15.10, §7A.6's named wart).
 */
export function cancelRun(runId: string): Promise<CancelDocument> {
  return apiJson<CancelDocument>(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

/**
 * `POST /context/preview` — §7A.3's "what will the agent be told?" disclosure.
 *
 * **Advisory.** The prompt route composes again, from the same server function,
 * at send time, and echoes the block it actually sent; saying this response were
 * authoritative would be a claim two separate calls cannot make good on.
 *
 * It starts no run and calls no tool, and it is deliberately **not** gated on
 * the agent runtime — a disclosure that went dark exactly when the composer is
 * disabled would be missing at the one moment the operator needs it.
 */
export function previewContext(context: ContextEnvelope | null): Promise<ContextDocument> {
  return apiJson<ContextDocument>("/context/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context }),
  });
}
