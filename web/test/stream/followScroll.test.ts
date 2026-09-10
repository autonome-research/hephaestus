// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Follow newest while at the bottom; stop the moment the operator scrolls up
// (#98). Opening a session and the jump control always pin.

import { describe, expect, it } from "vitest";
import {
  FOLLOW_BOTTOM_PX,
  readFollowMove,
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

describe("reading one scroll event (content growth is not an operator scroll)", () => {
  const pinned = box({ scrollTop: 400 });

  it("holds while pinned and following", () => {
    expect(readFollowMove(400, true, pinned)).toBe("hold");
  });

  it("re-pins when the content grew but the viewport did not move up", () => {
    // 500px of new content under a viewport left exactly where it was: this is
    // an image decoding, not a hand on the wheel.
    const grown = box({ scrollTop: 400, scrollHeight: 1300 });
    expect(readFollowMove(400, true, grown)).toBe("repin");
  });

  it("unfollows only when the viewport itself moved up", () => {
    const moved = box({ scrollTop: 100 });
    expect(readFollowMove(400, true, moved)).toBe("unfollow");
    // A nudge INSIDE the slack is still the operator's, and is judged against
    // the last position seen rather than against the end.
    const nudged = box({ scrollTop: 380, scrollHeight: 1300 });
    expect(readFollowMove(400, true, nudged)).toBe("unfollow");
  });

  it("re-follows when the operator returns to the newest row", () => {
    expect(readFollowMove(0, false, pinned)).toBe("follow");
  });

  it("never yanks a detached reader, however much content arrives", () => {
    const grown = box({ scrollTop: 0, scrollHeight: 4000 });
    expect(readFollowMove(0, false, grown)).toBe("hold");
  });
});
