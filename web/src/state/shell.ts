// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Shell layout state (INTERFACE.md §4.1's 2026-08-28 amendment, (a) and (c)).
//
// WHAT THIS HOLDS AND WHY IT IS NOT IN §4.5's RECORD — read this before adding
// a field. §4.1(a) says `useBreakpoint.ts` "writes `streamOpen` / `railOverlay`
// into workspace state", and §4.1(c) says the drag handle writes
// `--drawer-height` "into workspace state". §4.5's record is **closed** ("Every
// field is here; nothing else is workspace state") and is **URL-serialized**.
// Three fields that describe the viewport's width and a drawer's pixel height
// are not addressable state: a link carrying `railOverlay=true` would reopen on
// a machine whose window is a different size and immediately contradict itself.
//
// So they live in a store of their own, on the precedent `state/visibility.ts`
// already set for §5.4's toggles — client state, one authority, deliberately not
// in the URL. **This is a DEVIATION from §4.1(a)/(c)'s wording and it is
// recorded, not hidden**: the substantive requirement of both clauses — that
// there be exactly ONE authority and that CSS not decide the layout behind
// React's back — is met in full, and the §4.5 closure is left intact. Whoever
// owns §4.1 should reconcile the two sentences.
//
// THE DEFECT (a) NAMES, MEASURED. `Shell.module.css` collapsed the stream column
// to 44px by media query while `Shell.tsx`'s `useState(true)` decided whether the
// panel rendered its contents. Between 1024 and 1279px they disagreed, and
// `StreamPanel` shredded into a one-word-per-line ribbon with the body
// overflowing horizontally:
//
//   width  grid-template-columns          stream box  scrollWidth  overflows
//   1440   280px 740px 420px              420         419          no
//   1280   280px 580px 420px              420         419          no
//   1279   280px 955px 44px               44          81           YES
//   1024   280px 700px 44px               44          81           YES
//
// 1280×800 is the default MacBook Air logical resolution and any half-screen
// split on a 2560px monitor lands inside the broken band. This is not an edge
// case, and the fix is that `Shell.module.css` now keeps **no** media query that
// changes `grid-template-columns`: the grid is driven by `data-stream` and
// `data-rail`, which React sets from this store.
//
// THE DEFECT (b) NAMES. `grep -rn 'data-rail' web/src` returned exactly one hit
// — the CSS rule that *consumed* it. Nothing set it, so below 1024px the rail
// was a 280px absolutely-positioned overlay covering a third of the stage with
// no scrim, no close control, and **no dismissal at all**.

/** §4.1's two thresholds, as numbers. `tokens.css` carries the same two for CSS. */
export const BREAKPOINT_STREAM = 1280;
export const BREAKPOINT_RAIL = 1024;

/** The three bands §4.1's table measures. A band crossing re-evaluates defaults. */
export const BANDS = ["wide", "medium", "narrow"] as const;
export type Band = (typeof BANDS)[number];

/** Which band a viewport width is in. Pure, so a test needs no window. */
export function bandFor(width: number): Band {
  if (width < BREAKPOINT_RAIL) return "narrow";
  if (width < BREAKPOINT_STREAM) return "medium";
  return "wide";
}

export interface ShellState {
  readonly band: Band;
  readonly viewportWidth: number;
  /** Preferred expanded width; survives collapse and temporary viewport clamps, never serialized. */
  readonly streamWidth: number | null;
  /** Whether the Stream renders its contents. `false` ⇒ the 44px strip. */
  readonly streamOpen: boolean;
  /** Whether the Rail is an overlay over the Stage rather than a column. */
  readonly railOverlay: boolean;
  /** While `railOverlay`, whether the overlay is up. Always true otherwise. */
  readonly railOpen: boolean;
  /** §4.1(c)'s explicit drawer height in px, or `null` for the token default. */
  readonly drawerHeight: number | null;
}

export const DEFAULT_SHELL: ShellState = {
  band: "wide",
  viewportWidth: 1440,
  streamWidth: null,
  streamOpen: true,
  railOverlay: false,
  railOpen: true,
  drawerHeight: null,
};

/** §4.1(c): the drawer's band. The token default is `clamp(200px, 32vh, 420px)`. */
export const DRAWER_MIN = 200;
export const DRAWER_MAX = 420;

export const STREAM_MIN = 360;
export const STREAM_MAX = 640;
export const STAGE_MIN = 360;
export const RAIL_WIDTH = 280;

/** Current pixel budget. On exceptionally small screens, never overflow the document. */
export function streamSizing(state: ShellState): { min: number; max: number; width: number } {
  const usable = Math.max(0, state.viewportWidth - (state.railOverlay ? 0 : RAIL_WIDTH));
  const min = Math.min(STREAM_MIN, usable);
  const max = Math.max(min, Math.min(STREAM_MAX, usable - STAGE_MIN));
  const preferred = state.streamWidth ?? Math.max(STREAM_MIN, Math.min(420, state.viewportWidth * 0.3));
  return { min, max, width: Math.round(Math.max(min, Math.min(max, preferred))) };
}

type Listener = () => void;

export class ShellStore {
  #state: ShellState = DEFAULT_SHELL;
  /**
   * Whether the operator has collapsed or expanded the Stream **by hand** in
   * the current band.
   *
   * §4.1(a): "A user's explicit collapse survives a resize inside a band and is
   * re-evaluated on a band crossing." This flag is what makes the two halves of
   * that sentence both true, and it is cleared by `applyWidth` on a crossing.
   */
  #streamHeld = false;
  readonly #listeners = new Set<Listener>();

  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getSnapshot = (): ShellState => this.#state;

  /**
   * The **sole** entry point for a viewport width. `useBreakpoint` calls it and
   * nothing else does; no CSS media query duplicates the decision.
   */
  applyWidth(width: number): void {
    if (!Number.isFinite(width) || width < 0) return;
    width = Math.floor(width);
    const band = bandFor(width);
    const previous = this.#state;
    if (band === previous.band) {
      // Re-clamp even within a band without changing explicit open/closed state.
      if (width !== previous.viewportWidth) this.#commit({ ...previous, viewportWidth: width });
      return;
    }
    this.#streamHeld = false;
    this.#commit({
      ...previous,
      band,
      viewportWidth: width,
      // §4.1: below 1280px the Stream collapses to a docked strip; below 1024px
      // the Rail collapses to an overlay, and an overlay opens closed.
      streamOpen: band === "wide",
      railOverlay: band === "narrow",
      railOpen: band !== "narrow",
      drawerHeight: previous.drawerHeight,
    });
  }

  /**
   * An explicit collapse or expand.
   *
   * §4.1(a): "The Stream strip is a control, not a narrower panel (§7A.1):
   * focusing or activating it expands the column, because a composer cannot live
   * in 44px." The strip's only affordance calls this with `true`.
   */
  setStreamOpen(open: boolean): void {
    this.#streamHeld = true;
    if (this.#state.streamOpen === open) return;
    this.#commit({ ...this.#state, streamOpen: open });
  }

  /** Explicit resizing stores the achievable width, not an offscreen drag overshoot. */
  setStreamWidth(width: number | null): void {
    if (width !== null && !Number.isFinite(width)) return;
    const { min, max } = streamSizing(this.#state);
    const next = width === null ? null : Math.round(Math.max(min, Math.min(max, width)));
    if (next === this.#state.streamWidth) return;
    this.#commit({ ...this.#state, streamWidth: next });
  }

  /** Whether the current stream state is the operator's rather than the band's. */
  streamHeld(): boolean {
    return this.#streamHeld;
  }

  /** Open or dismiss the rail overlay. A no-op while the rail is a column. */
  setRailOpen(open: boolean): void {
    if (!this.#state.railOverlay) return;
    if (this.#state.railOpen === open) return;
    this.#commit({ ...this.#state, railOpen: open });
  }

  /** §4.1(c)'s drag handle. Clamped to the same band the token default clamps to. */
  setDrawerHeight(height: number | null): void {
    const next =
      height === null ? null : Math.round(Math.min(DRAWER_MAX, Math.max(DRAWER_MIN, height)));
    if (this.#state.drawerHeight === next) return;
    this.#commit({ ...this.#state, drawerHeight: next });
  }

  /** Test seam. */
  reset(): void {
    this.#streamHeld = false;
    this.#commit(DEFAULT_SHELL);
  }

  #commit(next: ShellState): void {
    this.#state = next;
    for (const listener of this.#listeners) listener();
  }
}

/** The process-wide store. One shell, one authority for its bands. */
export const shellStore = new ShellStore();
