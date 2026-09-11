// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The hook, not its predicates: what `useFollowScroll` does with the scroll
// events a real transcript produces.
//
// `followScroll.test.ts` covers the scroll predicates and persisted reading
// anchors as functions. Neither alone could catch the defect these clauses pin,
// because the defect is in what the hook TREATS as the operator
// scrolling: a transcript whose content grows under a pinned viewport fires
// scroll events too, and the browser's own scroll anchoring fires them while
// the operator's hands are nowhere near the wheel.

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { act, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { sessionReading, useFollowScroll } from "../../src/stream/followScroll";

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(() => {
  sessionReading.clear();
  document.body.replaceChildren();
});

/** A scroller whose metrics a test can drive; jsdom performs no layout. */
class FakeScroller {
  readonly el: HTMLDivElement;
  scrollHeight = 1000;
  clientHeight = 400;
  #scrollTop = 0;

  constructor() {
    this.el = document.createElement("div");
    Object.defineProperty(this.el, "scrollHeight", { get: () => this.scrollHeight });
    Object.defineProperty(this.el, "clientHeight", { get: () => this.clientHeight });
    Object.defineProperty(this.el, "scrollTop", {
      get: () => this.#scrollTop,
      // A real scroller clamps, and the clamp is load-bearing: `pinToLatest`
      // assigns `scrollHeight`, which lands at `scrollHeight - clientHeight`.
      set: (next: number) => {
        this.#scrollTop = Math.max(0, Math.min(next, this.scrollHeight - this.clientHeight));
      },
    });
  }

  get top(): number {
    return this.#scrollTop;
  }

  /** Content grew (an image decoded, a font swapped) — no operator input. */
  grow(px: number): void {
    this.scrollHeight += px;
    this.el.dispatchEvent(new Event("scroll"));
  }

  /** The operator moved the viewport. */
  scrollTo(top: number): void {
    this.el.scrollTop = top;
    this.el.dispatchEvent(new Event("scroll"));
  }
}

interface Probe {
  following: boolean;
  jump: () => void;
}

function mount(scroller: FakeScroller): { root: Root; probe: Probe } {
  const probe: Probe = { following: true, jump: () => {} };
  function Harness(): null {
    const ref = useRef<HTMLElement | null>(scroller.el);
    const { following, jumpToLatest } = useFollowScroll(ref, "s1", true);
    probe.following = following;
    probe.jump = jumpToLatest;
    return null;
  }
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(<Harness />);
  });
  return { root, probe };
}

describe("useFollowScroll against the events a live transcript fires", () => {
  it("keeps following when the CONTENT grows under a pinned viewport", () => {
    const scroller = new FakeScroller();
    const { root, probe } = mount(scroller);
    try {
      expect(probe.following).toBe(true);
      expect(scroller.top).toBe(scroller.scrollHeight - scroller.clientHeight);

      // A chip-dense transcript settles after its first paint: images decode,
      // fonts swap, rows re-measure. The row COUNT never changes, so the hook's
      // effect does not re-run — and the growth alone fires a scroll event.
      act(() => {
        scroller.grow(500);
      });

      expect(probe.following, "content growth is not the operator scrolling up").toBe(true);
      // …and the viewport stayed at the newest row rather than drifting up it.
      expect(scroller.top).toBe(scroller.scrollHeight - scroller.clientHeight);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it("detaches when the operator actually scrolls up, and reattaches at the end", () => {
    const scroller = new FakeScroller();
    const { root, probe } = mount(scroller);
    try {
      act(() => {
        scroller.scrollTo(0);
      });
      expect(probe.following).toBe(false);

      act(() => {
        scroller.scrollTo(scroller.scrollHeight);
      });
      expect(probe.following, "returning to the newest row reattaches").toBe(true);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it("leaves a detached viewport alone while content grows", () => {
    const scroller = new FakeScroller();
    const { root, probe } = mount(scroller);
    try {
      act(() => {
        scroller.scrollTo(0);
      });
      expect(probe.following).toBe(false);
      const parked = scroller.top;

      act(() => {
        scroller.grow(500);
      });

      expect(probe.following).toBe(false);
      expect(scroller.top, "a detached reader is never yanked to the end").toBe(parked);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it("the jump control re-attaches and pins", () => {
    const scroller = new FakeScroller();
    const { root, probe } = mount(scroller);
    try {
      act(() => {
        scroller.scrollTo(0);
      });
      expect(probe.following).toBe(false);
      act(() => {
        probe.jump();
      });
      expect(probe.following).toBe(true);
      expect(scroller.top).toBe(scroller.scrollHeight - scroller.clientHeight);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });
});
