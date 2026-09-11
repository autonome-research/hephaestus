// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Packaged tests must not pass on a mounted canvas concealing a GLTF 500.
import { expect, test as base, type Page } from "@playwright/test";

interface GeometryResponse {
  readonly requested: string;
  readonly status: number;
  readonly source: string | undefined;
  readonly bundle: string | undefined;
}
const responses = new WeakMap<Page, GeometryResponse[]>();

export const test = base.extend({
  page: async ({ page }, runTest, info) => {
    const geometry: GeometryResponse[] = [];
    const errors: string[] = [];
    responses.set(page, geometry);
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      const path = new URL(response.url()).pathname;
      const match = /^\/api\/v1\/artifacts\/([^/]+)\/gltf$/.exec(path);
      if (match === null) return;
      const headers = response.headers();
      geometry.push({ requested: decodeURIComponent(match[1]!), status: response.status(),
        source: headers["x-hephaestus-source-artifact"], bundle: headers["x-hephaestus-selection-bundle"] });
      // No allowlist for internal errors; explicit 4xx geometry refusal cases
      // remain legal. Throw at the response edge, not a later screenshot poll.
      expect(response.status(), `unexpected GLTF failure: ${path}`).toBeLessThan(500);
    });
    try { await runTest(page); }
    finally {
      await info.attach("geometry-runtime", { contentType: "application/json", body: JSON.stringify({ geometry, errors }) });
      expect(geometry.filter(response => response.status >= 500)).toEqual([]);
      expect(errors, "unhandled packaged browser errors").toEqual([]);
      responses.delete(page);
    }
  },
});

/** Positive built/pinned scenarios: real scene solids AND server provenance. */
export async function expectReadyGeometry(page: Page, source: string): Promise<void> {
  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute("data-glb-state", "ready", { timeout: 120_000 });
  await expect(viewport).toHaveAttribute("data-artifact-ref", source);
  await expect(viewport).not.toContainText("Geometry refused");
  await expect(viewport).not.toContainText("internal_error");
  await expect.poll(async () => await page.evaluate(expected => {
    const handle = (window as unknown as { __hephaestus_viewport__?: {
      artifact_ref: string | null; solids(): { visible: boolean; centroid: unknown }[];
    } }).__hephaestus_viewport__;
    return handle?.artifact_ref === expected
      ? handle.solids().filter(solid => solid.visible && solid.centroid !== null).length : 0;
  }, source), { timeout: 60_000 }).toBeGreaterThan(0);
  const served = responses.get(page)?.slice().reverse().find(response => response.requested === source);
  expect(served, "the browser must have loaded the pinned source's real GLTF response").toBeDefined();
  expect(served?.status).toBe(200);
  expect(served?.source).toBe(source);
  expect(served?.bundle).toMatch(/^artifact:selection-bundle:sha256:[a-f0-9]{64}$/);
}
