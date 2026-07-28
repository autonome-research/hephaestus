"""Shared scaffolding for the Gate G8C (assemblies and constraints) suite.

Every G8C clause below is asserted against a **real project driven through the
real tool dispatcher**, the real ``heph`` CLI, the real termination reviewer or
the real bench grader — the surfaces a model, an operator and an external
benchmark actually meet. The exhaustive record-level coverage of the geometry
and of the store lives in ``core/tests/test_geom_constraints.py``,
``core/tests/test_assembly_state.py`` and
``core/tests/test_assembly_evaluation.py``; this suite is the gate evidence, so
what it asserts is *product behaviour*: what a model can declare, what it is
refused, what an operator sees, what a scorer decides, and what a run is
forbidden to terminate green on.

The fixture is the ``ASSEMBLY.md`` §1 worked example made real: an ``enclosure``
whose ``base`` carries a bored **register slot** and whose ``lid`` carries the
matching **register wall**, plus three neighbours that give every other 8C kind
something honest to measure. Nothing here is synthesised — the parts are
authored through ``create_part``/``write_part`` and published through
``build_part``, so an anchor that resolves resolves against a **reloaded** BRep
and the numbers asserted below came out of the kernel.

Geometry, in world mm (right-handed, +Z up)::

    base    60 x 60 x 10 plate centred at the origin, Ø20 bore through it;
            top rim at z = +5, floor face at z = -5
    lid     60 x 60 x 6 plate seated on that rim (z = +5 .. +11) with a
            Ø(20 - 2c) boss reaching down into the bore (z = -3 .. +5)
    bracket 10 mm cube 50 mm away in +X: 15.0 mm of clear air from the base
    plug    Ø24 x 4 disc at the origin: it really does bite into the base ring
    pin     Ø6 x 20 rod 2 mm off the bore axis: a real concentricity error

so the register fit measures ``c`` (0.15 mm as authored), the base/bracket gap
measures exactly 15.0 mm, and the plug's interference is
``pi * (12^2 - 10^2) * 4`` mm³. Those are the numbers the kind clauses pin.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.tools_fixture import Project

__all__ = [
    "BASE_BRACKET_GAP_MM",
    "BASE_SRC",
    "BRACKET_SRC",
    "LID_SRC",
    "NOMINAL_CLEARANCE_MM",
    "ORCH",
    "PART_BASE",
    "PIN_OFFSET_MM",
    "PLUG_OVERLAP_MM3",
    "REGISTER_RADIUS_MM",
    "RIM_TO_FLOOR_MM",
    "assumed",
    "build_all",
    "check",
    "declare",
    "heph",
    "lid_src",
    "make_assembly_project",
    "outcome",
    "rewrite",
    "states",
    "write_part",
]

# --------------------------------------------------------------------------
# the shared interface, as project constants both parts read (ASSEMBLY.md §1:
# "parts already agree on interfaces through shared hc constants")

GLOBALS_SRC = """PARAMS = {}

BASE_XY = 60.0
BASE_Z = 10.0
LID_Z = 6.0
REGISTER_D = 20.0
"""

#: The bore radius both the fit and the concentricity clauses are written against.
REGISTER_RADIUS_MM = 10.0
#: The authored radial clearance of the register fit (bore radius - boss radius).
NOMINAL_CLEARANCE_MM = 0.15
#: Clear air between the base plate and the bracket cube.
BASE_BRACKET_GAP_MM = 15.0
#: Out-of-plane gap between the base's own rim and floor faces.
RIM_TO_FLOOR_MM = 10.0
#: How far the pin's axis sits off the bore's axis.
PIN_OFFSET_MM = 2.0
#: Volume the plug disc takes out of the base ring: pi * (12^2 - 10^2) * 4.
PLUG_OVERLAP_MM3 = math.pi * (12.0**2 - REGISTER_RADIUS_MM**2) * 4.0

BASE_SRC = """plate = Box(hc.BASE_XY, hc.BASE_XY, hc.BASE_Z)
body = plate - Cylinder(radius=hc.REGISTER_D / 2.0, height=4 * hc.BASE_Z)
flats = body.faces().filter_by(Axis.Z).sort_by(Axis.Z)
tag(flats[0], "floor_face")
tag(flats[-1], "rim_top")
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "register_slot")
body.label = "base_body"
part.geometry = body
"""

#: The lid. ``lid_body`` is bound but never labelled, so §5.1 label-fill gives
#: it the binding's name — the "binding form" of an anchor, resolved as a label.
#: ``spare_rib`` is bound and never reaches ``part.geometry``: the binding that
#: the published artifact genuinely cannot address.
LID_SRC = """seat_z = hc.BASE_Z / 2.0
plate = Pos(0.0, 0.0, seat_z + hc.LID_Z / 2.0) * Box(hc.BASE_XY, hc.BASE_XY, hc.LID_Z)
boss = Pos(0.0, 0.0, seat_z - 4.0) * Cylinder(
    radius=hc.REGISTER_D / 2.0 - {clearance}, height=8.0
)
lid_body = plate + boss
tag(lid_body.faces().filter_by(GeomType.CYLINDER)[0], "register_wall")
tag(lid_body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[1], "seat_face")
spare_rib = Box(2.0, 2.0, 2.0)
part.geometry = lid_body
"""

#: The lid after the register wall is re-tagged out of existence: the dangling
#: selector of the unresolvable taxonomy, produced by an ordinary script edit.
LID_UNTAGGED_SRC = """seat_z = hc.BASE_Z / 2.0
plate = Pos(0.0, 0.0, seat_z + hc.LID_Z / 2.0) * Box(hc.BASE_XY, hc.BASE_XY, hc.LID_Z)
boss = Pos(0.0, 0.0, seat_z - 4.0) * Cylinder(radius=hc.REGISTER_D / 2.0 - 0.15, height=8.0)
lid_body = plate + boss
tag(lid_body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[1], "seat_face")
part.geometry = lid_body
"""

BRACKET_SRC = """bracket_body = Pos(50.0, 0.0, 0.0) * Box(10.0, 10.0, 10.0)
tag(bracket_body.faces().filter_by(Axis.X).sort_by(Axis.X)[0], "inner_face")
part.geometry = bracket_body
"""

PLUG_SRC = """plug_body = Cylinder(radius=12.0, height=4.0)
part.geometry = plug_body
"""

PIN_SRC = """pin_body = Pos(2.0, 0.0, 0.0) * Cylinder(radius=3.0, height=20.0)
part.geometry = pin_body
"""

#: Declared, never built: the ``no_current_build`` case, which is a fact about
#: the project rather than about the geometry.
UNBUILT_SRC = "part.geometry = Box(2.0, 2.0, 2.0)\n"

#: The whole cast. A test that only needs the mating pair passes a subset.
PARTS: Mapping[str, str] = {
    "base": BASE_SRC,
    "lid": LID_SRC.format(clearance=NOMINAL_CLEARANCE_MM),
    "bracket": BRACKET_SRC,
    "plug": PLUG_SRC,
    "pin": PIN_SRC,
    "never_built": UNBUILT_SRC,
}

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)
PART_BASE = Principal(session_id="pb", profile="part", part="base")


def lid_src(clearance: float) -> str:
    """The lid script at a given radial clearance (the edit staleness turns on)."""
    return LID_SRC.format(clearance=clearance)


# --------------------------------------------------------------------------
# the project


def make_assembly_project(root: Path, *, parts: Sequence[str] | None = None) -> Project:
    """A real project + dispatcher carrying the register-fit cast.

    Scaffolded here rather than through ``hephaestus.testing.tools_fixture`` so a
    gate assertion cannot be satisfied by a change to another suite's fixture
    parts. The minimal ledger is seeded because ``VALIDATION.md`` §2 refuses
    ``build_part`` without one — a precondition of these clauses, never their
    subject; the review clauses record the entries they actually mean to judge.
    """
    from hephaestus.testing.ledger import seed_minimal_ledger

    wanted = tuple(parts) if parts is not None else tuple(PARTS)
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "enclosure"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    for name in wanted:
        (root / "parts" / f"{name}.py").write_text(PARTS[name], encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    dispatcher = ToolDispatcher(ProjectStore(layout, store), cad=cad)
    seed_minimal_ledger(cad)
    return Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])


def build_all(project: Project, *names: str) -> None:
    """``build_part`` every named part, each of which must have succeeded."""
    for name in names:
        result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
        assert result["status"] == "ok", result


def rewrite(project: Project, part: str, script: str) -> None:
    """Edit one part's script on disk, the way an operator or a quick edit would."""
    (project.root / "parts" / f"{part}.py").write_text(script, encoding="utf-8")


def write_part(project: Project, name: str, script: str) -> None:
    """Author a new part through the model's own tools (create_part + write_part)."""
    created = cast("dict[str, Any]", project.call("create_part", {"name": name}))
    applied = cast(
        "dict[str, Any]",
        project.call(
            "write_part",
            {"name": name, "expected_hash": created["content_hash"], "script": script},
        ),
    )
    assert applied["applied"] is True, applied


# --------------------------------------------------------------------------
# the constraint surface, as a model reaches it


def assumed(reason: str = "no requirement covers this interface yet") -> dict[str, Any]:
    """The ``assumed`` provenance an entry that cites no requirement must carry."""
    return {"assumed": True, "reason": reason}


def declare(
    project: Project,
    constraint_id: str,
    kind: str,
    a: str,
    b: str,
    *,
    principal: Principal = ORCH,
    provenance: Mapping[str, Any] | None = None,
    **values: Any,
) -> dict[str, Any]:
    """``declare_constraint`` through the dispatcher; returns the tool result."""
    entry: dict[str, Any] = {
        "id": constraint_id,
        "kind": kind,
        "a": a,
        "b": b,
        "provenance": dict(provenance) if provenance is not None else assumed(),
    }
    entry.update(values)
    return cast("dict[str, Any]", project.call("declare_constraint", entry, principal=principal))


def check(
    project: Project, ids: Sequence[str] | None = None, *, principal: Principal = ORCH
) -> dict[str, Any]:
    """``check_assembly`` through the dispatcher; returns the ``AssemblyStatus`` JSON."""
    arguments: dict[str, Any] = {} if ids is None else {"ids": list(ids)}
    result = cast("dict[str, Any]", project.call("check_assembly", arguments, principal=principal))
    assert result["status"] == "ok", result
    return cast("dict[str, Any]", result["assembly"])


def outcome(status: Mapping[str, Any], constraint_id: str) -> dict[str, Any]:
    """One constraint's row out of an ``AssemblyStatus`` document."""
    for item in cast("Sequence[Any]", status["constraints"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == constraint_id:
            return row
    raise AssertionError(f"no constraint {constraint_id!r} in {json.dumps(dict(status))}")


def states(status: Mapping[str, Any]) -> dict[str, str]:
    """``{constraint id: state}`` for a whole status, for the taxonomy clauses."""
    return {
        str(cast("dict[str, Any]", row)["id"]): str(cast("dict[str, Any]", row)["state"])
        for row in cast("Sequence[Any]", status["constraints"])
    }


# --------------------------------------------------------------------------
# the operator surface

_CLI_PROGRAM = """
import sys
from hephaestus.core.cli import main
sys.exit(main(sys.argv[1:]))
"""


def heph(root: Path, *argv: str, expect: int = 0) -> str:
    """Run ``heph`` in a FRESH interpreter rooted at the project.

    A subprocess, not :func:`hephaestus.core.cli.main`, wherever the clause is
    about two processes agreeing: an in-process second call would share this
    one's kernel state and prove nothing about reproducibility.
    """
    result = subprocess.run(
        [sys.executable, "-c", _CLI_PROGRAM, *argv],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expect, (
        f"heph {' '.join(argv)} exited {result.returncode} (expected {expect}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    return result.stdout
