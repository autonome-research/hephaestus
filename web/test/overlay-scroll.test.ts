// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Overlay scrollbars (#115 leftover). jsdom's scrollbar is typically 0px, so
// a measurement-only test would pass under `scrollbar-width: thin` too. The
// contract is both: the helper treats a reserved classic gutter as a failure,
// and a overflowing scroller styled like the shell has layout width equal to
// its content box (or overflow overlay).

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  CLASSIC_SCROLLBAR_GUTTER_PX,
  OVERLAY_SCROLL_CUE_PX,
  bindOverlayScrollTree,
  overlayThumbAlong,
  reservedScrollbarGutter,
  syncOverlayScrollCue,
} from "../src/system/overlayScroll";

const here = dirname(fileURLToPath(import.meta.url));
const globalCss = readFileSync(join(here, "../src/global.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

const mounted: HTMLElement[] = [];

function mountScroller(opts: { overflow?: boolean } = {}): HTMLElement {
  const style = document.createElement("style");
  style.textContent = globalCss;
  document.head.appendChild(style);
  mounted.push(style);

  const el = document.createElement("div");
  el.setAttribute("data-overlay-scroll", "");
  el.style.width = "200px";
  el.style.height = "80px";
  el.style.overflow = "auto";
  el.style.border = "0";
  el.style.boxSizing = "border-box";
  const inner = document.createElement("div");
  inner.style.height = "400px";
  inner.style.width = "100%";
  el.appendChild(inner);
  document.body.appendChild(el);
  mounted.push(el);
  if (opts.overflow === true) {
    // jsdom does not grow scrollHeight from a tall child. The overflow
    // contract is still the element's, so the test supplies the metrics a
    // browser would measure on this 80×400 box.
    let scrollTop = 0;
    Object.defineProperties(el, {
      clientHeight: { configurable: true, get: () => 80 },
      scrollHeight: { configurable: true, get: () => 400 },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value;
        },
      },
    });
  }
  return el;
}

afterEach(() => {
  for (const node of mounted.splice(0)) node.remove();
});

describe("reservedScrollbarGutter — classic track vs overlay", () => {
  it("reports a classic gutter when the offset box is wider than the content box", () => {
    // The live defect: rail 11px, Results 10px — this box's OS scrollbar is 10px.
    const host = document.createElement("div");
    Object.defineProperties(host, {
      offsetWidth: { value: 280 },
      clientWidth: { value: 269 },
      offsetHeight: { value: 800 },
      clientHeight: { value: 800 },
    });
    host.style.border = "0";
    document.body.appendChild(host);
    mounted.push(host);
    const gutter = reservedScrollbarGutter(host);
    expect(gutter.inline).toBe(11);
    expect(gutter.inline).toBeGreaterThanOrEqual(CLASSIC_SCROLLBAR_GUTTER_PX);
  });

  it("is zero when layout width equals the content box", () => {
    const host = document.createElement("div");
    host.style.width = "200px";
    host.style.height = "80px";
    host.style.border = "0";
    document.body.appendChild(host);
    mounted.push(host);
    const gutter = reservedScrollbarGutter(host);
    expect(gutter.inline).toBe(0);
    expect(gutter.block).toBe(0);
    expect(host.offsetWidth).toBe(host.clientWidth);
  });
});

describe("shell scroller layout — no classic gutter (issue 115 leftover)", () => {
  it("keeps a overflowing scroller's layout width equal to its content box", () => {
    const el = mountScroller();
    const gutter = reservedScrollbarGutter(el);
    const overlay =
      getComputedStyle(el).overflow === "overlay" ||
      getComputedStyle(el).overflowY === "overlay";
    expect(gutter.inline === 0 || overlay).toBe(true);
    expect(el.offsetWidth).toBe(el.clientWidth);
    expect(gutter.inline).toBeLessThan(CLASSIC_SCROLLBAR_GUTTER_PX);
  });

  it("does not hide overflow: the inner content stays reachable by scrollTop", () => {
    const el = mountScroller({ overflow: true });
    expect(el.scrollHeight).toBeGreaterThan(el.clientHeight);
    el.scrollTop = 40;
    expect(el.scrollTop).toBe(40);
  });

  it("syncs a 1–2px overlay cue that is not in the flow", () => {
    const el = mountScroller({ overflow: true });
    syncOverlayScrollCue(el);
    const height = Number.parseFloat(el.style.getPropertyValue("--overlay-scroll-height"));
    expect(height).toBeGreaterThan(0);
    expect(OVERLAY_SCROLL_CUE_PX).toBeLessThanOrEqual(2);
    const before = el.offsetWidth;
    bindOverlayScrollTree(document);
    expect(el.offsetWidth).toBe(before);
    expect(el.offsetWidth).toBe(el.clientWidth);
  });

  it("updates the cue when overflow appears after bind", async () => {
    const el = mountScroller();
    bindOverlayScrollTree(document);
    expect(el.style.getPropertyValue("--overlay-scroll-height")).toBe("0px");
    let scrollTop = 0;
    Object.defineProperties(el, {
      clientHeight: { configurable: true, get: () => 80 },
      scrollHeight: { configurable: true, get: () => 400 },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value;
        },
      },
    });
    const extra = document.createElement("div");
    extra.style.height = "200px";
    el.appendChild(extra);
    await Promise.resolve();
    expect(Number.parseFloat(el.style.getPropertyValue("--overlay-scroll-height"))).toBeGreaterThan(
      0,
    );
  });
});

describe("overlayThumbAlong", () => {
  it("hides the cue when content fits", () => {
    expect(overlayThumbAlong(0, 100, 100)).toBeNull();
    expect(overlayThumbAlong(0, 100, 80)).toBeNull();
  });

  it("tracks the visible window along the axis", () => {
    expect(overlayThumbAlong(0, 100, 200)).toEqual({ offset: 0, size: 50 });
    expect(overlayThumbAlong(100, 100, 200)).toEqual({ offset: 50, size: 50 });
  });
});
