# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Kerf compensation: the offset arithmetic, the source order, the refusals.

The claim under test is a manufacturing one and it is measurable: a contour cut
along the nominal boundary loses half a kerf per edge, so the compensated path
must measure **nominal + one kerf** across every axis (half on each side) while
a hole must measure **nominal minus one kerf**. Everything here is checked on the
geometry that comes back out of the kernel, never on the numbers the offset was
asked for.
"""

from __future__ import annotations

from typing import Any

import pytest
from build123d import Box, Compound, Cylinder, Pos, Sphere
from hephaestus.core.errors import ValidationError
from hephaestus.geom.kerf import (
    KERF_UNCOMPENSATED,
    KerfRefusal,
    kerf_compensated_shape,
    resolve_kerf,
)
from hephaestus.geom.nesting import Blank, flat_profiles, shelf_nest

#: A kerf big enough that a rounding error cannot hide inside it.
KERF: float = 0.4


def _plate(width: float, height: float, thickness: float = 6.0, *, at: Any = None) -> Any:
    solid: Any = Box(width, height, thickness)
    return solid if at is None else at * solid


def _one(shape: Any) -> Any:
    """The single flat profile of a one-solid shape."""
    profiles = flat_profiles(Compound(children=list(shape.solids())), prefix="p")
    assert len(profiles) == 1
    return profiles[0]


def _ring_span(ring: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (max(xs) - min(xs), max(ys) - min(ys))


# ==========================================================================
# the offset itself


def test_a_square_grows_by_exactly_one_kerf_on_each_axis() -> None:
    """Half a kerf per side is the whole point: 40 mm nominal cuts to 40 mm."""
    plate = _plate(40.0, 25.0)
    nominal = _one(plate)
    assert (nominal.width_mm, nominal.height_mm) == (pytest.approx(40.0), pytest.approx(25.0))

    compensated = _one(kerf_compensated_shape(plate, KERF, prefix="p"))
    assert compensated.width_mm == pytest.approx(40.0 + KERF, abs=1e-6)
    assert compensated.height_mm == pytest.approx(25.0 + KERF, abs=1e-6)
    # Sharp corners, not arcs of the beam radius: a square stays a square, so a
    # rectangle's corner still measures where the drawing puts it.
    assert len(compensated.points) == len(nominal.points) == 4


def test_a_hole_shrinks_by_one_kerf_so_the_opening_lands_nominal() -> None:
    """Waste is *inside* a hole, so its cut path offsets the other way."""
    plate = _plate(60.0, 40.0) - Cylinder(6.0, 20.0)
    nominal = _one(plate)
    assert _ring_span(nominal.holes[0])[0] == pytest.approx(12.0, abs=0.01)

    compensated = _one(kerf_compensated_shape(plate, KERF, prefix="p"))
    width, height = _ring_span(compensated.holes[0])
    assert width == pytest.approx(12.0 - KERF, abs=0.01)
    assert height == pytest.approx(12.0 - KERF, abs=0.01)
    # …and the outer boundary still went the other way in the same call.
    assert compensated.width_mm == pytest.approx(60.0 + KERF, abs=1e-6)


def test_no_kerf_returns_the_very_same_shape_untouched() -> None:
    """A zero/negative kerf is not a zero-distance offset: nothing is rebuilt.

    This is what makes an uncompensated export byte-identical to one produced
    before compensation existed — the geometry is not merely equivalent, it is
    the same object.
    """
    plate = _plate(30.0, 20.0)
    assert kerf_compensated_shape(plate, 0.0, prefix="p") is plate
    assert kerf_compensated_shape(plate, -1.0, prefix="p") is plate


def test_compensated_profiles_still_do_not_overlap_when_nested() -> None:
    """Packing sees the grown outlines, so the declared spacing survives."""
    plate = _plate(40.0, 25.0)
    pair = Compound(children=[plate.solids()[0], (Pos(200.0, 0.0, 0.0) * plate).solids()[0]])
    blank = Blank(200.0, 100.0, margin_mm=1.0, spacing_mm=2.0)

    profiles = flat_profiles(kerf_compensated_shape(pair, KERF, prefix="p"), prefix="p")
    layout = shelf_nest(profiles, blank)
    boxes = [placement.bbox() for placement in layout.placements]
    assert len(boxes) == 2
    first, second = boxes
    # Disjoint, and separated by the blank's own spacing — the offset ate none
    # of it, because it happened before the packer ever saw the outlines.
    assert second[0] - first[2] == pytest.approx(blank.spacing_mm, abs=1e-6)
    assert first[2] - first[0] == pytest.approx(40.0 + KERF, abs=1e-6)


# ==========================================================================
# refusals


def test_a_hole_narrower_than_the_kerf_is_a_structured_refusal() -> None:
    """There is no compensated path for it, and an uncompensated one is scrap."""
    plate = _plate(40.0, 25.0) - Cylinder(0.05, 20.0)
    with pytest.raises(KerfRefusal) as ei:
        kerf_compensated_shape(plate, KERF, prefix="vent")
    assert ei.value.reason == "kerf_offset_failed"
    assert ei.value.data["profile"] == "vent_1"
    assert ei.value.data["ring"] == "hole_1"
    assert ei.value.data["kerf_mm"] == pytest.approx(KERF)
    assert "kerf" in ei.value.message


def test_a_solid_with_no_flat_pattern_names_itself() -> None:
    """Nothing flat to cut is a different refusal from a failed offset."""
    ball: Any = Sphere(5.0)
    with pytest.raises(KerfRefusal) as ei:
        kerf_compensated_shape(ball, KERF, prefix="ball")
    assert ei.value.reason == "not_a_sheet_profile"
    assert ei.value.data["profile"] == "ball_1"


def test_an_artifact_with_no_solids_refuses() -> None:
    with pytest.raises(KerfRefusal) as ei:
        kerf_compensated_shape(Compound(children=[]), KERF)
    assert ei.value.reason == "no_profiles"


# ==========================================================================
# source order — the rule that a kerf is never invented


def test_an_explicit_kerf_wins_over_the_process_pack() -> None:
    decision = resolve_kerf(explicit_mm=0.35, process="laser_cut", pack_kerf_mm=0.2)
    assert (decision.applied_mm, decision.source) == (0.35, "explicit")
    assert decision.process == "laser_cut"
    assert decision.compensates
    assert decision.note is None


def test_the_process_pack_supplies_the_kerf_when_nothing_is_passed() -> None:
    decision = resolve_kerf(process="laser_cut", pack_kerf_mm=0.2)
    assert (decision.applied_mm, decision.source, decision.process) == (0.2, "dfm", "laser_cut")
    assert decision.to_json() == {"applied_mm": 0.2, "source": "dfm", "process": "laser_cut"}


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({}, "no_process"),
        ({"process": "fdm"}, "pack_declares_no_kerf"),
        (
            {"process": "laser_cut", "unavailable": "source_script_unavailable"},
            "source_script_unavailable",
        ),
    ],
)
def test_no_source_compensates_nothing_and_says_why(kwargs: dict[str, Any], reason: str) -> None:
    """Silence is the one thing this must never do."""
    decision = resolve_kerf(**kwargs)
    assert decision.applied_mm is None
    assert decision.source == "none"
    assert not decision.compensates
    assert decision.note == KERF_UNCOMPENSATED
    assert decision.reason == reason


def test_an_explicit_zero_is_the_nominal_path_and_labelled_as_such() -> None:
    decision = resolve_kerf(explicit_mm=0.0, process="laser_cut", pack_kerf_mm=0.2)
    assert decision.applied_mm == 0.0
    assert decision.source == "explicit"
    assert not decision.compensates
    assert decision.note == KERF_UNCOMPENSATED
    assert decision.reason == "explicit_zero"


@pytest.mark.parametrize("value", [-0.1, float("inf"), float("nan")])
def test_a_kerf_that_is_not_a_width_is_a_contract_error(value: float) -> None:
    with pytest.raises(ValidationError):
        resolve_kerf(explicit_mm=value)


def test_a_downgraded_decision_keeps_its_source_and_names_the_reason() -> None:
    downgraded = resolve_kerf(process="laser_cut", pack_kerf_mm=0.2).uncompensated(
        "not_a_sheet_profile"
    )
    assert downgraded.applied_mm is None
    assert downgraded.source == "dfm"
    assert downgraded.note == KERF_UNCOMPENSATED
    assert downgraded.reason == "not_a_sheet_profile"
