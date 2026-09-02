# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared scaffolding for the Gate G13C parameter-solve suite (not a test module).

Everything here is asserted against REAL published artifacts. The parts below
are ordinary part scripts, built through the executor and published through the
project store, and a parameter-space solve then **rebuilds them** — every
candidate is a preview build (``SOLVER.md`` §2C), which is the whole method and
also the whole safety argument: a preview is never current and persists no
override, so the project this suite measures is exactly where it started.

Scaffolded here rather than reusing ``tests/stage13a``'s arm or
``tests/stage13b``'s bench (the ``_g8c.make_assembly_project`` rationale,
restated a third time): a gate assertion must not be satisfiable by a change
made elsewhere. The three casts also have different shapes on purpose — 13A's
is a jointed chain, 13B's has no ``Param`` anywhere, and this one is built
entirely out of knobs, because in parameter space a part with no declared
``Param`` has nothing to solve for.

The cast, in world mm (right-handed, +Z up), at as-built
--------------------------------------------------------
::

    post    a 12 x 12 column standing on z = 0, ``p.post_h`` tall
            (default 20, bounds 5..60). Tags ``post_top`` (+Z at z =
            post_h), ``post_bottom`` (-Z at z = 0).
    shelf   a 50 x 50 plate ``hc.plate_t`` (6) thick whose underside sits at
            the PROJECT parameter ``hc.shelf_z`` (default 10, bounds 0..60).
            Tags ``shelf_under`` (-Z), ``shelf_top`` (+Z).
    boss    a 30 x 30 x 12 housing with a through bore of ``hc.bore_r`` (8).
            Tag ``boss_bore``. Nothing about it is adjustable: it is the
            fixed half of the fit.
    cap     a flange plus a spigot of ``p.spigot_r`` (default 8, bounds
            6..8). Tag ``cap_spigot``.
    pin     a Ø``p.pin_r`` post on the Z axis (default 3, bounds **0**..5).
            Tag ``pin_shaft``. The zero floor is deliberate and is the only
            reason this part exists: a build at radius 0 FAILS, which is what
            gives ``unbuildable_parameter_iterate`` something real to fire on
            without a script that raises on purpose. **Where it fails is worth
            recording**, because it is not where a reader would guess: the
            degenerate cylinder is constructed happily and the worker then dies
            FINGERPRINTING it — ``normal_at`` on a side face of zero radius
            raises ``StdFail_NotDone`` out of OCP, which is not a script
            exception and leaves the worker exiting non-zero rather than
            returning a failed ``BuildResult``. Both are "a candidate whose
            preview build failed" (``SOLVER.md`` §6.3) and
            ``_PreviewBuilder.build`` names both, so the fixture exercises the
            harder of the two seams rather than the one already covered.

The hand-computed answer, and why it is arithmetic rather than "about"
----------------------------------------------------------------------
The two-``Param`` fixture is ``c-seat`` + ``c-lift`` over
``(hc.shelf_z, post.post_h)``, and it is a genuinely determined **linear**
pair a reader can solve on paper:

* ``c-seat`` is ``coincident(post:post_top, shelf:shelf_under)``. The gap is
  ``dot(c_b - c_a, n_a)`` with ``n_a`` = +Z, so only the z components matter:
  ``c_a.z = post_h``, ``c_b.z = shelf_z``, gap ``= shelf_z - post_h``. The
  normals are +Z against -Z, already opposed, so the class predicate holds at
  every iterate and the mate is satisfied exactly when ``shelf_z == post_h``.
* ``c-lift`` is ``distance(shelf:shelf_top, post:post_bottom)`` declared at
  ``value_mm = 38``. Both faces are horizontal planes with overlapping XY
  footprints, so the separation is the vertical one: ``shelf_z + plate_t``.
  It is satisfied exactly when ``shelf_z = 38 - 6 = 32``.

So the optimum is ``shelf_z = post_h = 32.0`` exactly, both comfortably inside
their declared bounds — and :data:`OPTIMUM` states it as the arithmetic above
rather than as whatever the solver produced.
"""

from __future__ import annotations

import ast
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.constraints import ConstraintProvenance, ConstraintSet
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "BENCH_PARTS",
    "CONSTRAINTS",
    "FIXTURE_KAPPA",
    "GLOBALS_SRC",
    "KAPPA_MATCH_REL",
    "OPTIMUM",
    "PARAM_MATCH_FACTOR",
    "SOLVE_TOL",
    "assumed",
    "build_part",
    "kappa_reads_outside_the_pin",
    "make_project",
    "open_bench_project",
    "param_request",
    "param_values",
    "proposal_document",
]

GLOBALS_SRC = """PARAMS = {
    "shelf_z": Param(10.0, min=0.0, max=60.0),
}

plate_t = 6.0
shelf_w = 50.0
post_w = 12.0
bore_r = 8.0
boss_w = 30.0
boss_h = 12.0
cap_r = 14.0
cap_t = 5.0
spigot_len = 9.0
"""

POST_SRC = """PARAMS = {
    "post_h": Param(20.0, min=5.0, max=60.0),
}

column = Pos(0.0, 0.0, p.post_h / 2) * Box(hc.post_w, hc.post_w, p.post_h)
tag(column.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "post_top")
tag(column.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "post_bottom")
part.geometry = column
"""

SHELF_SRC = """plate = Pos(0.0, 0.0, hc.shelf_z + hc.plate_t / 2) * Box(
    hc.shelf_w, hc.shelf_w, hc.plate_t
)
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "shelf_under")
tag(plate.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "shelf_top")
part.geometry = plate
"""

BOSS_SRC = """block = Pos(0.0, 0.0, hc.boss_h / 2) * Box(hc.boss_w, hc.boss_w, hc.boss_h)
block = block - Pos(0.0, 0.0, hc.boss_h / 2) * Cylinder(
    radius=hc.bore_r, height=hc.boss_h * 3
)
tag(block.faces().filter_by(GeomType.CYLINDER)[0], "boss_bore")
part.geometry = block
"""

CAP_SRC = """PARAMS = {
    "spigot_r": Param(8.0, min=6.0, max=8.0),
}

flange = Pos(0.0, 0.0, hc.boss_h + hc.cap_t / 2) * Cylinder(
    radius=hc.cap_r, height=hc.cap_t
)
spigot = Pos(0.0, 0.0, hc.boss_h - hc.spigot_len / 2) * Cylinder(
    radius=p.spigot_r, height=hc.spigot_len
)
body = flange + spigot
tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "cap_spigot")
part.geometry = body
"""

PIN_SRC = """PARAMS = {
    "pin_r": Param(3.0, min=0.0, max=5.0),
}

shaft = Pos(0.0, 0.0, 30.0) * Cylinder(radius=p.pin_r, height=10.0)
tag(shaft.faces().filter_by(GeomType.CYLINDER)[0], "pin_shaft")
part.geometry = shaft
"""

#: The whole cast. Every part is built and published by
#: :func:`open_bench_project`.
BENCH_PARTS: Mapping[str, str] = {
    "post": POST_SRC,
    "shelf": SHELF_SRC,
    "boss": BOSS_SRC,
    "cap": CAP_SRC,
    "pin": PIN_SRC,
}

#: The hand-computed optimum of the two-``Param`` fixture, derived in the module
#: docstring from the fixture's own dimensions rather than measured.
OPTIMUM: Mapping[str, float] = {"hc.shelf_z": 32.0, "post.post_h": 32.0}

#: The tolerance every clause-44 solve declares. Above the determinism floor by
#: six orders, and chosen rather than inherited: a 2C residual is measured on
#: geometry the kernel re-tessellated, so a tolerance at the floor would be
#: asking the solve to terminate on digits nothing here claims.
SOLVE_TOL: float = 1e-3

#: ``PARAM_MATCH_EPS``'s declared factor (``SOLVER.md`` § Gates):
#: ``tol * PARAM_MATCH_FACTOR * kappa`` over the fixture's own recorded
#: conditioning. Residual accuracy and SOLUTION accuracy are different
#: quantities related by the conditioning, and the gate says which one it is
#: asserting — it never asserts 1e-9 of a solved quantity, because the solver
#: terminates on the declared tolerance and a tolerance tighter than 1e-9 is
#: refused ``tolerance_below_determinism_floor``.
PARAM_MATCH_FACTOR: float = 10.0

#: The clause-44 fixture's condition number of the weighted Jacobian at the
#: optimum, **recorded here beside** :data:`OPTIMUM` — the ``SOLVER.md`` § Gates
#: definition of ``kappa``, and the number ``PARAM_MATCH_EPS`` is derived from.
#:
#: **Repaired 2026-09-01**, after an independent verifier found the same defect
#: in G13B clause 18: the epsilon was being derived from
#: ``record.solver_core["kappa"]``, the solver's OWN reported conditioning, with
#: nothing pinning it — so a solver reporting an inflated number would have
#: widened the tolerance it was graded against and the gate would have stayed
#: green. The recording moves the number to the fixture and
#: :data:`KAPPA_MATCH_REL` holds the solver's report to it.
#:
#: **And it is exactly 2, on paper.** Both objective rows are lengths, so both
#: carry ``unit_scaled_v1``'s mm weight of 1.0 and the weighting drops out
#: entirely. ``c-seat`` is ``shelf_z - post_h`` and ``c-lift`` is
#: ``shelf_z + plate_t - 38``, so over ``(hc.shelf_z, post.post_h)`` the
#: Jacobian is ``[[1, -1], [1, 0]]``. Column-pivoted QR takes the first column
#: (norm ``sqrt(2)``) as the leading pivot; the second column's component
#: orthogonal to it is ``(-1/2, 1/2)``, of norm ``1/sqrt(2)``. So the retained
#: pivots are ``sqrt(2)`` and ``1/sqrt(2)`` and their ratio is **2**.
#:
#: Measured against the shipped solver on 2026-09-01: 1.9999999999855673, which
#: is 2 to 7e-12 relative. It is not closer because a parameter-space Jacobian
#: is a finite difference over **rebuilt geometry** (``SOLVER.md`` §2C — every
#: candidate is a preview build), and that is precisely the digit budget §2C
#: says a 2C solve has. Hence a band rather than an equality.
FIXTURE_KAPPA: float = 2.0

#: How far the solver's own reported ``kappa`` may sit from :data:`FIXTURE_KAPPA`.
#:
#: Not an accuracy claim about the solve, and deliberately not 1e-9: ``kappa`` is
#: computed from the weighted Jacobian at a *solved* iterate and the Gates
#: preamble forbids asserting 1e-9 of a solved quantity. It is an anti-inflation
#: pin, and it sits four orders above the 7e-12 actually observed — loose enough
#: that a rebuilt-geometry finite difference cannot trip it, tight enough that a
#: solver cannot quietly buy itself room in ``PARAM_MATCH_EPS``.
KAPPA_MATCH_REL: float = 1e-6


def assumed(reason: str = "no requirement covers this solve yet") -> dict[str, JSONValue]:
    """The ``assumed`` provenance every fixture entry that cites no requirement carries."""
    return {"assumed": True, "reason": reason}


#: The declared constraint set: the determined pair, the ``fit`` that is an
#: objective term HERE and refused in transform space, an insensitive-and-
#: unsatisfied trap, an insensitive-and-SATISFIED one (which must NOT be
#: refused), the two plateau kinds, and one withdrawn entry.
CONSTRAINTS: tuple[Mapping[str, JSONValue], ...] = (
    {
        "id": "c-seat",
        "kind": "coincident",
        "a": "post:post_top",
        "b": "shelf:shelf_under",
        "tol_mm": 0.05,
        "provenance": assumed("the shelf is meant to seat flush on the post"),
    },
    {
        "id": "c-lift",
        "kind": "distance",
        "a": "shelf:shelf_top",
        "b": "post:post_bottom",
        "value_mm": 38.0,
        "tol_mm": 0.05,
        "provenance": assumed("the shelf's top face stands 38 mm above the post's base"),
    },
    # A target the declared box cannot reach: the shelf's top face 100 mm above
    # the post's base needs `shelf_z = 94`, and `shelf_z` is declared 0..60. The
    # step is shortened to the boundary, `hc.shelf_z` comes back named in
    # `bounds_active`, and the verdict is verdict 4 — never a success, and never
    # a clamped value reported as if it were a solution.
    {
        "id": "c-tall",
        "kind": "distance",
        "a": "shelf:shelf_top",
        "b": "post:post_bottom",
        "value_mm": 100.0,
        "tol_mm": 0.05,
        "provenance": assumed("a stand-off the declared Param box cannot reach"),
    },
    # `fit` is `not_an_objective_kind(pose_invariant)` in transform space and a
    # legitimate objective term here: no rigid motion changes hole minus shaft,
    # and a Param change is exactly what does.
    {
        "id": "c-fit",
        "kind": "fit",
        "a": "boss:boss_bore",
        "b": "cap:cap_spigot",
        "min_mm": 0.15,
        "max_mm": 0.35,
        "provenance": assumed("the spigot is meant to be a slip fit in the bore"),
    },
    # Insensitive to `cap.spigot_r` AND unsatisfied at as-built: the
    # `no_free_variable_affects` positive.
    {
        "id": "c-square",
        "kind": "perpendicular",
        "a": "post:post_top",
        "b": "shelf:shelf_top",
        "tol_deg": 0.01,
        "provenance": assumed("two parallel faces are 0 deg apart, never 90 - unsatisfiable"),
    },
    # Insensitive to `cap.spigot_r` and SATISFIED at as-built: the negative the
    # second conjunct exists for. A pin on the Z axis is coaxial with the
    # boss's bore whatever radius either of them has.
    {
        "id": "c-coax",
        "kind": "concentric",
        "a": "boss:boss_bore",
        "b": "pin:pin_shaft",
        "tol_mm": 0.05,
        "provenance": assumed("the pin runs down the bore's own axis, at any radius"),
    },
    # The two plateau kinds: refused as objective terms in BOTH spaces, and
    # still evaluated at whatever solution is reached (§7.3).
    {
        "id": "c-clear",
        "kind": "no_interference",
        "a": "boss",
        "b": "cap",
        "provenance": assumed("plateau: overlap volume is identically 0 over the feasible set"),
    },
    {
        "id": "c-gap",
        "kind": "clearance_min",
        "a": "post",
        "b": "shelf",
        "value_mm": 0.1,
        "provenance": assumed("plateau: clearance_min is flat wherever the solids overlap"),
    },
    {
        "id": "c-old",
        "kind": "parallel",
        "a": "post:post_top",
        "b": "shelf:shelf_top",
        "tol_deg": 0.01,
        "provenance": assumed("declared then withdrawn, on purpose"),
    },
)


def make_project(root: Path, parts: Mapping[str, str], *, name: str = "bench") -> ProjectLayout:
    """Write a minimal real project tree under ``root`` and load its layout."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'name = "{name}"\nunits = "mm"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    parts_dir = root / "parts"
    parts_dir.mkdir(exist_ok=True)
    for part, script in parts.items():
        (parts_dir / f"{part}.py").write_text(script, encoding="utf-8")
    return load_project(root)


def build_part(publisher: Publisher, layout: ProjectLayout, part: str) -> None:
    """Freeze, build and publish one part through the ordinary pipeline.

    The hc projection is synced from the worker's own ``hc_state``, exactly as
    ``core/cli.py:195-208`` does: without it a part that READS ``hc.shelf_z``
    publishes against a projection that never recorded the name, and
    publication refuses it as a consumed name no longer defined. The parts here
    are the first fixture in this repo whose geometry is a function of a
    project parameter, so this is the first fixture that needs it.
    """
    frozen = publisher.freeze_inputs(part)
    build = run_build(
        BuildRequest(part=part, script=frozen.script, globals_source=frozen.globals_source),
        backend=UnsafeLocalBackend(),
        out_dir=layout.store_root / "builds" / f"{part}-seed",
    )
    assert build.result.status == "ok", build.result.error
    hc_state = build.worker_result.get("hc_state")
    if isinstance(hc_state, dict):
        live = publisher.projections.state().hc_state
        if canonical_json(dict(live)) != canonical_json(dict(hc_state)):
            publisher.projections.apply_hc_state(
                hc_state, reason="globals.py or project parameters changed"
            )
    outcome = publisher.publish_build(build, op_id=f"build-{part}-{build.result.artifact_ref}")
    assert outcome.kind == "current", outcome.details


def open_bench_project(root: Path) -> tuple[ProjectLayout, OpStore]:
    """The whole cast built and published, with the declared constraints."""
    layout = make_project(root, BENCH_PARTS)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    for part in BENCH_PARTS:
        build_part(publisher, layout, part)
    constraints = ConstraintSet(layout, store)
    for entry in CONSTRAINTS:
        constraints.declare(entry)
    constraints.withdraw("c-old", "the fixture needs a withdrawn entry to refuse on")
    return layout, store


def param_request(
    constraints: Sequence[str],
    free: Sequence[str],
    **overrides: Any,
) -> Any:
    """A well-formed parameter-space request, so each test states only its subject."""
    from hephaestus.core.placement import PlacementSolveRequest

    fields: dict[str, Any] = {
        "constraints": tuple(constraints),
        "free": tuple(free),
        "tol": SOLVE_TOL,
        "weighting": "unit_scaled_v1",
        "regularization": "min_norm_from_start",
        "provenance": ConstraintProvenance(assumed=True, reason="the gate's own solve"),
        "space": "parameters",
    }
    fields.update(overrides)
    return PlacementSolveRequest(**fields)


def param_values(record: Any, solution: int = 0) -> dict[str, float]:
    """``{variable name: value}`` for one returned solution."""
    placement = record.placements[solution]
    return {
        str(entry["name"]): float(entry["value"])
        for entry in placement["parameters"]  # pyright: ignore[reportUnknownVariableType]
    }


def kappa_reads_outside_the_pin(suite: Path) -> list[str]:
    """Every ``["kappa"]`` subscript in ``suite`` not inside a ``KAPPA_MATCH_REL`` function.

    The durable half of the 2026-09-01 repair, and the 13B twin of it
    (``tests/stage13b/_g13b.py``). ``PARAM_MATCH_EPS`` is
    ``tol * PARAM_MATCH_FACTOR * kappa``, so whoever supplies ``kappa`` sets the
    accuracy budget clause 44 grades against; the Gates preamble says the
    *fixture* supplies it. Fixing the one call site that read the solver's own
    number would leave the next one free to regress, so the rule is asserted
    over this suite's source: the solver's reported ``kappa`` may be read only
    where it is being **held to** :data:`FIXTURE_KAPPA`.

    Copied rather than imported from 13B, for the reason every fixture in this
    file is scaffolded rather than shared: a gate assertion must not be
    satisfiable by a change made in another sub-stage's directory — and
    ``uv run pytest tests/stage13c`` must pass on its own, which an import of
    another suite's private module would not survive.

    Matched by AST, never by substring, so that prose about the rule cannot
    trip it.
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


def proposal_document(layout: ProjectLayout, store: OpStore, record: Any) -> Mapping[str, Any]:
    """The stored proposal document a record's ``proposal_id`` names."""
    from hephaestus.core.project_store.proposals import ProposalSet

    return ProposalSet(layout, store).document(record.proposal_id)


def copy_project(source: Path, target: Path) -> tuple[ProjectLayout, OpStore]:
    """A byte copy of a built project, for a test that must mutate one."""
    shutil.copytree(source, target)
    layout = load_project(target)
    return layout, open_store(layout)
