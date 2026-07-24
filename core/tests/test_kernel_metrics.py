"""Kernel metrics tests: hand-computable fixtures per verification.md."""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import math

from build123d import Axis, Box, Compound, Cylinder, Pos, Sphere, Torus
from hephaestus.core.addressing import label_rows, namespace, resolve
from hephaestus.core.kernel import (
    AnyShape,
    bbox_mm,
    genus,
    geometry_index,
    is_sealed,
    labeled_nodes,
    metrics,
    shape_volume,
)
from hypothesis import given, settings
from hypothesis import strategies as st

TOL = 1e-6


def box() -> Box:
    return Box(10.0, 20.0, 30.0)


def holed_box() -> AnyShape:
    """Box with a cylindrical through-hole: sealed, genus 1."""
    return Box(20.0, 20.0, 10.0) - Cylinder(3.0, 10.0)


class TestMetrics:
    def test_box_full_record(self) -> None:
        m = metrics(box())
        assert m.solids == 1
        assert m.faces == 6
        assert m.edges == 12
        assert math.isclose(m.bbox_mm[0], 10.0, abs_tol=TOL)
        assert math.isclose(m.bbox_mm[1], 20.0, abs_tol=TOL)
        assert math.isclose(m.bbox_mm[2], 30.0, abs_tol=TOL)
        assert math.isclose(m.volume_mm3, 6000.0, abs_tol=1e-6 * 6000.0)
        assert m.area_mm2 is not None
        assert math.isclose(m.area_mm2, 2 * (200.0 + 300.0 + 600.0), rel_tol=1e-9)
        assert m.sealed is True
        assert m.genus == 0

    def test_metrics_serializes_via_types_record(self) -> None:
        data = metrics(box()).to_json()
        assert data["solids"] == 1
        assert data["sealed"] is True
        assert data["genus"] == 0
        assert isinstance(data["bbox_mm"], list)

    def test_two_solid_compound_counts(self) -> None:
        comp = Compound(children=[Box(10, 10, 10), Pos(30, 0, 0) * Box(5, 5, 5)])
        m = metrics(comp)
        assert m.solids == 2
        assert m.faces == 12
        assert math.isclose(m.volume_mm3, 1000.0 + 125.0, abs_tol=TOL)
        assert m.sealed is True
        assert m.genus == 0

    def test_bbox_mm_translation_moves_nothing(self) -> None:
        b = bbox_mm(Pos(7.0, -3.0, 11.0) * box())
        assert math.isclose(b[0], 10.0, abs_tol=TOL)
        assert math.isclose(b[1], 20.0, abs_tol=TOL)
        assert math.isclose(b[2], 30.0, abs_tol=TOL)


class TestSealedGenus:
    def test_box_sealed_genus_zero(self) -> None:
        assert is_sealed(box()) is True
        assert genus(box()) == 0

    def test_holed_box_sealed_genus_one(self) -> None:
        hb = holed_box()
        assert is_sealed(hb) is True
        assert genus(hb) == 1

    def test_torus_genus_one(self) -> None:
        t = Torus(10.0, 3.0)
        assert is_sealed(t) is True
        assert genus(t) == 1

    def test_sphere_periodic_surface_sealed_genus_zero(self) -> None:
        s = Sphere(5.0)
        assert is_sealed(s) is True
        assert genus(s) == 0

    def test_cylinder_sealed_genus_zero(self) -> None:
        c = Cylinder(3.0, 10.0)
        assert is_sealed(c) is True
        assert genus(c) == 0

    def test_open_face_not_sealed(self) -> None:
        face = box().faces()[0]
        assert is_sealed(face) is False

    def test_compound_with_stray_face_not_sealed(self) -> None:
        stray = (Pos(50, 0, 0) * Box(5, 5, 5)).faces()[0]
        comp = Compound(children=[box(), stray])
        assert is_sealed(comp) is False

    def test_genus_sums_over_solids(self) -> None:
        comp = Compound(children=[holed_box(), Pos(60, 0, 0) * Torus(10.0, 3.0)])
        assert is_sealed(comp) is True
        assert genus(comp) == 2


def labeled_fixture() -> Compound:
    """part_root -> [alpha, grp -> [alpha]] with duplicate 'alpha' labels."""
    a1 = Box(1, 1, 1)
    a1.label = "alpha"
    a2 = Pos(3.0, 0.0, 0.0) * Box(2, 2, 2)
    a2.label = "alpha"
    grp = Compound(children=[a2])
    grp.label = "grp"
    top = Compound(children=[a1, grp])
    top.label = "part_root"
    return top


class TestGeometryIndex:
    def test_labels_in_tree_order_with_duplicates(self) -> None:
        idx = geometry_index(labeled_fixture())
        assert idx.labels == ("part_root", "alpha", "grp", "alpha")

    def test_labeled_nodes_map_occurrences_to_shapes(self) -> None:
        top = labeled_fixture()
        nodes = labeled_nodes(top)
        assert tuple(label for label, _ in nodes) == ("part_root", "alpha", "grp", "alpha")
        idx = geometry_index(top)
        res = resolve("alpha#2", idx)
        assert res.occurrences == (3,)
        _, shape = nodes[res.occurrences[0]]
        assert math.isclose(shape_volume(shape), 8.0, abs_tol=TOL)
        first = resolve("alpha", idx)
        _, shape1 = nodes[first.occurrences[0]]
        assert math.isclose(shape_volume(shape1), 1.0, abs_tol=TOL)

    def test_bindings_and_tags_flow_through(self) -> None:
        idx = geometry_index(labeled_fixture(), bindings={"xs": 2, "solo": 1}, tags=("tread",))
        assert dict(idx.bindings) == {"xs": 2, "solo": 1}
        assert idx.tags == frozenset({"tread"})
        names = namespace(idx)
        assert "tread" in names
        assert "xs#2" in names
        assert resolve("tread", idx).kind == "tag"

    def test_label_rows_dedup_display(self) -> None:
        idx = geometry_index(labeled_fixture())
        assert label_rows(idx) == ("part_root", "alpha", "grp", "alpha#2")

    def test_unlabeled_shape_yields_empty_labels(self) -> None:
        idx = geometry_index(Box(1, 1, 1))
        assert idx.labels == ()
        assert namespace(idx) == ("part",)


@settings(max_examples=15, deadline=None)
@given(
    dx=st.floats(min_value=-50, max_value=50, allow_nan=False, allow_infinity=False),
    dy=st.floats(min_value=-50, max_value=50, allow_nan=False, allow_infinity=False),
    dz=st.floats(min_value=-50, max_value=50, allow_nan=False, allow_infinity=False),
)
def test_volume_translation_invariant(dx: float, dy: float, dz: float) -> None:
    base = metrics(box())
    moved = metrics(Pos(dx, dy, dz) * box())
    assert math.isclose(moved.volume_mm3, base.volume_mm3, abs_tol=TOL)
    assert moved.solids == base.solids
    assert moved.faces == base.faces
    assert moved.sealed == base.sealed
    assert moved.genus == base.genus


@settings(max_examples=10, deadline=None)
@given(
    sx=st.floats(min_value=1, max_value=40, allow_nan=False, allow_infinity=False),
    sy=st.floats(min_value=1, max_value=40, allow_nan=False, allow_infinity=False),
    sz=st.floats(min_value=1, max_value=40, allow_nan=False, allow_infinity=False),
)
def test_box_volume_matches_analytic(sx: float, sy: float, sz: float) -> None:
    m = metrics(Box(sx, sy, sz))
    assert math.isclose(m.volume_mm3, sx * sy * sz, rel_tol=1e-9, abs_tol=TOL)
    assert m.sealed is True
    assert m.genus == 0


def test_axis_sanity_of_fixture_orientation() -> None:
    # Guard: top face of a box is +Z; keeps face-based fixtures honest.
    top_face = box().faces().sort_by(Axis.Z)[-1]
    assert math.isclose(float(top_face.area), 200.0, abs_tol=TOL)
