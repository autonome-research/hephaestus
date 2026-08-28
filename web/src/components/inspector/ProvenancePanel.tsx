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
// with fields missing" — and the italic sentence under a weak one is the design
// point: "A weak answer that *says why it is weak* reads as instrument honesty;
// the same answer with a blank field reads as a bug." So `owned` and
// `unattributed` each carry their sentence, and the one case §4.4 singles out —
// a face that *is* tagged whose pinned build's source map is no longer stored —
// renders `owned` with the retention reason said out loud, never the generic
// `unattributed` copy.
//
// TWO STATIONS UPSTREAM ARE MISSING IN THIS BUILD, and the panel names them
// rather than rendering an empty frame: there is no viewport to raycast, and
// `POST /parts/{part}/selection/resolve` is not a served route (§19 item 8). A
// descriptor clicked in the DFM panel therefore arrives here as an *address*, not
// as a resolution, and the panel says which station is missing rather than
// dressing the address up as a provenance answer.

import type { ResolvedSelection } from "../../api/types";
import { copy } from "../../copy";
import { Fact } from "../Fact";
import { useWorkspace } from "../../state/react";
import type { DescriptorIntent } from "./DfmPanel";
import styles from "./panels.module.css";

/**
 * The reasons a provenance answer may carry, CLOSED (§4.4).
 *
 * §12.3 names `provenance` in its response shape without giving it one, and §4.4
 * requires two answers that would otherwise look identical to be told apart. This
 * is the smallest closed record that discharges that: a state, and — where the
 * server has one — a reason. `source_map_not_stored` is §4.4's named case (the
 * attribution existed and was not retained); `boolean_result_face` is
 * `architecture.md` §3.1's cap (a boolean **result** face is not attributed to an
 * operand statement, because OCCT history tracking is out of scope). An
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
    <section className={styles["panel"]} aria-label={copy.provenance.heading} data-panel="provenance">
      <h3 className={styles["heading"]}>{copy.provenance.heading}</h3>

      {origin === undefined ? null : (
        <p className={styles["note"]} data-provenance-origin={origin}>
          {copy.provenance.origin[origin]}
        </p>
      )}

      <dl className={styles["pairs"]}>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.pinned}</dt>
          <dd>
            {pinned === null ? (
              <span className={styles["dim"]}>{copy.absent.unavailable}</span>
            ) : (
              <Fact
                source="workspace.artifact_ref"
                value={pinned}
                className={styles["mono"]}
                mono
              />
            )}
          </dd>
        </div>
      </dl>

      {resolved === undefined ? (
        <>
          {intent === undefined ? null : <IntentAddress intent={intent} />}
          <p className={styles["absent"]}>
            {intent === undefined ? copy.provenance.absent : copy.dfm.descriptorPending}
          </p>
          <p className={styles["note"]}>{copy.provenance.unreachable}</p>
        </>
      ) : (
        <Resolved resolved={resolved} />
      )}
    </section>
  );
}

/**
 * The artifact-bound address a clicked DFM descriptor carries.
 *
 * Deliberately NOT dressed as a resolution: no `data-provenance-state`, because
 * no state was resolved. What is shown is exactly the descriptor the finding
 * reported plus the artifact it was measured against — every value a server
 * value, none of them joined to anything the client worked out.
 */
function IntentAddress({ intent }: { readonly intent: DescriptorIntent }): React.JSX.Element {
  return (
    <dl className={styles["pairs"]} data-provenance-intent={intent.rule_id}>
      <div className={styles["pairRow"]}>
        <dt>{copy.provenance.source}</dt>
        <dd>
          <Fact
            source="dfm.last.findings[].source_artifact_ref"
            value={intent.source_artifact_ref}
            className={styles["mono"]}
            mono
          />
        </dd>
      </div>
      <div className={styles["pairRow"]}>
        <dt>{copy.provenance.solid}</dt>
        <dd>
          <Fact
            source="dfm.last.findings[].topology[].solid_id"
            value={intent.descriptor.solid_id}
          />
        </dd>
      </div>
      <div className={styles["pairRow"]}>
        <dt>{copy.provenance.topology}</dt>
        <dd>
          <Fact
            source="dfm.last.findings[].topology[].topology_index"
            value={intent.descriptor.topology_index}
          />
        </dd>
      </div>
    </dl>
  );
}

/** §4.4's three shapes over one server resolution. */
function Resolved({ resolved }: { readonly resolved: ResolvedSelection }): React.JSX.Element {
  const state = resolved.provenance.state;
  // §4.4: "the attribution existed and was not retained" is a DIFFERENT fact
  // from "the machinery cannot attribute this face", and a panel that rendering
  // them identically would claim the first while the second is true. WHICH ONE
  // IS TRUE IS A SERVER VALUE — `provenance.reason` — never an inference from
  // `tag !== null && line === null`, which would be the client deducing a
  // provenance answer that §1 makes a server value.
  const reason = provenanceReason(resolved.provenance.reason);

  return (
    <>
      <div className={styles["headingRow"]}>
        <span className={styles["state"]} data-provenance-state={state}>
          {copy.provenance.state[state]}
        </span>
        <Fact
          source="selection.selection_id"
          value={resolved.selection_id}
          className={styles["dim"]}
        >
          {`${copy.provenance.selectionId} ${resolved.selection_id}`}
        </Fact>
      </div>

      <dl className={styles["pairs"]}>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.kind}</dt>
          <dd>
            <Fact source="selection.kind" value={resolved.kind} />{" "}
            {resolved.label === null ? null : (
              <Fact source="selection.label" value={resolved.label} className={styles["mono"]} />
            )}
          </dd>
        </div>
        {resolved.tag === null ? null : (
          <div className={styles["pairRow"]}>
            <dt>{copy.provenance.tag}</dt>
            <dd>
              <Fact source="selection.tag" value={resolved.tag} className={styles["mono"]} />
            </dd>
          </div>
        )}
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.solid}</dt>
          <dd>
            <Fact source="selection.solid_index" value={resolved.solid_index} />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.topology}</dt>
          <dd>
            <Fact source="selection.topology_index" value={resolved.topology_index} />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.line}</dt>
          <dd>
            {resolved.line === null ? (
              <span className={styles["dim"]}>{copy.provenance.noLine}</span>
            ) : (
              <Fact source="selection.line" value={resolved.line} className={styles["mono"]} />
            )}
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.source}</dt>
          <dd>
            <Fact
              source="selection.source_artifact_ref"
              value={resolved.source_artifact_ref}
              className={styles["mono"]}
              mono
            />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.bundle}</dt>
          <dd>
            <Fact
              source="selection.bundle_ref"
              value={resolved.bundle_ref}
              className={styles["mono"]}
              mono
            />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.table}</dt>
          <dd>
            <Fact
              source="selection.selection_table_ref"
              value={resolved.selection_table_ref}
              className={styles["mono"]}
              mono
            />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.provenance.crop}</dt>
          <dd>
            {resolved.crop_artifact_ref === null ? (
              <span className={styles["dim"]}>{copy.provenance.noCrop}</span>
            ) : (
              <Fact
                source="selection.crop_artifact_ref"
                value={resolved.crop_artifact_ref}
                className={styles["mono"]}
                mono
              />
            )}
          </dd>
        </div>
      </dl>

      {state === "tagged" && reason === null ? null : (
        <p
          className={styles["why"]}
          data-provenance-why={reason ?? state}
          data-provenance-reason={reason ?? ""}
        >
          {reason === null ? copy.provenance.why[state] : copy.provenance.reason[reason]}
        </p>
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
