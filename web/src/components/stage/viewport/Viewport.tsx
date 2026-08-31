// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The viewport (INTERFACE.md §5), and the whole of the client's share of
// rendering: a three.js canvas over the **pinned** artifact's GLB, the overlay
// controls (view cube, appearance cluster, explode, section), and one
// server-rendered plate layer.
//
// The component is a *driver*. `viewport/engine.ts` owns the renderer, the scene
// and the camera; every workspace field this viewport reads gets exactly one
// effect that pushes it into the engine, so there is no path by which the canvas
// and the URL can disagree about what is being shown.
//
// STATES, all named, none blank. §5.5: "During a rebuild the viewport keeps the
// **last completed** artifact … It never blanks." The absences below are the
// ones that are not that case — no pin at all, a refused GLB, a browser with no
// WebGL — and each says which it is:
//
//   data-glb-state = "no-pin" | "loading" | "stale" | "ready" | "refused"
//                  | "no-webgl" | "empty"
//
// `stale` is §5.5's own word and its own case: a *new* ref is being fetched while
// the **last completed** artifact is still on the canvas. The canvas is not
// cleared and `data-artifact-ref` keeps naming the artifact actually drawn, not
// the one being fetched — naming the pending ref over the old pixels would be
// the workspace claiming to show geometry it has not received.
//
// and `data-section-state` carries §5.3's distinction ("preview" while the
// clipping plane is live, "rendered" once the server's plate is up, absent when
// there is no section).

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { WorkspaceError } from "../../../api/client";
import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { NoWebglError, ViewportEngine } from "../../../viewport/engine";
import { parseSectionPlane } from "../../../viewport/section";
import { installViewportHandle } from "../../../viewport/testHook";
import { useGlb } from "../../../viewport/useGlb";
import { labelsForPart, visibilityStore } from "../../../state/visibility";
import { Badge, Chip, EmptyState, type IconId } from "../../../system";
import type { SolidIndex } from "../../../viewport/scene";
import { appearanceStore } from "../../../state/appearance";
import { AppearanceControls } from "./AppearanceControls";
import { AxisTriad } from "./AxisTriad";
import { ExplodeSlider } from "./ExplodeSlider";
import { GridReadout } from "./GridReadout";
import { SectionControl, type SceneBounds } from "./SectionControl";
import { SectionPlate } from "./SectionPlate";
import { ViewCube } from "./ViewCube";
import styles from "./Viewport.module.css";

type GlbState = "no-pin" | "loading" | "stale" | "ready" | "refused" | "no-webgl" | "empty";

/** One sprite id per named absence. `ready` never reaches the empty state. */
const ABSENCE_ICON: Readonly<Record<Exclude<GlbState, "ready">, IconId>> = {
  "no-pin": "pin",
  loading: "refresh",
  stale: "refresh",
  refused: "alert",
  "no-webgl": "alert",
  empty: "cube",
};

export function Viewport(): React.JSX.Element {
  const artifactRef = useWorkspace((s) => s.artifact_ref);
  const view = useWorkspace((s) => s.view);
  const explodeT = useWorkspace((s) => s.explode_t);
  const sectionPlane = useWorkspace((s) => s.section_plane);
  const overlay = useWorkspace((s) => s.channel_overlay);
  const part = useWorkspace((s) => s.part);
  // §5.4's toggles live in the Inspector's Results panel and write to the one
  // visibility store (`state/visibility.ts`); the viewport is the party that
  // applies them. Reading the store here rather than threading the set through
  // the Stage keeps the two halves in different regions of §4.1's shell without
  // a second authority between them.
  const hiddenKeys = useSyncExternalStore(
    visibilityStore.subscribe,
    visibilityStore.getSnapshot,
    visibilityStore.getSnapshot,
  );
  const hidden = useMemo(() => new Set(labelsForPart(hiddenKeys, part)), [hiddenKeys, part]);
  const appearance = useSyncExternalStore(
    appearanceStore.subscribe,
    appearanceStore.getSnapshot,
    appearanceStore.getSnapshot,
  );
  const glb = useGlb(artifactRef);

  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<ViewportEngine | null>(null);
  const indexRef = useRef<SolidIndex | null>(null);
  const loadedRefRef = useRef<string | null>(null);
  // What the engine last framed to: the view **and** whether explode was
  // engaged, because the server frames those two states to different extents
  // (`scene.ts::boundsAt`). §5.5's orbit snapshot writes a *name* for a camera
  // that is already there; re-framing on that write would yank the camera to the
  // rounded angles the instant the user let go, so the ref is set before the
  // write and the effect below sees no change.
  const framedRef = useRef<string | null>(null);
  const framingKey = `${view}|${explodeT > 0 ? "exploded" : "collapsed"}`;
  const [engineReady, setEngineReady] = useState(false);
  // The engine as *state* as well as a ref, for the one child that needs the
  // object rather than the fact of it: `AxisTriad` subscribes to the engine's
  // frame signal, and a subscription cannot be built from a ref that React never
  // tells it changed. Written and cleared in the same effect that owns the ref.
  const [engine, setEngine] = useState<ViewportEngine | null>(null);
  const [webglError, setWebglError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [bounds, setBounds] = useState<SceneBounds | null>(null);
  const [scale, setScale] = useState(0);
  /** §3.11.5's grid spacing, so the readout describes the grid it is next to. */
  const [step, setStep] = useState(0);
  // The ref whose geometry the engine last finished loading. It is written only
  // from the load callback; with no pin at all there is nothing on the canvas,
  // which `displayedRef` below expresses without a second write.
  const [loadedIntoScene, setLoadedIntoScene] = useState<string | null>(null);

  const onCameraSettled = useCallback((viewName: string): void => {
    framedRef.current = null;
    workspaceStore.update({ view: viewName });
  }, []);

  const onFit = useCallback((): void => {
    const live = engineRef.current;
    if (live === null) return;
    // Fit is an explicit re-frame of the *current* named view, including after
    // an orbit: `framedRef` would otherwise skip `frame()` for the same key.
    live.frame(view, explodeT > 0);
    framedRef.current = framingKey;
    setScale(live.scale());
    setStep(live.gridStep());
  }, [view, explodeT, framingKey]);

  // -- the engine: one per canvas, for the canvas's life --------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) return;
    let engine: ViewportEngine | null = null;
    let failure: string | null = null;
    try {
      engine = new ViewportEngine(canvas, { onCameraSettled });
    } catch (error) {
      failure = error instanceof NoWebglError ? error.message : String(error);
    }
    setWebglError(failure);
    if (engine === null) return;
    engineRef.current = engine;
    setEngine(engine);
    setEngineReady(true);
    const removeHandle = installViewportHandle(() => ({
      index: indexRef.current,
      artifactRef: loadedRefRef.current,
    }));
    const created = engine;
    return () => {
      removeHandle();
      engineRef.current = null;
      indexRef.current = null;
      loadedRefRef.current = null;
      setEngine(null);
      setEngineReady(false);
      created.dispose();
    };
  }, [onCameraSettled]);

  // -- size: the drawing buffer follows the host box ------------------------
  useEffect(() => {
    const host = hostRef.current;
    if (host === null || !engineReady) return;
    const observer = new ResizeObserver(() => {
      const rect = host.getBoundingClientRect();
      engineRef.current?.resize(rect.width, rect.height);
      setScale(engineRef.current?.scale() ?? 0);
    });
    observer.observe(host);
    const rect = host.getBoundingClientRect();
    engineRef.current?.resize(rect.width, rect.height);
    return () => {
      observer.disconnect();
    };
  }, [engineReady]);

  // -- geometry: load the pinned GLB, frame once ----------------------------
  const bytes = glb.data?.bytes;
  const geometry = glb.data?.geometry;
  const loadedRef = glb.data?.requested_ref ?? null;
  useEffect(() => {
    const engine = engineRef.current;
    if (engine === null || !engineReady) return;
    if (bytes === undefined || geometry === undefined || loadedRef === null) {
      // §5.5: a *rebuild* keeps the last completed artifact. This branch is the
      // other case — the pin itself went away — and an empty scene is then the
      // truthful picture rather than a stale one.
      if (artifactRef === null) {
        engine.clear();
        indexRef.current = null;
        loadedRefRef.current = null;
      }
      return;
    }
    let cancelled = false;
    void engine
      .load(bytes, geometry)
      .then((index) => {
        if (cancelled) return;
        // The outcome is reported from the callback, never synchronously in the
        // effect body: the load is the external system, and React learns what
        // happened when it has happened.
        setLoadError(null);
        indexRef.current = index;
        loadedRefRef.current = loadedRef;
        setLoadedIntoScene(loadedRef);
        setBounds(engine.boundsBox());
        engine.setExplode(explodeT);
        engine.setHidden(hidden);
        engine.frame(view, explodeT > 0);
        framedRef.current = framingKey;
        setScale(engine.scale());
        setStep(engine.gridStep());
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(String(error));
      });
    return () => {
      cancelled = true;
    };
    // `explodeT`/`hidden`/`view` are seeded from their current values on load and
    // then owned by the three effects below; listing them here would reload the
    // GLB on every slider tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bytes, geometry, loadedRef, artifactRef, engineReady]);

  // -- explode: `offset · t` (§5.2) -----------------------------------------
  useEffect(() => {
    engineRef.current?.setExplode(explodeT);
  }, [explodeT, engineReady]);

  // -- camera: framed once per (view, explode engaged) and held (§5.2) ------
  useEffect(() => {
    if (!engineReady || framedRef.current === framingKey) return;
    engineRef.current?.frame(view, explodeT > 0);
    framedRef.current = framingKey;
    setScale(engineRef.current?.scale() ?? 0);
    setStep(engineRef.current?.gridStep() ?? 0);
  }, [framingKey, view, explodeT, engineReady]);

  // -- visibility: a scene-graph property (§5.4) ----------------------------
  useEffect(() => {
    engineRef.current?.setHidden(hidden);
  }, [hidden, engineReady]);

  // -- appearance: the operator cluster (§3.11, §5.5) -----------------------
  useEffect(() => {
    engineRef.current?.setAppearance({
      wireframe: appearance.wireframe,
      materialOverride: appearance.materialOverride,
    });
  }, [appearance.wireframe, appearance.materialOverride, engineReady]);

  useEffect(() => {
    engineRef.current?.setGridVisible(appearance.grid);
  }, [appearance.grid, engineReady]);

  useEffect(() => {
    engineRef.current?.setOrtho(appearance.ortho);
  }, [appearance.ortho, engineReady]);

  // -- section: the live clipping preview (§5.3) ----------------------------
  const plane = useMemo(
    () => (sectionPlane === null ? null : parseSectionPlane(sectionPlane)),
    [sectionPlane],
  );
  useEffect(() => {
    engineRef.current?.setSection(plane);
  }, [plane, engineReady]);

  /** What is actually drawn: the last completed artifact, or nothing at all. */
  const displayedRef = artifactRef === null ? null : loadedIntoScene;

  const state: GlbState =
    webglError !== null
      ? "no-webgl"
      : artifactRef === null
        ? "no-pin"
        : glb.isError || loadError !== null
          ? "refused"
          : glb.data === undefined
            ? // §5.5: a *replacement* being fetched is `stale`, not `loading` —
              // the canvas still holds the last completed artifact.
              displayedRef === null
              ? "loading"
              : "stale"
            : glb.data.geometry.mesh_count === 0
              ? "empty"
              : "ready";

  const refusalReason =
    glb.error instanceof WorkspaceError ? glb.error.reason : loadError === null ? null : "malformed_gltf";

  // §5.3: "preview" while the browser is clipping, and the plate's own state
  // replaces it. `channel_overlay === "section"` is §4.5's switch for the plate.
  const sectionState = plane === null ? null : overlay === "section" ? "rendered" : "preview";

  return (
    <div
      ref={hostRef}
      className={styles["viewport"]}
      data-testid="viewport"
      data-glb-state={state}
      {...(displayedRef === null ? {} : { "data-artifact-ref": displayedRef })}
      {...(sectionState === null ? {} : { "data-section-state": sectionState })}
      aria-label={copy.viewport.label}
    >
      <canvas ref={canvasRef} className={styles["canvas"]} data-viewport-canvas="" />

      {state === "ready" ? null : (
        // §3.3's principle 5, generalised past the stream column: every state —
        // refusal, absence, "still loading" — is a first-class composed state
        // with a shape, an icon, a heading and its prose in a legible ink. The
        // shipped absence was an italic 3.10:1 sentence in the middle of a black
        // rectangle, which reads as a bug rather than as a designed state.
        <div className={styles["absent"]} data-viewport-absence={state}>
          <EmptyState
            icon={ABSENCE_ICON[state]}
            title={copy.viewport.absenceTitle[state]}
            body={
              <>
                <p>{copy.viewport.absence[state]}</p>
                {refusalReason === null ? null : (
                  <p>
                    <Chip tone="code" data-refusal-reason={refusalReason}>
                      {refusalReason}
                    </Chip>
                  </p>
                )}
              </>
            }
          />
        </div>
      )}

      {sectionState === "preview" ? (
        // §5.3: the preview "carries `data-section-state="preview"`, is **never**
        // golden-compared". The attribute is on the host; this is the same fact
        // said to the person looking at it, which is the half a machine-readable
        // attribute cannot carry.
        <span className={styles["previewNote"]} title={copy.viewport.section.previewExplain}>
          <Badge status="error">{copy.viewport.section.previewLabel}</Badge>
        </span>
      ) : null}

      {overlay === "section" && plane !== null ? <SectionPlate plane={plane.spec} /> : null}

      <ViewCube />
      {/* §3.11.6. Bottom-left with the readout, and — like the readout — an
          overlay that never changes size, because a Playwright element
          screenshot composites what is painted over the canvas and G4.5's
          control region is exactly that frame (see `GridReadout`'s header). */}
      <AxisTriad engine={engine} visible={appearance.triad} />
      {/* The grid step is a fact about a grid, so it is reported only while
          there is one. Derived at render rather than cleared from the load
          effect: an effect that calls `setState` in its own body is the
          cascading render `react-hooks/set-state-in-effect` refuses, and the
          answer is a pure function of state we already hold. Off is the same
          as "no framing": the readout must not describe a grid the operator
          has hidden. */}
      <GridReadout scale={scale} step={displayedRef === null || !appearance.grid ? 0 : step} />
      <AppearanceControls canFit={displayedRef !== null && state === "ready"} onFit={onFit} />
      <div className={styles["controls"]}>
        <ExplodeSlider />
        {/* The bounds belong to the *loaded* GLB: while none is loaded the
            control seats its offset on its own fallback range rather than on the
            previous artifact's, which would name a plane in the wrong model. */}
        <SectionControl bounds={glb.data === undefined ? null : bounds} />
      </div>
    </div>
  );
}
