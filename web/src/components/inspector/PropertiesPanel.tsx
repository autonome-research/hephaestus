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
// stays exactly the projection's keys.
//
// WHY THE NINE `<Fact source>` PATHS ARE WRITTEN OUT. §6.2 says "each row
// renders through `<Fact source="properties.<key>">`", and §1's `no-derived-fact`
// rule requires `source` to be a **static string literal** — a computed
// attribution cannot be reviewed or asserted on. Those two are only compatible
// because the vocabulary is closed: nine names, enumerated in
// `core/executor/namespace.py::METADATA_FIELDS`, so nine literals cover it. A
// name outside them (engine drift) falls to the indexed path
// `properties[].value` and is still rendered, still attributed, and still
// carries `data-field` — `inspector.test.tsx` asserts against the recorded
// `fields` list that no name actually takes that branch, which checks the client
// against the *server's* vocabulary rather than against a copy of it.

import type { PropertiesDocument } from "../../api/types";
import { useProperties } from "../../api/queries";
import { copy } from "../../copy";
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

  return (
    <section
      className={styles["panel"]}
      aria-label={copy.properties.heading}
      data-panel="properties"
      data-properties-source={properties.source}
    >
      <h3 className={styles["heading"]}>{copy.properties.heading}</h3>

      {declared.length === 0 ? (
        <p className={styles["absent"]}>{copy.properties.empty}</p>
      ) : (
        <dl className={styles["pairs"]}>
          {properties.fields
            .filter((field) => field in properties.properties)
            .map((field) => (
              <div key={field} className={styles["pairRow"]}>
                <dt data-field={field}>{field}</dt>
                <dd>
                  <PropertyFact field={field} value={properties.properties[field] ?? ""} />
                </dd>
              </div>
            ))}
        </dl>
      )}

      {undeclared.length === 0 ? null : (
        <>
          <dl className={styles["pairs"]}>
            {undeclared.map((field) => (
              <div key={field} className={styles["pairRow"]}>
                <dt data-undeclared-field={field} className={styles["dim"]}>
                  {field}
                </dt>
                <dd className={styles["dim"]}>{copy.properties.undeclared}</dd>
              </div>
            ))}
          </dl>
          <p className={styles["note"]}>{copy.properties.undeclaredNote}</p>
        </>
      )}

      {/* Which read answered is itself a fact, and it changes what the values
          mean: the build record carries the values the worker EVALUATED, so a
          computed `part.blank_size` reads like a literal one; the static parse
          cannot see a computed field at all. */}
      <dl className={styles["pairs"]}>
        <div className={styles["pairRow"]}>
          <dt>{copy.properties.sourceHeading}</dt>
          <dd>
            <Fact source="properties.source" value={properties.source} />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.properties.boundTo}</dt>
          <dd>
            {properties.build_artifact_ref === null ? (
              <span className={styles["dim"]}>{copy.properties.unbound}</span>
            ) : (
              <Fact
                source="properties.build_artifact_ref"
                value={properties.build_artifact_ref}
                className={styles["mono"]}
                mono
              />
            )}
          </dd>
        </div>
      </dl>
      <p className={styles["note"]}>{copy.properties.source[properties.source]}</p>
    </section>
  );
}

export function PropertiesPanel(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const properties = useProperties(part);

  if (part === null) return <p className={styles["absent"]}>{copy.inspector.selectPart}</p>;
  if (properties.data === undefined) {
    return <p className={styles["absent"]}>{copy.absent.loading}</p>;
  }
  return <PropertiesView properties={properties.data} />;
}
