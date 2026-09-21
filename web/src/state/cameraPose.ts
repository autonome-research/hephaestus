// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The viewport camera's LIVE angles, published for the orientation gizmo.
//
// WHY THIS EXISTS (2026-09-20). The view cube read `workspace.view` — the
// NAMED view — which is written by `onCameraSettled`, i.e. once, when a drag
// ends. So through the whole of an orbit the cube did not move at all, and
// then jumped to whichever name the camera had landed nearest. The operator's
// words: "it rotates as a rectangle, doesn't match user speed, slow and
// janky". All three are the same defect — the gizmo was not animating, it was
// snapping between eight poses.
//
// A camera pose is not workspace state and must not become any: §4.5's record
// is the named view, and writing sixty poses a second into the URL would make
// every orbit a history entry. So this is a plain module store, the same shape
// and for the same reason as the one the appearance flags use — the viewport
// writes it from its frame callback and the gizmo reads it.

/** Where the camera stands, in the same degrees `cameras.ts` speaks. */
export interface CameraPose {
  readonly azimuth_deg: number;
  readonly elevation_deg: number;
}

type Listener = () => void;

class CameraPoseStore {
  /** Iso, so the gizmo has something true to draw before the first frame. */
  #pose: CameraPose = { azimuth_deg: 45, elevation_deg: 35.264389682754654 };
  readonly #listeners = new Set<Listener>();

  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getSnapshot = (): CameraPose => this.#pose;

  /**
   * Publish a pose.
   *
   * The equality guard is load-bearing rather than tidy: this is called from
   * the render loop, and `useSyncExternalStore` re-renders every subscriber
   * on any notification. Without it a still camera would re-render the gizmo
   * sixty times a second forever.
   */
  set(pose: CameraPose): void {
    if (
      Math.abs(pose.azimuth_deg - this.#pose.azimuth_deg) < 1e-4 &&
      Math.abs(pose.elevation_deg - this.#pose.elevation_deg) < 1e-4
    ) {
      return;
    }
    this.#pose = pose;
    for (const listener of this.#listeners) listener();
  }
}

export const cameraPoseStore = new CameraPoseStore();
