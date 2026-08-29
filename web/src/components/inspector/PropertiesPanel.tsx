// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `PropertiesPanel` — the `part.*` manufacturing metadata (INTERFACE.md §6.2).
//
// §6.2's TIGHTENING (binds G4.3) is two-sided, and this panel is one side of it:
//
//   1. DOM ↔ projection: the e2e asserts **set equality** between this panel's
//      `data-field` nodes and the keys of `GET /parts/{part}/properties`.
//      Containment would be satisfied by rendering one field.
//   2. Projection ↔ contract: a server-side pytest asserts the projection's key
//      set equals the enumerated `part.*` metadata the script declares.
//
// Assertion (1) is why **`data-field` marks declared fields only**. The closed
// nine-name vocabulary ships beside the values (`fields`), and an undeclared
// field is rendered — a visible absence beats a silently missing row — but it
// carries `data-undeclared-field`, not `data-field`, so the set the e2e compares
// stays exactly the projection's keys. `DataTable` carries `data-field` on the
// ROW element, which is where the shipped `<dt>` carried it too, so the
// selector is preserved verbatim (§3.14's migration criterion).
//
// WHY THE NINE `<Fact source>` PATHS ARE WRITTEN OUT. §6.2 says "each row
// renders through `<Fact source="properties.<key>">`", and §1's `no-derived-fact`
// rule requires `source` to be a **static string literal** — a computed
// attribution cannot be reviewed or asserted on. Those two are only compatible
// because the vocabulary is closed: nine names, enumerated in
// `core/executor/namespace.py::METADATA_FIELDS`, so nine literals cover it. This
// is also §3.4's tightening said from the other end: `DataTable` takes a
// constructed `ReactNode`, never a `source` string, precisely so this stays a
// reviewable literal instead of a runtime-minted attribution.

import type { PropertiesDocument } from "../../api/types";
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
  type DataRow,
} from "../../system";
import { Fact } from "../Fact";
import { useWorkspace } from "../../state/react";
import styles from "./panels.module.css";

/** One declared field, attributed to the response path it was read from. */
function PropertyFact({ field, value }: { readonly field: string; readonly value: string }) {
  switch (field) {
    case "description":
      return <Fact source="properties.description" value={value} />;
    case "material_spec":
      return <Fact source="properties.material_spec" value={value} />;
    case "process":
      return <Fact source="properties.process" value={value} />;
    case "stock_form":
      return <Fact source="properties.stock_form" value={value} />;
    case "blank_size":
      return <Fact source="properties.blank_size" value={value} />;
    case "general_tolerance":
      return <Fact source="properties.general_tolerance" value={value} />;
    case "finish":
      return <Fact source="properties.finish" value={value} />;
    case "assembly_method":
      return <Fact source="properties.assembly_method" value={value} />;
    case "joint":
      return <Fact source="properties.joint" value={value} />;
    default:
      return <Fact source="properties[].value" value={value} />;
  }
}

export interface PropertiesViewProps {
  readonly properties: PropertiesDocument;
}

export function PropertiesView({ properties }: PropertiesViewProps): React.JSX.Element {
  const declared = Object.keys(properties.properties);
  const undeclared = properties.fields.filter((field) => !(field in properties.properties));

  const rows: readonly DataRow[] = properties.fields
    .filter((field) => field in properties.properties)
    .map((field) => ({
      key: field,
      label: field.replace(/_/g, " "),
      value: <PropertyFact field={field} value={properties.properties[field] ?? ""} />,
      attrs: { "data-field": field },
    }));

  return (
    <Panel
      label={copy.properties.heading}
      data-panel="properties"
      data-properties-source={properties.source}
    >
      <PanelHeader title={copy.properties.heading} level={3} />
      <PanelBody>
        {declared.length === 0 ? (
          <EmptyState
            icon="ruler"
            title={copy.properties.emptyTitle}
            body={copy.properties.empty}
          />
        ) : (
          <DataTable rows={rows} />
        )}

        {undeclared.length === 0 ? null : (
          <PanelSection eyebrow={copy.properties.undeclaredHeading}>
            <DataTable
              rows={undeclared.map((field) => ({
                key: field,
                label: <span className={styles["muted"]}>{field.replace(/_/g, " ")}</span>,
                value: <span className={styles["muted"]}>{copy.properties.undeclared}</span>,
                attrs: { "data-undeclared-field": field },
              }))}
            />
            <PanelNote>{copy.properties.undeclaredNote}</PanelNote>
          </PanelSection>
        )}

        {/* Which read answered is itself a fact, and it changes what the values
            mean: the build record carries the values the worker EVALUATED, so a
            computed `part.blank_size` reads like a literal one; the static parse
            cannot see a computed field at all. */}
        <PanelSection eyebrow={copy.properties.sourceHeading}>
          <DataTable
            rows={[
              {
                key: "source",
                label: copy.properties.sourceLabel,
                value: <Fact source="properties.source" value={properties.source} />,
                note: copy.properties.source[properties.source],
              },
              {
                key: "bound",
                label: copy.properties.boundTo,
                value:
                  properties.build_artifact_ref === null ? (
                    <span className={styles["muted"]}>{copy.properties.unbound}</span>
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
      </PanelBody>
    </Panel>
  );
}

export function PropertiesPanel(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const properties = useProperties(part);

  if (part === null) {
    return <EmptyState icon="cube" title={copy.inspector.noPartTitle} body={copy.inspector.selectPart} />;
  }
  if (properties.data === undefined) return <PanelNote>{copy.absent.loading}</PanelNote>;
  return <PropertiesView properties={properties.data} />;
}
