// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `DataTable` and `Field` — one primitive for all four inspector panels
// (INTERFACE.md §4.7, §4.6, §3.4).
//
// Three columns: label (`.label`, `--ink-muted`), value (`.data`, RIGHT-ALIGNED,
// `tabular-nums`), unit (`.label`, `--ink-muted`, LEFT-aligned so units form
// their own column). All tables inside one `PanelBody` share one grid through
// `subgrid`.
//
// THE ROW VALUE IS A `ReactNode`, AND THAT IS THE TIGHTENING (§3.4), not an
// implementation convenience. §1's boundary is held by `heph/no-derived-fact`,
// whose first rule is that `<Fact source>` must be a *static, dotted, literal*
// path — "a computed `source` would let a component mint an attribution at
// runtime, which is attribution theatre". A `rows={[{source: "…", value}]}` API
// is exactly that computed source one indirection away, and it would not survive
// the lint this repo already runs. So the CALLER writes
// `<Fact source="build.metrics.area_mm2" …/>` itself and every attribution stays
// a reviewable literal at the call site. This costs three characters per row and
// keeps §1 untouched; amending `no-derived-fact` to admit a dynamic source is a
// real option and it is deliberately NOT taken here.
//
// `format.ts` is the render boundary and the only place a number becomes a
// string. §1 is untouched because formatting is presentation, not derivation,
// and `<Fact>`'s `data-value` still carries the unformatted server value.
//
// *Retires, all four at once:* `74289.99999999999` shipped to an engineer as a
// measurement; left-aligned numerals with no tabular figures; units welded into
// SCREAMING_SNAKE API keys (`AREA_MM2`, `BBOX_MM`) and shown raw; and a 200px
// table floating in a 1490px panel with the Properties value column visibly
// jogging between two groups that each compute their own `max-content`.

import type { ReactNode } from "react";
import { cx, type DataAttributes } from "./dataAttrs";
import styles from "./DataTable.module.css";
import roles from "./type.module.css";

export interface DataRow {
  /** React key. Usually the response key the row was read from. */
  readonly key: string;
  /** The row's name, as words. Never a raw API key (§4.7). */
  readonly label: ReactNode;
  /** A constructed node — a `<Fact>`, a `Badge`, a `Chip`. Never a source string. */
  readonly value: ReactNode;
  /** The unit, in its own column. `null` where a value has none. */
  readonly unit?: ReactNode | undefined;
  /**
   * Addressing attributes for the row element — `data-field`, `data-metric`,
   * `data-check`. The primitive forwards them; it does not invent them, and it
   * does not let a caller write a *status* attribute through this door (those
   * are `Badge`'s, §3.14's `system-owns-status`).
   */
  readonly attrs?: DataAttributes | undefined;
  /** A sentence under the row — a named absence, an explanation (§4.4). */
  readonly note?: ReactNode | undefined;
}

export interface DataTableProps {
  readonly rows: readonly DataRow[];
  /** `dl` for facts about one thing, `div` inside a list. Default `dl`. */
  readonly as?: "dl" | "div" | undefined;
  /**
   * §4.7 (C27), LAYOUT ONLY: when set, the table renders two label/value/unit
   * column groups side by side once the nearest size container is ≥640px wide,
   * filling row-first, sharing one grid so values align within each group;
   * below 640px it is the single-column form unchanged. The caller supplies
   * the container (`container-type: inline-size` on a wrapper) — the switch
   * reads that container's own measured width, never a viewport breakpoint.
   * A split table declares its own tracks rather than subgridding the panel.
   */
  readonly split?: boolean | undefined;
  readonly className?: string | undefined;
}

export function DataTable({ rows, as = "dl", split, className }: DataTableProps): React.JSX.Element {
  const Tag = as;
  const Name = as === "dl" ? "dt" : "span";
  const Value = as === "dl" ? "dd" : "span";
  return (
    <Tag className={cx(styles["table"], split === true ? styles["split"] : undefined, className)}>
      {rows.map((row) => (
        <div key={row.key} className={styles["row"]} {...(row.attrs ?? {})}>
          <Name className={cx(styles["label"], roles["label"])}>{row.label}</Name>
          <Value className={cx(styles["value"], roles["data"])}>{row.value}</Value>
          <span className={cx(styles["unit"], roles["label"])}>{row.unit ?? ""}</span>
          {row.note === undefined ? null : (
            <span className={cx(styles["note"], roles["body"])}>{row.note}</span>
          )}
        </div>
      ))}
    </Tag>
  );
}

export interface FieldProps {
  readonly label: ReactNode;
  readonly value: ReactNode;
  readonly unit?: ReactNode | undefined;
  readonly note?: ReactNode | undefined;
  readonly attrs?: DataAttributes | undefined;
}

/**
 * One key/value fact on the same three-column geometry (§4.7).
 *
 * "for panels carrying a fact rather than a table. Replaces the `<dl>` grids in
 * `PropertiesPanel` and `ProvenancePanel`." It is `DataTable` with one row so
 * the two can never drift into two geometries.
 */
export function Field({ label, value, unit, note, attrs }: FieldProps): React.JSX.Element {
  return (
    <DataTable
      rows={[
        {
          key: "field",
          label,
          value,
          ...(unit === undefined ? {} : { unit }),
          ...(note === undefined ? {} : { note }),
          ...(attrs === undefined ? {} : { attrs }),
        },
      ]}
    />
  );
}
