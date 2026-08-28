// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import heph from "./eslint-rules/no-derived-fact.js";

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
    // `<Fact>` is the primitive that *mints* `data-source`; the rule forbidding
    // every other element from writing one necessarily exempts its definition.
    // Scoped to this single file by path so the exemption cannot spread.
    files: ["src/components/Fact.tsx"],
    rules: { "heph/no-derived-fact": "off" },
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
