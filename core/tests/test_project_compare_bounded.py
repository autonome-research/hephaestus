"""Bounded solid-diff execution (``COMPARE.md`` §5): same numbers, killable child.

Two properties carry the amendment. Determinism: a diff that completes through
the bounded subprocess is the *direct geom call's record*, byte for byte — the
BRep hand-off may not change a single number, or the bound would quietly coarsen
every comparison. And the cut-short case: a child that cannot finish is
``CompareTimeout`` and a child that dies is ``CompareChildDied`` — two named
reasons under the shared ``CompareCutShort`` carriage (J-build-state-4), each
CARRYING the cheap facts that arrived and naming the halves that did not, with
the subprocess provably dead afterwards either way.
"""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any, cast

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
    CompareChildDied,
    CompareCutShort,
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


def test_a_child_death_is_its_own_reason_not_a_timeout_with_a_ceiling_it_never_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """J-build-state-4: a kernel crash mid-diff (the sweep's SIGSEGV mode) is
    not a hang and not an empty hand — the streamed facts survive, and the
    exit code is named — but it is ALSO not a timeout: no ceiling fired, the
    child died after however long it took, and reporting a 300 s ceiling for a
    2.7 s crash tells four consumers (the model's tool error, the CLI's JSON,
    the check report, the bench's budget refunder) to wait longer for a bound
    that was never tested. ``CompareChildDied`` is a sibling of
    ``CompareTimeout`` under the shared ``CompareCutShort`` carriage, not the
    same type under a different message."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", dying_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    plate = Box(40.0, 20.0, 5.0)

    with pytest.raises(CompareChildDied) as excinfo:
        bounded_solid_diff(plate, plate, align="as_posed", timeout_s=120.0)

    refusal = excinfo.value
    assert isinstance(refusal, CompareCutShort)
    assert not isinstance(refusal, CompareTimeout)
    assert refusal.reason == "compare_child_died"
    assert refusal.exit_code == 7
    assert "died" in refusal.message and "exit code 7" in refusal.message
    assert refusal.partial == CHEAP_FACTS
    assert refusal.lost == (LOST_VOLUME, LOST_SURFACE)
    document = refusal.to_json()
    assert document["status"] == "compare_child_died"
    assert document["reason"] == "compare_child_died"
    assert document["exit_code"] == 7
    assert "timeout_s" not in document, "no ceiling fired — asserting one is dishonest"
    _assert_child_dead(pid_file)


def test_a_genuine_ceiling_still_reports_the_ceiling_not_the_death_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half of the split: a grinder that never dies is still
    ``CompareTimeout`` (with its ceiling), never mistaken for a crash. This is
    what proves the two reasons are discriminated rather than one having been
    renamed out from under the other."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", grinding_child)
    monkeypatch.setenv(COMPARE_TIMEOUT_ENV, "3.0")
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    plate = Box(40.0, 20.0, 5.0)

    with pytest.raises(CompareTimeout) as excinfo:
        bounded_solid_diff(plate, plate, align="as_posed")

    refusal = excinfo.value
    assert isinstance(refusal, CompareCutShort)
    assert refusal.reason == "compare_timeout"
    assert refusal.timeout_s == 3.0
    document = refusal.to_json()
    assert document["timeout_s"] == 3.0
    assert "exit_code" not in document, "the ceiling fired — there is no exit code to report"
    _assert_child_dead(pid_file)


def test_a_predicate_whose_child_dies_is_unverifiable_and_diagnosable_by_reason() -> None:
    """The check engine catches the shared carriage (``CompareCutShort``), so a
    dead comparison lands as ``unverifiable`` exactly like a ceiling kill would
    — never a pass, never a bare ``error`` — and the entry's own reason says
    which one it was (J-build-state-4's check-engine half)."""
    from collections.abc import Callable

    from hephaestus.core.checks.engine import run_checks
    from hephaestus.core.checks.facade import Measurement

    def predicate(_measurement: object) -> bool:
        raise CompareChildDied(
            "solid diff subprocess died (exit code 3) before reporting",
            exit_code=3,
            partial=CHEAP_FACTS,
            lost=(LOST_VOLUME, LOST_SURFACE),
        )

    results = run_checks(
        {"diff_check": predicate},
        measurement_factory=cast("Callable[[], Measurement]", lambda: object()),
    )

    result = results["diff_check"]
    assert result.passed is False
    measured = cast("dict[str, Any]", result.measured)
    unverifiable = cast("dict[str, Any]", measured["unverifiable"])
    assert unverifiable["reason"] == "compare_child_died"
    assert unverifiable["exit_code"] == 3


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
