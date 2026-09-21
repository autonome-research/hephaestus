// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Viewport appearance (INTERFACE.md §3.11, §5.5) — operator chrome, not
// workspace state.
//
// §3.11 already authors the picture: a material at `--viewport-part` with a
// ≥4.5:1 part-vs-ground floor, a silhouette, a ground grid, and
// an orthographic camera framed like `cameras.py`. This store is the operator
// cluster that *drives* those decisions. It holds no geometry and no server
// value. Four consequences:
//
// * **It is not workspace state.** §4.5's record is closed and carries no
//   appearance field. Putting wireframe or a hidden grid in the URL would widen
//   a closed vocabulary, and a link that silently hid the floor would be a link
//   that showed a different instrument than the one it names. Appearance is
//   therefore session-local, like `state/visibility.ts`, and does not survive a
//   reload.
// * **Defaults are the authored picture.** Wireframe off, ortho on, grid on,
//   material override on. G4.5's control region and §3.11.2's contrast
//   floor are measured against that picture; this store must not move those
//   pixels by existing.
// * **The material is not invented here.** Override on means the one authored
//   `MeshStandardMaterial` at `--viewport-part`. Override off restores the
//   exporter's own material, which is a selection ID, not a colour the operator
//   chose. There is no third material and no catalog.
// * **Bound to the pin, not to a second inspector.** The cluster lives on the
//   viewport that loads `GET /artifacts/{ref}/gltf` for `artifact_ref`. Fit
//   re-applies `cameras.py`'s framing for the current named view. Nothing here
//   writes the pin.

/** The five toggles the cluster exposes. Fit is an action, not a flag. */
export const APPEARANCE_TOGGLES = [
  "wireframe",
  "ortho",
  "grid",
  "materialOverride",
] as const;
export type AppearanceToggle = (typeof APPEARANCE_TOGGLES)[number];

export interface AppearanceState {
  readonly wireframe: boolean;
  readonly ortho: boolean;
  readonly grid: boolean;
  readonly materialOverride: boolean;
}

/** §3.11's authored picture — the only defaults this store may have. */
export const DEFAULT_APPEARANCE: AppearanceState = {
  wireframe: false,
  // PERSPECTIVE BY DEFAULT since 2026-09-20, on operator request.
  //
  // The orthographic default was not arbitrary — `cameras.py` fits an ortho
  // camera per named view, so an ortho canvas and `heph render` agree about
  // the same view pixel for pixel. That agreement is what this flag now
  // trades away BY DEFAULT rather than on request, and the trade is worth
  // naming: the build space is a room, and a room only reads as one under
  // perspective. Walls that converge are the whole depth cue; in an ortho
  // camera fitted to the part they fall outside the frame entirely.
  //
  // What is NOT traded: the eye direction is still the framing's, so a named
  // view still looks from where the server says it looks, and the toggle
  // restores the exact `heph render` projection in one click.
  ortho: false,
  grid: true,
  materialOverride: true,
};

type Listener = () => void;

function sameAppearance(a: AppearanceState, b: AppearanceState): boolean {
  return (
    a.wireframe === b.wireframe &&
    a.ortho === b.ortho &&
    a.grid === b.grid &&
    a.materialOverride === b.materialOverride
  );
}

/**
 * The appearance record, as an external store for `useSyncExternalStore`.
 *
 * The snapshot is the record itself and it is replaced (never mutated) on every
 * write, so identity comparison is a correct change test.
 */
export class AppearanceStore {
  #state: AppearanceState;
  readonly #listeners = new Set<Listener>();

  constructor(initial: AppearanceState = DEFAULT_APPEARANCE) {
    this.#state = initial;
  }

  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getSnapshot = (): AppearanceState => this.#state;

  /** Flip one flag. Returns nothing: the store is the authority, not the caller. */
  toggle(field: AppearanceToggle): void {
    this.#commit({ ...this.#state, [field]: !this.#state[field] });
  }

  /** Test seam: put the store back to the authored picture. */
  reset(): void {
    this.#commit(DEFAULT_APPEARANCE);
  }

  #commit(next: AppearanceState): void {
    if (sameAppearance(this.#state, next)) return;
    this.#state = next;
    for (const listener of this.#listeners) listener();
  }
}

/** The process-wide store. One workspace, one viewport. */
export const appearanceStore = new AppearanceStore();
