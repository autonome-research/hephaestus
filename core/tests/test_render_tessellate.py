"""Tessellation: kernel/tag index parity on a tagged part, and determinism."""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d / OCP surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import numpy as np
from build123d import Axis, Box, Compound, Pos
from hephaestus.core.executor.tags import TagRegistry, resolve_placements
from hephaestus.core.kernel.metrics import geometry_index, metrics
from hephaestus.core.render.tessellate import (
    ANGULAR_DEFLECTION,
    LINEAR_DEFLECTION,
    tessellate,
)


def _tagged_compound() -> tuple[Compound, TagRegistry]:
    """Two labelled boxes; the top face of the first box is tagged."""
    a = Box(20, 10, 6)
    a.label = "deck"
    b = Pos(40, 0, 0) * Box(8, 8, 8)
    b.label = "post"
    compound = Compound(children=[a, b])
    registry = TagRegistry()
    registry.set_statement(0, 1)
    top_face = compound.solids()[0].faces().sort_by(Axis.Z)[-1]
    registry.tag(top_face, "deck_top")
    return compound, registry


def test_solid_and_face_counts_match_kernel_metrics() -> None:
    compound, _ = _tagged_compound()
    tess = tessellate(compound)
    m = metrics(compound)
    assert len(tess.solids) == m.solids
    # Disjoint solids share no faces/edges, so per-solid counts sum to the
    # compound totals the kernel reports.
    assert sum(len(s.faces) for s in tess.solids) == m.faces
    assert sum(len(s.edges) for s in tess.solids) == m.edges
    # The geometry index still advertises both labelled solids.
    index = geometry_index(compound)
    assert index.labels == ("deck", "post")


def test_face_group_index_matches_tag_placement() -> None:
    compound, registry = _tagged_compound()
    placements = resolve_placements(registry, compound)
    placement = placements["deck_top"]
    assert placement.kind == "face"
    assert placement.solid_index is not None and placement.topo_index is not None

    tess = tessellate(compound)
    face = tess.face(placement.solid_index, placement.topo_index)
    assert face.solid_index == placement.solid_index
    assert face.face_index == placement.topo_index

    # That face group must be exactly the top face of the first solid: every
    # tessellated vertex sits on the solid's maximum-Z plane.
    solid = compound.solids()[placement.solid_index]
    max_z = solid.bounding_box().max.Z
    assert face.vertices.shape[1] == 3
    assert np.allclose(face.vertices[:, 2], max_z, atol=1e-6)
    # The face is a real triangle group.
    assert face.triangles.shape[0] >= 2
    assert int(face.triangles.max()) < face.vertices.shape[0]


def test_tessellation_is_stable_across_two_runs() -> None:
    compound, _ = _tagged_compound()
    a = tessellate(compound)
    b = tessellate(compound)
    assert len(a.solids) == len(b.solids)
    for sa, sb in zip(a.solids, b.solids, strict=True):
        assert len(sa.faces) == len(sb.faces)
        for fa, fb in zip(sa.faces, sb.faces, strict=True):
            assert np.array_equal(fa.vertices, fb.vertices)
            assert np.array_equal(fa.triangles, fb.triangles)
        for ea, eb in zip(sa.edges, sb.edges, strict=True):
            assert np.array_equal(ea.points, eb.points)


def test_edges_are_polylines() -> None:
    compound, _ = _tagged_compound()
    tess = tessellate(compound)
    for solid in tess.solids:
        assert len(solid.edges) == 12  # each box has 12 edges
        for edge in solid.edges:
            assert edge.points.shape[0] >= 2
            assert edge.points.shape[1] == 3


def test_deflection_constants_documented() -> None:
    # The determinism/golden contract pins these; guard against silent drift.
    assert LINEAR_DEFLECTION == 0.1
    assert ANGULAR_DEFLECTION == 0.5


def test_bounds_cover_geometry() -> None:
    compound, _ = _tagged_compound()
    tess = tessellate(compound)
    (lo, hi) = tess.bounds()
    bb = compound.bounding_box()
    assert lo[0] <= bb.min.X + 1e-6 and hi[0] >= bb.max.X - 1e-6
    assert hi[2] >= bb.max.Z - 1e-6
