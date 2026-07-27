"""Kernel measurement tests: two-box fixtures at known offsets, determinism."""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

from build123d import Axis, Box, Compound, Plane, Pos
from hephaestus.geom import (
    AnyShape,
    clearance,
    distance,
    interference,
    interference_pairs,
    mass,
    section,
)
from hypothesis import given, settings
from hypothesis import strategies as st

TOL = 1e-6


def unit10() -> Box:
    return Box(10.0, 10.0, 10.0)


class TestInterference:
    def test_half_overlap_volume(self) -> None:
        # Boxes 10x10x10 centered at x=0 and x=5: overlap slab is 5x10x10.
        assert math.isclose(interference(unit10(), Pos(5, 0, 0) * unit10()), 500.0, abs_tol=1e-6)

    def test_disjoint_is_zero(self) -> None:
        assert interference(unit10(), Pos(50, 0, 0) * unit10()) == 0.0

    def test_touching_faces_is_zero(self) -> None:
        assert math.isclose(interference(unit10(), Pos(10, 0, 0) * unit10()), 0.0, abs_tol=1e-6)

    def test_strict_containment_is_inner_volume(self) -> None:
        assert math.isclose(interference(Box(20, 20, 20), Box(5, 5, 5)), 125.0, abs_tol=1e-6)

    def test_pairs_breakdown(self) -> None:
        shapes: dict[str, AnyShape] = {
            "a": unit10(),
            "b": Pos(5, 0, 0) * unit10(),
            "c": Pos(50, 0, 0) * unit10(),
        }
        pairs = interference_pairs(shapes)
        assert set(pairs) == {("a", "b"), ("a", "c"), ("b", "c")}
        assert list(pairs) == sorted(pairs)  # deterministic emission order
        assert math.isclose(pairs[("a", "b")], 500.0, abs_tol=1e-6)
        assert pairs[("a", "c")] == 0.0
        assert pairs[("b", "c")] == 0.0


class TestClearance:
    def test_known_gap(self) -> None:
        # Centers 15 apart, half-widths 5+5 -> 5 mm gap.
        assert math.isclose(clearance(unit10(), Pos(15, 0, 0) * unit10()), 5.0, abs_tol=1e-6)

    def test_touching_is_zero(self) -> None:
        assert math.isclose(clearance(unit10(), Pos(10, 0, 0) * unit10()), 0.0, abs_tol=1e-6)

    def test_overlapping_is_zero(self) -> None:
        assert clearance(unit10(), Pos(5, 0, 0) * unit10()) == 0.0

    def test_strict_containment_is_zero_not_boundary_distance(self) -> None:
        # Boundary distance would be 7.5; clearance must detect the overlap.
        assert clearance(Box(20, 20, 20), Box(5, 5, 5)) == 0.0

    def test_non_solid_features_fall_back_to_distance(self) -> None:
        f1 = unit10().faces().sort_by(Axis.Z)[-1]
        f2 = (Pos(0, 0, 20) * unit10()).faces().sort_by(Axis.Z)[0]
        assert math.isclose(clearance(f1, f2), 10.0, abs_tol=1e-6)


class TestDistance:
    def test_between_solids(self) -> None:
        assert math.isclose(distance(unit10(), Pos(17, 0, 0) * unit10()), 7.0, abs_tol=1e-6)

    def test_between_resolved_faces(self) -> None:
        top = unit10().faces().sort_by(Axis.Z)[-1]
        bottom = (Pos(0, 0, 20) * unit10()).faces().sort_by(Axis.Z)[0]
        assert math.isclose(distance(top, bottom), 10.0, abs_tol=1e-6)

    def test_face_to_edge(self) -> None:
        top = unit10().faces().sort_by(Axis.Z)[-1]
        far_edge = (Pos(0, 0, 30) * unit10()).edges().sort_by(Axis.Z)[0]
        assert math.isclose(distance(top, far_edge), 20.0, abs_tol=1e-6)


class TestMass:
    def test_known_density(self) -> None:
        # 1000 mm^3 at steel-ish 7.8e-3 g/mm^3 -> 7.8 g.
        assert math.isclose(mass(unit10(), 7.8e-3), 7.8, rel_tol=1e-9)

    def test_zero_density(self) -> None:
        assert mass(unit10(), 0.0) == 0.0


class TestSection:
    def test_midplane_single_face(self) -> None:
        faces = section(unit10(), Plane.XY)
        assert len(faces) == 1
        assert math.isclose(float(faces[0].area), 100.0, abs_tol=1e-6)

    def test_offset_plane_still_sections(self) -> None:
        faces = section(Box(10, 10, 30), Plane.XY.offset(10.0))
        assert len(faces) == 1
        assert math.isclose(float(faces[0].area), 100.0, abs_tol=1e-6)

    def test_disjoint_plane_yields_nothing(self) -> None:
        assert section(unit10(), Plane.XY.offset(50.0)) == ()

    def test_compound_sections_per_solid(self) -> None:
        comp = Compound(children=[unit10(), Pos(30, 0, 0) * unit10()])
        faces = section(comp, Plane.XY)
        assert len(faces) == 2
        for f in faces:
            assert math.isclose(float(f.area), 100.0, abs_tol=1e-6)

    def test_non_solid_input_yields_nothing(self) -> None:
        assert section(unit10().faces()[0], Plane.XY) == ()


@settings(max_examples=15, deadline=None)
@given(
    off=st.floats(min_value=-8, max_value=8, allow_nan=False, allow_infinity=False),
    dy=st.floats(min_value=-30, max_value=30, allow_nan=False, allow_infinity=False),
)
def test_interference_symmetry(off: float, dy: float) -> None:
    a = unit10()
    b = Pos(off, dy, 0) * unit10()
    assert math.isclose(interference(a, b), interference(b, a), abs_tol=1e-6)


@settings(max_examples=15, deadline=None)
@given(
    gap=st.floats(min_value=0.5, max_value=30, allow_nan=False, allow_infinity=False),
    tx=st.floats(min_value=-40, max_value=40, allow_nan=False, allow_infinity=False),
    ty=st.floats(min_value=-40, max_value=40, allow_nan=False, allow_infinity=False),
    tz=st.floats(min_value=-40, max_value=40, allow_nan=False, allow_infinity=False),
)
def test_clearance_translation_invariant(gap: float, tx: float, ty: float, tz: float) -> None:
    a = unit10()
    b = Pos(10 + gap, 0, 0) * unit10()
    base = clearance(a, b)
    moved = clearance(Pos(tx, ty, tz) * a, Pos(tx, ty, tz) * b)
    assert math.isclose(base, gap, abs_tol=1e-6)
    assert math.isclose(moved, base, abs_tol=1e-6)


_DETERMINISM_SCRIPT = """\
import json
from build123d import Box, Cylinder, Pos
from hephaestus.geom import clearance, interference, metrics

shape = Box(20.0, 20.0, 10.0) - Cylinder(3.0, 10.0)
other = Pos(27.5, 0.0, 0.0) * Box(10.0, 10.0, 10.0)
overlap_probe = Pos(5.0, 0.0, 0.0) * Box(20.0, 20.0, 10.0)
out = {
    "metrics": metrics(shape).to_json(),
    "interference": interference(shape, overlap_probe),
    "clearance": clearance(shape, other),
}
print(json.dumps(out, sort_keys=True))
"""


def _run_metrics_subprocess(tmp_path: Path, run: int) -> dict[str, object]:
    script = tmp_path / f"determinism_{run}.py"
    script.write_text(_DETERMINISM_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    result: dict[str, object] = json.loads(proc.stdout)
    return result


def _flatten(prefix: str, value: object, out: dict[str, object]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}", v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    else:
        out[prefix] = value


def test_metric_determinism_across_processes(tmp_path: Path) -> None:
    """Same script + params => metrics identical to 1e-6 across two processes."""
    first = _run_metrics_subprocess(tmp_path, 1)
    second = _run_metrics_subprocess(tmp_path, 2)
    flat_a: dict[str, object] = {}
    flat_b: dict[str, object] = {}
    _flatten("$", first, flat_a)
    _flatten("$", second, flat_b)
    assert flat_a.keys() == flat_b.keys()
    for key, va in flat_a.items():
        vb = flat_b[key]
        if isinstance(va, float) and isinstance(vb, float):
            assert math.isclose(va, vb, abs_tol=1e-6), key
        else:
            assert va == vb, key
