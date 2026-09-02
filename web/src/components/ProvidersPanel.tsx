// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ProvidersPanel` (INTERFACE.md §23.8, §23.14 items 14 and 19).
//
// **The success condition is not "the panel says connected."** §23.0 states it
// exactly: `agent_unavailable` disappears → `GET /sessions` returns → the empty
// state becomes an action → no session → create one → prompt it. "A sign-in
// surface that ends at a green checkmark has not answered the complaint." So
// this panel's empty state is an *action*, and after a credential lands it calls
// `onAttached` so the shell can put the composer in front of the operator
// instead of leaving them to find it.
//
// Five properties this file is responsible for:
//
// * **Two axes, never collapsed** (§23.8). `source` answers *what would I have
//   to change to change this?*; `health` answers *does it work?* There is no
//   combined light, and there is no field for one — a green dot meaning "valid
//   90 seconds ago" is a claim the design cannot keep.
// * **Health is LAST OBSERVED** (§23.8). The row renders "accepted 14:32" and
//   the timestamp is a `Fact` with `last_observed_at` as its source, so the
//   staleness is on screen rather than in a footnote. There is no validity ping
//   on mount and no keepalive: an unsolicited outbound request from a local tool
//   burns provider rate limit to answer a question the next real turn answers
//   for free.
// * **No masked key tail. Not four characters, not two** (§23.8, §15.41). The
//   panel renders the provider id, the source state and the *variable name* — a
//   name is not a secret — and nothing derived from a credential.
// * **Discovery is an act** (§23.14 item 19). Nothing here adopts on render, on
//   hover, or on selection, and `discover()` is called from one click handler
//   and from nowhere else in this file. §15.41's *no background credential
//   probe* is unrelaxed by the 2026-08-28 ruling.
// * **Egress hosts are listed permanently** (§23.3, §23.13). "A silent
//   redirection is not available; a loud one is." The list is a file a reviewer
//   can read, and this is the panel that reads it back.
//
// AMENDED 2026-09-02 (§0.2c — C9, C13, C14):
//
// * **`primary` is availability, not invitation** (§23.8, C9). The sign-in
//   action renders `data-variant="primary"` ONLY while the composer carries
//   `data-disabled-reason="agent_unavailable"` — the runtime's own *current*
//   answer, read from `stream/composerGate.ts`'s store, which the mounted
//   composer publishes. The struck alternative — keying off "no usable
//   provider row" — read last-observed health, which is never current, and
//   could mint a second primary beside an enabled Send. In every other state,
//   including every credential rejected or expired (§23.10 fails the next run;
//   it never disables the composer), the action is `secondary` like rotate and
//   the health axis carries the bad news. While the exception holds, C8
//   (§4.7) demotes the disabled Send, so the shell count stays at one — and at
//   most ONE sign-in action here is promoted, for the same reason.
// * **One `MODEL PROVIDERS` section, at most one resting eyebrow** (C13). The
//   `SIGN IN` eyebrow and its duplicate heading do not render in any state;
//   provider rows, the sign-in/rotate action, and the discovery affordance are
//   children of the one titled section, and the discovery eyebrow waits for
//   the details face.
// * **The discovery button carries its privacy fact at rest** (C14). One
//   ≤ 20-word caption — reads-home-dir-only-on-press, nothing-used-until-
//   adopted — visible whenever the control renders, as a recorded exception to
//   §0.2b's quiet resting path. The fuller §23.5 mechanism stays behind the
//   disclosure.
//
// DOM contract, consumed by `providers.spec.ts`: `data-provider`,
// `data-provider-source`, `data-provider-health`, `data-provider-available`,
// `data-discovery`, `data-discovery-kind`, `data-discovery-adopt`,
// `data-providers-empty`, `data-providers-attach`, `data-auth-linked`.
// Selectors read attributes, never copy (§3).

import { useState, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { WorkspaceError } from "../api/client";
import { attachAgent } from "../api/attach";
import { keys, useProviders } from "../api/queries";
import {
  adopt,
  discover,
  signOut,
  unlinkAuthSource,
  type DiscoveryOffer,
  type ProviderRow,
  type ProvidersDocument,
} from "../api/providers";
import { copy } from "../copy";
import { composerGateStore, signInPrimary } from "../stream/composerGate";
import {
  Button,
  Chip,
  DataTable,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelNote,
  PanelSection,
  StatusBadge,
  formatObservedAt,
  type ChipStatus,
} from "../system";
import { Fact } from "./Fact";
import { SignInDialog, refusalText } from "./SignInDialog";
import styles from "./ProvidersPanel.module.css";

export interface ProvidersPanelProps {
  /** Called whenever a credential change may have made sessions reachable. */
  readonly onAttached?: (() => void) | undefined;
}

/**
 * §23.7's per-provider verification, mapped onto the system's chip vocabulary.
 *
 * `null` — no sidecar has answered — is `unknown` rather than `ok`: a provider
 * nothing has verified is not a verified provider, and the difference is the
 * whole of the no-substitution property.
 */
export function availabilityChip(available: boolean | null): ChipStatus {
  if (available === null) return "unknown";
  return available ? "ok" : "error";
}

/**
 * Presentation of `last_observed_at` — never welded into the health Fact.
 *
 * Two fields, two attributions (#94). A clock without a date hid a three-day-old
 * observation; `formatObservedAt` prints a date or a relative age when the
 * observation is not from today.
 */
export function healthObserved(row: ProviderRow, now: Date = new Date()): string | null {
  if (row.last_observed_at === null) return null;
  return `${copy.providers.healthStale} ${formatObservedAt(row.last_observed_at, now)}`;
}

export function ProvidersPanel(props: ProvidersPanelProps): React.JSX.Element {
  const { onAttached } = props;
  // `GET /providers` and NOTHING else on mount. It reads a file the serve
  // already owns; it performs no discovery, opens no flow, and asks no provider
  // anything (§15.41). `useProviders` is the ONLY query this panel runs.
  const query = useProviders();
  const client = useQueryClient();
  const [offers, setOffers] = useState<readonly DiscoveryOffer[] | null>(null);
  const [dialogFor, setDialogFor] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Collapsed by default: the full configuration table + discovery explainer
  // put Sign-in buttons at ~3000px in the rail. Compact keeps the actions
  // inside the rail box; details stay one click away.
  const [detailsOpen, setDetailsOpen] = useState(false);
  const document_: ProvidersDocument | null = query.data ?? null;

  // §23.8 (C9): the ONE fact the exception keys off — the composer's current
  // `data-disabled-reason`, published by the mounted composer. Never derived
  // from this panel's own rows: health is last observed, not current.
  const gateReason = useSyncExternalStore(
    composerGateStore.subscribe,
    composerGateStore.getSnapshot,
    composerGateStore.getSnapshot,
  );
  const signInLoud = signInPrimary(gateReason);

  const reload = async (): Promise<void> => {
    await client.invalidateQueries({ queryKey: keys.providers() });
  };

  const act = (work: () => Promise<void>): void => {
    setBusy(true);
    setRefusal(null);
    void (async () => {
      try {
        await work();
      } catch (error) {
        setRefusal(refusalText(error));
        if (error instanceof WorkspaceError && error.reason === "runs_in_flight") {
          // Surfaced, never swallowed: the operator is told what a restart
          // would end, and re-confirms in the dialog (§23.7).
          setDialogFor(dialogFor);
        }
      } finally {
        setBusy(false);
      }
    })();
  };

  const afterCredentialChange = (): void => {
    // EVERYTHING is invalidated, not just this panel's read. §23.0's success
    // condition is that `agent_unavailable` disappears and `GET /sessions`
    // starts returning — a credential change is the one event in this app that
    // can flip a whole surface from refusing to serving, so re-reading only the
    // panel that caused it would leave the rest of the workspace showing a
    // refusal that is no longer true.
    void client.invalidateQueries();
    onAttached?.();
  };

  if (document_ === null) {
    // A named state, not a blank one (§4.4): either the read is in flight or it
    // was refused, and the two do not render the same.
    const note = query.error === null ? copy.absent.loading : refusalText(query.error);
    return (
      <Panel
        label={copy.providers.title}
        className={styles["panel"]}
        data-providers-collapsed=""
      >
        <PanelHeader title={copy.providers.title} />
        <PanelBody className={styles["body"]}>
          <PanelNote>{refusal ?? note}</PanelNote>
        </PanelBody>
      </Panel>
    );
  }

  const rows = document_.providers;
  const dialogRow = rows.find((row) => row.id === dialogFor) ?? null;

  return (
    <Panel
      label={copy.providers.title}
      className={styles["panel"]}
      {...(detailsOpen ? { "data-providers-expanded": "" } : { "data-providers-collapsed": "" })}
    >
      {/* §23.8 (C13): the one heading. No eyebrow here — the resting face
          carries at most one, and it belongs to a *group* below, never to a
          `SIGN IN` restatement of this title. */}
      <PanelHeader
        title={copy.providers.title}
        actions={
          <Button
            variant="quiet"
            expanded={detailsOpen}
            onClick={() => {
              setDetailsOpen((open) => !open);
            }}
            data-providers-details=""
          >
            {detailsOpen ? copy.providers.detailsHide : copy.providers.detailsShow}
          </Button>
        }
      />
      <PanelBody className={styles["body"]}>
        {detailsOpen ? (
          <>
            {/* §23.2: the file, its mode, and — when it is not ours — a sentence
                saying we report the mode rather than change it. */}
            <DataTable
              rows={[
                {
                  key: "config",
                  label: copy.providers.configPath,
                  value: <Fact mono source="providers.config_path" value={document_.config_path} />,
                },
                {
                  key: "mode",
                  label: copy.providers.fileMode,
                  value: (
                    <Fact source="providers.file_mode" value={document_.file_mode} />
                  ),
                  ...(document_.config_exists && !document_.file_mode_private
                    ? { note: copy.providers.fileModeOpen }
                    : {}),
                },
                {
                  key: "allowlist",
                  label: copy.providers.allowlist,
                  value:
                    document_.credential_allowlist.length === 0 ? (
                      copy.providers.noneRecorded
                    ) : (
                      <>
                        {document_.credential_allowlist.map((name) => (
                          <Chip key={name} tone="code">
                            {name}
                          </Chip>
                        ))}
                      </>
                    ),
                  note: copy.providers.allowlistNote,
                },
              ]}
            />

            {document_.auth_source === null ? null : (
              <PanelSection eyebrow={copy.providers.authSource}>
                <Fact mono source="providers.auth_source" value={document_.auth_source} />
                {document_.auth_source_linked ? (
                  <div data-auth-linked>
                    <PanelNote>{copy.providers.authSourceLinked}</PanelNote>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        act(async () => {
                          await unlinkAuthSource();
                          await reload();
                        });
                      }}
                      data-auth-unlink
                    >
                      {copy.providers.unlink}
                    </Button>
                  </div>
                ) : null}
              </PanelSection>
            )}
          </>
        ) : null}

        {/* §23.13 / G10C: egress acknowledgements are on disk AND on screen,
            permanently. Compact may hide the configuration table; it may not
            unmount this list. The long note waits for details. */}
        {document_.egress_acknowledged.length === 0 ? null : (
          <PanelSection eyebrow={copy.providers.egressHosts}>
            {detailsOpen ? <PanelNote>{copy.providers.egressNote}</PanelNote> : null}
            <DataTable
              rows={document_.egress_acknowledged.map((row) => ({
                key: row.host,
                label: <Fact mono source="providers.egress_acknowledged.host" value={row.host} />,
                value: <Fact source="providers.egress_acknowledged.at" value={row.at} />,
                attrs: { "data-egress-host": row.host },
              }))}
            />
          </PanelSection>
        )}

        {rows.length === 0 ? (
          <div data-providers-empty>
            <EmptyState
              icon="info"
              title={copy.providers.emptyTitle}
              body={copy.providers.emptyBody}
              density="inline"
            />
          </div>
        ) : (
          // §23.8 (C13): the rows are children of the ONE titled section. The
          // eyebrow that used to sit here rendered this panel's own title a
          // second time — the §0.2b "the word 'session' four times" defect,
          // replayed with "provider" — so no eyebrow names the group at all.
          <div data-provider-rows="">
            {rows.map((row, index) => (
              <ProviderRowView
                key={row.id}
                row={row}
                busy={busy}
                compact={!detailsOpen}
                // §23.8 (C9) / §4.7 (C8): while the composer is
                // `agent_unavailable`, exactly ONE sign-in action takes
                // `primary` — the first row still without a credential, else
                // the first row — because the shell-wide count-of-one is the
                // clause, not "every sign-in shouts".
                signInVariant={
                  signInLoud &&
                  index ===
                    (rows.some((r) => r.source === "none")
                      ? rows.findIndex((r) => r.source === "none")
                      : 0)
                    ? "primary"
                    : "secondary"
                }
                onOpenDetails={() => {
                  setDetailsOpen(true);
                }}
                onSignIn={() => {
                  setDialogFor(row.id);
                }}
                onSignOut={() => {
                  act(async () => {
                    await signOut(row.id);
                    afterCredentialChange();
                  });
                }}
              />
            ))}
          </div>
        )}

        {/* §23.0's success condition: the attach that makes sessions reachable
            is an action on this panel, not a restart in a terminal. */}
        {document_.attach.attached ? null : (
          // §4.7 (C8): `secondary`. The attach re-read is a remedy, not the
          // sign-in action C9 promotes, and a primary here would stand beside
          // the promoted Sign-in as a second accent fill.
          <Button
            variant="secondary"
            onClick={() => {
              act(async () => {
                await attachAgent();
                afterCredentialChange();
              });
            }}
            data-providers-attach
          >
            {copy.providers.addProvider}
          </Button>
        )}

        <DiscoverySection
          offers={offers}
          busy={busy}
          compact={!detailsOpen}
          signedIn={rows.some((row) => row.source !== "none")}
          onDiscover={() => {
            // THE ONLY call site. Never on mount, never on a timer, never as a
            // side effect of another action (§15.41, §23.5).
            act(async () => {
              setOffers((await discover()).sources);
            });
          }}
          onAdopt={(offer) => {
            act(async () => {
              await adopt(offer.discovery_id);
              setOffers(null);
              afterCredentialChange();
            });
          }}
        />

        {refusal === null ? null : (
          <p className={styles["refusal"]} role="alert" data-providers-refusal>
            {refusal}
          </p>
        )}
      </PanelBody>

      {dialogRow === null ? null : (
        <SignInDialog
          provider={dialogRow}
          open
          onClose={() => {
            setDialogFor(null);
          }}
          onSignedIn={afterCredentialChange}
        />
      )}
    </Panel>
  );
}

interface ProviderRowViewProps {
  readonly row: ProviderRow;
  readonly busy: boolean;
  readonly compact: boolean;
  /**
   * §23.8 (C9): `primary` ONLY while the composer's current
   * `data-disabled-reason` is `agent_unavailable`, and then on at most one
   * row. The panel holds the predicate; this row only draws its verdict.
   */
  readonly signInVariant: "primary" | "secondary";
  readonly onOpenDetails: () => void;
  readonly onSignIn: () => void;
  readonly onSignOut: () => void;
}

function ProviderRowView(props: ProviderRowViewProps): React.JSX.Element {
  const { row, busy, compact, signInVariant, onOpenDetails, onSignIn, onSignOut } = props;
  const signedIn = row.source !== "none";
  const actions = (
    <div className={styles["actions"]}>
      {/* C9: sign-in/rotate is `secondary` in every state — all credentials
          rejected included, where the health axis carries the bad news — and
          `primary` only under the composer's own `agent_unavailable`. */}
      <Button
        variant={signInVariant}
        onClick={onSignIn}
        data-provider-signin={row.id}
      >
        {signedIn ? copy.providers.rotate : copy.providers.signIn}
      </Button>
      {signedIn ? (
        busy ? (
          <Button variant="quiet" disabled reason={copy.providers.dialog.waiting}>
            {copy.providers.signOut}
          </Button>
        ) : (
          <Button variant="quiet" onClick={onSignOut} data-provider-signout={row.id}>
            {copy.providers.signOut}
          </Button>
        )
      ) : null}
    </div>
  );
  if (compact) {
    return (
      <div
        className={styles["compactRow"]}
        data-provider={row.id}
        data-provider-source={row.source}
        data-provider-health={row.health}
        data-provider-available={row.available === null ? "unknown" : String(row.available)}
      >
        {signedIn ? (
          <Button
            variant="quiet"
            onClick={onOpenDetails}
            data-provider-chip={row.id}
            title={copy.providers.detailsShow}
          >
            {row.id}
          </Button>
        ) : (
          <>
            <Chip tone="code">{row.id}</Chip>
            {actions}
          </>
        )}
      </div>
    );
  }
  return (
    <div
      className={styles["row"]}
      data-provider={row.id}
      data-provider-source={row.source}
      data-provider-health={row.health}
      data-provider-available={row.available === null ? "unknown" : String(row.available)}
    >
      <DataTable
        rows={[
          {
            key: "source",
            label: copy.providers.source.label,
            // AXIS 1. Never merged with the row below it.
            value: <Fact source="providers.source" value={copy.providers.source[row.source]} />,
          },
          {
            key: "health",
            label: copy.providers.health.label,
            // AXIS 2, and it says *when*, not *now*. Two Facts: the wire
            // health, then `last_observed_at` with a date when it is not today.
            value: (
              <>
                <Fact source="providers.health" value={row.health}>
                  {copy.providers.health[row.health]}
                </Fact>
                {row.last_observed_at === null ? null : (
                  <>
                    {" · "}
                    <Fact source="providers.last_observed_at" value={row.last_observed_at}>
                      {healthObserved(row)}
                    </Fact>
                  </>
                )}
              </>
            ),
            ...(row.last_observed_at === null ? { note: copy.providers.healthNever } : {}),
          },
          {
            key: "availability",
            label: copy.providers.availability,
            value: (
              <StatusBadge status={availabilityChip(row.available)}>
                {row.available === false ? copy.providers.unavailable : copy.providers.available}
              </StatusBadge>
            ),
            ...(row.available === false ? { note: copy.providers.unavailableNote } : {}),
          },
          ...(row.credential === undefined
            ? []
            : [
                {
                  key: "credential",
                  label: copy.providers.allowlist,
                  // A variable NAME. §23.2: providers.json holds names, never
                  // values, and this row is the projection of that fact.
                  value: <Fact mono source="providers.credential" value={row.credential} />,
                },
              ]),
          ...(row.egress_host === undefined
            ? []
            : [
                {
                  key: "endpoint",
                  label: copy.providers.egressHosts,
                  value: <Fact mono source="providers.egress_host" value={row.egress_host} />,
                },
              ]),
        ]}
      />
      {actions}
    </div>
  );
}

interface DiscoverySectionProps {
  readonly offers: readonly DiscoveryOffer[] | null;
  readonly busy: boolean;
  readonly compact: boolean;
  /** Hunt-for-sign-ins lives behind Show configuration once attached (#55). */
  readonly signedIn: boolean;
  readonly onDiscover: () => void;
  readonly onAdopt: (offer: DiscoveryOffer) => void;
}

function DiscoverySection(props: DiscoverySectionProps): React.JSX.Element | null {
  const { offers, busy, compact, signedIn, onDiscover, onAdopt } = props;
  if (compact && signedIn) return null;
  // §23.8 (C13): at rest this group carries NO eyebrow — the panel's resting
  // face allows at most one, and the discovery affordance is a child of the
  // one titled section. The eyebrow returns with the details face, where the
  // fuller §23.5 note also lives.
  const body = (
    <>
      {compact ? null : <PanelNote>{copy.providers.discover.note}</PanelNote>}
      {busy ? (
        <Button variant="secondary" disabled reason={copy.providers.dialog.waiting}>
          {copy.providers.discover.action}
        </Button>
      ) : (
        <Button variant="secondary" onClick={onDiscover} data-discovery-run>
          {copy.providers.discover.action}
        </Button>
      )}
      {/* §23.8 (C14): the privacy fact where the finger hovers, VISIBLE AT
          REST — a recorded exception to §0.2b's quiet resting path. ≤ 20
          words, both halves: reads-home-dir-only-on-press,
          nothing-used-until-adopted. It does not grow; the mechanism's long
          form stays behind the disclosure above. */}
      <PanelNote data-discovery-caption="">{copy.providers.discover.caption}</PanelNote>
      {offers === null ? null : offers.length === 0 ? (
        <PanelNote>{copy.providers.discover.empty}</PanelNote>
      ) : (
        offers.map((offer) => (
          <div
            key={offer.discovery_id}
            className={styles["row"]}
            data-discovery={offer.discovery_id}
            data-discovery-kind={offer.kind}
          >
            <DataTable
              rows={[
                {
                  key: "kind",
                  label: copy.providers.discover.title,
                  value: <Fact source="sources.kind" value={copy.providers.discover.kind[offer.kind]} />,
                },
                {
                  key: "provider",
                  label: copy.providers.source.label,
                  value: <Fact mono source="sources.provider_id" value={offer.provider_id} />,
                },
                {
                  key: "models",
                  label: copy.providers.discover.models,
                  value:
                    offer.model_ids.length === 0 ? (
                      copy.providers.noneRecorded
                    ) : (
                      <Fact mono source="sources.model_ids" value={offer.model_ids.join(", ")} />
                    ),
                },
                {
                  key: "path",
                  label: copy.providers.discover.sourcePath,
                  // Display text. The server is telling the operator where their
                  // own file is; nothing here sends a path back (§23.6).
                  value: <Fact mono source="sources.source_path" value={offer.source_path} />,
                },
              ]}
            />
            {/* Unmistakably an act: nothing adopts on render, on hover, or on
                selection (§23.14 item 19). §4.7 (C8): `secondary` — adopting
                is not the shell's one primary, which is Send (or, under
                `agent_unavailable`, the sign-in action). */}
            <div className={styles["actions"]}>
              <Button
                variant="secondary"
                onClick={() => {
                  onAdopt(offer);
                }}
                data-discovery-adopt={offer.discovery_id}
              >
                {copy.providers.discover.adopt}
              </Button>
            </div>
          </div>
        ))
      )}
    </>
  );
  return compact ? (
    <div className={styles["discovery"]} data-discovery-section="">
      {body}
    </div>
  ) : (
    <PanelSection eyebrow={copy.providers.discover.title}>{body}</PanelSection>
  );
}
