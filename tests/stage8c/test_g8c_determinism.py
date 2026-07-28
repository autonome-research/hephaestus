"""G8C: the same answer twice, and a geometry service that owes nothing to the engine.

Two gate clauses:

* *determinism (two processes, identical residuals to 1e-9)* — asserted at the
  **product** surface: ``heph assembly check --json`` run twice in two fresh
  interpreters over one project must print the same document. Nothing between
  the published artifact and the printed number — artifact reload, anchor
  resolution, the kernel's own booleans, serialization — may introduce a
  run-to-run difference, or a residual quoted in a review would not be a fact
  about the geometry;
* *geom boundary tests admit ``constraints`` as a pure service* — the eighth
  geom service is asserted here the way an external scorer would meet it: a
  fresh interpreter that imports ``hephaestus.geom``, evaluates a residual over
  shapes it built itself, and never touches the executor, the project store or
  the agent packages. ``core/tests/test_geom_import_boundary.py`` enforces the
  same rule statically over every geom module; what this adds is that the
  constraint evaluator in particular is *usable* on those terms.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest
from _g8c import declare, heph
from hephaestus.testing.tools_fixture import Project

#: The prefixes an assembly-free geometry service may never pull in. ``opstore``
#: is deliberately absent: ``hephaestus.geom`` names ``opstore.types`` for the
#: ``JSONValue`` alias, and importing that package's ``__init__`` brings its
#: siblings along. Naming the JSON shape is not opening a store, and the module
#: boundary that says so is enforced statically, per module, in
#: ``core/tests/test_geom_import_boundary.py``.
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "hephaestus.core.executor",
    "hephaestus.core.project_store",
    "hephaestus.core.assembly",
    "hephaestus.core.cli",
    "hephaestus.core.registry",
    "hephaestus.core.render",
    "hephaestus.agent_bridge",
    "hephaestus.bench",
    "hephaestus.contract",
    "hephaestus.mcp",
)


@pytest.fixture
def measured(pair: Project) -> Project:
    """Four mates spanning three units (mm, mm³, deg) and both verdicts."""
    declare(
        pair,
        "c-register-fit",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.05,
        max_mm=0.25,
    )
    declare(pair, "c-seat-flush", "coincident", "base:rim_top", "lid:seat_face", tol_mm=0.01)
    declare(pair, "c-clear", "no_interference", "base", "lid")
    declare(pair, "c-square", "perpendicular", "base:rim_top", "lid:seat_face", tol_deg=0.01)
    pair.store.close()  # the subprocesses open the same store
    return pair


def residuals(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{constraint id: residual}`` out of one printed status."""
    out: dict[str, dict[str, Any]] = {}
    for row in cast("Sequence[Any]", document["constraints"]):
        record = cast("Mapping[str, Any]", row)
        residual = record["residual"]
        assert residual is not None, record
        out[str(record["id"])] = cast("dict[str, Any]", residual)
    return out


def test_two_processes_measure_the_same_assembly(measured: Project) -> None:
    """Byte-identical documents, and every number equal to 1e-9 besides."""
    first = heph(measured.root, "assembly", "check", "--json", expect=1)
    second = heph(measured.root, "assembly", "check", "--json", expect=1)

    # Byte-identical is the strongest form of the clause, and it is what an
    # operator diffing two runs' output actually relies on.
    assert first == second

    here = residuals(cast("Mapping[str, Any]", json.loads(first)))
    there = residuals(cast("Mapping[str, Any]", json.loads(second)))
    assert (
        sorted(here)
        == sorted(there)
        == [
            "c-clear",
            "c-register-fit",
            "c-seat-flush",
            "c-square",
        ]
    )
    for constraint_id, residual in here.items():
        other = there[constraint_id]
        assert residual["unit"] == other["unit"]
        assert residual["satisfied"] == other["satisfied"]
        for field in ("measured", "slack"):
            assert other[field] == pytest.approx(residual[field], abs=1e-9), (
                constraint_id,
                field,
            )
        # …including the secondary facts and the worst-point locations, which is
        # where a non-deterministic face enumeration would show up first.
        assert other["values"] == residual["values"], constraint_id
        assert other["worst_points"] == residual["worst_points"], constraint_id


def test_a_second_process_agrees_about_what_it_could_not_measure(pair: Project) -> None:
    """Determinism covers the unresolvable states too: same reason, same detail."""
    declare(pair, "c-dangling", "no_interference", "base", "lid:no_such_tag")
    declare(pair, "c-wrong-class", "concentric", "base:rim_top", "lid:seat_face", tol_mm=0.1)
    pair.store.close()

    first = heph(pair.root, "assembly", "check", "--json", expect=1)
    second = heph(pair.root, "assembly", "check", "--json", expect=1)

    assert first == second
    document = cast("Mapping[str, Any]", json.loads(first))
    rows = {
        str(cast("Mapping[str, Any]", row)["id"]): cast("Mapping[str, Any]", row)
        for row in cast("Sequence[Any]", document["constraints"])
    }
    assert rows["c-dangling"]["reason"] == "dangling_selector"
    assert rows["c-wrong-class"]["reason"] == "shape_refused"


# ==========================================================================
# geom as a service: no executor, no store, no project


_SERVICE_PROGRAM = textwrap.dedent(
    """
    import json, sys

    from build123d import Box, Location
    from hephaestus.geom import (
        CONSTRAINT_KINDS,
        ConstraintShapeError,
        OPTIONAL_PARAMS,
        REQUIRED_PARAMS,
        evaluate_residual,
    )

    # Shapes the caller already holds: no project, no build, no artifact.
    a = Box(10.0, 10.0, 10.0)
    b = Box(10.0, 10.0, 10.0).moved(Location((14.0, 0.0, 0.0)))
    residual = evaluate_residual("clearance_min", a, b, {"value_mm": 3.0})
    refused = None
    try:
        evaluate_residual("concentric", a, b, {"tol_mm": 0.1})
    except ConstraintShapeError as exc:
        refused = {"reason": exc.reason, "side": exc.side, "kind": exc.kind}

    print(json.dumps({
        "kinds": list(CONSTRAINT_KINDS),
        "required": {k: list(v) for k, v in REQUIRED_PARAMS.items()},
        "optional": {k: list(v) for k, v in OPTIONAL_PARAMS.items()},
        "measured": residual.measured,
        "satisfied": residual.satisfied,
        "refused": refused,
        "modules": sorted(sys.modules),
    }))
    """
)


def test_constraints_are_a_geometry_service_the_engine_is_not_needed_for() -> None:
    """A fresh interpreter measures a residual with nothing but geom and build123d."""
    result = subprocess.run(
        [sys.executable, "-c", _SERVICE_PROGRAM], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"geom.constraints is not usable on its own:\n{result.stderr}"
    report = cast("Mapping[str, Any]", json.loads(result.stdout))

    # The 8C vocabulary is the geometry package's own, and complete.
    assert list(cast("list[Any]", report["kinds"])) == [
        "no_interference",
        "clearance_min",
        "distance",
        "coincident",
        "concentric",
        "parallel",
        "perpendicular",
        "fit",
    ]
    assert set(cast("Mapping[str, Any]", report["required"])) == set(
        cast("list[Any]", report["kinds"])
    )
    assert set(cast("Mapping[str, Any]", report["optional"])) == set(
        cast("list[Any]", report["kinds"])
    )
    # It measured (4.0 mm of air between two 10 mm cubes 14 mm apart)…
    assert cast("float", report["measured"]) == pytest.approx(4.0, abs=1e-9)
    assert report["satisfied"] is True
    # …and refused the kind those shapes cannot answer, by name rather than with
    # a plausible number.
    refused = cast("Mapping[str, Any]", report["refused"])
    assert refused["reason"] == "not_cylindrical"
    assert refused["kind"] == "concentric"

    loaded = cast("list[str]", report["modules"])
    forbidden = sorted(
        name
        for name in loaded
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)
    )
    assert not forbidden, "evaluating a constraint pulled in the engine:\n" + "\n".join(forbidden)
