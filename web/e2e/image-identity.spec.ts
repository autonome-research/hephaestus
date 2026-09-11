// Packaged real CAD/sidecar/browser proof in a separate owned fake-provider world.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect } from "@playwright/test";
import { test } from "./harness/geometryHealth";
import type { SessionModelDocument } from "../src/api/sessions";
import { startSolProvider } from "./harness/sol_provider";
import type { ImageIdentity } from "../src/api/events";

for (const sol of [false, true]) test(`packaged ${sol ? "pinned Sol Codex" : "generic"} images retain artifact identity live and after reload; text-only refuses truthfully`, async ({ page }, testInfo) => {
  const scratch = testInfo.outputPath("image-world");
  mkdirSync(scratch, { recursive: true });
  const codex = sol ? await startSolProvider(scratch) : null;
  const child = spawn(resolve("../.venv/bin/python"), [resolve("e2e/harness/image_world.py"), scratch, ...(codex ? [codex.endpoint] : [])], { cwd: resolve(".."), stdio: ["ignore", "inherit", "inherit"] });
  try {
    await expect.poll(() => {
      if (child.exitCode !== null) throw Error(`image world exited ${child.exitCode}`);
      return existsSync(`${scratch}/ready.json`);
    }, { timeout: 180_000, message: "owned image world ready" }).toBe(true);
    const world = JSON.parse(readFileSync(`${scratch}/ready.json`, "utf8")) as { base_url: string; token: string; provider: string; image_provider: string; image_model: string; text_model: string };
    async function request(path: string, init?: RequestInit) {
      const response = await fetch(`${world.base_url}/api/v1${path}`, { ...init, headers: { "Content-Type": "application/json", Authorization: `Bearer ${world.token}`, Connection: "close" } });
      expect(response.ok, `${path}: ${response.status}`).toBe(true);
      return response;
    }
    const external: string[] = [];
    await page.context().route("**/*", async route => {
      const url = new URL(route.request().url());
      if (url.origin !== world.base_url) { external.push(url.origin); await route.abort(); }
      else await route.continue();
    });
    await page.goto(`${world.base_url}/#t=${world.token}`);
    for (const model of [world.text_model, world.image_model]) {
      const created = await (await request("/sessions", { method: "POST", body: JSON.stringify({ profile: "orchestrator", model: { provider_id: model === world.image_model ? world.image_provider : world.provider, model_id: model } }) })).json() as SessionModelDocument;
      const sid = created.session_id;
      expect(created.model_state.current?.model_id).toBe(model);
      if (sol && model === world.image_model) {
        expect(created.model_state.current).toMatchObject({ provider_id: "openai-codex", model_id: "gpt-5.6-sol", input: ["text", "image"] });
      }
      await page.goto(`${world.base_url}/#/p/tread?s=${sid}`);
      const composer = page.locator(`[data-composer][data-session-id="${sid}"]`);
      const send = composer.locator("[data-composer-send]");
      await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute("data-stream", "live");
      await composer.locator("[data-composer-input]").fill("Owned image transport identity probe; no visual assessment claim.");
      const done = page.waitForResponse(response => response.url().endsWith(`/sessions/${sid}/prompt`) && response.request().method() === "POST");
      await send.click();
      expect((await (await done).json() as { run_status: string }).run_status).toBe("completed");
      const images = page.locator('[data-image-state="shown"]');
      if (model === world.text_model) {
        await expect(images).toHaveCount(0);
        const result = page.locator('[data-tool-name="inspect_part"]');
        await result.locator("summary").first().click();
        await expect(result).toContainText("image_model_required");
        await expect(result).toContainText("automatic routing");
        await expect(result).not.toContainText("no vision model is configured");
      } else {
        await page.locator('[data-tool-name="inspect_part"] summary').first().click();
        await expect(images).toHaveCount(2);
        await expect(images.first()).toBeVisible();
        const refs: string[] = [];
        for (const [index, view] of ["iso", "+X"].entries()) {
          const image = images.nth(index);
          await expect(image).toHaveAttribute("data-image-identity", "recorded");
          await expect(image).toContainText(`tread · ${view} / rgb`);
          await expect(image).toContainText("Requested part: tread");
          const ref = await image.getAttribute("data-render-ref");
          expect(ref).toMatch(/^artifact:render:sha256:[a-f0-9]{64}$/);
          refs.push(ref!);
          const bytes = Buffer.from(await (await request(`/artifacts/${encodeURIComponent(ref!)}/bytes`)).arrayBuffer());
          expect(`artifact:render:sha256:${createHash("sha256").update(bytes).digest("hex")}`).toBe(ref);
          const src = await image.locator("img").getAttribute("src");
          expect(Buffer.from(src!.split(",")[1]!, "base64")).toEqual(bytes);
          if (codex) expect(codex.requests[1]?.images[index]?.render_artifact_ref).toBe(ref);
          await expect.poll(() => image.locator("img").evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(960);
        }
        expect(new Set(refs).size).toBe(2);
        for (const width of [1440, 843]) {
          await page.setViewportSize({ width, height: 900 });
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          expect(page.url()).not.toContain(world.token);
          await images.last().scrollIntoViewIfNeeded();
          await expect(images.last().locator("figcaption")).toBeVisible();
          const caption = await images.last().locator("figcaption").evaluate(element => {
            const first = element.firstElementChild!;
            return { direction: getComputedStyle(element).flexDirection, firstHeight: first.getBoundingClientRect().height, lineHeight: Number.parseFloat(getComputedStyle(first).lineHeight) };
          });
          expect(caption.direction).toBe("column");
          // This short fixture's operand/view must fit on one line at both widths.
          expect(caption.firstHeight).toBeLessThanOrEqual(caption.lineHeight + 1);
          await page.screenshot({ path: testInfo.outputPath(`image-${width}.png`) });
        }
        await page.reload();
        const archived = page.locator('[data-image-state="metadata_only"]');
        await expect(archived).toHaveCount(2);
        for (let index = 0; index < 2; index++) {
          await expect(archived.nth(index)).toHaveAttribute("data-render-ref", refs[index]!);
          await expect(archived.nth(index).locator("img")).toHaveCount(0);
        }
      }
    }
    const observed = readFileSync(`${scratch}/observations.jsonl`, "utf8").trim().split("\n").map(line => JSON.parse(line) as { model: string; refusal: string | null; images: (ImageIdentity & { sha256: string })[] });
    expect(observed.map(row => row.model)).toEqual(sol ? [world.text_model, world.text_model] : [world.text_model, world.text_model, world.image_model, world.image_model]);
    expect(observed[1]?.refusal).toBe("image_model_required");
    expect(observed[1]?.images).toHaveLength(0);
    const proof = codex ? codex.requests[1] : observed[3];
    expect(proof?.images.map(image => image.view)).toEqual(["iso", "+X"]);
    for (const image of proof!.images) expect(image.render_artifact_ref).toBe(`artifact:render:sha256:${image.sha256}`);
    if (codex) {
      expect(codex.requests).toHaveLength(2);
      expect(codex.requests.map(row => row.model)).toEqual(["gpt-5.6-sol", "gpt-5.6-sol"]);
      expect(codex.failures).toEqual([]);
    }
    expect(external).toEqual([]);
    const network = readFileSync(`${scratch}/network.jsonl`, "utf8");
    expect(network).toContain("guard_loaded");
    expect(network).not.toContain("denied_");
    if (sol) expect(network.match(/codex_http_redirect/g)).toHaveLength(2);
  } finally {
    try {
      child.kill("SIGTERM");
      await expect.poll(() => child.exitCode, { timeout: 40_000, message: "owned image world shutdown" }).not.toBeNull();
      expect(child.exitCode).toBe(0);
    } finally { await codex?.close(); }
  }
});

test("pinned Sol missing current build remains a tool failure with zero images", async ({ page }, testInfo) => {
  const scratch = testInfo.outputPath("missing-build-world");
  mkdirSync(scratch, { recursive: true });
  const codex = await startSolProvider(scratch, true);
  const child = spawn(resolve("../.venv/bin/python"), [resolve("e2e/harness/image_world.py"), scratch, codex.endpoint], { cwd: resolve(".."), stdio: ["ignore", "inherit", "inherit"] });
  try {
    await expect.poll(() => {
      if (child.exitCode !== null) throw Error(`missing-build world exited ${child.exitCode}`);
      return existsSync(`${scratch}/ready.json`);
    }, { timeout: 180_000 }).toBe(true);
    const world = JSON.parse(readFileSync(`${scratch}/ready.json`, "utf8")) as { base_url: string; token: string };
    const response = await fetch(`${world.base_url}/api/v1/sessions`, { method: "POST", headers: { Authorization: `Bearer ${world.token}`, "Content-Type": "application/json", Connection: "close" }, body: JSON.stringify({ profile: "orchestrator", model: { provider_id: "openai-codex", model_id: "gpt-5.6-sol" } }) });
    expect(response.ok).toBe(true);
    const created = await response.json() as SessionModelDocument;
    expect(created.model_state.current).toMatchObject({ provider_id: "openai-codex", model_id: "gpt-5.6-sol", input: ["text", "image"] });
    const external: string[] = [];
    await page.context().route("**/*", async route => {
      if (new URL(route.request().url()).origin !== world.base_url) { external.push("non-fixture request"); await route.abort(); }
      else await route.continue();
    });
    await page.goto(`${world.base_url}/#t=${world.token}`);
    await page.goto(`${world.base_url}/#/p/riser?s=${created.session_id}`);
    await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute("data-stream", "live");
    const composer = page.locator(`[data-composer][data-session-id="${created.session_id}"]`);
    await composer.locator("[data-composer-input]").fill("Owned missing-build image probe.");
    const done = page.waitForResponse(r => r.url().endsWith(`/sessions/${created.session_id}/prompt`) && r.request().method() === "POST");
    await composer.locator("[data-composer-send]").click();
    expect((await (await done).json() as { run_status: string }).run_status).toBe("completed");
    await expect(page.locator('[data-tool-name="inspect_part"]')).toHaveAttribute("data-status", "error");
    await expect(page.locator("[data-image-state]")).toHaveCount(0);
    expect(codex.requests).toHaveLength(2);
    expect(codex.requests[1]?.images).toHaveLength(0);
    expect(codex.requests[1]?.output_text).toMatch(/build|artifact|not_found/);
    expect(external).toEqual([]);
    expect(readFileSync(`${scratch}/network.jsonl`, "utf8")).not.toContain("denied_");
  } finally {
    try {
      child.kill("SIGTERM");
      await expect.poll(() => child.exitCode, { timeout: 40_000 }).not.toBeNull();
      expect(child.exitCode).toBe(0);
    } finally { await codex.close(); }
  }
});
