// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { BoxGeometry, Group, Mesh, MeshBasicMaterial, PerspectiveCamera } from 'three';
import { raycastHint } from '../src/viewport/scene';

describe('read-only actual scene pick hints', () => {
  it('returns loader mesh/primitive identity, never an invented selection', () => {
    const mesh = new Mesh(new BoxGeometry(), new MeshBasicMaterial());
    const group = new Group();
    group.add(mesh);
    group.updateMatrixWorld(true);
    const camera = new PerspectiveCamera(35, 1, .1, 100);
    camera.position.set(0, 0, 5);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld(true);
    const associations = new Map([[mesh, { meshes: 7, primitives: 3 }]]);
    expect(raycastHint(associations, camera, 0, 0)).toEqual({ mesh_index: 7, primitive_index: 3 });
    expect(raycastHint(associations, camera, NaN, 0)).toBeNull();
    expect(raycastHint(associations, camera, 2, 0)).toBeNull();
    group.visible = false;
    expect(raycastHint(associations, camera, 0, 0)).toBeNull();
    group.visible = true;
    expect(raycastHint(new Map([[mesh, { meshes: 7 }]]), camera, 0, 0)).toBeNull();
  });
});
