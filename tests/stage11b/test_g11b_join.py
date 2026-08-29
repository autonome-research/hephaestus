"""G11B clauses 16, 18 and 19: the join, end to end, through the existing paths.

This is the clause the sub-stage exists for, and the one the placement bug made
unreachable: a motor seated on a pad is not at the part origin, so if interface
tags only resolved at the origin the mechanism would have been inoperative for
its own motivating example.

Nothing here is new addressing. The constraint is an ordinary 8C ``coincident``
whose ``b`` anchor happens to be a tag a pasted fragment emitted, and the joint
is an ordinary Stage 9 ``revolute`` — both under ``ANCHOR_PATTERN`` unchanged,
both resolved by the one ``AnchorResolver`` that ``KINEMATICS.md`` §2 requires
joints and constraints to share. The two anchor forms §2.4 names are both here:
the component *inside* the consumer's part (same-part anchors, the bolted-on
motor) and the component as its own part file (cross-part).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from _g11b import (
    GANTRY_SRC,
    HUB_SRC,
    MOTOR_SRC,
    PAD_TOP_Z_MM,
    SEAT_POS,
    build_all,
    check,
    declare,
    fragment_for,
    make_join_project,
    outcome,
    requires_bwrap,
    rewrite,
    store_ops,
)
from hephaestus.testing.tools_fixture import Project

pytestmark = requires_bwrap

#: How far the pad's top face moves when the plate is thickened by 2 mm: the
#: exact out-of-plane gap the coincidence then measures.
PAD_LIFT_MM = 1.0


def _fragment(tmp_path: Path, instance: str, pos: dict[str, float] | None) -> tuple[str, str]:
    """``(fragment, instance name)`` from the REAL tool, sandbox and all."""
    ops = store_ops(tmp_path / f"reg-{instance}")
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=pos, instance=instance)
    fragment = cast("str", result["script_fragment"])
    emitted = cast("list[str]", result["interfaces"])
    assert emitted == [
        f"{instance}__{name}" for name in ("mount_face", "shaft", "shaft_ring", "rail", "envelope")
    ]
    return fragment, _prefix_of(fragment)


def _prefix_of(fragment: str) -> str:
    match = re.search(r"^#   (_\S+) into part\.geometry", fragment, re.M)
    assert match is not None, fragment
    return match.group(1)


def _gantry(fragment: str, prefix: str, *, pad_z: float = 8.0) -> str:
    return GANTRY_SRC.format(fragment=fragment, instance=prefix, pad_z=pad_z)


# ==========================================================================
# clause 16 — the 8C join, end to end, in ONE part


@pytest.fixture
def seated(tmp_path: Path) -> tuple[Project, str, str]:
    """A ``gantry_plate`` with a component seated on its pad at a non-zero pos."""
    fragment, prefix = _fragment(tmp_path, "motor_a", dict(SEAT_POS))
    project = make_join_project(tmp_path / "project", {"gantry_plate": _gantry(fragment, prefix)})
    build_all(project, "gantry_plate")
    return project, fragment, prefix


def test_a_seated_component_satisfies_a_coincident_constraint(
    seated: tuple[Project, str, str],
) -> None:
    """Both anchors name the same part, which is the correct model of a bolted-on motor.

    The instance is placed at a non-zero translation *and* rotation, so this row
    is exactly the one that would have been ``unresolvable`` under the first
    draft of §2 — the tag would have named the unplaced body local and
    ``resolve_placements`` matches with the location-sensitive ``IsSame``.
    """
    project, _fragment_text, _prefix = seated
    declare(
        project,
        "c-motor-seats",
        "coincident",
        "gantry_plate:motor_pad",
        "gantry_plate:motor_a__mount_face",
        tol_mm=0.05,
    )
    row = outcome(check(project), "c-motor-seats")
    assert row["state"] == "satisfied", row
    assert cast("dict[str, Any]", row["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)


def test_moving_the_pad_flips_it_to_violated_with_the_measured_gap(
    seated: tuple[Project, str, str],
) -> None:
    """A geometry edit, not a declaration edit: the constraint is untouched."""
    project, fragment, prefix = seated
    declare(
        project,
        "c-motor-seats",
        "coincident",
        "gantry_plate:motor_pad",
        "gantry_plate:motor_a__mount_face",
        tol_mm=0.05,
    )
    assert outcome(check(project), "c-motor-seats")["state"] == "satisfied"

    rewrite(project, "gantry_plate", _gantry(fragment, prefix, pad_z=8.0 + 2 * PAD_LIFT_MM))
    build_all(project, "gantry_plate")
    row = outcome(check(project), "c-motor-seats")
    assert row["state"] == "violated", row
    residual = cast("dict[str, Any]", row["residual"])
    assert residual["measured"] == pytest.approx(PAD_LIFT_MM, abs=1e-9)
    assert residual["unit"] == "mm"


def test_deleting_the_instance_makes_it_unresolvable_not_violated(
    seated: tuple[Project, str, str],
) -> None:
    """``dangling_selector``, and specifically NOT ``violated``.

    A constraint whose tag disappeared in an edit has not been checked, and
    reporting "not checked" as "violated" would be as dishonest as reporting it
    as "satisfied" (``ASSEMBLY.md`` §2, the taxonomy at ``assembly.py:161-170``).
    """
    project, _fragment_text, _prefix = seated
    declare(
        project,
        "c-motor-seats",
        "coincident",
        "gantry_plate:motor_pad",
        "gantry_plate:motor_a__mount_face",
        tol_mm=0.05,
    )
    assert outcome(check(project), "c-motor-seats")["state"] == "satisfied"

    rewrite(
        project,
        "gantry_plate",
        "pad = Box(hc.PAD_XY, 40.0, 8.0)\n"
        'tag(pad.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "motor_pad")\n'
        "part.geometry = pad\n",
    )
    build_all(project, "gantry_plate")
    row = outcome(check(project), "c-motor-seats")
    assert row["state"] == "unresolvable", row
    assert row["reason"] == "dangling_selector"


def test_the_pad_top_is_where_the_fixture_says_it_is(
    seated: tuple[Project, str, str],
) -> None:
    """A precondition made explicit, so a fixture drift cannot pass as a pass."""
    project, _fragment_text, _prefix = seated
    declare(
        project,
        "c-pad-height",
        "distance",
        "gantry_plate:motor_pad",
        "gantry_plate:motor_a__mount_face",
        value_mm=0.0,
        tol_mm=1e-6,
    )
    row = outcome(check(project), "c-pad-height")
    assert row["state"] == "satisfied", row
    assert PAD_TOP_Z_MM == 4.0


# ==========================================================================
# clause 19 — the cross-part form, through the same resolver


def test_a_component_instanced_as_its_own_part_anchors_cross_part(tmp_path: Path) -> None:
    """No anchor-grammar change: ``ANCHOR_PATTERN`` never learned about ``__``."""
    from hephaestus.core.project_store.constraints import ANCHOR_PATTERN

    fragment, prefix = _fragment(tmp_path, "motor_b", dict(SEAT_POS))
    project = make_join_project(
        tmp_path / "project",
        {
            "gantry_plate": "pad = Box(hc.PAD_XY, 40.0, 8.0)\n"
            'tag(pad.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "motor_pad")\n'
            "part.geometry = pad\n",
            "motor": MOTOR_SRC.format(fragment=fragment, instance=prefix),
        },
    )
    build_all(project, "gantry_plate", "motor")
    anchor = "motor:motor_b__mount_face"
    assert re.match(ANCHOR_PATTERN, anchor)
    declare(project, "c-cross", "coincident", "gantry_plate:motor_pad", anchor, tol_mm=0.05)
    row = outcome(check(project), "c-cross")
    assert row["state"] == "satisfied", row
    assert cast("dict[str, Any]", row["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)


# ==========================================================================
# clause 18 — the Stage 9 join


def _motion(project: Project) -> dict[str, Any]:
    result = cast("dict[str, Any]", project.call("check_motion", {}))
    assert result["status"] == "ok", result
    return cast("dict[str, Any]", result["motion"])


def _joint_row(motion: dict[str, Any], joint_id: str) -> dict[str, Any]:
    for item in cast("list[Any]", motion["joints"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == joint_id:
            return row
    raise AssertionError(f"no joint {joint_id!r} in {motion}")


@pytest.fixture
def hinged(tmp_path: Path) -> Project:
    """A motor part whose boss is coaxial with a hub's bore."""
    fragment, prefix = _fragment(tmp_path, "motor_c", dict(SEAT_POS))
    project = make_join_project(
        tmp_path / "project",
        {"motor": MOTOR_SRC.format(fragment=fragment, instance=prefix), "hub": HUB_SRC},
    )
    build_all(project, "motor", "hub")
    return project


def _declare_joint(project: Project, joint_id: str, parent: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        project.call(
            "declare_joint",
            {
                "id": joint_id,
                "kind": "revolute",
                "parent": parent,
                "child": "hub:hub_bore",
                "limits": {"min": -90.0, "max": 90.0},
                "provenance": {"assumed": True, "reason": "fixture"},
            },
        ),
    )


def test_a_revolute_on_a_cylindrical_interface_resolves(hinged: Project) -> None:
    """A ``cylindrical_face`` interface names an axis, which is what a revolute needs."""
    assert _declare_joint(hinged, "j-shaft", "motor:motor_c__shaft")["status"] == "ok"
    row = _joint_row(_motion(hinged), "j-shaft")
    assert row["state"] == "resolved", row


def test_the_same_joint_on_a_planar_interface_is_refused_for_shape_class(
    hinged: Project,
) -> None:
    """Refused, never silently framed (``KINEMATICS.md:80-85``).

    A planar face names a direction, not an axis. Guessing one would be the
    ``mating_features`` failure wearing a kinematics hat: a frame nobody
    declared, carried into every pose the mechanism is evaluated at.
    """
    assert _declare_joint(hinged, "j-face", "motor:motor_c__mount_face")["status"] == "ok"
    row = _joint_row(_motion(hinged), "j-face")
    assert row["state"] == "unresolvable", row
    assert row["reason"] == "shape_refused"
    assert "not_axial" in str(row.get("detail", ""))
