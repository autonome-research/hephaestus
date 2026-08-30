# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G12C (scan scoring, surface, corpus) suite.

Three kinds of fixture, and each is here for a reason that survives scepticism:

* **hand-computable meshes** — a unit square, a plate, a box — whose true
  point-to-surface distances are known in closed form, so clause 34's "equals
  hand-computed distances to 1e-9" is a comparison against arithmetic rather
  than against a second implementation of the same code;
* **the round-trip pair** — an analytic solid and the mesh the harness's own
  renderer + exporter produce from it, which is the only construction in which
  §6.6's fidelity claim has a ground truth to be measured against;
* **a pathological mesh** — one enormous triangle beside a fine patch — which is
  what makes ``scan_neighborhood_overflow`` reachable without lowering a ceiling
  to manufacture it.

Fixtures are authored here rather than imported from ``tests/stage12a``,
``tests/stage12b`` or ``corpus/`` so a gate assertion cannot be satisfied by a
change to somebody else's fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh
from hephaestus.testing.tools_fixture import Project

__all__ = [
    "BOX_X",
    "BOX_Y",
    "BOX_Z",
    "PLATE_MM",
    "SPHERE_R",
    "Fixtures",
    "brute_force_distances",
    "build_ok",
    "canonical_arrays",
    "export_mesh",
    "install_import",
    "make_fixtures",
    "rewrite_script",
    "scan_check",
    "tessellated_arrays",
    "write_script",
]

#: The analytic round-trip solid: a sphere is the shape whose tessellation
#: deviation is largest and most uniform, so §6.6's window has something to bind.
SPHERE_R = 20.0

#: The hand-computable box the direction-A clause measures against.
BOX_X, BOX_Y, BOX_Z = 40.0, 30.0, 20.0

#: A flat plate mesh's edge, in mm.
PLATE_MM = 10.0


def export_mesh(vertices: np.ndarray, faces: np.ndarray, fmt: str = "stl") -> bytes:
    """Write a triangle set through trimesh's own exporter, as an operator would."""
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    data = mesh.export(file_type=fmt)
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def tessellated_arrays(shape: object) -> tuple[np.ndarray, np.ndarray]:
    """``(vertices, triangles)`` straight out of ``render.tessellate``, UNWELDED.

    The renderer's own output at the pinned deflections, which is what makes the
    round-trip loop a statement about *this* pipeline rather than about a
    tessellator a test invented.
    """
    from hephaestus.core.render.tessellate import tessellate

    tessellation = tessellate(cast("Any", shape))
    vertex_blocks: list[np.ndarray] = []
    triangle_blocks: list[np.ndarray] = []
    offset = 0
    for solid in tessellation.solids:
        for face in solid.faces:
            points = np.asarray(face.vertices, dtype=np.float64).reshape(-1, 3)
            triangles = np.asarray(face.triangles, dtype=np.int64).reshape(-1, 3)
            vertex_blocks.append(points)
            triangle_blocks.append(triangles + offset)
            offset += points.shape[0]
    return np.vstack(vertex_blocks), np.vstack(triangle_blocks)


def canonical_arrays(data: bytes, *, path: str, units: str = "mm") -> tuple[Any, Any, Any]:
    """``(vertices, triangles, CanonicalMesh)`` through the product's own §1.5 path."""
    from hephaestus.geom.mesh import canonicalize_mesh, deserialize_mesh

    canonical = canonicalize_mesh(path, data, units)
    vertices, triangles, _factor = deserialize_mesh(canonical.blob, source=path)
    return vertices, triangles, canonical


def brute_force_distances(
    vertices: np.ndarray, faces: np.ndarray, queries: np.ndarray
) -> np.ndarray:
    """Distance to the mesh by testing EVERY triangle — the clause 35 reference.

    It shares the point-to-triangle primitive with the product on purpose: what
    G12C.35 tests is that the ``d_v + L_max`` candidate set is a sound superset,
    and a reference that reimplemented the arithmetic would be testing two
    implementations of *that* instead. The pruning is the claim; this is the
    unpruned answer.
    """
    from hephaestus.geom.mesh import closest_point_on_triangle

    corners = vertices[faces]
    out = np.empty(queries.shape[0], dtype=np.float64)
    for index in range(queries.shape[0]):
        point = np.repeat(queries[index][None, :], faces.shape[0], axis=0)
        closest = closest_point_on_triangle(point, corners[:, 0], corners[:, 1], corners[:, 2])
        offset = point - closest
        out[index] = float(np.sqrt(np.einsum("ij,ij->i", offset, offset)).min())
    return out


def _box(x: float, y: float, z: float) -> tuple[np.ndarray, np.ndarray]:
    """A closed axis-aligned box centred on the origin, wound outward."""
    hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
    vertices = np.array(
        [
            [-hx, -hy, -hz],
            [hx, -hy, -hz],
            [hx, hy, -hz],
            [-hx, hy, -hz],
            [-hx, -hy, hz],
            [hx, -hy, hz],
            [hx, hy, hz],
            [-hx, hy, hz],
        ]
    )
    faces = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],
            [4, 5, 6],
            [4, 6, 7],
            [0, 1, 5],
            [0, 5, 4],
            [1, 2, 6],
            [1, 6, 5],
            [2, 3, 7],
            [2, 7, 6],
            [3, 0, 4],
            [3, 4, 7],
        ],
        dtype=np.int64,
    )
    return vertices, faces


@dataclass(frozen=True)
class Fixtures:
    """Every G12C fixture, authored once per session (they are pure functions)."""

    #: A 40 x 30 x 20 box mesh centred on the origin: 8 vertices, 12 triangles,
    #: every distance to it computable by hand.
    box_stl: bytes
    box_vertices: np.ndarray
    box_faces: np.ndarray
    #: A flat 10 mm square in the z = 0 plane, two triangles.
    plate_vertices: np.ndarray
    plate_faces: np.ndarray
    #: The R20 sphere tessellated at the PINNED deflections, exported as STL:
    #: the §6.6 round-trip mesh, whose analytic truth is the sphere itself.
    sphere_stl: bytes
    #: The same sphere at a deliberately COARSER deflection — the §6.6 upper
    #: negative control, which must exceed the window.
    sphere_coarse_stl: bytes
    #: And a DENSE re-tessellation of the same analytic sphere — the §6.6 lower
    #: negative control, which must fall under the window's floor.
    sphere_dense_stl: bytes
    #: The pinned mesh with every vertex scaled by 1.001: the clause 45
    #: corruption control, whose nodes no longer lie on the surface they came
    #: from.
    sphere_scaled_stl: bytes
    #: A pathological mesh: one enormous triangle beside a fine patch, so
    #: ``L_max`` inflates every query radius and the candidate set overflows.
    pathological_vertices: np.ndarray
    pathological_faces: np.ndarray
    #: A point cloud at the box's own eight corners: the same measurement target
    #: with no surface between its points (§2.3).
    points_xyz: bytes


def make_fixtures() -> Fixtures:
    """Author every fixture once, through the renderer and trimesh's exporter."""
    from build123d import Sphere

    box_v, box_f = _box(BOX_X, BOX_Y, BOX_Z)
    plate_v = np.array(
        [[0.0, 0.0, 0.0], [PLATE_MM, 0.0, 0.0], [PLATE_MM, PLATE_MM, 0.0], [0.0, PLATE_MM, 0.0]]
    )
    plate_f = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    sphere_v, sphere_f = tessellated_arrays(Sphere(SPHERE_R))
    coarse_v, coarse_f = _icosphere(SPHERE_R, subdivisions=2)
    dense_v, dense_f = _icosphere(SPHERE_R, subdivisions=4)
    path_v, path_f = _pathological()
    corners = "\n".join(f"{x} {y} {z}" for x, y, z in box_v.tolist()) + "\n"
    return Fixtures(
        box_stl=export_mesh(box_v, box_f),
        points_xyz=corners.encode("utf-8"),
        box_vertices=box_v,
        box_faces=box_f,
        plate_vertices=plate_v,
        plate_faces=plate_f,
        sphere_stl=export_mesh(sphere_v, sphere_f),
        sphere_coarse_stl=export_mesh(coarse_v, coarse_f),
        sphere_dense_stl=export_mesh(dense_v, dense_f),
        sphere_scaled_stl=export_mesh(sphere_v * 1.001, sphere_f),
        pathological_vertices=path_v,
        pathological_faces=path_f,
    )


def _icosphere(radius: float, *, subdivisions: int) -> tuple[np.ndarray, np.ndarray]:
    """A subdivided icosahedron on the same analytic sphere.

    Authored rather than re-tessellated at a different deflection, because the
    renderer's deflections are golden provenance (``tessellate.py``) and a test
    that reached in to change them would be editing the thing §6.6 measures.
    Every vertex still lies exactly ON the sphere — which is what keeps the
    identity direction ~0 for all of them and leaves the *fidelity* direction as
    the only thing that moves.

    Measured on the 20 mm sphere: 2 subdivisions leave a 0.317 mm sampled
    maximum (three times the pinned 0.1 mm, comfortably above the window) and
    4 subdivisions leave 0.020 mm (comfortably below its floor). Those are the
    two negative controls §6.6 asks for.
    """
    mesh = cast("Any", trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius))
    return (
        np.asarray(mesh.vertices, dtype=np.float64),
        np.asarray(mesh.faces, dtype=np.int64),
    )


def _pathological() -> tuple[np.ndarray, np.ndarray]:
    """A fine patch of triangles plus one enormous one sharing its corner.

    ``L_max`` is the enormous triangle's edge, so every query radius inflates to
    cover the whole fine patch and the candidate count blows past the ceiling —
    §6.3 step 5's exact case, reached by geometry rather than by lowering a
    ceiling to manufacture it.
    """
    fine: list[list[float]] = []
    faces: list[list[int]] = []
    # 64 x 64 quads = 8192 triangles, which is past the shipped 4096 candidate
    # ceiling on its own: the fixture overflows by GEOMETRY, so the clause is
    # not satisfied by an environment variable a run could have set.
    n = 64
    for i in range(n):
        for j in range(n):
            base = len(fine)
            x0, y0 = i * 0.2, j * 0.2
            fine.extend(
                [[x0, y0, 0.0], [x0 + 0.2, y0, 0.0], [x0 + 0.2, y0 + 0.2, 0.0], [x0, y0 + 0.2, 0.0]]
            )
            faces.extend([[base, base + 1, base + 2], [base, base + 2, base + 3]])
    base = len(fine)
    fine.extend([[0.0, 0.0, 5.0], [900.0, 0.0, 5.0], [0.0, 900.0, 5.0]])
    faces.append([base, base + 1, base + 2])
    return np.asarray(fine, dtype=np.float64), np.asarray(faces, dtype=np.int64)


# --------------------------------------------------------------------------
# project helpers (the same shape tests/stage12a and 12b use, so all three read
# alike)


def install_import(root: Path, name: str, data: bytes) -> Path:
    """Put a file in the project's ``imports/`` the way an operator would."""
    target = root / "imports" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def write_script(project: Project, name: str, script: str) -> None:
    """Author a part through the model's own tools (create_part + write_part)."""
    created = cast("dict[str, Any]", project.call("create_part", {"name": name}))
    applied = cast(
        "dict[str, Any]",
        project.call(
            "write_part",
            {"name": name, "expected_hash": created["content_hash"], "script": script},
        ),
    )
    assert applied["applied"] is True, applied


def rewrite_script(project: Project, name: str, script: str) -> None:
    """Replace an existing part's source (read_part for the hash, then write)."""
    current = cast("dict[str, Any]", project.call("read_part", {"name": name}))
    applied = cast(
        "dict[str, Any]",
        project.call(
            "write_part",
            {"name": name, "expected_hash": current["content_hash"], "script": script},
        ),
    )
    assert applied["applied"] is True, applied


def build_ok(project: Project, name: str, script: str | None = None) -> dict[str, Any]:
    """Author (optionally) and build a part that must have succeeded."""
    if script is not None:
        write_script(project, name, script)
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "ok", result
    return result


def scan_check(project: Project, part: str, scan: str, **extra: Any) -> dict[str, Any]:
    """``compare_to_scan`` through the dispatcher; returns the tool result."""
    arguments: dict[str, Any] = {"part": part, "scan": scan, "units": "mm", **extra}
    return cast("dict[str, Any]", project.call("compare_to_scan", arguments))
