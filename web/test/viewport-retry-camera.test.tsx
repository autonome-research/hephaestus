// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { claimToken, dropToken } from "../src/api/token";
import { Viewport } from "../src/components/stage/viewport/Viewport";
import { startUrlSync, workspaceStore } from "../src/state/react";
import { DEFAULT_STATE } from "../src/state/workspace";
import { fakeGlb } from "./glb";

const engineHarness = vi.hoisted(() => ({
  instance: null as null | {
    camera: { eye: number[]; target: number[]; up: number[]; zoom: number };
    frame: ReturnType<typeof vi.fn>;
    setExplode: ReturnType<typeof vi.fn>;
  },
  loadCalls: 0,
  failLoadCalls: new Set<number>(),
  deferLoadCalls: new Set<number>(),
  deferredLoads: new Map<number, { resolve: () => void; reject: (error: Error) => void }>(),
}));

vi.mock("../src/viewport/engine", () => {
  class NoWebglError extends Error {}
  class ViewportEngine {
    camera = { eye: [0, 0, 10], target: [0, 0, 0], up: [0, 0, 1], zoom: 1 };
    frame = vi.fn((_view: string, _exploded: boolean, options?: { preserveCamera: boolean }) => {
      if (!options?.preserveCamera) {
        this.camera = { eye: [90, 0, 0], target: [0, 0, 0], up: [0, 0, 1], zoom: 1 };
      }
    });
    constructor() { engineHarness.instance = this; }
    load = vi.fn(async (
      _bytes: ArrayBuffer,
      _geometry: unknown,
      ownsLoad: () => boolean = () => true,
    ) => {
      engineHarness.loadCalls += 1;
      const call = engineHarness.loadCalls;
      if (engineHarness.failLoadCalls.has(call)) {
        throw new Error("malformed loader payload");
      }
      if (engineHarness.deferLoadCalls.has(call)) {
        await new Promise<void>((resolve, reject) => {
          engineHarness.deferredLoads.set(call, { resolve, reject });
        });
      }
      return ownsLoad() ? { nodes: [] } : null;
    });
    clear = vi.fn();
    boundsBox = vi.fn(() => ({ min: [-1, -1, -1], max: [1, 1, 1] }));
    setExplode = vi.fn();
    setHidden = vi.fn();
    setAppearance = vi.fn();
    setGridVisible = vi.fn();
    setOrtho = vi.fn();
    setSection = vi.fn();
    resize = vi.fn();
    dispose = vi.fn();
    onFrame = vi.fn(() => () => undefined);
    cameraSnapshot = vi.fn(() => ({
      eye: [...this.camera.eye], target: [...this.camera.target], up: [...this.camera.up],
      zoom: this.camera.zoom, scale: 10, fit: false, projection: "orthographic" as const,
      size: [800, 600],
    }));
  }
  return { NoWebglError, ViewportEngine };
});

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

let mounted: { host: HTMLDivElement; root: Root; client: QueryClient } | null = null;

afterEach(() => {
  if (mounted !== null) {
    act(() => mounted?.root.unmount());
    mounted.client.clear();
    mounted.host.remove();
    mounted = null;
  }
  engineHarness.instance = null;
  engineHarness.loadCalls = 0;
  engineHarness.failLoadCalls.clear();
  engineHarness.deferLoadCalls.clear();
  engineHarness.deferredLoads.clear();
  workspaceStore.reset(DEFAULT_STATE);
  dropToken();
  vi.unstubAllGlobals();
});

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

function mount(): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => root.render(
    <QueryClientProvider client={client}>
      <Viewport />
    </QueryClientProvider>,
  ));
  mounted = { host, root, client };
  return host;
}

describe("Viewport transient GLB retry", () => {
  it("browser setup navigation to +X is camera navigation, not a pin-only change", async () => {
    const priorRef = `artifact:build:sha256:${"0".repeat(64)}`;
    const nextRef = `artifact:build:sha256:${"a".repeat(64)}`;
    vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void {} });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(fakeGlb({ solids: [] }))));
    window.location.hash = "#t=setup-navigation-token";
    claimToken();
    window.history.replaceState(null, "", `#/p/tread?ref=${encodeURIComponent(priorRef)}&pin=pinned&view=az30_el20`);
    const stopSync = startUrlSync();
    try {
      mount(); await settle(); await settle();
      const engine = engineHarness.instance;
      if (engine === null) throw new Error("engine missing");
      engine.frame.mockClear();
      act(() => {
        window.history.pushState(null, "", `#/p/tread?ref=${encodeURIComponent(nextRef)}&pin=pinned&view=%2BX`);
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      // This is the browser spec's pinnedHash(A) operation, BEFORE A loads.
      expect(workspaceStore.getSnapshot().view).toBe("+X");
      expect(engine.frame).toHaveBeenCalledWith("+X", false);
    } finally { stopSync(); }
  });

  for (const action of ["held", "view", "explode"] as const) {
    it(`keeps a later ${action} action while retry parsing is pending`, async () => {
      const firstRef = `artifact:build:sha256:${"0".repeat(64)}`;
      const retryRef = `artifact:build:sha256:${"b".repeat(64)}`;
      const selection = { selection_id: "solid:7", kind: "solid", bundle_ref: "bundle:test" };
      let requests = 0;
      engineHarness.deferLoadCalls.add(2);
      vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void {} });
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes(encodeURIComponent(retryRef)) && ++requests === 1) throw new TypeError("offline");
        return new Response(fakeGlb({ solids: [{ solid_index: 0, label: "fixture" }] }));
      }));
      window.location.hash = "#t=later-camera-token"; claimToken();
      workspaceStore.reset({ ...DEFAULT_STATE, artifact_ref: firstRef, pin_mode: "pinned", selection, focus: "solid:7" });
      const host = mount(); await settle(); await settle();
      const engine = engineHarness.instance;
      if (engine === null) throw new Error("engine missing");
      engine.camera = { eye: [8, -4, 16], target: [1, 2, 3], up: [0, 0, 1], zoom: 1.4 };
      act(() => workspaceStore.hold(retryRef));
      await settle(); await settle();
      const retry = host.querySelector<HTMLButtonElement>("[data-glb-retry]");
      expect(retry).not.toBeNull();
      act(() => retry?.click());
      await settle(); await settle();
      expect(engineHarness.deferredLoads.has(2)).toBe(true);
      act(() => {
        if (action === "view") workspaceStore.update({ view: "+Z" });
        else if (action === "explode") workspaceStore.update({ explode_t: 0.6 });
        else engine.camera = { eye: [41, 23, 17], target: [3, 2, 1], up: [0, 1, 0], zoom: 2.1 };
      });
      const latest = structuredClone(engine.camera);
      const state = workspaceStore.getSnapshot();
      await act(async () => { engineHarness.deferredLoads.get(2)?.resolve(); });
      await settle();
      expect(engine.camera).toEqual(latest);
      expect(engine.frame).toHaveBeenLastCalledWith(state.view, state.explode_t > 0, { preserveCamera: true });
      expect(engine.setExplode).toHaveBeenLastCalledWith(state.explode_t);
      expect(workspaceStore.getSnapshot()).toEqual(state);
      expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-artifact-ref")).toBe(retryRef);
      expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
      expect(document.activeElement).toBe(host.querySelector("[data-viewport-canvas]"));
      expect(requests).toBe(2);
    });
  }

  it("ignores a stale asynchronous loader rejection from artifact A after B is ready", async () => {
    const staleRef = `artifact:build:sha256:${"c".repeat(64)}`;
    const currentRef = `artifact:build:sha256:${"d".repeat(64)}`;
    engineHarness.deferLoadCalls.add(1);
    vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void {} });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      fakeGlb({ solids: [{ solid_index: 0, label: "fixture" }] }),
      { status: 200, headers: { "content-type": "model/gltf-binary" } },
    )));
    window.location.hash = "#t=stale-loader-token";
    claimToken();
    workspaceStore.reset({ ...DEFAULT_STATE, artifact_ref: staleRef, pin_mode: "pinned" });

    const host = mount();
    for (let attempt = 0; attempt < 5 && !engineHarness.deferredLoads.has(1); attempt += 1) await settle();
    expect(engineHarness.deferredLoads.has(1)).toBe(true);
    act(() => workspaceStore.hold(currentRef));
    await settle(); await settle();
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-artifact-ref")).toBe(currentRef);

    await act(async () => {
      engineHarness.deferredLoads.get(1)?.reject(new Error("late malformed A"));
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
    expect(host.querySelector("[data-glb-retry]")).toBeNull();
    expect(workspaceStore.getSnapshot().artifact_ref).toBe(currentRef);
  });

  it("does not let artifact A's loader refusal suppress artifact B's transient retry", async () => {
    const priorRef = `artifact:build:sha256:${"0".repeat(64)}`;
    const malformedRef = `artifact:build:sha256:${"a".repeat(64)}`;
    const retryRef = `artifact:build:sha256:${"b".repeat(64)}`;
    const selection = { selection_id: "solid:7", kind: "solid", bundle_ref: "bundle:test" };
    let retryRequests = 0;
    engineHarness.failLoadCalls.add(2);
    vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void {} });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(encodeURIComponent(retryRef))) {
        retryRequests += 1;
        if (retryRequests === 1) throw new TypeError("transient offline");
      }
      return new Response(fakeGlb({ solids: [{ solid_index: 0, label: "fixture" }] }), {
        status: 200,
        headers: { "content-type": "model/gltf-binary" },
      });
    }));
    window.location.hash = "#t=artifact-owned-loader-token";
    claimToken();
    workspaceStore.reset({
      ...DEFAULT_STATE,
      artifact_ref: priorRef,
      pin_mode: "pinned",
      selection,
      focus: "solid:7",
    });

    const host = mount();
    await settle(); await settle();
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
    const engine = engineHarness.instance;
    if (engine === null) throw new Error("engine missing");
    engine.camera = { eye: [8, -4, 16], target: [1, 2, 3], up: [0, 0, 1], zoom: 1.4 };
    const heldCamera = structuredClone(engine.camera);

    act(() => workspaceStore.hold(malformedRef));
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await settle();
      if (host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state") === "refused") break;
    }
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("refused");
    expect(host.querySelector("[data-glb-retry]")).toBeNull();

    act(() => workspaceStore.hold(retryRef));
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await settle();
      if (host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state") === "refused") break;
    }
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("refused");
    const retry = host.querySelector<HTMLButtonElement>("[data-glb-retry]");
    expect(retry).not.toBeNull();
    retry?.focus();
    act(() => retry?.click());
    expect(document.activeElement).toBe(host.querySelector("[data-viewport-canvas]"));
    await settle(); await settle();

    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
    expect(engine.frame).toHaveBeenLastCalledWith(DEFAULT_STATE.view, false, { preserveCamera: true });
    expect(engine.camera).toEqual(heldCamera);
    expect(workspaceStore.getSnapshot()).toMatchObject({
      artifact_ref: retryRef,
      pin_mode: "pinned",
      selection,
      focus: "solid:7",
    });
    expect(retryRequests).toBe(2);
  });

  it("restores the engine camera and preserves pin, selection and focus", async () => {
    const firstRef = `artifact:build:sha256:${"a".repeat(64)}`;
    const retryRef = `artifact:build:sha256:${"b".repeat(64)}`;
    const selection = {
      selection_id: "solid:7",
      kind: "solid",
      bundle_ref: "artifact:selection-bundle:test",
    };
    let retryRequests = 0;
    vi.stubGlobal("ResizeObserver", class {
      observe(): void {}
      disconnect(): void {}
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(encodeURIComponent(firstRef))) {
        return new Response(fakeGlb({ solids: [{ solid_index: 0, label: "first" }] }), {
          status: 200,
          headers: { "content-type": "model/gltf-binary" },
        });
      }
      if (url.includes(encodeURIComponent(retryRef))) {
        retryRequests += 1;
        if (retryRequests === 1) throw new TypeError("transient offline");
        return new Response(fakeGlb({ solids: [{ solid_index: 1, label: "replacement" }] }), {
          status: 200,
          headers: { "content-type": "model/gltf-binary" },
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));
    window.location.hash = "#t=disposable-viewport-retry-token";
    claimToken();
    workspaceStore.reset({
      ...DEFAULT_STATE,
      artifact_ref: firstRef,
      pin_mode: "pinned",
      view: "+X",
      selection,
      focus: "solid:7",
    });

    const host = mount();
    await settle();
    await settle();
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
    const engine = engineHarness.instance;
    expect(engine).not.toBeNull();
    if (engine === null) return;
    engine.camera = {
      eye: [13, -9, 21], target: [4, 2, -3], up: [0.2, 0.1, 0.97], zoom: 1.8,
    };
    const heldCamera = structuredClone(engine.camera);

    act(() => workspaceStore.hold(retryRef));
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await settle();
      if (host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state") === "refused") break;
    }
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("refused");
    const retry = host.querySelector<HTMLButtonElement>("[data-glb-retry]");
    expect(retry).not.toBeNull();
    retry?.focus();
    act(() => retry?.click());
    expect(document.activeElement).toBe(host.querySelector("[data-viewport-canvas]"));
    await settle();
    await settle();

    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-glb-state")).toBe("ready");
    expect(host.querySelector("[data-testid='viewport']")?.getAttribute("data-artifact-ref")).toBe(retryRef);
    expect(engine.frame.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(engine.frame).toHaveBeenLastCalledWith("+X", false, { preserveCamera: true });
    expect(engine.camera).toEqual(heldCamera);
    expect(workspaceStore.getSnapshot()).toMatchObject({
      artifact_ref: retryRef,
      pin_mode: "pinned",
      selection,
      focus: "solid:7",
    });
    expect(document.activeElement).toBe(host.querySelector("[data-viewport-canvas]"));
    expect(retryRequests).toBe(2);
  });
});
