"""The unrequested post-build critique (``VALIDATION.md`` §4).

Every rung here must fire **by rule**: no test asks a model to be careful, and
every assertion is against ``build_part``'s own result on real built geometry.

The load-bearing case is ``test_s2_bracket_fires_both_number_warnings``: the
recorded ``bracket-101`` seed-2 script (46 mm in Y against a request that says
40 mm, with a self-authored ``CHECKS`` envelope that encodes the misreading and
passes) MUST produce both ``unmatched_request_number`` and ``dimension_mismatch``.
That is the measured failure this whole stage exists to catch; if it ever goes
silent here, the ladder is decorative.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import (
    MAX_INTERFERENCE_PAIRS,
    CadOps,
    request_numbers,
)
from hephaestus.bench.harness import load_tasks
from hephaestus.core.project_store.layout import load_project, open_store

from opstore import OpStore

FIXTURES = Path(__file__).parent / "fixtures"

#: Patch target for the pair cap: the constant is read at call time inside the
#: private critique module, so the bound is exercised where it actually bites.
_CAP_TARGET = "hephaestus.agent_bridge.cad_ops._critique.MAX_INTERFERENCE_PAIRS"

#: Two 10 mm cubes sharing a 5 mm slab — a real, undeclared solid overlap.
OVERLAP_SRC = """a = Box(10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN))
a.label = "left"
b = Pos(5.0, 0.0, 0.0) * Box(10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN))
b.label = "right"
part.geometry = Compound(children=[a, b])
part.description = "two overlapping cubes"
part.process = "milling"
"""

#: The same pair, moved apart: nothing to warn about.
CLEAR_SRC = """a = Box(10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN))
a.label = "left"
b = Pos(20.0, 0.0, 0.0) * Box(10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN))
b.label = "right"
part.geometry = Compound(children=[a, b])
part.description = "two clear cubes"
part.process = "milling"
"""

#: The overlapping pair, with the overlap declared intentional in the script.
DECLARED_SRC = OVERLAP_SRC.replace(
    'part.description = "two overlapping cubes"',
    'part.feature("press_boss").intentional_overlap = True\n'
    'part.description = "two overlapping cubes, on purpose"',
)

#: Four cubes in a row, each overlapping its neighbour: six pairs to cap.
FOUR_SOLIDS_SRC = """boxes = []
for i in range(4):
    box = Pos(i * 5.0, 0.0, 0.0) * Box(
        10.0, 10.0, 10.0, align=(Align.MIN, Align.MIN, Align.MIN)
    )
    box.label = "cube"
    boxes.append(box)
part.geometry = Compound(children=boxes)
part.description = "four overlapping cubes"
part.process = "milling"
"""

GLOBALS_SRC = 'PARAMS = {\n    "unused": Param(1.0, min=0.5, max=2.0),\n}\n\nSPARE = 1.0\n'


def _project(
    root: Path, parts: dict[str, str], *, globals_src: str = GLOBALS_SRC
) -> tuple[CadOps, OpStore]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "critique"\n', encoding="utf-8")
    (root / "globals.py").write_text(globals_src, encoding="utf-8")
    for name, source in parts.items():
        (root / "parts" / f"{name}.py").write_text(source, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    return CadOps(layout, store), store


@pytest.fixture
def solids_project(tmp_path: Path) -> Iterator[CadOps]:
    cad, store = _project(
        tmp_path / "solids",
        {
            "overlapping": OVERLAP_SRC,
            "clear": CLEAR_SRC,
            "declared": DECLARED_SRC,
            "four": FOUR_SOLIDS_SRC,
        },
    )
    try:
        yield cad
    finally:
        store.close()


def _critique_of(cad: CadOps, name: str) -> dict[str, Any]:
    result = cad.build_part(name)
    assert result["status"] == "ok", result.get("error")
    critique = result["critique"]
    assert isinstance(critique, dict)
    return cast("dict[str, Any]", critique)


def _kinds(block: dict[str, Any]) -> list[str]:
    return [str(w["kind"]) for w in cast("list[dict[str, Any]]", block["warnings"])]


# --------------------------------------------------------------------------
# interference


def test_overlapping_solids_are_reported_without_being_asked(solids_project: CadOps) -> None:
    """A build nobody asked to check comes back naming the overlapping pair."""
    critique = _critique_of(solids_project, "overlapping")
    interference = cast("dict[str, Any]", critique["interference"])
    assert interference["solids"] == 2
    assert interference["pairs_measured"] == 1
    assert interference["pairs_capped"] is False
    warnings = [
        w
        for w in cast("list[dict[str, Any]]", interference["warnings"])
        if w["kind"] == "interference"
    ]
    assert len(warnings) == 1
    warning = warnings[0]
    assert {warning["a"], warning["b"]} == {"solid#1", "solid#2"}
    # 5 x 10 x 10 of shared material, and the volume is reported, not just a flag.
    assert warning["volume_mm3"] == pytest.approx(500.0, rel=1e-6)
    assert "interference" in _kinds(critique)


def test_clear_solids_are_silent(solids_project: CadOps) -> None:
    """No overlap, no warning — the rung is a measurement, not a mood."""
    critique = _critique_of(solids_project, "clear")
    interference = cast("dict[str, Any]", critique["interference"])
    assert interference["pairs_measured"] == 1
    assert interference["overlaps"] == []
    assert "interference" not in _kinds(critique)


def test_intentional_overlap_declaration_suppresses_the_warning(solids_project: CadOps) -> None:
    """``part.feature(...).intentional_overlap`` declares it; the volume still shows."""
    critique = _critique_of(solids_project, "declared")
    interference = cast("dict[str, Any]", critique["interference"])
    assert interference["declared_intentional"] == ["feature:press_boss"]
    assert "interference" not in _kinds(critique)
    # Suppressing the *warning* never suppresses the *measurement*.
    overlaps = cast("list[dict[str, Any]]", interference["overlaps"])
    assert len(overlaps) == 1
    assert overlaps[0]["volume_mm3"] == pytest.approx(500.0, rel=1e-6)


def test_a_ledger_entry_can_declare_the_overlap_intentional(solids_project: CadOps) -> None:
    """The other §4 declaration channel: the requirement ledger."""
    solids_project.record_requirements(
        [
            {
                "id": "R1",
                "text": "the boss is a press fit into the housing",
                "source": "assumed",
                "rationale": "shrink-fit joint",
                "material": False,
                "applies_to": "intentional_overlap",
            }
        ],
        op_id="op-ledger-overlap",
    )
    critique = _critique_of(solids_project, "overlapping")
    interference = cast("dict[str, Any]", critique["interference"])
    assert interference["declared_intentional"] == ["requirement:R1"]
    assert "interference" not in _kinds(critique)


def test_pair_evaluation_is_capped_and_says_so(
    solids_project: CadOps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pass is bounded so N solids cannot eat the 300 s CAD budget."""
    monkeypatch.setattr(_CAP_TARGET, 2)
    critique = _critique_of(solids_project, "four")
    interference = cast("dict[str, Any]", critique["interference"])
    assert interference["solids"] == 4
    assert interference["pairs_total"] == 6
    assert interference["pairs_measured"] == 2
    assert interference["pairs_capped"] is True
    assert "interference_pairs_capped" in _kinds(critique)


def test_uncapped_run_measures_every_pair(solids_project: CadOps) -> None:
    """With the real cap in force the same part is fully measured."""
    assert MAX_INTERFERENCE_PAIRS >= 6
    interference = cast("dict[str, Any]", _critique_of(solids_project, "four")["interference"])
    assert interference["pairs_measured"] == 6
    assert interference["pairs_capped"] is False


# --------------------------------------------------------------------------
# manifold


def test_manifold_is_surfaced_on_every_successful_build(solids_project: CadOps) -> None:
    manifold = cast("dict[str, Any]", _critique_of(solids_project, "clear")["manifold"])
    assert manifold["available"] is True
    assert manifold["sealed"] is True
    assert manifold["genus"] == 0
    assert manifold["solids"] == 2


# --------------------------------------------------------------------------
# prompt_number_diff — the recorded s2 failure


BRACKET_101 = "bracket-101"


@pytest.fixture(scope="module")
def bracket_request() -> str:
    """The bracket-101 request text, read from the corpus (never paraphrased)."""
    task = load_tasks([BRACKET_101], specs=("prose",))[0]
    return task.prompt


@pytest.fixture
def s2_project(tmp_path: Path) -> Iterator[CadOps]:
    cad, store = _project(
        tmp_path / "s2",
        {"bracket": (FIXTURES / "bracket_101_s2_bracket.py").read_text(encoding="utf-8")},
        globals_src=(FIXTURES / "bracket_101_s2_globals.py").read_text(encoding="utf-8"),
    )
    try:
        yield cad
    finally:
        store.close()


def test_s2_bracket_fires_both_number_warnings(s2_project: CadOps, bracket_request: str) -> None:
    """THE case: 46 mm built against a request that says 40 mm (Y).

    The recorded run's own ``CHECKS`` envelope passes on this geometry. The
    critique — which the agent never asked for — contradicts it in the same
    tool result, naming both numbers.
    """
    s2_project.set_request_text(bracket_request)
    critique = _critique_of(s2_project, "bracket")
    diff = cast("dict[str, Any]", critique["prompt_number_diff"])
    dimensions = cast("dict[str, float]", diff["dimensions"])
    # The misreading, measured: 60 x 46 x 40 against a 60 x 40 x 40 request.
    assert dimensions["bbox.x"] == pytest.approx(60.0, abs=1e-6)
    assert dimensions["bbox.y"] == pytest.approx(46.0, abs=1e-6)
    assert dimensions["bbox.z"] == pytest.approx(40.0, abs=1e-6)

    warnings = cast("list[dict[str, Any]]", diff["warnings"])
    mismatches = [w for w in warnings if w["kind"] == "dimension_mismatch"]
    assert [
        (w["request_value_mm"], w["axis"], w["dimension"], w["dimension_value_mm"])
        for w in mismatches
    ] == [(40.0, "y", "bbox.y", pytest.approx(46.0, abs=1e-6))]

    unmatched = [
        w
        for w in warnings
        if w["kind"] == "unmatched_request_number" and w["request_value_mm"] == 40.0
    ]
    assert unmatched, "the 40 mm the request states on Y is matched by nothing built"
    assert unmatched[0]["axis"] == "y"

    # Both ride in the flattened list the agent reads.
    assert {"dimension_mismatch", "unmatched_request_number"} <= set(_kinds(critique))
    # …and the 40 mm overall *height* the same request states is matched, so the
    # rung discriminates rather than warning about every number it sees.
    heights = [
        n
        for n in cast("list[dict[str, Any]]", diff["numbers"])
        if n["axis"] == "z" and n["value_mm"] == 40.0
    ]
    assert heights and heights[0]["matched"] is True


def test_checks_thresholds_are_dimensions_the_script_claims(
    s2_project: CadOps, bracket_request: str
) -> None:
    """The self-authored envelope's numbers are part of the compared set."""
    s2_project.set_request_text(bracket_request)
    critique = _critique_of(s2_project, "bracket")
    diff = cast("dict[str, Any]", critique["prompt_number_diff"])
    dimensions = cast("dict[str, float]", diff["dimensions"])
    assert "checks_threshold:46.1" in dimensions


def test_prompt_number_diff_is_omitted_without_a_request(s2_project: CadOps) -> None:
    """No request in hand ⇒ no diff. It is never faked."""
    assert s2_project.request_text is None
    critique = _critique_of(s2_project, "bracket")
    assert "prompt_number_diff" not in critique
    assert "interference" in critique and "manifold" in critique


# --------------------------------------------------------------------------
# the extraction rules themselves (cheap, no build)


@pytest.mark.parametrize(
    ("text", "value_mm", "axis"),
    [
        ("a 60 mm (X) plate", 60.0, "x"),
        ("40 mm (Y) base plate", 40.0, "y"),
        ("the overall height is 40 mm", 40.0, "z"),
        ("of the same 60 mm length", 60.0, "x"),
        ("120 mm in X", 120.0, "x"),
        ("2.5 cm thick", 25.0, None),
        ('a 1" bore', 25.4, None),
        ("12 mm from the -X end", 12.0, None),
    ],
)
def test_request_number_extraction(text: str, value_mm: float, axis: str | None) -> None:
    numbers = request_numbers(text)
    assert len(numbers) == 1
    assert numbers[0].value_mm == pytest.approx(value_mm)
    assert numbers[0].axis == axis


def test_numbers_without_a_length_unit_are_not_dimension_claims() -> None:
    assert request_numbers("drill 2 holes at 45 degrees, part 101") == ()
