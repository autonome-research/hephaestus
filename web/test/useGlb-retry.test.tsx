// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cameraPoseStore } from "../src/state/cameraPose";
import { workspaceStore } from "../src/state/react";
import { DEFAULT_STATE } from "../src/state/workspace";
import { claimToken, dropToken } from "../src/api/token";
import { glbKey, useGlb } from "../src/viewport/useGlb";
import { fakeGlb } from "./glb";

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

let mounted: { host: HTMLDivElement; root: Root; client: QueryClient } | null = null;
const INITIAL_CAMERA_POSE = cameraPoseStore.getSnapshot();

afterEach(() => {
  if (mounted !== null) {
    act(() => mounted?.root.unmount());
    mounted.client.clear();
    mounted.host.remove();
    mounted = null;
  }
  workspaceStore.reset(DEFAULT_STATE);
  cameraPoseStore.set(INITIAL_CAMERA_POSE);
  dropToken();
  vi.unstubAllGlobals();
});

function Probe({ artifactRef }: { readonly artifactRef: string }): React.JSX.Element {
  const glb = useGlb(artifactRef);
  return (
    <div data-state={glb.isError ? "failed" : glb.data === undefined ? "loading" : "ready"}>
      {glb.isError ? (
        <button type="button" data-retry="" onClick={glb.retryGlb}>Retry</button>
      ) : null}
      <span data-requested-ref="">{glb.data?.requested_ref}</span>
    </div>
  );
}

function mount(artifactRef: string): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => root.render(
    <QueryClientProvider client={client}>
      <Probe artifactRef={artifactRef} />
    </QueryClientProvider>,
  ));
  mounted = { host, root, client };
  return host;
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

async function awaitState(host: HTMLElement, expected: "failed" | "ready"): Promise<void> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await settle();
    if (host.firstElementChild?.getAttribute("data-state") === expected) return;
  }
  expect(host.firstElementChild?.getAttribute("data-state")).toBe(expected);
}

describe("useGlb explicit retry", () => {
  it("recovers a transient first fetch for the same ref without changing pin or camera", async () => {
    const artifactRef = `artifact:build:sha256:${"c".repeat(64)}`;
    const bytes = fakeGlb({ solids: [{ solid_index: 0, label: "body" }] });
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(new Response(bytes, {
        status: 200,
        headers: {
          "content-type": "model/gltf-binary",
          "X-Hephaestus-Selection-Bundle": "artifact:selection-bundle:test",
          "X-Hephaestus-Source-Artifact": artifactRef,
        },
      }));
    vi.stubGlobal("fetch", fetchMock);
    window.location.hash = "#t=disposable-glb-test-token";
    claimToken();
    workspaceStore.reset({ ...DEFAULT_STATE, artifact_ref: artifactRef, pin_mode: "pinned", view: "+X" });
    cameraPoseStore.set({ azimuth_deg: 17, elevation_deg: 23 });
    const beforePose = cameraPoseStore.getSnapshot();

    const host = mount(artifactRef);
    await awaitState(host, "failed");
    // The mounted immutable query retains its settled refusal until the
    // explicit retry boundary resets exactly this artifact key.
    expect(mounted?.client.getQueryState(glbKey(artifactRef))?.status).toBe("error");
    act(() => host.querySelector<HTMLButtonElement>("[data-retry]")?.click());
    await awaitState(host, "ready");

    expect(mounted?.client.getQueryState(glbKey(artifactRef))?.status).toBe("success");
    expect(host.querySelector("[data-requested-ref]")?.textContent).toBe(artifactRef);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      `/api/v1/artifacts/${encodeURIComponent(artifactRef)}/gltf`,
      `/api/v1/artifacts/${encodeURIComponent(artifactRef)}/gltf`,
    ]);
    expect(workspaceStore.getSnapshot()).toMatchObject({
      artifact_ref: artifactRef,
      pin_mode: "pinned",
      view: "+X",
    });
    expect(cameraPoseStore.getSnapshot()).toEqual(beforePose);
  });
});
