// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer — the surface that **speaks** (INTERFACE.md §7A).
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
// **6. Session chrome stays a thin client** (issue #13). Model + effort are
// mapped from `GET /providers` using the provider's own model ids — never
// house names. There is no Plan mode in the engine; `[dfm] auto_run` /
// `run_dfm` is the equivalent and stays two controls (§6.4). Add current view
// is an explicit opt-in that opens `POST /context/preview`. No runtime / no
// `providers.json` keeps the named `agent_unavailable` absence.

import { useCallback, useEffect, useMemo, useSyncExternalStore, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { WorkspaceError } from "../../api/client";
import { writeDfmAutoRun, runDfm } from "../../api/dfm";
import { uuid7 } from "../../api/idempotency";
import { keys, useDfm, useProviders } from "../../api/queries";
import { refreshAfterTurn } from "../../api/refresh";
import { attachAgent, type AttachProjection, isAttachCause } from "../../api/attach";
import {
  cancelRun,
  previewContext,
  sendPrompt,
  type ContextDocument,
  type ProfileCapability,
} from "../../api/sessions";
import { copy } from "../../copy";
import { Button, Chip, EmptyState, Select, TextInput } from "../../system";
import { useWorkspaceState } from "../../state/react";
import { labelsForPart, visibilityStore } from "../../state/visibility";
import {
  defaultModel,
  effortOptionsFor,
  isEffortLevel,
  modelKey,
  modelsFrom,
  showDfmChrome,
  showModelChrome,
  type EffortLevel,
} from "../../stream/composerChrome";
import { chipsFor, envelopeFor, type ContextChip } from "../../stream/composerContext";
import type { ContextMember } from "../../api/sessions";
import { Fact } from "../Fact";
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
  /** That session's profile, from `GET /sessions`. Rendered, never inferred. */
  readonly profile: string | null;
  /** The §7A.8 attach projection when the runtime is missing, else `null`. */
  readonly attach: AttachProjection | null;
  /** `true` when the session routes are refusing `agent_unavailable`. */
  readonly agentUnavailable: boolean;
  /** The run of the last live frame for this session (§7A.5). */
  readonly liveRunId: string | null;
  /** Whether this tab's socket is `live` — cancel needs it (§7A.5). */
  readonly streamLive: boolean;
  /** Fired after a turn settles, so the panel can refetch its own session list. */
  readonly onTurnSettled?: (() => void) | undefined;
}

/** What the POST is doing. `unknown` is a *state*, not an error to swallow. */
type Post =
  | { readonly phase: "idle" }
  | { readonly phase: "sending" }
  | { readonly phase: "unknown" }
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
  const { sessionId, profile, attach, agentUnavailable, liveRunId, streamLive } = props;
  const client = useQueryClient();
  const state = useWorkspaceState();
  const hidden = useSyncExternalStore(
    visibilityStore.subscribe,
    visibilityStore.getSnapshot,
    visibilityStore.getSnapshot,
  );
  const hiddenLabels = useMemo(() => labelsForPart(hidden, state.part), [hidden, state.part]);

  const [text, setText] = useState("");
  const [post, setPost] = useState<Post>({ phase: "idle" });
  const [dropped, setDropped] = useState<ReadonlySet<ContextMember>>(() => new Set());
  const [added, setAdded] = useState<ReadonlySet<ContextMember>>(() => new Set());
  const [disclosed, setDisclosed] = useState(false);
  const [preview, setPreview] = useState<ContextDocument | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [cancelNote, setCancelNote] = useState<string | null>(null);
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const chips = useMemo(() => chipsFor(state, hiddenLabels), [state, hiddenLabels]);
  const envelope = useMemo(
    () => envelopeFor(state, hiddenLabels, dropped, added),
    [state, hiddenLabels, dropped, added],
  );

  // -- session chrome (issue #13) ----------------------------------------
  //
  // Model + effort are a projection of `GET /providers`. They render only
  // when a runtime is attached *and* that document named at least one model;
  // an empty picker would read as a signed-in agent that is not there.
  // DFM is the engine equivalent of a Plan/DFM chip: `[dfm] auto_run` and
  // `run_dfm`, two controls, because collapsing them would imply a tool
  // argument that does not exist (§6.4). There is no Plan mode to toggle.
  const providers = useProviders();
  const models = useMemo(() => modelsFrom(providers.data), [providers.data]);
  const modelChrome = showModelChrome(agentUnavailable, models);
  const [modelChoice, setModelChoice] = useState("");
  const [effortChoice, setEffortChoice] = useState<EffortLevel>("off");
  // Derived, not synced in an effect: a missing or stale choice falls back to
  // the first declared model / `off`. The picker writes the choice; the
  // document decides whether that choice still exists.
  const selectedModel = models.find((row) => modelKey(row) === modelChoice) ?? defaultModel(models);
  const resolvedChoice = selectedModel === null ? "" : modelKey(selectedModel);
  const effortOptions = effortOptionsFor(selectedModel);
  const effort = effortOptions.includes(effortChoice) ? effortChoice : "off";

  const dfm = useDfm(state.part);
  const [dfmBusy, setDfmBusy] = useState<"auto_run" | "run" | null>(null);
  const [dfmError, setDfmError] = useState<string | null>(null);

  const toggleAutoRun = useCallback(() => {
    if (dfm.data === undefined || dfmBusy !== null) return;
    setDfmBusy("auto_run");
    setDfmError(null);
    void writeDfmAutoRun(!dfm.data.auto_run, uuid7())
      .then(() => {
        if (state.part !== null) {
          void client.invalidateQueries({ queryKey: keys.dfm(state.part) });
        }
      })
      .catch((cause: unknown) => {
        setDfmError(cause instanceof WorkspaceError ? cause.message : copy.composer.dfmWriting);
      })
      .finally(() => {
        setDfmBusy(null);
      });
  }, [client, dfm.data, dfmBusy, state.part]);

  const runDfmNow = useCallback(() => {
    if (state.part === null || dfmBusy !== null) return;
    setDfmBusy("run");
    setDfmError(null);
    void runDfm(state.part, uuid7())
      .then(() => {
        refreshAfterTurn(client, state.part);
      })
      .catch((cause: unknown) => {
        setDfmError(cause instanceof WorkspaceError ? cause.message : copy.composer.dfmRunning);
      })
      .finally(() => {
        setDfmBusy(null);
      });
  }, [client, dfmBusy, state.part]);

  const addCurrentView = useCallback(() => {
    setDropped((previous) => {
      const next = new Set(previous);
      next.delete("view");
      if (state.selection !== null) next.delete("selection");
      return next;
    });
    setAdded((previous) => {
      const next = new Set(previous);
      next.add("view");
      if (state.selection !== null) next.add("selection");
      return next;
    });
    setDisclosed(true);
  }, [state.selection]);

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
      : refusedRunInFlight
        ? "run_in_flight"
        : null;

  const composerState: ComposerState =
    disabledReason !== null
      ? "disabled"
      : post.phase === "sending"
        ? liveRunId === null
          ? "sending"
          : "running"
        : "idle";

  // §7A.5's named limit, rendered with its reason rather than as a dead button.
  // The window is one model round-trip; saying so is what keeps it from reading
  // as a broken control.
  const cancellable = post.phase === "sending" && liveRunId !== null && streamLive;
  const cancelWhy =
    post.phase !== "sending"
      ? copy.composer.cancelIdle
      : !streamLive
        ? copy.composer.cancelNoStream
        : copy.composer.cancelNoRun;

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
  useEffect(() => {
    if (!disclosed) return;
    let live = true;
    void previewContext(envelope)
      .then((document) => {
        if (!live) return;
        setPreview(document);
        setPreviewError(null);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setPreview(null);
        setPreviewError(cause instanceof Error ? cause.message : copy.composer.discloseFailed);
      });
    return () => {
      live = false;
    };
  }, [disclosed, envelope]);

  const toggleChip = useCallback((key: ContextMember) => {
    setDropped((previous) => {
      const next = new Set(previous);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }, []);

  // -- the turn -----------------------------------------------------------

  const submit = useCallback(() => {
    if (sessionId === null || text.trim() === "" || post.phase === "sending") return;
    setCancelNote(null);
    setPost({ phase: "sending" });
    void sendPrompt(sessionId, text, envelope)
      .then((document) => {
        // §7A.6: THE PROMPT RESPONSE IS THE AUTHORITY THAT THE TURN IS OVER.
        // Not the `terminal` event, which is live-only and never appears in a
        // history page — a tab that resynced across the end of its own run
        // could lose it, and does not need it.
        setPost({ phase: "idle" });
        setText("");
        // §7A.11: refetch the server projection. Never a merge of the turn's
        // tool results, and never a move of the pin.
        refreshAfterTurn(client, state.part);
        props.onTurnSettled?.();
        void document;
      })
      .catch((cause: unknown) => {
        if (cause instanceof WorkspaceError) {
          // A NAMED refusal is an answer, and it keeps the operator's text.
          setPost({
            phase: "refused",
            reason: cause.reason,
            message: cause.message,
            data: cause.data,
          });
          return;
        }
        // The POST did not come back. §7A.5: the turn MAY have started, so it
        // is not retried automatically and the stream is named as the authority.
        setPost({ phase: "unknown" });
      });
  }, [sessionId, text, post.phase, envelope, client, state.part, props]);

  const cancel = useCallback(() => {
    if (liveRunId === null) return;
    void cancelRun(liveRunId)
      .then((document) => {
        setCancelNote(copy.composer.cancelled(document.abandoned_questions));
      })
      .catch(() => {
        // A cancel that does not come back changes nothing this client can
        // report honestly; the run's own terminal is what settles it.
        setCancelNote(null);
      });
  }, [liveRunId]);

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
        setAttachError(
          cause instanceof WorkspaceError ? cause.message : copy.composer.attachFailed,
        );
      })
      .finally(() => {
        setAttaching(false);
      });
  }, [client]);

  const sendDisabled = disabledReason !== null || text.trim() === "" || post.phase === "sending";
  const sendReason =
    disabledReason !== null
      ? copy.composer.disabled[disabledReason]
      : post.phase === "sending"
        ? copy.composer.sending
        : copy.composer.placeholder;

  return (
    <form
      className={styles["composer"]}
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
            body={copy.composer.disabled.agent_unavailable}
            density="inline"
          />
          {attach !== null ? (
            <>
              <p className={styles["cause"]} data-attach-cause={attach.cause ?? ""}>
                {isAttachCause(attach.cause)
                  ? copy.composer.attachCause[attach.cause]
                  : copy.composer.attachCause.sidecar_failed}
              </p>
              <p className={styles["path"]} data-attach-path={attach.config_path}>
                <Chip tone="code">{attach.config_path}</Chip>
              </p>
              {attach.detail !== undefined ? (
                <p className={styles["cause"]} data-attach-detail="">
                  {attach.detail}
                </p>
              ) : null}
              <p className={styles["cause"]}>{copy.composer.attachHow}</p>
            </>
          ) : null}
          <Button
            variant="secondary"
            onClick={retryAttach}
            data-attach-retry=""
            {...(attaching ? { disabled: true as const, reason: copy.composer.sending } : {})}
          >
            {copy.composer.attachRetry}
          </Button>
          {attachError !== null ? (
            <p className={styles["cause"]} data-attach-error="">
              {attachError}
            </p>
          ) : null}
        </div>
      ) : null}

      {/* Session chrome: model + effort from GET /providers, DFM as the
          engine equivalent of a Plan/DFM chip, and Add current view. Existing
          `data-*` selectors on the form and the chip row are unchanged. */}
      <div className={styles["chrome"]} data-composer-chrome="">
        {modelChrome && selectedModel !== null ? (
          <>
            <Select
              label={copy.composer.model}
              hideLabel
              value={resolvedChoice}
              options={models.map((row) => modelKey(row))}
              onChange={setModelChoice}
              data-composer-model={selectedModel.id}
              data-composer-provider={selectedModel.providerId}
            />
            {selectedModel.reasoning ? (
              <Select
                label={copy.composer.effort}
                hideLabel
                value={effort}
                options={[...effortOptions]}
                onChange={(value) => {
                  if (isEffortLevel(value)) setEffortChoice(value);
                }}
                data-composer-effort={effort}
              />
            ) : (
              <span className={styles["note"]} data-composer-effort="off" data-composer-effort-absent="">
                {copy.composer.effortOff}
              </span>
            )}
          </>
        ) : null}

        {showDfmChrome(agentUnavailable, state.part, dfm.data !== undefined) === "chip" &&
        dfm.data !== undefined ? (
          <div className={styles["dfm"]} data-composer-dfm="">
            <Chip data-dfm-auto-run={String(dfm.data.auto_run)}>
              <Fact source="dfm.auto_run" value={dfm.data.auto_run}>
                {dfm.data.auto_run ? copy.dfm.autoRunOn : copy.dfm.autoRunOff}
              </Fact>
            </Chip>
            <Button
              variant="toggle"
              pressed={dfm.data.auto_run}
              onClick={toggleAutoRun}
              data-dfm-auto-run-toggle=""
              {...(dfmBusy !== null
                ? { disabled: true as const, reason: copy.composer.dfmWriting }
                : {})}
            >
              {copy.composer.dfmAutoRun}
            </Button>
            <Button
              variant="quiet"
              onClick={runDfmNow}
              data-dfm-run=""
              {...(dfmBusy !== null
                ? { disabled: true as const, reason: copy.composer.dfmRunning }
                : {})}
            >
              {copy.composer.dfmRun}
            </Button>
          </div>
        ) : showDfmChrome(agentUnavailable, state.part, dfm.data !== undefined) === "absent" ? (
          <span className={styles["note"]} data-composer-dfm-absent="">
            {copy.composer.dfmNoPart}
          </span>
        ) : null}

        <Button variant="quiet" onClick={addCurrentView} data-context-add-view="">
          {copy.composer.addCurrentView}
        </Button>
      </div>
      {dfmError !== null ? (
        <p className={styles["note"]} data-composer-dfm-error="">
          {dfmError}
        </p>
      ) : null}

      {/* §7A.3's chip row: the references this turn carries, every one
          removable. The chips render §4.5 state — navigation, not fact — so
          none goes through `<Fact>` and none carries a `data-source` (§7A.10). */}
      <ul className={styles["chips"]} data-context-chips="" aria-label={copy.composer.contextHeading}>
        {chips.map((chip) => (
          <ContextChipRow
            key={chip.key}
            chip={chip}
            dropped={dropped.has(chip.key)}
            onToggle={toggleChip}
          />
        ))}
      </ul>

      <TextInput
        label={copy.composer.label}
        hideLabel
        multiline
        rows={3}
        value={text}
        onChange={setText}
        placeholder={copy.composer.placeholder}
        disabled={disabledReason !== null || post.phase === "sending"}
        data-composer-input=""
      />

      <div className={styles["actions"]}>
        <Button
          variant="primary"
          type="submit"
          data-composer-send=""
          {...(sendDisabled ? { disabled: true as const, reason: sendReason } : {})}
        >
          {post.phase === "sending" ? copy.composer.sending : copy.composer.send}
        </Button>
        <Button
          variant="quiet"
          onClick={cancel}
          data-composer-cancel=""
          {...(cancellable ? {} : { disabled: true as const, reason: cancelWhy })}
        >
          {copy.composer.cancel}
        </Button>
        <Button
          variant="quiet"
          onClick={() => {
            setDisclosed((open) => !open);
          }}
          pressed={disclosed}
          data-context-disclose=""
        >
          {disclosed ? copy.composer.discloseHide : copy.composer.disclose}
        </Button>
      </div>

      {/* §7A.5: a lost POST leaves the text in the box and states that the turn
          may have started. The retry is the OPERATOR's, deliberately: an
          automatic one over an at-least-once route is a duplicate-turn
          generator with a spinner on it. */}
      {post.phase === "unknown" ? (
        <div className={styles["note"]} data-send-unknown="">
          <strong>{copy.composer.sendUnknownTitle}</strong>
          <p>{copy.composer.sendUnknown}</p>
          <Button variant="secondary" onClick={submit} data-composer-retry="">
            {copy.composer.retry}
          </Button>
        </div>
      ) : null}

      {post.phase === "refused" ? (
        <div className={styles["note"]} data-composer-refused={post.reason}>
          <strong>{copy.errors.title}</strong>
          <p>
            {post.reason === "run_in_flight"
              ? copy.composer.disabled.run_in_flight
              : post.message}
          </p>
          {/* §7A.5: the refusal NAMES which session holds the live run. The
              ids come from the server's own payload — a client that guessed
              would be naming a session it inferred was busy. */}
          {post.reason === "run_in_flight" && typeof post.data["session_id"] === "string" ? (
            <p data-run-in-flight-session={post.data["session_id"]}>
              {copy.composer.runInFlightHolder(post.data["session_id"])}
            </p>
          ) : null}
        </div>
      ) : null}

      {cancelNote !== null ? (
        <p className={styles["note"]} data-cancel-note="">
          {cancelNote}
        </p>
      ) : null}

      {disclosed ? (
        <div className={styles["disclosure"]} data-context-preview="">
          <p className={styles["note"]}>{copy.composer.discloseAdvisory}</p>
          {previewError !== null ? (
            <p className={styles["note"]} data-context-preview-error="">
              {previewError}
            </p>
          ) : preview === null ? null : preview.block === "" ? (
            <p className={styles["note"]} data-context-preview-empty="">
              {copy.composer.discloseEmpty}
            </p>
          ) : (
            <>
              {preview.truncated ? (
                <p className={styles["note"]} data-context-truncated="">
                  {copy.composer.discloseTruncated}
                </p>
              ) : null}
              <pre className={styles["block"]} data-context-block="">
                {preview.block}
              </pre>
            </>
          )}
        </div>
      ) : null}
    </form>
  );
}

/** One removable reference. A chip is never a fact (§7A.10, §4.6). */
function ContextChipRow(props: {
  readonly chip: ContextChip;
  readonly dropped: boolean;
  readonly onToggle: (key: ContextMember) => void;
}): React.JSX.Element {
  const { chip, dropped, onToggle } = props;
  const label = copy.composer.contextKey[chip.key];
  return (
    <li
      className={styles["chip"]}
      data-context-key={chip.key}
      {...(chip.value !== null ? { "data-context-value": chip.value } : {})}
      {...(chip.count !== null ? { "data-context-count": chip.count } : {})}
      {...(dropped ? { "data-context-dropped": "" } : {})}
    >
      <Chip tone="label">{label}</Chip>
      <Chip tone="code">
        {chip.count !== null ? copy.composer.hiddenCount(chip.count) : (chip.value ?? "")}
      </Chip>
      <Button
        variant="quiet"
        icon="close"
        iconLabel={copy.composer.contextDrop(label)}
        pressed={dropped}
        onClick={() => {
          onToggle(chip.key);
        }}
        data-context-drop={chip.key}
      />
    </li>
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
  return (
    <div className={styles["create"]} data-session-create="">
      {orchestrator !== undefined ? (
        <>
          <Button
            variant="primary"
            onClick={() => {
              onCreate("orchestrator", null);
            }}
            data-create-profile="orchestrator"
            {...(pending ? { disabled: true as const, reason: copy.composer.sending } : {})}
          >
            {copy.composer.createOrchestrator}
          </Button>
          <p className={styles["note"]} data-profile-what="orchestrator">
            {copy.composer.profileWhat(
              orchestrator.profile,
              orchestrator.can_delegate,
              orchestrator.part_scoped,
            )}
          </p>
        </>
      ) : null}
      {partProfile !== undefined && part !== null ? (
        <>
          <Button
            variant="secondary"
            onClick={() => {
              onCreate("part", part);
            }}
            data-create-profile="part"
            {...(pending ? { disabled: true as const, reason: copy.composer.sending } : {})}
          >
            {copy.composer.createPart(part)}
          </Button>
          <p className={styles["note"]} data-profile-what="part">
            {copy.composer.profileWhat(
              partProfile.profile,
              partProfile.can_delegate,
              partProfile.part_scoped,
            )}
          </p>
        </>
      ) : null}
      {/* §7A.2: at-least-once is the stated consequence and the UI carries it.
          There is no route that closes a session and none is invented. */}
      <p className={styles["note"]} data-orphan-note="">
        {copy.composer.orphanNote}
      </p>
    </div>
  );
}
