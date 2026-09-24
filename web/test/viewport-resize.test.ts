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

type CameraFrame = { right: Vector3; up: Vector3; away: Vector3 };
function cameraFrame(live: Internals): CameraFrame {
  live.camera.updateMatrixWorld(true);
  const right = new Vector3(); const up = new Vector3(); const away = new Vector3();
  live.camera.matrixWorld.extractBasis(right, up, away);
  return { right: right.normalize(), up: up.normalize(), away: away.normalize() };
}

function mousePointer(type: "pointerdown" | "pointermove" | "pointerup", x: number, y: number, shiftKey = false): MouseEvent {
  const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: y, shiftKey });
  Object.defineProperties(event, { pointerId: { value: 1 }, pointerType: { value: "mouse" } });
  return event;
}
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

describe("ordinary axis drag", () => {
  for (const view of ["iso", "+Z"]) for (const ortho of [true, false]) {
    it(`orbits on the screen axes, keeps Shift pan/Fit, and settles (${view}, ${ortho ? "ortho" : "perspective"})`, () => {
      const frames: FrameRequestCallback[] = [];
      vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.push(callback); return frames.length; });
      vi.stubGlobal("cancelAnimationFrame", () => undefined);
      const drain = () => {
        for (let count = 0; frames.length > 0 && count < 200; count += 1) frames.shift()!(count * 16);
        expect(frames, "camera animation did not settle").toHaveLength(0);
      };

      const canvas = document.createElement("canvas"); document.body.append(canvas);
      Object.defineProperty(canvas, "clientHeight", { value: 600 });
      Object.defineProperty(canvas, "clientWidth", { value: 800 });
      Object.assign(canvas, { setPointerCapture: () => undefined, releasePointerCapture: () => undefined });
      const settled = vi.fn(); const engine = new ViewportEngine(canvas, { onCameraSettled: settled });
      const live = engine as unknown as Internals;
      live.bounds = new Box3(new Vector3(-60, -25, -10), new Vector3(60, 25, 10));
      engine.resize(800, 600); engine.setOrtho(ortho); engine.frame(view, false); drain();

      const drag = (dx: number, dy: number, shift = false) => {
        canvas.dispatchEvent(mousePointer("pointerdown", 400, 300, shift));
        document.dispatchEvent(mousePointer("pointermove", 400 + dx, 300 + dy, shift));
        document.dispatchEvent(mousePointer("pointerup", 400 + dx, 300 + dy, shift));
        drain();
      };

      try {
        // A horizontal pointer move rotates around the initial screen-up axis:
        // the eye stays in its horizontal plane and the camera does not roll.
        let initial = cameraFrame(live);
        drag(60, 0);
        let after = cameraFrame(live);
        expect(after.away.dot(initial.up)).toBeCloseTo(0, 9);
        expect(after.up.dot(initial.up)).toBeCloseTo(1, 9);
        expect(live.controls.update()).toBe(false);

        // A vertical pointer move rotates around the initial screen-right axis.
        engine.frame(view, false); drain(); initial = cameraFrame(live);
        drag(0, 60); after = cameraFrame(live);
        expect(after.away.dot(initial.right)).toBeCloseTo(0, 9);
        expect(after.right.dot(initial.right)).toBeCloseTo(1, 9);
        expect(live.controls.update()).toBe(false);

        // Shift+left drag remains OrbitControls' pan gesture: eye and target
        // translate together without changing the held view direction.
        engine.frame(view, false); drain(); initial = cameraFrame(live);
        const target = live.controls.target.clone(); const eye = live.camera.position.clone();
        drag(60, 35, true); after = cameraFrame(live);
        expect(after.away.dot(initial.away)).toBeCloseTo(1, 12);
        expect(live.controls.target.distanceTo(target)).toBeGreaterThan(0);
        const eyeShift = live.camera.position.clone().sub(eye);
        const targetShift = live.controls.target.clone().sub(target);
        expect(eyeShift.distanceTo(targetShift)).toBeCloseTo(0, 10);
        expect(live.controls.update()).toBe(false);

        // An explicit view/Fit wins even when invoked before damping's queued
        // frames run; old inertia must not pull the newly framed camera away.
        engine.frame(view, false); drain();
        const fitted = engine.cameraSnapshot();
        canvas.dispatchEvent(mousePointer("pointerdown", 400, 300));
        document.dispatchEvent(mousePointer("pointermove", 460, 300));
        document.dispatchEvent(mousePointer("pointerup", 460, 300));
        engine.frame(view, false); drain();
        const reframed = engine.cameraSnapshot();
        expect(reframed.eye).toEqual(fitted.eye);
        expect(reframed.target).toEqual(fitted.target);
        expect(reframed.up).toEqual(fitted.up);
        expect(reframed.fit).toBe(true);
        expect(live.controls.update()).toBe(false);
        expect(settled).toHaveBeenCalled();
      } finally { engine.dispose(); canvas.remove(); }
    });
  }
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
