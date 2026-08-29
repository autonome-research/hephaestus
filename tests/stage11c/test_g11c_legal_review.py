"""G11C clause 15: the ``LEGAL-REVIEW.md`` schema check exists and has teeth.

``mission_plan.md:646`` says "CI checks the file's schema". Before this stage
that sentence described nothing: ``scripts/docs_check.py`` carried
``LEGAL-REVIEW.md`` in ``FORWARD_REFERENCES`` as a Stage 7 deliverable that
deliberately does not exist, and a grep for ``LEGAL-REVIEW`` across ``*.py`` and
``*.yml`` returned that one line and nothing else. An unnamed or misnamed
mechanism is a claim of existence, so ``PARTS_STORE.md`` §7.5 made the checker
**named new work** (item 33): it ships with Stage 11 rather than waiting on
Stage 7, and Stage 7 inherits a checker instead of owing one.

**Asserted against fixtures, not against the repository root** — the clause says
so explicitly, and the reason is in §7.5: ``LEGAL-REVIEW.md`` is a Stage 7
deliverable that deliberately does not exist here. A check that read the root
would either be vacuous (pass because there is nothing to read) or would fail
every development build for a file that "blocks only publication, not
development". So this clause pins the *checker*; Stage 7's own gate pins the
signed file.

**The fifth field, and where it actually lives.** §7.5's tightening adds
*third-party component data provenance and terms* to the scope, and states
plainly that the 2026-08-29 amendment **did not edit G7's gate text** — an
amendment opening one stage does not rewrite another stage's gate. The
requirement lives in the ``mission_plan.md`` Stage 11 block and in §7.5 until
whoever next amends G7 folds it in, and the checker validates it now so the gate
and the checker do not disagree in G7's favour.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import legal_review_check

REPO: Path = Path(__file__).resolve().parents[2]

#: A complete review document: the two identity fields and all four scope
#: statements, the fourth being §7.5's tightening.
COMPLETE = """# Legal review

- reviewer: A. Reviewer (not the author of the content reviewed)
- date: 2026-09-01

## Scope

- scope.tos_analysis: the reference product's ToS permits the described use.
- scope.reference_fixture_publication: the private fixtures may be published.
- scope.trademark_scan: no identifier names a vendor product.
- scope.third_party_component_data: DIN 912, ISO 15, ISO 53 and NEMA ICS 16
  nominal dimensions only; no vendor payload is vendored; every datasheet
  pointer's terms permit reference-by-citation.
"""


def _without(key: str) -> str:
    """``COMPLETE`` with one field's line removed, and nothing else changed."""
    return "\n".join(
        line
        for line in COMPLETE.splitlines()
        if not line.lstrip("- ").startswith(f"{key}:")
        and not line.lstrip("- ").startswith(f"scope.{key}:")
    )


def test_a_fixture_carrying_every_field_passes(tmp_path: Path) -> None:
    path = tmp_path / "LEGAL-REVIEW.md"
    path.write_text(COMPLETE, encoding="utf-8")
    assert legal_review_check.check_file(path) == []


def test_the_fifth_scope_field_is_required_and_named_when_missing(tmp_path: Path) -> None:
    """§7.5's tightening, which is the whole reason this checker ships now.

    A reader who greps G7 for this field will not find it — the amendment
    deliberately did not rewrite another stage's gate text — so the refusal has
    to say where the requirement comes from, or the author has nowhere to look.
    """
    path = tmp_path / "LEGAL-REVIEW.md"
    path.write_text(_without("third_party_component_data"), encoding="utf-8")
    problems = legal_review_check.check_file(path)
    assert len(problems) == 1
    assert "third_party_component_data" in problems[0]
    assert "third-party component data provenance and terms" in problems[0]
    assert "PARTS_STORE.md §7.5" in problems[0]


@pytest.mark.parametrize(
    "key", ["reviewer", "date", "tos_analysis", "reference_fixture_publication", "trademark_scan"]
)
def test_any_one_of_the_original_fields_missing_is_refused_and_named(
    key: str, tmp_path: Path
) -> None:
    """Every field G7's checklist sentence names, one at a time.

    Parametrised rather than tested as a batch: a checker that reported only the
    first missing field would pass a batch test and still leave an author fixing
    one problem per CI run.
    """
    path = tmp_path / "LEGAL-REVIEW.md"
    path.write_text(_without(key), encoding="utf-8")
    problems = legal_review_check.check_file(path)
    assert len(problems) == 1
    assert f"'{key}'" in problems[0]
    assert "mission_plan.md:643-645" in problems[0]


def test_every_missing_field_is_reported_not_just_the_first(tmp_path: Path) -> None:
    path = tmp_path / "LEGAL-REVIEW.md"
    path.write_text("# Legal review\n\nnothing has been filled in yet.\n", encoding="utf-8")
    problems = legal_review_check.check_file(path)
    assert len(problems) == len(legal_review_check.REQUIRED_FIELDS)


def test_a_present_but_blank_field_counts_as_missing(tmp_path: Path) -> None:
    """The unsigned checklist this check exists to catch.

    A heading that says ``reviewer:`` with nothing after it is not a review; it
    is a template. Accepting it would make the check a spell-checker for field
    names.
    """
    path = tmp_path / "LEGAL-REVIEW.md"
    blank = COMPLETE.replace("A. Reviewer (not the author of the content reviewed)", "")
    path.write_text(blank, encoding="utf-8")
    problems = legal_review_check.check_file(path)
    assert len(problems) == 1
    assert "'reviewer'" in problems[0]


def test_a_field_named_only_inside_a_fenced_block_does_not_count(tmp_path: Path) -> None:
    """A template quoted in the document is not the document being filled in."""
    fenced = "# Legal review\n\n```\n- reviewer: <name>\n- date: <date>\n```\n"
    problems = legal_review_check.check_file(tmp_path / "LEGAL-REVIEW.md")
    assert problems == [f"{tmp_path / 'LEGAL-REVIEW.md'}: no such file"]
    (tmp_path / "LEGAL-REVIEW.md").write_text(fenced, encoding="utf-8")
    assert len(legal_review_check.check_file(tmp_path / "LEGAL-REVIEW.md")) == len(
        legal_review_check.REQUIRED_FIELDS
    )


def test_the_scope_prefix_is_optional(tmp_path: Path) -> None:
    """Tolerant about layout, strict about content: the reviewer writes prose."""
    path = tmp_path / "LEGAL-REVIEW.md"
    path.write_text(COMPLETE.replace("scope.", ""), encoding="utf-8")
    assert legal_review_check.check_file(path) == []


# ==========================================================================
# the clause's own boundary: fixtures, never the repository root


def test_the_repository_seam_passes_while_the_file_deliberately_does_not_exist() -> None:
    """§7.5, verified: ``ls LEGAL-REVIEW.md`` at the root is still "no such file".

    ``check_repository`` is the CI seam, and its absence behaviour is the whole
    reason it is separate from ``check_file``. The review "blocks only
    publication, not development" (``mission_plan.md:448-449``), so failing
    every development build on the file's absence would convert a publication
    gate into a development gate.
    """
    assert not (REPO / "LEGAL-REVIEW.md").exists(), (
        "LEGAL-REVIEW.md now exists — this clause pins the CHECKER against "
        "fixtures; Stage 7's gate pins the signed file, and it should now be "
        "checking it"
    )
    assert legal_review_check.check_repository(REPO) == []


def test_the_seam_bites_the_moment_the_file_appears(tmp_path: Path) -> None:
    """ "Ships now, checks when Stage 7 lands it" — with no further edit.

    A seam that only passed because nothing ever reached it would be the same
    empty claim ``mission_plan.md:646`` made before this stage. Pointed at a
    root that DOES carry an incomplete file, it must refuse.
    """
    (tmp_path / "LEGAL-REVIEW.md").write_text(_without("trademark_scan"), encoding="utf-8")
    problems = legal_review_check.check_repository(tmp_path)
    assert len(problems) == 1
    assert "trademark_scan" in problems[0]


def test_docs_check_runs_the_schema_check(tmp_path: Path) -> None:
    """The CI join, so "CI checks the file's schema" is true of a real command.

    ``scripts/docs_check.py`` is what G7H's lane runs for the docs claim; the
    schema check is joined to it rather than shipped as an orphan module, so the
    sentence becomes true on the run that already makes the docs claim true.
    """
    source = (REPO / "scripts" / "docs_check.py").read_text(encoding="utf-8")
    assert "legal_review_check.check_repository" in source
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "docs_check.py")],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr


def test_the_checker_runs_as_its_own_command() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "legal_review_check.py")],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0
    assert "not present" in result.stdout


def test_the_required_field_set_is_closed_and_states_where_each_came_from() -> None:
    """A vocabulary this stage adds to is a vocabulary it must state (mission rule).

    Six fields: two identity, four scope. Each carries the document that
    requires it, which is what lets the refusal name a gate rather than a
    filename — and what makes the count discrepancy §7.5 leaves behind
    (its prose says "four scope fields" while G7's own parenthetical enumerates
    five items) a decision recorded in one place rather than an accident.
    """
    keys = [field.key for field in legal_review_check.REQUIRED_FIELDS]
    assert keys == [
        "reviewer",
        "date",
        "tos_analysis",
        "reference_fixture_publication",
        "trademark_scan",
        "third_party_component_data",
    ]
    assert all(field.origin for field in legal_review_check.REQUIRED_FIELDS)
    assert legal_review_check.SCOPE_FIELDS[-1].origin.startswith("PARTS_STORE.md §7.5")
