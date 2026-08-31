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
// DOM contract, consumed by `providers.spec.ts`: `data-provider`,
// `data-provider-source`, `data-provider-health`, `data-provider-available`,
// `data-discovery`, `data-discovery-kind`, `data-discovery-adopt`,
// `data-providers-empty`, `data-providers-attach`, `data-auth-linked`.
// Selectors read attributes, never copy (§3).

import { useState } from "react";
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

/** The "accepted 14:32" half of §23.8's health axis, or a named absence. */
export function healthLine(row: ProviderRow): string {
  const health = copy.providers.health[row.health];
  if (row.last_observed_at === null) return health;
  const at = new Date(row.last_observed_at * 1000);
  return `${health} · ${copy.providers.healthStale} ${at.toLocaleTimeString()}`;
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
        <PanelHeader title={copy.providers.title} eyebrow={copy.providers.eyebrow} />
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
      <PanelHeader
        title={copy.providers.title}
        eyebrow={copy.providers.eyebrow}
        actions={
          <Button
            variant="quiet"
            pressed={detailsOpen}
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

            {document_.egress_acknowledged.length === 0 ? null : (
              <PanelSection eyebrow={copy.providers.egressHosts}>
                <PanelNote>{copy.providers.egressNote}</PanelNote>
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
          </>
        ) : null}

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
          <PanelSection eyebrow={copy.providers.title}>
            {rows.map((row) => (
              <ProviderRowView
                key={row.id}
                row={row}
                busy={busy}
                compact={!detailsOpen}
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
          </PanelSection>
        )}

        {/* §23.0's success condition: the attach that makes sessions reachable
            is an action on this panel, not a restart in a terminal. */}
        {document_.attach.attached ? null : (
          <Button
            variant="primary"
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
  readonly onSignIn: () => void;
  readonly onSignOut: () => void;
}

function ProviderRowView(props: ProviderRowViewProps): React.JSX.Element {
  const { row, busy, compact, onSignIn, onSignOut } = props;
  const signedIn = row.source !== "none";
  const actions = (
    <div className={styles["actions"]}>
      <Button
        variant={signedIn ? "secondary" : "primary"}
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
        <Chip tone="code">{row.id}</Chip>
        {actions}
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
            // AXIS 2, and it says *when*, not *now*.
            value: <Fact source="providers.health" value={healthLine(row)} />,
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
  readonly onDiscover: () => void;
  readonly onAdopt: (offer: DiscoveryOffer) => void;
}

function DiscoverySection(props: DiscoverySectionProps): React.JSX.Element {
  const { offers, busy, compact, onDiscover, onAdopt } = props;
  return (
    <PanelSection eyebrow={copy.providers.discover.title}>
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
                selection (§23.14 item 19). */}
            <div className={styles["actions"]}>
              <Button
                variant="primary"
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
    </PanelSection>
  );
}
