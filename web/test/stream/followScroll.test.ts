// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Follow newest while at the bottom; stop the moment the operator scrolls up
// (#98). Opening a session and the jump control always pin.

import { describe, expect, it } from "vitest";
import {
  FOLLOW_BOTTOM_PX,
  scrolledAwayFromBottom,
  shouldStickToLatest,
} from "../../src/stream/followScroll";

function box(
  over: Partial<{ scrollTop: number; scrollHeight: number; clientHeight: number }> = {},
): { scrollTop: number; scrollHeight: number; clientHeight: number } {
  return { scrollTop: 400, scrollHeight: 800, clientHeight: 400, ...over };
}

describe("follow vs detach (#98)", () => {
  it("stays attached at the newest row, including a small slack", () => {
    expect(scrolledAwayFromBottom(box({ scrollTop: 400 }))).toBe(false);
    expect(scrolledAwayFromBottom(box({ scrollTop: 400 - FOLLOW_BOTTOM_PX }))).toBe(false);
  });

  it("detaches the moment the operator scrolls up", () => {
    expect(scrolledAwayFromBottom(box({ scrollTop: 400 - FOLLOW_BOTTOM_PX - 1 }))).toBe(true);
    expect(scrolledAwayFromBottom(box({ scrollTop: 0 }))).toBe(true);
  });

  it("pins new rows only while following; open and jump always pin", () => {
    expect(shouldStickToLatest(true, "rows")).toBe(true);
    expect(shouldStickToLatest(false, "rows")).toBe(false);
    expect(shouldStickToLatest(false, "open")).toBe(true);
    expect(shouldStickToLatest(false, "jump")).toBe(true);
  });
});
