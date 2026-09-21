// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer — the surface that **speaks** (INTERFACE.md §7A).
// Issue 120 supersedes the historical picker exclusions below: the context row
// now includes a wired live-session model control. Model state and reservations
// live in conversation.ts; prompt requests carry the reviewed model revision.
//
// §7 specifies the stream as a surface that *renders*. This is the other half,
// and it is the half the shipped build declined to write: `StreamPanel.tsx`
// stated "§9 puts prompting in Stage 5", and §9 does not — it is titled "Stage 5
// — editing" and the word "prompt" occurs in it once, as "merge prompt".
// §7A.9's table settles what actually gates this: the composer on an
// orchestrator or part session, and the blank-canvas create, are **Stage 4**,
// because no clause asks and no clause forbids, §4.1 places it in the STREAM
// column, and §2.3 already carries every route it uses.
//
// FIVE DECISIONS THIS COMPONENT IMPLEMENTS, each with its WHY:
//
// **1. One composer per session tab, no session picker** (§7A.1). Its identity
// is the tab's `session_id`. A composer that could retarget without the tab
// changing would let a part-scoped question land in an orchestrator, or an
// orchestrator's project-wide instruction land in a part-bound session, with the
// only visible difference being a dropdown the operator was not looking at.
// **Scope must move when the reader's eye moves.**
//
// **2. It never retries a prompt automatically** (§7A.5's TIGHTENING). The route
// carries no idempotency key and a supplied one is ignored, so an auto-retry
// over it is a duplicate-turn generator with a spinner on it. A failed or lost
// POST leaves the text in the box and marks `data-send-state="unknown"`.
//
// **3. The run id comes from the stream, not from the response** (§7A.5).
// `run_prompt` blocks for the whole turn, so its response arrives *after* the
// run is over and cannot be a mid-run cancel target. Between submit and the
// first event carrying the run id, cancel renders `unavailable` **with its
// reason** rather than as a dead button — and the same when the socket is not
// live, because a tab with no stream has no way to learn the id.
//
// **4. The turn's completion comes from the prompt response, not from
// `terminal`** (§7A.6). Issuing a prompt does not upgrade the socket: the
// originating tab stays a non-durable observer and can be closed `4409` across
// the end of its own run. `run_prompt` already returns `{run_status, terminal}`
// for exactly this reason, so the originating tab gets the stronger guarantee
// from a field that already exists rather than from a new event kind.
//
// **5. A disabled composer says why** (§7A.8). "A disabled text box with no
// explanation would be worse than its honest absence" is correct reasoning to a
// wrong conclusion, because it considers two options where there are three. A
// disabled composer **with** its reason is §4.4's discipline applied to this
// surface: a state that exists for a reason reads as designed; the same state
// with its content missing reads as a bug. Silence is what produced a product
// review finding that the workspace has no way to talk to an agent.
//
// **6. Session chrome stays backed by explicit contracts.** Model is a
// projection of `GET /providers/models` using provider-owned identities. Plan,
// DFM context, and effort are explicit prompt members validated by HTTP and the
// sidecar; Plan additionally narrows the active tool set before model work.
// Inspector DFM execution remains separate: choosing DFM context does not run a
// check. Context details and their advisory preview remain behind one control.
//
// **7. AMENDED 2026-09-01 (§0.2b) — the resting composer is an input and one
// button.** Three drawn controls stood permanently in the action row: Send, a
// Cancel that was `disabled` for nearly all of the time, and a full `secondary`
// disclosure. Above them sat a chip row that `chipsFor` always filled with
// `stage_tab` / `inspector_tab` / `view`, so an idle composer was four rows of
// chrome around a one-row textarea. The amendment collapses that:
//
// * §7A.3(a)-(e): ONE summary line — `Context:` and the envelope's present
//   members, in a fixed order, `+N` for the remainder — with the editable chip
//   form behind it. `ul[data-context-chips]` does **not** mount while the
//   disclosure is collapsed. An **excluded** member stays visible on the line
//   (§7A.3(e)), because "the agent will not be told about the selection" is a
//   fact about what is being sent and the quiet path is only for the envelope
//   the workspace state implies.
// * §7A.6 / §7A.10(b): Cancel MOUNTS iff `data-cancel-state="available"`. The
//   attribute itself is unchanged and stays on the form, so `unavailable` is
//   still readable with no control present, and its reason moved to the form's
//   `title` rather than being a disabled button's excuse.
// * §7A.10(a): Send keeps disabled-with-reason. It is a **primary** action, and
//   one that vanished would leave the operator with no target for "why can't I
//   send?" — the opposite case from Cancel.
// * §7A.10(c)(d): the disclosure is a compact quiet toggle attached to the
//   summary line (one affordance). The model chip is retired (#114): idle
//   chrome is context + textarea + Send. Model identity lives on the rail's
//   Model providers. The context disclosure this once named was struck
//   2026-09-20; the envelope it described is unchanged and still sent.
//
// NOTHING LEFT THE DOM (§0.2b's governing discipline). `data-cancel-state`,
// `data-send-state`, `data-composer-state`, `data-disabled-reason`, every
// `data-context-key`/`-value`/`-count` and the model attribution are all still
// minted; what was dropped is a count nobody read and two normal-state words.
//
// **8. AMENDED 2026-09-02 (§0.2c, C15/C22) — the resting composer is two rows,
// counted, and Add current view surfaces where the gap is visible.**
//
// * §7A.10 (C15): the 2026-09-01 amendment's four-high stack collapses to two
//   rows. The CONTEXT ROW is §7A.3(a)'s summary line — no model id at rest
//   (#114). The INPUT ROW holds the textarea with Send right-aligned on the
//   same row. No third row mounts at rest: no meta line, no empty action row,
//   no model chip — the keyboard hint lives on Send's `title`. Exceptional
//   states stay loud and add their rows as specified: Cancel while
//   cancellable (§7A.6), the disabled reason, and C1's
//   `data-send-state="unknown"` note. §7A.10(a)'s testable is restated to the
//   input row: count one button-role element, and it is the Send hook.
//   (Send's and the input's DOM hooks are spelled only in the JSX below, on
//   purpose — source order of the hooks is itself a testable.)
// * §7A.3 (C22): `[data-context-add-view]` renders on the resting summary
//   line exactly when `view` and `selection` are absent from the envelope and
//   a selection exists — `stream/composerContext.ts`'s `addViewOnLine` is the
//   predicate — and unmounts when satisfied, when no selection exists, or
//   while the disclosure is open. Activating it does exactly what the form's
//   copy does: it adds the members to the `added` set, computing nothing (§1).
//   `data-context-keys` equality is untouched.
//
// **9. AMENDED 2026-09-02 (§0.2c, C8/C9) — one primary per shell, and it is
// Send.** The steady-state shell has exactly one `data-variant="primary"` and
// it is the Send hook. (Spelled without the literal here on purpose: source
// order of the hooks is itself a testable.) The sole exception keys off THIS form's
// current `data-disabled-reason="agent_unavailable"` — never last-observed
// provider health, which the review fix struck — during which the
// still-mounted Send demotes to `secondary` and the ProvidersPanel's Sign-in
// takes `primary`. The reason is published through
// `stream/composerGate.ts`'s store so both surfaces read one fact.

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useSyncExternalStore,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { WorkspaceError } from "../../api/client";
import { refusalText } from "../refusalText";
import { refreshAfterTurn } from "../../api/refresh";
import {
  attachAgent,
  attachDetailAdds,
  type AttachCause,
  type AttachProjection,
  isAttachCause,
} from "../../api/attach";
import {
  cancelRun,
  createSession,
  sendPrompt,
  type DfmMode,
  type InteractionMode,
  type ProfileCapability,
  type ThinkingLevel,
} from "../../api/sessions";
import { copy } from "../../copy";
import { Button, EmptyState, TextInput } from "../../system";
import { useWorkspaceState, workspaceStore } from "../../state/react";
import { labelsForPart, visibilityStore } from "../../state/visibility";
import {
  canSendTurn,
  cancelAvailability,
  composerGateStore,
  isComposable,
  isSendKey,
  signInPrimary,
} from "../../stream/composerGate";
import {
  chipsFor,
  envelopeFor,
  summaryFor,
} from "../../stream/composerContext";
import { sessionPromptStore } from "../../stream/sessionPrompts";
import { holderSessionTitle } from "../../stream/sessionTitle";
import { promptFailurePost, runtimeFaultOf, type RuntimeFault } from "../../stream/runtimeFault";
import type { ContextMember } from "../../api/sessions";
import { conversationStore, currentTurn, modelRefusal, readSessionModel, useConversation, type CurrentTurn } from "../../stream/conversation";
import { ModelPicker } from "./ModelPicker";
import { ComposerControls, PlanControl } from "./ComposerControls";
import {
  ImageAttach,
  ImageStrip,
  imagesFromTransfer,
  useRevokeOnUnmount,
  type HeldImage,
} from "./ImageAttach";
import { sameModel } from "../../stream/composerChrome";
import type { ModelRevision } from "../../api/providers";
import styles from "./Composer.module.css";

/** §7A.10's closed `data-composer-state` vocabulary. */
export const COMPOSER_STATES = ["idle", "sending", "running", "disabled"] as const;
export type ComposerState = (typeof COMPOSER_STATES)[number];

/** §7A.10's closed `data-disabled-reason` vocabulary. `null` when enabled. */
export const DISABLED_REASONS = ["agent_unavailable", "run_in_flight", "no_session"] as const;
export type DisabledReason = (typeof DISABLED_REASONS)[number];

/** §7A.10's `data-send-state`. `unknown` is §7A.5's honest failure. */
export const SEND_STATES = ["ok", "unknown"] as const;
export type SendState = (typeof SEND_STATES)[number];

export interface ComposerProps {
  /** The tab's session. `null` is `no_session` — the composer still renders. */
  readonly sessionId: string | null;
  readonly currentTurn?: CurrentTurn;
  /** That session's profile, from `GET /sessions`. Rendered, never inferred. */
  readonly profile: string | null;
  readonly scopePart?: string | null;
  /** The §7A.8 attach projection when the runtime is missing, else `null`. */
  readonly attach: AttachProjection | null;
  /** `true` when the session routes are refusing `agent_unavailable`. */
  readonly agentUnavailable: boolean;
  /** Legacy transport hint for sending/running chrome; NOT a Stop authority. */
  readonly liveRunId: string | null;
  /** Legacy transport hint. A known authoritative run can be stopped offline. */
  readonly streamLive: boolean;
  /**
   * Live `terminal` frames seen for this session (§7A.11's counter, reused).
   *
   * A `run_in_flight` refusal is only true while that run is live, and a run
   * ending is exactly what a `terminal` says. Without this the refusal had no
   * expiry at all: the composer stayed disabled on a fact that had stopped
   * being true, and nothing in the UI could clear it.
   */
  readonly terminals?: number | undefined;
  /**
   * A failed request said the runtime is not answering (`stream/runtimeFault.ts`).
   *
   * Reported upward rather than rendered here because it is a fact about the
   * session, not about the composer: the well states it once, above the
   * transcript whose run it ended.
   */
  readonly onRuntimeFault?: ((fault: RuntimeFault | null) => void) | undefined;
  /** Fired after a turn settles, so the panel can refetch its own session list. */
  readonly onTurnSettled?: (() => void) | undefined;
  /**
   * Forget the live run id on submit (§7A.5). The stream holds the previous
   * turn's id until `terminal` unless this fires — a second Send would then
   * offer Cancel against a finished run (#99).
   */
  readonly onForgetLiveRun?: (() => void) | undefined;
  /**
   * §7A.5 (C1): append the local-prompt echo row on Send — the sent text
   * verbatim, minted from the textarea's own value, the one fact this clause
   * touches that the tab holds without the server's help. Fired on the same
   * submit that calls `sessionPromptStore.remember`, before the POST, so the
   * operator's words are on screen for the whole model round-trip.
   *
   * Takes the session id the turn actually targets — `sessionId` for an
   * already-open tab, or the id `POST /sessions` just minted on the
   * create-then-send path — so the echo always lands in the session it is
   * about even though this component's own `sessionId` prop is still `null`
   * at the moment `createSession` resolves.
   */
  readonly onEcho?: ((sessionId: string, text: string) => void) | undefined;
  /**
   * §7A.5: a NAMED refusal to the prompt POST (`run_in_flight`,
   * `agent_unavailable`, any other reason the route names) marks that same
   * echo `refused` rather than leaving it looking like an ordinary sent turn.
   * Not called for the `unknown` outcome (a POST that never came back) — that
   * stays on the composer's own `data-send-state="unknown"`, per §7A.5.
   */
  readonly onEchoRefused?: ((sessionId: string, reason: string) => void) | undefined;
  /**
   * Incremented after `POST /sessions` so the new session's box is focused
   * (#61). `0` / omitted means "do not steal focus".
   */
  readonly focusNonce?: number | undefined;
  /**
   * Human title for a session id (#51 / #66). The `run_in_flight` holder
   * used to dump the UUID; the tab label is what the operator already reads.
   */
  readonly sessionTitle?: ((sessionId: string) => string) | undefined;
}

/** What the POST is doing. `unknown` is a *state*, not an error to swallow. */
type Post =
  | { readonly phase: "idle" }
  | { readonly phase: "sending" }
  | {
      readonly phase: "unknown";
      /**
       * The lost POST was a runtime fault (unnamed 5xx). The fault band is
       * the only place that is stated — this flag keeps the §7A.5
       * `data-send-state="unknown"` without painting a second footer.
       */
      readonly runtimeFault?: boolean;
    }
  | {
      readonly phase: "refused";
      readonly reason: string;
      readonly message: string;
      /**
       * The refusal's `data`, carried whole (§2.4). It is what makes
       * `run_in_flight` actionable rather than merely true: §7A.5 has the
       * refusal name "the holding session and run ids", because the operator's
       * remedy — wait, or cancel that run — depends on knowing which turn is in
       * the way and it may not be one they started.
       */
      readonly data: Readonly<Record<string, unknown>>;
    };

export function Composer(props: ComposerProps): React.JSX.Element {
  const {
    sessionId,
    profile,
    attach,
    agentUnavailable,
    liveRunId,
    terminals,
    focusNonce,
  } = props;
  const client = useQueryClient();
  const state = useWorkspaceState();
  const hidden = useSyncExternalStore(
    visibilityStore.subscribe,
    visibilityStore.getSnapshot,
    visibilityStore.getSnapshot,
  );
  const hiddenLabels = useMemo(() => labelsForPart(hidden, state.part), [hidden, state.part]);

  const conversation = useConversation(sessionId);
  const turn = props.currentTurn ?? currentTurn(conversation, sessionId !== null);
  // Keep the immutable submitted revision recoverable, but never present it as
  // an editable/queued next message while the blocking POST is unresolved.
  const text = (conversation.attempt?.phase === "sending" || conversation.attempt?.phase === "unknown")
    && conversation.draft.revision === conversation.attempt.submitted.revision ? "" : conversation.draft.text;
  const setText = (value: string) => conversationStore.draft(sessionId, value);
  const attempt = conversation.attempt;
  const post: Post = attempt?.phase === "sending" ? { phase: "sending" }
    : attempt?.phase === "unknown" ? { phase: "unknown" }
    : attempt?.phase === "refused" ? {
      phase: "refused", reason: attempt.reason ?? "", message: attempt.reason ?? "",
      data: { session_id: attempt.holderSession, run_id: attempt.holderRun },
    } : { phase: "idle" };
  // Held images (2026-09-20). They live in the composer because a cancelled
  // message must leave nothing behind; see `ImageAttach.tsx` for why they are
  // collected but not yet put on the wire.
  const [images, setImages] = useState<readonly HeldImage[]>([]);
  useRevokeOnUnmount(images);
  const dropped = conversation.contextDropped;
  const added = conversation.contextAdded;
  const [controls, setControls] = useState<{
    readonly sessionId: string | null;
    readonly interactionMode: InteractionMode;
    readonly dfmMode: DfmMode;
    readonly thinkingLevel: ThinkingLevel;
  }>({ sessionId, interactionMode: "modeling", dfmMode: "off", thinkingLevel: "medium" });
  const turnControls = useMemo(() => controls.sessionId === sessionId ? controls
    : { sessionId, interactionMode: "modeling" as const, dfmMode: "off" as const, thinkingLevel: "medium" as const }, [controls, sessionId]);
  const updateControls = (patch: Partial<typeof turnControls>) => {
    setControls({ ...turnControls, ...patch, sessionId });
  };
  const [attaching, setAttaching] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | HTMLInputElement | null>(null);
  const [attachError, setAttachError] = useState<string | null>(null);
  const chips = useMemo(() => chipsFor(state, hiddenLabels), [state, hiddenLabels]);
  const envelope = useMemo(
    () => envelopeFor(state, hiddenLabels, dropped, added),
    [state, hiddenLabels, dropped, added],
  );
  // §7A.3(d): the summary is a projection of the envelope this form would POST,
  // not a second reading of the workspace. That is what makes `data-context-keys`
  // and the chips' `data-context-key` set answer the same question.
  const summary = useMemo(
    () => summaryFor(envelope, chips, dropped),
    [envelope, chips, dropped],
  );

  // ModelPicker reads the live session, never the first provider declaration.
  // Effort is a reviewed per-turn setting; model changes remain explicit.
  const promptRows = 2;
  // Add roughly 0.5 cm at standard browser density without changing the
  // composer's two-row semantic baseline.
  const promptHeightBonus = 19;
  // Grow only the visible editor, never the draft revision. Include wrapped
  // lines and width changes; longer drafts retain native internal scrolling.
  useEffect(() => {
    const input = inputRef.current;
    if (!(input instanceof HTMLTextAreaElement)) return;
    const fit = () => {
      const css = getComputedStyle(input);
      const line = Number.parseFloat(css.lineHeight);
      if (!Number.isFinite(line)) return;
      const edges = Number.parseFloat(css.paddingTop) + Number.parseFloat(css.paddingBottom)
        + Number.parseFloat(css.borderTopWidth) + Number.parseFloat(css.borderBottomWidth);
      input.style.height = "0px";
      input.style.height = `${Math.max(2 * line + edges + promptHeightBonus, Math.min(input.scrollHeight + 2, 4 * line + edges))}px`;
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    let width = input.clientWidth;
    const observer = new ResizeObserver(() => {
      if (input.clientWidth === width) return;
      width = input.clientWidth;
      fit();
    });
    observer.observe(input);
    return () => observer.disconnect();
  }, [text]);

  // §7A.3 (C22): ONE handler for both copies of the affordance. The line's
  // copy and the form's copy do exactly the same thing — un-drop and add the
  // members — and neither touches the disclosure: the form's copy only exists
  // while it is already open, and the line's copy closing the gap is what
  // unmounts it, not a disclosure it never asked for.
  const addCurrentView = useCallback(() => {
    conversationStore.addCurrentView(sessionId, state.selection !== null);
  }, [sessionId, state.selection]);

  // -- the two closed vocabularies (§7A.10) -------------------------------
  //
  // Ordered most-specific first, and every branch is a fact the SERVER stated:
  // `agent_unavailable` is the refusal `GET /sessions` returned, `run_in_flight`
  // is the 409 a previous submit received (with the holding ids in its payload),
  // and `no_session` is this tab's own emptiness. Nothing here is inferred from
  // watching the stream — a client that guessed "a run looks live" would be
  // disabling on a derivation the server never made.
  const refusedRunInFlight = post.phase === "refused" && post.reason === "run_in_flight";
  const disabledReason: DisabledReason | null = agentUnavailable
    ? "agent_unavailable"
    : sessionId === null
      ? "no_session"
      : turn.runId !== null
        ? "run_in_flight"
        : null;

  const composerState: ComposerState =
    disabledReason !== null || (!turn.canSend && post.phase !== "sending")
      ? "disabled"
      : post.phase === "sending"
        ? liveRunId === null
          ? "sending"
          : "running"
        : "idle";

  // §4.7 (C8) / §23.8 (C9): the composer's CURRENT `data-disabled-reason` is
  // the one condition the single-primary exception may key off — never
  // last-observed health, which the review fix struck. It is published to the
  // gate store so the ProvidersPanel reads the same fact the operator sees on
  // this form's own attribute; unmount resets it, because an unmounted
  // composer has no current reason for an exception to hold against.
  useEffect(() => {
    composerGateStore.publish(disabledReason);
  }, [disabledReason]);
  useEffect(
    () => () => {
      composerGateStore.publish(null);
    },
    [],
  );

  // WHAT `disabled` DISABLES. §7A.5 says the composer "disables while any run
  // is live"; that is about SENDING. `stream/composerGate.ts` carries the
  // partition and the dead end it removes.
  const composable = isComposable(disabledReason);

  // Stop targets authoritative active ownership, including a refusal's holder.
  // A disconnected observer can still explicitly stop that known run over HTTP;
  // the last frame's id alone must never offer Stop against a finished run.
  const awaitingRun = post.phase === "sending" || refusedRunInFlight;
  const cancel = cancelAvailability({ liveRunId: turn.runId, streamLive: true, awaitingRun });
  const cancellable = cancel.available;
  // A run ending is what makes a `run_in_flight` refusal stop being true, and
  // `terminal` is the frame that says a run ended (§7A.11's counter). Monotone,
  // so this fires once per completed run and not again on a re-render.
  // A terminal count cannot release a refusal: it may belong to an older run.
  // Admission availability is reconciled through the shared sessions read.
  void terminals;

  // #61: after New session / Ask about <part>, the nonce ticks and focus
  // lands on the box that exists so the operator can talk.
  useEffect(() => {
    if (focusNonce === undefined || focusNonce === 0) return;
    inputRef.current?.focus();
  }, [focusNonce]);

  // -- the disclosure (§7A.3) --------------------------------------------
  //
  // Advisory, and it says so: the prompt route composes again from the same
  // server function at send time and echoes the block it actually sent.
  //
  // One state, written only from the async callbacks. An eager
  // `setPreviewError(null)` in the effect body would be a synchronous setState
  // inside an effect — a cascading render, and the same shape `useStream`'s own
  // header comment rejects for tab switching. The stale-error window it would
  // have closed is closed instead by the settle: whichever of the two callbacks
  // wins replaces the whole record, so an error never outlives the request that
  // produced it.
  const toggleChip = useCallback((key: ContextMember) => {
    conversationStore.toggleContext(sessionId, key);
  }, [sessionId]);

  // -- the turn -----------------------------------------------------------

  // THE GUARD IS THE SAME PREDICATE AS `sendDisabled`, and it has to be. Enter
  // and the form's own `onSubmit` reach this function directly, without passing
  // through the Send button, so a disabled Send is not a gate — it is a
  // *rendering* of a gate that has to exist here. `run_in_flight` is the case
  // that proves it: `post.phase` is `refused` rather than `sending`, and this
  // component deliberately keeps the textarea typable while a turn finishes
  // (`stream/composerGate.ts`), so a `disabledReason` check absent from this
  // line means Enter posts a second prompt against a run the server has already
  // told us is in flight. §7A.5's "the composer disables while any run is live"
  // is a statement about sending, and sending is what happens here.
  const sending = post.phase === "sending";
  const sendAllowed = canSendTurn({ disabledReason, text, sending }) && turn.canSend
    && currentTurn(conversation, sessionId !== null).canSend;

  const submit = useCallback(() => {
    // THE GUARD IS THE SAME PREDICATE AS THE SEND BUTTON. Enter, click, and
    // the form's `onSubmit` all land here. A gate that lived only on the
    // button would be one the keyboard walks past; a gate that lived only
    // here would leave Send looking enabled while a click did nothing (#44).
    if (!canSendTurn({ disabledReason, text, sending: post.phase === "sending" }) || !turn.canSend) return;
    // Use the revision this render actually showed, not a newer store value
    // that arrived between paint and activation. A stale action is refused.
    const revision = conversation.model?.revision;
    const choice = conversationStore.get(null).proposal;
    if (sessionId !== null ? revision === undefined : choice?.available !== true) return;
    const submitted = conversationStore.begin(sessionId, envelope ?? undefined, revision);
    if (submitted === null) return;
    let attemptSid = sessionId;
    const setPost = (next: Post) => {
      conversationStore.finish(attemptSid, submitted.id,
        next.phase === "idle" ? "settled" : next.phase,
        next.phase === "refused" ? {
          ...(typeof next.data["session_id"] === "string" ? { holderSession: next.data["session_id"] } : {}),
          ...(typeof next.data["run_id"] === "string" ? { holderRun: next.data["run_id"] } : {}),
          // Closed refusal name is preserved rather than translated.
          ...{ reason: next.reason },
        } : {},
      );
    };
    // `no_session` is typable: Send creates the appropriate session (part if
    // one is selected, else a project/orchestrator session) and then posts.
    const opening = text;
    props.onForgetLiveRun?.();
    void client.invalidateQueries({ queryKey: ["sessions"] });

    const postPrompt = (sid: string, expected: ModelRevision): void => {
      props.onEcho?.(sid, opening);
      void sendPrompt(sid, opening, envelope, expected, {
        interaction_mode: turnControls.interactionMode,
        dfm_mode: turnControls.dfmMode,
        thinking_level: turnControls.thinkingLevel,
      })
        .then((document) => {
          setPost({ phase: "idle" });
          conversationStore.response(sid, document);
          sessionPromptStore.remember(sid, opening);
          props.onRuntimeFault?.(null);
          refreshAfterTurn(client, state.part);
          props.onTurnSettled?.();

        })
        .catch((cause: unknown) => {
          void client.invalidateQueries({ queryKey: ["sessions"] });
          const fault = runtimeFaultOf(cause);
          if (fault !== null) props.onRuntimeFault?.(fault);
          const next = promptFailurePost(cause);
          if (next === "unknown") {
            setPost({ phase: "unknown", ...(fault !== null ? { runtimeFault: true } : {}) });
            return;
          }
          if (next === "idle") {
            setPost({ phase: "idle" });
            return;
          }
          if (cause instanceof WorkspaceError) {
            // §7A.5: a NAMED refusal — the turn definitively did not start —
            // marks the echo `refused` rather than leaving it standing as
            // though the turn were merely unresolved.
            props.onEchoRefused?.(sid, cause.reason);
            setPost({
              phase: "refused",
              reason: cause.reason,
              message: cause.message,
              data: cause.data,
            });
            modelRefusal(sid, cause);
            return;
          }
          setPost({ phase: "unknown" });
        }).finally(() => { void readSessionModel(sid, true); });
    };

    if (sessionId !== null) {
      if (revision !== undefined) postPrompt(sessionId, revision);
      return;
    }

    const profile = state.part !== null ? "part" : "orchestrator";
    if (choice === null) return;
    void createSession(profile, state.part, choice)
      .then((created) => {
        attemptSid = created.session_id;
        conversationStore.update(created.session_id, c => ({ ...c,
          attempt: { ...submitted, sessionId: created.session_id, modelRevision: created.model_state.revision,
            baselineRunId: created.execution?.run_id ?? null },
          draft: conversationStore.get(null).draft,
          contextDropped: conversationStore.get(null).contextDropped,
          contextAdded: conversationStore.get(null).contextAdded,
          checking: true, barrier: conversationStore.ticket() }));
        conversationStore.finish(null, submitted.id, "settled");
        if (workspaceStore.getSnapshot().session === sessionId) {
          workspaceStore.update({ session: created.session_id });
        }
        void client.invalidateQueries({ queryKey: ["sessions"] });
        conversationStore.modelSnapshot(created.session_id, created.model_state, created.execution, conversationStore.ticket());
        if (created.model_state.state !== "ready" || !sameModel(created.model_state.current, choice)) {
          setPost({ phase: "refused", reason: created.model_state.state === "ready" ? "model_changed" : "selection_required",
            message: copy.models.none, data: {} });
          return;
        }
        postPrompt(created.session_id, created.model_state.revision);
      })
      .catch((cause: unknown) => {
        const fault = runtimeFaultOf(cause);
        if (fault !== null) props.onRuntimeFault?.(fault);
        if (cause instanceof WorkspaceError) {
          setPost({
            phase: "refused",
            reason: cause.reason,
            message: cause.message,
            data: cause.data,
          });
          return;
        }
        setPost({ phase: "unknown" });
      });
  }, [disabledReason, sessionId, text, post.phase, envelope, client, state.part, props, turn.canSend, conversation.model?.revision, turnControls]);

  const cancelTurn = useCallback(() => {
    // An acknowledgement only records Stop requested for this same active run.
    // It is never terminal evidence, and cannot mark a successor run stopped.
    const target = turn.runId;
    if (target === null || sessionId === null) return;
    const attempt = conversationStore.stop(sessionId, target);
    if (attempt === null) return;
    void cancelRun(target)
      .then((document) => {
        if (document.run_id !== target || document.status !== "ok"
          || (document.session_id !== null && document.session_id !== sessionId)) throw new Error("Invalid Stop acknowledgement");
        conversationStore.stopResult(sessionId, attempt, "acknowledged");
        void client.invalidateQueries({ queryKey: ["sessions"] });
      })
      .catch(() => {
        // Fetch failure cannot distinguish a dropped request from a lost
        // response. Only a fresh same-run read may enable an explicit retry.
        conversationStore.stopResult(sessionId, attempt, "uncertain");
        void client.invalidateQueries({ queryKey: ["sessions"] });
      });
  }, [turn.runId, sessionId, client]);

  const retryAttach = useCallback(() => {
    setAttaching(true);
    setAttachError(null);
    void attachAgent()
      .then(() => {
        // Every session read is now answerable; the panel refetches through the
        // same key it already reads rather than being handed a session list.
        void client.invalidateQueries({ queryKey: ["sessions"] });
      })
      .catch((cause: unknown) => {
        // NEVER the server's raw sentence (RC-5, J-web-stream-6). A refused
        // attach carries the same closed §7A.8 `cause` the refusal that
        // disabled this composer carried, and `refusalText` maps it; an
        // unmapped reason falls back to §2.4's title, not to
        // `f"{cause}: {detail}"` in a reading surface.
        setAttachError(refusalText(cause));
      })
      .finally(() => {
        setAttaching(false);
      });
  }, [client]);

  const sendDisabled = !sendAllowed;
  const sendReason =
    turn.status !== null && !turn.canSend && !agentUnavailable
      && (turn.runId !== null || sending || post.phase === "unknown")
      ? `${turn.status}. ${copy.composer.nextDraftHint}`
    : disabledReason !== null
      ? copy.composer.disabled[disabledReason]
      : conversation.modelPending || conversation.model?.state === "changing"
        ? copy.models.changing
      : conversation.modelChecking || conversation.model?.state !== "ready"
        ? copy.models.checking
      : !turn.canSend
        ? copy.composer.checking
        : sending
        ? copy.composer.sending
        : copy.composer.placeholder;
  // §7A.8's cause, resolved ONCE. `null` covers "no projection" and "a cause
  // word this build has never heard of"; both render the generic start failure
  // and both keep the server's word on `data-attach-cause`.
  const attachCause: AttachCause | null =
    attach !== null && isAttachCause(attach.cause) ? attach.cause : null;
  // §4.7's shared-cause rule (J-web-stream-4). While the composed refusal is
  // mounted it has ALREADY rendered `disabled.agent_unavailable` as prose; Send
  // describes itself from that element instead of rendering the same sentence a
  // second time in its own clipped reason span. Outside that state Send mints
  // its own, because there is nothing else on screen that says why.
  const unavailableReasonId = useId();
  const sendDescribes = disabledReason === "agent_unavailable";
  const sendHint =
    !turn.canSend || agentUnavailable ? copy.composer.sendHintBusy : copy.composer.sendHint;

  // Enter sends; `stream/composerGate.ts` decides which keystroke that is.
  //
  // This binding adds NO gate of its own, and that is a claim about `submit`
  // rather than about the keyboard: every state that must not send is refused
  // there, on the same predicate `sendDisabled` renders. It has to be that way
  // round — this path and the form's `onSubmit` both bypass the Send button, so
  // a gate living only on the button would be a gate the keyboard walks past.
  const onPromptKey = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!isSendKey({ ...event, isComposing: event.nativeEvent.isComposing })) return;
      event.preventDefault();
      submit();
    },
    [submit],
  );

  return (
    <form
      id="composer"
      className={styles["composer"]}
      aria-label={copy.composer.label}
      tabIndex={-1}
      data-composer=""
      data-session-id={sessionId ?? ""}
      data-profile={profile ?? ""}
      data-composer-state={composerState}
      data-disabled-reason={disabledReason ?? "null"}
      data-cancel-state={cancellable ? "available" : "unavailable"}
      data-send-state={post.phase === "unknown" ? "unknown" : "ok"}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {/* §7A.8: the refusal, with its cause and the path the server checked.
          It NAMES the file and does not offer to write it — until §23 ships
          there is nothing behind such an offer but a text editor. What it does
          offer is re-reading a configuration the operator has already fixed,
          which writes nothing. */}
      {disabledReason === "agent_unavailable" ? (
        <div className={styles["refusal"]} data-composer-refusal="agent_unavailable">
          <EmptyState
            icon="alert"
            title={copy.stream.noAgentTitle}
            // The sentence, ONCE, in an element with an id — Send's
            // `aria-describedby` points here rather than minting a second copy
            // (§4.7's shared-cause rule; J-web-stream-4).
            body={<span id={unavailableReasonId}>{copy.composer.disabled.agent_unavailable}</span>}
            density="inline"
          />
          {attach !== null ? (
            <>
              {/* One cause, one sentence. The attribute is unconditional so a
                  harness reads the server's word even where this build has no
                  sentence for it; the visible text falls back to the generic
                  start failure rather than to the raw word. */}
              <p className={styles["cause"]} data-attach-cause={attach.cause ?? ""}>
                {copy.attach.cause[attachCause ?? "sidecar_failed"]}
              </p>
              {/* §7A.8's named file, as WRAPPING CODE TEXT and not a `Chip`
                  (J-web-stream-3). A chip is a compact readout; this is a
                  ninety-character identifier whose whole text is load-bearing —
                  the refusal exists to name it — and `Chip` is `white-space:
                  nowrap` by construction, so inside a 395px column it drew a
                  621px box whose right edge sat 214px past the column's, with
                  the end of the path clipped away and no ellipsis to say so.
                  `data-attach-path` is unchanged: it is what the gates read. */}
              <p className={styles["path"]} data-attach-path={attach.config_path}>
                <span className={styles["pathLabel"]}>{copy.attach.pathLabel}</span>{" "}
                <code className={styles["pathText"]}>{attach.config_path}</code>
              </p>
              {/* The detail is DIAGNOSTIC and renders only where it adds
                  something the mapped cause does not (`attachDetailAdds`), and
                  then behind §4.7's disclosure — never as a fourth bare
                  paragraph. For the other five causes the server derives it
                  from the same raise the cause word came from, so it restated
                  the sentence above and re-printed the path beside it
                  (J-web-stream-4). */}
              {attach.detail !== undefined && attachDetailAdds(attachCause) ? (
                <details className={styles["disclosure"]} data-attach-detail="">
                  <summary className={styles["cause"]}>{copy.attach.detailLabel}</summary>
                  <pre className={styles["block"]}>{attach.detail}</pre>
                </details>
              ) : null}
            </>
          ) : null}
          {/* §7A.8's remedy rides on the one action rather than on a fourth
              paragraph. The section's requirement is that the refusal NAME the
              file the server looked for — the path above does that — and that
              it not offer to write it. Four stacked paragraphs and a button in
              a ~380px column is the wall the operator read as a broken chat;
              the sentence is still here, on the control it describes, together
              with what the press itself does (§2.3: this route creates a
              runtime from configuration that already exists — it cannot create
              configuration, which is why it is not called "Add a provider"). */}
          <Button
            variant="secondary"
            onClick={retryAttach}
            title={`${copy.attach.actionTitle} ${copy.attach.how}`}
            className={styles["refusalAction"]}
            data-attach-retry=""
            {...(attaching ? { disabled: true as const, reason: copy.composer.sending } : {})}
          >
            {copy.attach.action}
          </Button>
          {attachError !== null ? (
            <p className={styles["cause"]} data-attach-error="">
              {attachError}
            </p>
          ) : null}
        </div>
      ) : null}

      {/* §7A.3(a): ONE line at rest — the word `Context:`, the envelope's
          present members in the fixed order, `+N` for the remainder, and any
          member the operator excluded, said out loud (§7A.3(e)). The toggle is
          attached to it: §7A.10(c) makes the line and the toggle one
          affordance, so the chip form and the composed preview open together.
          C22 mounts the Add-current-view control here exactly while the gap
          it closes is visible. Issue 120 integrates the model control here. */}
      {turn.runId !== null ? <div className={styles["note"]} data-task-action="" role="status">
        <span>{turn.status}</span>
      </div> : null}
      {(attempt?.phase === "sending" || attempt?.phase === "unknown") && turn.runId === null ?
        <details data-submitted-attempt=""><summary>{copy.composer.submittedAttempt}</summary>
          <p>{attempt.submitted.text}</p>
        </details> : null}
      {props.scopePart && state.part && props.scopePart !== state.part ?
        <p className={styles["note"]} data-context-mismatch="">
          {copy.composer.scopeMismatch(props.scopePart, state.part, summary.keys.includes("part"))}{" "}
          <Button variant="quiet" onClick={() => workspaceStore.update({ part: props.scopePart!, selection: null, measure: null })} data-view-scope="">
            {copy.composer.viewScope(props.scopePart)}
          </Button>
        </p> : null}

      <div className={styles["composerShell"]}>
        {/* Paste and drop land here as well as on the button: an operator with
            a screenshot will try all three, and two of them targeting the box
            rather than a 34px control is the whole point. `preventDefault` on
            a drop that carried images stops the browser navigating to the
            file, which is its default and is always wrong here. */}
        <div
          className={styles["inputRow"]}
          data-composer-input-row=""
          onPaste={(event) => {
            const held = imagesFromTransfer(event.clipboardData);
            if (held.length === 0) return;
            event.preventDefault();
            setImages((was) => [...was, ...held]);
          }}
          onDragOver={(event) => {
            if ([...event.dataTransfer.types].includes("Files")) event.preventDefault();
          }}
          onDrop={(event) => {
            const held = imagesFromTransfer(event.dataTransfer);
            if (held.length === 0) return;
            event.preventDefault();
            setImages((was) => [...was, ...held]);
          }}
        >
          <TextInput
            label={turn.canSend ? copy.composer.label : copy.composer.nextDraft}
            hideLabel
            multiline
            rows={promptRows}
            value={text}
            onChange={setText}
            onKeyDown={onPromptKey}
            placeholder={copy.composer.placeholder}
            disabled={!composable}
            inputRef={inputRef}
            className={styles["grow"]}
            data-composer-input=""
          />
          <ImageStrip images={images} onChange={setImages} />
        </div>
        {/* The message box's own bottom row (2026-09-20). The two settings that
            change what THIS message means — model/effort and Plan — sit at the
            leading edge inside the box, with Send at its trailing edge, so the
            controls that compose a message live in the thing being composed.
            `[data-composer-input-row]` stays button-free and
            `[data-composer-input-action]` still wraps Send/Stop; both are
            asserted by name. */}
        <div className={styles["shellBar"]} data-composer-shell-bar="">
          <div className={styles["shellBarLeading"]}>
            <ModelPicker key={sessionId ?? "new"} sessionId={sessionId}
              effort={turnControls.thinkingLevel}
              onEffort={(thinkingLevel) => updateControls({ thinkingLevel })} />
            {/* The view toggle says which way it is set IN THE GLYPH
                (2026-09-20). It was one `view` icon whose only off-state
                signal was the pressed fill, which is state by colour alone
                (§3.13.2). Off, it is the same eye with a slash through it.

                THE CONTEXT SUMMARY IS STRUCK from this row. It printed
                `Context:` plus the envelope's member words and opened a
                disclosure — a readout and a second control, on the row where
                every other member is one control that does one thing. What it
                reported is still true and still sent; it is simply not
                narrated in the box any more. */}
            <Button variant="toggle"
              icon={summary.keys.includes("view") ? "view" : "view-off"}
              iconLabel={copy.composer.addCurrentView}
              pressed={summary.keys.includes("view")}
              title={copy.composer.addCurrentViewWhy}
              onClick={() => {
                if (summary.keys.includes("view")) {
                  toggleChip("view");
                  if (summary.keys.includes("selection")) toggleChip("selection");
                } else addCurrentView();
              }}
              data-context-add-view="" />
            {/* MANUFACTURING CONTEXT, back in the box (2026-09-20).
                
                This control was split onto an outer toolbar when Plan moved
                inside the message box, and then the toolbar was struck —
                which left `ComposerControls` in the tree with no caller and
                the operator with no way to say which process a request is
                about. It belongs beside the other three: they all answer
                "what does THIS message mean", and the process a part is made
                by is exactly that kind of context. */}
            <ComposerControls
              dfmMode={turnControls.dfmMode}
              disabled={!turn.canSend}
              disabledReason={sendReason}
              onDfmMode={(dfmMode) => updateControls({ dfmMode })}
            />
            <ImageAttach images={images} onChange={setImages} />
            <PlanControl
              interactionMode={turnControls.interactionMode}
              disabled={!turn.canSend}
              disabledReason={sendReason}
              onInteractionMode={(interactionMode) => updateControls({ interactionMode })}
            />
          </div>
        </div>
        {/* CANCEL SITS BESIDE SEND, NOT INSTEAD OF IT (fixed 2026-09-20).
            
            These were a ternary — `cancellable ? Cancel : Send` — so while a
            run was in flight `[data-composer-send]` left the DOM entirely.
            That breaks §7A.10(a)/C15: Send is the input row's one target and
            must be PRESENT AND DISABLED WITH A REASON, never absent, because
            "why can't I send?" needs something to point at. It also made
            `toBeDisabled()` fail against an element that did not exist, which
            is how the regression surfaced.
            
            Cancel keeps C15's own rule: it mounts only while a run this tab
            can cancel is in flight, so at rest this row is Send alone. */}
        <div className={styles["inputAction"]} data-composer-input-action="">
          {cancellable ? (
            <Button variant="secondary" icon="stop"
              onClick={cancelTurn} data-composer-cancel=""
              {...(turn.stopRequested && !turn.canRetryStop ? { disabled: true as const, reason: copy.composer.stopRequested } : {})}>
              <span className={styles["srOnly"]}>{turn.canRetryStop ? copy.composer.retryStop : copy.composer.cancel}</span>
            </Button>
          ) : null}
          <Button
            variant={signInPrimary(disabledReason) ? "secondary" : "primary"}
            type="button"
            icon="arrow-up"
            iconLabel={copy.composer.sendMessage}
            title={sendHint}
            className={styles["sendButton"]}
            data-composer-send=""
            onClick={submit}
            {...(sendDisabled ? { disabled: true as const, reason: sendReason,
              ...(sendDescribes ? { reasonElementId: unavailableReasonId } : {}) } : {})}
          />
        </div>
      </div>
      {/* §7A's composer toolbar is STRUCK (2026-09-20). Its last two members —
          Add-current-view and the context disclosure — moved INSIDE the message
          box beside the model and Plan, which is where every control that
          shapes this message now lives. A row with nothing on it is the
          furniture this pass has been removing. */}
      <p className={styles["hint"]} data-composer-hint="">{sendHint}</p>

      {/* §7A.10(b) / C15's negative half: Cancel's row is an EXCEPTION and
          mounts only while a run this tab can cancel is in flight — at rest no
          action row exists at all, empty or otherwise. */}


      {/* §7A.5: a lost POST leaves the text in the box and states that the turn
          may have started. The retry is the OPERATOR's, deliberately: an
          automatic one over an at-least-once route is a duplicate-turn
          generator with a spinner on it. */}
      {post.phase === "unknown" && post.runtimeFault !== true ? (
        <p className={styles["note"]} data-send-unknown="" role="status">
          {turn.runId !== null || turn.terminalRunId !== null ? copy.composer.receiptUncertain : copy.composer.deliveryUncertain}
          {!conversation.checking && conversation.execution?.admission_available === true ? (
            <Button variant="quiet" onClick={() => {
              conversationStore.update(sessionId, c => ({ ...c, attempt: null }));
            }}>{copy.composer.keepDraft}</Button>
          ) : null}
        </p>
      ) : null}

      {post.phase === "refused" ? (
        <div className={styles["note"]} data-composer-refused={post.reason} role="status">
          {post.reason !== "run_in_flight" || typeof post.data["session_id"] !== "string"
            ? <span>{copy.composer.notSent(post.reason)}{post.reason === "model_changed" ? ` ${copy.models.changed}` : ""}</span> : null}
          {/* §7A.5: the refusal NAMES which session holds the live run. The
              ids come from the server's own payload — a client that guessed
              would be naming a session it inferred was busy. */}
          {post.reason === "run_in_flight" && typeof post.data["session_id"] === "string" ? (
            <p data-run-in-flight-session={post.data["session_id"]}>
              {copy.composer.runInFlightHolder(
                holderSessionTitle(
                  post.data["session_id"],
                  props.sessionTitle?.(post.data["session_id"]),
                ),
              )}
            </p>
          ) : null}
          <details>
            <summary>{copy.composer.deliveryDetails}</summary>
            <p>{attempt?.submitted.text}</p>
            <code>{post.reason} {attempt?.holderRun}</code>
          </details>
        </div>
      ) : null}

      {turn.stopNote != null ? (
        <p className={styles["note"]} data-cancel-note="">
          {turn.stopNote}
        </p>
      ) : null}

      {/* THE CONTEXT DISCLOSURE IS STRUCK (2026-09-20), on request.
          
          It was a region holding the envelope's member chips, an advisory
          sentence, and a preformatted dump of the exact block the turn would
          carry. The
          summary line in the message box was its only opener, and that line
          went with it.

          LOST CAPABILITY, named rather than buried: those chips were the only
          UI that could DROP an individual context member before sending —
          `toggleChip` is still the handler, but the view/selection pair is now
          the only thing with a control bound to it. Everything else the
          envelope carries is sent without a way to inspect or remove it from
          this column. `previewContext` still exists and the route is
          unchanged; nothing in the composer calls it any more. */}
    </form>
  );
}



/**
 * §7A.2's create affordance — the blank canvas, said out loud.
 *
 * "After this section lands, the only way to bring a part into existence from
 * the browser is to **type English at an orchestrator agent, which calls
 * `create_part`**. There is no part-creation route, no button, and none is
 * added: §15.9 forbids the workspace inventing model tools and a part is
 * authored source, not a form. What this section owes the operator is therefore
 * not a button but an **entry point** … **A blank canvas the operator has to
 * guess is filled by talking is the same defect as a composer that is not
 * there.**"
 *
 * The profile line is composed from the SERVER's capability facts
 * (`GET /sessions`'s `profiles`), never from a client-side copy of §7A.2's
 * table: "a user who does not know their session cannot delegate reads
 * `scope_denied` as a broken product."
 */
export function NewSessionAction(props: {
  readonly profiles: readonly ProfileCapability[];
  readonly part: string | null;
  readonly pending: boolean;
  readonly onCreate: (profile: "orchestrator" | "part", part: string | null) => void;
}): React.JSX.Element | null {
  const { profiles, part, pending, onCreate } = props;
  const orchestrator = profiles.find((row) => row.profile === "orchestrator");
  const partProfile = profiles.find((row) => row.profile === "part");
  // POST /sessions does not need this list — only the capability line does.
  // A 500 on the same document that raised `data-runtime-fault` leaves
  // `profiles = []`. Hiding the buttons then is the #43 dead-end: the one
  // §7A.2 affordance dies with the read that reported the fault.
  return (
    <div className={styles["create"]} data-session-create="">
      {/* §4.7 (C8): `secondary`, deliberately. The composer mounts in every
          state (§7A.1) and its Send keeps `primary` through `no_session`, so a
          primary here would be a second accent fill in the same frame — the
          exact defect C8 closes. The invitation's prominence is its position
          and its words, not the loudest variant. */}
      <Button
        variant="secondary"
        title={
          orchestrator !== undefined
            ? copy.composer.profileWhat(
                orchestrator.profile,
                orchestrator.can_delegate,
                orchestrator.part_scoped,
              )
            : copy.composer.createOrchestrator
        }
        onClick={() => {
          onCreate("orchestrator", null);
        }}
        data-create-profile="orchestrator"
        {...(pending ? { disabled: true as const, reason: copy.composer.sending } : {})}
      >
        {copy.composer.createOrchestrator}
      </Button>
      {part !== null ? (
        <Button
          variant="secondary"
          title={
            partProfile !== undefined
              ? copy.composer.profileWhat(
                  partProfile.profile,
                  partProfile.can_delegate,
                  partProfile.part_scoped,
                )
              : copy.composer.createPart(part)
          }
          onClick={() => {
            onCreate("part", part);
          }}
          data-create-profile="part"
          // §7.1(b)(3): the part-scoped create is addressable by name wherever
          // it lives — here on the empty-list invitation, and on the `+`
          // control's menu entry beside a drawn tab strip.
          data-session-ask=""
          {...(pending ? { disabled: true as const, reason: copy.composer.sending } : {})}
        >
          {copy.composer.createPart(part)}
        </Button>
      ) : null}
    </div>
  );
}
