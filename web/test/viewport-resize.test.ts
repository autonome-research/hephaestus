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
      const target0 = new Vector3(...fitPose.target);
      const dir0 = new Vector3(...fitPose.eye).sub(target0).normalize();
      for (const width of [740, 616, 664, 483, 664, 740]) {
        engine.resize(width, 430);
        const half = framingFor(live.bounds, 'iso', width / 430)!.halfHeight;
        if (ortho) {
          // The orthographic camera never moves to fit: only its extents do.
          expect(pose()).toEqual(fitPose);
          expect(engine.scale()).toBeCloseTo(half, 8);
        } else {
          // A FIXED LENS fits by MOVING (2026-09-20). Requiring the eye to
          // hold still under perspective is requiring the fov to change, and
          // solving for a fov that matched the ortho half-height is exactly
          // what magnified the near half of the model off the canvas. What
          // still holds — and is what this case is protecting — is that the
          // view DIRECTION, the target and the up are the framing's.
          expect(pose().target).toEqual(fitPose.target);
          expect(pose().up).toEqual(fitPose.up);
          const dir = new Vector3(...pose().eye).sub(target0).normalize();
          expect(dir.x).toBeCloseTo(dir0.x, 9);
          expect(dir.y).toBeCloseTo(dir0.y, 9);
          expect(dir.z).toBeCloseTo(dir0.z, 9);
          // Stepping back to clear the bounding circle shows MORE than the
          // orthographic half-height, never less.
          expect(engine.scale()).toBeGreaterThanOrEqual(half);
        }
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
      const refit = framingFor(live.bounds, 'iso', 483 / 430)!.halfHeight;
      // Orthographic re-fit lands exactly on the framing's half-height.
      // Perspective steps back far enough to clear the bounding CIRCLE, so it
      // necessarily shows more than the rectangle's half-height — that extra
      // is the fit, not a drift.
      if (ortho) expect(engine.scale()).toBeCloseTo(refit, 8);
      else expect(engine.scale()).toBeGreaterThanOrEqual(refit);
    } finally { engine.dispose(); canvas.remove(); }
  });
});

/*
 * §5.5's projection toggle, and the size it must not change.
 *
 * "Toggling the projection must not steal an orbit" is the engine's rule, and
 * for an ORBITED camera it is the whole rule. For a camera still on its
 * framing it was implemented as a conversion — a fov and a distance into a
 * half-height — which preserved the pose and changed the SIZE, because the
 * perspective fit steps back far enough to clear the bounding CIRCLE while the
 * orthographic one fits the rectangle. The part came out smaller than
 * `heph render` draws it, which is the join G4.5 measures across.
 */
describe("the projection toggle", () => {
  type Live = { bounds: Box3; camera: OrthographicCamera | PerspectiveCamera; controls: OrbitControls };

  it("re-frames a camera that is still on its framing, and holds an orbited one", () => {
    const canvas = document.createElement("canvas"); document.body.append(canvas);
    const engine = new ViewportEngine(canvas, { onCameraSettled: () => undefined });
    const live = engine as unknown as Live;
    try {
      live.bounds = new Box3(new Vector3(-600, -90, -20), new Vector3(600, 90, 20));
      engine.resize(740, 430);
      engine.setOrtho(false);
      engine.frame("iso", false);
      expect(engine.cameraSnapshot().fit).toBe(true);

      // Still fitted: the orthographic camera lands on the framing's own
      // half-height rather than on a half-height read off the fixed lens.
      engine.setOrtho(true);
      const half = framingFor(live.bounds, "iso", 740 / 430)!.halfHeight;
      expect(engine.scale()).toBeCloseTo(half, 8);
      expect(engine.cameraSnapshot().fit).toBe(true);

      // Orbited: the pose is the operator's and the toggle leaves it alone.
      live.controls.dispatchEvent({ type: "start" });
      live.camera.position.add(new Vector3(31, -17, 9));
      live.controls.update();
      live.controls.dispatchEvent({ type: "end" });
      expect(engine.cameraSnapshot().fit).toBe(false);
      const held = live.camera.position.toArray();
      engine.setOrtho(false);
      const after = new Vector3(...live.camera.position.toArray());
      const target = live.controls.target;
      const before = new Vector3(...held).sub(target).normalize();
      const now = after.clone().sub(target).normalize();
      expect(now.x).toBeCloseTo(before.x, 9);
      expect(now.y).toBeCloseTo(before.y, 9);
      expect(now.z).toBeCloseTo(before.z, 9);
      expect(engine.cameraSnapshot().fit).toBe(false);
    } finally { engine.dispose(); canvas.remove(); }
  });
});
