# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared scaffolding for the Gate G13A pose-solving suite (not a test module).

Every clause in this suite that talks about geometry is asserted against REAL
published artifacts: the parts below are ordinary part scripts, built through
the executor and published through the project store, so a solve that resolves
an anchor resolves it against a *reloaded* BRep the way ``ASSEMBLY.md`` §2 and
``KINEMATICS.md`` §2 require. Frames extracted from a synthetic in-memory shape
would prove nothing about the anchoring path the solver actually rides — and
``SOLVER.md`` §7's whole argument is that the verification pass re-reads the
same store in another process.

Scaffolded here rather than reusing ``tests/stage9a/_g9a.py``'s cast (the
``_g8c.make_assembly_project`` rationale, restated once more): a gate assertion
must not be satisfiable by a change made elsewhere.

The mechanism, in world mm (right-handed, +Z up), ``zero: "as_built"``
---------------------------------------------------------------------
A planar three-revolute arm on the Z axis, plus two angular references and a
deliberately dishonest flush pair::

    post     Ø10 post on the Z axis (tag ``post_axis``) - the ground root and
             the shoulder's frame owner.
    link1    a bar x in [-4, 44] at z = 8 with Ø6 bores at x = 0 (``hub1``)
             and x = 40 (``elbow1``).
    link2    a bar x in [36, 80] at z = 14 with Ø6 bores at x = 40 (``hub2``)
             and x = 74 (``wrist2``), and its +X end face tagged ``tip_face``
             (normal +X, centre (80, 0, 14)).
    link3    a bar x in [73, 103] at z = 20 with a Ø6 bore at x = 74
             (``hub3``) and its +X end face tagged ``tool_face`` (normal +X,
             centre (103, 0, 20)).
    ref30    a bar rotated 30 deg about Z whose +X face (``ref30``) therefore
             has normal (cos 30, sin 30, 0).
    ref90    an axis-aligned bar whose +Y face (``ref90``) has normal (0, 1, 0).
    pad      a fixed plate whose top face ``pad_top`` sits at z = 30, normal +Z.
    slide    a block riding a prismatic joint, top face ``slide_top`` at
             z = 5, normal **+Z as well** - the same-facing pair.

Joints: ``j-shoulder`` (revolute, post -> link1), ``j-elbow`` (revolute,
link1 -> link2), ``j-wrist`` (revolute, link2 -> link3, **limits ±10 deg**),
``j-lift`` (prismatic, pad -> slide, limits [0, 40] mm).

Numbers the clauses pin, and why each is exact rather than "about"
------------------------------------------------------------------
* the shoulder, elbow and wrist axes are the Z lines through x = 0, 40 and 74,
  so the arm's link lengths are exactly 40, 34 and 29 mm and ``tool_face``'s
  centre sits at radius 103 from the shoulder. A target at 200 mm is therefore
  out of reach by construction, not by a measurement that might drift.
* ``ref30``'s normal is 30 deg from ``tip_face``'s at zero, and ``parallel``
  folds - so ``c-align`` has exactly TWO solutions in the elbow, +30 and -150.
  That is the discrete multiplicity clause 6 asserts, and it is a property of
  the fold, not of the fixture's luck.
* the four kinds ``SOLVER.md`` §3.2 refuses as objective terms are declared
  too (``c-gap`` and ``c-touch`` for ``plateau``, ``c-reach`` for
  ``kernel_extremum``, ``c-fit`` for ``pose_invariant``), anchored between the
  two STATIC reference bars wherever the kind allows it. That placement is
  deliberate: they exist to be refused at request time, before any geometry is
  read, and anchoring a boolean-valued kind on a moving part would make every
  unrelated solve in this suite pay for a kernel intersection it never asked
  for.
* ``c-flush``'s gap is exactly 25 mm and closes to zero at ``j-lift`` = 25,
  with both normals still +Z: ``normal_deviation_deg`` is 180 there, and no
  prismatic DOF can flip it. That is the class-predicate negative of clause 2
  - "the gap is zero and it is still not a mate" - built so that a solver
  graded on the residual number alone would report success.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.constraints import ConstraintSet
from hephaestus.core.project_store.kinematics import JointSet
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "ARM_PARTS",
    "CONSTRAINTS",
    "JOINTS",
    "REF30_DEG",
    "TIP_CENTRE",
    "TOOL_CENTRE",
    "assumed",
    "build_part",
    "make_project",
    "open_arm_project",
]

#: The angle (deg) between ``tip_face``'s normal and ``ref30``'s at zero.
REF30_DEG = 30.0

#: ``anchor_center`` of ``link2:tip_face`` and ``link3:tool_face`` as built.
TIP_CENTRE = (80.0, 0.0, 14.0)
TOOL_CENTRE = (103.0, 0.0, 20.0)

POST_SRC = """post_body = Cylinder(radius=5.0, height=12.0)
tag(post_body.faces().filter_by(GeomType.CYLINDER)[0], "post_axis")
part.geometry = post_body
"""

LINK1_SRC = """bar = Pos(20.0, 0.0, 8.0) * Box(48.0, 10.0, 4.0)
bar = bar - Pos(0.0, 0.0, 8.0) * Cylinder(radius=3.0, height=12.0)
bar = bar - Pos(40.0, 0.0, 8.0) * Cylinder(radius=3.0, height=12.0)
bores = bar.faces().filter_by(GeomType.CYLINDER).sort_by(Axis.X)
tag(bores[0], "hub1")
tag(bores[-1], "elbow1")
part.geometry = bar
"""

LINK2_SRC = """bar = Pos(58.0, 0.0, 14.0) * Box(44.0, 10.0, 4.0)
bar = bar - Pos(40.0, 0.0, 14.0) * Cylinder(radius=3.0, height=12.0)
bar = bar - Pos(74.0, 0.0, 14.0) * Cylinder(radius=3.0, height=12.0)
bores = bar.faces().filter_by(GeomType.CYLINDER).sort_by(Axis.X)
tag(bores[0], "hub2")
tag(bores[-1], "wrist2")
tag(bar.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "tip_face")
part.geometry = bar
"""

LINK3_SRC = """bar = Pos(88.0, 0.0, 20.0) * Box(30.0, 10.0, 4.0)
bar = bar - Pos(74.0, 0.0, 20.0) * Cylinder(radius=3.0, height=12.0)
tag(bar.faces().filter_by(GeomType.CYLINDER).sort_by(Axis.X)[0], "hub3")
tag(bar.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "tool_face")
part.geometry = bar
"""

REF30_SRC = """pad = Rotation(0.0, 0.0, 30.0) * Pos(90.0, 0.0, 14.0) * Box(30.0, 4.0, 4.0)
tag(pad.faces().sort_by(Axis.X)[-1], "ref30")
part.geometry = pad
"""

REF90_SRC = """pad = Pos(0.0, 90.0, 14.0) * Box(4.0, 30.0, 4.0)
tag(pad.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1], "ref90")
part.geometry = pad
"""

PAD_SRC = """plate = Pos(-40.0, 0.0, 28.0) * Box(20.0, 20.0, 4.0)
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "pad_top")
part.geometry = plate
"""

SLIDE_SRC = """block = Pos(-40.0, 0.0, 3.0) * Box(10.0, 10.0, 4.0)
tag(block.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "slide_top")
part.geometry = block
"""

#: The whole cast. Every part is built and published by :func:`open_arm_project`.
ARM_PARTS: Mapping[str, str] = {
    "post": POST_SRC,
    "link1": LINK1_SRC,
    "link2": LINK2_SRC,
    "link3": LINK3_SRC,
    "ref30": REF30_SRC,
    "ref90": REF90_SRC,
    "pad": PAD_SRC,
    "slide": SLIDE_SRC,
}


def assumed(reason: str = "no requirement covers this solve yet") -> dict[str, JSONValue]:
    """The ``assumed`` provenance every fixture entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}


#: The declared joint set. ``j-wrist``'s ±10 deg window is the limit clause's
#: subject: a target reachable only past it must come back with the joint in
#: ``limits_active`` and the returned value INSIDE the window, never clamped
#: past it (``geom/kinematics.py:217-245``).
JOINTS: tuple[Mapping[str, JSONValue], ...] = (
    {
        "id": "j-shoulder",
        "kind": "revolute",
        "parent": "post:post_axis",
        "child": "link1:hub1",
        "limits": {"min": -180.0, "max": 180.0},
        "provenance": assumed(),
    },
    {
        "id": "j-elbow",
        "kind": "revolute",
        "parent": "link1:elbow1",
        "child": "link2:hub2",
        "limits": {"min": -180.0, "max": 180.0},
        "provenance": assumed(),
    },
    {
        "id": "j-wrist",
        "kind": "revolute",
        "parent": "link2:wrist2",
        "child": "link3:hub3",
        "limits": {"min": -10.0, "max": 10.0},
        "provenance": assumed(),
    },
    {
        "id": "j-lift",
        "kind": "prismatic",
        "parent": "pad:pad_top",
        "child": "slide:slide_top",
        "limits": {"min": 0.0, "max": 40.0},
        "provenance": assumed(),
    },
)

#: The declared constraint set.
#:
#: ``c-flush`` is the honest trap: its gap closes to exactly zero at
#: ``j-lift`` = 25 while both normals still point +Z, so it is *unsatisfied
#: with positive slack* - the case ``geom/constraints.py:304-311`` stores
#: ``satisfied`` for and the case ``SOLVER.md`` §3.1 says a solver graded on
#: ``slack`` would get wrong.
CONSTRAINTS: tuple[Mapping[str, JSONValue], ...] = (
    {
        "id": "c-align",
        "kind": "parallel",
        "a": "link2:tip_face",
        "b": "ref30:ref30",
        "tol_deg": 0.01,
        "provenance": assumed("the tool face is meant to run along the 30 deg rail"),
    },
    {
        "id": "c-square",
        "kind": "parallel",
        "a": "link2:tip_face",
        "b": "ref90:ref90",
        "tol_deg": 0.01,
        "provenance": assumed("and also along the 90 deg rail - deliberately, they conflict"),
    },
    {
        "id": "c-flush",
        "kind": "coincident",
        "a": "pad:pad_top",
        "b": "slide:slide_top",
        "tol_mm": 0.05,
        "provenance": assumed("the slide is meant to seat flush against the pad"),
    },
    {
        "id": "c-perp",
        "kind": "perpendicular",
        "a": "link2:tip_face",
        "b": "ref90:ref90",
        "tol_deg": 0.01,
        "provenance": assumed("square to the 90 deg rail"),
    },
    # The four kinds SOLVER.md §3.2 refuses as objective terms in pose space,
    # one per reason. Anchored between the two STATIC reference bars (and, for
    # `fit`, on a bore/shaft pair) so they are cheap: they exist to be refused
    # at request time, before any geometry is read, and anchoring the plateau
    # pair on a moving part would make every unrelated solve pay for a boolean
    # it never asked for.
    {
        "id": "c-gap",
        "kind": "clearance_min",
        "a": "ref30",
        "b": "ref90",
        "value_mm": 1.0,
        "provenance": assumed("plateau: clearance_min is flat wherever the solids overlap"),
    },
    {
        "id": "c-touch",
        "kind": "no_interference",
        "a": "ref30",
        "b": "ref90",
        "provenance": assumed("plateau: overlap volume is identically 0 over the feasible set"),
    },
    {
        "id": "c-reach",
        "kind": "distance",
        "a": "ref30:ref30",
        "b": "ref90:ref90",
        "value_mm": 10.0,
        "tol_mm": 1.0,
        "provenance": assumed("kernel_extremum: the witness pair switches as surfaces slide"),
    },
    {
        "id": "c-fit",
        "kind": "fit",
        "a": "link1:hub1",
        "b": "post:post_axis",
        "min_mm": 1.0,
        "max_mm": 3.0,
        "provenance": assumed("pose_invariant: no rigid motion changes hole minus shaft"),
    },
)


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "arm") -> ProjectLayout:
    """Write a minimal real project tree under ``root`` and load its layout."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'name = "{name}"\nunits = "mm"\n', encoding="utf-8")
    parts_dir = root / "parts"
    parts_dir.mkdir(exist_ok=True)
    for part, script in parts.items():
        (parts_dir / f"{part}.py").write_text(script, encoding="utf-8")
    return load_project(root)


def build_part(publisher: Publisher, layout: ProjectLayout, part: str) -> None:
    """Freeze, build and publish one part through the ordinary pipeline."""
    frozen = publisher.freeze_inputs(part)
    build = run_build(
        BuildRequest(part=part, script=frozen.script, globals_source=frozen.globals_source),
        backend=UnsafeLocalBackend(),
        out_dir=layout.store_root / "builds" / f"{part}-{len(part)}",
    )
    assert build.result.status == "ok", build.result.error
    outcome = publisher.publish_build(build, op_id=f"build-{part}-{build.result.artifact_ref}")
    assert outcome.kind == "current", outcome.details


def open_arm_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The whole cast built and published, with :data:`JOINTS` and :data:`CONSTRAINTS`."""
    layout = make_project(root, ARM_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in ARM_PARTS:
        build_part(publisher, layout, part)
    joints = JointSet(layout, store)
    for entry in JOINTS:
        joints.declare(entry)
    constraints = ConstraintSet(layout, store)
    for entry in CONSTRAINTS:
        constraints.declare(entry)
    return layout, store
