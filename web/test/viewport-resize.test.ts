// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it, vi } from 'vitest';
import { Box3, OrthographicCamera, Vector3 } from 'three';
import type { PerspectiveCamera, Vector2 } from 'three';
import type * as Three from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ViewportEngine } from '../src/viewport/engine';
import { framingFor } from '../src/viewport/scene';
vi.mock('three', async importOriginal => {
  const actual = await importOriginal<typeof Three>();
  return { ...actual, WebGLRenderer: class {
    size = new actual.Vector2(740, 430);
    setClearColor() {} setPixelRatio() {} render() {} dispose() {}
    setSize(x: number, y: number) { this.size.set(x, y); }
    getSize(target: Vector2) { return target.copy(this.size); }
  } };
});
// Test-only inspection of engine internals; no mutable browser hook is shipped.
type Internals = { bounds: Box3; camera: OrthographicCamera | PerspectiveCamera; controls: OrbitControls };
describe('resize preserves camera intent', () => {
  for (const ortho of [true, false]) it(`Fit adapts projection without changing eye/target/up; held pose survives (${ortho})`, () => {
    const canvas = document.createElement('canvas'); document.body.append(canvas);
    const settled = vi.fn(); const engine = new ViewportEngine(canvas, { onCameraSettled: settled });
    const live = engine as unknown as Internals;
    try {
      live.bounds = new Box3(new Vector3(-600, -90, -20), new Vector3(600, 90, 20));
      engine.frame('iso', false); engine.setOrtho(ortho);
      const pose = () => ({ eye: live.camera.position.toArray(), up: live.camera.up.toArray(), target: live.controls.target.toArray() });
      const fitPose = pose();
      for (const width of [740, 616, 664, 483, 664, 740]) {
        engine.resize(width, 430);
        expect(pose()).toEqual(fitPose);
        expect(engine.scale()).toBeCloseTo(framingFor(live.bounds, 'iso', width / 430)!.halfHeight, 8);
      }
      live.controls.dispatchEvent({ type: 'start' });
      live.controls.dispatchEvent({ type: 'end' });
      expect(engine.cameraSnapshot().fit).toBe(true); // click without camera movement
      settled.mockClear();
      live.controls.dispatchEvent({ type: 'start' });
      live.camera.position.add(new Vector3(22, -18, 10));
      live.controls.target.add(new Vector3(12, 6, -8));
      if (live.camera instanceof OrthographicCamera) live.camera.zoom = 1.7;
      else live.camera.fov *= 0.75;
      live.controls.update(); live.controls.dispatchEvent({ type: 'end' });
      expect(settled).toHaveBeenCalledOnce();
      const held = pose(); const scale = engine.scale(); const zoom = live.camera.zoom;
      for (const width of [740, 616, 664, 483, 664, 740]) {
        engine.resize(width, 350);
        expect(pose()).toEqual(held); expect(live.camera.zoom).toBe(zoom); expect(engine.scale()).toBeCloseTo(scale, 8);
      }
      expect(settled).toHaveBeenCalledOnce(); // resize is not a viewpoint/navigation write
      engine.frame('iso', false); engine.resize(483, 430);
      expect(engine.scale()).toBeCloseTo(framingFor(live.bounds, 'iso', 483 / 430)!.halfHeight, 8);
    } finally { engine.dispose(); canvas.remove(); }
  });
});
