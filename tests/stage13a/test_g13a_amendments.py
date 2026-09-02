# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13A clauses 14 and 17: amendment drift, the pins, and the geom boundary.

Clause 14 is the clause that keeps a *passing* gate from leaving a normative
document contradicting the machinery the same sub-stage shipped. It asserts a
STATE, not an edit, so it passes whether the amendment landed with this
sub-stage or one step earlier — which it did, on 2026-08-30, with the
``mission_plan.md`` Stage 13 block.

Clause 17 asserts the seam the tenth geom service sits on: ``solve`` is a pure
geom service under the standing contract, and — the part that is easy to lose —
it is deliberately absent from the package's eager re-export, because
``SOLVER.md`` §7.1 requires the verification process's import closure to
exclude it and that process imports :mod:`hephaestus.geom`.

Nothing here reads evidence a bare checkout does not have: every assertion is
over files in the repository or over the declaration in memory.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from hephaestus.contract import tools_decl

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# ==========================================================================
# clause 14: the amendments, asserted as landed text


def test_tool_schema_carries_solve_pose_and_no_unscoped_no_solver_sentence() -> None:
    """The pair-assertion: a heading for the tool, and no sentence denying it.

    A normative tool document that carried a ``solve_pose`` signature block and
    the un-scoped sentence "There is no solver." would contradict itself for
    the whole duration of a passing G13A, and doc drift a gate does not catch
    is the failure ``KINEMATICS.md:25-29`` names.
    """
    md = _read("tool_schema.md")
    assert re.search(r"^solve_pose\(", md, re.MULTILINE), "no solve_pose signature block"
    assert "### solve_pose" in md
    # The scoped form is what replaced it, and it is still a refusal.
    assert "No solver moves geometry." in md
    # The old sentence survives EXACTLY ONCE, and only as the dated record of
    # what was replaced - the ``ASSEMBLY.md`` §1 pattern. A gate that banned the
    # string outright would forbid the amendment note itself, which is the one
    # place a reader can see what the reversal spent.
    assert md.count("There is no solver.") == 1
    quoted = md.index("There is no solver.")
    note = md.index("The sentence this replaced")
    assert 0 < quoted - note < 200, "the surviving sentence is not inside the amendment note"
    # And the note does not claim a state the surface contradicts.
    assert "No Stage 13 tool exists in this document yet" not in md


def test_every_declared_tool_still_has_a_normative_heading_with_a_signature() -> None:
    """The ``test_g2_contract_drift`` shape, re-run here at the sub-stage that ships.

    Re-run rather than delegated, because a heading gate that only lives in
    another suite is a gate this sub-stage does not own.
    """
    md = _read("tool_schema.md")
    for name in tools_decl.tool_names():
        assert re.search(rf"^{re.escape(name)}\(", md, re.MULTILINE), name


def test_assembly_and_kinematics_carry_the_scoped_rules() -> None:
    """The two rule sentences: scoped, not deleted, and still refusing writeback."""
    assembly = " ".join(_read("ASSEMBLY.md").split())
    assert "NO SOLVER MOVES GEOMETRY" in assembly
    # The first two sentences stay normative VERBATIM - the reversal is scoped,
    # and what it did not buy is exactly as binding as before. Whitespace is
    # normalised first because the source is hard-wrapped and a gate that broke
    # on a re-wrap would be pinning the wrapping, not the rule.
    assert "Scripts position geometry; constraints verify, they never move anything." in assembly
    assert "A constraint that requires motion to satisfy is simply unsatisfied." in assembly
    assert "SOLVER.md" in assembly and "never a verdict" in assembly

    kinematics = " ".join(_read("KINEMATICS.md").split())
    assert "A solver that MOVES authored geometry" in kinematics
    assert "SOLVER.md" in kinematics
    assert "nothing in Stage 9 moves what a script authored" in kinematics


def test_the_cli_reference_does_not_deny_a_verb_it_documents() -> None:
    """Clause 14: ``docs/cli.md``'s ``heph joints`` section, scoped at 13A.

    Landed with this sub-stage rather than earlier, and deliberately: unlike
    the three rule sentences it names a CLI SURFACE, and scoping it before the
    verb existed would have described machinery that did not — the drift
    ``KINEMATICS.md:25-29`` actually names. A CLI reference that denies a verb
    it documents is the ``tool_schema.md`` defect in a different file.
    """
    md = _read("docs/cli.md")
    assert "### `heph solve pose`" in md
    joints = md[md.index("### `heph joints`") : md.index("### `heph motion`")]
    assert "no solver" in joints
    assert "no solver **in\nthis surface**" in joints or "no solver **in this surface**" in joints
    assert "SOLVER.md" in joints
    # And the verb the section now points at really exists in the parser.
    from hephaestus.core.cli import build_parser

    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]  # pyright: ignore[reportPrivateUsage]
    assert actions and "solve" in getattr(actions[0], "choices", {})


def test_the_mission_plan_carries_the_writeback_refusal_in_its_own_words() -> None:
    """Clause 14: asserted as text present IN the plan, never as a citation.

    The operator directed on 2026-08-29 that the refusal live in the plan's own
    text. A gate that accepted a pointer would let the plan say nothing, so
    this reads the plan's sentences rather than its references.
    """
    plan = _read("mission_plan.md")
    stage = plan[plan.index("## Stage 13") :]
    assert "THE SOLVER PROPOSES." in stage
    assert "Nothing applies a proposal." in stage
    assert "WRITEBACK IS REFUSED." in stage
    normalised = " ".join(stage.split())
    assert "authoring act" in normalised
    assert "measurement artifact" in normalised
    # The refusal in the plan's own words: no inverse from a transform to a
    # script expression is computed, offered or guessed.
    assert "computes, offers or guesses an inverse" in normalised
    assert "sole authority on position" in normalised


#: The absolute clause 17 used to claim, superseded on 2026-09-01. It survives
#: in ``mission_plan.md`` only as the dated record of what was replaced — the
#: ``ASSEMBLY.md`` §1 / ``tool_schema.md`` pattern — so what is asserted is not
#: its absence but its QUOTATION: a quoted sentence is a record, an unquoted one
#: is a claim, and only the claim was ever false. The range dash is spelled as
#: an escape because the prose uses U+2013 and a literal one here trips RUF001 —
#: the byte that must match the document is the same either way.
SUPERSEDED_ABSOLUTE = "`tests/stage9a`\u2013`stage9c` unchanged"


def test_the_plans_own_g13a_summary_carries_clause_seventeens_delta() -> None:
    """Clause 14: the plan's gate summaries, not only its writeback refusal.

    This is the clause closing on itself. Clause 17's tightening landed in
    ``SOLVER.md`` and in the plan's own closure record, while the plan's G13A
    gate summary — hundreds of lines earlier, and the block a verifier is told to read
    — still restated the superseded absolute verbatim. It was false against
    the tree (13C's corpus family moved stage9c's pin, clause 54), so a
    *passing* G13A coexisted with a normative document contradicting the
    machinery this stage shipped, which is the exact sentence clause 14 ends
    on. It survived because clause 14 asserted only the writeback refusal in
    ``mission_plan.md`` and nothing asserted the plan's gate summaries.

    So both halves are asserted here: the summary states the delta, and the
    absolute appears nowhere in the plan except in quotation marks.
    """
    plan = _read("mission_plan.md")
    stage = plan[plan.index("## Stage 13") :]
    summary = stage[stage.index("**Gate G13A**") : stage.index("- **13B")]
    normalised = " ".join(summary.split())

    # The delta, in the plan's own words, matching `SOLVER.md` clause 17.
    assert "`tests/stage9a` and `tests/stage9b` untouched" in normalised
    assert "`tests/stage9c`" in normalised
    assert "23 → 25" in normalised
    assert "corpus-count pin" in normalised

    # And the absolute is a record, never a claim — every occurrence quoted.
    body = " ".join(plan.split())
    occurrences = [m.start() for m in re.finditer(re.escape(SUPERSEDED_ABSOLUTE), body)]
    assert occurrences, (
        "the superseded absolute vanished from mission_plan.md entirely - "
        "the dated record of what the reversal replaced is what makes the "
        "tightening legible, and deleting it is not the same as scoping it"
    )
    for start in occurrences:
        end = start + len(SUPERSEDED_ABSOLUTE)
        assert body[start - 1] == '"' and body[end] == '"', (
            "mission_plan.md restates the superseded absolute as a live claim: "
            f"{body[start - 60 : end + 20]!r}"
        )


def test_the_tool_count_pins_moved_with_the_sub_stage_that_adds_the_tool() -> None:
    """Clause 14: the pins track the declaration, and ``solve_pose`` is in it.

    ``assert len(...) == N`` on an existing suite fails the moment a tool
    lands, so the pin moves with the sub-stage that adds it or "existing suites
    stay green" catches it late and painfully (``SOLVER.md`` §11). 13A moved it
    54 -> 55; 13B moved it 55 -> 57 (``propose_placement``, ``read_proposals``)
    and its own clause 40 asserts that literal.

    So the ABSOLUTE number is pinned where it belongs — in the two suites this
    clause names — and what 13A asserts here is the invariant that outlives
    every sub-stage: both pins agree with the declaration, and ``solve_pose``
    is in it with its generated schema on disk. Restating a literal 55 here
    would have made this clause a second, competing pin that goes stale the
    moment the next sub-stage lands, which is the failure the clause is about.
    """
    declared = len(tools_decl.tool_names())
    assert "solve_pose" in tools_decl.tool_names()
    assert f"assert len(TOOL_NAMES) == {declared}" in _read(
        "tests/stage2/test_g2_contract_drift.py"
    )
    toolgen = _read("contract/tests/test_toolgen.py")
    assert f"assert len(tools_decl.tool_names()) == {declared}" in toolgen
    # And the generated artifact really exists on disk, not just in memory.
    assert (ROOT / "schemas" / "tools" / "solve_pose.schema.json").is_file()


#: One row of ``SOLVER.md``'s anchor register: ``- `file:line` — "anchor"``.
#: The register is NORMATIVE TEXT, not a list curated in this file. That is the
#: 2026-09-01 tightening: the clause used to claim an anchor check over *every*
#: citation, which no parser can perform (a line number carries no expectation),
#: while the machinery checked a list two test files kept privately. Parsing the
#: register instead gives the clause exactly one source of truth, and the
#: register-agreement test below makes a row that lands in the spec and nowhere
#: else a red gate.
_REGISTER_ROW = re.compile(
    r'^- `([A-Za-z0-9_./-]+\.(?:md|py|json|toml):\d+(?:-\d+)?)` — "([^"]+)"$',
    re.MULTILINE,
)
_CITATION = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|json|toml)):(\d+)(?:-(\d+))?`")


def _resolve(name: str) -> Path:
    """The cited file, allowing the manifest's short forms (``cli.md``)."""
    candidate = ROOT / name
    if candidate.is_file():
        return candidate
    for prefix in ("core/src/hephaestus/", "core/src/hephaestus/core/", "docs/", "schemas/tools/"):
        if (ROOT / prefix / name).is_file():
            return ROOT / prefix / name
    raise AssertionError(f"{name} does not exist")


def _register() -> tuple[tuple[str, str], ...]:
    return tuple(_REGISTER_ROW.findall(_read("SOLVER.md")))


#: Read once, at collection time, so the parametrisation IS the register.
CITED_ANCHORS: tuple[tuple[str, str], ...] = _register()


def test_the_anchor_register_is_the_document_s_own_and_is_not_thin() -> None:
    """Clause 14: the asserted list is held equal to the register itself.

    Without this, "every citation in the register resolves" would be satisfiable
    by an empty register, and the tightening would have bought a weaker clause
    than the one it replaced. Two things are asserted: the register is not thin,
    and every row of it is a citation the document actually MAKES somewhere
    outside the register — a registered anchor for a citation nothing cites
    would be maintenance with no clause behind it.
    """
    spec = _read("SOLVER.md")
    assert len(CITED_ANCHORS) >= 27, (
        f"the anchor register parsed as {len(CITED_ANCHORS)} rows - "
        "either it was thinned or the row syntax drifted"
    )
    assert len({citation for citation, _anchor in CITED_ANCHORS}) == len(CITED_ANCHORS)
    body = _REGISTER_ROW.sub("", spec)
    for citation, _anchor in CITED_ANCHORS:
        assert f"`{citation}`" in body, (
            f"{citation} is registered for an anchor but is cited nowhere in SOLVER.md"
        )


def test_every_solver_md_line_citation_resolves(tmp_path: Path) -> None:
    """Clause 14: the Amendment manifest's citation audit, run as a gate.

    ``SOLVER.md`` was drafted before Stages 11 and 12 landed and roughly thirty
    of its line citations had drifted by up to 550 lines; two of them were
    load-bearing rather than cosmetic. Documents drift under other stages, so a
    spec that cites them by line has to be re-measured, not trusted.

    This is the RANGE half, which stays universal: every cited range resolves
    inside the file it names. The ANCHOR half is the register, next.
    """
    del tmp_path
    spec = _read("SOLVER.md")
    checked = 0
    for match in _CITATION.finditer(spec):
        name, start, end = match.group(1), int(match.group(2)), match.group(3)
        candidate = _resolve(name)
        lines = candidate.read_text(encoding="utf-8").splitlines()
        last = int(end) if end else start
        assert 1 <= start <= last <= len(lines), (
            f"{match.group(0)} points past {name}'s {len(lines)} lines"
        )
        checked += 1
    assert checked >= 100, f"only {checked} citations found - the audit stopped seeing them"


@pytest.mark.parametrize(("citation", "anchor"), CITED_ANCHORS)
def test_the_registered_citations_point_at_their_anchors(citation: str, anchor: str) -> None:
    """Clause 14, the ANCHOR half — at 13A, not two sub-stages later.

    A citation whose range still resolves but whose text has slid is worse than
    one that points past the end of a file: it fails silently, and a reader
    following it lands on a sentence that says something else. Four of these
    were wrong that way before this stage touched anything, which a
    range-resolves check cannot catch and this can.
    """
    name, _colon, span = citation.partition(":")
    start, _dash, end = span.partition("-")
    lines = _resolve(name).read_text(encoding="utf-8").splitlines()
    body = " ".join(" ".join(lines[int(start) - 1 : int(end or start)]).split())
    assert anchor in body, f"{citation} no longer contains {anchor!r}: {body[:120]!r}"


# ==========================================================================
# clause 17: what Stage 13 did and did not touch under `tests/stage9*`


#: The strings by which a Stage 13 edit identifies itself. Every amendment this
#: stage makes to another suite carries its citation and its date — that is
#: clause 54's own rule for the count pins ("a count silently edited from 23 to
#: 25 is indistinguishable from a count that drifted"), used here in reverse: an
#: edit that named this stage nowhere would be the drift, and an edit that names
#: it is findable.
STAGE_THIRTEEN_MARKS = (
    "SOLVER",
    "Stage 13",
    "G13",
    "2026-08-30",
    "2026-09-01",
    "solve_pose",
    "propose_placement",
    "read_proposals",
)


def _marked_lines(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [n for n, line in enumerate(lines, 1) if any(m in line for m in STAGE_THIRTEEN_MARKS)]


@pytest.mark.parametrize("suite", ["tests/stage9a", "tests/stage9b"])
def test_stage_thirteen_left_the_first_two_stage_nine_suites_untouched(suite: str) -> None:
    """Clause 17's first delta, asserted rather than asserted-about.

    The clause used to say "``tests/stage9a``-``stage9c`` unchanged", which was
    both false and asserted by nothing — 13C's corpus family had to move
    stage9c's count pin. It was tightened on 2026-09-01 to the delta, and this
    is the delta's larger half: Stage 13 named itself in **no** file under
    either of these two suites, so nothing here was rewritten to fit the solver.

    "Unchanged" is not directly assertable from a checkout — a bare tree has no
    prior version to diff against, and a gate that shelled out to ``git diff``
    would read evidence CI's checkout cannot have (the Stage 11 clause-12(b)
    defect). What IS assertable, and is what the sentence was protecting, is
    that this stage left no mark: every Stage 13 amendment to another suite
    carries its own citation, so a suite that mentions this stage nowhere is a
    suite this stage did not amend.
    """
    marked = {
        path.name: _marked_lines(path)
        for path in sorted((ROOT / suite).rglob("*.py"))
        if _marked_lines(path)
    }
    assert not marked, f"{suite} carries a Stage 13 edit: {marked}"


def test_the_only_stage_thirteen_edit_under_stage9c_is_the_repointed_corpus_pin() -> None:
    """Clause 17's second delta: one file, one contiguous edit, and the right number.

    Three conjuncts, because "only the pin" is three claims. Exactly one file
    under ``tests/stage9c`` names this stage; every line of it that does lies in
    a single short contiguous block; and that block is the corpus-count pin —
    which is held to the **public corpus on disk** rather than to a literal, so
    the number cannot be repointed here without the tasks that justify it.

    The last conjunct is what keeps the tightening honest. Clause 54 moved this
    pin 23 -> 25 because 13C adds two public tasks; if a later stage moved it
    again without adding tasks, this clause fails, and the reason the pin exists
    stays legible from the sub-stage that first had to touch it.
    """
    suite = ROOT / "tests" / "stage9c"
    marked = {path: _marked_lines(path) for path in sorted(suite.rglob("*.py"))}
    touched = {path.name: lines for path, lines in marked.items() if lines}
    assert set(touched) == {"test_corpus_mechanisms.py"}, (
        f"Stage 13 touched more of tests/stage9c than clause 17's delta admits: {touched}"
    )

    path = suite / "test_corpus_mechanisms.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = touched["test_corpus_mechanisms.py"]
    assert hits[-1] - hits[0] < 20, (
        f"the Stage 13 marks in {path.name} are scattered over lines {hits}, not a single edit"
    )
    block = "\n".join(lines[hits[0] - 1 : hits[-1]])
    assert "corpus v6" in block and "G13C clause" in block, block

    tasks = ROOT / "corpus" / "tasks"
    public = sum(1 for entry in tasks.iterdir() if (entry / "task.json").is_file())
    assert f"assert len(prose) == {public}" in "\n".join(lines), (
        f"the repointed pin does not equal the {public} public tasks in corpus/tasks"
    )
    assert f"assert len(seeded) == {public}" in "\n".join(lines)


# ==========================================================================
# clause 17: the geom boundary admits `solve` as a PURE service


def test_solve_is_a_pure_geom_service_by_its_imports() -> None:
    """Clause 17: no executor, no store, no project, no contract, no server.

    The same allowlist ``core/tests/test_geom_import_boundary.py`` enforces for
    the other nine, asserted here over the new module so this sub-stage owns
    the admission rather than inheriting it.
    """
    source = (ROOT / "core/src/hephaestus/geom/solve.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "hephaestus.core.executor",
        "hephaestus.core.project_store",
        "hephaestus.core.checks",
        "hephaestus.core.placement",
        "hephaestus.contract",
        "hephaestus.agent_bridge",
        "opstore",
        "numpy",
        "scipy",
        "random",
    )
    for name in imported:
        for prefix in forbidden:
            assert not name.startswith(prefix), f"{name} is not allowed in geom.solve"
    # ``SOLVER.md`` §4.2/§9: no RNG and no BLAS anywhere in the ITERATION -
    # asserted on the imports, not on the prose, because the module explains at
    # length why it does not delegate to numpy and a text search would trip
    # over its own reasoning.
    assert not any(name in {"random", "numpy", "scipy"} for name in imported)


def test_the_package_does_not_re_export_the_solver() -> None:
    """Clause 17 / §7.1: the omission IS the guarantee.

    ``hephaestus.geom``'s ``__init__`` re-exports nine services and not the
    tenth. If it re-exported ``solve``, the verification process — which
    imports ``hephaestus.geom`` — would pull the solver into its own import
    closure through the package, and §7's independence claim would be false
    while every other test still passed.
    """
    import hephaestus.geom as geom

    assert "solve_least_squares" not in geom.__all__
    assert not hasattr(geom, "solve_least_squares")
    init = (ROOT / "core/src/hephaestus/geom/__init__.py").read_text(encoding="utf-8")
    assert "from hephaestus.geom.solve import" not in init
    # The reason is written down where a future editor will see it.
    assert "import closure" in init.lower()


def test_the_module_contracts_the_reversal_did_not_buy_are_unamended() -> None:
    """The four "no solver" module contracts are NOT weakened (``SOLVER.md`` §0)."""
    constraints = _read("core/src/hephaestus/geom/constraints.py")
    assert "**NO SOLVER**" in constraints
    assert "Nothing here moves geometry." in constraints
    kinematics = _read("core/src/hephaestus/geom/kinematics.py")
    assert "Posed evaluation, not a solver" in kinematics
    assembly = _read("core/src/hephaestus/core/assembly.py")
    assert "**No solver, no verdict.**" in assembly
    motion = " ".join(_read("core/src/hephaestus/core/motion.py").split())
    assert "**No solver, no verdict.** Nothing here moves authored geometry" in motion
    # And the new modules RESTATE them rather than quietly dropping the claim.
    for path in ("core/src/hephaestus/geom/solve.py", "core/src/hephaestus/core/placement.py"):
        text = _read(path)
        assert "NO SOLVER MOVES GEOMETRY" in text or "writes nothing" in text
        assert "not weakened" in text or "unamended" in text


@pytest.mark.parametrize(
    "name", ["anchor_center", "motion_resolution", "check_motion", "check_motion_with_results"]
)
def test_stage_nine_engine_surface_is_intact(name: str) -> None:
    """Clause 17: Stage 9's engine surface still exports what its gates use.

    13A ADDED to ``core.motion`` and removed nothing: ``anchor_center`` (so the
    solver and its verification pass agree on what "where the anchor is" means)
    plus two methods on ``MotionResolution``. This pins the direction a
    refactor is most likely to break — a rename that quietly moved Stage 9's
    entry points would leave that stage's gates asserting against a surface
    nobody has.
    """
    from hephaestus.core import motion

    assert hasattr(motion, name), name


@pytest.mark.parametrize("name", ["transforms_at", "chain_joints", "transforms", "frame"])
def test_the_solver_rides_one_implementation_of_forward_placement(name: str) -> None:
    """Mission rule 6: ``transforms_at`` is a METHOD beside ``transforms``.

    Stage 9 already answers "where does each part sit at this DECLARED pose";
    ``SOLVER.md`` §2A needs the same answer for an assignment nobody has
    declared yet, and the honest way to get it is another method on the same
    resolution — sharing the coupling derivation, the limit checks and the
    chain walk — rather than a second forward-kinematics driver that could
    disagree with the first.
    """
    from hephaestus.core.motion import MotionResolution

    assert hasattr(MotionResolution, name), name
