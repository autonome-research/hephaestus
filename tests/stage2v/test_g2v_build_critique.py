"""G2V clause: the unrequested post-build critique (``VALIDATION.md`` §4).

The gate clause reads: *"post-build critique (interference pair detection,
``unmatched_request_number`` and ``dimension_mismatch`` on the recorded s2
fixture — it MUST fire there)"*.

The load-bearing test is :func:`test_the_recorded_s2_misread_is_contradicted_by_
the_critique`: the **verbatim recorded** ``bracket-101`` seed-2 script, built
against the **verbatim corpus request**, through the real dispatcher. That run's
own ``CHECKS`` block passes on the geometry it built — 46 mm in Y against a
request that says 40 mm — so this module asserts both halves of §4's reason for
existing: ``run_checks`` says green in the same project in which ``build_part``,
unasked, hands the model the contradiction.

The critique's internals (extraction rules, unit normalization, the pair cap,
intentional-overlap declarations) are covered exhaustively in
``server/tests/test_build_critique.py``; this module is the gate evidence that
the block rides out of the real tool result without anyone requesting it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import load_tasks
from hephaestus.testing.tools_fixture import Project, make_project

#: The recorded seed-2 run, kept where ``server/tests`` keeps it: it is evidence,
#: not example code, so both gates read the same bytes rather than a copy.
FIXTURES = Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures"

#: Two 10 mm cubes sharing a 5 mm slab: a real, undeclared solid overlap.
OVERLAP_SRC = """a = Box(10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN))
a.label = "left"
b = Pos(5.0, 0.0, 0.0) * Box(10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN))
b.label = "right"
part.geometry = Compound(children=[a, b])
part.description = "two overlapping cubes"
part.process = "milling"
"""


@pytest.fixture(scope="module")
def request_text() -> str:
    """The ``bracket-101`` request, read from the corpus and never paraphrased."""
    return load_tasks(["bracket-101"], specs=("prose",))[0].prompt


@pytest.fixture
def s2(tmp_path: Path, request_text: str) -> Iterator[Project]:
    """A project holding the recorded s2 run, with its original request bound."""
    project = make_project(tmp_path / "s2")
    (project.root / "globals.py").write_text(
        (FIXTURES / "bracket_101_s2_globals.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (project.root / "parts" / "bracket.py").write_text(
        (FIXTURES / "bracket_101_s2_bracket.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    project.cad.set_request_text(request_text)
    try:
        yield project
    finally:
        project.close()


def warnings_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    critique = cast("dict[str, Any]", result["critique"])
    return [cast("dict[str, Any]", w) for w in cast("list[Any]", critique["warnings"])]


def kinds_of(result: dict[str, Any]) -> set[str]:
    return {str(warning["kind"]) for warning in warnings_of(result)}


def test_the_recorded_s2_misread_is_contradicted_by_the_critique(s2: Project) -> None:
    """THE case §4 exists for: nobody asked, and the numbers do not agree.

    The agent's own acceptance test passes on this geometry. The critique rides
    back in the same ``build_part`` result and names both numbers.
    """
    result = cast("dict[str, Any]", s2.call("build_part", {"name": "bracket"}))
    assert result["status"] == "ok"

    # The self-authored spec test is green on the misreading it encodes …
    checks = cast("dict[str, Any]", s2.call("run_checks", {"scope": "part", "name": "bracket"}))
    passed = cast("dict[str, Any]", checks["checks"])
    assert all(cast("dict[str, Any]", entry)["pass"] for entry in passed.values())

    # … and the unrequested critique contradicts it in the same tool result.
    assert {"dimension_mismatch", "unmatched_request_number"} <= kinds_of(result)
    mismatches = [w for w in warnings_of(result) if w["kind"] == "dimension_mismatch"]
    assert [(w["request_value_mm"], w["axis"], w["dimension_value_mm"]) for w in mismatches] == [
        (40.0, "y", pytest.approx(46.0, abs=1e-6))
    ]
    unmatched = [
        w
        for w in warnings_of(result)
        if w["kind"] == "unmatched_request_number" and w["request_value_mm"] == 40.0
    ]
    assert unmatched and unmatched[0]["axis"] == "y"


def test_the_critique_rides_on_every_successful_build(s2: Project) -> None:
    """It is a property of the result, not of the arguments the model chose."""
    result = cast("dict[str, Any]", s2.call("build_part", {"name": "bracket"}))
    critique = cast("dict[str, Any]", result["critique"])
    # Nothing in build_part's arguments can ask for — or decline — any of these.
    assert set(critique) >= {"interference", "manifold", "prompt_number_diff", "warnings"}
    manifold = cast("dict[str, Any]", critique["manifold"])
    assert manifold["available"] is True and manifold["sealed"] is True


def test_an_undeclared_overlap_is_reported_with_its_pair_and_volume(tmp_path: Path) -> None:
    project = make_project(tmp_path / "overlap")
    try:
        (project.root / "parts" / "bracket.py").write_text(OVERLAP_SRC, encoding="utf-8")
        result = cast("dict[str, Any]", project.call("build_part", {"name": "bracket"}))
        assert result["status"] == "ok"

        interference = cast("dict[str, Any]", result["critique"]["interference"])
        overlaps = [cast("dict[str, Any]", p) for p in cast("list[Any]", interference["overlaps"])]
        assert overlaps, "an undeclared 5 mm overlap must be reported"
        assert overlaps[0]["volume_mm3"] == pytest.approx(500.0, rel=1e-3)
        assert overlaps[0]["a"] != overlaps[0]["b"]
        assert interference["pairs_measured"] == 1 and interference["pairs_capped"] is False
        # The pair and its volume ride in the flattened warning list too.
        flagged = [w for w in warnings_of(result) if w["kind"] == "interference"]
        assert len(flagged) == 1
        assert flagged[0]["volume_mm3"] == pytest.approx(500.0, rel=1e-3)
    finally:
        project.close()
