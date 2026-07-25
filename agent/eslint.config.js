import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**", "src/tools/schema.gen.ts", "coverage/**"],
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
);
