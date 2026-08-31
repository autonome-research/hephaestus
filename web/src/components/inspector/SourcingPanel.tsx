// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// BOM / sourcing inspector — manufacturing identity the part already declares.
//
// Issue #12: "BOM/sourcing inspector only from manufacturing fields the part
// already declares (`process`, stock, `conform_to`-class). No live vendor
// catalog." There is no `conform_to` field on the `part.*` surface
// (`script_contract.md` §5.2). The closed subset this panel reads is
// `SOURCING_FIELDS`: `process`, `stock_form`, `blank_size`, `material_spec`.
// Values come from `GET /parts/{part}/properties`. Nothing here queries a
// storefront, and no identifier in this file names one.
//
// `data-field` marks declared sourcing fields only, so a set-equality check
// against the projection ∩ `SOURCING_FIELDS` stays exact. An undeclared
// sourcing field is a visible absence (`data-undeclared-field`), not a
// silently missing row. Description, finish, joint, and the other
// `part.*` names stay on the Properties tab — this panel does not restyle
// that one.

import { SOURCING_FIELDS, type PropertiesDocument, type SourcingField } from "../../api/types";
import { useProperties } from "../../api/queries";
import { copy } from "../../copy";
import {
  DataTable,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelNote,
  PanelSection,
  formatRef,
  type DataRow,
} from "../../system";
import { Fact } from "../Fact";
import { useWorkspace } from "../../state/react";
import styles from "./panels.module.css";

/** One declared sourcing field, attributed to the response path it was read from. */
function SourcingFact({ field, value }: { readonly field: SourcingField; readonly value: string }) {
  switch (field) {
    case "process":
      return <Fact source="properties.process" value={value} />;
    case "stock_form":
      return <Fact source="properties.stock_form" value={value} />;
    case "blank_size":
      return <Fact source="properties.blank_size" value={value} />;
    case "material_spec":
      return <Fact source="properties.material_spec" value={value} />;
  }
}

export interface SourcingViewProps {
  readonly properties: PropertiesDocument;
  /** The workspace pin — the artifact on screen, which sourcing is about. */
  readonly pinned: string | null;
}

export function SourcingView({ properties, pinned }: SourcingViewProps): React.JSX.Element {
  const declared = SOURCING_FIELDS.filter((field) => field in properties.properties);
  const undeclared = SOURCING_FIELDS.filter((field) => !(field in properties.properties));

  const rows: readonly DataRow[] = declared.map((field) => ({
    key: field,
    label: copy.sourcing.fields[field],
    value: <SourcingFact field={field} value={properties.properties[field] ?? ""} />,
    attrs: { "data-field": field, "data-sourcing-field": field },
  }));

  return (
    <Panel
      label={copy.sourcing.heading}
      data-panel="sourcing"
      data-properties-source={properties.source}
    >
      <PanelHeader title={copy.sourcing.heading} level={3} />
      <PanelBody>
        <PanelSection eyebrow={copy.sourcing.subjectHeading}>
          <DataTable
            rows={[
              {
                key: "pin",
                label: copy.sourcing.pin,
                value:
                  pinned === null ? (
                    <span className={styles["muted"]}>{copy.sourcing.noPin}</span>
                  ) : (
                    <Fact source="workspace.artifact_ref" value={pinned} mono>
                      {formatRef(pinned)}
                    </Fact>
                  ),
              },
              {
                key: "bound",
                label: copy.sourcing.boundTo,
                value:
                  properties.build_artifact_ref === null ? (
                    <span className={styles["muted"]}>{copy.sourcing.unbound}</span>
                  ) : (
                    <Fact
                      source="properties.build_artifact_ref"
                      value={properties.build_artifact_ref}
                      mono
                    />
                  ),
              },
            ]}
          />
        </PanelSection>

        {declared.length === 0 ? (
          <EmptyState
            icon="cube"
            title={copy.sourcing.emptyTitle}
            body={copy.sourcing.empty}
          />
        ) : (
          <DataTable rows={rows} />
        )}

        {undeclared.length === 0 ? null : (
          <PanelSection eyebrow={copy.sourcing.undeclaredHeading}>
            <DataTable
              rows={undeclared.map((field) => ({
                key: field,
                label: <span className={styles["muted"]}>{copy.sourcing.fields[field]}</span>,
                value: <span className={styles["muted"]}>{copy.sourcing.undeclared}</span>,
                attrs: { "data-undeclared-field": field },
              }))}
            />
            <PanelNote>{copy.sourcing.undeclaredNote}</PanelNote>
          </PanelSection>
        )}

        <PanelSection eyebrow={copy.sourcing.sourceHeading}>
          <DataTable
            rows={[
              {
                key: "source",
                label: copy.sourcing.sourceLabel,
                value: <Fact source="properties.source" value={properties.source} />,
                note: copy.sourcing.source[properties.source],
              },
            ]}
          />
          <PanelNote data-sourcing-catalog="none">{copy.sourcing.catalogNote}</PanelNote>
        </PanelSection>
      </PanelBody>
    </Panel>
  );
}

export function SourcingPanel(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const pinned = useWorkspace((s) => s.artifact_ref);
  const properties = useProperties(part);

  if (part === null) {
    return <EmptyState icon="cube" title={copy.inspector.noPartTitle} body={copy.inspector.selectPart} />;
  }
  if (properties.data === undefined) return <PanelNote>{copy.absent.loading}</PanelNote>;
  return <SourcingView properties={properties.data} pinned={pinned} />;
}
