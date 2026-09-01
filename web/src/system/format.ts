// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `format.ts` — the numeric render boundary (INTERFACE.md §4.7, §1).
//
// THE ONE PLACE A NUMBER BECOMES A STRING. §1 is untouched by this file and the
// reason is worth stating precisely: **formatting is presentation, not
// derivation.** `<Fact>`'s `data-value` still carries the server's value
// verbatim, so the e2e's DOM-vs-JSON comparison still reads an unrounded number;
// what changes is only the glyphs a human sees. Nothing here converts a unit,
// combines two metrics, or re-counts a server array — those are §1's closed
// list and they stay on the server.
//
// *Retires:* `74289.99999999999` shipped to an engineer as a measurement. That
// is a float artefact of an exact computation, and printing it whole tells the
// reader the engine measured to fourteen digits, which it did not.
//
// AND: "units welded into SCREAMING_SNAKE API keys (`AREA_MM2`, `BBOX_MM`) and
// shown raw". A metric key is an API name, not a label. `metricLabel` and
// `metricUnit` split it into the two columns §4.7's DataTable gives them —
// **by parsing the key's own suffix, never by inventing a unit for a key that
// does not declare one.** A key with no recognised suffix gets no unit, and the
// label is the key with its separators opened up. Guessing "mm" for an unsuffixed
// key would be the client asserting a dimension the server never sent.

/** The unit suffixes a metric key may declare, longest-first so `MM2` wins. */
const UNIT_SUFFIXES: readonly (readonly [string, string])[] = [
  ["_MM3", "mm³"],
  ["_MM2", "mm²"],
  ["_MM", "mm"],
  ["_DEG", "°"],
  ["_G", "g"],
  ["_KG", "kg"],
  ["_S", "s"],
];

/**
 * The unit a metric key declares, or `null`.
 *
 * `null` is a real answer and is rendered as an empty unit cell, not as a
 * guess. §1's boundary is about numbers, but a fabricated unit is the same
 * failure in a different column.
 */
export function metricUnit(key: string): string | null {
  const upper = key.toUpperCase();
  for (const [suffix, unit] of UNIT_SUFFIXES) {
    if (upper.endsWith(suffix)) return unit;
  }
  return null;
}

/** A metric key as words: `AREA_MM2` → `area`, `bbox_mm` → `bbox`. */
export function metricLabel(key: string): string {
  const upper = key.toUpperCase();
  let stem = key;
  for (const [suffix] of UNIT_SUFFIXES) {
    if (upper.endsWith(suffix)) {
      stem = key.slice(0, key.length - suffix.length);
      break;
    }
  }
  return stem.replace(/[_-]+/g, " ").trim().toLowerCase();
}

/**
 * Significant digits for display. Six is enough to distinguish any measurement
 * this workspace reports and short enough to scan in a column.
 */
const SIGNIFICANT = 6;

/**
 * A number as a reader should see it.
 *
 * Integers print whole. Everything else is rounded to `SIGNIFICANT` significant
 * digits and stripped of trailing zeros, which turns `74289.99999999999` into
 * `74290` without pretending the underlying value changed — `data-value` still
 * carries every digit the server sent.
 */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return String(value);
  const rounded = Number(value.toPrecision(SIGNIFICANT));
  if (Number.isInteger(rounded)) return String(rounded);
  return String(rounded);
}

/**
 * Any JSON value a metric or a measurement may carry, as display text.
 *
 * An array of numbers — a `bbox_mm` triple — becomes `12 × 34 × 5.5`, because
 * `[12,34,5.5]` printed as JSON is punctuation a reader has to parse. Anything
 * else falls back to compact JSON: a *reading surface never receives
 * `JSON.stringify` output* is §4.7's rule for typed errors, and this is the
 * narrow remaining case where the value genuinely is a structure.
 */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value) && value.every((item) => typeof item === "number")) {
    return (value as readonly number[]).map(formatNumber).join(" × ");
  }
  return JSON.stringify(value) ?? "";
}

/**
 * Visible width for the header pin and composer artifact chips. The full ref
 * stays on `title` / `data-value` / `data-context-value`. 34 glyphs still ate
 * the build-state chip at 1280px.
 */
export const CHIP_REF_WIDTH = 22;

/**
 * `artifact:<kind>:<algo>:<digest>` — the only ref grammar the pin and the
 * composer chips spend their width on. Spending it on `artifact:build:` is what
 * printed `artifact:buil…` in a 22-glyph chip (#57).
 */
const ARTIFACT_REF = /^artifact:([^:]+):([^:]+):(.+)$/;

/**
 * A content-addressed ref, shortened for a chip while staying identifiable.
 *
 * Artifact refs print `kind · <digest prefix>` so the operator sees the hash,
 * not the scheme. Other strings keep head and tail, never a bare `.slice(-10)`:
 * `ScriptEditor`'s status bar shipped two different refs both rendered
 * `.slice(-10)`, which collided on the fixture and printed the same hash twice
 * with no labels (§4.7).
 */
export function formatRef(ref: string, width = 34): string {
  const artifact = ARTIFACT_REF.exec(ref);
  if (artifact !== null) {
    const kind = artifact[1] ?? "";
    const digest = artifact[3] ?? "";
    const prefix = digest.slice(0, 8);
    const compact = `${kind} · ${prefix}`;
    if (compact.length <= width) return compact;
    // A long kind (build-checkpoint) still yields the digest, not the scheme.
    if (prefix.length > 0 && prefix.length <= width) return prefix;
    return digest.slice(0, Math.max(0, width));
  }
  if (ref.length <= width) return ref;
  const tail = 8;
  // Below `tail + 2` there is no room for a head, an ellipsis and a tail, and
  // `slice(0, negative)` counts from the END — which is how `formatRef(head, 8)`
  // printed a 40-glyph sha plus an ellipsis plus its own last eight bytes into
  // the 44px header bar. A width that small can only be a prefix.
  if (width < tail + 2) return ref.slice(0, width);
  return `${ref.slice(0, width - tail - 1)}…${ref.slice(-tail)}`;
}

/**
 * A git object id, abbreviated the way git abbreviates one: a prefix.
 *
 * An oid is not a content-addressed ref with a scheme in front of it, so the
 * head-and-tail treatment `formatRef` gives a ref says nothing extra here — the
 * first bytes are what `git show` takes and what a reader recognises.
 */
export function formatOid(oid: string, width = 8): string {
  return oid.length <= width ? oid : oid.slice(0, width);
}

/** A byte count, for the §8 pager. Decimal units, because the server counts bytes. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return String(bytes);
  if (bytes < 1000) return `${String(bytes)} B`;
  if (bytes < 1000 * 1000) return `${formatNumber(bytes / 1000)} kB`;
  return `${formatNumber(bytes / (1000 * 1000))} MB`;
}
