// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import noDerivedFact from "./eslint-rules/no-derived-fact.js";
import designSystem from "./eslint-rules/design-system.js";
import * as cssParser from "./eslint-rules/css-parser.js";

// One plugin namespace for both rule files: `heph/no-derived-fact` keeps the
// name every `eslint-disable` and every reference in INTERFACE.md already uses,
// and §3.14's four checks join it rather than inventing a second prefix.
const heph = { rules: { ...noDerivedFact.rules, ...designSystem.rules } };

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "playwright-report/**", "test-results/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { heph, "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // INTERFACE.md §1: the client computes no fact. The rule is the mechanical
      // half of that boundary; see `eslint-rules/no-derived-fact.js` for exactly
      // what it decides and what it deliberately leaves to the e2e.
      "heph/no-derived-fact": "error",
      // §3.14's checks, on the TS side: a literal colour in a string, an inline
      // `style` that sets type, and a status attribute with no stylesheet beside
      // it. The CSS side of the same three runs in the `**/*.css` block below.
      "heph/no-palette-token": "error",
      "heph/no-raw-type": "error",
      "heph/system-owns-status": "error",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
      // INTERFACE.md §3, clean-room hygiene: all workspace copy lives in exactly
      // one module so a reviewer can audit it in one file. A string that reaches
      // the DOM from anywhere else defeats that.
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/copy.js", "**/copy"],
              importNames: ["default"],
              message:
                "Import the named `copy` record from `src/copy.ts`; there is no default export.",
            },
          ],
        },
      ],
    },
  },
  {
    // INTERFACE.md §3.14's four checks are facts about CSS, and §1's precedent
    // is that a boundary is a lint rule rather than a promise. `css-parser.js`
    // yields an empty `Program` spanning the stylesheet, so the rules below read
    // the text and every inherited JS rule finds nothing to say. No dependency
    // is added; §3.2's rejections all survive.
    files: ["**/*.css"],
    languageOptions: { parser: cssParser },
    plugins: { heph },
    rules: {
      "heph/no-palette-token": "error",
      "heph/no-raw-type": "error",
      "heph/token-contrast": "error",
    },
  },
  {
    // `<Fact>` is the primitive that *mints* `data-source`; the rule forbidding
    // every other element from writing one necessarily exempts its definition.
    // Scoped to this single file by path so the exemption cannot spread.
    files: ["src/components/Fact.tsx"],
    rules: { "heph/no-derived-fact": "off" },
  },
  {
    // §3.14's four checks are asserted against inputs they MUST reject, so this
    // file necessarily contains a palette token and a literal hex — the very
    // strings `no-palette-token` exists to refuse. Linting the test with the
    // rule it tests would make the rule unable to have a negative case, which
    // is the only kind of case that proves a check fires at all.
    files: ["test/system/checks.test.ts"],
    rules: { "heph/no-palette-token": "off" },
  },
  {
    // The eslint-rules directory is plain JS tooling, not app source.
    files: ["eslint-rules/**/*.js", "*.config.ts"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
  {
    // Fixture recorders are node scripts run by hand (`node web/test/fixtures/
    // record-*.mjs`), not bundled source. They are still linted; they are just
    // told which globals a node script has, which no `.ts` file here needs
    // because typescript-eslint resolves those through the compiler instead.
    files: ["test/fixtures/**/*.mjs"],
    languageOptions: { globals: { process: "readonly", console: "readonly" } },
  },
);
