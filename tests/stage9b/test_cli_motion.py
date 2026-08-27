# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9B: ``heph motion`` — the operator's view (``KINEMATICS.md`` §6, 9B subset).

The verb pair is what makes the declared motion-check state inspectable and
re-measurable without a model in the loop, pinned on the ``heph joints`` /
``heph assembly`` precedent: both output modes carry the same facts, the bare
verb reads the projection and never evaluates, ``heph motion check`` is the
only thing that measures (and projects only a FULL run — a named subset says
``partial`` and leaves the projection alone, the ``check_assembly`` rule),
withdrawn entries stay visible with their recorded reasons, "never evaluated"
is said out loud rather than shown as an empty pass, and the exit code follows
the §6 never-green rule — any non-success verdict (``violated``,
``not_reached_at_samples``, ``unresolvable``) exits 1 so a build script can
gate on motion state. The sweep numbers asserted here are REAL measurements
over the ``_g9b`` mechanism's published BReps (pin/bore radial air 0.1 mm),
not stubs. The coupling table is Stage 9C and deliberately absent.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _g9b import (
    NOMINAL_RADIAL_AIR_MM,
    REACH_TARGET_MM,
    assumed,
    make_project,
    open_sweep_project,
)
from hephaestus.core.cli import main
from hephaestus.core.project_store.kinematics import JointSet, MotionCheckSet
from hephaestus.core.project_store.layout import ProjectLayout


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    """Invoke the real CLI entry point with the project as the working directory."""
    monkeypatch.chdir(root)
    return main(list(argv))


def emitted(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return payload


@pytest.fixture(scope="module")
def swept(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ProjectLayout]:
    """The _g9b mechanism built, a hinge joint and three checks declared.

    Declared: ``mc-air`` (clearance threshold under the 0.1 mm pin/bore air —
    holds), ``mc-tight`` (threshold over it — violated), ``mc-reach`` (a
    target only a -90° swing touches, swept ±10° — not reached), and
    ``mc-temp`` (declared then withdrawn; the reason must stay readable).
    Nothing is evaluated here: the CLI verbs under test drive every
    measurement, and the store is closed so each test exercises the CLI's own
    open/close path.
    """
    layout, store = open_sweep_project(tmp_path_factory.mktemp("swept") / "proj")
    try:
        joints = JointSet(layout, store)
        checks = MotionCheckSet(layout, store, joints)
        joints.declare(
            {
                "id": "j-hinge",
                "kind": "revolute",
                "parent": "base:hinge_bore",
                "child": "arm:hinge_pin",
                "limits": {"min": -90.0, "max": 90.0},
                "provenance": assumed(),
            }
        )
        checks.declare(
            {
                "id": "mc-air",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "min_mm": 0.05,
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "samples": 3,
                "provenance": assumed(),
            }
        )
        checks.declare(
            {
                "id": "mc-tight",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "min_mm": 0.5,
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "samples": 3,
                "provenance": assumed(),
            }
        )
        checks.declare(
            {
                "id": "mc-reach",
                "kind": "reach",
                "anchor": "arm",
                "target_point_mm": list(REACH_TARGET_MM),
                "tol_mm": 0.5,
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "samples": 3,
                "provenance": assumed(),
            }
        )
        checks.declare(
            {
                "id": "mc-temp",
                "kind": "sweep_no_interference",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "samples": 2,
                "provenance": assumed(),
            }
        )
        checks.withdraw("mc-temp", "the temporary claim was dropped from the design")
    finally:
        store.close()
    yield layout


class TestReporting:
    def test_a_project_with_nothing_declared_says_so(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout = make_project(tmp_path / "proj", {})
        assert run(layout.root, monkeypatch, "motion") == 0
        assert "no motion checks declared" in capsys.readouterr().out

        assert run(layout.root, monkeypatch, "motion", "--json") == 0
        payload = emitted(capsys)
        assert payload["status"] == "not_evaluated"
        assert payload["checks"] == []
        assert payload["results"] is None
        assert payload["motion"] is None
        # The coupling table is Stage 9C: no fake column, no dead key.
        assert "couplings" not in payload

    def test_declared_but_never_evaluated_is_not_reported_as_measured(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # "Not measured" is a fact about the project, not a CLI failure: exit 0.
        assert run(swept.root, monkeypatch, "motion") == 0
        out = capsys.readouterr().out
        assert "never evaluated" in out
        assert "not measured" in out
        # The withdrawn entry stays visible with its recorded reason.
        assert "WITHDRAWN" in out
        assert "dropped from the design" in out

        assert run(swept.root, monkeypatch, "motion", "--json") == 0
        payload = emitted(capsys)
        assert payload["status"] == "not_evaluated"
        assert payload["results"] is None and payload["results_ref"] is None
        assert [entry["id"] for entry in payload["checks"]] == [
            "mc-air",
            "mc-tight",
            "mc-reach",
            "mc-temp",
        ]
        assert payload["checks"][3]["withdrawn"] is True


class TestEvaluation:
    """Ordered: ``check`` measures and projects; the bare verb then reads it."""

    def test_check_measures_real_verdicts_and_exits_never_green(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # mc-tight is violated, so the never-green rule exits 1.
        assert run(swept.root, monkeypatch, "motion", "check", "--json") == 1
        payload = emitted(capsys)
        assert payload["status"] == "ok" and payload["partial"] is False
        by_id = {record["id"]: record for record in payload["results"]}
        # The withdrawn check is never evaluated — three results, not four.
        assert sorted(by_id) == ["mc-air", "mc-reach", "mc-tight"]
        # All five verdict spellings are one closed set; the three landed here
        # are asserted verbatim, on REAL measured numbers.
        assert by_id["mc-air"]["verdict"] == "holds_at_samples"
        assert by_id["mc-air"]["worst"]["measured"] == pytest.approx(
            NOMINAL_RADIAL_AIR_MM, abs=1e-6
        )
        assert by_id["mc-air"]["samples_evaluated"] == 3
        assert by_id["mc-tight"]["verdict"] == "violated"
        assert by_id["mc-reach"]["verdict"] == "not_reached_at_samples"
        assert by_id["mc-reach"]["miss_mm"] is not None and by_id["mc-reach"]["miss_mm"] > 0
        motion = payload["motion"]
        assert motion["counts"]["joints"] == {"resolved": 1, "unresolvable": 0}

    def test_the_bare_verb_reads_the_projection_without_measuring(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(swept.root, monkeypatch, "motion", "--json") == 1
        payload = emitted(capsys)
        assert payload["status"] == "ok"
        assert payload["results_ref"].startswith("artifact:motion-results:sha256:")
        assert [record["id"] for record in payload["results"]] == [
            "mc-air",
            "mc-tight",
            "mc-reach",
        ]
        assert payload["motion_ref"].startswith("artifact:motion-status:sha256:")

    def test_the_human_table_carries_the_same_facts(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(swept.root, monkeypatch, "motion") == 1
        out = capsys.readouterr().out
        # Success spellings stay lowercase; non-success shouts (heph assembly).
        assert "holds_at_samples" in out
        assert "VIOLATED" in out
        assert "NOT_REACHED_AT_SAMPLES" in out
        assert "WITHDRAWN" in out
        assert "0.1 mm" in out  # the real worst sample, unit attached
        assert "joints 1 resolved" in out

    def test_a_named_subset_is_evaluated_but_not_projected(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # mc-air alone holds and the status resolves: exit 0.
        assert run(swept.root, monkeypatch, "motion", "check", "mc-air", "--json") == 0
        payload = emitted(capsys)
        assert payload["partial"] is True
        assert [record["id"] for record in payload["results"]] == ["mc-air"]

        # The projection still carries the last FULL run — all three results.
        assert run(swept.root, monkeypatch, "motion", "--json") == 1
        assert len(emitted(capsys)["results"]) == 3

    def test_check_human_output_carries_the_verdict_table(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(swept.root, monkeypatch, "motion", "check") == 1
        out = capsys.readouterr().out
        assert "holds_at_samples" in out and "VIOLATED" in out
        assert "joints 1 resolved" in out

    def test_a_partial_check_says_so_in_human_output(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(swept.root, monkeypatch, "motion", "check", "mc-air") == 0
        out = capsys.readouterr().out
        assert "partial" in out
        # Only the evaluated subset is tabled: the run measured nothing else.
        assert "mc-air" in out and "VIOLATED" not in out

    def test_an_unknown_check_id_is_usage_naming_the_declared_ones(
        self,
        swept: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(swept.root, monkeypatch, "motion", "check", "mc-ghost") == 2
        err = capsys.readouterr().err
        assert "mc-ghost" in err and "mc-air" in err
