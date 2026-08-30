# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12B clauses 26-27: ``section_polylines`` against hand-computable fixtures.

The one thing this function must never do is close a contour that did not
close. A plane crossing a hole in a limb scan is crossing the place a socket
will press, and joining the two loose ends there would fabricate surface the
scanner never saw. Every assertion below is arithmetic over a 10 mm cube, so a
reader can redo it: a plane at z = 5 cuts a square of perimeter 40 mm and area
100 mm², and deleting the wall triangle the plane crosses opens it.
"""

from __future__ import annotations

import numpy as np
import pytest
from _g12b import Fixtures, canonical_arrays
from hephaestus.geom.mesh import (
    OPEN_SECTION_CONTOUR,
    MeshOperationError,
    SectionPolyline,
    section_polylines,
)

#: The eight points where the plane z = 5 crosses the canonical cube: its four
#: vertical edges, and the midpoint of each wall's triangulation diagonal.
CUBE_SECTION_POINTS = (
    (0.0, 0.0, 5.0),
    (0.0, 5.0, 5.0),
    (0.0, 10.0, 5.0),
    (5.0, 0.0, 5.0),
    (5.0, 10.0, 5.0),
    (10.0, 0.0, 5.0),
    (10.0, 5.0, 5.0),
    (10.0, 10.0, 5.0),
)


def _perimeter(polyline: SectionPolyline) -> float:
    points = np.asarray(polyline.points, dtype=np.float64)
    walked = np.vstack([points, points[:1]]) if polyline.closed else points
    return float(np.linalg.norm(np.diff(walked, axis=0), axis=1).sum())


def _area_xy(polyline: SectionPolyline) -> float:
    points = np.asarray(polyline.points, dtype=np.float64)
    x, y = points[:, 0], points[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


# ==========================================================================
# clause 26 — hand-computable sections, and the open contour that stays open


def test_clause26_a_plane_through_a_cube_is_one_closed_square_with_exact_coordinates(
    meshes: Fixtures,
) -> None:
    """One closed contour, and its vertices are the exact crossings, not a golden.

    Eight points rather than four, because the cube's walls are triangulated:
    the plane crosses each wall's diagonal as well as its two vertical edges.
    They are collinear in pairs and nothing collapses them, which is deliberate
    — a simplification pass here would be a decision about the geometry taken
    without recording it.
    """
    vertices, faces, _canonical = canonical_arrays(meshes.cube_stl, path="cube.stl")
    contours = section_polylines(vertices, faces, origin=(0.0, 0.0, 5.0), normal=(0.0, 0.0, 1.0))

    assert len(contours) == 1
    contour = contours[0]
    assert contour.closed is True
    assert contour.flag is None
    assert contour.point_spacing_mm is None
    assert len(contour.points) == 8
    assert tuple(sorted(contour.points)) == CUBE_SECTION_POINTS
    # Exact, because every crossing is at a half or a whole edge of a 10 mm cube.
    assert _perimeter(contour) == 40.0
    assert _area_xy(contour) == 100.0
    # A closed contour does not repeat its first point; ``closed`` says so.
    assert contour.points[0] != contour.points[-1]


def test_clause26_a_plane_through_two_components_yields_two_contours(
    meshes: Fixtures,
) -> None:
    """Two cubes 100 mm apart cut into two separate closed squares, not one."""
    vertices, faces, canonical = canonical_arrays(meshes.two_components_stl, path="two.stl")
    assert canonical.quality.connected_component_count == 2
    contours = section_polylines(vertices, faces, origin=(0.0, 0.0, 5.0), normal=(0.0, 0.0, 1.0))

    assert len(contours) == 2
    assert [c.closed for c in contours] == [True, True]
    assert [c.flag for c in contours] == [None, None]
    assert [_area_xy(c) for c in contours] == [100.0, 100.0]
    # …and they are the two cubes, not one contour reported twice.
    x_ranges = sorted(round(min(p[0] for p in c.points)) for c in contours)
    assert x_ranges == [0, 100]


def test_clause26_a_plane_through_a_hole_is_open_and_is_never_closed(
    meshes: Fixtures,
) -> None:
    """The load-bearing clause: an open contour comes back OPEN and flagged.

    The wall triangle the plane crosses is missing, so the walk runs out of
    segments. What comes back is an open polyline flagged
    ``open_section_contour`` whose two ends are 5 mm apart — the gap the scanner
    left, preserved. If this ever returns ``closed=True`` the harness has
    invented limb surface.
    """
    vertices, faces, canonical = canonical_arrays(meshes.side_holed_stl, path="holed.stl")
    assert canonical.quality.boundary_loop_count == 1
    contours = section_polylines(vertices, faces, origin=(0.0, 0.0, 5.0), normal=(0.0, 0.0, 1.0))

    assert len(contours) == 1
    contour = contours[0]
    assert contour.closed is False
    assert contour.flag == OPEN_SECTION_CONTOUR
    # The ends are apart, and by exactly the missing wall's half-width.
    first = np.asarray(contour.points[0])
    last = np.asarray(contour.points[-1])
    assert float(np.linalg.norm(first - last)) == pytest.approx(5.0, abs=1e-9)
    assert contour.to_json()["flag"] == OPEN_SECTION_CONTOUR


def test_clause26_a_plane_that_misses_is_empty_section_not_an_empty_success(
    meshes: Fixtures,
) -> None:
    """No crossing triangle is a REFUSAL. An empty tuple would be a claim about
    the geometry where the truth is a claim about the plane."""
    vertices, faces, _canonical = canonical_arrays(meshes.cube_stl, path="cube.stl")
    with pytest.raises(MeshOperationError) as raised:
        section_polylines(
            vertices, faces, origin=(0.0, 0.0, 50.0), normal=(0.0, 0.0, 1.0), source="cube.stl"
        )
    assert raised.value.reason == "empty_section"
    assert "crosses no triangle" in str(raised.value)

    # A zero normal is the same refusal, for the same reason: there is no plane.
    with pytest.raises(MeshOperationError) as degenerate:
        section_polylines(vertices, faces, origin=(0.0, 0.0, 5.0), normal=(0.0, 0.0, 0.0))
    assert degenerate.value.reason == "empty_section"


def test_clause26_a_declared_spacing_is_recorded_on_the_record(meshes: Fixtures) -> None:
    """``point_spacing_mm`` rides the record, so a consumer knows whether it is
    fitting the data or a resampling of it (§5.3)."""
    vertices, faces, _canonical = canonical_arrays(meshes.cube_stl, path="cube.stl")
    raw = section_polylines(vertices, faces, origin=(0.0, 0.0, 5.0), normal=(0.0, 0.0, 1.0))[0]
    resampled = section_polylines(
        vertices, faces, origin=(0.0, 0.0, 5.0), normal=(0.0, 0.0, 1.0), spacing=1.0
    )[0]
    assert raw.point_spacing_mm is None
    assert resampled.point_spacing_mm == 1.0
    assert resampled.closed is True
    # 40 mm of perimeter at 1 mm spacing, and the square is still a square.
    assert len(resampled.points) == 40
    assert _area_xy(resampled) == pytest.approx(100.0, abs=1e-9)


# ==========================================================================
# clause 27 — section determinism across processes


SECTION_CHILD = """
from _g12b import canonical_arrays, make_fixtures
from hephaestus.geom.mesh import section_polylines

fixtures = make_fixtures()
out = {}
for name, origin in (("cube_stl", (0.0, 0.0, 5.0)), ("two_components_stl", (0.0, 0.0, 5.0))):
    vertices, faces, _canonical = canonical_arrays(getattr(fixtures, name), path=name + ".stl")
    contours = section_polylines(vertices, faces, origin=origin, normal=(0.0, 0.0, 1.0))
    out[name] = [c.to_json() for c in contours]
print(json.dumps(out, sort_keys=True))
"""


def test_clause27_sections_are_identical_in_identical_order_in_two_processes() -> None:
    """Identical polylines, in identical ORDER, in two separate processes.

    Order is asserted as strictly as the coordinates. A section walk that
    returned the same contours in a different sequence would still break every
    consumer that pairs section *i* of one plane with section *i* of the next —
    which is exactly what ``loft_sections`` does.
    """
    from _g12b_subprocess import run_json

    first = run_json(SECTION_CHILD)
    second = run_json(SECTION_CHILD)
    assert first == second
    assert [c["closed"] for c in first["two_components_stl"]] == [True, True]
    # And the coordinates are bit-identical, not merely close: every crossing is
    # computed from the mesh edge's endpoints in ascending index order, so the
    # two triangles sharing an edge produce the same float (§5.3).
    assert first["cube_stl"][0]["points"] == second["cube_stl"][0]["points"]
