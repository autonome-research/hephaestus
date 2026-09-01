// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §3.14's COMPONENT test, and the split is the point.
//
// The 2026-08-28 review correction, quoted because it is the whole reason this
// file exists rather than a Playwright spec: "an earlier draft put the whole
// no-colour-only assertion in Playwright over the fixture, where it cannot run.
// `not_run` has no producer in the public clean-room fixture, deliberately and
// with a written refusal, so a browser assertion over it has nothing to render."
//
// So: this test renders **all six** `Badge` statuses DIRECTLY and asserts a
// distinct icon id **and** distinct text for each. That covers `not_run` without
// faking an engine state, and it is what actually catches the `ChecksPanel`
// class of bug — an attribute one element away from its selector.
//
// It also forces the VOCABULARY to be honest: two statuses may not share an
// icon id, so `info` and `dirty` take different ids rather than both taking
// `dot`. `dirty` and `error` also take different hues (brass vs amber, #81).
//
// Clean-room hygiene (§3, §3.14): no assertion here is on a string of UI copy.
// Where a visible distinction is the obligation, the assertion is that two
// states render **different** text — never that either says any particular
// words. The words come from `copy.ts` and are compared to each other.

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import {
  BADGE_ICONS,
  BADGE_STATUSES,
  Badge,
  CHIP_ICONS,
  CHIP_STATUSES,
  ICON_IDS,
  Icon,
  SEVERITIES,
  SEVERITY_ICONS,
  SeverityBadge,
  StatusBadge,
} from "../../src/system";
import { copy } from "../../src/copy";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

/** The word each check-badge status renders. Six words, from `copy.ts` only. */
const WORD: Readonly<Record<string, string>> = {
  pass: copy.checks.badge.pass,
  fail: copy.checks.badge.fail,
  error: copy.checks.badge.error,
  not_run: copy.checks.badge.not_run,
  info: copy.buildState.preview,
  dirty: copy.rail.dirtyShort,
};

describe("§3.14 — every Badge status differs in icon AND in text", () => {
  it("renders all six statuses, including the one the fixture cannot reach", () => {
    // The list is the vocabulary, not a copy of it: a status added to
    // `BADGE_STATUSES` without an icon or a word fails here rather than shipping
    // as a badge that computes to the neutral fallback.
    expect([...BADGE_STATUSES]).toEqual(["pass", "fail", "error", "not_run", "info", "dirty"]);
    expect(BADGE_STATUSES).toContain("not_run");
  });

  it("emits data-badge ON THE STYLED ELEMENT, never one element away", () => {
    // The shipped P0, asserted as unrepresentable: `ChecksPanel.tsx`:59 put
    // `data-badge` on the `<li>` while the CSS selected `.badge[data-badge=…]`
    // one level down. Here the attribute and the class are on the same node by
    // construction, so the selector cannot miss.
    for (const status of BADGE_STATUSES) {
      const host = render(<Badge status={status}>{WORD[status]}</Badge>);
      const node = host.querySelector("[data-badge]");
      expect(node, status).not.toBeNull();
      expect(node?.getAttribute("data-badge")).toBe(status);
      expect(node?.getAttribute("class") ?? "", status).not.toBe("");
      // The icon is INSIDE the element that carries the status, so an icon in a
      // danger-ink badge is red with no icon-specific rule (§3.12).
      expect(node?.querySelector("svg[data-icon]"), status).not.toBeNull();
    }
  });

  it("gives every status its OWN icon id — none shared", () => {
    const ids = BADGE_STATUSES.map((status) => BADGE_ICONS[status]);
    expect(new Set(ids).size, "two statuses share an icon id").toBe(BADGE_STATUSES.length);
    // §3.14 names the pair this rule exists for by name.
    expect(BADGE_ICONS.info).not.toBe(BADGE_ICONS.dirty);
  });

  it("gives dirty its own brass, not error amber (#81)", () => {
    const tokens = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../../src/system/tokens.css"),
      "utf8",
    );
    expect(tokens).toMatch(/--status-error-ink:\s*var\(--p-amber-400\)/);
    expect(tokens).toMatch(/--status-dirty-ink:\s*var\(--p-brass-400\)/);
    expect(tokens).toMatch(/--p-brass-400:\s*#c4a35a/);
    expect(tokens).not.toMatch(/--status-dirty-ink:\s*var\(--p-amber-400\)/);
    expect(tokens).not.toMatch(/--status-dirty-ink:\s*var\(--p-grey/);
    expect(tokens).not.toMatch(/--status-dirty-ink:\s*var\(--status-error-ink\)/);
  });

  it("renders a DISTINCT icon id and DISTINCT text for each of the six", () => {
    const seenIcons = new Set<string>();
    const seenText = new Set<string>();
    for (const status of BADGE_STATUSES) {
      const host = render(<Badge status={status}>{WORD[status]}</Badge>);
      const node = host.querySelector("[data-badge]");
      const icon = node?.querySelector("svg[data-icon]")?.getAttribute("data-icon") ?? "";
      // The word, with the icon's own markup removed — an `<svg>` contributes no
      // text, so `textContent` is exactly what a reader reads.
      const text = (node?.textContent ?? "").trim();
      expect(icon, `${status} has no icon`).not.toBe("");
      expect(text, `${status} has no word`).not.toBe("");
      expect(seenIcons.has(icon), `${status} reuses an icon id`).toBe(false);
      expect(seenText.has(text), `${status} reuses a word`).toBe(false);
      seenIcons.add(icon);
      seenText.add(text);
    }
    expect(seenIcons.size).toBe(6);
    expect(seenText.size).toBe(6);
  });

  it("carries a fill and no border, except not_run which is dashed (§4.7)", () => {
    // The fill is REQUIRED, not optional: "a 1px hairline in an accent hue at
    // 11px is not a status signal at arm's length". The stylesheet is not loaded
    // in jsdom, so what is asserted here is the *contract the CSS selects on* —
    // that `not_run` is distinguishable from every other status by its attribute
    // alone, which is what lets one rule give it the dashed border.
    const host = render(<Badge status="not_run">{WORD["not_run"]}</Badge>);
    expect(host.querySelector('[data-badge="not_run"]')).not.toBeNull();
    expect(host.querySelector('[data-badge="pass"]')).toBeNull();
  });
});

describe("§3.14 — the other two status vocabularies keep the same recipe", () => {
  it("renders every §6.4 severity with its own icon and its own attribute", () => {
    const ids = SEVERITIES.map((severity) => SEVERITY_ICONS[severity]);
    expect(new Set(ids).size).toBe(SEVERITIES.length);
    for (const severity of SEVERITIES) {
      const host = render(<SeverityBadge severity={severity}>{severity}</SeverityBadge>);
      const node = host.querySelector("[data-severity]");
      expect(node?.getAttribute("data-severity")).toBe(severity);
      expect(node?.querySelector("svg[data-icon]")).not.toBeNull();
    }
  });

  it("renders every §7.2 chip status with its own icon and its own attribute", () => {
    const ids = CHIP_STATUSES.map((status) => CHIP_ICONS[status]);
    expect(new Set(ids).size).toBe(CHIP_STATUSES.length);
    for (const status of CHIP_STATUSES) {
      const host = render(
        <StatusBadge status={status}>{copy.stream.chip.status[status]}</StatusBadge>,
      );
      const node = host.querySelector("[data-chip-status]");
      expect(node?.getAttribute("data-chip-status")).toBe(status);
      expect(node?.querySelector("svg[data-icon]")).not.toBeNull();
    }
  });

  it("forwards an addressing attribute onto the styled element (G4.4's pairing)", () => {
    // `dom.spec.ts` reads `data-check` and `data-badge` off the SAME node. The
    // primitive owns the status attribute and forwards the addressing one, which
    // is how §3.14's migration criterion — "no selector changes" — is met
    // without a call site ever writing `data-badge`.
    const host = render(
      <Badge status="pass" data-check="wall_thickness">
        {WORD["pass"]}
      </Badge>,
    );
    const node = host.querySelector('[data-check="wall_thickness"]');
    expect(node?.getAttribute("data-badge")).toBe("pass");
  });
});

describe("§3.12 — the sprite is closed and every id it names resolves", () => {
  it("names exactly 18 ids", () => {
    expect(ICON_IDS).toHaveLength(18);
    expect(new Set(ICON_IDS).size).toBe(18);
  });

  it("draws exactly one path per icon, with no embedded colour", () => {
    // Every id, not just the ones a badge happens to use: §3.12's rules are
    // about the sprite, and an id nobody renders today is an id someone renders
    // tomorrow. `d` is asserted non-empty so a missing entry is a failure rather
    // than an invisible icon.
    for (const id of ICON_IDS) {
      const host = render(<Icon id={id} />);
      const svg = host.querySelector("svg");
      expect(svg?.getAttribute("data-icon"), id).toBe(id);
      expect(svg?.getAttribute("viewBox"), id).toBe("0 0 16 16");
      expect(svg?.getAttribute("stroke"), id).toBe("currentColor");
      expect(svg?.getAttribute("fill"), id).toBe("none");
      const paths = svg?.querySelectorAll("path") ?? [];
      expect(paths, id).toHaveLength(1);
      expect((paths[0]?.getAttribute("d") ?? "").length, id).toBeGreaterThan(4);
      expect(host.innerHTML, id).not.toContain("<style");
      expect(host.innerHTML, id).not.toContain("Gradient");
      // No embedded colour anywhere in the markup (§3.12, and `no-palette-token`
      // would fail a hex in the source; this is the rendered half of the same).
      expect(host.innerHTML, id).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
  });

  it("names the icon when it IS a control's only label (§3.12)", () => {
    const host = render(<Icon id="close" label={copy.rail.close} />);
    const svg = host.querySelector("svg");
    expect(svg?.getAttribute("role")).toBe("img");
    expect(svg?.getAttribute("aria-label")).toBe(copy.rail.close);
    expect(svg?.getAttribute("aria-hidden")).toBeNull();
  });

  it("hides an icon from assistive technology unless it is the only label", () => {
    const host = render(<Badge status="pass">{WORD["pass"]}</Badge>);
    const svg = host.querySelector("svg");
    // Icon + word, always both (§3.12's refusal). The word is the label, so the
    // icon is decorative and says so.
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.getAttribute("aria-label")).toBeNull();
  });
});
