// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-viewport-1: the panel body's three-column grid (INTERFACE.md §4.7).
// jsdom cannot measure pixels or resolve `subgrid` tracks (see
// `shell-layout.test.ts`'s own note), so — like that file — this asserts on
// the CSS the panel and its children actually ship, which is exactly the rule
// whose *absence* produced the 487.625px label column: `.body > *` had a
// full-span, zero-minimum rule and `.section > *` did not, so a `PanelNote`
// inside a `PanelSection` auto-placed into column 1 and its `max-width: 68ch`
// became the label track's intrinsic size.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "..", "..", "src");

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("Panel body tracks — a section's children span like the body's own (§4.7)", () => {
  const panel = css("system/Panel.module.css");

  it("gives the body's direct children a full span and a zero minimum", () => {
    // The rule this bug's counterpart already exists beside.
    expect(panel).toMatch(/\.body\s*>\s*\*\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;[^}]*min-width:\s*0;?[^}]*\}/);
  });

  it("gives a SECTION's direct children the identical full span and zero minimum", () => {
    // This is the rule whose absence was the root cause: a section is a
    // subgrid over the body's tracks, so anything inside it that does not
    // itself declare a column lands in column 1 by auto-placement and its
    // measure-limited max-width becomes that track's intrinsic size.
    expect(panel).toMatch(
      /\.section\s*>\s*\*\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;[^}]*min-width:\s*0;?[^}]*\}/,
    );
  });

  it("declares the section rule at the same specificity as the body rule (one class, universal child)", () => {
    // Both selectors are `.<class> > *` — a single class combined with a
    // child combinator and a universal selector — so neither rule can lose to
    // the other by specificity; only source order or `!important` could, and
    // neither file uses `!important` for this pair.
    expect(panel).not.toMatch(/!important/);
    const bodyRule = /\.body\s*>\s*\*\s*\{/.exec(panel);
    const sectionRule = /\.section\s*>\s*\*\s*\{/.exec(panel);
    expect(bodyRule).not.toBeNull();
    expect(sectionRule).not.toBeNull();
  });
});

describe("DataTable claims the last word on its own span (§4.7)", () => {
  const table = css("system/DataTable.module.css");

  it("declares its own full span and subgrid at the same specificity as the panel's generic rule", () => {
    // The panel's `.section > *` / `.body > *` rules give ANYTHING a full span
    // and a zero minimum; `.table` restates the same span itself (rather than
    // relying on inheriting the parent's rule) so a `DataTable` is never at the
    // mercy of cascade order between two stylesheets.
    expect(table).toMatch(/\.table\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;[^}]*\}/);
    expect(table).toMatch(/\.table\s*\{[^}]*grid-template-columns:\s*subgrid;?[^}]*\}/);
  });

  it("gives each row the same subgrid span, so every table in one panel aligns down the drawer", () => {
    expect(table).toMatch(/\.row\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;[^}]*grid-template-columns:\s*subgrid;?[^}]*\}/);
  });
});
