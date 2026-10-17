// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Standalone local-milestone collector: real installed native Chrome, real API.
// No Gate G4 provider/global-setup, request mocks, or golden rebaseline.
/* global window, fetch, crypto */
import process from 'node:process';
import { Buffer } from 'node:buffer';
import { URL } from 'node:url';
import { once } from 'node:events';
import { chromium, expect } from '@playwright/test';
import { readFileSync, writeFileSync, openSync, fsyncSync, closeSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

const [readyPath, directory] = process.argv.slice(2);
const ready = JSON.parse(readFileSync(readyPath, 'utf8'));
const token = readFileSync(ready.token_path, 'utf8').trim();
const origin = ready.http;
const report = { passed: false, cleanup_passed: false, http: [], page_errors: [] };
const sha = data => createHash('sha256').update(data).digest('hex');
const save = (name, value) => writeFileSync(join(directory, name), JSON.stringify(value, null, 2));
let server, browser, context;
let interrupted = false;
function owned(value) {
  const temporary = join(directory, 'browser-owner.next');
  writeFileSync(temporary, JSON.stringify(value));
  const file = openSync(temporary, 'r');
  try { fsyncSync(file); } finally { closeSync(file); }
  renameSync(temporary, join(directory, 'browser-owner.json'));
  const dir = openSync(directory, 'r');
  try { fsyncSync(dir); } finally { closeSync(dir); }
}
const stop = () => {
  interrupted = true;
  // Do not disappear like a Docker attach client: close the actual owned browser.
  // If launch is still pending, its bounded completion immediately enters finally.
  void server?.close().catch(() => { report.cleanup_error = 'signal close failed'; });
};
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
owned({ launch_pending: true, pid: null, closed: false });
let bytesSaved = 0;
function archive(name, bytes) {
  bytesSaved += bytes.length;
  if (bytesSaved > 24 * 1024 * 1024) throw new Error('browser evidence byte bound');
  writeFileSync(join(directory, name), bytes);
}
try {
  server = await chromium.launchServer({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true, host: '127.0.0.1', timeout: 30000,
    args: ['--disable-background-networking', '--disable-component-update'],
  });
  report.browser_pid = server.process().pid;
  owned({ launch_pending: false, pid: report.browser_pid, closed: false });
  if (process.argv[4] === '--interrupt-control') {
    const delivered = once(process, 'SIGTERM');
    process.kill(process.pid, 'SIGTERM');
    await delivered;
    throw new Error('intentional browser interruption control');
  }
  if (interrupted) throw new Error('interrupted during native browser launch');
  browser = await chromium.connect(server.wsEndpoint());
  report.browser_version = browser.version();
  context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  context.setDefaultTimeout(120000);
  const page = await context.newPage();
  page.on('pageerror', error => report.page_errors.push(String(error).replaceAll(token, '[redacted]')));
  page.on('response', response => {
    const url = new URL(response.url());
    if (url.origin !== origin && url.protocol !== 'blob:' && url.protocol !== 'data:') {
      report.page_errors.push('unexpected external response: ' + url.origin);
    }
    if (url.origin === origin) {
      if (report.http.length >= 256) throw new Error('HTTP evidence count bound');
      report.http.push({ path: url.pathname, status: response.status() });
    }
  });
  const api = async (path, body, authorized = true, extraHeaders = {}) => {
    const response = await context.request.fetch(origin + '/api/v1' + path, {
      method: body === undefined ? 'GET' : 'POST', timeout: 120000,
      headers: { ...(authorized ? { Authorization: 'Bearer ' + token } : {}), 'Content-Type': 'application/json', ...extraHeaders },
      ...(body === undefined ? {} : { data: body }),
    });
    const bytes = await response.body();
    if (bytes.length > 8 * 1024 * 1024) throw new Error('HTTP body bound');
    return { response, bytes };
  };
  const denied = await api('/project', undefined, false);
  expect(denied.response.status()).toBe(401);
  report.unauthenticated_status = denied.response.status();
  const project = await api('/project');
  expect(project.response.status()).toBe(200);
  report.project = JSON.parse(project.bytes);
  expect(report.project.capabilities.secure_executor).toBe(true);
  // Build through the actual serve-mode dispatcher and explicitly bounded backend.
  const keyBytes = Buffer.alloc(16);
  crypto.getRandomValues(keyBytes);
  keyBytes.writeUIntBE(Date.now(), 0, 6);
  keyBytes[6] = (keyBytes[6] & 15) | 112;
  keyBytes[8] = (keyBytes[8] & 63) | 128;
  const hex = keyBytes.toString('hex');
  const key = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  const rebuilt = await api('/parts/two_solids/build', {}, true, { 'Idempotency-Key': key });
  expect(rebuilt.response.status()).toBe(200);
  report.workspace_build = JSON.parse(rebuilt.bytes);
  expect(report.workspace_build.status).toBe('ok');
  expect(report.workspace_build.current).toBe(true);
  const built = await api('/parts/two_solids/build');
  expect(built.response.status()).toBe(200);
  const build = JSON.parse(built.bytes);
  report.build = build;
  expect(build.metrics.solids).toBe(2);
  expect(build.metrics.volume_mm3).toBeCloseTo(162, 8);
  const ref = build.artifact_ref;
  await page.goto(origin + '/#t=' + token);
  await expect(page.locator('[data-testid="no-token"]')).toHaveCount(0);
  await page.goto(origin + '/#/p/two_solids?tab=viewport&itab=results&t=0&view=iso');
  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute('data-glb-state', 'ready', { timeout: 180000 });
  await expect(viewport).toHaveAttribute('data-artifact-ref', ref);
  expect(page.url()).not.toContain(token);
  expect(await page.locator('body').innerText()).not.toContain(token);
  const solids = await page.evaluate(() => window.__hephaestus_viewport__.solids());
  expect(solids).toHaveLength(2);
  expect(new Set(solids.map(s => s.mesh_index)).size).toBe(2);
  report.scene = solids;
  const glb = await api('/artifacts/' + encodeURIComponent(ref) + '/gltf');
  expect(glb.response.status()).toBe(200);
  const bundle = glb.response.headers()['x-hephaestus-selection-bundle'];
  expect(glb.response.headers()['x-hephaestus-source-artifact']).toBe(ref);
  const gltf = JSON.parse(glb.bytes.subarray(20, 20 + glb.bytes.readUInt32LE(12)).toString('utf8').trim());
  expect(gltf.meshes).toHaveLength(2);
  expect(gltf.asset.extras.selection_bundle_ref).toBe(bundle);
  archive('browser.glb', glb.bytes);
  report.glb = { sha256: sha(glb.bytes), bytes: glb.bytes.length, bundle, source: ref };
  // Read-only actual scene raycast; no synthetic hit, injected geometry or mask.
  // The HINT is mapped through actual GLB bytes by this harness, then resolved
  // by the existing authenticated context endpoint, never trusted as provenance.
  const hit = await page.evaluate(() => {
    const handle = window.__hephaestus_viewport__;
    for (let y = -.8; y <= .8; y += .1) {
      for (let x = -.8; x <= .8; x += .1) {
        const hint = handle.raycast(x, y);
        if (hint) return { ...hint, x, y };
      }
    }
    return null;
  });
  expect(hit).not.toBeNull();
  const canvas = await page.locator('[data-viewport-canvas]').boundingBox();
  await page.mouse.click(canvas.x + (hit.x + 1) * canvas.width / 2,
                         canvas.y + (1 - hit.y) * canvas.height / 2);
  const id = gltf.meshes[hit.mesh_index].primitives[hit.primitive_index].extras.selection_id;
  const selection = { artifact_ref: ref, selection: { bundle_ref: bundle, selection_id: String(id) } };
  const resolved = await api('/context/preview', { context: selection });
  expect(resolved.response.status()).toBe(200);
  const answer = JSON.parse(resolved.bytes);
  expect(answer.block).toContain('selection ' + id + ': a face on solid ');
  expect(answer.block).toContain(ref);
  const stale = await api('/context/preview', { context: {
    ...selection, selection: { bundle_ref: bundle, selection_id: '999999' },
  } });
  expect(stale.response.status()).toBe(409);
  report.pick = { hint: hit, selection_id: id, resolution: answer, rejected_unknown: JSON.parse(stale.bytes) };
  archive('viewport.png', await page.screenshot());
  // Actual operator section controls, then exact stored server bytes.
  await page.goto(origin + '/#/p/two_solids?tab=viewport&itab=results&t=0&view=%2BZ');
  await expect(viewport).toHaveAttribute('data-glb-state', 'ready');
  const disclose = page.locator('[data-section-disclose]');
  if (await disclose.count()) await disclose.click();
  await page.getByTestId('section-enable').click();
  await expect(viewport).toHaveAttribute('data-section-state', 'preview');
  if (await disclose.count()) await disclose.click();
  const sectionResponse = page.waitForResponse(r => r.url().endsWith('/parts/two_solids/inspect') && r.request().method() === 'POST', { timeout: 180000 });
  await page.getByTestId('section-render').click();
  const section = await sectionResponse;
  expect(section.status()).toBe(200);
  const sectionDoc = await section.json();
  expect(sectionDoc.status).toBe('ok');
  expect(sectionDoc.source_artifact_ref).toBe(ref);
  await expect(page.locator('[data-section-plate]')).toHaveAttribute('data-section-plate', 'rendered', { timeout: 180000 });
  const plateRef = await page.locator('[data-section-plate]').getAttribute('data-plate-ref');
  expect(sectionDoc.render_artifact_refs).toContain(plateRef);
  const plate = await api('/artifacts/' + encodeURIComponent(plateRef) + '/bytes');
  expect(plate.response.status()).toBe(200);
  expect(plate.bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  const displayed = await page.locator('[data-section-plate] img').evaluate(async img => {
    await img.decode();
    const bytes = await (await fetch(img.src)).arrayBuffer();
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return { sha256: Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, '0')).join(''), width: img.naturalWidth, height: img.naturalHeight };
  });
  expect(displayed).toEqual({ sha256: sha(plate.bytes), width: 320, height: 240 });
  archive('section.png', plate.bytes);
  archive('section-workspace.png', await page.screenshot());
  report.section = { ref: plateRef, source: ref, displayed, inspection: sectionDoc };
  expect(report.page_errors).toEqual([]);
  report.passed = !interrupted;
} catch (error) {
  report.error = String(error).replaceAll(token, '[redacted]');
} finally {
  try {
    await context?.close();
    await browser?.close();
    await server?.close();
    report.browser_exit = server ? { code: server.process().exitCode, signal: server.process().signalCode } : null;
    report.cleanup_passed = !!server && (server.process().exitCode !== null || server.process().signalCode !== null);
    if (!report.cleanup_passed) {
      report.cleanup_error = 'browser process not reaped or launch evidence missing';
      report.passed = false;
    }
  } catch (error) {
    report.cleanup_error = String(error).replaceAll(token, '[redacted]');
    report.passed = false;
  }
  if (report.cleanup_passed) owned({ launch_pending: false, pid: report.browser_pid, closed: true });
  report.interrupted = interrupted;
  save('browser.json', report);
}
process.exitCode = report.passed && report.cleanup_passed ? 0 : 1;
