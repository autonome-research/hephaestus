# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G12B (mesh -> B-rep, sections, socket path) suite.

G12A's fixtures are hand-computable arithmetic over a 10 mm cube. G12B needs two
more kinds, and both are here for a reason that survives a reader's scepticism:

* **the §4.1 reference sphere, tessellated by the harness's own renderer** at
  the pinned deflections, because every number ``MESH_INGEST.md`` §4.1 and §4.2
  quote was measured on exactly that mesh. It is kept in TWO forms — the
  tessellator's raw output (1027 vertices for 2004 triangles, every corner its
  own copy) and the same bytes through §1.5 canonicalization (1003 vertices,
  2002 triangles). They sew to different verdicts, and the difference is the
  single most important thing this suite found;
* **a tessellated cylinder**, whose plane sections are near-circular and whose
  loft therefore has an analytic ground truth a reader can check: π r² h.

Fixtures are authored here rather than imported from ``tests/stage12a`` or
``corpus/`` so a gate assertion cannot be satisfied by a change to somebody
else's fixture. The cube helpers ARE re-derived here for the same reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh
from hephaestus.testing.tools_fixture import Project

__all__ = [
    "CYLINDER_HEIGHT_MM",
    "CYLINDER_RADIUS_MM",
    "SECTION_SPACING_MM",
    "SPHERE_RADIUS_MM",
    "Fixtures",
    "build_error",
    "build_ok",
    "canonical_arrays",
    "cube_faces",
    "cube_vertices",
    "evidence_path",
    "evidence_world",
    "export_mesh",
    "install_import",
    "make_fixtures",
    "read_evidence",
    "tessellated_arrays",
    "write_evidence",
    "write_script",
]

#: The §4.1 reference sphere's radius, in millimetres.
SPHERE_RADIUS_MM = 20.0

#: The §5.2 socket fixture's cylinder. A limb is not a cylinder, but a cylinder
#: is the shape whose lofted sections have a volume a reader can compute.
CYLINDER_RADIUS_MM = 15.0
CYLINDER_HEIGHT_MM = 40.0

#: The declared section spacing the §5.2 path uses (§5.3). Not decoration: at
#: the mesh's own crossing density the loft comes back an uncapped shell and is
#: refused, which this suite asserts as its own clause.
SECTION_SPACING_MM = 2.0


def cube_vertices(edge: float = 10.0) -> np.ndarray:
    """The 8 corners of an axis-aligned cube with one corner at the origin."""
    return np.array(
        [
            [0.0, 0.0, 0.0],
            [edge, 0.0, 0.0],
            [edge, edge, 0.0],
            [0.0, edge, 0.0],
            [0.0, 0.0, edge],
            [edge, 0.0, edge],
            [edge, edge, edge],
            [0.0, edge, edge],
        ]
    )


def cube_faces() -> np.ndarray:
    """The 12 triangles of that cube, wound consistently outward."""
    return np.array(
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


def export_mesh(vertices: np.ndarray, faces: np.ndarray, fmt: str = "stl") -> bytes:
    """Write a triangle set through trimesh's own exporter, as an operator would."""
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    data = mesh.export(file_type=fmt)
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def tessellated_arrays(shape: object) -> tuple[np.ndarray, np.ndarray]:
    """``(vertices, triangles)`` straight out of ``render.tessellate``, UNWELDED.

    This is the mesh ``MESH_INGEST.md`` §4.1 and §4.2 were measured on: the
    renderer emits one vertex array per FACE, so a 2004-triangle sphere arrives
    with 1027 vertices and no two faces share one. Keeping it unwelded is the
    whole point — §1.5's weld is what the canonical form adds, and the two forms
    sew to different verdicts.
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
    """``(vertices, triangles, CanonicalMesh)`` through the product's own §1.5 path.

    Nothing here reimplements canonicalization: a test that welded its own mesh
    would be asserting against its own arithmetic rather than against the
    pipeline every ``import_mesh`` actually runs.
    """
    from hephaestus.geom.mesh import canonicalize_mesh, deserialize_mesh

    canonical = canonicalize_mesh(path, data, units)
    vertices, triangles, _factor = deserialize_mesh(canonical.blob, source=path)
    return vertices, triangles, canonical


@dataclass(frozen=True)
class Fixtures:
    """Every G12B fixture, authored once per session (they are pure functions)."""

    #: The §4.1 reference sphere as the tessellator emits it: unwelded.
    sphere_raw_vertices: np.ndarray
    sphere_raw_faces: np.ndarray
    #: The same sphere's STL bytes, the form an operator would hand the harness.
    sphere_stl: bytes
    #: A tessellated R15 x 40 cylinder's STL bytes (the §5.2 socket fixture).
    cylinder_stl: bytes
    #: The 10 mm cube, which sews to a VALID solid.
    cube_stl: bytes
    #: The cube with one BOTTOM triangle deleted: an open shell, refused by the
    #: validity gate. The hole is below every section plane this suite cuts, so
    #: it tests the gate without also testing the section walk.
    holed_stl: bytes
    #: The cube with one SIDE triangle deleted, so a plane at z = 5 crosses the
    #: hole itself: the section walk runs out of segments and must report an
    #: OPEN contour rather than joining its ends.
    side_holed_stl: bytes
    #: Two cubes 100 mm apart: a plane through both yields TWO contours.
    two_components_stl: bytes
    #: A square split in two plus a third triangle on the shared diagonal.
    nonmanifold_fin_stl: bytes


def make_fixtures() -> Fixtures:
    """Author every fixture once, through the renderer and trimesh's exporter."""
    from build123d import Cylinder, Sphere

    sphere_v, sphere_f = tessellated_arrays(Sphere(SPHERE_RADIUS_MM))
    cylinder_v, cylinder_f = tessellated_arrays(
        Cylinder(radius=CYLINDER_RADIUS_MM, height=CYLINDER_HEIGHT_MM)
    )
    cube_v, cube_f = cube_vertices(), cube_faces()
    two_v = np.vstack([cube_v, cube_v + np.array([100.0, 0.0, 0.0])])
    two_f = np.vstack([cube_f, cube_f + len(cube_v)])
    fin_v = np.array(
        [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 10.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 10.0]]
    )
    fin_f = np.array([[0, 1, 2], [0, 2, 3], [0, 2, 4]], dtype=np.int64)
    return Fixtures(
        sphere_raw_vertices=sphere_v,
        sphere_raw_faces=sphere_f,
        sphere_stl=export_mesh(sphere_v, sphere_f),
        cylinder_stl=export_mesh(cylinder_v, cylinder_f),
        cube_stl=export_mesh(cube_v, cube_f),
        holed_stl=export_mesh(cube_v, np.delete(cube_f, 0, axis=0)),
        # Triangle 4 is [0, 1, 5] on the y = 0 wall: the z = 5 plane crosses it.
        side_holed_stl=export_mesh(cube_v, np.delete(cube_f, 4, axis=0)),
        two_components_stl=export_mesh(two_v, two_f),
        nonmanifold_fin_stl=export_mesh(fin_v, fin_f),
    )


# --------------------------------------------------------------------------
# project helpers (the same shape tests/stage12a uses, so the two read alike)


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


def build_ok(project: Project, name: str, script: str | None = None) -> dict[str, Any]:
    """Author (optionally) and build a part that must have succeeded."""
    if script is not None:
        write_script(project, name, script)
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "ok", result
    return result


def build_error(project: Project, name: str, script: str) -> dict[str, Any]:
    """Author ``script``, build it, and return the §8 error record it must produce."""
    write_script(project, name, script)
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "error", result
    return cast("dict[str, Any]", result["error"])


# --------------------------------------------------------------------------
# archived evidence (mission rules 1 and 2: the measurement, not the opinion)

#: Where the §4.2 / §4.5 measurements this gate reasons from are archived.
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"


def evidence_path(name: str) -> Path:
    return EVIDENCE_DIR / name


def read_evidence(name: str) -> dict[str, Any]:
    """The archived measurement, or ``{}`` when it has not been recorded yet."""
    path = evidence_path(name)
    if not path.exists():
        return {}
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def evidence_world(name: str) -> dict[str, str]:
    """The ``(image digest, OCCT version)`` pair an archived measurement was taken in.

    Refuses rather than returning a default. An archived kernel measurement that
    cannot say which world it came from is an anecdote: the sew goldens beside
    it have carried this pair since 12B (``verification.md``'s golden-provenance
    rule, extended to OCCT by §8 Tier 3), and the §4.2 / §4.5 evidence was the
    one place in this suite that did not — which matters most for §4.5, whose
    clause says the experiment runs *on the pinned image*.
    """
    archived = read_evidence(name)
    world = archived.get("provenance")
    if not isinstance(world, dict) or not {"image_digest", "occt_version"} <= set(
        cast("dict[str, Any]", world)
    ):
        raise AssertionError(
            f"the archived measurement {name!r} carries no provenance stamp naming the "
            "(container image digest, OCCT version) pair it was recorded in. Re-record "
            "it with HEPHAESTUS_REBASELINE_SEW_GOLDENS=1 (MESH_INGEST.md §8 Tier 3)."
        )
    return {str(key): str(value) for key, value in cast("dict[str, Any]", world).items()}


def write_evidence(name: str, payload: dict[str, Any]) -> None:
    """Archive one measurement, stamped with the world it was measured in.

    The stamp is added here rather than at each call site for the reason
    ``MeshReadError`` derives its code in the constructor: a provenance a caller
    writes by hand is a provenance a caller can forget, and the evidence that
    forgets is exactly the evidence somebody later reads as if it came from
    anywhere.
    """
    from hephaestus.core.mesh_solid import sew_provenance

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path(name).write_text(
        json.dumps({**payload, "provenance": sew_provenance()}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
