"""VALIDATION.md §2 lint rules: unsourced CHECKS constants and quoted specs.

Both rules exist because a self-authored spec test cannot catch a misreading of
the spec — it encodes it. ``unsourced_constant`` refuses a ``CHECKS`` threshold
whose provenance is not written next to it; ``unsourced_requirement`` refuses a
ledger entry that claims to quote the request but does not. Each rule is tested
positively (it fires on the real ``bracket-101`` seed-2 misread) and negatively
(a correctly cited script/ledger is clean), because a lint that cannot stay
quiet is not a lint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.cli import main
from hephaestus.core.lint import (
    LintFinding,
    lint_part_script,
    lint_requirements,
    lint_script,
    requirement_entries,
)
from opstore.types import JSONValue

#: The shape of the recorded bracket-101 seed-2 failure: a self-authored
#: envelope check whose 46.1 encodes the misreading of a stated 40 mm.
MISREAD_SCRIPT = """from build123d import *

part.description = "L bracket"
part.process = "milled"
part.geometry = Box(60.0, 46.0, 40.0)

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1),
}
"""

CITED_SCRIPT = """from build123d import *

part.description = "L bracket"
part.process = "milled"
part.geometry = Box(60.0, 40.0, 40.0)

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (60.1, 40.1, 40.1),  # R1 R2 R3
}
"""

NAME_CITED_SCRIPT = """from build123d import *

part.description = "L bracket"
part.process = "milled"
part.geometry = Box(60.0, 40.0, 40.0)

CHECKS = {
    "y_envelope_R2": lambda m: m.bbox("part")[1] <= 40.1,
}
"""

REQUEST = (
    "The bracket is a 60 mm (X) by 40 mm (Y) base plate, 6 mm thick, lying on\n"
    "the XY plane. The wall rises so the bracket's overall height is 40 mm."
)


def _codes(findings: tuple[LintFinding, ...], code: str) -> list[LintFinding]:
    return [finding for finding in findings if finding.code == code]


# -- unsourced_constant ------------------------------------------------------


LEDGER = ("R1", "R2", "R3")


def test_the_rule_is_off_without_a_ledger() -> None:
    """No ledger at all is a §3 clarification-gate failure, not a lint finding."""
    assert _codes(lint_script(MISREAD_SCRIPT), "unsourced_constant") == []


def test_an_empty_ledger_sources_nothing() -> None:
    assert len(_codes(lint_script(MISREAD_SCRIPT, ledger_ids=[]), "unsourced_constant")) == 3


def test_uncited_checks_thresholds_are_reported() -> None:
    findings = _codes(lint_script(MISREAD_SCRIPT, ledger_ids=LEDGER), "unsourced_constant")
    assert [finding.line for finding in findings] == [8, 8, 8]
    assert all(finding.severity == "warning" for finding in findings)
    assert all(finding.name == "envelope" for finding in findings)
    # The offending value is named, so the diff between 46.1 and a stated 40 is
    # visible in the finding itself.
    assert any("46.1" in finding.message for finding in findings)


def test_a_trailing_ledger_citation_silences_the_rule() -> None:
    assert _codes(lint_script(CITED_SCRIPT, ledger_ids=LEDGER), "unsourced_constant") == []


def test_the_check_name_may_carry_the_citation() -> None:
    assert _codes(lint_script(NAME_CITED_SCRIPT, ledger_ids=LEDGER), "unsourced_constant") == []


def test_only_the_ledgers_own_ids_count_as_citations() -> None:
    """A citation names an entry that exists; an invented token is not one."""
    source = MISREAD_SCRIPT.replace("40.1),", "40.1),  # wall_dir")
    assert _codes(lint_script(source, ledger_ids=["wall_dir"]), "unsourced_constant") == []
    # The same comment against a ledger that has no such entry stays reported.
    assert _codes(lint_script(source, ledger_ids=["R1"]), "unsourced_constant")


def test_a_citation_comment_elsewhere_does_not_cover_the_literal() -> None:
    source = MISREAD_SCRIPT.replace("CHECKS = {", "# R1 R2 R3\nCHECKS = {")
    assert _codes(lint_script(source, ledger_ids=LEDGER), "unsourced_constant")


def test_non_checks_numbers_and_booleans_are_not_reported() -> None:
    """Geometry literals are not thresholds; ``True`` is not a number."""
    source = "part.geometry = Box(60.0, 40.0, 40.0)\n\nCHECKS = {\n    'ok': lambda m: True,\n}\n"
    assert _codes(lint_script(source, ledger_ids=LEDGER), "unsourced_constant") == []


def test_the_rule_survives_a_script_with_no_checks_block() -> None:
    findings = lint_script("part.geometry = Box(1.0, 2.0, 3.0)\n", ledger_ids=LEDGER)
    assert _codes(findings, "unsourced_constant") == []


def test_lint_part_script_forwards_ledger_ids() -> None:
    source = MISREAD_SCRIPT.replace("40.1),", "40.1),  # envelope_y")
    assert _codes(lint_part_script(source, ledger_ids=["envelope_y"]), "unsourced_constant") == []
    assert _codes(lint_part_script(source, ledger_ids=LEDGER), "unsourced_constant")


# -- unsourced_requirement ---------------------------------------------------


def test_a_specified_entry_must_quote_the_request() -> None:
    entries = [
        {"id": "R1", "source": "specified", "quote": "60 mm (X) by 40 mm (Y) base plate"},
        {"id": "R2", "source": "specified", "quote": "overall height is 46 mm"},
    ]
    findings = lint_requirements(entries, REQUEST)
    assert [finding.name for finding in findings] == ["R2"]
    assert findings[0].code == "unsourced_requirement"
    assert findings[0].severity == "error"
    assert "not in the request" in findings[0].message


def test_a_quote_spanning_a_line_break_still_matches() -> None:
    entries = [{"id": "R1", "source": "specified", "quote": "lying   on the XY   PLANE"}]
    assert lint_requirements(entries, REQUEST) == ()


def test_a_specified_entry_without_a_quote_is_reported() -> None:
    (finding,) = lint_requirements([{"id": "R1", "source": "specified"}], REQUEST)
    assert finding.code == "unsourced_requirement"
    assert "has no quote" in finding.message


def test_derived_and_assumed_entries_are_not_quote_checked() -> None:
    entries = [
        {"id": "R3", "source": "derived", "from": ["R1"]},
        {
            "id": "R4",
            "source": "assumed",
            "rationale": "no wall direction stated",
            "material": True,
        },
    ]
    assert lint_requirements(entries, REQUEST) == ()


def test_requirement_entries_accepts_a_list_or_a_generation_document() -> None:
    entries = [{"id": "R1", "source": "specified", "quote": "40 mm"}]
    assert requirement_entries(entries) == entries
    assert requirement_entries({"generation": 3, "entries": entries}) == entries
    assert requirement_entries({"entries": "not a list"}) == []
    assert requirement_entries(None) == []


# -- `heph lint` wiring ------------------------------------------------------


def test_heph_lint_reports_both_rules_from_a_ledger_and_a_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rules reach the CLI: ledger ids source thresholds, request sources quotes."""
    script = tmp_path / "bracket.py"
    script.write_text(MISREAD_SCRIPT, encoding="utf-8")
    ledger = tmp_path / "requirements.json"
    ledger.write_text(
        json.dumps(
            {
                "generation": 2,
                "entries": [
                    {
                        "id": "R1",
                        "source": "specified",
                        "quote": "60 mm (X) by 40 mm (Y) base plate",
                    },
                    {"id": "R2", "source": "specified", "quote": "overall height is 46 mm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    request = tmp_path / "request.txt"
    request.write_text(REQUEST, encoding="utf-8")

    exit_code = main(
        [
            "lint",
            str(script),
            "--json",
            "--requirements",
            str(ledger),
            "--request",
            str(request),
        ]
    )
    # unsourced_requirement is an error, so the command fails.
    assert exit_code == 1
    findings = [
        cast("dict[str, JSONValue]", entry)
        for entry in cast("list[JSONValue]", json.loads(capsys.readouterr().out))
    ]
    codes = [finding["code"] for finding in findings]
    assert codes.count("unsourced_constant") == 3
    assert [f["name"] for f in findings if f["code"] == "unsourced_requirement"] == ["R2"]


def test_heph_lint_without_a_ledger_leaves_the_constant_rule_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "bracket.py"
    script.write_text(MISREAD_SCRIPT, encoding="utf-8")
    assert main(["lint", str(script), "--json"]) == 0
    findings = [
        cast("dict[str, JSONValue]", entry)
        for entry in cast("list[JSONValue]", json.loads(capsys.readouterr().out))
    ]
    assert not [f for f in findings if str(f["code"]).startswith("unsourced")]


def test_heph_lint_rejects_a_missing_ledger_file(tmp_path: Path) -> None:
    script = tmp_path / "bracket.py"
    script.write_text(MISREAD_SCRIPT, encoding="utf-8")
    assert main(["lint", str(script), "--requirements", str(tmp_path / "nope.json")]) == 2
