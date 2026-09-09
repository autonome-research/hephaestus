import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // `build/**` is the bundled sidecar: 14 MB of generated third-party code.
    ignores: [
      "dist/**",
      "build/**",
      "node_modules/**",
      "src/tools/schema.gen.ts",
      "coverage/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      // The Pi SDK boundary needs isolated casts; ban `any` everywhere else.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Stage S disposition 4 (binding): thread-phase may be imported ONLY via
      // its `/session` and `/patterns` subpaths — the root barrel eagerly loads
      // the transitive `openai` SDK, which the packaged sidecar must not carry.
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@autonome-research/thread-phase",
              message:
                "Import thread-phase via '@autonome-research/thread-phase/session' or '/patterns' only: the root barrel eagerly loads the transitive openai SDK (Stage S disposition 4).",
            },
          ],
          patterns: [
            {
              group: ["@autonome-research/thread-phase/dist/*"],
              message:
                "Deep dist paths are not part of thread-phase's public exports; use the '/session' or '/patterns' subpath.",
            },
          ],
        },
      ],
    },
  },
  {
    // ---- TYPE-AWARE RULES (J-mirrors-and-dx-36) --------------------------
    //
    // Both lint configurations used the untyped preset — the default scaffold's
    // output — so the rules that need type information were simply unavailable,
    // and the most valuable of them is the one this package most needs: the
    // entry module stands in for `no-floating-promises` by hand, with the `void`
    // operator, at two sites.
    //
    // MEASURED before choosing, the way the repository treats its performance
    // ceilings (2026-09-07, this checkout):
    //
    //   * the whole `recommendedTypeChecked` preset over `src/`: 51 findings —
    //     36 `no-base-to-string`, 13 `no-unnecessary-type-assertion`, 2
    //     `require-await` — and 4.7 s -> 25.7 s;
    //   * the three promise rules alone: ZERO findings, same wall time (the cost
    //     is the type information, not the rule count).
    //
    // So the three land and the preset does not: 51 findings is a cleanup PR of
    // its own, and adopting a preset by silencing it is how an exclusion list
    // starts. The decision is recorded here rather than in a commit message
    // because the next author will otherwise re-run the same measurement.
    //
    // SCOPED TO `src/` for a reason, not by preference: type-aware linting needs
    // the type configuration to cover every linted file, and `tsconfig.json`
    // includes the source only — widening it is J-mirrors-and-dx-28, which is
    // blocked on splitting the build configuration from the check
    // configuration. Extend `files` here in the same change.
    files: ["src/**/*.ts"],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/await-thenable": "error",
    },
  },
);
