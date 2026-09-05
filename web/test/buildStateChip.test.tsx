// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// audit-2026-09-04 B-5: `GET /parts/{part}/build` reports a superseded build as
// current, and the header chip drew the same lie — `current === true` mapped
// straight to `copy.buildState.current`, "up to date", with no way to print the
// spec's own `stale` word (INTERFACE.md §4.1's closed chip vocabulary).
//
// The fix keeps `current` as publication state and adds a read-time freshness
// fact (`build.stale` / `build.stale_inputs`) the engine recomputes on every
// read. This file pins the client half: `buildState()` must check `stale`
// BEFORE the current/preview split, and the chip must attribute that boolean
// through `<Fact>` exactly like the existing `build.current` leaf — never as a
// bare rendered `true`/`false` (`Fact.tsx`'s `silent` rule).
//
// Clean-room hygiene (§3): no assertion is on a UI copy string except to prove
// two states render *different* words — the words themselves come from
// `copy.ts` and are compared to each other, never hard-coded here.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { BuildStateBadge, buildState } from "../src/components/BuildStateChip";
import type { BuildDocument } from "../src/api/types";
import { copy } from "../src/copy";

function render(build: BuildDocument | undefined): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<BuildStateBadge build={build} />);
  return host;
}

/** The minimal `ok` build document the chip and `buildState()` need. */
function okBuild(overrides: Partial<BuildDocument> = {}): BuildDocument {
  return {
    status: "ok",
    current: true,
    geometry_count: 1,
    geometries: [],
    artifact_ref: "artifact:build:sha256:" + "a".repeat(64),
    stale: false,
    stale_inputs: [],
    ...overrides,
  } as BuildDocument;
}

describe("buildState()", () => {
  it("reads stale BEFORE the current/preview split — a stale current build is `stale`, not `current`", () => {
    const build = okBuild({ current: true, stale: true, stale_inputs: ["script"] });
    expect(buildState(build)).toBe("stale");
  });

  it("a fresh current build is still `current` — `stale: false` must not become the default `preview`", () => {
    const build = okBuild({ current: true, stale: false, stale_inputs: [] });
    expect(buildState(build)).toBe("current");
  });

  it("a non-current build with no staleness fact is `preview` — the closed vocabulary's other producer", () => {
    const build = okBuild({ current: false, stale: false, stale_inputs: [] });
    expect(buildState(build)).toBe("preview");
  });

  it("a build with no staleness fact at all (a bundle written before the field existed) falls back to today's mapping", () => {
    // Additive-JSON compatibility (the ledger's fix design, item 9): older
    // bundles make `freshness()` return `None`, the keys are omitted, and the
    // client must not crash reading them.
    const { stale: _stale, stale_inputs: _staleInputs, ...rest } = okBuild({ current: true });
    const build = rest as BuildDocument;
    expect(buildState(build)).toBe("current");
  });

  it("`stale` outranks `current` even when both fields are literally true", () => {
    // `current` is publication state (architecture.md §3.5) and stays true;
    // `stale` is the separate freshness fact. Both true is exactly the B-5
    // reproduction's shape, and it must render as the word `stale`.
    const stale = okBuild({ current: true, stale: true, stale_inputs: ["script"] });
    const fresh = okBuild({ current: true, stale: false, stale_inputs: [] });
    expect(copy.buildState[buildState(stale) as "stale"]).not.toBe(
      copy.buildState[buildState(fresh) as "current"],
    );
  });
});

describe("<BuildStateBadge>", () => {
  it("prints the stale copy for {status: 'ok', current: true, stale: true}", () => {
    const host = render(okBuild({ current: true, stale: true, stale_inputs: ["script"] }));
    // The operator-visible word is the badge's own `build.status` Fact child.
    // `host.textContent` is NOT that word: the clipped boolean leaves
    // (`build.current`, `build.stale`) keep their serialized text — `Fact`'s
    // `silent` drops them from the accessibility tree and `.hidden` clips them
    // visually, but the node stays, because `data-value` and the text are one
    // value (`Fact.tsx`). Asserting on the whole host would be asserting on
    // that implementation detail rather than on what is read.
    const word = host.querySelector('[data-source="build.status"]')?.textContent;
    expect(word).toBe(copy.buildState.stale);
    expect(word).not.toBe(copy.buildState.current);
  });

  it("carries a `build.stale` Fact attribution beside `build.current`, matching the JSON", () => {
    const host = render(okBuild({ current: true, stale: true, stale_inputs: ["script"] }));
    const staleFact = host.querySelector('[data-source="build.stale"]');
    const currentFact = host.querySelector('[data-source="build.current"]');
    expect(staleFact).not.toBeNull();
    expect(currentFact).not.toBeNull();
    expect(staleFact?.getAttribute("data-value")).toBe("true");
    expect(currentFact?.getAttribute("data-value")).toBe("true");
  });

  it("never announces a bare true/false for `stale` (Fact's `silent` rule)", () => {
    const host = render(okBuild({ current: true, stale: true, stale_inputs: ["script"] }));
    const staleFact = host.querySelector('[data-source="build.stale"]');
    const currentFact = host.querySelector('[data-source="build.current"]');
    // `silent` is `aria-hidden` (#96): the leaf is a boolean hook, not a
    // sentence, so the bare word `true` is never announced — while `data-value`
    // and the text node stay, which is what the e2e indexes the JSON with. The
    // new fact is asserted to be attributed EXACTLY like the existing
    // `build.current` leaf rather than against a hand-copied shape.
    expect(staleFact?.getAttribute("aria-hidden")).toBe("true");
    expect(staleFact?.getAttribute("aria-hidden")).toBe(
      currentFact?.getAttribute("aria-hidden"),
    );
    expect(staleFact?.className).toBe(currentFact?.className);
    // The word the operator reads comes from the badge's `build.status` child,
    // never from this leaf.
    expect(host.querySelector('[data-source="build.status"]')?.textContent).toBe(
      copy.buildState.stale,
    );
  });

  it("the fresh case draws `build.stale=false` on the same Fact, not an absent attribute", () => {
    const host = render(okBuild({ current: true, stale: false, stale_inputs: [] }));
    const staleFact = host.querySelector('[data-source="build.stale"]');
    expect(staleFact?.getAttribute("data-value")).toBe("false");
  });
});
