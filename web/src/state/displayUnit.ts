// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The DISPLAY unit, and the one place a length is converted (2026-09-20).
//
// §1 AMENDED, deliberately, and this is the amendment. `ResultsPanel` said
// "Nothing here rounds, converts units, or combines two metrics … a client that
// reformatted a measurement into a different number would be computing one."
// That sentence is kept for combining and re-counting, which are still refused.
// It is relaxed for UNIT CONVERSION ONLY, on the seam the same comment names:
//
//     "`formatValue` decides only what a human SEES; `data-value` keeps the
//      server's own bytes."
//
// So conversion happens on the human side of that line and nowhere else. Every
// `<Fact>` still carries the SERVER'S millimetre value in `data-value`, which
// is what the e2e's DOM-versus-JSON comparison and the audit harness read; the
// drawn text is the same measurement said in another unit. This is the
// precedent `MeasuredValue` set: "The defect was never that the value was
// serialized; it was that the same serialization was ALSO the human text."
//
// WHAT IS NOT CONVERTED, and why: angles (`°`), masses (`g`, `kg`) and times
// (`s`) are not lengths, and a length unit has nothing to say about them. A
// converter that touched every number because most of them were millimetres is
// the fabricated-unit failure in a different column.
//
// The geometry itself is millimetres throughout — `bbox_mm`, `volume_mm3`,
// `area_mm2` — and stays so. This changes what is READ, never what is stored,
// sent, or built.

/** The cycle, in the order one click walks it. */
export const DISPLAY_UNITS = ["mm", "cm", "m", "in", "ft"] as const;
export type DisplayUnit = (typeof DISPLAY_UNITS)[number];

/** Millimetres per one of each unit — the exact inch, so `in` is not a drift. */
const MM_PER: Readonly<Record<DisplayUnit, number>> = {
  mm: 1,
  cm: 10,
  m: 1000,
  in: 25.4,
  ft: 304.8,
};

/** The suffixes a metric key can declare that this store converts. */
export type LengthDimension = 1 | 2 | 3;

/**
 * Convert a millimetre value for DISPLAY.
 *
 * `dimension` is 1 for a length, 2 for an area, 3 for a volume — the factor is
 * raised to it, because an area in cm² is not an area in mm² divided by ten.
 */
export function fromMillimetres(
  value: number,
  unit: DisplayUnit,
  dimension: LengthDimension,
): number {
  return value / MM_PER[unit] ** dimension;
}

/** `mm²` for `cm` at dimension 2 → `cm²`. */
export function unitLabel(unit: DisplayUnit, dimension: LengthDimension): string {
  return dimension === 1 ? unit : dimension === 2 ? `${unit}²` : `${unit}³`;
}

/** The next unit in the cycle; `ft` wraps to `mm`. */
export function nextUnit(unit: DisplayUnit): DisplayUnit {
  const at = DISPLAY_UNITS.indexOf(unit);
  return DISPLAY_UNITS[(at + 1) % DISPLAY_UNITS.length] ?? "mm";
}

/**
 * The project's declared unit as a display unit, or `mm`.
 *
 * `hephaestus.toml`'s `units` is a free-form string — nothing validates it
 * against this list — so an unrecognised declaration falls back to `mm` rather
 * than being shown as a unit this app cannot convert.
 */
export function asDisplayUnit(declared: string | undefined): DisplayUnit {
  const lower = (declared ?? "").trim().toLowerCase();
  const alias: Readonly<Record<string, DisplayUnit>> = {
    mm: "mm", millimetre: "mm", millimeter: "mm",
    cm: "cm", centimetre: "cm", centimeter: "cm",
    m: "m", metre: "m", meter: "m",
    in: "in", inch: "in", inches: "in",
    ft: "ft", foot: "ft", feet: "ft",
  };
  return alias[lower] ?? "mm";
}

type Listener = () => void;

class DisplayUnitStore {
  #unit: DisplayUnit | null = null;
  readonly #listeners = new Set<Listener>();

  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  /** `null` until the operator chooses — the project's declaration stands. */
  getSnapshot = (): DisplayUnit | null => this.#unit;

  set(unit: DisplayUnit): void {
    if (this.#unit === unit) return;
    this.#unit = unit;
    for (const listener of this.#listeners) listener();
  }

  /** Test seam. */
  reset(): void {
    this.#unit = null;
    for (const listener of this.#listeners) listener();
  }
}

export const displayUnitStore = new DisplayUnitStore();

/**
 * A millimetre measurement, said in `unit`.
 *
 * Returns `null` for anything that is not a number or a numeric tuple — a
 * structure this cannot convert is handed back to the caller's own renderer
 * rather than guessed at. Trailing zeros are trimmed so `40 mm` reads `4 cm`
 * and not `4.0000 cm`; the precision is four decimals, which is finer than any
 * value the kernel produces is meaningful to.
 */
export function convertedText(
  value: unknown,
  unit: DisplayUnit,
  dimension: LengthDimension,
): string | null {
  const say = (n: number): string => String(Number(fromMillimetres(n, unit, dimension).toFixed(4)));
  if (typeof value === "number") return Number.isFinite(value) ? say(value) : null;
  if (Array.isArray(value) && value.length > 0 && value.every((n) => typeof n === "number")) {
    return (value as readonly number[]).map(say).join(" × ");
  }
  return null;
}
