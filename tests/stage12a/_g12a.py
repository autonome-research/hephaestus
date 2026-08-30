# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G12A (mesh and scan ingest) evidence suite.

Every G12A clause is asserted against a **real project driven through the real
tool dispatcher** — the surface a model actually calls — over a real opstore.
What it asserts is *product behaviour*: what a script can import, what it is
refused, what the project's own state says afterwards, and — the reason this
stage exists — that no fact the harness reports about a mesh claims more than a
triangle soup can support.

**There is no second suite underneath this one, and the claim that there was has
been removed.** An earlier version of this docstring said the exhaustive unit
coverage of the mechanisms lived beside them in ``core/tests``. It does not:
there are no mesh tests in ``core/tests`` at all, and every assertion about
``hephaestus.geom.mesh`` in this repository is in ``tests/stage12a``. That
matters to a reader deciding how much a change to ``geom/mesh.py`` is covered
by — the honest answer is "this suite, and nothing else" — and a docstring
pointing at coverage that does not exist is exactly the kind of comfortable
inaccuracy this stage is about refusing. Clauses that need the geom layer
directly assert against it here (``MeshReadError.reason`` beside each
build-level check, the hand-computable quality fixtures, the canonicalizer's own
records) rather than deferring to a suite that was never written.

**The fixtures are hand-computable on purpose.** A cube has 8 vertices, 18
edges, 12 triangles and χ = 2; delete one triangle and it has exactly 3 boundary
edges in exactly 1 loop whose perimeter is ``10 + 10 + 10√2``. Every quality
number this suite asserts is arithmetic a reader can redo, not a golden captured
from the implementation — a golden would pass just as happily if the
implementation were wrong from the first run.

They are authored here rather than imported from ``core/tests`` or ``corpus/``
so a gate assertion cannot be satisfied by a change to somebody else's fixture.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh
from hephaestus.testing.tools_fixture import Project

__all__ = [
    "CUBE_EDGE_MM",
    "HOLE_PERIMETER_MM",
    "MeshFixtures",
    "asset_of",
    "build_error",
    "build_ok",
    "cube_faces",
    "cube_vertices",
    "export_mesh",
    "install_import",
    "make_mesh_fixtures",
    "scan_facts",
    "write_script",
]

#: The cube fixture's edge, in millimetres. Everything below is arithmetic over
#: this one number, so a reader can check the expectations by hand.
CUBE_EDGE_MM = 10.0

#: The perimeter of the single hole left by deleting one triangle from the
#: cube: two edges of the square face plus its diagonal.
HOLE_PERIMETER_MM = 2.0 * CUBE_EDGE_MM + CUBE_EDGE_MM * 2.0**0.5


def cube_vertices(edge: float = CUBE_EDGE_MM) -> np.ndarray:
    """The 8 corners of an axis-aligned cube with one corner at the origin."""
    half = edge
    return np.array(
        [
            [0.0, 0.0, 0.0],
            [half, 0.0, 0.0],
            [half, half, 0.0],
            [0.0, half, 0.0],
            [0.0, 0.0, half],
            [half, 0.0, half],
            [half, half, half],
            [0.0, half, half],
        ],
        dtype=np.float64,
    )


def cube_faces() -> np.ndarray:
    """12 outward-wound triangles over :func:`cube_vertices`."""
    return np.array(
        [
            [0, 3, 2],
            [0, 2, 1],  # z = 0
            [4, 5, 6],
            [4, 6, 7],  # z = edge
            [0, 1, 5],
            [0, 5, 4],  # y = 0
            [2, 3, 7],
            [2, 7, 6],  # y = edge
            [1, 2, 6],
            [1, 6, 5],  # x = edge
            [3, 0, 4],
            [3, 4, 7],  # x = 0
        ],
        dtype=np.int64,
    )


def export_mesh(vertices: np.ndarray, faces: np.ndarray, fmt: str) -> bytes:
    """Write a triangle set through trimesh's own exporter, as an operator would.

    ``process=False`` on the way in, because the *fixture* must be the array the
    test wrote: a merge or a reorder here would make the pipeline's own weld
    untestable.
    """
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    data = mesh.export(file_type=fmt)
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def binary_stl(vertices: np.ndarray, faces: np.ndarray) -> bytes:
    """A binary STL written by hand, so the fixture's 80-byte header is ours.

    trimesh's own binary STL writer is exercised elsewhere; this one exists so
    the declared-count header the §1.6 ceiling reads is a value this suite set.
    """
    out = bytearray(b"\x00" * 80)
    out += struct.pack("<I", len(faces))
    for tri in faces:
        a, b, c = vertices[tri[0]], vertices[tri[1]], vertices[tri[2]]
        normal = np.cross(b - a, c - a)
        length = float(np.linalg.norm(normal))
        normal = normal / length if length else normal
        out += struct.pack("<3f", *[float(v) for v in normal])
        for corner in (a, b, c):
            out += struct.pack("<3f", *[float(v) for v in corner])
        out += struct.pack("<H", 0)
    return bytes(out)


@dataclass(frozen=True)
class MeshFixtures:
    """Every fixture the gate needs, authored once and handed round as bytes."""

    cube_stl_binary: bytes
    cube_stl_ascii: bytes
    cube_ply_binary: bytes
    cube_ply_ascii: bytes
    cube_obj: bytes
    cube_off: bytes
    points_xyz: bytes
    #: The same cube with one triangle deleted: 3 boundary edges, 1 loop.
    holed_ply: bytes
    #: Two cubes in one file, far apart: 2 connected components.
    two_components_ply: bytes
    #: A square split in two, plus a third triangle on the shared diagonal.
    nonmanifold_fin_ply: bytes
    #: The cube with one triangle's winding reversed.
    reversed_winding_ply: bytes
    #: The cube plus a zero-area triangle, to be dropped and counted.
    degenerate_ply: bytes
    #: The cube with every vertex written three times (one per triangle
    #: corner), so the weld has 24 duplicate pairs to merge and report.
    duplicated_vertices_stl: bytes
    #: Two triangles that genuinely cross, with no shared vertex.
    crossing_ply: bytes
    #: Nothing but degenerate triangles.
    all_degenerate_ply: bytes
    #: A cube whose first vertex is NaN.
    nan_ply: bytes
    #: An OBJ declaring two objects.
    multi_object_obj: bytes
    #: A PLY carrying an extra non-geometry element with a nonzero count.
    multi_element_ply: bytes


def make_mesh_fixtures() -> MeshFixtures:
    """Author every fixture once (they are pure functions of the arrays above)."""
    vertices, faces = cube_vertices(), cube_faces()

    two_v = np.vstack([vertices, vertices + np.array([100.0, 0.0, 0.0])])
    two_f = np.vstack([faces, faces + len(vertices)])

    fin_v = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.5, 0.5, 1.0]]
    )
    fin_f = np.array([[0, 1, 2], [0, 2, 3], [0, 2, 4]], dtype=np.int64)

    reversed_f = faces.copy()
    reversed_f[0] = reversed_f[0][::-1]

    degenerate_v = np.vstack([vertices, [[20.0, 0.0, 0.0], [20.0, 0.0, 0.0], [20.0, 0.0, 0.0]]])
    degenerate_f = np.vstack([faces, [[8, 9, 10]]])

    duplicated = vertices[faces.reshape(-1)]
    duplicated_f = np.arange(len(duplicated), dtype=np.int64).reshape(-1, 3)

    crossing_v = np.array(
        [
            [0.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [0.0, 4.0, 0.0],
            [1.0, 1.0, -2.0],
            [1.0, 1.0, 2.0],
            [3.0, 1.0, 0.0],
        ]
    )
    crossing_f = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)

    flat = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    flat_f = np.array([[0, 1, 2]], dtype=np.int64)

    nan_v = vertices.copy()
    nan_v[0, 1] = float("nan")

    multi_obj = (
        b"o first\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        b"o second\nv 5 0 0\nv 6 0 0\nv 5 1 0\nf 4 5 6\n"
    )
    multi_element = (
        b"ply\nformat ascii 1.0\n"
        b"element vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
        b"element face 1\nproperty list uchar int vertex_indices\n"
        b"element material 2\nproperty float shine\n"
        b"end_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n0.5\n0.5\n"
    )

    return MeshFixtures(
        cube_stl_binary=binary_stl(vertices, faces),
        cube_stl_ascii=export_mesh(vertices, faces, "stl_ascii"),
        cube_ply_binary=export_mesh(vertices, faces, "ply"),
        cube_ply_ascii=_ascii_ply(vertices, faces),
        cube_obj=export_mesh(vertices, faces, "obj"),
        cube_off=export_mesh(vertices, faces, "off"),
        points_xyz=b"0.0 0.0 0.0\n1.0 2.0 3.0\n4.0 5.0 6.5\n",
        holed_ply=export_mesh(vertices, faces[:-1], "ply"),
        two_components_ply=export_mesh(two_v, two_f, "ply"),
        nonmanifold_fin_ply=export_mesh(fin_v, fin_f, "ply"),
        reversed_winding_ply=export_mesh(vertices, reversed_f, "ply"),
        degenerate_ply=export_mesh(degenerate_v, degenerate_f, "ply"),
        duplicated_vertices_stl=binary_stl(duplicated, duplicated_f),
        crossing_ply=export_mesh(crossing_v, crossing_f, "ply"),
        all_degenerate_ply=export_mesh(flat, flat_f, "ply"),
        nan_ply=_ascii_ply(nan_v, faces),
        multi_object_obj=multi_obj,
        multi_element_ply=multi_element,
    )


def _ascii_ply(vertices: np.ndarray, faces: np.ndarray) -> bytes:
    """An ASCII PLY written by hand — trimesh's exporter emits binary by default."""
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    lines += [" ".join(repr(float(value)) for value in row) for row in vertices]
    lines += ["3 " + " ".join(str(int(value)) for value in row) for row in faces]
    return ("\n".join(lines) + "\n").encode("ascii")


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


def build_ok(project: Project, name: str) -> dict[str, Any]:
    """``build_part`` that must have succeeded; returns the tool result."""
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "ok", result
    return result


def build_error(project: Project, name: str, script: str) -> dict[str, Any]:
    """Author ``script``, build it, and return the §8 error record it must produce."""
    write_script(project, name, script)
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "error", result
    return cast("dict[str, Any]", result["error"])


def scan_facts(path: str, data: bytes, units: str) -> Any:
    """The ``MeshAsset`` a build would see, computed through the product's own path.

    Canonicalize in the parent, serialize, then rebuild the asset from the
    staged blob and its sidecar — the same two-file round trip the worker makes
    — so a test never reads a record the staging code did not produce.
    """
    from hephaestus.geom.mesh import canonicalize_mesh, facts_to_json, mesh_asset_from_staged

    canonical = canonicalize_mesh(path, data, units)
    return mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path=path, units=units
    )


def asset_of(project: Project, part: str) -> dict[str, Any]:
    """The published build record of ``part`` (its input hashes and metrics)."""
    current = project.cad.current_build(part)
    assert current is not None, f"{part} has no current build"
    return {
        "input_hashes": current.input_hashes,
        "metrics": current.metrics,
    }
