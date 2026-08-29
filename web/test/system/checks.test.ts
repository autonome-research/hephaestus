// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §3.14's four checks, checked.
//
// "§1 made the client boundary a lint rule rather than a promise. The same move
// applies here; without it this section is a mood board with hex codes." A lint
// rule that does not fire is the same promise wearing a plugin, so each of the
// four is run here against an input it MUST reject and an input it must accept.
//
// `token-contrast` gets a second, stronger assertion: it is run against the REAL
// `system/tokens.css`, so the guarantee table §3.9 calls "the normative artefact"
// is verified on every `pnpm test` as well as on every `pnpm lint`. §3.14 says
// that check "catches a `--border-control` at 1.85:1, which is how that defect
// reached a spec draft in the first place" — this file proves it does, by
// feeding it exactly that.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ESLint } from "eslint";

import designSystem from "../../eslint-rules/design-system.js";
import * as cssParser from "../../eslint-rules/css-parser.js";

// `import.meta.url` is a `/@fs/…` URL under vitest's transform, so paths are
// resolved from the project root instead. The rules read `context.filename`, so
// what matters is only that the path ends where the exemption expects.
const ROOT = process.cwd();
const TOKENS_PATH = "src/system/tokens.css";
const TOKENS = resolve(ROOT, TOKENS_PATH);

/**
 * One linter configured exactly as `eslint.config.js` configures the rule under
 * test — the CSS block with `css-parser.js`, the TS block with JSX.
 *
 * The real `ESLint` class rather than `Linter.verify`, because a `files` pattern
 * is what decides that a `.css` file is linted at all, and a check that only
 * fires under a hand-built config is not the check `pnpm lint` runs.
 */
async function lint(
  code: string,
  path: string,
  rule: string,
  isCss: boolean,
): Promise<readonly string[]> {
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: [
      {
        files: [isCss ? "**/*.css" : "**/*.{ts,tsx}"],
        languageOptions: isCss
          ? { parser: cssParser as never }
          : { parserOptions: { ecmaFeatures: { jsx: true } } },
        plugins: { heph: designSystem },
        rules: { [`heph/${rule}`]: "error" },
      },
    ],
  });
  const results = await eslint.lintText(code, { filePath: resolve(ROOT, path) });
  return (results[0]?.messages ?? []).map((message) => message.message);
}

function css(code: string, path: string, rule: string): Promise<readonly string[]> {
  return lint(code, path, rule, true);
}

function tsx(code: string, path: string, rule: string): Promise<readonly string[]> {
  return lint(code, path, rule, false);
}

describe("no-palette-token (§3.6, §3.14)", () => {
  it("refuses a palette token spent outside the palette layer", async () => {
    const found = await css(
      ".a { color: var(--p-blue-500); }",
      "src/components/A.module.css",
      "no-palette-token",
    );
    expect(found).toHaveLength(1);
    expect(found[0]).toContain("--p-blue-500");
  });

  it("refuses a literal hex — the reason `.chip` and `.state` diverged", async () => {
    const found = await css(
      ".a { border: 1px solid #333b47; }",
      "src/components/A.module.css",
      "no-palette-token",
    );
    expect(found).toHaveLength(1);
  });

  it("accepts a semantic token, which is the entire public API", async () => {
    const found = await css(
      ".a { color: var(--ink-base); }",
      "src/components/A.module.css",
      "no-palette-token",
    );
    expect(found).toHaveLength(0);
  });

  it("exempts the palette's own home, and nothing else", async () => {
    const code = ":root { --p-blue-500: #4ea3f0; }";
    expect(await css(code, TOKENS_PATH, "no-palette-token")).toHaveLength(0);
    const elsewhere = await css(code, "src/system/other.css", "no-palette-token");
    expect(elsewhere.length).toBeGreaterThan(0);
  });

  it("refuses a hex in a TS string literal but ignores one in a comment", async () => {
    const inCode = await tsx('const c = "#0d0f12";', "src/viewport/engine.ts", "no-palette-token");
    expect(inCode).toHaveLength(1);
    // A check that cannot survive being written about is not a check.
    const inComment = await tsx(
      "// the shipped value was #0d0f12\nconst c = 1;",
      "src/viewport/engine.ts",
      "no-palette-token",
    );
    expect(inComment).toHaveLength(0);
  });
});

describe("no-raw-type (§3.8, §3.14)", () => {
  it("refuses each of the five properties outside the type layer", async () => {
    for (const property of [
      "font-size: 12px",
      "font-weight: 600",
      "letter-spacing: 0.08em",
      "text-transform: uppercase",
      "font-family: monospace",
    ]) {
      const found = await css(`.a { ${property}; }`, "src/components/A.module.css", "no-raw-type");
      expect(found.length, property).toBeGreaterThan(0);
    }
  });

  it("accepts a composed type role, which is what the rule is asking for", async () => {
    const found = await css(
      '.a { composes: label from "../system/type.module.css"; color: var(--ink-base); }',
      "src/components/A.module.css",
      "no-raw-type",
    );
    expect(found).toHaveLength(0);
  });

  it("keeps 11px inside `.eyebrow` and nowhere else (§3.8's TIGHTENING)", async () => {
    // The one rule that converts the shipped 65-of-91 distribution into a ramp.
    const elsewhere = await css(
      ".a { padding: 11px; }",
      "src/components/A.module.css",
      "no-raw-type",
    );
    expect(elsewhere.length).toBeGreaterThan(0);
    const inEyebrow = await css(
      ".eyebrow { font-size: 11px; }",
      "src/system/type.module.css",
      "no-raw-type",
    );
    expect(inEyebrow).toHaveLength(0);
    const inAnotherRole = await css(
      ".label { font-size: 11px; }",
      "src/system/type.module.css",
      "no-raw-type",
    );
    expect(inAnotherRole.length).toBeGreaterThan(0);
  });

  it("refuses an inline style that sets type", async () => {
    const typed = await tsx(
      "const a = <p style={{ fontSize: 11 }} />;",
      "src/components/A.tsx",
      "no-raw-type",
    );
    expect(typed).toHaveLength(1);
    const geometric = await tsx(
      "const a = <p style={{ paddingLeft: 8 }} />;",
      "src/components/A.tsx",
      "no-raw-type",
    );
    expect(geometric).toHaveLength(0);
  });
});

describe("system-owns-status (§3.4, §3.14)", () => {
  it("refuses a status attribute with no stylesheet beside it — the shipped P0", async () => {
    const found = await tsx(
      'const a = <li data-badge="pass" />;',
      "src/__no_such_directory__/ChecksPanel.tsx",
      "system-owns-status",
    );
    expect(found).toHaveLength(1);
    expect(found[0]).toContain("data-badge");
  });

  it("accepts the primitive that owns both halves", async () => {
    // `src/system/Badge.tsx` writes the three attributes and
    // `src/system/Badge.module.css` selects all three, in the same directory.
    const found = await tsx(
      'const a = <span data-badge="pass" />;',
      "src/system/Badge.tsx",
      "system-owns-status",
    );
    expect(found).toHaveLength(0);
  });
});

describe("token-contrast (§3.9, §3.13.1, §3.14)", () => {
  it("passes on the SHIPPED token file — the guarantee table, verified", async () => {
    expect(await css(readFileSync(TOKENS, "utf8"), TOKENS_PATH, "token-contrast")).toEqual([]);
  });

  it("catches a --border-control at 1.85:1, which is how the defect got in", async () => {
    const code = [
      "/* @permit ui --border-control : panel */",
      ":root {",
      "  --p-a: #2f3542;",
      "  --p-b: #161a20;",
      "  --border-control: var(--p-a);",
      "  --surface-panel: var(--p-b);",
      "}",
    ].join("\n");
    const found = await css(code, TOKENS_PATH, "token-contrast");
    expect(found).toHaveLength(1);
    expect(found[0]).toContain("below the ui floor");
  });

  it("catches text below 4.5:1 against a surface it is permitted on", async () => {
    const code = [
      "/* @permit text --ink-muted : panel */",
      ":root { --p-a: #4a5262; --p-b: #161a20; --ink-muted: var(--p-a); --surface-panel: var(--p-b); }",
    ].join("\n");
    const found = await css(code, TOKENS_PATH, "token-contrast");
    expect(found).toHaveLength(1);
  });

  it("encodes §3.9's two refusals rather than asserting them in prose", async () => {
    // `--ink-muted` on `--surface-overlay`, and `--ink-faint` as text at all.
    const muted = [
      "/* @permit text --ink-muted : overlay */",
      "/* @refuse --ink-muted : overlay */",
      ":root { --p-a: #eef1f6; --p-b: #30374a; --ink-muted: var(--p-a); --surface-overlay: var(--p-b); }",
    ].join("\n");
    const mutedFound = await css(muted, TOKENS_PATH, "token-contrast");
    expect(mutedFound).toHaveLength(1);
    expect(mutedFound[0]).toContain("@refuse");

    const faint = [
      "/* @permit text --ink-faint : panel */",
      "/* @refuse-text --ink-faint */",
      ":root { --p-a: #eef1f6; --p-b: #161a20; --ink-faint: var(--p-a); --surface-panel: var(--p-b); }",
    ].join("\n");
    const faintFound = await css(faint, TOKENS_PATH, "token-contrast");
    expect(faintFound).toHaveLength(1);
    expect(faintFound[0]).toContain("not-a-text-token");
  });

  // The `part` class, added 2026-08-28 with plan item 6 for §3.11.2's "≥ 4.5:1
  // part vs ground, exporter-independent". Both sides, on the §3.14 precedent
  // that a check with no negative case is a check that cannot fail.
  it("holds --viewport-part to §3.11.2's 4.5:1 against the ground", async () => {
    const table = "/* @permit part --viewport-part : canvas */";
    const declare = (part: string): string =>
      `${table}\n:root { --p-a: ${part}; --p-b: #080a0d; --viewport-part: var(--p-a); --surface-canvas: var(--p-b); }`;

    // The shipped `--p-part`, which clears the floor with room above it.
    expect(await css(declare("#b8c2cf"), TOKENS_PATH, "token-contrast")).toEqual([]);

    // And a part the exporter's own palette would produce: `id_to_rgb(0)` is
    // `(0, 0, 1)`, the value §3.11.2 exists because of. It fails by the number
    // the spec writes out, not by the `ui` floor one class down.
    const black = await css(declare("#000001"), TOKENS_PATH, "token-contrast");
    expect(black).toHaveLength(1);
    expect(black[0]).toContain("below the part floor of 4.5");
  });

  it("refuses to pass vacuously when the table is empty", async () => {
    const found = await css(":root { --ink-base: #ffffff; }", TOKENS_PATH, "token-contrast");
    expect(found).toHaveLength(1);
  });
});
