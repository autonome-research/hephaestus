# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared scaffolding for the Gate G13B placement-proposal suite (not a test module).

Every clause here that talks about geometry is asserted against REAL published
artifacts: the parts below are ordinary part scripts, built through the
executor and published through the project store, so a solve resolves anchors
against a *reloaded* BRep the way ``ASSEMBLY.md`` §2 requires — and
``SOLVER.md`` §7's whole argument is that the verification pass re-reads the
same store in another process.

Scaffolded here rather than reusing ``tests/stage13a/_g13a.py``'s arm (the
``_g8c.make_assembly_project`` rationale, restated once more): a gate assertion
must not be satisfiable by a change made elsewhere. The two casts also have
opposite shapes on purpose — 13A's is a jointed chain, and in transform space a
part that rides a joint may not be free at all (``free_part_is_jointed``).

The mechanism, in world mm (right-handed, +Z up), everything at as-built
------------------------------------------------------------------------
::

    base    60 x 40 x 10 plate on the origin corner (x 0..60, y 0..40,
            z 0..10) with a Ø8 bore on the Z axis through (20, 20).
            Tags: ``base_top`` (+Z, at z = 10), ``base_bottom`` (-Z, at
            z = 0), ``base_x`` (+X, at x = 60), ``base_y`` (+Y, at y = 40),
            ``base_bore``.
    lug     20 x 20 x 10 block held 30 mm in the air (z 40..50, x 0..20,
            y 0..20) with a Ø8 bore on the Z axis through (10, 10).
            Tags: ``lug_bottom`` (-Z, z = 40), ``lug_top`` (+Z, z = 50),
            ``lug_x`` (+X), ``lug_y`` (+Y), ``lug_bore``. THE free part.
    post    Ø9 shaft on the Z axis through (20, 20), z 10..30. Tag
            ``post_shaft`` - the SHAFT half of the one ``fit`` pair, since a
            fit needs one hole and one shaft and two bores are refused. It is
            deliberately FATTER than ``lug``'s Ø8 bore, which is what makes the
            seated solution an interference: the four analytic mates are
            satisfiable only by driving the lug's bore onto the post, so the
            proposal that satisfies all four comes back with
            ``no_interference`` violated beside them (clause 22).
    sleeve  a block whose Ø6 bore runs along **X**, so its axis is 90 deg from
            every other axis here. Tag ``sleeve_bore``.
    hinge_a Ø6 pin on the Z axis through (100, 0). Tag ``hinge_pin``.
    hinge_b a block with a Ø6 bore on the same axis. Tag ``hinge_bore``.
            The two exist ONLY to carry a declared joint and a declared pose,
            so the ``free_part_is_jointed`` and
            ``pose_bound_constraint_in_transform_space`` refusals have
            something real to fire on.

The hand-computed answer, and why it is exact rather than "about"
-----------------------------------------------------------------
Every full-rank fixture below has the SAME solution, and it is arithmetic a
reader can do without running anything:

* ``c-seat`` (coincident ``base_top`` / ``lug_bottom``) is satisfied when the
  gap ``dot(c_b - c_a, n_a)`` is zero. ``n_a`` is +Z, so only the z components
  matter: ``c_a.z = 10``, ``c_b.z = 40``, gap ``= 30``, and the only translation
  that closes it is ``tz = -30``. The normals are already opposed (+Z against
  -Z), so no rotation is required or wanted.
* ``c-bore`` (concentric) is satisfied when ``lug``'s bore axis meets ``base``'s.
  Both are Z lines, at (10, 10) and (20, 20), so the radial offset is
  ``sqrt(200)`` and the only translation that closes it is ``tx = ty = +10``.
* ``c-face`` (parallel ``base_x`` / ``lug_x``) and ``c-square``
  (perpendicular ``base_x`` / ``lug_y``) already hold at the identity rotation.

So :data:`SEATED_ROWS` is ``[[1,0,0,10],[0,1,0,10],[0,0,1,-30]]``, exactly, and
G13B clause 18 asserts the returned transform against it rather than against
whatever the solver happened to produce.

The traps, each built so a solver graded on the wrong number would pass
-----------------------------------------------------------------------
* ``c-invert`` (coincident ``base_top`` / ``lug_top``) has **same-facing**
  normals at as-built: +Z against +Z, ``normal_deviation_deg`` 180. Its gap
  closes by translation alone, with the normals still same-facing, so a solver
  graded on the residual number reports success for a placement the engine
  measures ``violated``. With the rotations boxed to zero it is the clause-20
  negative; with a rotational degree of freedom released it is the mirror
  positive, and the solver turns the lug over.
* The **interference** clause 22 needs is not a trap at all, it is the
  fixture's own arithmetic: ``post`` is Ø9 and ``lug``'s bore is Ø8, so the
  four analytic mates of :data:`FULL_RANK_FIXTURES` are satisfiable only by
  driving the bore onto the post. The solve converges with all four
  ``satisfied``, and ``c-clear`` (``no_interference(post, lug)``) comes back
  violated beside them — evaluated at the solution, never silently dropped.
* ``c-tilt`` (concentric ``base_bore`` / ``sleeve_bore``) is the same trap in
  the other class predicate: the radial offset closes to zero while the axes
  stay 90 deg apart.
* ``c-cross`` (parallel ``base_y`` / ``lug_x``) contradicts ``c-face``
  (parallel ``base_x`` / ``lug_x``) outright: one direction cannot be parallel
  to two perpendicular ones, and the least-squares floor sits between them.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.constraints import ConstraintProvenance, ConstraintSet
from hephaestus.core.project_store.kinematics import JointSet, PoseSet
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from opstore.types import JSONValue

from opstore import OpStore

#: G13B clause 18: one full-column-rank fixture per analytic kind — the kind
#: under test plus enough further analytic mates to remove the null space
#: entirely, so a unique answer exists to hand-compute at all. Two of the four
#: completing sets coincide, and that is a fact about the geometry rather than
#: laziness: with three translational and three rotational degrees of freedom
#: to remove from ONE free part, a rank-6 system out of these four declared
#: mates has only so many spellings. What the clause needs is that each kind is
#: exercised inside a full-rank system, and each of the four is.
FULL_RANK_FIXTURES: Mapping[str, tuple[str, ...]] = {
    "coincident": ("c-seat", "c-bore", "c-face"),
    "concentric": ("c-bore", "c-seat", "c-square"),
    "parallel": ("c-face", "c-seat", "c-bore", "c-square"),
    "perpendicular": ("c-square", "c-seat", "c-bore"),
}

__all__ = [
    "ACOS_CONDITIONING_EPS_DEG",
    "BENCH_PARTS",
    "CONSTRAINTS",
    "FIXTURE_KAPPA",
    "FULL_RANK_FIXTURES",
    "IDENTITY_EPS",
    "IDENTITY_PROBE_ROTATION_DEG",
    "IDENTITY_PROBE_TRANSLATION_MM",
    "JACOBIAN_FD_EPS",
    "KAPPA_MATCH_REL",
    "SEATED_ROWS",
    "TRANSFORM_MATCH_FACTOR",
    "assumed",
    "build_part",
    "kappa_reads_outside_the_pin",
    "make_project",
    "open_bench_project",
    "placement_request",
    "proposal_document",
    "rows_of",
    "transform_match_eps",
    "transform_model",
]

#: The exact transform every full-column-rank fixture below solves to
#: (translation (+10, +10, -30) with no rotation), derived in the module
#: docstring from the fixture's own dimensions rather than measured.
SEATED_ROWS: tuple[tuple[float, ...], ...] = (
    (1.0, 0.0, 0.0, 10.0),
    (0.0, 1.0, 0.0, 10.0),
    (0.0, 0.0, 1.0, -30.0),
)

#: Each fixture's condition number of the weighted Jacobian at the solution,
#: **recorded here beside the hand-computed answer it qualifies** — the
#: ``SOLVER.md`` § Gates definition of ``kappa``, and the reason
#: :func:`transform_match_eps` takes a number rather than reading one off the
#: record.
#:
#: **Why this constant exists at all, said plainly** (repaired 2026-09-01, after
#: an independent verifier found the defect): ``TRANSFORM_MATCH_EPS`` is
#: ``tol * TRANSFORM_MATCH_FACTOR * kappa``, so whoever supplies ``kappa`` sets
#: the accuracy budget clause 18 grades against. The shipped machinery read it
#: from ``record.solver_core["kappa"]`` — the solver's OWN reported conditioning
#: — and nothing pinned it, so a solver reporting an inflated number would have
#: widened its own tolerance and the gate would have stayed green. That is the
#: self-grading shape this whole stage exists to refuse (§7: a solved placement
#: is verified independently, never trusted because the solver said so), and it
#: is fixed by recording the number in the fixture and holding the solver's
#: report to it (:data:`KAPPA_MATCH_REL`).
#:
#: **And it is arithmetic, not a transcribed decimal.** ``unit_scaled_v1``
#: weights a mm row 1.0 and a deg row ``R * pi/180``, where ``R`` is the free
#: part's bounding-box centre-to-corner radius (``placement._characteristic_
#: radius``). ``lug`` is 20 x 20 x 10, so ``R = sqrt(10^2 + 10^2 + 5^2) = 15``
#: exactly and a degree costs ``15 * pi/180 = pi/12`` mm. At the seated solution
#: the largest retained pivot of the weighted Jacobian is the unit translational
#: one (1.0) and the smallest is the angular one, so:
#:
#: * a three-mate fixture carries ONE independent angular row and its smallest
#:   pivot is ``pi/12`` — ``kappa = 12/pi``;
#: * ``parallel``'s fixture is the four-mate one, whose extra angular row raises
#:   that pivot by ``sqrt(2)`` — ``kappa = 12/(pi*sqrt(2)) = 6*sqrt(2)/pi``.
#:
#: Measured against the shipped solver on 2026-09-01: 3.8197186342054716 /
#: 3.819718634205688 / 2.70094894847141 / 3.819718634205688 for coincident /
#: concentric / parallel / perpendicular, agreeing with the two closed forms to
#: 5e-15 relative. The two three-mate values differ from each other in the 13th
#: digit because the fixtures order their rows differently, which is exactly why
#: :data:`KAPPA_MATCH_REL` is a band and not an equality.
FIXTURE_KAPPA: Mapping[str, float] = {
    "coincident": 12.0 / math.pi,
    "concentric": 12.0 / math.pi,
    "parallel": 12.0 / (math.pi * math.sqrt(2.0)),
    "perpendicular": 12.0 / math.pi,
}

#: How far the solver's own reported ``kappa`` may sit from :data:`FIXTURE_KAPPA`.
#:
#: This is **not** an accuracy claim about the solve and it is deliberately not
#: 1e-9: ``kappa`` is computed from the weighted Jacobian at a *solved* iterate,
#: and the Gates preamble forbids asserting 1e-9 of a solved quantity. It is an
#: anti-inflation pin, and it only has to be tight enough that a solver cannot
#: quietly buy itself room — the observed agreement is 5e-15 relative, and any
#: widening large enough to matter to ``TRANSFORM_MATCH_EPS`` is many orders
#: above this band.
KAPPA_MATCH_REL = 1e-6

BASE_SRC = """plate = Pos(30.0, 20.0, 5.0) * Box(60.0, 40.0, 10.0)
plate = plate - Pos(20.0, 20.0, 5.0) * Cylinder(radius=4.0, height=30.0)
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "base_top")
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "base_bottom")
tag(plate.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "base_x")
tag(plate.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1], "base_y")
tag(plate.faces().filter_by(GeomType.CYLINDER)[0], "base_bore")
part.geometry = plate
"""

LUG_SRC = """body = Pos(10.0, 10.0, 45.0) * Box(20.0, 20.0, 10.0)
body = body - Pos(10.0, 10.0, 45.0) * Cylinder(radius=4.0, height=30.0)
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "lug_bottom")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "lug_top")
tag(body.faces().filter_by(Axis.X).sort_by(Axis.X)[-1], "lug_x")
tag(body.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1], "lug_y")
tag(body.faces().filter_by(GeomType.CYLINDER)[0], "lug_bore")
part.geometry = body
"""

POST_SRC = """shaft = Pos(20.0, 20.0, 20.0) * Cylinder(radius=4.5, height=20.0)
tag(shaft.faces().filter_by(GeomType.CYLINDER)[0], "post_shaft")
part.geometry = shaft
"""

SLEEVE_SRC = """block = Pos(20.0, -30.0, 20.0) * Box(20.0, 12.0, 12.0)
block = block - Rotation(0.0, 90.0, 0.0) * Pos(-20.0, -30.0, 20.0) * Cylinder(
    radius=3.0, height=40.0
)
tag(block.faces().filter_by(GeomType.CYLINDER)[0], "sleeve_bore")
part.geometry = block
"""

HINGE_A_SRC = """pin = Pos(100.0, 0.0, 5.0) * Cylinder(radius=3.0, height=10.0)
tag(pin.faces().filter_by(GeomType.CYLINDER)[0], "hinge_pin")
part.geometry = pin
"""

HINGE_B_SRC = """block = Pos(100.0, 0.0, 5.0) * Box(16.0, 16.0, 10.0)
block = block - Pos(100.0, 0.0, 5.0) * Cylinder(radius=3.0, height=30.0)
tag(block.faces().filter_by(GeomType.CYLINDER)[0], "hinge_bore")
part.geometry = block
"""

#: The whole cast. Every part is built and published by
#: :func:`open_bench_project`.
BENCH_PARTS: Mapping[str, str] = {
    "base": BASE_SRC,
    "lug": LUG_SRC,
    "post": POST_SRC,
    "sleeve": SLEEVE_SRC,
    "hinge_a": HINGE_A_SRC,
    "hinge_b": HINGE_B_SRC,
}


def assumed(reason: str = "no requirement covers this solve yet") -> dict[str, JSONValue]:
    """The ``assumed`` provenance every fixture entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}


#: The one declared joint, on the hinge pair. It exists so that
#: ``free_part_is_jointed`` and the pose-bound refusal have something real to
#: fire on: in transform space a part whose position forward kinematics owns
#: may not also be claimed by a free transform.
JOINTS: tuple[Mapping[str, JSONValue], ...] = (
    {
        "id": "j-hinge",
        "kind": "revolute",
        "parent": "hinge_a:hinge_pin",
        "child": "hinge_b:hinge_bore",
        "limits": {"min": -90.0, "max": 90.0},
        "provenance": assumed("the hinge pair exists to carry a joint, and only that"),
    },
)

#: One declared pose, so a pose-BOUND constraint can exist to be refused.
POSES: tuple[Mapping[str, JSONValue], ...] = (
    {
        "id": "p-open",
        "joints": {"j-hinge": 30.0},
        "provenance": assumed("a pose to bind a constraint to"),
    },
)

#: The declared constraint set: the four analytic kinds as objective terms, the
#: four ``SOLVER.md`` §3.2 refuses as objective terms, the two class-predicate
#: traps, the contradiction, and one withdrawn entry.
CONSTRAINTS: tuple[Mapping[str, JSONValue], ...] = (
    {
        "id": "c-seat",
        "kind": "coincident",
        "a": "base:base_top",
        "b": "lug:lug_bottom",
        "tol_mm": 0.01,
        "provenance": assumed("the lug is meant to seat flush on the plate"),
    },
    {
        "id": "c-bore",
        "kind": "concentric",
        "a": "base:base_bore",
        "b": "lug:lug_bore",
        "tol_mm": 0.01,
        "provenance": assumed("the two bores are meant to be coaxial"),
    },
    {
        "id": "c-face",
        "kind": "parallel",
        "a": "base:base_x",
        "b": "lug:lug_x",
        "tol_deg": 0.01,
        "provenance": assumed("the lug's +X face runs with the plate's"),
    },
    {
        "id": "c-square",
        "kind": "perpendicular",
        "a": "base:base_x",
        "b": "lug:lug_y",
        "tol_deg": 0.01,
        "provenance": assumed("the lug's +Y face is square to the plate's +X"),
    },
    # The class-predicate traps: zero primary, failing predicate.
    {
        "id": "c-invert",
        "kind": "coincident",
        "a": "base:base_top",
        "b": "lug:lug_top",
        "tol_mm": 0.01,
        "provenance": assumed("the lug's TOP is meant against the plate - it must flip"),
    },
    {
        "id": "c-tilt",
        "kind": "concentric",
        "a": "base:base_bore",
        "b": "sleeve:sleeve_bore",
        "tol_mm": 0.01,
        "provenance": assumed("the sleeve's bore is 90 deg from the plate's - it must turn"),
    },
    # The mm-against-deg trade-off (clause 29). ``c-lid`` wants the lug's TOP
    # against the plate's underside while ``c-seat`` wants its BOTTOM against
    # the plate's top face: the two gaps are 10 mm apart and can both be closed
    # only by turning the lug over, at which point both class predicates are as
    # wrong as they can be. So the answer is a genuine trade between millimetres
    # and degrees, and which side it lands on is decided by the declared
    # weights - which is exactly why SOLVER.md §3.4 refuses to pick one.
    {
        "id": "c-lid",
        "kind": "coincident",
        "a": "base:base_bottom",
        "b": "lug:lug_top",
        "tol_mm": 0.01,
        "provenance": assumed("and the lug's top against the plate's underside - it cannot"),
    },
    # The contradiction: one direction cannot be parallel to two perpendicular ones.
    {
        "id": "c-cross",
        "kind": "parallel",
        "a": "base:base_y",
        "b": "lug:lug_x",
        "tol_deg": 0.01,
        "provenance": assumed("and also along +Y - deliberately, this contradicts c-face"),
    },
    # The four kinds SOLVER.md §3.2 refuses as objective terms, one per reason.
    # Each anchors the free part so that it is also COLLATERAL: §7.3 evaluates
    # them at whatever solution is reached, which is how a proposal that
    # satisfies four mates and drives two solids together says so.
    {
        "id": "c-clear",
        "kind": "no_interference",
        "a": "post",
        "b": "lug",
        "provenance": assumed("plateau: overlap volume is identically 0 over the feasible set"),
    },
    {
        "id": "c-gap",
        "kind": "clearance_min",
        "a": "base",
        "b": "lug",
        "value_mm": 0.1,
        "provenance": assumed("plateau: clearance_min is flat wherever the solids overlap"),
    },
    {
        "id": "c-reach",
        "kind": "distance",
        "a": "base:base_x",
        "b": "lug:lug_x",
        "value_mm": 40.0,
        "tol_mm": 1.0,
        "provenance": assumed("kernel_extremum: the witness pair switches as surfaces slide"),
    },
    {
        "id": "c-fit",
        "kind": "fit",
        "a": "lug:lug_bore",
        "b": "post:post_shaft",
        # A press fit, declared as one: the window is negative because the
        # shaft is fatter than the bore, which `fit_residual` treats as a
        # legitimate declared intent rather than refusing.
        "min_mm": -1.0,
        "max_mm": -0.1,
        "provenance": assumed("pose_invariant: no rigid motion changes hole minus shaft"),
    },
    # Pose-bound: refused as an objective term in transform space, because its
    # residual is already a function of a pose assignment.
    {
        "id": "c-posed",
        "kind": "parallel",
        "a": "base:base_x",
        "b": "lug:lug_x",
        "poses": ["p-open"],
        "tol_deg": 0.01,
        "provenance": assumed("bound to a pose, so it belongs in pose space"),
    },
    # Withdrawn, so `withdrawn_constraint` has something real to fire on.
    {
        "id": "c-old",
        "kind": "parallel",
        "a": "base:base_y",
        "b": "lug:lug_y",
        "tol_deg": 0.01,
        "provenance": assumed("declared then withdrawn, on purpose"),
    },
)


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "bench") -> ProjectLayout:
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


def open_bench_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The whole cast built and published, with the joint, pose and constraints."""
    layout = make_project(root, BENCH_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in BENCH_PARTS:
        build_part(publisher, layout, part)
    joints = JointSet(layout, store)
    for entry in JOINTS:
        joints.declare(entry)
    poses = PoseSet(layout, store, joints)
    for entry in POSES:
        poses.declare(entry)
    constraints = ConstraintSet(layout, store)
    for entry in CONSTRAINTS:
        constraints.declare(entry)
    constraints.withdraw("c-old", "the fixture needs a withdrawn entry to refuse on")
    return layout, store


def placement_request(
    constraints: Sequence[str],
    free: Sequence[str] = ("lug",),
    **overrides: Any,
) -> Any:
    """A well-formed transform-space request, so each test states only its subject."""
    from hephaestus.core.placement import PlacementSolveRequest

    fields: dict[str, Any] = {
        "constraints": tuple(constraints),
        "free": tuple(free),
        "tol": 1e-4,
        "weighting": "unit_scaled_v1",
        "regularization": "min_norm_from_start",
        "provenance": ConstraintProvenance(assumed=True, reason="the gate's own solve"),
    }
    fields.update(overrides)
    return PlacementSolveRequest(**fields)


def rows_of(record: Any, part: str = "lug", solution: int = 0) -> tuple[tuple[float, ...], ...]:
    """The proposed 3x4 rows for one part in one returned solution."""
    placement = record.placements[solution]
    for entry in placement["parts"]:
        if entry["part"] == part:
            return tuple(tuple(float(value) for value in row) for row in entry["rows"])
    raise AssertionError(f"no proposed transform for {part!r} in {placement}")


def proposal_document(layout: ProjectLayout, store: OpStore, record: Any) -> Mapping[str, Any]:
    """The stored proposal document a record's ``proposal_id`` names."""
    from hephaestus.core.project_store.proposals import ProposalSet

    return ProposalSet(layout, store).document(record.proposal_id)


# --------------------------------------------------------------------------
# the three gate-only epsilons (``SOLVER.md`` § Gates)


#: How far a returned transform may sit from a hand-computed one, as
#: ``tol * TRANSFORM_MATCH_FACTOR * kappa`` — where ``kappa`` is the fixture's
#: own recorded condition number of the weighted Jacobian at the solution,
#: :data:`FIXTURE_KAPPA`, and NOT the number the solver reported. The
#: distinction is the whole point of the constant and is argued there.
#:
#: Residual accuracy and SOLUTION accuracy are different quantities related by
#: the conditioning, and this gate says which one it is asserting. A clause
#: demanding 1e-9 of a *solved* quantity is a clause nobody can write: the
#: solver terminates on the declared tolerance, and a tolerance tighter than
#: 1e-9 is refused ``tolerance_below_determinism_floor``.
TRANSFORM_MATCH_FACTOR = 10.0

#: Relative agreement between an analytic Jacobian column and a central finite
#: difference of the SAME reformulated residual. Loose enough to absorb the
#: difference's own truncation and round-off (step ``1e-6``, so ~1e-10 of
#: each), tight enough that a wrong derivative cannot hide.
JACOBIAN_FD_EPS = 1e-5

#: The one epsilon this gate asserts at 1e-9, and it is a PURE-FUNCTION claim
#: over fixed inputs: a §3.3 identity mapping a reformulated residual back to
#: the number the engine measured. Never a solved quantity.
IDENTITY_EPS = 1e-9

#: How far an ANGULAR identity may sit from the engine's own number **at the
#: solution**, where 1e-9 is unreachable — and the reason is the pathology
#: ``SOLVER.md`` §3.3 exists to name, measured rather than asserted away.
#:
#: The engine computes an angle as ``degrees(acos(clamp(dot)))``. Near a mate
#: the dot product is within a few ulp of +/-1, and ``acos``'s derivative there
#: is ``-1/sqrt(1 - u^2)``, so an error of one ulp in ``dot`` becomes an error
#: of ``ulp / sin(theta)`` in the angle. The reformulation
#: (``degrees(asin(||cross||))``) has no such amplification, which is precisely
#: why §3.3 replaces the ``acos`` form for the iteration. So at a converged
#: solution the two forms agree only to what ``acos`` has left: this gate
#: MEASURED 1.2e-8 deg at its tightest fixture (theta ~ 3e-5 deg), and this
#: constant sits two orders above that worst observation.
#:
#: It stays three orders BELOW the tightest bound any design declares
#: (``COINCIDENT_NORMAL_EPS_DEG`` / ``CONCENTRIC_AXIS_EPS_DEG``, both 1e-3
#: deg), which the clause asserts, so the comparison can never go vacuous: a
#: reformulation wrong enough to matter to a class predicate is still caught.
#:
#: **Deviation from ``SOLVER.md`` clause 19 as written**, reported rather than
#: absorbed: the clause asks for 1e-9 "for every fixture and every objective
#: component", and for a length component this gate delivers exactly that, at
#: the solution and away from it. For an ANGULAR component it delivers 1e-9 at
#: a well-conditioned configuration (the clause's own "pure function evaluated
#: at fixed given inputs") and this measured bound at the solution, because
#: 1e-9 there would be demanding of ``acos`` an accuracy it does not have —
#: the same defect the ``tolerance_below_determinism_floor`` rename corrects
#: elsewhere in this spec.
ACOS_CONDITIONING_EPS_DEG = 1e-6

#: The rigid placement the identity clause evaluates its 1e-9 half at: one
#: millimetre and a few degrees off the solved one, so every angle in the
#: fixture is comfortably away from the ``acos`` limit and BOTH forms are
#: well conditioned. Deliberately not the as-built configuration either, where
#: several of these mates sit at exactly 0 or exactly 180 degrees.
IDENTITY_PROBE_TRANSLATION_MM = (11.0, 10.0, -30.0)
IDENTITY_PROBE_ROTATION_DEG = (3.0, 2.0, 5.0)


def kappa_reads_outside_the_pin(suite: Path) -> list[str]:
    """Every ``["kappa"]`` subscript in ``suite`` not inside a ``KAPPA_MATCH_REL`` function.

    The durable half of the 2026-09-01 repair. ``TRANSFORM_MATCH_EPS`` and
    ``PARAM_MATCH_EPS`` are both ``tol * FACTOR * kappa``, so whoever supplies
    ``kappa`` sets the accuracy budget the gate grades against; the Gates
    preamble says the *fixture* supplies it. Fixing the one call site that read
    the solver's own number would leave the next one free to regress, so the
    rule is asserted over the suite's source instead: the solver's reported
    ``kappa`` may be read only where it is being **held to** the recording.

    Matched by AST, never by substring, so that prose about the rule — every
    docstring here included — cannot trip it.
    """
    offenders: list[str] = []
    for path in sorted(suite.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Constant):
                continue
            if node.slice.value != "kappa":
                continue
            enclosing = [
                function
                for function in functions
                if function.lineno <= node.lineno <= (function.end_lineno or function.lineno)
            ]
            innermost = max(enclosing, key=lambda function: function.lineno, default=None)
            scope = (
                "\n".join(lines[innermost.lineno - 1 : innermost.end_lineno])
                if innermost is not None and innermost.end_lineno is not None
                else source
            )
            if "KAPPA_MATCH_REL" not in scope:
                offenders.append(f"{path.name}:{node.lineno}: {lines[node.lineno - 1].strip()}")
    return offenders


def transform_match_eps(kappa: float, tol: float) -> float:
    """``tol * TRANSFORM_MATCH_FACTOR * kappa`` for one fixture.

    Takes the fixture's **recorded** conditioning (:data:`FIXTURE_KAPPA`) as an
    argument rather than reading the record, so the solver cannot supply the
    number that sets its own accuracy budget. Repaired 2026-09-01; the argument
    is on :data:`FIXTURE_KAPPA`.
    """
    return tol * TRANSFORM_MATCH_FACTOR * kappa


def transform_model(layout: ProjectLayout, store: OpStore, request: Any, scratch: Path) -> Any:
    """Rebuild the residual model one request produces, for the Jacobian clause.

    G13B clause 19 asserts that each analytic Jacobian column agrees with a
    central finite difference **of the same reformulated residual**, evaluated
    within one declared tolerance of the solution. "The same" is the whole
    claim, so this reaches into :mod:`hephaestus.core.placement`'s own
    extraction rather than rebuilding an equivalent model out of
    :mod:`hephaestus.geom.solve` primitives: a second assembly of the residual
    vector would be a second implementation, and a clause comparing one
    implementation's derivative against another's would prove nothing about the
    one that actually solves.
    """
    from hephaestus.core.assembly import AnchorResolver
    from hephaestus.core.placement import (
        ConstraintTarget,
        _extract,  # pyright: ignore[reportPrivateUsage]
        _pivots,  # pyright: ignore[reportPrivateUsage]
        _placement_entries,  # pyright: ignore[reportPrivateUsage]
        _transform_variables,  # pyright: ignore[reportPrivateUsage]
        _TransformModel,  # pyright: ignore[reportPrivateUsage]
    )
    from hephaestus.core.project_store.constraints import ConstraintSet
    from hephaestus.core.project_store.publication import Publisher

    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
    state = ConstraintSet(layout, store).state()
    entries = _placement_entries(state, request)
    free = tuple(request.free)
    variables = _transform_variables(free, request.box)
    problem = _extract(
        resolver,
        entries,
        tuple(ConstraintTarget(name) for name in request.constraints),
        variables,
        lambda parts: {part for part in parts if part in set(free)},
        state.active,
    )
    return _TransformModel(
        problem.terms, problem.specs, problem.variables, free, _pivots(resolver, free)
    )
