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

/**
 * The readouts that expand IN THE SIDE PANEL rather than taking the stage
 * (2026-09-20).
 *
 * ALL FOUR are disclosures, in one order, with one shape (2026-09-20). The rail
 * used to be two kinds of thing stacked: two collapsible readouts, then three
 * always-open panels with their own headings. One shape means the operator
 * learns the row once.
 *
 * The order runs from the artifact outward: what this build MEASURES
 * (Geometry), how it was BUILT (Timeline), what the project CONTAINS (Parts),
 * and what git says about it (Working tree).
 *
 * `results` and `timeline` are also `stage_tab` ids, and the stage still
 * renders whichever a URL names — `?tab=timeline` from before this change still
 * opens the full-stage timeline. What moved is where a CLICK puts them.
 */
export const PANEL_SECTIONS = ["results", "timeline", "parts", "working_tree"] as const;
export type PanelSection = (typeof PANEL_SECTIONS)[number];

export interface ShellState {
  readonly band: Band;
  readonly viewportWidth: number;
  /** Preferred width; survives temporary viewport clamps, never serialized. */
  readonly streamWidth: number | null;
  /**
   * Whether the Agent column is drawn (2026-09-20, second pass).
   *
   * The collapse was struck earlier the same day and is back by request, in a
   * different shape: the control is the Views bar's chat toggle, which is
   * ALWAYS VISIBLE, rather than a chevron inside the column plus a docked
   * return strip to come back through. One control, both directions, and it
   * cannot disappear with the thing it toggles.
   *
   * The panel stays MOUNTED when closed — the track goes to zero and the
   * column is `display: none`. A draft, a scroll position and an unsent
   * envelope therefore survive a close without the store having to re-hydrate
   * them, which is what the old hide/reveal round-trip existed to prove.
   */
  readonly streamOpen: boolean;
  /**
   * Which side-panel readouts are expanded. Several at once, like the rail's
   * other sections — an accordion would close the thing you were reading to
   * show the thing you just asked for.
   */
  readonly panelOpen: readonly PanelSection[];
  /** Whether the Rail is an overlay over the Stage rather than a column. */
  readonly railOverlay: boolean;
  /** While `railOverlay`, whether the overlay is up. Always true otherwise. */
  readonly railOpen: boolean;
  /** §4.1(c)'s explicit drawer height in px, or `null` for the token default. */
  readonly drawerHeight: number | null;
  /**
   * Whether the inspector drawer's BODY is drawn (2026-09-20).
   *
   * The tab strip never leaves — collapsing to nothing would take the control
   * that reopens it, and a drawer you cannot find is worse than a drawer in
   * the way. Closed, the strip stays on the stage's bottom edge and the
   * canvas takes the height the body gave up; opening extends the body back
   * up into the canvas, which is the direction the operator asked for.
   */
  readonly drawerOpen: boolean;
}

export const DEFAULT_SHELL: ShellState = {
  band: "wide",
  viewportWidth: 1440,
  streamWidth: null,
  streamOpen: true,
  panelOpen: ["parts"],
  railOverlay: false,
  railOpen: true,
  drawerHeight: null,
  drawerOpen: true,
};

/** §4.1(c): the drawer's band. The token default is `clamp(200px, 32vh, 420px)`. */
export const DRAWER_MIN = 200;
export const DRAWER_MAX = 420;

/**
 * The Views bar's width.
 *
 * ONE WIDTH since 2026-09-20: the bar has no expanded state to toggle into.
 * 44px clears §3.13.6's 24px hit area with room to spare, and the grid template
 * therefore never changes shape — the stage does not re-fit its camera because
 * of anything this column does (§3.3 principle 4: furniture does not move).
 */
export const VIEWS_RAIL_WIDTH = 44;

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
      //
      // LEAVING overlay for a column opens it once — the operator did not
      // choose "closed", the narrow capacity did. A close chosen while the rail
      // was already a column is explicit and survives every width inside that
      // capacity, because only the overlay transition rewrites it (2026-09-20,
      // when the Views bar's Parts entry made closing a column possible at all).
      railOpen: railOverlay
        ? previous.railOverlay && previous.railOpen
        : previous.railOverlay || previous.railOpen,
    });
  }

  /** Explicit resizing stores the achievable width, not an offscreen drag overshoot. */
  setStreamWidth(width: number | null): void {
    if (width !== null && !Number.isFinite(width)) return;
    const { min, max } = streamSizing(this.#state);
    const next = width === null ? null : Math.round(Math.max(min, Math.min(max, width)));
    if (next === this.#state.streamWidth) return;
    this.#commit({ ...this.#state, streamWidth: next });
  }

  /** The Views bar's chat toggle. Presentation only; no session is touched. */
  setStreamOpen(open: boolean): void {
    if (this.#state.streamOpen === open) return;
    this.#commit({ ...this.#state, streamOpen: open });
  }

  /**
   * Expand or collapse one side-panel readout, opening Parts if it is closed —
   * a section cannot expand inside a column that is not drawn, and a click that
   * appears to do nothing is worse than one that does too much.
   */
  togglePanelSection(section: PanelSection): void {
    const open = this.#state.panelOpen.includes(section);
    const panelOpen = open
      ? this.#state.panelOpen.filter((name) => name !== section)
      : [...this.#state.panelOpen, section];
    this.#commit({ ...this.#state, panelOpen, railOpen: open ? this.#state.railOpen : true });
  }

  /**
   * Open or dismiss Parts — the overlay below 1280px, the COLUMN above it.
   *
   * The column case is new (2026-09-20): the Views bar's Parts entry is the
   * control, so a wide viewport can close Parts and give the width to the
   * stage. The overlay guard that used to make this a no-op above 1280px is
   * struck; the two capacities share one field because they are one question —
   * "is Parts showing" — and two fields would need a rule for disagreeing.
   */
  setRailOpen(open: boolean): void {
    if (this.#state.railOpen === open) return;
    this.#commit({ ...this.#state, railOpen: open });
  }

  /** §4.1(c)'s drag handle. Clamped to the same band the token default clamps to. */
  /** Fold the drawer's body away, or bring it back. The strip always stays. */
  setDrawerOpen(open: boolean): void {
    if (this.#state.drawerOpen === open) return;
    this.#commit({ ...this.#state, drawerOpen: open });
  }

  toggleDrawer(): void {
    this.setDrawerOpen(!this.#state.drawerOpen);
  }

  setDrawerHeight(height: number | null): void {
    const next =
      height === null ? null : Math.round(Math.min(DRAWER_MAX, Math.max(DRAWER_MIN, height)));
    if (this.#state.drawerHeight === next) return;
    this.#commit({ ...this.#state, drawerHeight: next });
  }

  /** Test seam. */
  reset(): void {
    this.#commit(DEFAULT_SHELL);
  }

  #commit(next: ShellState): void {
    this.#state = next;
    for (const listener of this.#listeners) listener();
  }
}

/** The process-wide store. One shell, one authority for its bands. */
export const shellStore = new ShellStore();
