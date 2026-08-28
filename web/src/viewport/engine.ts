// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The three.js renderer, camera and controls (INTERFACE.md §5).
//
// A plain class rather than a hook or a component: the renderer owns a GPU
// context and a scene graph whose lifetime is the canvas's, not a render pass's,
// and React's job here is to *drive* it — one effect per workspace field — not to
// own it. `Viewport.tsx` is the driver and holds no three.js state of its own.
//
// FOUR DECISIONS WORTH THE READING:
//
// * **Orthographic, framed like the server.** `cameras.py::camera_framing` fits
//   an orthographic camera per view; a perspective viewport would put the
//   browser and `heph render` in visible disagreement about the same named view
//   for no gain in a CAD instrument. `scene.ts::framingFor` mirrors that
//   construction and this class applies it.
// * **On-demand rendering, and a *synchronous* frame after a programmatic
//   change.** There is no animation loop: a frame is drawn when something
//   changed. A change the app made (a toggle, a slider tick, a view) draws
//   immediately rather than on the next rAF, so a harness that screenshots right
//   after a click sees the frame that click produced — G4.5's before/after delta
//   would otherwise be a race against the compositor. A user drag coalesces
//   through rAF, because sixty synchronous frames a second is what a loop is for.
// * **`preserveDrawingBuffer`.** Chromium may clear a WebGL back buffer after
//   compositing; a screenshot taken afterwards can come back blank. G4.5 reads
//   viewport pixels, so the buffer is preserved. It costs a copy per frame and
//   buys a deterministic screenshot.
// * **The GLB's own materials are kept.** They carry the server's per-solid
//   palette colour, and §5.4 describes the viewport as exactly that: "lit and
//   antialiased", the thing a mask is *not* decoded from. Lighting and AA are
//   what make it undecodable, and replacing the colours would only make the
//   picture less like the render the same build produces elsewhere.

import {
  AmbientLight,
  Color,
  DirectionalLight,
  Group,
  OrthographicCamera,
  Plane,
  Scene,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import type { Box3 } from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { nameForDirection } from "./cameras";
import type { GlbGeometry } from "./glb";
import {
  applyClipping,
  applyExplode,
  applyFraming,
  applyVisibility,
  boundsAt,
  framingFor,
  indexSolidNodes,
  type Framing,
  type SolidIndex,
} from "./scene";
import { clippingHalfSpace, type SectionPlaneSpec } from "./section";

/** The page did not grant a WebGL context; there is no substitute and none is faked. */
export class NoWebglError extends Error {
  constructor(cause: string) {
    super(cause);
    this.name = "NoWebglError";
  }
}

/** Instrument ground, matching `--ground-0`; the geometry is the bright thing. */
const BACKGROUND = new Color("#0d0f12");

export interface ViewportEngineOptions {
  /** Called when a free orbit settles, with the nearest nameable camera (§5.5). */
  readonly onCameraSettled: (viewName: string) => void;
}

export class ViewportEngine {
  readonly canvas: HTMLCanvasElement;
  private readonly renderer: WebGLRenderer;
  private readonly scene: Scene;
  private readonly camera: OrthographicCamera;
  private readonly controls: OrbitControls;
  private readonly root = new Group();
  private readonly options: ViewportEngineOptions;

  private index: SolidIndex | null = null;
  /** The plain scene bbox — the `rgb`/`mask`/`section` framing (`_framing`). */
  private bounds: Box3 | null = null;
  /** The `t = 1` extent — the `explode` channel's framing. */
  private explodedBounds: Box3 | null = null;
  private framing: Framing | null = null;
  private frameRequest = 0;
  private disposed = false;

  constructor(canvas: HTMLCanvasElement, options: ViewportEngineOptions) {
    this.canvas = canvas;
    this.options = options;
    try {
      this.renderer = new WebGLRenderer({
        canvas,
        antialias: true,
        preserveDrawingBuffer: true,
        alpha: false,
      });
    } catch (error) {
      throw new NoWebglError(String(error));
    }
    this.renderer.setClearColor(BACKGROUND, 1);
    this.renderer.localClippingEnabled = true;

    this.scene = new Scene();
    this.scene.background = BACKGROUND;
    this.scene.add(this.root);

    this.camera = new OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
    // Z-up, matching `cameras.py`'s frame. three.js defaults to Y-up, and a
    // viewport in the other convention would show every named view rotated.
    this.camera.up.set(0, 0, 1);

    // Lights ride with the camera so shading does not change meaning when the
    // view does: the picture is an instrument reading, not a beauty render.
    const key = new DirectionalLight(0xffffff, 2.2);
    key.position.set(1, 1.5, 2);
    const fill = new DirectionalLight(0xffffff, 0.8);
    fill.position.set(-1.5, -1, 0.5);
    this.camera.add(key, fill);
    this.scene.add(this.camera, new AmbientLight(0xffffff, 0.9));

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false;
    this.controls.addEventListener("change", this.requestFrame);
    this.controls.addEventListener("end", this.settleCamera);
  }

  /** Replace the scene's geometry with the meshes of `bytes`. */
  async load(bytes: ArrayBuffer, geometry: GlbGeometry): Promise<SolidIndex> {
    const gltf: GLTF = await new GLTFLoader().parseAsync(bytes, "");
    this.clearRoot();
    this.root.add(gltf.scene);
    this.index = indexSolidNodes(gltf, geometry);
    this.bounds = boundsAt(this.index, 0);
    this.explodedBounds = boundsAt(this.index, 1);
    return this.index;
  }

  /** Drop the loaded geometry, leaving an empty lit scene. */
  clear(): void {
    this.clearRoot();
    this.index = null;
    this.bounds = null;
    this.explodedBounds = null;
    this.framing = null;
    this.render();
  }

  solidIndex(): SolidIndex | null {
    return this.index;
  }

  /**
   * The **plain** scene bbox as plain numbers, or `null` before a load.
   *
   * The section control needs it to seat its offset, and it must be the *plain*
   * bbox rather than the exploded extent: `parse_section_plane` resolves the `c`
   * keyword against `scene.bbox_min` / `scene.bbox_max` (`channels.py`:479-481), and §4.5's URL
   * carries a **number**, so the midpoint has to be resolved — against the same
   * box the server would have used — before it becomes workspace state. A
   * bounding box is camera-framing material, the screen-space class §1 hands the
   * client, and nothing renders it as a fact.
   */
  boundsBox(): { min: [number, number, number]; max: [number, number, number] } | null {
    const bounds = this.bounds;
    if (bounds === null || bounds.isEmpty()) return null;
    return {
      min: [bounds.min.x, bounds.min.y, bounds.min.z],
      max: [bounds.max.x, bounds.max.y, bounds.max.z],
    };
  }

  /**
   * Frame the camera for `view`, to the extent the server frames the matching
   * channel to (`scene.ts::boundsAt`).
   *
   * §5.2: framed **once** and held. This is called on a load, a view change, and
   * when explode engages or disengages — never between two non-zero `t` values,
   * so no drag re-fits the camera.
   */
  frame(view: string, exploded: boolean): void {
    const bounds = exploded ? this.explodedBounds : this.bounds;
    if (bounds === null || bounds.isEmpty()) return;
    const framing = framingFor(bounds, view, this.aspect());
    if (framing === null) return;
    this.framing = framing;
    applyFraming(this.camera, framing);
    this.camera.zoom = 1;
    this.camera.updateProjectionMatrix();
    this.controls.target.set(framing.target[0], framing.target[1], framing.target[2]);
    this.controls.update();
    this.render();
  }

  setExplode(t: number): void {
    if (this.index === null) return;
    applyExplode(this.index, t);
    this.render();
  }

  setHidden(hidden: ReadonlySet<string>): void {
    if (this.index === null) return;
    applyVisibility(this.index, hidden);
    this.render();
  }

  /** §5.3's live preview: `null` clears every clipping plane. */
  setSection(plane: SectionPlaneSpec | null): void {
    if (plane === null) {
      applyClipping(this.root, []);
    } else {
      const half = clippingHalfSpace(plane);
      const normal = new Vector3(half.normal[0], half.normal[1], half.normal[2]);
      applyClipping(this.root, [new Plane(normal, half.constant)]);
    }
    this.render();
  }

  /** Fit the drawing buffer to `width × height` CSS pixels and re-fit the aspect. */
  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(width, height, false);
    const framing = this.framing;
    if (framing !== null) {
      // Keep the vertical extent and re-fit the horizontal one, so a resize
      // changes how much is visible and never how large a millimetre is.
      const halfWidth = framing.halfHeight * this.aspect();
      this.camera.left = -halfWidth;
      this.camera.right = halfWidth;
      this.camera.updateProjectionMatrix();
    }
    this.render();
  }

  /** The camera's current half-height in model units — the grid readout's scale. */
  scale(): number {
    return this.camera.top / this.camera.zoom;
  }

  /** Draw one frame now. Synchronous on purpose; see the header. */
  render(): void {
    if (this.disposed) return;
    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.disposed = true;
    if (this.frameRequest !== 0) cancelAnimationFrame(this.frameRequest);
    this.controls.removeEventListener("change", this.requestFrame);
    this.controls.removeEventListener("end", this.settleCamera);
    this.controls.dispose();
    this.clearRoot();
    this.renderer.dispose();
  }

  private aspect(): number {
    const size = this.renderer.getSize(new Vector2());
    return size.y > 0 ? size.x / size.y : 1;
  }

  private clearRoot(): void {
    for (const child of [...this.root.children]) this.root.remove(child);
  }

  /** A user drag: coalesce to one frame per animation frame. */
  private readonly requestFrame = (): void => {
    if (this.disposed || this.frameRequest !== 0) return;
    this.frameRequest = requestAnimationFrame(() => {
      this.frameRequest = 0;
      this.render();
    });
  };

  /**
   * §5.5: "free orbit snapshots the nearest `az/el` into workspace state,
   * keeping every reachable camera nameable."
   */
  private readonly settleCamera = (): void => {
    const direction = this.camera.position.clone().sub(this.controls.target);
    if (direction.lengthSq() === 0) return;
    direction.normalize();
    this.options.onCameraSettled(nameForDirection([direction.x, direction.y, direction.z]));
  };
}
