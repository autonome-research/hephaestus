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
// * **The client authors the display; the GLB's materials are kept anyway.**
//   §3.11.2 makes the material the client's decision, and `viewport/display.ts`
//   makes it — for the reason its header measures out: the exporter's
//   `baseColorFactor` is `id_to_rgb(solid_id)`, an albedo of zero to three
//   decimal places, not a dark colour choice. This bullet used to say the
//   opposite ("replacing the colours would make the picture less like the
//   render"), and the sentence under it was the reason the part was the dimmest
//   object in frame. What survives from it is the half that was right: the
//   exporter's material is a **selection channel**, so it is preserved on the
//   node rather than discarded, and §5.4's "lit and antialiased" is still the
//   reason a mask is never decoded from this canvas.

import {
  ACESFilmicToneMapping,
  AmbientLight,
  DirectionalLight,
  Group,
  OrthographicCamera,
  Plane,
  SRGBColorSpace,
  Scene,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import type { Box3 } from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { nameForDirection } from "./cameras";
import {
  authorDisplay,
  buildGroundGrid,
  gridStep,
  groundGridSpec,
  readViewportPalette,
  type AuthoredDisplay,
  type GroundGrid,
  type ViewportPalette,
} from "./display";
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
  /**
   * The ground grid (§3.11.5), OUTSIDE `root` on purpose.
   *
   * `clearRoot` empties `root` on every load and `applyClipping` walks `root` to
   * install §5.3's clipping planes. The grid belongs to neither: it is not the
   * artifact, so a reload must not take the floor away for a frame, and a
   * section plane cuts the *part*, not the ruler the part is measured against.
   */
  private readonly gridRoot = new Group();
  private readonly options: ViewportEngineOptions;
  private readonly palette: ViewportPalette;

  private readonly frameListeners = new Set<() => void>();
  private display: AuthoredDisplay | null = null;
  private grid: GroundGrid | null = null;
  private step = 0;
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
    // §3.11.3. `outputColorSpace` is SET EXPLICITLY THOUGH IT IS ALREADY THE
    // DEFAULT, and the distinction matters enough to write down: three@0.185.1
    // defaults it to `SRGBColorSpace` (`three.module.js`:16298), so §3.11.3's
    // claim that its absence produced "the flat desaturated grey" does not hold
    // against this version — `display.ts`'s header measures what actually did.
    // The line stays because the spec names the value and a default is not a
    // decision; if three.js changes its mind, this viewport does not.
    // `toneMapping` genuinely was absent (`:16263` defaults to `NoToneMapping`).
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.palette = readViewportPalette();
    const background = this.palette.ground;
    this.renderer.setClearColor(background, 1);
    this.renderer.localClippingEnabled = true;

    this.scene = new Scene();
    // The clear colour is NOT tone-mapped by three.js, so the ground lands on
    // `--viewport-ground` byte for byte while everything drawn over it goes
    // through ACES. `design-system.spec.ts` asserts that byte equality at a
    // corner pixel, and this is why it can.
    this.scene.background = background;
    this.scene.add(this.root);
    this.scene.add(this.gridRoot);

    this.camera = new OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
    // Z-up, matching `cameras.py`'s frame. three.js defaults to Y-up, and a
    // viewport in the other convention would show every named view rotated.
    this.camera.up.set(0, 0, 1);

    // Lights ride with the camera so shading does not change meaning when the
    // view does: the picture is an instrument reading, not a beauty render.
    //
    // §3.11.7 says these are correct and asks for them "unchanged", and they
    // ARE unchanged — but "unchanged" was written before ACES was in the chain,
    // so the three intensities were checked against it rather than assumed. A
    // facet square to the camera receives `(2.2·0.743 + 0.8·0.266 + 0.9)/π ≈
    // 0.874` of albedo, which for `--viewport-part` is a linear radiance near
    // 0.41-0.54 — the part of the ACES curve with the most slope, so facets
    // separate. Nothing reaches the shoulder, so nothing clips to white, and an
    // ambient-only facet still clears §3.11.2's floor on its own. Raising them
    // for a brighter part would have flattened the shading instead.
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
    // §3.11.2 and §3.11.4, and BEFORE the index is built rather than after: the
    // silhouettes become children of the meshes, and `indexSolidNodes` reads the
    // loader's `associations` map, which only ever names nodes the loader made.
    // Authoring first proves the join is unaffected by what we add.
    this.display = authorDisplay(gltf.scene, this.palette);
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
    // No part, no floor. A grid left standing over an empty canvas would be the
    // viewport drawing a ruler for something it is not showing.
    this.rebuildGrid();
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
    // §3.11.5's grid is stepped off the span this framing just fixed — the same
    // number `GridReadout` prints — so it is rebuilt exactly when that number
    // changes and at no other time. §5.2's "framed once and held" therefore
    // holds the grid still through a whole explode drag as well.
    this.rebuildGrid();
    this.render();
  }

  /**
   * The ground grid's spacing in model units, or 0 before a framing.
   *
   * §3.11.5 wants the readout to "finally describe something visible", so the
   * readout reads this rather than deriving a second answer. A screen-space
   * quantity like `scale()`, and rendered the same way: never through `<Fact>`.
   */
  gridStep(): number {
    return this.step;
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

  /**
   * Be told after every drawn frame. Returns the unsubscribe.
   *
   * The axis triad (§3.11.6) is the only listener and it needs one per orbit
   * frame, which is why this is a plain callback set and not a React state
   * write: sixty re-renders a second to move three lines is what §5.5's
   * camera-settle write already exists to avoid.
   */
  onFrame(listener: () => void): () => void {
    this.frameListeners.add(listener);
    return () => {
      this.frameListeners.delete(listener);
    };
  }

  /** Draw one frame now. Synchronous on purpose; see the header. */
  render(): void {
    if (this.disposed) return;
    this.renderer.render(this.scene, this.camera);
    for (const listener of this.frameListeners) listener();
  }

  dispose(): void {
    this.disposed = true;
    if (this.frameRequest !== 0) cancelAnimationFrame(this.frameRequest);
    this.controls.removeEventListener("change", this.requestFrame);
    this.controls.removeEventListener("end", this.settleCamera);
    this.controls.dispose();
    this.frameListeners.clear();
    this.clearRoot();
    this.grid?.dispose();
    this.grid = null;
    this.renderer.dispose();
  }

  /**
   * The three world axes as **screen-space** unit vectors, for the axis triad.
   *
   * `[x, y]` in a `+x right, +y down` frame — the frame an SVG uses — so the
   * triad's markup is the projection and nothing else. `depth` is the axis's
   * component along the view direction, negative toward the viewer; the triad
   * uses it only to order the three so the nearest is drawn last.
   *
   * §1 hands this to the client outright: "The client may compute screen-space
   * quantities … camera transforms". Nothing here is or becomes a measurement —
   * the vectors are unit-length by construction, so no model distance survives
   * the projection at all.
   */
  cameraBasis(): readonly { readonly axis: "x" | "y" | "z"; readonly screen: readonly [number, number]; readonly depth: number }[] {
    const right = new Vector3();
    const up = new Vector3();
    const forward = new Vector3();
    this.camera.matrixWorld.extractBasis(right, up, forward);
    const axes = [
      { axis: "x" as const, world: new Vector3(1, 0, 0) },
      { axis: "y" as const, world: new Vector3(0, 1, 0) },
      { axis: "z" as const, world: new Vector3(0, 0, 1) },
    ];
    return axes.map(({ axis, world }) => ({
      axis,
      // `-up` because screen y grows downward and the camera's up does not.
      screen: [world.dot(right), -world.dot(up)] as const,
      // `+forward` points from the target toward the eye, so a positive dot is
      // an axis leaning toward the viewer.
      depth: world.dot(forward),
    }));
  }

  private aspect(): number {
    const size = this.renderer.getSize(new Vector2());
    return size.y > 0 ? size.x / size.y : 1;
  }

  private clearRoot(): void {
    for (const child of [...this.root.children]) this.root.remove(child);
    // The authored material and the edge geometries are ours; the GLB's own
    // buffers are the loader's and are collected with the parsed document. The
    // preserved exporter material is NEVER disposed here — see `display.ts`.
    this.display?.dispose();
    this.display = null;
  }

  /**
   * Rebuild the ground grid for the current framing and bounds.
   *
   * The grid follows the **plain** bounds even while explode is engaged: the
   * floor a part stands on does not move when the part comes apart, and a pad
   * that grew with the explosion would make the readout's step describe a
   * different picture at every `t`.
   */
  private rebuildGrid(): void {
    this.grid?.dispose();
    for (const child of [...this.gridRoot.children]) this.gridRoot.remove(child);
    this.grid = null;
    const framing = this.framing;
    const bounds = this.bounds;
    if (framing === null || bounds === null) {
      this.step = 0;
      return;
    }
    const span = framing.halfHeight * 2;
    this.step = gridStep(span);
    const spec = groundGridSpec(bounds, span);
    if (spec === null) {
      this.step = 0;
      return;
    }
    const grid = buildGroundGrid(spec, this.palette);
    this.grid = grid;
    this.gridRoot.add(grid.object);
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
