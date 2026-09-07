// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-viewport-7: with no part in the URL, the workspace used to open on
// position zero of the server's (alphabetical) listing, which correlates with
// nothing an operator cares about — and, in the fixture, is the one part with
// no build. `defaultPart` (`App.tsx`) is the fix: the first part that has
// something to show, falling back to position zero only when nothing does.

import { describe, expect, it } from "vitest";
import { defaultPart } from "../src/App";
import type { PartSummary } from "../src/api/types";

function part(name: string, build_status?: "ok" | "error" | "not_built"): PartSummary {
  return {
    name,
    path: `parts/${name}.py`,
    content_hash: `sha256:${name}`,
    snapshot_ref: `artifact:snapshot:sha256:${name}`,
    ...(build_status === undefined ? {} : { build_status }),
  };
}

describe("defaultPart — the first part with something to show, else the first part (J-web-viewport-7)", () => {
  it("picks the alphabetically-first part when it is built", () => {
    expect(defaultPart([part("bracket", "ok"), part("kerf_card", "ok")])).toBe("bracket");
  });

  it("skips an unbuilt alphabetically-first part for the next built one", () => {
    // The fixture's own shape: the alphabetically first part has never been
    // built, and the old default landed the whole workspace on its absence.
    expect(
      defaultPart([part("assembly_jig", "not_built"), part("bracket", "ok"), part("kerf_card", "ok")]),
    ).toBe("bracket");
  });

  it("treats an errored build as 'something to show' — it is not not_built", () => {
    expect(defaultPart([part("assembly_jig", "not_built"), part("bracket", "error")])).toBe("bracket");
  });

  it("falls back to position zero when every part is unbuilt, landing on the composed absence honestly", () => {
    expect(defaultPart([part("assembly_jig", "not_built"), part("bracket", "not_built")])).toBe(
      "assembly_jig",
    );
  });

  it("falls back to position zero when no row carries a build_status at all (an older server)", () => {
    expect(defaultPart([part("assembly_jig"), part("bracket")])).toBe("assembly_jig");
  });

  it("returns null for an empty project, never guessing a name", () => {
    expect(defaultPart([])).toBeNull();
  });
});
