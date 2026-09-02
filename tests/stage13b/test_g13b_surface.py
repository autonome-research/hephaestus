# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13B clauses 39-41 and 43: the surface a model and an operator actually meet.

* **clause 39** — ``propose_placement`` through the **real dispatcher**:
  refused on the part profile, dispatching on the orchestrator's;
  ``read_proposals`` on both, returning withdrawn generations with their
  reasons.
* **clause 40** — the tool-count pins repointed 55 -> 57 **with this
  sub-stage**, the five generated artifacts drift-clean, and the ``space`` enum
  admitting ``"transform"`` alone, because a schema already listing
  ``"parameters"`` would make 13C's own clause vacuous.
* **clause 41** — ``heph solve placement`` and ``heph proposals``, human and
  ``--json``, including the exit code, because a script gates on it.
* **clause 43** — the amendments this sub-stage owed, and the module contracts
  the reversal did NOT buy, asserted unamended.

The profile split is the clause worth reading. ``propose_placement`` reasons
ACROSS parts and spends a project-scoped budget, which is the rationale that
makes project-scoped ``set_params`` and ``run_checks`` orchestrator-only; a
part agent that could propose placements for parts it does not own would be
interpreting a system it cannot see. ``read_proposals`` is on both, for the
reason every 8C read tool is: generational state is honest only if every
generation stays readable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g13b import BENCH_PARTS, CONSTRAINTS, JOINTS, POSES, make_project
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import DispatchError, Principal, ToolDispatcher
from hephaestus.contract import tools_decl
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.tools_fixture import Project

ROOT = Path(__file__).resolve().parents[2]

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)
PART_LUG = Principal(session_id="p1", profile="part", part="lug")
REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)

#: The one request every dispatch clause here drives.
REQUEST: dict[str, Any] = {
    "space": "transform",
    "constraints": ["c-seat", "c-bore", "c-face", "c-square"],
    "free": ["lug"],
    "tol": 1e-4,
    "weighting": "unit_scaled_v1",
    "regularization": "min_norm_from_start",
    "provenance": {"assumed": True, "reason": "the gate's own solve"},
}


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _flat(relative: str) -> str:
    """One document with its line wrapping removed.

    The normative documents are hard-wrapped at 80 columns, so a sentence this
    gate quotes is usually split across lines. Searching the wrapped text would
    make the assertion depend on where the reflow happened to land, which is
    not the fact being asserted.
    """
    return " ".join(_read(relative).split())


@pytest.fixture(scope="module")
def wired(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    """The bench cast behind the REAL dispatcher, built through the model's own tool.

    Scaffolded here rather than reusing the engine suite's session fixture: a
    dispatch clause has to drive the parts through ``build_part`` on the tool
    surface, which is a different path from the engine-side publisher the other
    files use, and a gate assertion must not be satisfiable by a change made in
    one of them.
    """
    from hephaestus.testing.ledger import seed_minimal_ledger

    root = tmp_path_factory.mktemp("g13b-surface") / "proj"
    make_project(root, BENCH_PARTS)
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    project = Project(
        root=root,
        layout=layout,
        store=store,
        cad=cad,
        dispatcher=ToolDispatcher(ProjectStore(layout, store), cad=cad),
        _n=[0],
    )
    seed_minimal_ledger(cad)
    try:
        for name in BENCH_PARTS:
            built = cast("dict[str, Any]", project.call("build_part", {"name": name}))
            assert built["status"] == "ok", built
        for entry in JOINTS:
            project.call("declare_joint", dict(entry))
        for entry in POSES:
            project.call("declare_pose", dict(entry))
        for entry in CONSTRAINTS:
            project.call("declare_constraint", dict(entry))
        project.call(
            "update_constraint",
            {
                "id": "c-old",
                "patch": {"withdrawn": True},
                "reason": "the fixture needs a withdrawn entry to refuse on",
            },
        )
        yield project
    finally:
        project.close()


# ==========================================================================
# clause 39: profiles


def test_propose_placement_dispatches_on_the_orchestrator(wired: Project) -> None:
    """Clause 39: the tool really drives, and records a proposal, from a session."""
    result = cast("dict[str, Any]", wired.call("propose_placement", REQUEST))
    assert result["status"] == "ok"
    assert result["verdict"] == "converged_at_tolerance", result["detail"]
    assert str(result["proposal_ref"]).startswith("artifact:placement-proposal:sha256:")
    assert cast("dict[str, Any]", result["solver_core"])["determinism_tier"] == "D1"
    assert cast("dict[str, Any]", result["verification"])["determinism_tier"] == "D2"
    # The placement reaches the model as rows AND as a decomposition, and
    # nothing in it is source text.
    part = cast("dict[str, Any]", cast("list[Any]", result["placements"])[0]["parts"][0])
    assert set(part) == {"part", "rows", "translation_mm", "axis", "angle_deg"}


@pytest.mark.parametrize("principal", [PART_LUG, REVIEWER])
def test_propose_placement_is_refused_off_the_orchestrator(
    wired: Project, principal: Principal
) -> None:
    """Clause 39: the part profile is refused, and so is the reviewer's.

    A part agent may not propose placements for a system it cannot see; a
    reviewer judging evidence may not commission it.
    """
    with pytest.raises(DispatchError) as excinfo:
        wired.call("propose_placement", REQUEST, principal=principal)
    assert excinfo.value.reason == "scope_denied"


@pytest.mark.parametrize("principal", [ORCH, PART_LUG])
def test_read_proposals_dispatches_on_both_profiles_with_withdrawn_generations(
    wired: Project, principal: Principal
) -> None:
    """Clause 39: both profiles, and a withdrawn proposal comes back with its reason."""
    from hephaestus.core.project_store.proposals import ProposalSet

    recorded = cast("dict[str, Any]", wired.call("propose_placement", REQUEST))
    proposal_id = str(recorded["proposal_id"])
    proposals = ProposalSet(wired.layout, wired.store)
    # Content-addressed, so the second parametrisation of this test records the
    # SAME proposal rather than a second one - and withdrawing it twice is a
    # refusal, correctly.
    if not proposals.state().by_id[proposal_id].withdrawn:
        proposals.withdraw(proposal_id, "superseded by a rebuild")

    read = cast("dict[str, Any]", wired.call("read_proposals", {}, principal=principal))
    assert read["status"] == "ok"
    entries = {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", read["proposals"])
    }
    assert proposal_id in entries, entries
    assert entries[proposal_id]["withdrawn"] is True
    assert entries[proposal_id]["withdrawn_reason"] == "superseded by a rebuild"
    assert entries[proposal_id]["stale"] is False
    # The document itself is still readable, on request.
    full = cast(
        "dict[str, Any]",
        wired.call(
            "read_proposals",
            {"ids": [proposal_id], "include_documents": True},
            principal=principal,
        ),
    )
    document = cast("dict[str, Any]", full["documents"])[proposal_id]
    assert cast("dict[str, Any]", document)["space"] == "transform"


def test_reading_an_unrecorded_proposal_id_is_refused_by_name(wired: Project) -> None:
    """A read for an id nobody recorded is REFUSED, never filtered away.

    An empty result for a typo looks exactly like an empty result for a project
    that has no proposals, and "nothing silently skipped" is the rule this
    stage is written under. The refusal names the ids that do exist, on the
    ``addressing_error`` shape every other id-taking surface here uses.
    """
    with pytest.raises(DispatchError) as excinfo:
        wired.call("read_proposals", {"ids": ["p-000000000000"]})
    assert excinfo.value.reason == "unknown_proposal"


# ==========================================================================
# clause 40: the pins, the generated artifacts, and the 13B enum


def test_the_tool_count_pins_moved_with_this_sub_stage() -> None:
    """Clause 40: 55 -> 57, repointed HERE.

    ``assert len(...) == N`` on an existing suite fails the moment a tool
    lands, so the pin moves with the sub-stage that adds it or "existing suites
    stay green" catches it late and painfully (``SOLVER.md`` §11).
    """
    assert len(tools_decl.tool_names()) == 57
    assert {"propose_placement", "read_proposals"} <= set(tools_decl.tool_names())
    assert "assert len(TOOL_NAMES) == 57" in _read("tests/stage2/test_g2_contract_drift.py")
    assert "assert len(tools_decl.tool_names()) == 57" in _read("contract/tests/test_toolgen.py")
    for name in ("propose_placement", "read_proposals"):
        assert (ROOT / "schemas" / "tools" / f"{name}.schema.json").is_file()


def test_the_generated_artifacts_are_drift_clean() -> None:
    """Clause 40: the five generated artifacts really match the declaration.

    Each tool costs five drift-tested generated artifacts, which is why the
    surface is a design constraint at this size and why 13C's parameter space
    is an enum value rather than a fourth tool.
    """
    from hephaestus.contract import toolgen

    for relative, text in toolgen.generate_json_schemas().items():
        assert (ROOT / relative).read_text(encoding="utf-8") == text, relative
    assert (ROOT / "agent" / "src" / "tools" / "schema.gen.ts").read_text(
        encoding="utf-8"
    ) == toolgen.generate_typebox_module()
    assert (ROOT / "schemas" / "mcp" / "tools.json").read_text(
        encoding="utf-8"
    ) == toolgen.generate_mcp_document()


#: The space enum members declared AFTER Stage 13B, accounted for by name.
#: ``space: "parameters"`` is 13C's extension — the ``layout="nested_sheet"``
#: precedent, a schema amendment rather than a new tool — and it landed
#: 2026-08-30 with the machinery it names.
SPACE_ENUM_ADDED_AFTER_13B: tuple[str, ...] = ("parameters",)


def test_the_space_enum_at_13b_admits_transform_and_only_named_later_additions() -> None:
    """Clause 40: 13B declared ONE member, so 13C's extension is not vacuous.

    The clause used to be written as ``enum == ["transform"]``, which said
    something 13B never claimed: that no later sub-stage may ever extend it.
    That turned red the moment 13C landed ``parameters``, exactly as three
    absolute count pins turned red when 13A landed ``solve_pose`` — the same
    defect, the same repair. What Stage 13B's clause was actually about is
    that **13B itself declared one member**, so it now pins that plus a NAMED
    list of what was declared afterwards. An unaccounted member is still a red
    build, and 13C's clause 51 still has a fact to point at: at 13B, this enum
    did not admit ``parameters``.
    """
    schema = json.loads(
        (ROOT / "schemas" / "tools" / "propose_placement.schema.json").read_text(encoding="utf-8")
    )
    space = cast("dict[str, Any]", schema["parameters"]["properties"]["space"])
    members = cast("list[str]", space["enum"])
    assert members[0] == "transform", space
    assert tuple(members[1:]) == SPACE_ENUM_ADDED_AFTER_13B, (
        "an enum member was added without being accounted for here; 13B's own "
        "member is 'transform' and every later one has to be named"
    )


def test_every_declared_tool_still_has_a_normative_heading_with_a_signature() -> None:
    """Clause 40: the heading gate re-runs over the 13B headings.

    A normative tool document that declared a surface it does not describe is
    the doc drift ``KINEMATICS.md:25-29`` names, and it is caught at the
    sub-stage that adds the heading rather than one later.
    """
    document = _read("tool_schema.md")
    # Every declared tool has a SIGNATURE — the drift gate's own direction 2,
    # re-run here at the sub-stage that adds two of them.
    signatures = set(re.findall(r"^([a-z][a-z0-9_]+)\(", document, re.MULTILINE))
    assert set(tools_decl.tool_names()) <= signatures, set(tools_decl.tool_names()) - signatures
    # And the three Stage 13 tools additionally have their own headings, which
    # is where the "a heading lands only with the sub-stage that ships the
    # tool" rule is checkable.
    for name in ("solve_pose", "propose_placement", "read_proposals"):
        assert f"\n### {name}\n" in document, f"{name} has no normative heading"
    # The old sentence survives EXACTLY ONCE and only inside the dated
    # amendment note, as the record of what the reversal spent. Banning the
    # string outright would forbid that note, which is the one place a reader
    # can see what was replaced (the 13A pair-assertion, re-run here because
    # this sub-stage adds two headings beside it).
    assert document.count("There is no solver.") == 1
    quoted = document.index("There is no solver.")
    note = document.index("The sentence this replaced")
    assert 0 < quoted - note < 200, "the surviving sentence is not inside the amendment note"
    assert "`propose_placement` and\n`read_proposals` are absent" not in document


# ==========================================================================
# clause 41: the operator CLI


def _run_cli(argv: list[str], cwd: Path) -> int:
    """``heph`` as a script would call it, from inside the project."""
    import os

    from hephaestus.core.cli import main

    saved = Path.cwd()
    os.chdir(cwd)
    try:
        return main(argv)
    finally:
        os.chdir(saved)


def test_heph_solve_placement_human_form(
    wired: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clause 41: the human form says what was proposed and that nothing was applied."""
    code = _run_cli(
        [
            "solve",
            "placement",
            "--constraint",
            "c-seat",
            "--constraint",
            "c-bore",
            "--constraint",
            "c-face",
            "--constraint",
            "c-square",
            "--free",
            "lug",
            "--tol",
            "1e-4",
            "--weighting",
            "unit_scaled_v1",
            "--regularization",
            "min_norm_from_start",
            "--assumed",
            "--reason",
            "the gate's own solve",
        ],
        wired.root,
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "verdict: converged_at_tolerance" in out
    assert "proposal: p-" in out
    assert "lug: move (" in out and "turn" in out
    assert "nothing was applied" in out
    # The excluded kinds are reported at the solution, labeled as what they are.
    assert "(not an objective term)" in out


def test_heph_proposals_lists_what_was_recorded(
    wired: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clause 41: ``heph proposals``, human and ``--json``."""
    code = _run_cli(["proposals"], wired.root)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "generation:" in out
    assert "converged_at_tolerance" in out

    code = _run_cli(["proposals", "--json"], wired.root)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert payload["status"] == "ok"
    rows = cast("list[Any]", payload["proposals"])
    assert rows and all("stale" in cast("dict[str, Any]", row) for row in rows)


def test_heph_solve_placement_exits_non_zero_on_an_outcome_that_is_not_a_pass(
    wired: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clause 41: a script gates on the exit code, so it gates on an ANSWER.

    An under-determined answer is a fact to read, not a pass: a lone
    ``concentric`` mate leaves the axis's translation and rotation free, and
    "here is one member of a continuum" is not "this is the placement".
    """
    code = _run_cli(
        [
            "solve",
            "placement",
            "--constraint",
            "c-bore",
            "--free",
            "lug",
            "--tol",
            "1e-4",
            "--weighting",
            "unit_scaled_v1",
            "--regularization",
            "min_norm_from_start",
            "--assumed",
            "--reason",
            "one mate only",
        ],
        wired.root,
    )
    out = capsys.readouterr().out
    assert code == 1, out
    assert "verdict: underdetermined_at_tolerance" in out


def test_there_is_no_apply_verb() -> None:
    """Clause 41's negative: no flag on any solve verb applies anything.

    ``SOLVER.md`` §1.3's decision is that applying is an authoring act through
    the existing edit surface. A ``--apply`` here would move the authoring act
    from the author to the tool and the diff would stop carrying intent.
    """
    source = _read("core/src/hephaestus/core/cli_solve.py")
    for flag in ("--apply", "--write", "--accept", "--declare-pose", "--writeback"):
        assert f'"{flag}"' not in source, f"{flag} exists on a solve verb"


# ==========================================================================
# clause 43: the amendments this sub-stage owed, and what stayed unamended


def test_the_documents_this_sub_stage_scopes_carry_their_scoped_rules() -> None:
    """Clause 43: ``ASSEMBLY.md`` §4, ``KINEMATICS.md`` §7 and ``VALIDATION.md`` §5.

    Each is SCOPED, not deleted: the sentence keeps its no-writeback force and
    gains the scope the amendment bought. A rule sentence left standing false
    between the plan block and the machinery is the drift
    ``KINEMATICS.md:25-29`` names.
    """
    assembly = _flat("ASSEMBLY.md")
    assert "No placement solver **in 8C**" in assembly
    assert "nothing in Stage 13 moves what a script authored" in assembly
    assert "writeback is refused" in assembly

    kinematics = _flat("KINEMATICS.md")
    assert "No placement/assembly solver **in Stage 9**" in kinematics
    assert "in Stage 9 and in Stage 13 alike" in kinematics

    validation = _flat("VALIDATION.md")
    assert "A placement proposal (`SOLVER.md` §8) is delivered to the reviewer" in validation
    assert "never as a constraint verdict" in validation
    assert "no verdict is solicited or accepted for a proposal id" in validation
    # The never-green rule itself is UNCHANGED.
    assert (
        "A `violated` or `unresolvable` constraint at termination review is a "
        "**blocking finding by rule**" in validation
    )


def test_the_cli_reference_documents_the_verbs_it_now_has() -> None:
    """Clause 43: ``docs/cli.md`` describes the surface that exists, and no more."""
    cli = _read("docs/cli.md")
    assert "### `heph solve placement`" in cli
    assert "### `heph proposals`" in cli
    assert "no solver **in this surface**" in _flat("docs/cli.md")
    assert "nothing was applied: this is a measurement" in cli


@pytest.mark.parametrize(
    ("path", "phrase"),
    [
        ("core/src/hephaestus/geom/constraints.py", "**NO SOLVER**"),
        ("core/src/hephaestus/core/assembly.py", "**No solver, no verdict.**"),
        ("core/src/hephaestus/core/motion.py", "no solver"),
    ],
)
def test_the_module_contracts_the_reversal_did_not_buy_are_unamended(
    path: str, phrase: str
) -> None:
    """Clause 43: the four module contracts stand, and the new modules restate them.

    ``SOLVER.md`` §0: the reversal is scoped, and the scope is the whole of it.
    What it bought is proposing; the modules that say nothing here moves
    geometry keep saying it.
    """
    assert phrase.lower() in _read(path).lower()


def test_the_new_modules_restate_the_rule_they_ride_under() -> None:
    """Clause 43: the 13B machinery says, in its own text, that it applies nothing."""
    proposals = _read("core/src/hephaestus/core/project_store/proposals.py")
    assert "Writeback is refused" in _read("core/src/hephaestus/core/placement.py")
    assert "It is never a verdict" in proposals
    assert "It carries no source text" in proposals
    assert "It clears nothing" in proposals
    assert "It is never an input to a build" in proposals


# ==========================================================================
# the Amendment manifest's citation audit, re-run as THIS sub-stage's gate


#: The citations this gate re-resolves by ANCHOR rather than only by range —
#: read out of ``SOLVER.md``'s own anchor register, never curated here. Each is
#: load-bearing (a clause somewhere greps it, or a rule's whole force depends on
#: the sentence being the one cited), and a range check cannot catch an anchor
#: that slid by a line or two, which is how four of them were wrong once before.
#: The register moved into the normative document on 2026-09-01, so that the
#: three sub-stages assert the same list and neither can drift from the clause.
_REGISTER_ROW = re.compile(
    r'^- `([A-Za-z0-9_./-]+\.(?:md|py|json|toml):\d+(?:-\d+)?)` — "([^"]+)"$',
    re.MULTILINE,
)


def _resolve(name: str) -> Path:
    candidate = ROOT / name
    if candidate.is_file():
        return candidate
    for prefix in ("core/src/hephaestus/", "core/src/hephaestus/core/", "docs/", "schemas/tools/"):
        if (ROOT / prefix / name).is_file():
            return ROOT / prefix / name
    raise AssertionError(f"{name} does not exist")


CITED_ANCHORS: tuple[tuple[str, str], ...] = tuple(
    _REGISTER_ROW.findall((ROOT / "SOLVER.md").read_text(encoding="utf-8"))
)


def test_the_anchor_register_is_the_document_s_own_and_is_not_thin() -> None:
    """The register is the spec's, and an empty one would not satisfy the clause.

    13B asserts this for itself rather than trusting 13A to have asserted it:
    each sub-stage's gate is a command that runs alone.
    """
    spec = (ROOT / "SOLVER.md").read_text(encoding="utf-8")
    assert len(CITED_ANCHORS) >= 27, f"the anchor register parsed as {len(CITED_ANCHORS)} rows"
    assert len({citation for citation, _anchor in CITED_ANCHORS}) == len(CITED_ANCHORS)
    body = _REGISTER_ROW.sub("", spec)
    for citation, _anchor in CITED_ANCHORS:
        assert f"`{citation}`" in body, f"{citation} is registered but cited nowhere in SOLVER.md"


def test_every_solver_md_line_citation_still_resolves() -> None:
    """The manifest's audit, as a precondition on THIS sub-stage.

    ``SOLVER.md`` cites five documents by line, and 13B amended four of them —
    ``ASSEMBLY.md``, ``KINEMATICS.md``, ``VALIDATION.md``, ``tool_schema.md`` —
    plus ``mission_plan.md`` and ``docs/cli.md``. Documents drift under other
    stages *and under this one*; a spec that cites them by line has to be
    re-measured, not trusted. This is the RANGE half.
    """
    spec = _read("SOLVER.md")
    pattern = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|json|toml)):(\d+)(?:-(\d+))?`")
    checked = 0
    for match in pattern.finditer(spec):
        name, start, end = match.group(1), int(match.group(2)), match.group(3)
        path = _resolve(name)
        lines = path.read_text(encoding="utf-8").splitlines()
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
    following it lands on a sentence that says something else. 13B's own
    insertions moved four of these by up to 54 lines, which is why the audit
    is a per-sub-stage precondition rather than a one-time repair.
    """
    name, _colon, span = citation.partition(":")
    start, _dash, end = span.partition("-")
    lines = _resolve(name).read_text(encoding="utf-8").splitlines()
    body = " ".join(" ".join(lines[int(start) - 1 : int(end or start)]).split())
    assert anchor in body, f"{citation} no longer contains {anchor!r}: {body[:120]!r}"
