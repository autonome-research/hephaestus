"""G2V clause: the requirement ledger and its lint rules (``VALIDATION.md`` §2).

The gate clause reads: *"ledger CRUD + generations + lint rules (unsourced
constant, unquoted ``specified``)"*.

The ledger is the substrate the rest of the ladder stands on, so this module
drives it the way an agent does — through the real dispatcher, one tool call at
a time — and asserts the two properties later rungs rely on:

* **an immutable generation per write.** ``record_requirements`` and
  ``update_requirement`` each freeze a project artifact; an earlier generation is
  still readable, unchanged, after a later one lands. §5 quotes the ledger back
  to an independent reviewer, so a mutable-in-place ledger would let a run edit
  its own interpretation after the fact.
* **the citation rules bite on the recorded evidence.** Both lint rules are run
  over the verbatim ``bracket-101`` seed-2 script and the verbatim corpus
  request: the s2 ``CHECKS`` envelope cites nothing (``unsourced_constant``), and
  a ``specified`` entry whose quote is not in the request is a fabricated
  citation (``unsourced_requirement``).

The rules' own edge cases live in ``core/tests/test_lint_ledger.py`` and the
ledger's storage semantics in ``server/tests/test_requirements_ledger.py``; this
module is the gate evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import entry_views, ledger_state
from hephaestus.bench.harness import load_tasks
from hephaestus.core.lint import lint_requirements, lint_script
from hephaestus.testing.tools_fixture import Project, make_project

FIXTURES = Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures"

#: A ledger for the recorded s2 run: what it read, and what it made up.
LEDGER: list[dict[str, Any]] = [
    {
        "id": "R1",
        "text": "base plate 60 mm in X by 40 mm in Y",
        "source": "specified",
        "quote": "60 mm (X) by 40 mm (Y) base plate",
        "value": 40.0,
        "unit": "mm",
        "applies_to": "bracket",
    },
    {
        "id": "R2",
        "text": "the wall is 6 mm thick",
        "source": "derived",
        "from": ["R1"],
        "value": 6.0,
        "unit": "mm",
        "applies_to": "bracket",
    },
    {
        "id": "R9",
        "text": "the wall stands outside the stated footprint",
        "source": "assumed",
        "rationale": "the request does not say which side of the stated Y the wall is on",
        "material": True,
        "applies_to": "bracket",
    },
]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    # seed_ledger=False: this module's subject IS the ledger/gate, so it must see
    # the project's real initial state — no ledger at all (VALIDATION.md §2).
    p = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(scope="module")
def request_text() -> str:
    return load_tasks(["bracket-101"], specs=("prose",))[0].prompt


@pytest.fixture(scope="module")
def s2_script() -> str:
    return (FIXTURES / "bracket_101_s2_bracket.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# CRUD + generations


def test_the_ledger_round_trips_through_the_tool_surface(project: Project) -> None:
    recorded = cast("dict[str, Any]", project.call("record_requirements", {"entries": LEDGER}))
    read_back = cast("dict[str, Any]", project.call("read_requirements", {}))
    patched = cast(
        "dict[str, Any]",
        project.call("update_requirement", {"id": "R9", "value": 46.0, "unit": "mm"}),
    )

    assert recorded["status"] == "ok"
    assert [e["id"] for e in cast("list[Any]", recorded["entries"])] == ["R1", "R2", "R9"]
    # The tool result shape is one projection shared by all three tools.
    assert set(read_back) == set(recorded) == set(patched)
    assert read_back["artifact_ref"] == recorded["artifact_ref"]
    # Reading never writes; patching writes exactly once.
    assert (recorded["generation"], read_back["generation"], patched["generation"]) == (1, 1, 2)

    # The §3 gate reads this field, so it is part of the ledger's contract. A
    # model-facing patch cannot clear it — `resolution` is the runtime's to write
    # (see test_g2v_clarification_gate.py) — so R9 stays open across the patch.
    assert recorded["unresolved_material"] == ["R9"]
    assert patched["unresolved_material"] == ["R9"]
    entries = {e["id"]: e for e in cast("list[dict[str, Any]]", patched["entries"])}
    assert (entries["R9"]["value"], entries["R9"]["unit"]) == (46.0, "mm")
    assert entries["R9"]["source"] == "assumed"  # a patch never rewrites provenance
    assert entries["R1"]["quote"] == LEDGER[0]["quote"]
    assert entries["R2"]["from"] == ["R1"]  # the JSON key is "from", the field is from_ids


def test_every_write_freezes_a_generation_that_later_writes_cannot_touch(
    project: Project,
) -> None:
    """§5 quotes the ledger back at the run; the run may not edit its own past."""
    first = cast("dict[str, Any]", project.call("record_requirements", {"entries": LEDGER}))
    ref = str(first["artifact_ref"])
    assert ref.startswith("artifact:requirements:sha256:")

    project.call("update_requirement", {"id": "R1", "value": 46.0, "text": "46 mm in Y"})
    second = cast("dict[str, Any]", project.call("read_requirements", {}))
    assert second["artifact_ref"] != ref
    assert second["generation"] == first["generation"] + 1

    historical = project.cad.ledger_generation(ref)
    assert historical.generation == 1
    assert historical.by_id["R1"].value == 40.0
    assert historical.artifact_ref == ref
    # …and the live state really did move.
    assert ledger_state(project.cad).by_id["R1"].value == 46.0


# --------------------------------------------------------------------------
# the two lint rules, on the recorded evidence


def _codes(source: str, *, ledger_ids: list[str] | None) -> list[str]:
    findings = lint_script(source, hc_names=("bracket_len",), ledger_ids=ledger_ids)
    return [finding.code for finding in findings]


def test_an_uncited_checks_threshold_is_unsourced(s2_script: str) -> None:
    """The s2 envelope's 46.1 traces to nothing; that is the whole misreading."""
    ids = [str(entry["id"]) for entry in LEDGER]
    reported = _codes(s2_script, ledger_ids=ids)
    assert "unsourced_constant" in reported

    # A citation of a real ledger id silences it …
    cited = s2_script.replace(
        '"envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1),',
        '"envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1),  # R1',
    ).replace(
        '"sealed": lambda m: m.sealed("part"),',
        '"sealed": lambda m: m.sealed("part"),  # R2',
    )
    assert cited != s2_script
    assert "unsourced_constant" not in _codes(cited, ledger_ids=ids)

    # … and an id the ledger does not hold is not a citation at all.
    assert "unsourced_constant" in _codes(cited, ledger_ids=["Q7"])
    # With no ledger in hand the rule is off rather than guessing.
    assert "unsourced_constant" not in _codes(s2_script, ledger_ids=None)


def test_a_specified_entry_must_quote_the_request(project: Project, request_text: str) -> None:
    """A fabricated citation is an assumption wearing a specification's badge."""
    project.call("record_requirements", {"entries": LEDGER})
    entries = entry_views(ledger_state(project.cad).entries)
    assert lint_requirements(entries, request_text) == ()

    project.call("update_requirement", {"id": "R1", "quote": "46 mm (Y) base plate"})
    findings = lint_requirements(entry_views(ledger_state(project.cad).entries), request_text)
    assert [(f.code, f.severity, f.name) for f in findings] == [
        ("unsourced_requirement", "error", "R1")
    ]
    # Only `specified` entries are quote-checked: the assumption is honest about
    # being one, and the derived entry cites its parents instead.
    assert all(finding.name == "R1" for finding in findings)
