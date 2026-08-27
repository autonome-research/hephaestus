# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9A: the Stage 9A tool surface through dispatch on both profiles.

Two gate clauses, both at the surface a model actually meets (the
``tests/stage8c/test_g8c_declaration.py`` precedent — the exhaustive per-tool
coverage lives in ``server/tests/test_motion_tools.py``; this file is the gate
evidence, driven through the **real dispatcher** over **real built geometry**):

* *the tool surface through dispatch on both profiles* — the seven
  ``KINEMATICS.md`` §6 Stage 9A tools are declared on exactly ``part`` +
  ``orchestrator`` (the 8C quartet decision applied unchanged), and both
  profiles really drive them. A joint spans parts by nature, so the part
  session's declaration names ANOTHER part — scoping it to one would gut the
  feature — and the reviewer, who is handed the resulting ``MotionStatus``,
  is refused every one of the seven by ``scope_denied``;
* *staleness, end to end* — a rebuild of a forest part through the model's own
  ``build_part`` restales the motion projection every read reports (the stale
  status stays readable: stale is never "never evaluated"), and re-evaluating
  through ``check_motion`` FLIPS the formerly resolved joint to
  ``misaligned_joint_anchors`` — a rebuild neither repairs recorded evidence
  nor hides that the world moved under it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g9a import HINGE_PARTS
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import DispatchError, Principal, ToolDispatcher
from hephaestus.contract import tools_decl
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.tools_fixture import Project

SEPTET: tuple[str, ...] = (
    "declare_joint",
    "update_joint",
    "read_joints",
    "declare_pose",
    "update_pose",
    "read_poses",
    "check_motion",
)

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)
PART_BASE = Principal(session_id="pb", profile="part", part="base")
REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)

#: The arm with its pin moved 0.5 mm off the bore axis — beyond
#: ``JOINT_FRAME_EPS_MM`` — so a rebuild flips the hinge's resolution to
#: ``misaligned_joint_anchors`` through geometry alone (no declaration moves).
ARM_OFFSET_SRC = HINGE_PARTS["arm"].replace(
    "pin = Cylinder(radius=3.9, height=18.0)",
    "pin = Pos(0.5, 0.0, 0.0) * Cylinder(radius=3.9, height=18.0)",
)


def make_motion_project(root: Path) -> Project:
    """The ``_g9a`` hinge pair behind the real dispatcher.

    Scaffolded here rather than through another suite's fixture parts (the
    ``_g8c.make_assembly_project`` rationale): a gate assertion must not be
    satisfiable by a change elsewhere. The minimal ledger is seeded because
    ``VALIDATION.md`` §2 refuses ``build_part`` without one — a precondition
    of these clauses, never their subject.
    """
    from hephaestus.testing.ledger import seed_minimal_ledger

    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "mech"\n', encoding="utf-8")
    for name, source in HINGE_PARTS.items():
        (root / "parts" / f"{name}.py").write_text(source, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    dispatcher = ToolDispatcher(ProjectStore(layout, store), cad=cad)
    seed_minimal_ledger(cad)
    return Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])


@pytest.fixture
def hinge(tmp_path: Path) -> Iterator[Project]:
    """``base`` + ``arm`` built through the model's own ``build_part``."""
    project = make_motion_project(tmp_path / "proj")
    try:
        for name in ("base", "arm"):
            result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
            assert result["status"] == "ok", result
        yield project
    finally:
        project.close()


def hinge_entry(**fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "j-hinge",
        "kind": "revolute",
        "parent": "base:hinge_bore",
        "child": "arm:hinge_pin",
        "limits": {"min": -90.0, "max": 90.0},
        "provenance": {"requirement": "r-1"},
    }
    entry.update(fields)
    return entry


def joint_row(motion: dict[str, Any], joint_id: str) -> dict[str, Any]:
    for item in cast("list[Any]", motion["joints"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == joint_id:
            return row
    raise AssertionError(f"no joint {joint_id} in {motion}")


def pose_row(motion: dict[str, Any], pose_id: str) -> dict[str, Any]:
    for item in cast("list[Any]", motion["poses"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == pose_id:
            return row
    raise AssertionError(f"no pose {pose_id} in {motion}")


# ==========================================================================
# the septet, on both profiles


def test_the_septet_is_reachable_on_both_declared_profiles(hinge: Project) -> None:
    """All seven tools, driven by a part session and by the orchestrator.

    The part principal is ``base``; the joint it declares rides on ``arm`` —
    that is the point of the clause (``KINEMATICS.md`` §6, the 8C quartet
    decision unchanged): a cross-part joint cannot be authored by anyone who
    is only allowed to talk about one part.
    """
    for name in SEPTET:
        assert tools_decl.get_tool(name).profiles == ("part", "orchestrator"), name

    # The part session declares and revises the cross-part joint…
    declared = cast(
        "dict[str, Any]", hinge.call("declare_joint", hinge_entry(), principal=PART_BASE)
    )
    assert declared["status"] == "ok" and declared["generation"] == 1
    assert declared["motion"] is None  # never evaluated, which is not a pass
    revised = cast(
        "dict[str, Any]",
        hinge.call(
            "update_joint",
            {
                "id": "j-hinge",
                "patch": {"limits": {"min": -90.0, "max": 45.0}},
                "reason": "the paddle fouls the stop past 45",
            },
            principal=PART_BASE,
        ),
    )
    assert revised["generation"] == 2
    assert cast("dict[str, Any]", revised["change"])["reason"] == (
        "the paddle fouls the stop past 45"
    )

    # …the orchestrator reads exactly what the part session wrote…
    read = cast("dict[str, Any]", hinge.call("read_joints", {}, principal=ORCH))
    entries = [cast("dict[str, Any]", item) for item in cast("list[Any]", read["entries"])]
    assert cast("dict[str, Any]", entries[0]["limits"])["max"] == pytest.approx(45.0)

    # …the part session names a pose the orchestrator then revises…
    posed = cast(
        "dict[str, Any]",
        hinge.call(
            "declare_pose",
            {
                "id": "p-swung",
                "joints": {"j-hinge": -90.0},
                "provenance": {"requirement": "r-1"},
            },
            principal=PART_BASE,
        ),
    )
    assert posed["generation"] == 1
    reposed = cast(
        "dict[str, Any]",
        hinge.call(
            "update_pose",
            {
                "id": "p-swung",
                "patch": {"joints": {"j-hinge": -45.0}},
                "reason": "swing retargeted to the revised limit",
            },
            principal=ORCH,
        ),
    )
    assert reposed["generation"] == 2
    read_poses = cast("dict[str, Any]", hinge.call("read_poses", {}, principal=PART_BASE))
    pose_entries = [
        cast("dict[str, Any]", item) for item in cast("list[Any]", read_poses["entries"])
    ]
    assert cast("dict[str, Any]", pose_entries[0]["joints"]) == {"j-hinge": -45.0}

    # …and BOTH profiles may evaluate: the measurement is the engine's either way.
    checked = cast("dict[str, Any]", hinge.call("check_motion", {}, principal=PART_BASE))
    assert checked["status"] == "ok"
    motion = cast("dict[str, Any]", checked["motion"])
    assert joint_row(motion, "j-hinge")["state"] == "resolved"
    assert pose_row(motion, "p-swung")["state"] == "resolved"
    assert str(checked["artifact_ref"]).startswith("artifact:motion-status:sha256:")
    rechecked = cast("dict[str, Any]", hinge.call("check_motion", {}, principal=ORCH))
    assert cast("dict[str, Any]", rechecked["motion"])["joints"] == motion["joints"]

    # The evaluation is projected: the next read reports it without measuring.
    read_after = cast("dict[str, Any]", hinge.call("read_joints", {}, principal=ORCH))
    assert read_after["motion_ref"] == rechecked["artifact_ref"]


@pytest.mark.parametrize("tool", SEPTET)
def test_a_reviewer_may_not_write_the_motion_state_it_judges(hinge: Project, tool: str) -> None:
    """The reviewer reads the ``MotionStatus``; it does not get to author it."""
    with pytest.raises(DispatchError) as excinfo:
        hinge.call(tool, {}, principal=REVIEWER)
    assert excinfo.value.reason == "scope_denied"


def test_a_pose_bound_constraint_declares_and_evaluates_through_dispatch(
    hinge: Project,
) -> None:
    """``KINEMATICS.md`` §3 through the 8C constraint surface, end to end.

    The ``poses`` field must be *declarable through the tool contract* — the
    schema admits it, the store validates it, and ``check_assembly`` evaluates
    the entry at the bound pose (the engine-level shape is pinned in
    ``test_pose_bound_constraints.py``; this is the surface a model meets).
    """
    hinge.call("declare_joint", hinge_entry(), principal=PART_BASE)
    hinge.call(
        "declare_pose",
        {"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": {"requirement": "r-1"}},
        principal=PART_BASE,
    )
    declared = cast(
        "dict[str, Any]",
        hinge.call(
            "declare_constraint",
            {
                "id": "c-swing",
                "kind": "clearance_min",
                "a": "base",
                "b": "arm",
                "value_mm": 0.05,
                "poses": ["p-swung"],
                "provenance": {"requirement": "r-1"},
            },
            principal=ORCH,
        ),
    )
    entries = [cast("dict[str, Any]", item) for item in cast("list[Any]", declared["entries"])]
    assert entries[0]["poses"] == ["p-swung"]

    checked = cast("dict[str, Any]", hinge.call("check_assembly", {}, principal=ORCH))
    rows = cast("list[Any]", cast("dict[str, Any]", checked["assembly"])["constraints"])
    row = cast("dict[str, Any]", rows[0])
    assert row["id"] == "c-swing"
    # At -90 deg the paddle lands exactly on the stop: 0.0 mm < 0.05 mm.
    assert row["state"] == "violated"
    table = [cast("dict[str, Any]", item) for item in cast("list[Any]", row["pose_residuals"])]
    assert [(item["pose_id"], item["verdict"]) for item in table] == [("p-swung", "violated")]


# ==========================================================================
# staleness, end to end: rebuild -> stale projection -> flipped evaluation


def test_a_rebuild_restales_the_projection_and_reevaluation_flips_the_joint(
    hinge: Project,
) -> None:
    hinge.call("declare_joint", hinge_entry(), principal=PART_BASE)
    hinge.call(
        "declare_pose",
        {"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": {"requirement": "r-1"}},
        principal=PART_BASE,
    )
    first = cast("dict[str, Any]", hinge.call("check_motion", {}, principal=ORCH))
    first_motion = cast("dict[str, Any]", first["motion"])
    assert joint_row(first_motion, "j-hinge")["state"] == "resolved"
    assert pose_row(first_motion, "p-swung")["state"] == "resolved"
    assert first_motion["stale"] == []

    # An ordinary script edit moves the pin 0.5 mm off the bore axis, and the
    # rebuild goes through the model's own build_part — the whole real path.
    (hinge.root / "parts" / "arm.py").write_text(ARM_OFFSET_SRC, encoding="utf-8")
    rebuilt = cast("dict[str, Any]", hinge.call("build_part", {"name": "arm"}, principal=ORCH))
    assert rebuilt["status"] == "ok", rebuilt

    # The projection is STALE, said so on every read — and the recorded status
    # is still the old evidence, readable, not erased and not "never evaluated".
    read = cast("dict[str, Any]", hinge.call("read_joints", {}, principal=ORCH))
    stale_motion = cast("dict[str, Any]", read["motion"])
    assert stale_motion["stale"] == ["arm"]
    assert joint_row(stale_motion, "j-hinge")["state"] == "resolved"

    # Re-evaluation flips the outcome: the child anchor's axis now diverges
    # beyond JOINT_FRAME_EPS_MM, and the pose that binds the joint goes with it.
    second = cast("dict[str, Any]", hinge.call("check_motion", {}, principal=ORCH))
    second_motion = cast("dict[str, Any]", second["motion"])
    flipped = joint_row(second_motion, "j-hinge")
    assert flipped["state"] == "unresolvable"
    assert flipped["reason"] == "misaligned_joint_anchors"
    poisoned = pose_row(second_motion, "p-swung")
    assert poisoned["state"] == "unresolvable"
    assert poisoned["reason"] == "unresolvable_joint"
    assert "j-hinge" in str(poisoned["detail"])
    assert set(cast("list[Any]", second_motion["blocking"])) == {"j-hinge", "p-swung"}
    assert second_motion["stale"] == []
    assert second["artifact_ref"] != first["artifact_ref"]
