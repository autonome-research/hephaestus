// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { Box3, BoxGeometry, Group, Mesh, MeshStandardMaterial, Vector3 } from "three";
import type { OrthographicCamera, PerspectiveCamera, Vector2 } from "three";
import type * as Three from "three";
import type { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { Viewport } from "../src/components/stage/viewport/Viewport";
import { ViewportEngine } from "../src/viewport/engine";
import type { CameraSnapshot } from "../src/viewport/engine";
import { framingFor } from "../src/viewport/scene";
import { workspaceStore } from "../src/state/react";
import { DEFAULT_STATE } from "../src/state/workspace";
import { appearanceStore } from "../src/state/appearance";
import { claimToken, dropToken } from "../src/api/token";
import { fakeGlb } from "./glb";

// Only GPU rendering and external input/completion are mocked. Viewport, the
// query/store, engine framing, scene indexing and OrbitControls all run normally.
vi.mock("three", async (original) => {
  const actual = await original<typeof Three>();
  return { ...actual, WebGLRenderer: class {
    size = new actual.Vector2(800, 600);
    setClearColor() {} setPixelRatio() {} render() {} dispose() {}
    setSize(width: number, height: number) { this.size.set(width, height); }
    getSize(out: Vector2) { return out.copy(this.size); }
  } };
});

type Internals = {
  bounds: Box3;
  explodedBounds: Box3;
  camera: OrthographicCamera | PerspectiveCamera;
  controls: OrbitControls;
  fit: { view: string; exploded: boolean } | null;
};
const reactEnvironment = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
let cleanup = (): void => {};
beforeAll(() => { reactEnvironment.IS_REACT_ACT_ENVIRONMENT = true; });
afterEach(() => {
  reactEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
  cleanup();
  cleanup = () => {};
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  workspaceStore.reset(DEFAULT_STATE);
  appearanceStore.reset();
  dropToken();
});
async function tick(): Promise<void> {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}
function direction(snapshot: CameraSnapshot): Vector3 {
  return new Vector3(...snapshot.eye).sub(new Vector3(...snapshot.target)).normalize();
}

for (const ortho of [true, false]) for (const held of [false, true]) {
  for (const action of ["none", "view", "explode"] as const) {
    it(`retry completion keeps pending ${action} intent from ${held ? "held" : "Fit"} (${ortho ? "ortho" : "perspective"})`, async () => {
      vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
      const frames: FrameRequestCallback[] = [];
      vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
        frames.push(callback); return frames.length;
      });
      vi.stubGlobal("cancelAnimationFrame", () => {});
      const drain = () => {
        for (let i = 0; frames.length > 0 && i < 400; i += 1) frames.shift()!(i * 16);
        expect(frames).toHaveLength(0);
      };
      const prior = `artifact:build:sha256:${"0".repeat(64)}`;
      const next = `artifact:build:sha256:${"b".repeat(64)}`;
      const selection = { selection_id: "solid:7", kind: "solid", bundle_ref: "bundle:test" };
      let requests = 0;
      let parses = 0;
      let release!: () => void;
      const meshes: Mesh<BoxGeometry, MeshStandardMaterial>[] = [];
      vi.spyOn(GLTFLoader.prototype, "parseAsync").mockImplementation(async () => {
        parses += 1;
        if (parses === 2) await new Promise<void>((resolve) => { release = resolve; });
        const scene = new Group();
        const associations = new Map();
        for (const [index, sign] of [-1, 1].entries()) {
          const mesh = new Mesh(new BoxGeometry(120, 50, 20), new MeshStandardMaterial());
          // GLB vertices are baked in world space; node transforms start at identity.
          mesh.geometry.translate(sign * 80, 0, 0);
          meshes.push(mesh); scene.add(mesh); associations.set(mesh, { meshes: index });
        }
        return { scene, parser: { associations } } as unknown as GLTF;
      });
      const load = vi.spyOn(ViewportEngine.prototype, "load"); // calls through
      const frame = vi.spyOn(ViewportEngine.prototype, "frame"); // calls through
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes(encodeURIComponent(next)) && ++requests === 1) throw new TypeError("offline");
        return new Response(fakeGlb({ solids: [
          { solid_index: 0, label: "left", explode_offset: [-100, -60, 0] },
          { solid_index: 1, label: "right", explode_offset: [100, 60, 0] },
        ] }));
      }));
      window.location.hash = "#t=completion-window-synthetic"; claimToken();
      workspaceStore.reset({ ...DEFAULT_STATE, view: "+X", artifact_ref: prior, pin_mode: "pinned", selection, focus: "solid:7" });
      if (appearanceStore.getSnapshot().ortho !== ortho) appearanceStore.toggle("ortho");
      const host = document.createElement("div"); document.body.append(host);
      const root = createRoot(host);
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      cleanup = () => {
        act(() => root.unmount()); client.clear(); host.remove();
        for (const mesh of meshes) { mesh.geometry.dispose(); mesh.material.dispose(); }
      };
      act(() => root.render(<QueryClientProvider client={client}><Viewport /></QueryClientProvider>));
      await tick(); await tick();
      const engine = load.mock.instances[0]!;
      expect(engine).toBeInstanceOf(ViewportEngine);
      if (!(engine instanceof ViewportEngine)) throw new Error("real engine missing");
      const live = engine as unknown as Internals;
      act(() => drain());
      expect(live.fit).toEqual({ view: "+X", exploded: false });
      if (held) act(() => {
        live.controls.dispatchEvent({ type: "start" });
        live.camera.position.add(new Vector3(19, -11, 7));
        live.controls.target.add(new Vector3(6, 4, -3));
        live.controls.update(); live.controls.dispatchEvent({ type: "end" }); drain();
      });
      expect(engine.cameraSnapshot().fit).toBe(!held);
      act(() => workspaceStore.hold(next)); await tick(); await tick();
      const retry = host.querySelector<HTMLButtonElement>("[data-glb-retry]");
      expect(retry).not.toBeNull();
      act(() => retry!.click()); await tick(); await tick();
      expect(parses).toBe(2);
      const before = engine.cameraSnapshot();
      const oldIndex = engine.solidIndex();
      frame.mockClear();
      let insideCompletionWindow = false;
      // Do NOT wrap this ordering in act: store intent arrives after the real
      // engine installs B, but before Viewport's promise callback acknowledges
      // it and before React runs the camera effect. No engine method is replaced.
      reactEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
      try {
        release();
        queueMicrotask(() => queueMicrotask(() => {
          insideCompletionWindow = engine.solidIndex() !== oldIndex && frame.mock.calls.length === 0;
          if (action === "view") workspaceStore.update({ view: "+Z" });
          if (action === "explode") workspaceStore.update({ explode_t: 0.6 });
        }));
        await new Promise((resolve) => setTimeout(resolve, 0));
      } finally { reactEnvironment.IS_REACT_ACT_ENVIRONMENT = true; }
      await tick(); act(() => drain());
      expect(insideCompletionWindow).toBe(true);
      const state = workspaceStore.getSnapshot();
      const fit = !held || action !== "none";
      expect(frame.mock.calls).toEqual(action === "none" ? [
        [state.view, false, { preserveCamera: true }],
      ] : [
        [state.view, state.explode_t > 0, { preserveCamera: true }],
        [state.view, state.explode_t > 0],
      ]);
      expect(live.fit).toEqual(fit ? { view: state.view, exploded: state.explode_t > 0 } : null);
      const after = engine.cameraSnapshot();
      expect(after.fit).toBe(fit);
      if (action === "none") expect(after).toEqual(before);
      if (action === "view") expect(state.view).toBe("+Z");
      if (action === "explode") {
        expect(state.explode_t).toBe(0.6);
        expect(meshes.slice(2).map((mesh) => new Box3().setFromObject(mesh).getCenter(new Vector3()).toArray()))
          .toEqual([[-140, -36, 0], [140, 36, 0]]);
      }
      expect(state).toMatchObject({ artifact_ref: next, pin_mode: "pinned", selection, focus: "solid:7" });
      expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-artifact-ref")).toBe(next);
      expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
      expect(document.activeElement).toBe(host.querySelector("[data-viewport-canvas]"));
      expect(requests).toBe(2);

      // Assert the metadata's observable consequences, not just its Fit flag.
      for (const width of [400, 950]) {
        act(() => engine.resize(width, 600));
        const resized = engine.cameraSnapshot();
        expect(resized.fit).toBe(fit);
        expect(resized.target).toEqual(after.target);
        expect(resized.up).toEqual(after.up);
        expect(direction(resized).distanceTo(direction(after))).toBeLessThan(1e-12);
        if (fit) {
          const framing = framingFor(state.explode_t > 0 ? live.explodedBounds : live.bounds, state.view, width / 600)!;
          const scale = ortho ? framing.halfHeight
            : Math.hypot(framing.halfWidth, framing.halfHeight) * 1.05 / Math.cos(35 * Math.PI / 360);
          expect(resized.scale).toBeCloseTo(scale, 10);
          if (ortho) expect(resized.eye).toEqual(after.eye);
        } else {
          expect(resized.eye).toEqual(after.eye);
          expect(resized.zoom).toBe(after.zoom);
          expect(resized.scale).toBe(after.scale);
        }
      }
      const beforeToggle = engine.cameraSnapshot();
      act(() => appearanceStore.toggle("ortho"));
      const switched = engine.cameraSnapshot();
      expect(switched.projection).toBe(ortho ? "perspective" : "orthographic");
      expect(switched.fit).toBe(fit);
      if (fit) {
        act(() => engine.frame(state.view, state.explode_t > 0));
        expect(engine.cameraSnapshot()).toEqual(switched);
      } else {
        expect(switched.target).toEqual(beforeToggle.target);
        expect(switched.up).toEqual(beforeToggle.up);
        expect(direction(switched).distanceTo(direction(beforeToggle))).toBeLessThan(1e-12);
        act(() => engine.resize(500, 600));
        expect(engine.cameraSnapshot().eye).toEqual(switched.eye);
        expect(engine.cameraSnapshot().scale).toBe(switched.scale);
        expect(engine.cameraSnapshot().fit).toBe(false);
      }
      expect(workspaceStore.getSnapshot()).toEqual(state);
    });
  }
}
