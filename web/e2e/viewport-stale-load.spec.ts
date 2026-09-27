// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Real Chromium + the production ViewportEngine + three's real GLTFLoader.
// Artifact A blocks inside GLTF parsing on an external texture while artifact B
// fails once, is explicitly retried, and loads. Releasing A afterwards proves
// the engine-side ownership fence (not merely React's promise callback) protects
// B's scene and the retry restores the operator's camera.

import { expect, test, type Page } from "@playwright/test";
import { api, apiBytes, open, refSegment, route } from "./harness/world";
import type { ViewportHandle } from "../src/viewport/testHook";

const PART = "tread";
const A_REF = `artifact:build:sha256:${"a".repeat(64)}`;
const B_REF = `artifact:build:sha256:${"b".repeat(64)}`;
const SELECTION = "solid:7|solid|artifact:selection-bundle:browser-regression";
const FOCUS = "solid:7";
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0EcAAAAASUVORK5CYII=",
  "base64",
);

interface BuildDocument { readonly artifact_ref: string }
interface GlbChunk { readonly type: number; readonly bytes: Uint8Array }

/** Add a texture used by every primitive, preserving the real server BIN chunk. */
function glbWaitingOnTexture(source: Buffer): Buffer {
  const input = new Uint8Array(source);
  const view = new DataView(input.buffer, input.byteOffset, input.byteLength);
  expect(view.getUint32(0, true)).toBe(0x46546c67);
  const chunks: GlbChunk[] = [];
  let document: Record<string, unknown> | null = null;
  for (let offset = 12; offset + 8 <= input.byteLength;) {
    const length = view.getUint32(offset, true);
    const type = view.getUint32(offset + 4, true);
    const bytes = input.slice(offset + 8, offset + 8 + length);
    if (type === 0x4e4f534a) {
      document = JSON.parse(new TextDecoder().decode(bytes).trim()) as Record<string, unknown>;
    } else chunks.push({ type, bytes });
    offset += 8 + length;
  }
  if (document === null) throw new Error("fixture GLB has no JSON chunk");

  document["images"] = [{ uri: "/slow-a.png" }];
  document["textures"] = [{ source: 0 }];
  const materials = Array.isArray(document["materials"])
    ? document["materials"] as Array<Record<string, unknown>>
    : [];
  if (materials.length === 0) materials.push({});
  for (const material of materials) {
    const current = material["pbrMetallicRoughness"];
    material["pbrMetallicRoughness"] = {
      ...(current !== null && typeof current === "object" ? current as Record<string, unknown> : {}),
      baseColorTexture: { index: 0 },
    };
  }
  document["materials"] = materials;
  for (const mesh of document["meshes"] as Array<Record<string, unknown>>) {
    for (const primitive of mesh["primitives"] as Array<Record<string, unknown>>) {
      primitive["material"] = 0;
    }
  }

  const encoded = new TextEncoder().encode(JSON.stringify(document));
  const jsonLength = (encoded.length + 3) & ~3;
  const json = new Uint8Array(jsonLength);
  json.set(encoded);
  json.fill(0x20, encoded.length);
  const outputChunks: GlbChunk[] = [{ type: 0x4e4f534a, bytes: json }, ...chunks];
  const total = 12 + outputChunks.reduce((sum, chunk) => sum + 8 + chunk.bytes.length, 0);
  const output = new Uint8Array(total);
  const header = new DataView(output.buffer);
  header.setUint32(0, 0x46546c67, true);
  header.setUint32(4, 2, true);
  header.setUint32(8, total, true);
  let offset = 12;
  for (const chunk of outputChunks) {
    header.setUint32(offset, chunk.bytes.length, true);
    header.setUint32(offset + 4, chunk.type, true);
    output.set(chunk.bytes, offset + 8);
    offset += 8 + chunk.bytes.length;
  }
  return Buffer.from(output);
}

async function camera(page: Page): Promise<ReturnType<ViewportHandle["camera"]>> {
  return await page.evaluate(() => {
    const handle = (window as unknown as { __hephaestus_viewport__: ViewportHandle })
      .__hephaestus_viewport__;
    return structuredClone(handle.camera());
  });
}

function pinnedHash(ref: string): string {
  return route(PART, {
    ref,
    pin: "pinned",
    view: "+X",
    t: "0",
    ov: "none",
    tab: "viewport",
    itab: "results",
    sel: SELECTION,
    focus: FOCUS,
  });
}

async function navigate(page: Page, hash: string, ref: string): Promise<void> {
  await page.evaluate((next) => {
    window.history.pushState(null, "", next);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, hash);
  await expect.poll(async () => page.evaluate(() => window.location.hash))
    .toContain(`ref=${encodeURIComponent(ref)}`);
}

test("stale real GLTF parse cannot replace B after exact-key retry or move its camera/pin/selection/focus", async ({ page }) => {
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  const real = await apiBytes(`/artifacts/${refSegment(build.artifact_ref)}/gltf`);
  const delayedA = glbWaitingOnTexture(real);
  let bRequests = 0;
  let releaseTexture = (): void => undefined;
  const textureGate = new Promise<void>((resolve) => { releaseTexture = resolve; });
  let sawTexture = (): void => undefined;
  const textureStarted = new Promise<void>((resolve) => { sawTexture = resolve; });
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.route("**/slow-a.png", async (request) => {
    sawTexture();
    await textureGate;
    await request.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 });
  });
  await page.route("**/api/v1/artifacts/**/gltf", async (request) => {
    const path = decodeURIComponent(new URL(request.request().url()).pathname);
    if (path.includes(A_REF)) {
      await request.fulfill({
        status: 200,
        contentType: "model/gltf-binary",
        headers: { "Cache-Control": "no-store" },
        body: delayedA,
      });
      return;
    }
    if (path.includes(B_REF)) {
      bRequests += 1;
      if (bRequests === 1) {
        await request.abort("failed");
        return;
      }
      await request.fulfill({
        status: 200,
        contentType: "model/gltf-binary",
        headers: { "Cache-Control": "no-store" },
        body: real,
      });
      return;
    }
    await request.fallback();
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, pinnedHash(build.artifact_ref));
  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute("data-glb-state", "ready", { timeout: 120_000 });

  // Establish an unmistakably operator-owned free camera before B's failed read.
  const canvas = page.locator("[data-viewport-canvas]");
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("viewport canvas has no box");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down({ button: "left" });
  await page.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2 + 55, { steps: 8 });
  await page.mouse.up({ button: "left" });
  await page.mouse.wheel(0, -140);
  await page.waitForTimeout(500);

  await navigate(page, pinnedHash(A_REF), A_REF);
  await textureStarted;
  // A's bytes are present but its real GLTF parse is still blocked; the scene
  // and its published identity remain the last completed artifact.
  await expect(viewport).toHaveAttribute("data-artifact-ref", build.artifact_ref);

  await navigate(page, pinnedHash(B_REF), B_REF);
  await expect(viewport).toHaveAttribute("data-glb-state", "refused");
  const held = await camera(page);
  const retry = page.locator("[data-glb-retry]");
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(viewport).toHaveAttribute("data-glb-state", "ready", { timeout: 120_000 });
  await expect(viewport).toHaveAttribute("data-artifact-ref", B_REF);
  expect(await camera(page)).toEqual(held);
  expect(bRequests).toBe(2);

  // Let A's already-running production GLTFLoader finish only after B owns the
  // scene. The engine's in-load generation check must turn that result into a
  // no-op: no stale mutation, no stale refusal, and no operator-state damage.
  releaseTexture();
  await page.waitForTimeout(750);
  await expect(viewport).toHaveAttribute("data-glb-state", "ready");
  await expect(viewport).toHaveAttribute("data-artifact-ref", B_REF);
  expect(await camera(page)).toEqual(held);
  expect(browserErrors).toEqual([]);

  const final = new URLSearchParams((await page.evaluate(() => window.location.hash)).split("?")[1]);
  expect(final.get("ref")).toBe(B_REF);
  expect(final.get("pin")).toBe("pinned");
  expect(final.get("sel")).toBe(SELECTION);
  expect(final.get("focus")).toBe(FOCUS);
  await expect(canvas).toBeFocused();
});
