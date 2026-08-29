# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The ``LEGAL-REVIEW.md`` schema check that ``mission_plan.md`` already claims.

``mission_plan.md:646`` says "CI checks the file's schema". It did not.
``scripts/docs_check.py`` carried ``LEGAL-REVIEW.md`` in ``FORWARD_REFERENCES``
as a Stage 7 deliverable that deliberately does not exist yet, and a grep for
``LEGAL-REVIEW`` across ``*.py`` and ``*.yml`` returned that one line and nothing
else. An unnamed or misnamed mechanism is a claim of existence
(``KINEMATICS.md``'s convention), so ``PARTS_STORE.md`` §7.5 made the checker
**named new work** (item 33) and gated it at G11C clause 15. Stage 7 inherits a
checker instead of owing one; what Stage 7 still owns is the one deliberately
human step — the review itself, and the signature on it.

**What is checked, and the count that had to be decided.** The document declares
a reviewer, a date, and one signed-off statement per scope item. G7's checklist
sentence names three scope items (ToS analysis of the reference product,
reference-fixture publication decision, trademark scan of identifiers);
``PARTS_STORE.md`` §7.5 adds the fourth — *third-party component data provenance
and terms* — as the tightening Stage 11 lands under mission rule 1. So this
checker requires **six** fields: two identity fields and four scope statements.

That is not the count the spec's own prose uses, and the discrepancy is recorded
here rather than glossed. §7.5 and the ``mission_plan.md`` Stage 11 block both
call G7's set "four scope fields" and the new total "five", while G7's own
parenthetical enumerates five items (reviewer, date, and three scope items). The
two cannot both be right. This module resolves it the only way that loses
nothing: **every field either text names is required**, and no field is dropped
to make a count come out. Whoever amends G7's sentence should fix the count with
it.

**Asserted against fixtures, never against the repository root.**
``LEGAL-REVIEW.md`` does not exist here, deliberately (§7.5), so a check that
read the root would either be vacuous or would fail the build for a file Stage 7
owes. The gate therefore pins the *checker* against fixtures; Stage 7's gate pins
the signed file. :func:`check_repository` is the CI seam and passes when the file
is absent, saying so.

Usage::

    uv run python scripts/legal_review_check.py            # the repository root
    uv run python scripts/legal_review_check.py <path>     # one file
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: The file this checker validates when it exists (a Stage 7 deliverable).
LEGAL_REVIEW_FILENAME: Final[str] = "LEGAL-REVIEW.md"


@dataclass(frozen=True)
class Field:
    """One required field: its machine key and the prose a reader will look for."""

    key: str
    label: str
    #: Which document introduced the requirement, quoted in the refusal so a
    #: reader knows which gate to argue with.
    origin: str


#: Who reviewed, and when. Named separately from the scope statements because
#: they identify the review rather than describing its coverage.
IDENTITY_FIELDS: Final[tuple[Field, ...]] = (
    Field("reviewer", "reviewer", "mission_plan.md:643-645"),
    Field("date", "date", "mission_plan.md:643-645"),
)

#: The scope statements. The first three are G7's; the fourth is
#: ``PARTS_STORE.md`` §7.5's tightening, and it is the one a reader who greps G7
#: will not find there — the requirement lives in the ``mission_plan.md``
#: Stage 11 block and in §7.5 until whoever next amends G7 folds it in.
SCOPE_FIELDS: Final[tuple[Field, ...]] = (
    Field("tos_analysis", "ToS analysis of the reference product", "mission_plan.md:643-645"),
    Field(
        "reference_fixture_publication",
        "reference-fixture publication decision",
        "mission_plan.md:643-645",
    ),
    Field("trademark_scan", "trademark scan of identifiers", "mission_plan.md:643-645"),
    Field(
        "third_party_component_data",
        "third-party component data provenance and terms",
        "PARTS_STORE.md §7.5 (mission_plan.md Stage 11 block)",
    ),
)

#: Every field the document must carry.
REQUIRED_FIELDS: Final[tuple[Field, ...]] = IDENTITY_FIELDS + SCOPE_FIELDS

#: A field line: ``- reviewer: A. Name`` / ``* scope.trademark_scan: …``. The
#: value must be non-empty, because a present-but-blank field is exactly the
#: unsigned checklist this check exists to catch.
_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[-*]?\s*(?:scope\.)?(?P<key>[a-z][a-z0-9_]*)\s*:\s*(?P<value>\S.*?)\s*$"
)


def parse_fields(text: str) -> dict[str, str]:
    """Every ``key: value`` field the document declares, first occurrence winning.

    Deliberately tolerant about layout — bullet or not, ``scope.``-prefixed or
    not — and deliberately strict about content: a key with nothing after the
    colon is not recorded, so it is reported missing rather than accepted as
    filled in. The reviewer writes prose around these lines; only the lines
    matter.
    """
    fields: dict[str, str] = {}
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _FIELD_RE.match(line)
        if match is None:
            continue
        fields.setdefault(match.group("key"), match.group("value"))
    return fields


def check_text(text: str, *, source: str) -> list[str]:
    """Every schema problem in one legal-review document, in field order.

    Returns an empty list when the document carries all six fields with
    non-empty values. Each problem names the missing field, the prose label a
    reviewer would write beside it, and where the requirement comes from — a
    refusal that only said "invalid" would send the reader back to the spec to
    work out which half of it they broke.
    """
    fields = parse_fields(text)
    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        if fields.get(field.key):
            continue
        problems.append(
            f"{source}: missing required field {field.key!r} "
            f"({field.label}) — required by {field.origin}"
        )
    return problems


def check_file(path: Path) -> list[str]:
    """Schema problems in one file (a missing file is one problem, named)."""
    if not path.is_file():
        return [f"{path}: no such file"]
    return check_text(path.read_text(encoding="utf-8"), source=str(path))


def check_repository(root: Path | None = None) -> list[str]:
    """The CI seam: check the root ``LEGAL-REVIEW.md`` **if it exists**.

    Absent is not a failure here, and that is the whole reason this function is
    separate from :func:`check_file`. ``LEGAL-REVIEW.md`` is a Stage 7
    deliverable that deliberately does not exist in this checkout (§7.5), and it
    "blocks only publication, not development". Failing every development build
    on its absence would convert a publication gate into a development gate,
    which is the opposite of what ``mission_plan.md:448-449`` says it is. When
    Stage 7 lands the signed file, this starts checking it, on the same CI run,
    with no further edit.
    """
    base = REPO_ROOT if root is None else root
    path = base / LEGAL_REVIEW_FILENAME
    if not path.is_file():
        return []
    return check_file(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="legal_review_check", description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help=f"a legal-review document to check (default: {LEGAL_REVIEW_FILENAME} at the root)",
    )
    args = parser.parse_args(argv)
    raw_path = args.path
    if raw_path is None:
        problems = check_repository()
        if not problems and not (REPO_ROOT / LEGAL_REVIEW_FILENAME).is_file():
            print(
                f"legal_review_check: {LEGAL_REVIEW_FILENAME} is not present — it is a Stage 7 "
                "deliverable and blocks publication, not development (PARTS_STORE.md §7.5)"
            )
            return 0
    else:
        problems = check_file(Path(str(raw_path)))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"\nlegal_review_check: {len(problems)} schema problem(s)", file=sys.stderr)
        return 1
    print(f"legal_review_check: all {len(REQUIRED_FIELDS)} required fields present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
