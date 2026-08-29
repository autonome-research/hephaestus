// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ProvenancePanel` — a station on §4.3's spine (INTERFACE.md §4.3, §4.4, §12.3).
//
// §4.3 draws one continuous path and forbids short-circuiting any station:
//
//   artifact pin (HEADER) → viewport GLTF bound to that ref → raycast hit
//   (client, a HINT) → POST /selection/resolve (server validates) →
//   SelectionPopover → ProvenancePanel (source_artifact_ref, table ref, bundle
//   ref, crop) → "Ask about this" → quick-edit spawn
//
//   "No station may be short-circuited by client knowledge. The popover renders
//   only what the server returned."
//
// This panel renders **only** fields of a server `ResolvedSelection`. It does not
// raycast, does not read `asset.extras`, does not join a tag to a line, and does
// not decide which of §4.4's three shapes applies: `provenance.state` is a server
// value, exactly like `kind` and `line`.
//
// §4.4's three shapes are each a first-class designed state — "not a strong state
// with fields missing" — and the italic sentence under a weak one WAS the design
// point. §4.7 corrects the styling without touching the substance: **the
// explanatory sentence is `.body` in a legible ink and is no longer italic.**
// §3.9 measured the shipped `--ink-3` at 3.10:1 and §4.7 says outright that a
// sentence which exists to make a weak answer read as designed "cannot itself be
// below the legibility floor". The words are unchanged; the footnote styling that
// contradicted them is gone.
//
// TWO STATIONS UPSTREAM ARE MISSING IN THIS BUILD, and the panel names them
// rather than rendering an empty frame: there is no viewport to raycast, and
// `POST /parts/{part}/selection/resolve` is not a served route (§19 item 8).

import type { ResolvedSelection } from "../../api/types";
import { copy } from "../../copy";
import {
  Chip,
  DataTable,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelNote,
  PanelSection,
  type DataRow,
} from "../../system";
import { Fact } from "../Fact";
import { useWorkspace } from "../../state/react";
import type { DescriptorIntent } from "./DfmPanel";
import styles from "./panels.module.css";

/**
 * The reasons a provenance answer may carry, CLOSED (§4.4).
 *
 * `source_map_not_stored` is §4.4's named case (the attribution existed and was
 * not retained); `boolean_result_face` is `architecture.md` §3.1's cap. An
 * unrecognized reason is dropped back to the state's own sentence rather than
 * rendered raw — a vocabulary that widened by echoing whatever arrived would not
 * be closed.
 */
export const PROVENANCE_REASONS = ["source_map_not_stored", "boolean_result_face"] as const;

export type ProvenanceReason = (typeof PROVENANCE_REASONS)[number];

function provenanceReason(reason: string | undefined): ProvenanceReason | null {
  return PROVENANCE_REASONS.find((known) => known === reason) ?? null;
}

export interface ProvenanceViewProps {
  /** The pinned artifact — the head of §4.3's spine, from workspace state. */
  readonly pinned: string | null;
  /** What the server resolved, when a resolution exists. */
  readonly resolved?: ResolvedSelection | undefined;
  /** How this panel was reached, when it was reached from somewhere. */
  readonly origin?: "dfm_finding" | "viewport" | undefined;
  /** A descriptor the user clicked, with no resolution behind it yet. */
  readonly intent?: DescriptorIntent | undefined;
}

export function ProvenanceView({
  pinned,
  resolved,
  origin,
  intent,
}: ProvenanceViewProps): React.JSX.Element {
  return (
    <Panel label={copy.provenance.heading} data-panel="provenance">
      <PanelHeader
        title={copy.provenance.heading}
        level={3}
        actions={
          origin === undefined ? undefined : (
            <Chip data-provenance-origin={origin}>{copy.provenance.origin[origin]}</Chip>
          )
        }
      />
      <PanelBody>
        <DataTable
          rows={[
            {
              key: "pinned",
              label: copy.provenance.pinned,
              value:
                pinned === null ? (
                  <span className={styles["muted"]}>{copy.absent.unavailable}</span>
                ) : (
                  <Fact source="workspace.artifact_ref" value={pinned} mono />
                ),
            },
          ]}
        />

        {resolved === undefined ? (
          <>
            {intent === undefined ? null : <IntentAddress intent={intent} />}
            <EmptyState
              icon="tag"
              title={
                intent === undefined
                  ? copy.provenance.absentTitle
                  : copy.dfm.descriptorPendingTitle
              }
              body={
                <>
                  <p>{intent === undefined ? copy.provenance.absent : copy.dfm.descriptorPending}</p>
                  <p>{copy.provenance.unreachable}</p>
                </>
              }
            />
          </>
        ) : (
          <Resolved resolved={resolved} />
        )}
      </PanelBody>
    </Panel>
  );
}

/**
 * The artifact-bound address a clicked DFM descriptor carries.
 *
 * Deliberately NOT dressed as a resolution: no `data-provenance-state`, because
 * no state was resolved. What is shown is exactly the descriptor the finding
 * reported plus the artifact it was measured against.
 */
function IntentAddress({ intent }: { readonly intent: DescriptorIntent }): React.JSX.Element {
  return (
    <PanelSection eyebrow={copy.provenance.addressHeading}>
      <DataTable
        rows={[
          {
            key: "source",
            label: copy.provenance.source,
            value: (
              <Fact
                source="dfm.last.findings[].source_artifact_ref"
                value={intent.source_artifact_ref}
                mono
              />
            ),
            attrs: { "data-provenance-intent": intent.rule_id },
          },
          {
            key: "solid",
            label: copy.provenance.solid,
            value: (
              <Fact
                source="dfm.last.findings[].topology[].solid_id"
                value={intent.descriptor.solid_id}
              />
            ),
          },
          {
            key: "topology",
            label: copy.provenance.topology,
            value: (
              <Fact
                source="dfm.last.findings[].topology[].topology_index"
                value={intent.descriptor.topology_index}
              />
            ),
          },
        ]}
      />
    </PanelSection>
  );
}

/** §4.4's three shapes over one server resolution. */
function Resolved({ resolved }: { readonly resolved: ResolvedSelection }): React.JSX.Element {
  const state = resolved.provenance.state;
  // §4.4: "the attribution existed and was not retained" is a DIFFERENT fact
  // from "the machinery cannot attribute this face", and a panel that rendered
  // them identically would claim the first while the second is true. WHICH ONE
  // IS TRUE IS A SERVER VALUE — `provenance.reason` — never an inference from
  // `tag !== null && line === null`, which would be the client deducing a
  // provenance answer that §1 makes a server value.
  const reason = provenanceReason(resolved.provenance.reason);

  const rows: readonly DataRow[] = [
    {
      key: "kind",
      label: copy.provenance.kind,
      value: (
        <>
          <Fact source="selection.kind" value={resolved.kind} />{" "}
          {resolved.label === null ? null : (
            <Fact source="selection.label" value={resolved.label} className={styles["mono"]} />
          )}
        </>
      ),
    },
    ...(resolved.tag === null
      ? []
      : [
          {
            key: "tag",
            label: copy.provenance.tag,
            value: <Fact source="selection.tag" value={resolved.tag} mono />,
          },
        ]),
    {
      key: "solid",
      label: copy.provenance.solid,
      value: <Fact source="selection.solid_index" value={resolved.solid_index} />,
    },
    {
      key: "topology",
      label: copy.provenance.topology,
      value: <Fact source="selection.topology_index" value={resolved.topology_index} />,
    },
    {
      key: "line",
      label: copy.provenance.line,
      value:
        resolved.line === null ? (
          <span className={styles["muted"]}>{copy.provenance.noLine}</span>
        ) : (
          <Fact source="selection.line" value={resolved.line} mono />
        ),
    },
    {
      key: "source",
      label: copy.provenance.source,
      value: <Fact source="selection.source_artifact_ref" value={resolved.source_artifact_ref} mono />,
    },
    {
      key: "bundle",
      label: copy.provenance.bundle,
      value: <Fact source="selection.bundle_ref" value={resolved.bundle_ref} mono />,
    },
    {
      key: "table",
      label: copy.provenance.table,
      value: <Fact source="selection.selection_table_ref" value={resolved.selection_table_ref} mono />,
    },
    {
      key: "crop",
      label: copy.provenance.crop,
      value:
        resolved.crop_artifact_ref === null ? (
          <span className={styles["muted"]}>{copy.provenance.noCrop}</span>
        ) : (
          <Fact source="selection.crop_artifact_ref" value={resolved.crop_artifact_ref} mono />
        ),
    },
  ];

  return (
    <>
      <div className={styles["chips"]}>
        <Chip data-provenance-state={state}>{copy.provenance.state[state]}</Chip>
        <Fact
          source="selection.selection_id"
          value={resolved.selection_id}
          className={styles["muted"]}
        >
          {`${copy.provenance.selectionId} ${resolved.selection_id}`}
        </Fact>
      </div>

      <DataTable rows={rows} />

      {state === "tagged" && reason === null ? null : (
        <PanelNote
          data-provenance-why={reason ?? state}
          data-provenance-reason={reason ?? ""}
          className={styles["why"]}
        >
          {reason === null ? copy.provenance.why[state] : copy.provenance.reason[reason]}
        </PanelNote>
      )}
    </>
  );
}

export function ProvenancePanel({
  resolved,
  intent,
}: {
  readonly resolved?: ResolvedSelection | undefined;
  readonly intent?: DescriptorIntent | undefined;
}): React.JSX.Element {
  const pinned = useWorkspace((s) => s.artifact_ref);
  return (
    <ProvenanceView
      pinned={pinned}
      resolved={resolved}
      intent={intent}
      origin={intent === undefined ? undefined : "dfm_finding"}
    />
  );
}
