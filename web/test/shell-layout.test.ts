// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Shell layout budget (INTERFACE.md §4.1). jsdom cannot measure pixels, so
// these assertions are on the CSS the grid and chips actually ship: the three
// columns must be able to sit in 1280px, and nothing in the stream may force
// a min-content wider than `--stream-width`.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatRef } from "../src/system";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "..", "src");

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("shell layout — usable at 1280px, not a 2400px desk", () => {
  const tokens = css("system/tokens.css");
  const shell = css("components/Shell.module.css");

  it("keeps the §4.1 column budget at or under 1280px", () => {
    const rail = /--rail-width:\s*(\d+)px/.exec(tokens);
    const stream = /--stream-width:\s*(\d+)px/.exec(tokens);
    expect(rail?.[1]).toBe("280");
    expect(stream?.[1]).toBe("420");
    expect(Number(rail?.[1]) + Number(stream?.[1])).toBeLessThanOrEqual(1280);
    // Stage gets the remainder: 1280 - 280 - 420 = 580, matching §4.1's table.
    expect(1280 - Number(rail?.[1]) - Number(stream?.[1])).toBe(580);
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

  it("shortens a full artifact ref to a chip that fits the 420px stream", () => {
    const ref =
      "artifact:build:sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3f67d4bac82b";
    expect(formatRef(ref).length).toBeLessThan(ref.length);
    expect(formatRef(ref).length).toBeLessThanOrEqual(34);
    const composer = readFileSync(join(webSrc, "components/stream/Composer.tsx"), "utf8");
    expect(composer).toMatch(/formatRef\(chip\.value/);
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
    const tree = css("components/rail/ProjectTree.module.css");
    expect(tree).toMatch(/\.panel\s*\{[^}]*flex:\s*none/);
    expect(tree).toMatch(/\.panel\s*\{[^}]*align-content:\s*start/);
  });
});
