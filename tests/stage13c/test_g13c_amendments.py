# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13C: the amendments this sub-stage lands, and the audit it re-runs.

``SOLVER.md``'s Amendment manifest makes the citation audit **a precondition on
every sub-stage**, not a one-time repair: "Documents drift under other stages;
a spec that cites them by line has to be re-measured, not trusted." 13C's own
amendments moved four documents underneath it — ``SOLVER.md``, ``VALIDATION.md``,
``tool_schema.md`` and ``mission_plan.md`` — so this suite re-resolves every
line citation by range AND the load-bearing ones by anchor, exactly as 13A and
13B do.

It also asserts the text this sub-stage was supposed to land, and the text it
was supposed to make false and therefore remove. A document that still says the
enum has one member while the schema admits two is the drift
``KINEMATICS.md:25-29`` names, and a gate that only checked for added text would
never see it.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """One line of single-spaced text.

    Prose wraps; a clause that grepped a wrapped sentence would be asserting
    the line width of the paragraph it is about rather than the sentence.
    """
    return " ".join(text.split())


def _resolve(name: str) -> Path:
    candidate = ROOT / name
    if candidate.is_file():
        return candidate
    for prefix in ("core/src/hephaestus/", "core/src/hephaestus/core/", "docs/", "schemas/tools/"):
        if (ROOT / prefix / name).is_file():
            return ROOT / prefix / name
    raise AssertionError(f"{name} does not exist")


#: The citations this gate re-resolves by ANCHOR rather than only by range —
#: read out of ``SOLVER.md``'s own anchor register, never curated here. Each is
#: load-bearing (a clause somewhere greps it, or a rule's whole force depends on
#: the sentence being the one cited), and a range check cannot catch an anchor
#: that slid by a line or two. **13C's own edits moved six of these**, which is
#: the third consecutive sub-stage at which this audit has paid for itself and
#: the reason it is a per-sub-stage precondition. The register moved into the
#: normative document on 2026-09-01, under mission rule 1, so that the clause's
#: anchor half names an enumerated set instead of claiming a universal check no
#: parser can perform — and so that all three sub-stages assert the same list.
_REGISTER_ROW = re.compile(
    r'^- `([A-Za-z0-9_./-]+\.(?:md|py|json|toml):\d+(?:-\d+)?)` — "([^"]+)"$',
    re.MULTILINE,
)

CITED_ANCHORS: tuple[tuple[str, str], ...] = tuple(_REGISTER_ROW.findall(_read("SOLVER.md")))


def test_the_anchor_register_is_the_document_s_own_and_is_not_thin() -> None:
    """The register is the spec's, and an empty one would not satisfy the clause.

    "Every citation in the register resolves" is trivially true of an empty
    register, so the clause is only as strong as this: the list is parsed from
    normative text, it is not thin, it has no duplicate rows, and every row is a
    citation the document actually makes somewhere outside the register.
    """
    spec = _read("SOLVER.md")
    assert len(CITED_ANCHORS) >= 27, f"the anchor register parsed as {len(CITED_ANCHORS)} rows"
    assert len({citation for citation, _anchor in CITED_ANCHORS}) == len(CITED_ANCHORS)
    body = _REGISTER_ROW.sub("", spec)
    for citation, _anchor in CITED_ANCHORS:
        assert f"`{citation}`" in body, f"{citation} is registered but cited nowhere in SOLVER.md"


def test_every_solver_md_line_citation_still_resolves() -> None:
    """The manifest's audit, as a precondition on THIS sub-stage (range half)."""
    spec = _read("SOLVER.md")
    pattern = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|json|toml)):(\d+)(?:-(\d+))?`")
    checked = 0
    for match in pattern.finditer(spec):
        name, start, end = match.group(1), int(match.group(2)), match.group(3)
        lines = _resolve(name).read_text(encoding="utf-8").splitlines()
        last = int(end) if end else start
        assert 1 <= start <= last <= len(lines), (
            f"{match.group(0)} points past {name}'s {len(lines)} lines"
        )
        checked += 1
    assert checked >= 150, f"only {checked} citations found - the audit stopped seeing them"


@pytest.mark.parametrize(("citation", "anchor"), CITED_ANCHORS)
def test_the_load_bearing_citations_still_point_at_their_anchors(
    citation: str, anchor: str
) -> None:
    """The ANCHOR half, which the range check cannot do for you.

    A citation whose range still resolves but whose text has slid is worse than
    one that points past the end of a file: it fails silently, and a reader
    following it lands on a sentence that says something else.
    """
    name, _colon, span = citation.partition(":")
    start, _dash, end = span.partition("-")
    lines = _resolve(name).read_text(encoding="utf-8").splitlines()
    body = " ".join(" ".join(lines[int(start) - 1 : int(end or start)]).split())
    assert anchor in body, f"{citation} no longer contains {anchor!r}: {body[:120]!r}"


def test_validation_md_gained_the_corpus_split_with_this_sub_stage() -> None:
    """The manifest's ``VALIDATION.md`` §1 row, landed here and not before.

    An amendment that describes machinery which does not exist is the drift
    ``KINEMATICS.md:25-29`` names, so this row waited for the family it
    describes.
    """
    document = _flat(_read("VALIDATION.md"))
    assert "### Corpus families: `solve-*` (2026-08-30, `SOLVER.md` §11)" in document
    assert "solve_baseline.json" in document
    assert "insufficient_solve_seeds" in document
    assert "proposal_requirements" in document
    assert "graded on the **rebuilt part**, never on the proposal" in document
    # Its own split, never averaged into the historical bars.
    assert "neither compared against nor averaged into the v1/v2/v3 baselines" in document


def test_the_manifest_records_both_13c_rows_as_landed() -> None:
    """Silence in an amendment manifest is a claim, so landing is stated."""
    manifest = _read("SOLVER.md")
    assert "**LANDED 2026-08-30 with 13C**" in manifest
    assert manifest.count("**LANDED 2026-08-30 with 13C**") >= 2, (
        "both the tool_schema.md enum row and the VALIDATION.md §1 row land here"
    )


def test_the_13b_note_that_13c_made_false_is_gone() -> None:
    """A gate that only looked for ADDED text would never see this.

    ``tool_schema.md``'s amendment note said `space: "parameters"` "is
    deliberately not listed yet". That was true while it was true; the schema
    now admits the value, so the sentence had to go — replaced by the rule it
    was expressing, which is that a Stage 13 surface lands with the sub-stage
    that ships it.
    """
    document = _flat(_read("tool_schema.md"))
    assert "deliberately not listed yet" not in document
    assert "landed with 13C" in document
    assert "adding no fourth tool" in document


def test_the_spec_records_the_deviations_this_sub_stage_made() -> None:
    """Reality contradicting the spec is reported LOUDLY, in the spec itself."""
    spec = _flat(_read("SOLVER.md"))
    # The finite-difference cost, corrected in the arithmetic rather than the prose.
    assert "finite-difference gradient costs `2n` evaluations, not `1 + n`" in spec
    # The verification pass's builds are not charged to the iteration's budget.
    assert "verification pass's builds are NOT charged to this budget**" in spec
    # The sensitivity test's second conjunct.
    assert "second conjunct, added at 13C because the first alone is wrong" in spec
    # `unbounded_param`'s reachable case.
    assert "`unbounded_param` names a case that really exists" in spec
    # `budgets?` renamed to the one budget that exists.
    assert "`budgets?` was this slot's placeholder name in the draft" in spec


def test_the_plan_records_this_sub_stage_landing_in_its_own_words() -> None:
    """``mission_plan.md`` is where the operator reads what happened."""
    plan = _flat(_read("mission_plan.md"))
    assert "**13C landed 2026-08-30, with six deviations recorded rather than absorbed.**" in plan
    assert "stage gates 13A-13C" in plan
    assert "`bench.scoring.CORPUS_FAMILIES` as an **exact mapping**" in plan


def test_the_plan_still_carries_the_writeback_refusal_in_its_own_words() -> None:
    """The operator's 2026-08-29 direction, re-asserted at every sub-stage.

    A rule that exists only in the spec it constrains is a rule with one
    reader, so the plan states it in the plan. G13A clause 14 asserted it
    present; nothing here may quietly remove it, and 13C touched this file.
    """
    plan = _flat(_read("mission_plan.md"))
    assert "**WRITEBACK IS REFUSED.**" in plan
    assert "No code path in Stage 13" in plan


def test_the_ci_lane_names_the_three_suites_it_runs() -> None:
    """A lane naming a suite that does not exist is a red build, not a placeholder.

    And the converse, which is this sub-stage's half: a lane that runs a suite
    it does not name is a gate nobody can find. The ``release.yml`` prior-gate
    list moves in the same change, because ``tests/stage7h`` asserts set
    equality between the two and forgetting either half turns a green gate red.
    """
    ci = _read(".github/workflows/ci.yml")
    assert "name: stage gates 13A-13C" in ci
    assert "uv run pytest tests/stage13a tests/stage13b tests/stage13c -q" in ci
    assert "stage gates 13A-13B" not in ci
    release = _read(".github/workflows/release.yml")
    assert '"stage gates 13A-13C"' in release
    assert '"stage gates 13A-13B"' not in release


def test_the_lane_timeout_moved_for_a_stated_reason() -> None:
    """13C is the first solve suite that spends kernel time per iterate.

    A lane that times out is a red build that says nothing about the gate, and
    a timeout raised without a reason is a number a later reader cannot check.
    """
    ci = _read(".github/workflows/ci.yml")
    lane = ci[ci.index("stages13:") : ci.index("stages13:") + 900]
    assert "timeout-minutes: 75" in lane
    window = _flat(ci[max(0, ci.index("stages13:") - 1400) : ci.index("stages13:")])
    assert "every 2C candidate is a preview build" in window


def test_the_new_module_surface_restates_the_rule_it_rides_under() -> None:
    """The parameter half says, in code, what nothing applies.

    ``SOLVER.md`` §0's rule has to be readable where the machinery is, not only
    in the spec: a later editor reads the module, not the manifest.
    """
    source = _read("core/src/hephaestus/core/placement.py")
    marker = source.index("# parameter space (``SOLVER.md`` §2C)")
    banner = source[marker : marker + 1200]
    # The banner is a COMMENT block, so the leading "#" of each line has to go
    # before the prose reads as prose.
    flat = " ".join(line.lstrip().lstrip("#").strip() for line in banner.splitlines()).replace(
        "  ", " "
    )
    flat = " ".join(flat.split())
    assert "every candidate is a preview build" in flat
    assert "no override is persisted" in flat
    assert "it can only reach placements the author parameterised" in flat
    cli = _flat(_read("core/src/hephaestus/core/cli_solve.py"))
    assert "``solve params`` additionally issues **preview** builds" in cli
    assert "there is no ``--apply`` and no ``--set``" in cli


def test_the_geom_package_still_does_not_re_export_the_solver() -> None:
    """13A's D3, inherited by every later sub-stage (``SOLVER.md`` §7.1).

    The verification pass imports ``hephaestus.geom``; a package ``__init__``
    that re-exported ``solve`` would pull the solver into the very closure §7.1
    excludes, and the exclusion would be false while every other test passed.
    The omission IS the guarantee, so it is re-asserted here — 13C widened the
    verification closure (it now builds), which is exactly when an "it was fine
    before" assumption would be wrong.
    """
    import sys

    package = _read("core/src/hephaestus/geom/__init__.py")
    assert "solve" not in {
        name.strip().strip('"').strip("'")
        for name in re.findall(r'"([a-z_]+)"', package)
        if name.strip() == "solve"
    }
    for module in list(sys.modules):
        if module.startswith("hephaestus.geom"):
            del sys.modules[module]
    importlib.import_module("hephaestus.geom")

    assert "hephaestus.geom.solve" not in sys.modules
