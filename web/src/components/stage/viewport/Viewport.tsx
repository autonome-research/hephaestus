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
//
// THE OVERLAYS EXIST WHEN THERE IS GEOMETRY (operator review, 2026-09-01). The
// shipped viewport painted the whole control frame over every state, so an
// unbuilt part got a view cube, an axis triad, a grid readout describing a grid
// that was not drawn, six appearance toggles, an explode slider, a `Cut a
// section` control, and a centred paragraph — nine surfaces around an empty
// well, every one of them addressing an artifact that is not there. §5.5 defines
// the cluster as operator chrome "bound to the pin", and `Fit`'s own disabled
// reason already said "No pinned artifact is on the canvas, so there is nothing
// to frame" — which is true of the entire frame, not of one button in it. The
// overlays now render while `hasGeometry` holds (`ready`, and `stale`, which by
// §5.5 keeps the LAST COMPLETED artifact on the canvas and must not lose its
// controls mid-rebuild); otherwise the well carries one short empty state and
// nothing else. G4.5's control-region thresholds are unaffected: they are
// measured on a `ready` canvas, where every overlay is exactly where it was.

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { WorkspaceError } from "../../../api/client";
import { copy } from "../../../copy";
import { useBuild } from "../../../api/queries";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { NoWebglError, ViewportEngine } from "../../../viewport/engine";
import { plateOwnsWell as plateOwnsWellFor, parseSectionPlane } from "../../../viewport/section";
import { installViewportHandle } from "../../../viewport/testHook";
import { cameraPoseStore } from "../../../state/cameraPose";
import { anglesFromDirection } from "../../../viewport/cameras";
import { useGlb } from "../../../viewport/useGlb";
import { labelsForPart, visibilityStore } from "../../../state/visibility";
import { Badge, Button, Chip, EmptyState, type IconId } from "../../../system";
import type { SolidIndex } from "../../../viewport/scene";
import { appearanceStore } from "../../../state/appearance";
import { ExplodeSlider } from "./ExplodeSlider";
import { ViewCube } from "./ViewCube";
import { SectionControl, type SceneBounds } from "./SectionControl";
import { SectionPlate } from "./SectionPlate";
import styles from "./Viewport.module.css";

type GlbState =
  | "no-pin"
  | "loading"
  | "stale"
  | "ready"
  | "refused"
  | "no-webgl"
  | "empty"
  | "not-built";

/** One sprite id per named absence. `ready` never reaches the empty state. */
const ABSENCE_ICON: Readonly<Record<Exclude<GlbState, "ready">, IconId>> = {
  "no-pin": "pin",
  loading: "refresh",
  stale: "refresh",
  refused: "alert",
  "no-webgl": "alert",
  empty: "cube",
  "not-built": "cube",
};

/**
 * §5.5 C10 — which absence an EMPTY PIN composes to.
 *
 * `not-built` renders when the pin holds no artifact AND the selected part's
 * build state is `not_built` — the state where the well is empty because this
 * part has simply never been built — and in NO other state: with no part
 * selected, `no-pin` renders as before, and a part with a failed build (or a
 * build projection that has not answered, or refused to) stays `no-pin` here
 * and renders its failure where failures render. The build status is a server
 * projection (`GET /parts/{part}/build`); this function composes, it does not
 * derive (§1). Exported so both halves of the never-renders rule are testable
 * without a WebGL context.
 */
export function emptyPinAbsence(
  part: string | null,
  buildStatus: string | undefined,
): "no-pin" | "not-built" {
  return part !== null && buildStatus === "not_built" ? "not-built" : "no-pin";
}

/**
 * §5.5 C18 — the named stage width below which the bottom band yields, and the
 * fixed order it yields in: the explode slider collapses to its disclosure
 * first, then the section control, and the legend yields last, because a
 * readout that lies about camera scale is worse than a missing control.
 * 560px is the named threshold (the width at which 120px of explode track no
 * longer fits beside the other two); the later steps are derived from the
 * remaining occupants' natural widths. Nothing yields above 560px.
 */
export const BAND_YIELD_WIDTH = 560;
const SECTION_YIELD_WIDTH = 450;

/**
 * The states whose TITLE is the whole fact, so the plate prints no sentence.
 *
 * "No artifact pinned" over "No artifact is pinned, so there is no geometry to
 * show." is the heading twice. The other four absences say something the title
 * does not — which artifact is still on the canvas, that the server refused, that
 * this browser has no WebGL, that the build has no solids — and keep their prose.
 */
const TITLE_IS_ENOUGH: ReadonlySet<GlbState> = new Set<GlbState>(["no-pin", "loading"]);

/**
 * The well's one composed state, for every case that is not `ready`.
 *
 * Exported so all seven can be asserted without a WebGL context: jsdom reaches
 * exactly one of them (`no-webgl`), and "the empty viewport is quiet" is a claim
 * about the other six as much as about that one.
 */
export function ViewportAbsence({
  state,
  refusalReason,
  part = null,
}: {
  readonly state: Exclude<GlbState, "ready">;
  readonly refusalReason: string | null;
  /** The selected part's name — a server fact — for the `not-built` state. */
  readonly part?: string | null;
}): React.JSX.Element {
  if (state === "not-built") {
    // §5.5 C10: the title names the part and the state; the body is exactly
    // the two remedies — ask the agent below, or `heph build <part>` (the
    // command in `.code`). Both facts are server projections; composed here.
    const name = part ?? "";
    return (
      <div className={styles["absent"]} data-viewport-absence="not-built">
        <div className={styles["absencePlate"]}>
          <EmptyState
            icon={ABSENCE_ICON[state]}
            title={copy.viewport.notBuilt.title(name)}
            action={<Button variant="secondary" data-unbuilt-conversation="" onClick={() => {
              // The Stream is always mounted, so this only moves focus.
              const target = document.querySelector<HTMLElement>("[data-composer-input]:not(:disabled)")
                ?? document.querySelector<HTMLElement>("#composer");
              target?.focus({ preventScroll: true });
            }}>{copy.viewport.notBuilt.open}</Button>}
            body={
              <>
                <p>{copy.viewport.notBuilt.ask}</p>
                <p>
                  {copy.viewport.notBuilt.run}{" "}
                  <Chip tone="code" data-not-built-command="">
                    {copy.viewport.notBuilt.command(name)}
                  </Chip>
                </p>
              </>
            }
          />
        </div>
      </div>
    );
  }
  const prose = !TITLE_IS_ENOUGH.has(state) || refusalReason !== null;
  return (
    <div className={styles["absent"]} data-viewport-absence={state}>
      <div className={styles["absencePlate"]}>
        <EmptyState
          icon={ABSENCE_ICON[state]}
          title={copy.viewport.absenceTitle[state]}
          {...(prose
            ? {
                body: (
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
                ),
              }
            : {})}
        />
      </div>
    </div>
  );
}

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
  // §5.5 C10: the `not-built` absence needs the selected part's build STATE,
  // and only while the pin is empty — with an artifact pinned the projection
  // is irrelevant to the well and the query stays off.
  const build = useBuild(part, artifactRef === null);

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
  // The engine as *state* as well as a ref. Its one consumer was `AxisTriad`,
  // which subscribed to the engine's frame signal; the triad is struck, so the
  // setter is kept (the effect that owns the ref writes it) and the value is
  // not read. Left as state rather than collapsed to a ref because the effect
  // below clears it on teardown and a ref would hide that from React.
  const [, setEngine] = useState<ViewportEngine | null>(null);
  const [webglError, setWebglError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [bounds, setBounds] = useState<SceneBounds | null>(null);
  /** §5.5 C18: the stage column's width, for the bottom band's yield ladder. */
  const [stageWidth, setStageWidth] = useState<number | null>(null);
  const bandRef = useRef<HTMLDivElement | null>(null);
  /**
   * §5.5 C18's yield ladder, MEASURED (J-web-viewport-3).
   *
   * The ladder compared a width constant against the stage width and never
   * looked at what the band actually demands — which depends on whether a
   * section is engaged (the control's natural size goes from 131px collapsed to
   * 624px engaged), whether explode is engaged, and how wide the readout's
   * numbers are. So at 1600px with a section engaged the explode card was
   * squeezed to 113px around 172px of content and its Collapse button was drawn
   * entirely on the canvas, while nothing yielded, because both widths are above
   * the trigger.
   *
   * `level` is how far down C18's fixed order the band has yielded: 1 collapses
   * the explode slider to its disclosure, 2 also yields the section control. The
   * legend is last and stays on the width constant, because a readout that lies
   * about camera scale is worse than a missing control.
   *
   * `width` is the band width the level was latched at, and it is what keeps
   * this from oscillating: yielding makes the band fit, which would otherwise
   * un-yield it. The latch is released only when the band gets WIDER than the
   * width that produced it, so the term is monotone in one direction per size.
   */
  const [pressure, setPressure] = useState<{ level: number; width: number }>({
    level: 0,
    width: 0,
  });
  /** §3.11.5's grid spacing, so the readout describes the grid it is next to. */
  // The ref whose geometry the engine last finished loading. It is written only
  // from the load callback; with no pin at all there is nothing on the canvas,
  // which `displayedRef` below expresses without a second write.
  const [loadedIntoScene, setLoadedIntoScene] = useState<string | null>(null);

  const onCameraSettled = useCallback((viewName: string): void => {
    // Recording an orbit's nearest name must not refit its zoom/pan or round
    // its pose. Explicit view navigation and Fit still frame normally.
    framedRef.current = `${viewName}|${workspaceStore.getSnapshot().explode_t > 0 ? "exploded" : "collapsed"}`;
    workspaceStore.update({ view: viewName });
  }, []);

  /*
   * RE-FIT, BACK ON THE CUBE (2026-09-20).
   *
   * §5.5's Fit — "re-applies `cameras.py`'s framing for the current named
   * view" — was a button in the appearance cluster. When the cluster moved out
   * to `StageViewRail`, Fit's HANDLER had to cross a sibling boundary that its
   * presence never did, and it was dropped rather than threaded. Dropping it
   * left no way back from a deliberate orbit except picking a DIFFERENT view,
   * which is a worse answer than the one the operator wanted.
   *
   * It belongs on the cube, which lives here and needs nothing threaded:
   * clicking the cell whose camera you are already on means "frame this view
   * again", which is what every other view cube does and what the control is
   * shaped like. A click that CHANGES the view re-frames through `framingKey`
   * as before; this is only the unchanged case, which that key cannot see.
   */
  const refit = useCallback((): void => {
    const live = engineRef.current;
    if (live === null) return;
    const state = workspaceStore.getSnapshot();
    live.frame(state.view, state.explode_t > 0);
  }, []);

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
      camera: engineRef.current?.cameraSnapshot() ?? null,
    }));
    // PUBLISH THE LIVE POSE for the orientation gizmo (2026-09-20). The cube
    // used to read `workspace.view`, which is written once when a drag SETTLES
    // — so it stood still through an orbit and then snapped to the nearest
    // named view. `onFrame` fires after every drawn frame, which is exactly
    // the rate the gizmo needs to track the camera.
    const removePose = engine.onFrame(() => {
      const live = engineRef.current?.cameraSnapshot();
      if (live === undefined) return;
      cameraPoseStore.set(
        anglesFromDirection([
          live.eye[0] - live.target[0],
          live.eye[1] - live.target[1],
          live.eye[2] - live.target[2],
        ]),
      );
    });
    const created = engine;
    return () => {
      removePose();
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
      setStageWidth(rect.width);
    });
    observer.observe(host);
    const rect = host.getBoundingClientRect();
    engineRef.current?.resize(rect.width, rect.height);
    setStageWidth(rect.width);
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
        ? // §5.5 C10: an empty pin composes to `not-built` only when the
          // selected part's build state IS `not_built` — never over a failure
          // (status `error` keeps `no-pin`) or a no-selection state.
          emptyPinAbsence(part, build.data?.status)
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

  /**
   * Is there geometry on this canvas? `ready` yes; `stale` also yes — §5.5's
   * whole point is that a rebuild keeps the last completed artifact — and every
   * other state is an empty well whose controls would address nothing.
   */
  const hasGeometry = state === "ready" || state === "stale";

  /** C18's yield ladder input: unmeasured means "wide" — nothing yields early. */
  const bandWidth = stageWidth ?? Number.POSITIVE_INFINITY;

  /**
   * §5.3 (amended 2026-09-05): while a plate covers the well, THE PLATE OWNS THE
   * WELL (J-web-viewport-2).
   *
   * The plate is absolutely positioned over the whole well with a full-bleed
   * header, and every viewport overlay used to be painted on top of it: the
   * appearance cluster covered the header's left end and the view cube its right
   * end, so the `source_artifact_ref` §5.3 requires be shown was partly
   * unreadable — and six controls that address a live canvas were drawn over a
   * rendered image they cannot affect, which is the deeper incoherence that
   * merely nudging them down would have left in place.
   *
   * So the four CANVAS-AUTHORING overlays unmount: the view cube, the appearance
   * cluster, the axis triad and the grid readout all describe or drive a camera
   * that is not what the reader is looking at. The section control stays because
   * it is the EXIT — without it the plate is a state with no way out — and the
   * explode slider stays only while engaged, so its `t` can be returned to 0.
   * The surface set under a plate is then the header, the section control and
   * (sometimes) the explode card: disjoint by construction.
   */
  const plateOwnsWell = plateOwnsWellFor(overlay, sectionPlane);

  // -- the bottom band: does it fit? (§5.5 C18, J-web-viewport-3) -----------
  //
  // The band's own box tracks the host, so a host resize is one input; the other
  // is the band's DEMAND, which changes with no resize at all when a section is
  // engaged and the section control goes from 131px to 624px. Observing every
  // CHILD as well as the band catches that, and re-running this effect whenever
  // the occupant set changes re-observes — `observe()` delivers an initial
  // callback, which is how a fresh measurement is taken after a render without
  // this effect setting state in its own body.
  useEffect(() => {
    const band = bandRef.current;
    if (band === null) return;
    const measure = (): void => {
      const width = band.clientWidth;
      const over = band.scrollWidth > width + 1;
      setPressure((current) => {
        if (!over) {
          // Released only when the band is WIDER than the width that latched
          // it; releasing at the same width is what would oscillate, because
          // yielding is exactly what made it fit.
          return width > current.width && current.level > 0 ? { level: 0, width: 0 } : current;
        }
        if (width > current.width) return { level: 1, width };
        // C18's fixed order: explode first, then the section control. The
        // legend never yields on this term.
        return current.level >= 2 ? current : { level: current.level + 1, width };
      });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(band);
    for (const child of band.children) observer.observe(child);
    return () => {
      observer.disconnect();
    };
  }, [hasGeometry, plateOwnsWell, plane, explodeT, stageWidth, pressure.level]);

  return (
    <div
      ref={hostRef}
      className={styles["viewport"]}
      data-testid="viewport"
      data-glb-state={state}
      {...(displayedRef === null ? {} : { "data-artifact-ref": displayedRef })}
      {...(sectionState === null ? {} : { "data-section-state": sectionState })}
    >
      <canvas
        ref={canvasRef}
        id="stage"
        className={styles["canvas"]}
        data-viewport-canvas=""
        tabIndex={0}
        aria-label={copy.viewport.label}
      />

      {state === "ready" ? null : (
        // §3.3's principle 5, generalised past the stream column: every state —
        // refusal, absence, "still loading" — is a first-class composed state
        // with a shape, an icon, a heading and its prose in a legible ink. The
        // shipped absence was an italic 3.10:1 sentence in the middle of a black
        // rectangle, which reads as a bug rather than as a designed state.
        <ViewportAbsence state={state} refusalReason={refusalReason} part={part} />
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

      {!hasGeometry ? null : (
        <>
          {/* The view cube, restored 2026-09-20 with the axes drawn INSIDE it.
              It was struck earlier the same day as one of two overlays painted
              over the model; what came back is one widget, not two, in the
              corner furthest from the controls — and it is again the only thing
              that SETS a named view by click. Every cell is a face, edge or
              corner of a bevelled cube, and the drawn polygon IS the hit region
              (`viewport/cubeTargets.ts`); the axes share its projection, so the
              letters cannot point somewhere the cube does not. */}
          {plateOwnsWell ? null : <ViewCube onRefit={refit} />}
          {/* §3.11's View / Scale / Grid readout is STRUCK (2026-09-20). It was
              a plate over the model reporting three facts the operator can see
              or does not need: the named view is in the URL, the grid's step is
              visible in the grid, and the scale changes as they zoom. The
              camera-scale and grid-step state it read is gone with it. */}
          {/* The appearance cluster is DRAWN BY THE STAGE RAIL since
              2026-09-20 — the same edge the view switches sit on, so every
              control that changes what you are looking at is one column rather
              than two corners of the canvas. This component publishes nothing
              to it: the cluster is four `appearanceStore` flags, and the rail
              gates them on the stage tab it already reads. Fit was the one
              control that needed a handler across that boundary, and Fit was
              struck later the same day. */}
          {/* §5.5 C18: the bottom overlays share ONE flex band — the legend at
              `flex: none` (a readout never stretches), the explode slider at
              `flex: 1` with a 120px minimum track, the section control at its
              natural size. Below 560px of stage column the band yields in a
              fixed order — explode to its disclosure first, then the section
              control, the legend last — and no bottom overlay is ever
              absolutely positioned over another. */}
          <div className={styles["band"]} data-viewport-band="" ref={bandRef}>
            {/* Under a plate the explode card mounts only while engaged: an
                explode of 0 authors nothing and the plate is not showing it,
                but an engaged `t` must stay returnable to 0 (§5.2). */}
            {plateOwnsWell && explodeT === 0 ? null : (
              <ExplodeSlider
                noop={glb.data !== undefined && glb.data.geometry.mesh_count <= 1}
                // The measured term ORs with the constant and can only yield
                // EARLIER, so C18's specified behaviour below 560px is
                // unchanged: "nothing yields above 560px" becomes "nothing
                // yields above 560px while the band fits".
                yielded={bandWidth < BAND_YIELD_WIDTH || pressure.level >= 1}
              />
            )}
            {/* The bounds belong to the *loaded* GLB: while none is loaded the
                control seats its offset on its own fallback range rather than on
                the previous artifact's, which would name a plane in the wrong
                model. */}
            <SectionControl
              bounds={glb.data === undefined ? null : bounds}
              yielded={bandWidth < SECTION_YIELD_WIDTH || pressure.level >= 2}
              noop={glb.data !== undefined && glb.data.geometry.mesh_count <= 1}
            />
          </div>
        </>
      )}
    </div>
  );
}
