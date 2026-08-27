"""``KINEMATICS.md`` §6 (Stage 9A/9B): the joint, pose and motion-check tools.

Everything here is asserted through the *real* dispatcher, over real geometry,
on the ``test_assembly_tools`` precedent — what is tested is the surface a
model actually meets:

* the ten tools on both declared profiles (part + orchestrator, the 8C
  quartet decision applied unchanged), including every refusal the contract
  names (``invalid_joint`` / ``unknown_joint`` / ``cyclic_joint_graph``,
  ``invalid_pose`` / ``unknown_pose``, ``invalid_motion_check`` /
  ``unknown_motion_check``) — and the ``quick_edit``/``reviewer`` profiles
  being denied, which is what keeps a reviewer from writing the motion state
  it will be handed;
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

#: The Stage 9B motion-check triplet (KINEMATICS.md §4/§6).
TRIPLET: tuple[str, ...] = (
    "declare_motion_check",
    "update_motion_check",
    "read_motion_checks",
)

KINEMATICS_TOOLS: tuple[str, ...] = SEPTET + TRIPLET

REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)

# The _g9b mechanism's hinge pair, restated here rather than imported (the
# recorded rule: this suite's evidence must not shift when another suite's
# fixture does): a Ø8 bore through a plate, a Ø7.8 pin riding it — the
# arm/base minimum clearance over small swings is the radial air, 0.1 mm.
BASE_SRC = """plate = Box(40.0, 40.0, 6.0)
body = plate - Cylinder(radius=4.0, height=20.0)
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_bore")
part.geometry = body
"""

ARM_SRC = """arm_body = Cylinder(radius=3.9, height=18.0)
tag(arm_body.faces().filter_by(GeomType.CYLINDER)[0], "hinge_pin")
part.geometry = arm_body
"""

#: Pin/bore radial air: the sweep's real measured worst clearance.
RADIAL_AIR_MM = 0.1


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
    from hephaestus.core.motion import MOTION_OUTCOME_STATES, SWEEP_VERDICTS
    from hephaestus.core.project_store.constraints import ANCHOR_PATTERN
    from hephaestus.core.project_store.kinematics import (
        JOINT_ID_PATTERN,
        JOINT_KINDS,
        MOTION_CHECK_KINDS,
        SWEEP_SAMPLES_DEFAULT,
        SWEEP_SAMPLES_MAX,
    )

    assert tools_decl.JOINT_KINDS == JOINT_KINDS
    assert tools_decl.JOINT_ID_PATTERN == JOINT_ID_PATTERN
    assert tools_decl.MOTION_OUTCOME_STATES == MOTION_OUTCOME_STATES
    # KINEMATICS.md §1: joint anchors are the 8C anchor grammar, exactly — the
    # schema reuses the constraint anchor pattern, and both equal the store's.
    assert tools_decl.CONSTRAINT_ANCHOR_PATTERN == ANCHOR_PATTERN
    # KINEMATICS.md §4 (Stage 9B): the motion-check vocabulary, same rule.
    assert tools_decl.MOTION_CHECK_KINDS == MOTION_CHECK_KINDS
    assert tools_decl.SWEEP_VERDICTS == SWEEP_VERDICTS
    assert tools_decl.SWEEP_SAMPLES_DEFAULT == SWEEP_SAMPLES_DEFAULT
    assert tools_decl.SWEEP_SAMPLES_MAX == SWEEP_SAMPLES_MAX


def test_the_kinematics_tools_are_declared_on_the_canonical_pipeline_only() -> None:
    # KINEMATICS.md Stage 9A/9B (§6): the 8C quartet decision applied unchanged.
    for name in KINEMATICS_TOOLS:
        assert tools_decl.get_tool(name).profiles == ("part", "orchestrator"), name


@pytest.mark.parametrize("tool", KINEMATICS_TOOLS)
def test_a_reviewer_may_not_touch_the_motion_state_it_is_handed(
    project: Project, tool: str
) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(tool, {}, principal=REVIEWER)
    assert excinfo.value.reason == "scope_denied"


@pytest.mark.parametrize("tool", KINEMATICS_TOOLS)
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


# ==========================================================================
# Stage 9B: the motion-check triplet + the enriched check_motion result
# (KINEMATICS.md §4/§6)


def hinge(project: Project) -> None:
    """A real, sweepable mechanism: pin-in-bore hinge, both parts built."""
    (project.root / "parts" / "base.py").write_text(BASE_SRC, encoding="utf-8")
    (project.root / "parts" / "arm.py").write_text(ARM_SRC, encoding="utf-8")
    project.build("base", "arm")
    project.call(
        "declare_joint",
        joint(
            "j-hinge",
            kind="revolute",
            parent="base:hinge_bore",
            child="arm:hinge_pin",
            limits={"min": -90.0, "max": 90.0},
        ),
    )


def motion_check(check_id: str = "mc-air", **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": check_id,
        "kind": "sweep_clearance",
        "a": "arm",
        "b": "base",
        "min_mm": 0.05,
        "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
        "samples": 3,
        "provenance": {"assumed": True, "reason": "fixture clearance claim"},
    }
    entry.update(fields)
    return entry


def test_motion_check_lifecycle_is_three_generations(project: Project) -> None:
    hinge(project)
    declared = project.call("declare_motion_check", motion_check())
    assert declared["generation"] == 1
    assert declared["artifact_ref"].startswith("artifact:motion-checks:sha256:")
    assert declared["change"] == {
        "kind": "declare",
        "id": "mc-air",
        "patch": declared["entries"][0],
    }
    # Never evaluated is null — which is not "the sweep holds".
    assert declared["results"] is None and declared["results_ref"] is None

    revised = project.call(
        "update_motion_check",
        {"id": "mc-air", "patch": {"min_mm": 0.08}, "reason": "tightened the claim"},
    )
    assert revised["generation"] == 2
    assert revised["entries"][0]["min_mm"] == 0.08
    assert revised["change"]["reason"] == "tightened the claim"

    withdrawn = project.call(
        "update_motion_check",
        {"id": "mc-air", "patch": {"withdrawn": True}, "reason": "the claim was retired"},
    )
    assert withdrawn["generation"] == 3
    # Withdrawn, not erased: the entry and its reason stay in the projection.
    assert withdrawn["entries"][0]["withdrawn"] is True
    assert withdrawn["entries"][0]["withdrawn_reason"] == "the claim was retired"

    # …and every earlier generation is still readable through the engine.
    history = project.cad.motion_check_set().history()
    assert [state.generation for state in history] == [1, 2, 3]


def test_provenance_is_compelled_on_motion_checks(project: Project) -> None:
    hinge(project)
    entry = motion_check()
    del entry["provenance"]
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_motion_check", entry)
    assert excinfo.value.reason == "invalid_motion_check"
    assert "provenance" in excinfo.value.message
    assert project.call("read_motion_checks", {})["generation"] == 0


def test_a_sweep_over_an_undeclared_joint_is_refused(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_motion_check", motion_check(sweep={"j-ghost": {"from": 0, "to": 1}}))
    assert excinfo.value.reason == "invalid_motion_check"
    assert "j-ghost" in excinfo.value.message
    assert project.call("read_motion_checks", {})["generation"] == 0


def test_a_sweep_over_a_fixed_joint_is_refused(project: Project) -> None:
    """A 0-DOF joint has nothing to sweep — born-unevaluatable, refused now."""
    project.call("declare_joint", joint())  # the fixture's fixed widget/bracket mount
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_motion_check", motion_check(sweep={"j-mount": {"from": 0, "to": 1}}))
    assert excinfo.value.reason == "invalid_motion_check"
    assert "j-mount" in excinfo.value.message


def test_the_grid_total_cap_is_refused_naming_the_computed_total(project: Project) -> None:
    """KINEMATICS.md §4: 65 per axis is fine over one joint; 65² = 4225 is not."""
    hinge(project)
    project.call(
        "declare_joint",
        joint(
            "j-slide",
            kind="prismatic",
            parent="widget",
            child="bracket",
            limits={"min": 0.0, "max": 20.0},
        ),
    )
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "declare_motion_check",
            motion_check(
                sweep={"j-hinge": {"from": -10.0, "to": 10.0}, "j-slide": {"from": 0, "to": 5}},
                samples=65,
            ),
        )
    assert excinfo.value.reason == "invalid_motion_check"
    assert "4225" in excinfo.value.message
    assert project.call("read_motion_checks", {})["generation"] == 0


def test_patching_an_unknown_motion_check_is_unknown_motion_check(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "update_motion_check", {"id": "mc-nope", "patch": {"note": "n"}, "reason": "r"}
        )
    assert excinfo.value.reason == "unknown_motion_check"


def test_a_motion_check_withdrawal_carrying_field_edits_is_refused(project: Project) -> None:
    """Two acts, two generations: "stop claiming it" is not "the bound changed"."""
    hinge(project)
    project.call("declare_motion_check", motion_check())
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "update_motion_check",
            {"id": "mc-air", "patch": {"withdrawn": True, "min_mm": 9.0}, "reason": "both"},
        )
    assert excinfo.value.reason == "invalid_motion_check"
    assert project.call("read_motion_checks", {})["generation"] == 1


def test_check_motion_returns_real_sweep_results_and_projects_them(project: Project) -> None:
    """The enriched result (§6): MotionStatus + per-check §4 records, measured.

    The clearance is a real measurement over reloaded BReps placed by forward
    kinematics: the pin/bore radial air, 0.1 mm at every swing sample.
    """
    hinge(project)
    project.call("declare_motion_check", motion_check())  # min_mm 0.05 < 0.1
    result = project.call("check_motion", {})
    assert result["partial"] is False
    assert joint_row(result, "j-hinge")["state"] == "resolved"
    [record] = cast("list[Any]", result["results"])
    assert record["id"] == "mc-air"
    assert record["verdict"] == "holds_at_samples"
    assert record["samples_evaluated"] == 3 and record["grid_total"] == 3
    assert record["worst"]["measured"] == pytest.approx(RADIAL_AIR_MM, abs=1e-6)
    assert record["min_mm"] == 0.05 and record["unit"] == "mm"
    assert result["results_ref"].startswith("artifact:motion-results:sha256:")

    # Reading never measures — it returns THIS run's projected results.
    read = project.call("read_motion_checks", {})
    assert read["results"] == result["results"]
    assert read["results_ref"] == result["results_ref"]


def test_a_falsifying_sample_is_violated_by_name(project: Project) -> None:
    hinge(project)
    project.call("declare_motion_check", motion_check("mc-tight", min_mm=0.5))  # > 0.1 air
    result = project.call("check_motion", {})
    [record] = cast("list[Any]", result["results"])
    assert record["verdict"] == "violated"
    assert record["worst"]["measured"] == pytest.approx(RADIAL_AIR_MM, abs=1e-6)


def test_a_named_subset_is_evaluated_but_never_projected(project: Project) -> None:
    """The check_assembly rule: a projection covering some checks would report
    a set the project does not have."""
    hinge(project)
    project.call("declare_motion_check", motion_check())
    project.call("declare_motion_check", motion_check("mc-tight", min_mm=0.5))
    result = project.call("check_motion", {"ids": ["mc-air"]})
    assert result["partial"] is True
    assert result["artifact_ref"] is None and result["results_ref"] is None
    assert [record["id"] for record in cast("list[Any]", result["results"])] == ["mc-air"]
    # …and the projection still says "never evaluated".
    assert project.call("read_motion_checks", {})["results"] is None


def test_an_unknown_check_id_is_refused_naming_the_declared_ones(project: Project) -> None:
    hinge(project)
    project.call("declare_motion_check", motion_check())
    with pytest.raises(DispatchError) as excinfo:
        project.call("check_motion", {"ids": ["mc-ghost"]})
    assert excinfo.value.reason == "unknown_motion_check"
    assert "mc-air" in excinfo.value.message


def test_a_withdrawn_check_is_never_evaluated_but_its_last_result_stays(
    project: Project,
) -> None:
    hinge(project)
    project.call("declare_motion_check", motion_check())
    first = project.call("check_motion", {})
    assert [r["id"] for r in cast("list[Any]", first["results"])] == ["mc-air"]
    project.call(
        "update_motion_check",
        {"id": "mc-air", "patch": {"withdrawn": True}, "reason": "retired"},
    )
    # The last recorded result stays readable exactly as measured…
    read = project.call("read_motion_checks", {})
    assert read["entries"][0]["withdrawn"] is True
    assert [r["id"] for r in cast("list[Any]", read["results"])] == ["mc-air"]
    # …and a re-measure evaluates nothing (withdrawn: never evaluated).
    second = project.call("check_motion", {})
    assert second["results"] == []
