// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Shell layout budget (INTERFACE.md §4.1). jsdom cannot measure pixels, so
// these assertions are on the CSS the grid and chips actually ship: the three
// columns must be able to sit in 1280px, and nothing in the stream may force
// a min-content wider than `--stream-width`.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { copy } from "../src/copy";
import { formatRef } from "../src/system";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "..", "src");

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("shell layout — usable at 1280px, not a 2400px desk", () => {
  const tokens = css("system/tokens.css");
  const shell = css("components/Shell.module.css");

  it("keeps the §4.1 column budget at or under 1280px, with the §4.1(g) clamp", () => {
    const rail = /--rail-width:\s*(\d+)px/.exec(tokens);
    // §4.1(g), amended 2026-09-02 (C12): the expanded stream track is
    // `clamp(360px, 30vw, 420px)` — the diagram's 420px is the clamp's MAXIMUM.
    const stream = /--stream-width:\s*clamp\(\s*(\d+)px,\s*(\d+)vw,\s*(\d+)px\s*\)/.exec(tokens);
    expect(rail?.[1]).toBe("280");
    expect(stream?.[1]).toBe("360");
    expect(stream?.[2]).toBe("30");
    expect(stream?.[3]).toBe("420");
    // At the 1280px collapse boundary the clamp yields 30vw = 384px, so the
    // three columns fit with the stage at 1280 - 280 - 384 = 616px.
    const atBoundary = Math.max(360, Math.min(0.3 * 1280, 420));
    expect(atBoundary).toBe(384);
    expect(Number(rail?.[1]) + atBoundary).toBeLessThanOrEqual(1280);
  });

  it("writes the clamp into the data-stream-driven rule's token, not a media query (§4.1(g))", () => {
    // The negative half, stated: no media query implements the clamp — §4.1(a)'s
    // "no media query that changes `grid-template-columns`" survives verbatim,
    // and the grid rule still reads the one token the clamp lives in.
    expect(shell).not.toMatch(/@media[^{]*\{[^}]*grid-template-columns/);
    // Four tracks since 2026-09-20 (Views | Parts | Stage | Agent); the rule
    // still reads tokens rather than literals, which is what §4.1(g) is about.
    expect(shell).toMatch(
      /grid-template-columns:\s*var\(--views-width\)\s+var\(--rail-width\)\s+minmax\(0,\s*1fr\)\s+var\(--stream-width\)/,
    );
    expect(tokens).not.toMatch(/--stream-width:\s*420px/);
  });

  it("lets every column shrink below min-content so a chip cannot blow the grid", () => {
    expect(shell).toMatch(/\.shell\s*\{[^}]*min-width:\s*0/);
    expect(shell).toMatch(/\.body\s*\{[^}]*min-width:\s*0/);
    expect(shell).toMatch(/\.rail\s*\{[^}]*min-width:\s*0/);
    expect(shell).toMatch(/\.stream\s*\{[^}]*min-width:\s*0/);
    expect(shell).toMatch(/\.stage\s*\{[^}]*min-width:\s*0/);
  });

  it("does not change grid-template-columns from a media query", () => {
    expect(shell).not.toMatch(/@media[^{]*\{[^}]*grid-template-columns/);
  });

  it("keeps the Stream a full column when the Rail is hidden", () => {
    const railHidden =
      /\.body\[data-rail="overlay"\],\s*\.body\[data-rail="hidden"\]\s*\{([^}]*)\}/.exec(
        shell,
      )?.[1] ?? "";

    // The narrow-viewport regression rendered StreamPanel while a later
    // `[data-rail]` rule kept its track at 44px. A hidden Rail must still give
    // the Stream the full `--stream-width` column.
    // Views keeps its track when Parts becomes an overlay (2026-09-20).
    expect(railHidden).toMatch(
      /grid-template-columns:\s*var\(--views-width\)\s+minmax\(0,\s*1fr\)\s+var\(--stream-width\)/,
    );
    expect(railHidden).not.toContain("var(--stream-strip-width)");
    // A collapsed Agent zeroes its width INLINE (`Shell.tsx`), not here: the
    // token is an inline custom property and no stylesheet rule can beat one.
    // The template is untouched either way, so two rules cannot disagree about
    // the shape (2026-09-20).
    expect(shell).not.toMatch(/\[data-stream="collapsed"\]\s*\{[^}]*--stream-width/);
    expect(shell).toMatch(/\[data-stream="collapsed"\]\s*\.stream\s*\{[^}]*overflow:\s*hidden/);
    expect(shell).not.toContain("--stream-strip-width");
    expect(shell).not.toContain("writing-mode: vertical-rl");
  });

  it("shortens a full artifact ref to a chip that fits the 420px stream", () => {
    const ref =
      "artifact:build:sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3f67d4bac82b";
    expect(formatRef(ref).length).toBeLessThan(ref.length);
    expect(formatRef(ref).length).toBeLessThanOrEqual(34);
    // 2026-09-20: the composer's context chips were struck with the readout,
    // so the pin is the only place a ref is abbreviated for a narrow column.
    // `formatRef`'s own bound above is what this case is actually about.
    const pin = readFileSync(join(webSrc, "components/ArtifactPin.tsx"), "utf8");
    expect(pin).toMatch(/CHIP_REF_WIDTH/);
  });

  it("gives the body one definite row so an 800px shell cannot grow", () => {
    expect(shell).toMatch(/\.body\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/);
  });
});

/*
 * J-web-stream-1: the stream aside kept a two-row `grid-template-rows` written
 * for a child dd9ee1c deleted (the eyebrow band). With one child auto-placed
 * into a content-sized first row, the second row absorbed ~780px with nothing
 * in it and `StreamPanel`'s `height: 100%` resolved against a content-sized
 * track — the composer sat under the tab strip instead of at the column's
 * bottom. This is "one line that would have caught the deletion": the aside's
 * row template must be a SINGLE definite row, in both of its states, because it
 * holds exactly one child in both.
 */
describe("stream aside — one child, one row (J-web-stream-1)", () => {
  const shell = css("components/Shell.module.css");
  const shellSrc = readFileSync(join(webSrc, "components/Shell.tsx"), "utf8");

  it("gives the .stream aside exactly one definite row, not a two-row template with a leftover track", () => {
    const rule = /^\.stream\s*\{([^}]*)\}/m.exec(shell);
    expect(rule, ".stream rule not found").not.toBeNull();
    const body = rule?.[1] ?? "";
    expect(body).toMatch(/grid-template-rows:\s*minmax\(0,\s*1fr\)\s*;/);
    // The defect was a template with two tracks (e.g. `auto minmax(0, 1fr)` or
    // `auto 1fr`); guard directly against a second track reappearing. Splitting
    // naively on whitespace would miscount `minmax(0, 1fr)` as two tokens (the
    // comma inside the function), so track boundaries are counted at
    // top-level (paren-depth zero) commas/spaces instead.
    const rows = /grid-template-rows:\s*([^;]+);/.exec(body)?.[1] ?? "";
    let depth = 0;
    let tracks = rows.trim() === "" ? 0 : 1;
    for (const ch of rows.trim()) {
      if (ch === "(") depth += 1;
      else if (ch === ")") depth -= 1;
      else if (/\s/.test(ch) && depth === 0) tracks += 1;
    }
    expect(tracks).toBe(1);
  });

  it("does not declare a second, collapsed-state row template that could drift from the first", () => {
    // The two states used to disagree — the collapsed override already had the
    // correct single-row template and the open state did not. Now that they
    // are unified there must be exactly one `.stream` rule carrying
    // `grid-template-rows`, not two that have to be kept in sync by hand.
    const occurrences = [...shell.matchAll(/\.stream[^{]*\{[^}]*grid-template-rows/g)];
    expect(occurrences.length).toBe(1);
  });

  it("renders exactly one child of the aside, unconditionally", () => {
    // A source-level companion to the CSS assertion above: the row template is
    // only safe to be a single definite row if the aside truly holds ONE child.
    // Since C25 (2026-09-20) there is no second branch to keep in step — the
    // Stream has one drawn state — so the assertion is that the child is
    // `<StreamPanel />` and that nothing branches around it.
    const asideMatch = /<aside\s+className=\{styles\["stream"\]\}[^>]*>([\s\S]*?)<\/aside>/.exec(
      shellSrc,
    );
    expect(asideMatch, "could not find the stream <aside> in Shell.tsx").not.toBeNull();
    const body = (asideMatch?.[1] ?? "").trim();
    expect(body).toBe("<StreamPanel />");
  });

  it("keeps a closed region in the grid rather than removing it", () => {
    // Measured, not inferred: `display: none` drops a grid item from
    // auto-placement, so closing Parts moved the Stage into the 0px rail track
    // and handed its `1fr` to the Agent — 852px of chat beside a stage of
    // nothing. Both closed regions clip instead, and `inert` (not `display`)
    // is what takes them out of the tab order.
    expect(shell).not.toMatch(/\[data-(rail="closed"|stream="collapsed")\][^{]*\{[^}]*display:\s*none/);
    expect(shell).toMatch(/\[data-rail="closed"\]\s*\.rail\s*\{[^}]*overflow:\s*hidden/);
    expect(shellSrc).toMatch(/shell\.railOpen \? \{\} : \{ inert: "" \}/);
    expect(shellSrc).toMatch(/!shell\.streamOpen \? \{ inert: "" \}/);
  });
});

describe("left rail — no dead band between the section list and Working tree", () => {
  it("does not grow the versions panel into leftover height", () => {
    const versions = css("components/rail/VersionList.module.css");
    expect(versions).toMatch(/\.panel\s*\{[^}]*flex:\s*none/);
    expect(versions).not.toMatch(/flex:\s*1 1 auto/);
  });

  it("keeps every rail child content-sized", () => {
    const shell = css("components/Shell.module.css");
    expect(shell).toMatch(/\.rail\s*>\s*\*\s*\{[^}]*flex:\s*0 0 auto/);
    expect(shell).toMatch(/\.rail\s*>\s*\*\s*\{[^}]*min-width:\s*0/);
    const tree = css("components/rail/ProjectTree.module.css");
    expect(tree).toMatch(/\.panel\s*\{[^}]*flex:\s*none/);
    expect(tree).toMatch(/\.panel\s*\{[^}]*align-content:\s*start/);
  });
});

/*
 * §4.1(f) + §19 item 42, amended 2026-09-01, WITHDRAWN 2026-09-20.
 *
 * The breakpoint prose promised "a docked strip with an unread count" and
 * nothing ever built one. The 2026-09-01 amendment withdrew the count; C25
 * has now withdrawn the strip itself, because the Stream is a peer column
 * with one drawn state and there is nothing to dock or return from.
 *
 * What survives is the half that was never about the strip: "unread" is not a
 * fact this product has. Live events are keyed `(run_id, seq)` and historical
 * ones `(session_id, ordinal)` with no read watermark on either side, so a
 * count would be client-side derived state (§1). A deferral with no assertion
 * is how the original clause rotted, so the deferral keeps one.
 */
describe("§4.1(f) — no unread count, and nothing left to draw one on", () => {
  it("keeps no unread copy for a control to draw", () => {
    // A copy key waiting for a control is the dead surface §0.2b's repair (c)
    // is about. (The word itself survives in `unknownKind`, where "shown
    // unread" describes an event outside the vocabulary; it is the KEY that
    // would be the surface.)
    expect(Object.keys(copy.stream).filter((key) => /unread/i.test(key))).toEqual([]);
  });

  it("has no return strip left to badge", () => {
    // The negative half of C25's removal, on disk rather than in prose.
    expect(existsSync(join(webSrc, "components/stream/ConversationReturn.tsx"))).toBe(false);
    const styles = css("components/Shell.module.css");
    expect(styles).not.toContain(".strip");
    expect(styles).not.toContain(".stripLabel");
  });
});
