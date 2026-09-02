// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §4.7 (C11) and §3.9 (C28), amended 2026-09-02 — the chip recipe's two token
// decisions, asserted on the stylesheet the way `shell-layout.test.ts` asserts
// the grid (jsdom computes no CSS-module styles; the file is the artifact).
//
// C11: "a chip whose `data-status` is `ok` draws its card edge with `--border`
// (the seam token); only a chip whose status is non-terminal or failed —
// `running`, `error`, or `unknown` — draws `--border-strong`." Detachment is
// the exception's signal. Both sides are asserted: the resting rule uses the
// seam token, the exception selector names EXACTLY the three loud statuses,
// and no `ok` selector reaches for `--border-strong`.
//
// C28: "no inert element draws accent ink or fill in any state." The named
// offender was the reference-field name rule, which drew `snapshot_ref` in
// `--accent` as inert text. The attribute survives; the accent does not.
// The browser half of C28 (the computed-style sweep) is
// `e2e/design-system.spec.ts`'s; this is the file-shaped half that fails in
// `pnpm test` before a browser ever starts.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const webSrc = join(dirname(fileURLToPath(import.meta.url)), "../../src");

function css(relative: string): string {
  return readFileSync(join(webSrc, relative), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

const transcript = css("components/stream/Transcript.module.css");

describe("§4.7 (C11) — a finished, successful tool card rests on the seam border", () => {
  it("gives the resting .chip the seam token, not the detached one", () => {
    const block = /\.chip\s*\{([^}]*)\}/.exec(transcript);
    expect(block?.[1]).toMatch(/border:\s*1px solid var\(--border\)/);
    expect(block?.[1]).not.toMatch(/--border-strong/);
  });

  it("detaches exactly running, error and unknown — the closed loud set", () => {
    const exception =
      /((?:\.chip\[data-status="[a-z]+"\],?\s*)+)\{([^}]*)\}/.exec(transcript);
    expect(exception).not.toBeNull();
    const statuses = [...(exception?.[1] ?? "").matchAll(/data-status="([a-z]+)"/g)]
      .map((m) => m[1])
      .sort();
    expect(statuses).toEqual(["error", "running", "unknown"]);
    expect(exception?.[2]).toMatch(/border-color:\s*var\(--border-strong\)/);
  });

  it("never selects an ok chip for the strong border (the negative half)", () => {
    expect(transcript).not.toMatch(/data-status="ok"[^{]*\{[^}]*--border-strong/);
  });
});

describe("§3.9 (C28) — the reference-field name is inert text and draws no accent", () => {
  it("keeps the data-field-reference hook but de-accents its ink to muted", () => {
    const rule = /\.field\[data-field-reference="true"\]\s*\.fieldName\s*\{([^}]*)\}/.exec(
      transcript,
    );
    expect(rule).not.toBeNull();
    expect(rule?.[1]).toMatch(/color:\s*var\(--ink-muted\)/);
    expect(rule?.[1]).not.toMatch(/--accent/);
  });

  it("spends accent in this stylesheet only where an interaction answers it", () => {
    // The transcript's remaining accent uses are the ask_user widget's — the
    // one row that IS a request for interaction (§7A.7). Nothing else in this
    // file may buy the colour; a new `--accent` here must land in the ask
    // block or move to a control recipe.
    const uses = [...transcript.matchAll(/^\s*([^{}]+)\{[^}]*var\(--accent\)[^}]*\}/gm)].map(
      (m) => (m[1] ?? "").trim(),
    );
    for (const selector of uses) {
      expect(selector, `accent outside the ask widget: ${selector}`).toMatch(/\.ask/);
    }
  });

  it("keeps the product mark off the accent fill (Header)", () => {
    const header = css("components/Header.module.css");
    const mark = /\.mark\s*\{([^}]*)\}/.exec(header);
    expect(mark?.[1]).toMatch(/background:\s*var\(--ink-strong\)/);
    expect(mark?.[1]).not.toMatch(/--accent/);
  });
});
