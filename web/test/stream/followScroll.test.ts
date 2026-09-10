// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindReadingPosition, FOLLOW_BOTTOM_PX, readingPosition, scrolledAwayFromBottom, sessionReading } from "../../src/stream/followScroll";

afterEach(() => { sessionReading.clear(); vi.unstubAllGlobals(); document.body.replaceChildren(); });
describe("session reading continuity", () => {
  it("follows at the bottom with bounded slack", () => {
    const box = { scrollTop: 400 - FOLLOW_BOTTOM_PX, scrollHeight: 800, clientHeight: 400 };
    expect(scrolledAwayFromBottom(box)).toBe(false);
    expect(scrolledAwayFromBottom({ ...box, scrollTop: box.scrollTop - 1 })).toBe(true);
  });
  it("defaults only unseen sessions to following; retains independent anchors", () => {
    Object.assign(readingPosition("long"), { following: false, anchor: "call:1", offset: -18, top: 950 });
    expect(readingPosition("short").following).toBe(true);
    expect(readingPosition("long")).toEqual({ following: false, anchor: "call:1", offset: -18, top: 950 });
  });
  it("follows height growth without new rows and restores a detached content anchor", () => {
    let resize: () => void = () => {};
    vi.stubGlobal("ResizeObserver", class {
      constructor(cb: () => void) { resize = cb; }
      observe() {} disconnect() {}
    });
    const el = document.createElement("div");
    const row = document.createElement("li");
    row.dataset["rowKey"] = "stable";
    el.append(row); document.body.append(el);
    let height = 1000, top = 0, rowTop = 400;
    Object.defineProperties(el, {
      clientHeight: { get: () => 200 }, scrollHeight: { get: () => height },
      scrollTop: { get: () => top, set: (value: number) => { top = Math.max(0, Math.min(height - 200, value)); } },
    });
    row.getBoundingClientRect = () => ({ top: rowTop - top, height: 900 } as DOMRect);
    const position = readingPosition("long");
    const binding = bindReadingPosition(el, position, () => {});
    expect(top).toBe(800);
    height = 1400; resize(); expect(top).toBe(1200);
    el.scrollTop = 450; el.dispatchEvent(new Event("scroll"));
    expect(position.following).toBe(false); expect(position.offset).toBe(-50);
    rowTop = 600; height = 1600; resize(); expect(top).toBe(650);
    el.dispatchEvent(new Event("scroll")); // programmatic restoration does not re-own anchor
    expect(position.offset).toBe(-50);
    binding.close();
    el.scrollTop = 0;
    const returned = bindReadingPosition(el, position, () => {});
    expect(top).toBe(650);
    returned.close();
  });
});
