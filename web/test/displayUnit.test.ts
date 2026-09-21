// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §1's one relaxation, and its limits (2026-09-20).
//
// A client may say a millimetre measurement in another unit. It may NOT change
// what `data-value` carries, re-count anything, or convert a number that is not
// a length. Each of those is asserted here.

import { describe, expect, it } from "vitest";
import {
  asDisplayUnit,
  convertedText,
  DISPLAY_UNITS,
  fromMillimetres,
  nextUnit,
  unitLabel,
} from "../src/state/displayUnit";
import { metricDimension, metricUnit } from "../src/system";

describe("the display unit cycles and converts", () => {
  it("walks mm → cm → m → in → ft → mm", () => {
    const walk: string[] = ["mm"];
    let at = nextUnit("mm");
    while (at !== "mm") {
      walk.push(at);
      at = nextUnit(at);
    }
    expect(walk).toEqual(["mm", "cm", "m", "in", "ft"]);
    expect([...DISPLAY_UNITS]).toEqual(walk);
  });

  it("converts by dimension, not by a single factor", () => {
    // An area in cm² is NOT an area in mm² divided by ten, which is the whole
    // reason the factor is raised to the dimension.
    expect(fromMillimetres(40, "cm", 1)).toBeCloseTo(4, 10);
    expect(fromMillimetres(2320, "cm", 2)).toBeCloseTo(23.2, 10);
    expect(fromMillimetres(4800, "cm", 3)).toBeCloseTo(4.8, 10);
  });

  it("uses the exact inch, so imperial is not a drift", () => {
    expect(fromMillimetres(25.4, "in", 1)).toBeCloseTo(1, 12);
    expect(fromMillimetres(304.8, "ft", 1)).toBeCloseTo(1, 12);
  });

  it("says a triple as a triple and trims trailing zeros", () => {
    expect(convertedText([40, 20, 6], "cm", 1)).toBe("4 × 2 × 0.6");
    expect(convertedText(2320, "cm", 2)).toBe("23.2");
  });

  it("refuses anything it cannot convert rather than guessing", () => {
    expect(convertedText("sealed", "cm", 1)).toBeNull();
    expect(convertedText(null, "cm", 1)).toBeNull();
    expect(convertedText({ a: 1 }, "cm", 1)).toBeNull();
    expect(convertedText(Number.NaN, "cm", 1)).toBeNull();
  });

  it("labels the unit at its dimension", () => {
    expect(unitLabel("cm", 1)).toBe("cm");
    expect(unitLabel("cm", 2)).toBe("cm²");
    expect(unitLabel("in", 3)).toBe("in³");
  });
});

describe("only LENGTHS convert", () => {
  it("knows which metric keys declare a length, and at what dimension", () => {
    expect(metricDimension("bbox_mm")).toBe(1);
    expect(metricDimension("area_mm2")).toBe(2);
    expect(metricDimension("volume_mm3")).toBe(3);
  });

  it("leaves angles, masses, times and unitless counts alone", () => {
    // A length unit has nothing to say about these. A converter that touched
    // every number because MOST of them were millimetres would be the
    // fabricated-unit failure in a different column.
    for (const key of ["draft_deg", "mass_g", "mass_kg", "elapsed_s", "edges", "faces"]) {
      expect(metricDimension(key), key).toBeNull();
    }
    // …and their own declared units still come through untouched.
    expect(metricUnit("draft_deg")).toBe("°");
    expect(metricUnit("mass_kg")).toBe("kg");
    expect(metricUnit("edges")).toBeNull();
  });
});

describe("the project's declaration is a label, not a vocabulary", () => {
  it("reads the units it knows, in any spelling", () => {
    expect(asDisplayUnit("mm")).toBe("mm");
    expect(asDisplayUnit("Millimeter")).toBe("mm");
    expect(asDisplayUnit("inches")).toBe("in");
    expect(asDisplayUnit("FEET")).toBe("ft");
  });

  it("falls back to mm rather than showing a unit it cannot convert", () => {
    // `hephaestus.toml`'s `units` is a free-form string — nothing validates it
    // against this list — so "furlongs" parses fine at the server and must not
    // become a display unit here.
    expect(asDisplayUnit("furlongs")).toBe("mm");
    expect(asDisplayUnit(undefined)).toBe("mm");
    expect(asDisplayUnit("")).toBe("mm");
  });
});
