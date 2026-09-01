// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `SignInDialog` (INTERFACE.md §23.3, §23.4, §23.14 item 14).
//
// Two flows in one dialog, because they are two answers to one question the
// operator is asking — *how do I attach a model?* — and splitting them into two
// surfaces would make the choice look bigger than it is.
//
// Five clauses this file exists to satisfy, each of which would be a defect if
// it were merely intended:
//
// * **The key field is `type="password"`, `autocomplete="off"`, and has no
//   `name`** (§23.3). The last one is the subtle one: a provider key saved by a
//   password manager under the identity of a loopback page is a credential filed
//   in the wrong place forever. `TextInput secret` carries all three, and no
//   input in this app emits a `name` at all.
// * **Scope has no default and nothing is preselected** (§23.2). The control
//   starts with neither option chosen, so submitting without choosing is
//   refused `credential_scope_required` by the server *and* disabled here with a
//   reason — the two agree rather than one covering for the other.
// * **The subscription disclosure is said BEFORE the operator clicks** (§23.4).
//   "…an operator who later revokes 'that Pi thing they don't remember
//   installing' and finds Hephaestus dead was misled by our silence."
// * **The device code is large and the URI is a link the operator opens in a
//   normal tab** (§23.4). The browser never talks to the provider; the sidecar
//   does the polling. This dialog polls `loginStatus` until complete or a named
//   failure, and `cancelLogin` on dismiss — the API existed; the dialog did not
//   call it.
// * **The paste fallback explains the connection error before it happens**
//   (§23.4). The redirect goes to a loopback address where nothing is
//   listening — by decision, not by accident — so the operator sees a browser
//   error and needs to know that it is the expected outcome and where the answer
//   is. That copy-paste is the cost §23 pays for opening no socket, and the UI
//   pays it out loud.
//
// A DOM contract, consumed by `providers.spec.ts` and by nothing else: every
// control carries a `data-signin-*` attribute naming what it is, and the dialog
// carries `data-signin-flow`. Selectors that read copy would pin wording, which
// §3 forbids.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { WorkspaceError } from "../api/client";
import {
  CREDENTIAL_SCOPES,
  beginLogin,
  cancelLogin,
  completeLogin,
  loginStatus,
  submitKey,
  type CredentialScope,
  type FlowDocument,
  type ProviderRow,
} from "../api/providers";
import { copy } from "../copy";
import { Button, Panel, PanelBody, PanelHeader, PanelNote, Popover, TextInput } from "../system";
import styles from "./SignInDialog.module.css";

/** Which half of the dialog is showing. Closed; §23 adds no third mechanism. */
export type SignInMode = "key" | "subscription";

export interface SignInDialogProps {
  readonly provider: ProviderRow;
  readonly open: boolean;
  readonly onClose: () => void;
  /** Called after a credential actually landed, so the panel can re-read. */
  readonly onSignedIn: () => void;
}

/**
 * The refusal sentence for a named reason.
 *
 * §23.14 item 15: "no reason string constructed at a call site". An unmapped
 * reason falls back to the server's own message rather than to a phrase this
 * file invents — the server named it, and a client that paraphrases a refusal it
 * does not recognise is guessing.
 */
export function refusalText(error: unknown): string {
  if (!(error instanceof WorkspaceError)) return copy.errors.title;
  const known = copy.providers.refusal as Readonly<Record<string, string>>;
  return known[error.reason] ?? error.message;
}

const PENDING_FLOW = new Set(["authorization_pending", "awaiting_input", "slow_down"]);
const FAILED_FLOW = new Set(["failed", "cancelled", "expired"]);

/**
 * What a `loginStatus` body means for an open device-code / authorize-url flow.
 *
 * The client polls THIS; the sidecar polls the provider (§23.4). Pending and
 * `slow_down` stay 200. Completion is `flow.state === "complete"` or the
 * status route flipping to `{type:"oauth"}`. A named failure stops the loop.
 */
export function loginPollOutcome(status: Record<string, unknown>): "pending" | "complete" | "failed" {
  const reason = typeof status.reason === "string" ? status.reason : null;
  if (reason === "authorization_pending" || reason === "slow_down") return "pending";
  if (status.status === "error" && reason !== null) return "failed";

  const nested = status.flow;
  const flowState =
    nested !== null && typeof nested === "object" && typeof (nested as { state?: unknown }).state === "string"
      ? (nested as { state: string }).state
      : typeof status.state === "string" &&
          (PENDING_FLOW.has(status.state) || FAILED_FLOW.has(status.state) || status.state === "complete")
        ? status.state
        : null;

  if (flowState === "complete" || status.type === "oauth") return "complete";
  if (flowState !== null && FAILED_FLOW.has(flowState)) return "failed";
  return "pending";
}

function pollIntervalMs(flow: FlowDocument, status: Record<string, unknown> | null): number {
  const named = typeof status?.reason === "string" ? status.reason : null;
  const nested = status?.flow;
  const flowState =
    nested !== null && typeof nested === "object" && typeof (nested as { state?: unknown }).state === "string"
      ? (nested as { state: string }).state
      : null;
  const seconds = flow.interval_seconds ?? 2;
  const slowed = named === "slow_down" || flowState === "slow_down";
  return Math.max(0, (slowed ? seconds * 2 : seconds) * 1000);
}

export function SignInDialog(props: SignInDialogProps): React.JSX.Element {
  const { provider, open, onClose, onSignedIn } = props;
  const [mode, setMode] = useState<SignInMode>(
    provider.kind === "pi_native" ? "subscription" : "key",
  );
  const [key, setKey] = useState("");
  // NOT initialised to a scope. §23.2: "Omitting it is refused
  // `credential_scope_required`, **not defaulted**." `null` is that absence, and
  // the submit control is disabled with a reason while it holds.
  const [scope, setScope] = useState<CredentialScope | null>(null);
  const [flow, setFlow] = useState<FlowDocument | null>(null);
  const [paste, setPaste] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [confirmRuns, setConfirmRuns] = useState<number | null>(null);

  const dismiss = useCallback((): void => {
    // Idempotent: closing an unstarted dialog is a no-op on the sidecar.
    void cancelLogin(provider.id);
    onClose();
  }, [provider.id, onClose]);

  useEffect(() => {
    if (!open || flow === null) return;
    let cancelled = false;
    let timer = 0;
    const tick = async (waitMs: number): Promise<void> => {
      timer = window.setTimeout(() => {
        void (async () => {
          let status: Record<string, unknown> | null = null;
          try {
            status = await loginStatus(provider.id);
            if (cancelled) return;
            const outcome = loginPollOutcome(status);
            if (outcome === "complete") {
              onSignedIn();
              onClose();
              return;
            }
            if (outcome === "failed") {
              const reason = typeof status.reason === "string" ? status.reason : "authorization_expired";
              const known = copy.providers.refusal as Readonly<Record<string, string>>;
              setRefusal(known[reason] ?? copy.errors.title);
              return;
            }
          } catch (error) {
            if (cancelled) return;
            setRefusal(refusalText(error));
            return;
          }
          if (cancelled) return;
          void tick(pollIntervalMs(flow, status));
        })();
      }, waitMs);
    };
    void tick(pollIntervalMs(flow, null));
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, flow, provider.id, onSignedIn, onClose]);

  const run = async (work: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setRefusal(null);
    try {
      await work();
    } catch (error) {
      // §23.7's confirmed cost: a restart ends live turns, and the operator is
      // told how many before being asked again — never after.
      if (error instanceof WorkspaceError && error.reason === "runs_in_flight") {
        const count = error.data["count"];
        setConfirmRuns(typeof count === "number" ? count : 1);
      }
      setRefusal(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  const submitKeyNow = (confirm: boolean): void => {
    if (scope === null) return;
    void run(async () => {
      await submitKey(provider.id, key, scope, confirm);
      setKey("");
      setConfirmRuns(null);
      onSignedIn();
      onClose();
    });
  };

  const begin = (type: "device_code" | "authorize_url"): void => {
    void run(async () => {
      setFlow(await beginLogin(provider.id, type));
    });
  };

  const complete = (): void => {
    void run(async () => {
      const done = await completeLogin(provider.id, paste);
      setPaste("");
      setFlow(done);
      if (done.state === "complete") {
        onSignedIn();
        onClose();
      }
    });
  };

  return (
    <Popover
      open={open}
      onClose={dismiss}
      label={copy.providers.dialog.title}
      variant="dialog"
      data-signin-dialog={provider.id}
      data-signin-flow={mode}
    >
      <Panel label={copy.providers.dialog.title}>
        <PanelHeader title={copy.providers.dialog.title} eyebrow={provider.name} />
        <PanelBody>
          <div className={styles["modes"]}>
            <Button
              variant="toggle"
              pressed={mode === "key"}
              onClick={() => {
                setMode("key");
              }}
              data-signin-mode="key"
            >
              {copy.providers.dialog.keyLabel}
            </Button>
            <Button
              variant="toggle"
              pressed={mode === "subscription"}
              onClick={() => {
                setMode("subscription");
              }}
              data-signin-mode="subscription"
            >
              {copy.providers.dialog.subscriptionTitle}
            </Button>
          </div>

          {mode === "key" ? (
            <KeyForm
              value={key}
              onValue={setKey}
              scope={scope}
              onScope={setScope}
              busy={busy}
              confirmRuns={confirmRuns}
              onSubmit={submitKeyNow}
            />
          ) : (
            <SubscriptionForm
              flow={flow}
              paste={paste}
              onPaste={setPaste}
              busy={busy}
              onBegin={begin}
              onComplete={complete}
            />
          )}

          {refusal === null ? null : (
            <p className={styles["refusal"]} data-signin-refusal role="alert">
              {refusal}
            </p>
          )}
        </PanelBody>
      </Panel>
    </Popover>
  );
}

interface KeyFormProps {
  readonly value: string;
  readonly onValue: (value: string) => void;
  readonly scope: CredentialScope | null;
  readonly onScope: (scope: CredentialScope) => void;
  readonly busy: boolean;
  readonly confirmRuns: number | null;
  readonly onSubmit: (confirm: boolean) => void;
}

function KeyForm(props: KeyFormProps): React.JSX.Element {
  const { value, onValue, scope, onScope, busy, confirmRuns, onSubmit } = props;
  const empty = value.trim() === "";
  return (
    <>
      <TextInput
        label={copy.providers.dialog.keyLabel}
        value={value}
        onChange={onValue}
        secret
        data-signin-key
      />
      <PanelNote>{copy.providers.dialog.keyHint}</PanelNote>

      <fieldset className={styles["scopes"]} data-signin-scopes>
        <legend className={styles["legend"]}>{copy.providers.dialog.scopeLabel}</legend>
        {CREDENTIAL_SCOPES.map((option) => (
          <Button
            key={option}
            variant="toggle"
            pressed={scope === option}
            onClick={() => {
              onScope(option);
            }}
            data-signin-scope={option}
          >
            {copy.providers.dialog.scope[option]}
          </Button>
        ))}
      </fieldset>
      <PanelNote>{copy.providers.dialog.scopeNote}</PanelNote>
      <PanelNote>
        {scope === null
          ? copy.providers.dialog.scope.serveNote
          : copy.providers.dialog.scope[`${scope}Note` as const]}
      </PanelNote>

      {confirmRuns === null ? null : (
        <p className={styles["confirm"]} data-signin-runs={confirmRuns}>
          {copy.providers.runsInFlight(confirmRuns)}
        </p>
      )}
      <SubmitRow
        busy={busy}
        // The two absences that block submission are named, not merged: the
        // §4.7 rule is that a disabled control must say WHY, and "type a key"
        // and "choose where it lives" are different remedies.
        reason={empty ? copy.providers.dialog.keyLabel : scope === null ? copy.providers.dialog.scopeNote : null}
        label={confirmRuns === null ? copy.providers.dialog.submit : copy.providers.runsInFlightConfirm}
        onSubmit={() => {
          onSubmit(confirmRuns !== null);
        }}
      />
    </>
  );
}

interface SubscriptionFormProps {
  readonly flow: FlowDocument | null;
  readonly paste: string;
  readonly onPaste: (value: string) => void;
  readonly busy: boolean;
  readonly onBegin: (type: "device_code" | "authorize_url") => void;
  readonly onComplete: () => void;
}

function SubscriptionForm(props: SubscriptionFormProps): React.JSX.Element {
  const { flow, paste, onPaste, busy, onBegin, onComplete } = props;
  return (
    <>
      {/* Said before the operator clicks, not after they wonder (§23.4). */}
      <PanelNote>{copy.providers.dialog.subscriptionDisclosure}</PanelNote>
      {flow === null ? (
        <div className={styles["modes"]}>
          {busy ? (
            <Button variant="primary" disabled reason={copy.providers.dialog.waiting}>
              {copy.providers.dialog.submit}
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => {
                onBegin("device_code");
              }}
              data-signin-begin="device_code"
            >
              {copy.providers.dialog.submit}
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => {
              onBegin("authorize_url");
            }}
            data-signin-begin="authorize_url"
          >
            {copy.providers.dialog.pasteLabel}
          </Button>
        </div>
      ) : null}

      {flow?.user_code === undefined ? null : (
        <div data-signin-device-code={flow.user_code}>
          <p className={styles["label"]}>{copy.providers.dialog.deviceCode}</p>
          {/* Rendered large: the operator is reading it off one screen and
              typing it into another. */}
          <p className={styles["code"]}>{flow.user_code}</p>
          {flow.verification_uri === undefined ? null : (
            <a
              className={styles["link"]}
              href={flow.verification_uri}
              target="_blank"
              rel="noreferrer"
              data-signin-verification-uri
            >
              {copy.providers.dialog.deviceCodeOpen}
            </a>
          )}
        </div>
      )}

      {flow?.authorize_url === undefined ? null : (
        <div data-signin-authorize-url>
          <a
            className={styles["link"]}
            href={flow.authorize_url}
            target="_blank"
            rel="noreferrer"
          >
            {copy.providers.dialog.deviceCodeOpen}
          </a>
          <PanelNote>{copy.providers.dialog.pasteHint}</PanelNote>
          <TextInput
            label={copy.providers.dialog.pasteLabel}
            value={paste}
            onChange={onPaste}
            data-signin-paste
          />
          <SubmitRow
            busy={busy}
            reason={paste.trim() === "" ? copy.providers.dialog.pasteLabel : null}
            label={copy.providers.dialog.submit}
            onSubmit={onComplete}
          />
        </div>
      )}
    </>
  );
}

interface SubmitRowProps {
  readonly busy: boolean;
  /** Non-null disables the control and IS the reason it is disabled (§4.7). */
  readonly reason: string | null;
  readonly label: ReactNode;
  readonly onSubmit: () => void;
}

function SubmitRow({ busy, reason, label, onSubmit }: SubmitRowProps): React.JSX.Element {
  const blocked = busy ? copy.providers.dialog.waiting : reason;
  return (
    <div className={styles["actions"]}>
      {blocked === null ? (
        <Button variant="primary" onClick={onSubmit} data-signin-submit>
          {label}
        </Button>
      ) : (
        <Button variant="primary" disabled reason={blocked} data-signin-submit>
          {label}
        </Button>
      )}
    </div>
  );
}
