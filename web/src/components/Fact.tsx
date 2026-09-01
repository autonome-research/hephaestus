// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The `<Fact>` primitive (INTERFACE.md §4.6).
//
//   <Fact source="build.geometry_count" value={n} />
//   → <span data-source="build.geometry_count" data-value="12">12</span>
//
// This is what makes §1's `no-derived-fact` lint mechanical, and it gives the
// e2e one uniform selector for DOM-vs-JSON comparison instead of per-panel text
// scraping. Three properties are load-bearing:
//
// * `data-source` names the **HTTP response field** the number came from. Not
//   the panel, not the concept — the field, so an assertion can index the JSON
//   with it.
// * `data-value` carries the value **unformatted**, so a human-readable
//   rendering (thousands separators, a unit suffix) never becomes the thing an
//   assertion has to parse back.
// * `<Fact>` is the *only* element allowed to mint `data-source`; the eslint
//   rule enforces that, because an attribution any element could write is not an
//   attribution.

import type { ReactNode } from "react";
import styles from "./Fact.module.css";

export interface FactProps {
  /** A dotted path into the response document, e.g. `build.geometry_count`. */
  readonly source: string;
  /** The value **as the server sent it**. Never a client-computed number (§1). */
  readonly value: string | number | boolean | null;
  /** Optional presentation of the same value. Absent ⇒ the value renders itself. */
  readonly children?: ReactNode | undefined;
  // `| undefined` is explicit under `exactOptionalPropertyTypes`: a CSS-module
  // class read under `noUncheckedIndexedAccess` is `string | undefined`, and a
  // prop that could not accept that would push a non-null assertion into every
  // call site — a worse trade than saying what the type actually is.
  readonly className?: string | undefined;
  /** Renders a ref or a hash in the mono face without changing the data. */
  readonly mono?: boolean | undefined;
  /**
   * Keep `data-source` / `data-value` and drop the text from the accessibility
   * tree. The clipped `build.current` leaf is a boolean hook, not a sentence
   * (#96): announcing the bare word `true` / `false` is the defect.
   */
  readonly silent?: boolean | undefined;
}

/** The canonical string form of a value, used for `data-value` and the default text. */
function serialize(value: FactProps["value"]): string {
  if (value === null) return "";
  return String(value);
}

export function Fact({
  source,
  value,
  children,
  className,
  mono,
  silent,
}: FactProps): React.JSX.Element {
  const text = serialize(value);
  const classes = [styles["fact"], mono === true ? styles["mono"] : null, className]
    .filter((c): c is string => typeof c === "string" && c !== "")
    .join(" ");
  return (
    <span
      className={classes}
      data-source={source}
      data-value={text}
      {...(silent === true ? { "aria-hidden": true as const } : {})}
    >
      {children ?? text}
    </span>
  );
}
