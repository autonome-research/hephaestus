"""Shared scaffolding for Gate G11B (mounting interfaces as tagged geometry).

G11B is the sub-stage the whole component store exists for: a store component's
mounting interfaces become **tagged geometry**, so a model constrains one
against a user part through the *existing* Stage 8C path — no new addressing,
no new anchor grammar, no second resolver. Everything here is therefore
asserted against real builds and the real tool surfaces; a fragment that is
never executed proves nothing about a mechanism whose entire premise is that
the fragment is pasted source.

Two fixtures carry the suite.

:data:`RIG_SRC` is a component generator whose geometry offers **one topology
of each of §2.3's five declared classes**, each selectable by a *measure* and
therefore invariant under the placement a consumer applies:

    a 30 x 20 x 6 plate centred at the origin with a Ø8 boss standing on its
    top face (z = +3 .. +3 + ``boss_h``)

    ``mount_face``  the plate's BOTTOM face — 600 mm^2, the unique largest
                    planar face; normal -Z, so it opposes a pad's +Z
    ``shaft``       the boss outer cylinder — the only cylindrical face
    ``shaft_ring``  the largest circular edge (Ø8)
    ``rail``        the longest linear edge (30 mm)
    ``envelope``    the whole solid, the ``("solid", "OTHER")`` row

Nothing here is ordered by a world axis. That is the authoring rule §2.1 states
and ``interface_placement_drift`` can only *partly* enforce, so the fixture
obeys it and :data:`DRIFTING_INTERFACE` is the deliberate counter-example.

:func:`make_join_project` is the 8C/Stage-9 half: a real project whose
``gantry_plate`` pastes a component instance seated on its pad, and whose
``motor`` part is the same component instanced as a part file — the two anchor
forms §2.4 names, both reaching the resolver through ``ANCHOR_PATTERN``
unchanged.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.core.executor.sandbox.bwrap import find_bwrap
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    PartsIndex,
    RegistryOps,
    RegistrySet,
    load_registry,
)
from hephaestus.testing.tools_fixture import Project

from opstore import OpStore

__all__ = [
    "BOSS_RADIUS_MM",
    "DRIFTING_INTERFACE",
    "MOUNT_FACE_AREA_MM2",
    "ORCH",
    "PAD_TOP_Z_MM",
    "RIG_INTERFACES",
    "RIG_SRC",
    "SEAT_POS",
    "component_tree",
    "declare",
    "fragment_for",
    "make_join_project",
    "ops_for",
    "outcome",
    "requires_bwrap",
    "rig_component",
    "store_ops",
    "tag_names",
]

#: Registry content executes only under a probed OS sandbox; a machine without
#: one cannot produce the instantiation half of the evidence, and must not fake
#: it (the rule ``tests/stage6/_g6.py`` and ``tests/stage11a/_g11a.py`` state).
requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="store generators execute only under a probed bwrap sandbox",
)

#: The plate bottom: 30 x 20, the unique largest planar face of the rig.
MOUNT_FACE_AREA_MM2: Final[float] = 600.0
#: The boss outer radius, i.e. the ``shaft`` interface's radius.
BOSS_RADIUS_MM: Final[float] = 4.0
#: Half the plate thickness: the plate bottom sits at ``z = -3`` unplaced.
PLATE_HALF_Z_MM: Final[float] = 3.0
#: The pad's top face in ``gantry_plate``.
PAD_TOP_Z_MM: Final[float] = 4.0
#: Where a motor seats on that pad — a non-zero translation AND a non-zero
#: rotation, which is the placement §2.1's first draft could not have survived.
SEAT_POS: Final[dict[str, float]] = {"z": PAD_TOP_Z_MM + PLATE_HALF_Z_MM, "rz": 30.0}

#: Declared interfaces of :data:`RIG_SRC`, one per §2.3 table row.
RIG_INTERFACES: Final[tuple[tuple[str, str, str], ...]] = (
    ("mount_face", "planar_face", "mount_face"),
    ("shaft", "cylindrical_face", "shaft"),
    ("shaft_ring", "circular_edge", "ring"),
    ("rail", "linear_edge", "rail"),
    ("envelope", "solid", "envelope"),
)

_RIG_BODY: Final[str] = """# --- hephaestus-store: params ---
PARAMS = {
    "boss_h": Param(4.0, min=2.0, max=10.0, doc="boss height above the plate, mm"),
}
# --- hephaestus-store: bind ---
_boss_h = p.boss_h
# --- hephaestus-store: body ---
_plate = Box(30.0, 20.0, 6.0)
_boss = Pos(0.0, 0.0, 3.0 + _boss_h / 2) * Cylinder(4.0, _boss_h)
_rig = _plate + _boss
_rig.label = "rig"
part.geometry = _rig
"""

#: Every selector ordered by a measure, and rooted at the published name.
RIG_REGION: Final[str] = """# --- hephaestus-store: interface ---
tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")
tag(_rig.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "shaft")
tag(_rig.edges().filter_by(GeomType.CIRCLE).sort_by(SortBy.LENGTH)[-1], "shaft_ring")
tag(_rig.edges().filter_by(GeomType.LINE).sort_by(SortBy.LENGTH)[-1], "rail")
tag(_rig.solids().sort_by(SortBy.VOLUME)[-1], "envelope")
"""

RIG_SRC: Final[str] = _RIG_BODY + RIG_REGION

#: The pos-DEPENDENT selector §2.1 declines to forbid at parse time — it is not
#: decidable by a parser — and §2.3 catches at instantiation. At the origin
#: ``sort_by(Axis.X)[-1]`` picks the plate's +X end face (20 x 6 = 120 mm^2);
#: under :data:`DRIFT_ROT` it picks a *side* face (30 x 6 = 180 mm^2) instead,
#: which is a different measure and therefore caught. Under
#: :data:`EQUAL_MEASURE_ROT` it picks the opposite end face, which is a
#: different face of the *same* measure and therefore NOT caught: the exact
#: limit §2.3 states, and the reason the rule reports drift and never certifies
#: invariance.
DRIFTING_INTERFACE: Final[str] = (
    'tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(Axis.X)[-1], "mount_face")'
)
#: A quarter turn: the +X end face swings to x = 0 and a side face takes the lead.
DRIFT_ROT: Final[dict[str, float]] = {"rz": 90.0}
#: A half turn: the two end faces swap, and they are congruent.
EQUAL_MEASURE_ROT: Final[dict[str, float]] = {"rz": 180.0}


def rig(**overrides: Any) -> dict[str, Any]:
    """The rig's ``component`` record; ``overrides`` replace or delete keys."""
    record: dict[str, Any] = {
        "class": "motor",
        "series": {"family": "fixture", "size": "rig"},
        "license": "Apache-2.0",
        "data_license": "facts-only",
        "frame": "plate bottom at z = -3; boss along +Z",
        "simplifications": ["a test rig, not a motor"],
        "interfaces": [
            {"name": name, "class": klass, "role": role} for name, klass, role in RIG_INTERFACES
        ],
    }
    for key, value in overrides.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    return record


#: Alias kept because "the record of the rig component" reads better at a call
#: site than "rig(...)" does inside a clause about records.
rig_component = rig


def component_tree(
    root: Path,
    *,
    part_id: str = "rig",
    component: Mapping[str, Any] | None = None,
    generator: str = RIG_SRC,
    params: Mapping[str, Any] | None = None,
) -> Path:
    """Write a one-part ``parts`` registry at ``root`` and return it.

    Deliberately built here rather than shared with ``tests/stage11a``: a gate
    assertion must not be satisfiable by an edit to another sub-gate's fixture.
    """
    directory = root / part_id
    directory.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_FILENAME).write_text(
        "\n".join(
            [
                "[registry]",
                'name = "fixture-parts"',
                'kind = "parts"',
                'version = "0.0.1"',
                'license = "Apache-2.0"',
                "",
                "[[parts]]",
                f'id = "{part_id}"',
                f'dir = "{part_id}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    declared = (
        {"boss_h": {"type": "float", "default": 4.0, "min": 2.0, "max": 10.0, "unit": "mm"}}
        if params is None
        else dict(params)
    )
    meta: dict[str, Any] = {
        "id": part_id,
        "name": "Interface rig",
        "summary": "A fixture component offering one topology per declared class.",
        "keywords": ["rig", "fixture", "motor"],
        "params": declared,
    }
    record = rig() if component is None else component
    if record is not None:
        meta["component"] = dict(record)
    (directory / "part.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (directory / "generator.py").write_text(generator, encoding="utf-8")
    return root


def index_of(root: Path) -> PartsIndex:
    return PartsIndex(load_registry(root))


def ops_for(root: Path, tmp_path: Path, *, backend: Any = None) -> RegistryOps:
    """A :class:`RegistryOps` over ``root``, sandboxed unless told otherwise."""
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

    store = OpStore.create(tmp_path / f"store-{root.name}")
    return RegistryOps(
        RegistrySet({"parts": load_registry(root)}),
        store,
        backend=BwrapBackend() if backend is None else backend,
        scratch_root=tmp_path / "scratch",
    )


def store_ops(tmp_path: Path, *, generator: str = RIG_SRC, **record: Any) -> RegistryOps:
    """One call from "a component record and a generator" to "the real tool"."""
    root = component_tree(
        tmp_path / "reg", component=rig(**record) if record else None, generator=generator
    )
    return ops_for(root, tmp_path)


def fragment_for(
    ops: RegistryOps,
    *,
    params: Mapping[str, Any] | None = None,
    pos: Mapping[str, Any] | None = None,
    instance: str | None = None,
    part_id: str = "rig",
) -> dict[str, Any]:
    """``instance_store_part`` through the real op, returning the whole result."""
    return cast(
        "dict[str, Any]",
        ops.instance_store_part(part_id, dict(params or {}), dict(pos) if pos else None, instance),
    )


def tag_names(fragment: str) -> tuple[str, ...]:
    """Every ``tag(..., "<name>")`` literal in a rendered fragment, in order.

    Read out of the fragment's own AST rather than by a regular expression, so
    a name appearing in a comment cannot be mistaken for an emitted tag.
    """
    import ast

    names: list[str] = []
    for node in ast.walk(ast.parse(fragment)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "tag" or len(node.args) != 2:
            continue
        literal = node.args[1]
        if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
            names.append(literal.value)
    return tuple(names)


# --------------------------------------------------------------------------
# the 8C / Stage 9 join

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)

GLOBALS_SRC: Final[str] = "PARAMS = {}\n\nPAD_XY = 60.0\nPAD_Z = 8.0\n"

#: The user part: a pad with its top face tagged, plus a pasted component
#: instance seated on it. Both anchors name the same part, which is the correct
#: model of a bolted-on motor and needs no change to ``ANCHOR_PATTERN``.
GANTRY_SRC: Final[str] = """{fragment}
pad = Box(hc.PAD_XY, 40.0, {pad_z})
tag(pad.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "motor_pad")
plate_body = Compound(children=[pad, {instance}])
part.geometry = plate_body
"""

#: The same component as its OWN part file, whose whole body is one fragment:
#: the cross-part anchor form, through the same resolver.
MOTOR_SRC: Final[str] = """{fragment}
part.geometry = {instance}
"""

#: A hub whose bore is coaxial with the seated motor's boss, so a revolute
#: anchored on the component's ``shaft`` has a child frame to agree with.
HUB_SRC: Final[str] = """hub_body = Pos(0.0, 0.0, 20.0) * (
    Cylinder(radius=9.0, height=6.0) - Cylinder(radius=4.0, height=12.0)
)
tag(hub_body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "hub_bore")
part.geometry = hub_body
"""


def make_join_project(root: Path, parts: Mapping[str, str]) -> Project:
    """A real project + dispatcher carrying ``parts``, with a seeded ledger.

    The ledger is seeded because ``VALIDATION.md`` §2 refuses ``build_part``
    without one — a precondition of these clauses, never their subject.
    """
    from hephaestus.testing.ledger import seed_minimal_ledger

    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "gantry"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    for name, script in parts.items():
        (root / "parts" / f"{name}.py").write_text(script, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    dispatcher = ToolDispatcher(ProjectStore(layout, store), cad=cad)
    seed_minimal_ledger(cad)
    return Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])


def build_all(project: Project, *names: str) -> None:
    for name in names:
        result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
        assert result["status"] == "ok", result


def rewrite(project: Project, part: str, script: str) -> None:
    (project.root / "parts" / f"{part}.py").write_text(script, encoding="utf-8")


def assumed(reason: str = "no requirement covers this interface yet") -> dict[str, Any]:
    return {"assumed": True, "reason": reason}


def declare(
    project: Project,
    constraint_id: str,
    kind: str,
    a: str,
    b: str,
    **values: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": constraint_id,
        "kind": kind,
        "a": a,
        "b": b,
        "provenance": assumed(),
    }
    entry.update(values)
    return cast("dict[str, Any]", project.call("declare_constraint", entry, principal=ORCH))


def check(project: Project, ids: Sequence[str] | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {} if ids is None else {"ids": list(ids)}
    result = cast("dict[str, Any]", project.call("check_assembly", arguments, principal=ORCH))
    assert result["status"] == "ok", result
    return cast("dict[str, Any]", result["assembly"])


def outcome(status: Mapping[str, Any], constraint_id: str) -> dict[str, Any]:
    for item in cast("Sequence[Any]", status["constraints"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == constraint_id:
            return row
    raise AssertionError(f"no constraint {constraint_id!r} in {json.dumps(dict(status))}")
