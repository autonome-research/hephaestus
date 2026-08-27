# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9A: ``heph joints`` — the operator's view (``KINEMATICS.md`` §6, 9A subset).

The verb is what makes the declared kinematic state inspectable without a
model in the loop: an operator (or a script) asks the project what joints and
poses it claims and what the last evaluation made of them, in a table or as
JSON. Pinned here, on the ``heph assembly`` precedent: both output modes carry
the same facts, the verb reads the projection and never evaluates, withdrawn
entries stay visible with their recorded reasons, staleness is *said* rather
than silently repaired, and the exit code follows the never-green rule so a
build script can gate on it. ``heph motion`` (statuses plus sweep results,
with its ``check`` sub-verb) is Stage 9B and deliberately absent.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _g9a import HINGE_PARTS, assumed, build_part, make_project, open_hinge_project
from hephaestus.core.cli import main
from hephaestus.core.motion import MotionEvaluator
from hephaestus.core.project_store.kinematics import JointSet, PoseSet
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher

from opstore import OpStore


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    """Invoke the real CLI entry point with the project as the working directory."""
    monkeypatch.chdir(root)
    return main(list(argv))


def emitted(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return payload


@pytest.fixture(scope="module")
def hinged(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ProjectLayout]:
    """The hinge pair built, a mechanism declared and evaluated, store closed.

    Declared: ``j-hinge`` (resolvable, requirement-cited), ``j-temp`` (declared
    then withdrawn — the reason must stay readable), ``p-swung`` and ``p-zero``
    (both resolvable). The store is closed so every test exercises the CLI's
    own open/close path; mutating tests reopen it themselves.
    """
    layout, store = open_hinge_project(tmp_path_factory.mktemp("hinge") / "proj")
    try:
        joints = JointSet(layout, store)
        poses = PoseSet(layout, store, joints)
        joints.declare(
            {
                "id": "j-temp",
                "kind": "revolute",
                "parent": "base:hinge_bore",
                "child": "phantom:pin",
                "limits": {"min": -10.0, "max": 10.0},
                "provenance": assumed(),
            }
        )
        joints.withdraw("j-temp", "the temporary hinge was dropped from the design")
        joints.declare(
            {
                "id": "j-hinge",
                "kind": "revolute",
                "parent": "base:hinge_bore",
                "child": "arm:hinge_pin",
                "limits": {"min": -90.0, "max": 90.0},
                "provenance": {"requirement": "r-1"},
                "note": "arm swing per request",
            }
        )
        poses.declare({"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": assumed()})
        poses.declare({"id": "p-zero", "joints": {}, "provenance": assumed()})
        MotionEvaluator(layout, store).evaluate()
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
        assert run(layout.root, monkeypatch, "joints") == 0
        assert "no joints or poses declared" in capsys.readouterr().out

        assert run(layout.root, monkeypatch, "joints", "--json") == 0
        payload = emitted(capsys)
        assert payload["status"] == "not_evaluated"
        assert payload["joints"] == []
        assert payload["poses"] == []

    def test_declared_but_never_evaluated_is_not_reported_as_measured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Declaration is structural (the store's own rule), so no build is
        # needed to hold state the CLI must report honestly.
        layout = make_project(tmp_path / "proj", {})
        store = open_store(layout)
        try:
            joints = JointSet(layout, store)
            poses = PoseSet(layout, store, joints)
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
            poses.declare({"id": "p-swung", "joints": {"j-hinge": 45.0}, "provenance": assumed()})
        finally:
            store.close()

        assert run(layout.root, monkeypatch, "joints") == 0
        assert "never evaluated" in capsys.readouterr().out

        assert run(layout.root, monkeypatch, "joints", "--json") == 0
        payload = emitted(capsys)
        assert payload["status"] == "not_evaluated"
        assert payload["joint_generation"] == 1
        assert payload["pose_generation"] == 1
        assert payload["joints"][0]["id"] == "j-hinge"
        assert payload["poses"][0]["id"] == "p-swung"
        assert "motion" not in payload

    def test_the_table_joins_entries_with_the_latest_outcomes(
        self,
        hinged: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(hinged.root, monkeypatch, "joints") == 0
        out = capsys.readouterr().out
        # The resolvable joint: kind, both anchors, limits, provenance, state.
        assert "j-hinge" in out
        assert "revolute" in out
        assert "base:hinge_bore" in out
        assert "arm:hinge_pin" in out
        assert "[-90, 90] deg" in out
        assert "r-1" in out
        assert "resolved" in out
        # The withdrawn joint is still a row, marked, with its recorded reason.
        assert "j-temp" in out
        assert "WITHDRAWN" in out
        assert "the temporary hinge was dropped from the design" in out
        # Poses are listed with their bindings and per-pose outcomes.
        assert "p-swung" in out
        assert "j-hinge=-90" in out
        assert "p-zero" in out
        assert "(zero)" in out
        # The counts line names both generations and both sections.
        assert "joint generation 3, pose generation 2" in out
        assert "joints 1 resolved, 0 unresolvable" in out
        assert "poses 2 resolved, 0 unresolvable" in out

    def test_json_mode_is_the_machine_form(
        self,
        hinged: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(hinged.root, monkeypatch, "joints", "--json") == 0
        payload = emitted(capsys)
        assert payload["status"] == "ok"
        # Declared entries — withdrawn included — ride alongside the status.
        assert [item["id"] for item in payload["joints"]] == ["j-temp", "j-hinge"]
        assert payload["joints"][0]["withdrawn"] is True
        assert (
            payload["joints"][0]["withdrawn_reason"]
            == "the temporary hinge was dropped from the design"
        )
        # The status carries only ACTIVE entries (a withdrawn joint is never
        # evaluated), each with its outcome, and the evidence ref is named.
        motion = payload["motion"]
        assert [item["id"] for item in motion["joints"]] == ["j-hinge"]
        assert motion["joints"][0]["state"] == "resolved"
        assert {item["id"]: item["state"] for item in motion["poses"]} == {
            "p-swung": "resolved",
            "p-zero": "resolved",
        }
        assert motion["blocking"] == []
        assert motion["joint_generation"] == payload["joint_generation"] == 3
        assert motion["pose_generation"] == payload["pose_generation"] == 2
        assert str(payload["motion_ref"]).startswith("artifact:motion-status:sha256:")


class TestExitCodesAndStaleness:
    def test_an_unresolvable_outcome_blocks_in_both_modes(
        self,
        hinged: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = open_store(hinged)
        try:
            joints = JointSet(hinged, store)
            poses = PoseSet(hinged, store, joints)
            # A joint on a part the project does not carry: missing_part.
            joints.declare(
                {
                    "id": "j-ghost",
                    "kind": "revolute",
                    "parent": "base:hinge_bore",
                    "child": "ghost:pin",
                    "limits": {"min": -10.0, "max": 10.0},
                    "provenance": assumed(),
                }
            )
            # A pose orphaned AFTER declaration (§3): declare a joint, bind
            # it, withdraw the joint — the pose outcome names the joint.
            joints.declare(
                {
                    "id": "j-drop",
                    "kind": "revolute",
                    "parent": "base:hinge_bore",
                    "child": "phantom2:pin",
                    "limits": {"min": -10.0, "max": 10.0},
                    "provenance": assumed(),
                }
            )
            poses.declare({"id": "p-orphan", "joints": {"j-drop": 5.0}, "provenance": assumed()})
            joints.withdraw("j-drop", "superseded before it was ever built")
            MotionEvaluator(hinged, store).evaluate()
        finally:
            store.close()

        assert run(hinged.root, monkeypatch, "joints") == 1
        out = capsys.readouterr().out
        assert "UNRESOLVABLE" in out
        assert "j-ghost" in out
        assert "j-drop" in out  # the orphaned pose's detail names the joint

        assert run(hinged.root, monkeypatch, "joints", "--json") == 1
        motion = emitted(capsys)["motion"]
        by_id = {item["id"]: item for item in motion["joints"]}
        assert by_id["j-ghost"]["state"] == "unresolvable"
        assert by_id["j-ghost"]["reason"] == "missing_part"
        orphan = next(item for item in motion["poses"] if item["id"] == "p-orphan")
        assert orphan["state"] == "unresolvable"
        assert orphan["reason"] == "orphaned_pose"
        assert "j-drop" in orphan["detail"]
        assert set(motion["blocking"]) == {"j-ghost", "p-orphan"}

    def test_a_rebuild_shows_up_as_stale_not_as_a_new_number(
        self,
        hinged: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store: OpStore = open_store(hinged)
        try:
            script = (hinged.root / "parts" / "arm.py").read_text(encoding="utf-8")
            assert script == HINGE_PARTS["arm"]
            (hinged.root / "parts" / "arm.py").write_text(
                script.replace("radius=3.9", "radius=3.8"), encoding="utf-8"
            )
            build_part(Publisher(hinged, store), hinged, "arm")
        finally:
            store.close()

        # The verb SAYS the status is stale and still prints it — a rebuild
        # never silently repairs (or erases) recorded evidence.
        run(hinged.root, monkeypatch, "joints")
        out = capsys.readouterr().out
        assert "stale: arm rebuilt since this status was measured" in out
        assert "j-hinge" in out

        run(hinged.root, monkeypatch, "joints", "--json")
        assert emitted(capsys)["motion"]["stale"] == ["arm"]
