// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * A stylesheet parser for ESLint, adding no dependency.
 *
 * INTERFACE.md §3.14 asks for four checks — `no-palette-token`, `no-raw-type`,
 * `system-owns-status`, `token-contrast` — "on the `no-derived-fact`
 * precedent", and three of the four are facts about CSS. The precedent §1 set
 * was a **lint rule rather than a promise**, and running them anywhere but
 * `pnpm lint` would reintroduce the gap: a check nobody runs is prose again,
 * which is the exact criticism §3.13 opens with.
 *
 * ESLint will lint any file a flat-config block claims, but it needs a parser
 * that yields an ESTree `Program`. This is that parser and nothing more: it
 * produces an **empty** program spanning the file, so every JS rule that might
 * inherit onto a `.css` file finds nothing to report, and the four design rules
 * read `context.sourceCode.text` directly. That is the honest shape — §3.14
 * calls the checks "grep-shaped", and grep-shaped is what they are; what the
 * parser buys is that they run in the same command, on the same file list, with
 * the same reporting as every other rule in this repo.
 *
 * *Rejected:* `@eslint/css` and any other stylesheet plugin. §3.2's dependency
 * ruling is that every rejection survives, and a lint dependency is a dependency
 * — the four checks are a hundred lines of string work between them.
 */

/** @param {string} text */
export function parseForESLint(text) {
  const lines = text.split("\n");
  const lastLine = lines[lines.length - 1] ?? "";
  return {
    ast: {
      type: "Program",
      body: [],
      comments: [],
      tokens: [],
      sourceType: "script",
      range: [0, text.length],
      loc: {
        start: { line: 1, column: 0 },
        end: { line: lines.length, column: lastLine.length },
      },
    },
    visitorKeys: { Program: ["body"] },
  };
}

export default { parseForESLint };
