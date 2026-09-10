// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Shell layout capacity and explicit panel intent (INTERFACE.md §4.1).
//
// Client presentation is not §4.5's addressable URL record. This store owns
// explicit panel intent and preferred dimensions; useBreakpoint supplies only
// capacity. CSS consumes data-stream/data-rail, never a competing grid media
// query. Session/model/draft/attempt/reading/task state has independent owners.

/** Capacity thresholds; neither automatically hides the conversation. */
export const BREAKPOINT_STREAM = 1280;
export const BREAKPOINT_RAIL = 1280;
export const BREAKPOINT_NARROW = 1024;

/** Capacity bands never reset explicit conversation intent. */
export const BANDS = ["wide", "medium", "narrow"] as const;
export type Band = (typeof BANDS)[number];

/** Which band a viewport width is in. Pure, so a test needs no window. */
export function bandFor(width: number): Band {
  if (width < BREAKPOINT_NARROW) return "narrow";
  if (width < BREAKPOINT_STREAM) return "medium";
  return "wide";
}

export interface ShellState {
  readonly band: Band;
  readonly viewportWidth: number;
  /** Preferred expanded width; survives collapse and temporary viewport clamps, never serialized. */
  readonly streamWidth: number | null;
  /** Explicit open intent; false shows a horizontal state-bearing return control. */
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
  /** Whether the operator has explicitly set intent, independent of capacity. */
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
    if (width === previous.viewportWidth) return;
    const railOverlay = width < BREAKPOINT_RAIL;
    this.#commit({
      ...previous,
      band,
      viewportWidth: width,
      railOverlay,
      // Entering overlay capacity never auto-opens Parts. Within that capacity
      // retain explicit overlay intent, including the 1024 band transition.
      railOpen: railOverlay ? previous.railOverlay && previous.railOpen : true,
    });
  }

  /** Explicit Hide/Open (including focus-only Skip); width observations cannot undo it. */
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

  /** Whether conversation intent has been explicitly set. */
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
