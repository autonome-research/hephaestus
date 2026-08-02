"""Bounded solid-diff execution (``COMPARE.md`` §5): same numbers, killable child.

Two properties carry the amendment. Determinism: a diff that completes through
the bounded subprocess is the *direct geom call's record*, byte for byte — the
BRep hand-off may not change a single number, or the bound would quietly coarsen
every comparison. And the ceiling: a child that cannot finish (or dies) yields
the named ``compare_timeout`` refusal CARRYING the cheap facts that arrived and
naming the halves that did not, with the subprocess provably dead afterwards.
"""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import hephaestus.core.project_compare as project_compare
import pytest
from _bounded_grind import (
    CHEAP_FACTS,
    PID_FILE_ENV,
    dying_child,
    grinding_child,
    silent_child,
)
from build123d import Box, Cylinder
from hephaestus.core.project_compare import (
    COMPARE_TIMEOUT_ENV,
    COMPARE_TIMEOUT_S,
    LOST_SURFACE,
    LOST_TOPOLOGY,
    LOST_VOLUME,
    CompareRefusal,
    CompareTimeout,
    bounded_solid_diff,
    compare_timeout_s,
)
from hephaestus.geom.compare import solid_diff

#: The G8B determinism tolerance (``COMPARE.md`` gate: "identical records to
#: 1e-9"). The BRep hand-off is a 17-significant-digit decimal text format, so
#: a boolean volume may wiggle by one ULP; anything past 1e-9 is a defect.
RECORD_TOL = 1e-9


def _assert_records_match(bounded: object, direct: object, path: str = "diff") -> None:
    """Recursive equality: floats to :data:`RECORD_TOL`, everything else exact."""
    if isinstance(direct, dict):
        assert isinstance(bounded, dict), path
        assert set(bounded) == set(direct), path
        for key in direct:
            _assert_records_match(bounded[key], direct[key], f"{path}.{key}")
    elif isinstance(direct, list | tuple):
        assert isinstance(bounded, list | tuple), path
        assert len(bounded) == len(direct), path
        for i, (got, want) in enumerate(zip(bounded, direct, strict=True)):
            _assert_records_match(got, want, f"{path}[{i}]")
    elif isinstance(direct, float):
        assert bounded == pytest.approx(direct, abs=RECORD_TOL), path
    else:
        assert bounded == direct, path  # ints, bools, strings: exact


def _assert_child_dead(pid_file: Path) -> None:
    """The killed subprocess must be gone — reaped by join, not orphaned."""
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


# ==========================================================================
# determinism (COMPARE.md §5: completed diffs keep their numbers)


def test_a_completed_bounded_diff_is_the_direct_geom_record() -> None:
    """The bounded path returns ``asdict(solid_diff(a, b))`` — every volume,
    every chamfer mean, every sample count — to the gate's own 1e-9 determinism
    tolerance, with counts and structure exact."""
    a = Box(40.0, 20.0, 5.0)
    b = Box(40.0, 20.0, 5.0) - Cylinder(3.0, 20.0)

    direct = dataclasses.asdict(solid_diff(a, b, align="as_posed"))
    bounded = bounded_solid_diff(a, b, align="as_posed", timeout_s=600.0)

    _assert_records_match(bounded, direct)


def test_the_geom_refusal_keeps_its_identity_across_the_boundary() -> None:
    """``align="principal"`` on a shape with no volume is ``no_solid_geometry``
    (COMPARE.md §1) — a fact about the geometry, never rebranded as a timeout
    just because it was discovered in a subprocess."""
    plate = Box(40.0, 20.0, 5.0)
    face_only = plate.faces()[0]

    with pytest.raises(CompareRefusal) as excinfo:
        bounded_solid_diff(face_only, plate, align="principal", timeout_s=600.0)

    assert excinfo.value.reason == "no_solid_geometry"
    assert not isinstance(excinfo.value, CompareTimeout)


# ==========================================================================
# the ceiling


def test_a_ceiling_kill_carries_the_streamed_facts_and_leaves_no_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A grinder that streamed the cheap facts is killed at the deadline; the
    refusal carries those facts, names the lost halves, and the subprocess is
    dead — the 19-hour compare_solids grind becomes one named refusal."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", grinding_child)
    monkeypatch.setenv(COMPARE_TIMEOUT_ENV, "3.0")
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    plate = Box(40.0, 20.0, 5.0)

    with pytest.raises(CompareTimeout) as excinfo:
        bounded_solid_diff(plate, plate, align="as_posed")

    refusal = excinfo.value
    assert refusal.reason == "compare_timeout"
    assert refusal.timeout_s == 3.0  # the env override, resolved per call
    assert refusal.partial == CHEAP_FACTS
    assert refusal.lost == (LOST_VOLUME, LOST_SURFACE)
    document = refusal.to_json()
    assert document["status"] == "compare_timeout"
    assert document["partial"] == CHEAP_FACTS
    assert document["lost"] == [LOST_VOLUME, LOST_SURFACE]
    _assert_child_dead(pid_file)


def test_a_child_death_is_the_same_named_refusal_with_the_facts_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A kernel crash mid-diff (the sweep's SIGSEGV mode) is not a hang and not
    an empty hand: the streamed facts survive, and the exit is named."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", dying_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    plate = Box(40.0, 20.0, 5.0)

    with pytest.raises(CompareTimeout) as excinfo:
        bounded_solid_diff(plate, plate, align="as_posed", timeout_s=120.0)

    refusal = excinfo.value
    assert "died" in refusal.message and "exit code 7" in refusal.message
    assert refusal.partial == CHEAP_FACTS
    assert refusal.lost == (LOST_VOLUME, LOST_SURFACE)
    _assert_child_dead(pid_file)


def test_a_silent_child_loses_every_half_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When not even the census arrived, the refusal says so — ``partial`` is
    None and ``lost`` starts with the topology census, so an empty hand can
    never be misread as 'the shapes did not differ'."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", silent_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    plate = Box(40.0, 20.0, 5.0)

    with pytest.raises(CompareTimeout) as excinfo:
        bounded_solid_diff(plate, plate, align="as_posed", timeout_s=2.0)

    refusal = excinfo.value
    assert refusal.partial is None
    assert refusal.lost == (LOST_TOPOLOGY, LOST_VOLUME, LOST_SURFACE)
    _assert_child_dead(pid_file)


# ==========================================================================
# the ceiling's knob


def test_the_ceiling_is_env_overridable_and_falls_back_on_nonsense(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(COMPARE_TIMEOUT_ENV, raising=False)
    assert compare_timeout_s() == COMPARE_TIMEOUT_S
    monkeypatch.setenv(COMPARE_TIMEOUT_ENV, "17.5")
    assert compare_timeout_s() == 17.5
    monkeypatch.setenv(COMPARE_TIMEOUT_ENV, "not-a-number")
    assert compare_timeout_s() == COMPARE_TIMEOUT_S
