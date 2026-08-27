"""``KINEMATICS.md`` §6 (Stage 9A): the joint and pose quartets plus ``check_motion``.

Everything here is asserted through the *real* dispatcher, over real geometry,
on the ``test_assembly_tools`` precedent — what is tested is the surface a
model actually meets:

* the seven tools on both declared profiles (part + orchestrator, the 8C
  quartet decision applied unchanged), including every refusal the contract
  names (``invalid_joint`` / ``unknown_joint`` / ``cyclic_joint_graph``,
  ``invalid_pose`` / ``unknown_pose``) — and the ``quick_edit``/``reviewer``
  profiles being denied, which is what keeps a reviewer from writing the
  motion state it will be handed;
* withdrawal as a new generation that erases nothing, and a pose that binds a
  withdrawn joint becoming ``orphaned_pose`` at evaluation rather than being
  erased or re-refused;
* ``check_motion`` returning the two-section ``MotionStatus`` measured against
  the parts' current build artifacts, projected so a later read sees it, and
  restaled when a forest part is rebuilt;
* the declared vocabulary staying byte-equal to the engine's own tables (the
  drift test the contract module points at).

The fixture geometry is deliberately concrete: ``widget`` and ``bracket`` are
real built boxes, so a ``fixed`` joint between them really resolves through
the 8C anchoring path — a "resolved" assertion here is a measurement, not a
mock.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.contract import tools_decl
from hephaestus.testing.tools_fixture import (
    PART_WIDGET,
    QUICK_WIDGET,
    WIDGET_SRC,
    Project,
    make_project,
)

SEPTET: tuple[str, ...] = (
    "declare_joint",
    "update_joint",
    "read_joints",
    "declare_pose",
    "update_pose",
    "read_poses",
    "check_motion",
)

REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    proj = make_project(tmp_path / "proj")
    try:
        yield proj
    finally:
        proj.close()


def joint(
    joint_id: str = "j-mount",
    *,
    kind: str = "fixed",
    parent: str = "widget",
    child: str = "bracket",
    **fields: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": joint_id,
        "kind": kind,
        "parent": parent,
        "child": child,
        "provenance": {"assumed": True, "reason": "fixture mount"},
    }
    entry.update(fields)
    return entry


def pose(pose_id: str = "p-zero", *, joints: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "id": pose_id,
        "joints": joints if joints is not None else {},
        "provenance": {"assumed": True, "reason": "fixture pose"},
    }


def joint_row(result: dict[str, Any], joint_id: str) -> dict[str, Any]:
    motion = cast("dict[str, Any]", result["motion"])
    for item in cast("list[Any]", motion["joints"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == joint_id:
            return row
    raise AssertionError(f"no joint {joint_id} in {motion}")


def pose_row(result: dict[str, Any], pose_id: str) -> dict[str, Any]:
    motion = cast("dict[str, Any]", result["motion"])
    for item in cast("list[Any]", motion["poses"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == pose_id:
            return row
    raise AssertionError(f"no pose {pose_id} in {motion}")


# ==========================================================================
# the declaration: vocabulary, availability, profiles


def test_declared_joint_vocabulary_matches_engine() -> None:
    """The schema restates the engine's tables; drift between them is a bug here.

    ``tools_decl`` cannot import the core (the contract package is pure
    declaration), so the equality that keeps the tool schema honest is asserted
    rather than enforced by construction — the 8C constraint-vocabulary rule.
    """
    from hephaestus.core.motion import MOTION_OUTCOME_STATES
    from hephaestus.core.project_store.constraints import ANCHOR_PATTERN
    from hephaestus.core.project_store.kinematics import JOINT_ID_PATTERN, JOINT_KINDS

    assert tools_decl.JOINT_KINDS == JOINT_KINDS
    assert tools_decl.JOINT_ID_PATTERN == JOINT_ID_PATTERN
    assert tools_decl.MOTION_OUTCOME_STATES == MOTION_OUTCOME_STATES
    # KINEMATICS.md §1: joint anchors are the 8C anchor grammar, exactly — the
    # schema reuses the constraint anchor pattern, and both equal the store's.
    assert tools_decl.CONSTRAINT_ANCHOR_PATTERN == ANCHOR_PATTERN


def test_the_septet_is_declared_on_the_canonical_pipeline_only() -> None:
    # KINEMATICS.md Stage 9A (§6): the 8C quartet decision applied unchanged.
    for name in SEPTET:
        assert tools_decl.get_tool(name).profiles == ("part", "orchestrator"), name


@pytest.mark.parametrize("tool", SEPTET)
def test_a_reviewer_may_not_touch_the_motion_state_it_is_handed(
    project: Project, tool: str
) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(tool, {}, principal=REVIEWER)
    assert excinfo.value.reason == "scope_denied"


@pytest.mark.parametrize("tool", SEPTET)
def test_a_quick_edit_session_declares_no_kinematics(project: Project, tool: str) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(tool, {}, principal=QUICK_WIDGET)
    assert excinfo.value.reason == "scope_denied"


def test_a_part_session_may_declare_a_joint_touching_another_part(project: Project) -> None:
    """A joint spans parts by nature; scoping it to one would gut it."""
    result = project.call("declare_joint", joint(), principal=PART_WIDGET)
    assert result["generation"] == 1
    assert [entry["id"] for entry in result["entries"]] == ["j-mount"]
    assert project.call("read_joints", {}, principal=PART_WIDGET)["generation"] == 1


# ==========================================================================
# generations: declare -> update -> withdraw, nothing erased


def test_declare_update_withdraw_are_three_generations(project: Project) -> None:
    declared = project.call("declare_joint", joint())
    assert declared["generation"] == 1
    assert declared["artifact_ref"].startswith("artifact:joints:sha256:")
    assert declared["change"] == {
        "kind": "declare",
        "id": "j-mount",
        "patch": declared["entries"][0],
    }

    revised = project.call(
        "update_joint",
        {"id": "j-mount", "patch": {"note": "per drawing 7"}, "reason": "cited the drawing"},
    )
    assert revised["generation"] == 2
    assert revised["entries"][0]["note"] == "per drawing 7"
    assert revised["change"]["reason"] == "cited the drawing"

    withdrawn = project.call(
        "update_joint",
        {"id": "j-mount", "patch": {"withdrawn": True}, "reason": "the bracket was deleted"},
    )
    assert withdrawn["generation"] == 3
    # Withdrawn, not erased: the entry and its reason stay in the projection.
    assert withdrawn["entries"][0]["withdrawn"] is True
    assert withdrawn["entries"][0]["withdrawn_reason"] == "the bracket was deleted"

    # …and every earlier generation is still readable through the engine.
    history = project.cad.joint_set().history()
    assert [state.generation for state in history] == [1, 2, 3]
    assert history[0].entries[0].note is None


def test_pose_lifecycle_mirrors_the_joint_one(project: Project) -> None:
    project.call("declare_joint", joint(kind="revolute", limits={"min": -5.0, "max": 150.0}))
    declared = project.call("declare_pose", pose(joints={"j-mount": 10.0}))
    assert declared["generation"] == 1
    assert declared["artifact_ref"].startswith("artifact:poses:sha256:")

    revised = project.call(
        "update_pose",
        {"id": "p-zero", "patch": {"joints": {"j-mount": 20.0}}, "reason": "moved the stop"},
    )
    assert revised["generation"] == 2
    assert revised["entries"][0]["joints"] == {"j-mount": 20.0}

    withdrawn = project.call(
        "update_pose",
        {"id": "p-zero", "patch": {"withdrawn": True}, "reason": "no longer a claim"},
    )
    assert withdrawn["generation"] == 3
    assert withdrawn["entries"][0]["withdrawn"] is True
    assert withdrawn["entries"][0]["withdrawn_reason"] == "no longer a claim"


# ==========================================================================
# refusals — the named machine tokens, and nothing written


def test_provenance_is_compelled_on_joints(project: Project) -> None:
    entry = joint()
    del entry["provenance"]
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_joint", entry)
    assert excinfo.value.reason == "invalid_joint"
    assert "provenance" in excinfo.value.message
    assert project.call("read_joints", {})["generation"] == 0


def test_provenance_is_compelled_on_poses(project: Project) -> None:
    entry = pose()
    del entry["provenance"]
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_pose", entry)
    assert excinfo.value.reason == "invalid_pose"
    assert project.call("read_poses", {})["generation"] == 0


def test_a_slash_bearing_anchor_is_refused_by_the_two_grammars_rule(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_joint", joint(child="bracket/face"))
    assert excinfo.value.reason == "invalid_joint"
    assert "slash" in excinfo.value.message


def test_a_dof_kind_requires_limits(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_joint", joint(kind="revolute"))
    assert excinfo.value.reason == "invalid_joint"
    assert "limits" in excinfo.value.message


def test_a_cycle_is_refused_with_the_cycle_named(project: Project) -> None:
    project.call("declare_joint", joint("j-a", parent="widget", child="bracket"))
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_joint", joint("j-b", parent="bracket", child="widget"))
    assert excinfo.value.reason == "cyclic_joint_graph"
    assert "widget" in excinfo.value.message and "bracket" in excinfo.value.message
    assert project.call("read_joints", {})["generation"] == 1


def test_patching_an_unknown_joint_is_unknown_joint(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("update_joint", {"id": "j-nope", "patch": {"note": "n"}, "reason": "r"})
    assert excinfo.value.reason == "unknown_joint"


def test_patching_an_unknown_pose_is_unknown_pose(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("update_pose", {"id": "p-nope", "patch": {"note": "n"}, "reason": "r"})
    assert excinfo.value.reason == "unknown_pose"


def test_a_withdrawal_carrying_field_edits_is_refused(project: Project) -> None:
    """Two acts, two generations: "stop claiming it" is not "the note changed"."""
    project.call("declare_joint", joint())
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "update_joint",
            {"id": "j-mount", "patch": {"withdrawn": True, "note": "bye"}, "reason": "both"},
        )
    assert excinfo.value.reason == "invalid_joint"
    assert project.call("read_joints", {})["generation"] == 1


def test_a_pose_may_not_bind_an_undeclared_joint(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_pose", pose(joints={"j-ghost": 1.0}))
    assert excinfo.value.reason == "invalid_pose"
    assert "j-ghost" in excinfo.value.message
    assert project.call("read_poses", {})["generation"] == 0


# ==========================================================================
# evaluation: real geometry, both sections, projected and restaled


def test_a_resolved_joint_is_measured_not_asserted(project: Project) -> None:
    project.build("widget", "bracket")
    project.call("declare_joint", joint())
    project.call("declare_pose", pose())
    result = project.call("check_motion", {})
    row = joint_row(result, "j-mount")
    assert row["state"] == "resolved"
    assert row["reason"] is None and row["detail"] is None
    assert row["parent"]["rule"] == "part"
    assert row["parent"]["artifact_ref"].startswith("artifact:")
    assert pose_row(result, "p-zero")["state"] == "resolved"
    motion = cast("dict[str, Any]", result["motion"])
    assert motion["blocking"] == []
    assert motion["counts"] == {
        "joints": {"resolved": 1, "unresolvable": 0},
        "poses": {"resolved": 1, "unresolvable": 0},
    }
    assert result["artifact_ref"].startswith("artifact:motion-status:sha256:")


def test_an_unbuilt_part_is_unresolvable_and_blocking(project: Project) -> None:
    project.build("widget")  # bracket never built: the joint cannot resolve
    project.call("declare_joint", joint())
    result = project.call("check_motion", {})
    row = joint_row(result, "j-mount")
    assert row["state"] == "unresolvable"
    assert row["reason"] == "no_current_build"
    # …and it still blocks: an unchecked joint is not a resolved one.
    assert cast("dict[str, Any]", result["motion"])["blocking"] == ["j-mount"]


def test_a_pose_binding_a_withdrawn_joint_is_orphaned_not_erased(project: Project) -> None:
    project.build("widget", "bracket")
    project.call("declare_joint", joint(kind="revolute", limits={"min": -5.0, "max": 150.0}))
    project.call("declare_pose", pose(joints={"j-mount": 10.0}))
    project.call(
        "update_joint",
        {"id": "j-mount", "patch": {"withdrawn": True}, "reason": "redesigned the mount"},
    )
    result = project.call("check_motion", {})
    # The withdrawn joint is never evaluated — withdrawal is not a failure —
    # which is exactly why the pose that still names it is a per-POSE state.
    motion = cast("dict[str, Any]", result["motion"])
    assert motion["joints"] == []
    row = pose_row(result, "p-zero")
    assert row["state"] == "unresolvable"
    assert row["reason"] == "orphaned_pose"
    assert "j-mount" in row["detail"]
    assert motion["blocking"] == ["p-zero"]


def test_reading_never_measures(project: Project) -> None:
    project.build("widget", "bracket")
    project.call("declare_joint", joint())
    # Never evaluated is null — which is not "the joints resolve".
    assert project.call("read_joints", {})["motion"] is None
    assert project.call("read_poses", {})["motion"] is None

    project.call("check_motion", {})
    read = project.call("read_joints", {})
    motion = cast("dict[str, Any]", read["motion"])
    assert motion["counts"]["joints"]["resolved"] == 1
    assert read["motion_ref"].startswith("artifact:motion-status:sha256:")
    assert project.call("read_poses", {})["motion_ref"] == read["motion_ref"]


def test_a_rebuild_of_a_forest_part_marks_the_projection_stale(project: Project) -> None:
    project.build("widget", "bracket")
    project.call("declare_joint", joint())
    checked = project.call("check_motion", {})
    assert cast("dict[str, Any]", checked["motion"])["stale"] == []
    # A rebuild that moves the geometry moves the artifact, and the projection
    # says so rather than reporting a resolution of the previous shape.
    (project.root / "parts" / "widget.py").write_text(
        WIDGET_SRC.replace("Box(p.width, 20.0, hc.wall)", "Box(p.width, 25.0, hc.wall)"),
        encoding="utf-8",
    )
    project.build("widget")
    read = project.call("read_joints", {})
    assert cast("dict[str, Any]", read["motion"])["stale"] == ["widget"]
