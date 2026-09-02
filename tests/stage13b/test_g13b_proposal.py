# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13B clauses 32-36 and 42: the proposal discipline, which is this gate's point.

A proposal is a **measurement artifact**. Nothing applies it, it is never a
verdict, it clears nothing, it carries no source text, and it is never an input
to a build. Each of those is asserted here, and the ones that can be made
structural are asserted structurally rather than by triggering a refusal —
because a refusal nobody can trigger is not a safeguard, and a schema that
cannot express the field is.

The last test in this file is the other half of the discipline and the one the
whole design is for: an operator takes a proposal and **applies it through the
ordinary authoring path**, and the constraint that was violated measures
satisfied afterwards. The diff is a one-line change to a part script. That is
what "the authoring act stays with the author" buys, and a stage that refused
writeback without demonstrating the route would have refused a capability
rather than relocated one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from _g13b import build_part, placement_request
from hephaestus.core.placement import InvalidSolveRequest, propose_placement
from hephaestus.core.project_store.constraints import ConstraintProvenance
from hephaestus.core.project_store.proposals import (
    PROPOSAL_DOCUMENT_SCHEMA,
    ProposalError,
    ProposalSet,
    proposal_views,
    validate_document,
)

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

TOL = 1e-4
SEATED = ("c-seat", "c-bore", "c-face", "c-square")

#: Every key a source-text smuggler would use. Asserted absent from the schema
#: and from every produced document, at every depth.
FORBIDDEN_FIELDS = (
    "suggested_edit",
    "suggestion",
    "source",
    "script",
    "patch",
    "diff",
    "edit",
    "new_str",
    "expression",
)


def _current_ref(layout: ProjectLayout, store: OpStore) -> Callable[[str], str | None]:
    from hephaestus.core.project_store.publication import Publisher

    publisher = Publisher(layout, store)

    def current(part: str) -> str | None:
        result = publisher.current_result(part)
        return None if result is None else result.artifact_ref

    return current


# ==========================================================================
# clause 32: the proposal is not a verdict


def test_a_converged_proposal_leaves_the_violated_row_saying_violated(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 32: ``check_assembly`` is unchanged by a proposal against it.

    ``c-seat`` is violated as built — the lug is 30 mm in the air. A solve
    converges on a placement that would satisfy it, records the proposal, and
    the assembly status still reports ``violated`` for the same constraint with
    the same residual. That is P5 (``SOLVER.md`` §1.2) holding: the verdict
    vocabulary means something because a verdict is stamped from measuring
    DELIVERED geometry, and a proposal is a fact about a hypothetical one.
    """
    from hephaestus.core.assembly import AssemblyEvaluator

    layout, store = bench_copy
    evaluator = AssemblyEvaluator(layout, store)
    before = evaluator.evaluate(["c-seat"])
    row_before = next(row for row in before.constraints if row.id == "c-seat")
    assert row_before.state == "violated", row_before

    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert record.verdict == "converged_at_tolerance", record.detail
    assert record.proposal_id

    after = AssemblyEvaluator(layout, store).evaluate(["c-seat"])
    row_after = next(row for row in after.constraints if row.id == "c-seat")
    assert row_after.state == "violated"
    assert row_after.to_json() == row_before.to_json(), "the proposal moved an assembly row"


def test_no_tool_accepts_a_proposal_id_where_a_constraint_id_is_expected(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 32: the id is not interchangeable with a constraint id.

    Two directions. A solve targeted at a proposal id is ``unknown_constraint``
    — the proposal set and the constraint set are different vocabularies, and a
    tool that quietly accepted one for the other would let a computation stand
    in for a claim. And ``check_assembly`` refuses it the same way.
    """
    from hephaestus.core.assembly import AssemblyEvaluator

    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    proposal_id = record.proposal_id
    assert proposal_id

    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request((proposal_id,), tol=TOL))
    assert excinfo.value.reason == "unknown_constraint"

    from hephaestus.core.errors import AddressingError

    with pytest.raises(AddressingError):
        AssemblyEvaluator(layout, store).evaluate([proposal_id])


# ==========================================================================
# clause 33: the proposal clears nothing


def test_the_reviewer_still_blocks_on_a_constraint_a_proposal_would_fix(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 33: the blocking finding survives the proposal, by rule.

    ``assembly_review_findings`` lifts every ``violated`` constraint into the
    report as a blocking ``fail`` with ``harness=True`` — measured by the
    engine, never solicited from the reviewer. A converged proposal against
    that constraint changes nothing about it, and there is **no model-facing
    write** that clears it: the ``VALIDATION.md:285-296`` clearing rule adopted
    verbatim, a violated row clears by a later successful build that measures
    otherwise or by an explicit operator dismissal, and by nothing else.
    """
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.agent_bridge.review import assembly_review_findings, assembly_status

    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert record.verdict == "converged_at_tolerance"

    cad = CadOps(layout, store)
    status = assembly_status(cad)
    assert status is not None
    findings = assembly_review_findings(status)
    blocking = {finding.id for finding in findings if finding.verdict == "fail"}
    assert "c-seat" in blocking, findings
    assert all(finding.harness for finding in findings)


def test_the_reviewer_context_carries_proposals_as_labeled_non_evidence(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 42: delivered, and labeled — and no verdict accepted for one.

    The reviewer is HANDED the proposal as a fact about a computation. The
    label is a field, not a convention: ``evidence`` is ``False`` and ``kind``
    says what it is, so a reader (or a later harness) cannot mistake it for a
    measurement of delivered geometry. And the prompt says so in words, because
    the model reading it is the one that must not treat it as evidence.

    The other half is mechanical: a verdict returned for a proposal id is filed
    as unknown and counts for nothing, exactly as one returned for a dimension
    finding is. So the reviewer cannot talk a constraint closed by grading a
    proposal.
    """
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.agent_bridge.review import normalize_findings, open_proposals

    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    cad = CadOps(layout, store)
    proposals = open_proposals(cad)
    assert len(proposals) == 1
    entry = proposals[0]
    assert entry["id"] == record.proposal_id
    assert entry["evidence"] is False
    assert entry["kind"] == "placement_proposal"
    assert entry["verdict"] == "converged_at_tolerance"

    # No verdict is solicited or accepted for a proposal id.
    report = normalize_findings(
        [],
        [{"id": record.proposal_id, "verdict": "pass", "evidence": "the solver said so"}],
        cycle=1,
    )
    assert record.proposal_id in report.unknown_ids
    assert all(finding.id != record.proposal_id for finding in report.findings)


def test_the_reviewer_prompt_says_a_proposal_is_not_evidence(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 42: the label reaches the model that has to honour it."""
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.agent_bridge.review import build_review_context

    layout, store = bench_copy
    propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    context = build_review_context(CadOps(layout, store), request="review this")
    assert len(context.proposals) == 1
    prompt = context.prompt()
    assert "NOT EVIDENCE" in prompt
    assert "clears nothing" in prompt
    assert "no verdict is solicited or accepted for a proposal id" in prompt


# ==========================================================================
# clause 34: provenance is compulsory and every input is bound


def test_a_proposal_binds_every_source_ref_the_generations_and_the_toolchain(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 34: the document binds what it was computed from.

    A solve is an interpretation of intent for the same reason a constraint is
    (``ASSEMBLY.md:52-54``), so the provenance rides the same taxonomy — and
    everything the answer depends on is bound in the document: each source
    part's ``artifact_ref`` at solve time, the constraint and joint
    generations, the toolchain hash, the solver version, and the full request.
    """
    from hephaestus.core.hashing import toolchain_hash
    from hephaestus.core.project_store.publication import Publisher
    from hephaestus.geom.solve import SOLVE_VERSION

    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    document = ProposalSet(layout, store).document(record.proposal_id)

    publisher = Publisher(layout, store)
    refs = cast("dict[str, str]", document["artifact_refs"])
    assert {"base", "lug"} <= set(refs)
    for part, bound in refs.items():
        result = publisher.current_result(part)
        assert result is not None and result.artifact_ref == bound

    assert document["toolchain"] == toolchain_hash()
    assert document["solver_version"] == SOLVE_VERSION
    assert isinstance(document["constraint_generation"], int)
    assert isinstance(document["joint_generation"], int)
    assert document["provenance"] == {"assumed": True, "reason": "the gate's own solve"}
    request = cast("dict[str, Any]", document["request"])
    assert request["weighting"] == "unit_scaled_v1"
    assert request["regularization"] == "min_norm_from_start"
    assert request["ground"], "the RESOLVED ground set is echoed, not the omission"
    assert set(cast("list[str]", request["constraints"])) == set(SEATED)


def test_a_solve_with_neither_a_requirement_nor_an_assumption_is_refused(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 34's negative: ``missing_provenance``, and nothing written."""
    layout, store = bench_copy
    before = ProposalSet(layout, store).state().generation
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(
            layout,
            store,
            placement_request(SEATED, tol=TOL, provenance=ConstraintProvenance()),
        )
    assert excinfo.value.reason == "missing_provenance"
    assert ProposalSet(layout, store).state().generation == before


# ==========================================================================
# clause 35: staleness is a read-time FACT, never a refusal


def test_rebuilding_a_bound_part_makes_the_proposal_stale_and_still_readable(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 35: ``stale: true`` names the changed ref; the proposal survives.

    A proposal is immutable and its inputs are already bound, so freshness is a
    pure function of the parts' current refs — which is why §8 refuses to add a
    ``ProjectionState`` field for it: a projection would be a second,
    cache-shaped copy of a fact that can be recomputed exactly.

    Staleness is deliberately NOT a refusal. The proposal was valid when it was
    written and it stays readable; what changed is the geometry underneath it,
    and naming which part changed is what tells a reader what to re-run.
    """
    from hephaestus.core.project_store.publication import Publisher

    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    proposals = ProposalSet(layout, store)
    fresh = proposal_views(proposals.state(), _current_ref(layout, store))
    assert [view["stale"] for view in fresh] == [False]
    assert [view["changed_refs"] for view in fresh] == [[]]

    # Change the plate's GEOMETRY and republish it. A comment would not do:
    # an artifact ref is a hash of the BRep, so a build that produces identical
    # geometry produces the identical ref and nothing has moved.
    script = layout.root / "parts" / "base.py"
    script.write_text(
        script.read_text(encoding="utf-8").replace(
            "Box(60.0, 40.0, 10.0)", "Box(60.0, 40.0, 12.0)"
        ),
        encoding="utf-8",
    )
    build_part(Publisher(layout, store), layout, "base")

    stale = proposal_views(proposals.state(), _current_ref(layout, store))
    assert [view["stale"] for view in stale] == [True]
    assert stale[0]["changed_refs"] == ["base"]
    assert stale[0]["verdict"] == "converged_at_tolerance", "a stale proposal keeps its verdict"
    # And the document is still there, byte for byte.
    assert proposals.document(record.proposal_id)["verdict"] == "converged_at_tolerance"


def test_a_withdrawn_proposal_stays_readable_with_its_reason(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Generational state is honest only if every generation stays readable."""
    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    proposals = ProposalSet(layout, store)
    proposals.withdraw(record.proposal_id, "the requirement moved")
    views = proposal_views(proposals.state(), _current_ref(layout, store))
    assert len(views) == 1
    assert views[0]["withdrawn"] is True
    assert views[0]["withdrawn_reason"] == "the requirement moved"
    assert proposals.document(record.proposal_id)["space"] == "transform"
    # Withdrawn is not erased, and it is not open either.
    assert proposals.state().open == ()


# ==========================================================================
# clause 36: no writeback, asserted STRUCTURALLY


def test_the_proposal_schema_declares_no_source_text_and_cannot_grow_one() -> None:
    """Clause 36 (i) and (ii): no such field, and the shape is closed everywhere.

    There is no ``suggested_edit`` in this schema, and because every object in
    it is ``additionalProperties: false``, there cannot be one whatever an
    implementer adds. That is the whole of the writeback refusal on this side —
    a schema fact rather than a runtime name, because a refusal nobody can
    trigger is not a safeguard.
    """
    from jsonschema import Draft202012Validator

    document = dict(PROPOSAL_DOCUMENT_SCHEMA)
    Draft202012Validator.check_schema(document)
    assert document["additionalProperties"] is False

    closed = _closed_objects(document)
    assert closed >= 10, f"only {closed} closed objects — the schema stopped being closed"
    # Asserted over the schema's PROPERTY NAMES, not over its text: the
    # description says in prose that the artifact carries no source text, and a
    # substring search would trip on the sentence that promises it.
    for name in _declared_property_names(document):
        assert name not in FORBIDDEN_FIELDS, f"the schema declares {name!r}"


def test_a_document_carrying_source_text_is_refused_before_it_is_stored(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 36: the closed shape is ENFORCED, not merely declared.

    A schema nobody validates against is a comment. Every document is checked
    before it is written, so the field is unrepresentable rather than merely
    undocumented — and the check is refused rather than trimmed, because a
    store that silently dropped an unknown field would make the closed shape a
    formatting convention.
    """
    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    document = dict(ProposalSet(layout, store).document(record.proposal_id))
    validate_document(document)  # the real one round-trips
    for field in FORBIDDEN_FIELDS:
        with pytest.raises(ProposalError) as excinfo:
            validate_document({**document, field: "body = Pos(20, 20, 15) * Box(20, 20, 10)"})
        assert "closed" in excinfo.value.message


def test_no_produced_proposal_carries_source_text_at_any_depth(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 36 (i): the record really carries none — checked at every depth.

    A key search rather than a top-level one, because a closed schema is only
    as good as its nesting, and this is the assertion that would catch a hole
    in it. The transform is there as rows and as a translation plus an
    axis-angle, for a person to read; which STATEMENT expresses that intent is
    the author's decision and the record says nothing about it.
    """
    layout, store = bench_copy
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    document = ProposalSet(layout, store).document(record.proposal_id)
    for key in _all_keys(cast("Any", document)):
        assert key not in FORBIDDEN_FIELDS, f"the proposal carries a {key!r} field"
    # No value in it looks like source either.
    for value in _all_strings(cast("Any", document)):
        assert "\\n" not in value, f"a multi-line string reached the proposal: {value[:60]!r}"

    placement = cast("dict[str, Any]", cast("list[Any]", document["placements"])[0])
    part = cast("dict[str, Any]", cast("list[Any]", placement["parts"])[0])
    assert set(part) == {"part", "rows", "translation_mm", "axis", "angle_deg"}


def test_all_fifty_seven_tool_input_schemas_are_closed() -> None:
    """Clause 36 (iii): the field cannot be REQUESTED either.

    An extra key on a tool call is a JSON Schema rejection before dispatch, so
    there is no reachable request for a ``suggested_edit`` and therefore no
    named refusal for one — which is why ``no_writeback_grammar`` was removed
    from §6.3's closed set rather than listed in it.
    """
    root = Path(__file__).resolve().parents[2]
    schemas = sorted((root / "schemas" / "tools").glob("*.schema.json"))
    assert len(schemas) == 57, [path.name for path in schemas]
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["parameters"]["additionalProperties"] is False, path.name


#: The refusal names Stage 13's closed vocabulary declares that only **13C**
#: can reach: they are parameter-space names, and no transform-space or
#: pose-space request can produce one. Listed as a literal so clause 36's
#: coverage assertion is a partition rather than a hand-wave — a name that
#: quietly stopped being reachable anywhere would show up here as an
#: unexercised member rather than as nothing at all.
DEFERRED_TO_13C: frozenset[str] = frozenset(
    {
        "unknown_param",
        "unbounded_param",
        "no_free_variable_affects",
        "build_budget_exhausted",
        "unbuildable_parameter_iterate",
    }
)

#: Exercised by a G13A clause rather than a G13B one: pose space's own
#: request-time refusal, the rank straddle, and the nine 8C anchor-resolution
#: reasons the resolution tuple reuses verbatim.
EXERCISED_BY_13A: frozenset[str] = frozenset({"unknown_joint", "rank_undecidable"})


def test_a_concurrent_rebuild_underneath_a_solve_is_refused_by_name(
    bench_copy: tuple[ProjectLayout, OpStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clause 36(a): ``stale_proposal_inputs``, on the concurrent-rebuild fixture.

    A part's ``artifact_ref`` changes *between* frame extraction and the §7
    verification pass — a concurrent build republished geometry underneath the
    running solve. The run is refused **by name**, nothing is written, and no
    verdict is emitted: the iterate was computed against frames that no longer
    describe any current artifact, and re-measuring it would silently mix two
    generations, which is the one thing a proposal must never do. It is a
    resolution-time refusal rather than a run-time one for the reason
    ``unresolvable`` is: the fix is to rerun, not to read a number.

    The rebuild here is REAL — the plate's script is edited and republished
    through the ordinary publisher, so the verification child genuinely reads a
    different ref and the comparison genuinely detects it. What the test
    arranges is only the *timing*, by hanging the rebuild off the one seam the
    engine already has between extraction and verification. A monkeypatched
    ref, by contrast, would have tested the assertion rather than the race.
    """
    from hephaestus.core import placement as engine
    from hephaestus.core.project_store.publication import Publisher

    layout, store = bench_copy
    original = engine._verify  # pyright: ignore[reportPrivateUsage]
    fired: list[int] = []

    def republish_then_verify(spec: Any, *, timeout_s: float) -> Any:
        if not fired:
            fired.append(1)
            script = layout.root / "parts" / "base.py"
            script.write_text(
                script.read_text(encoding="utf-8").replace(
                    "Box(60.0, 40.0, 10.0)", "Box(60.0, 40.0, 14.0)"
                ),
                encoding="utf-8",
            )
            build_part(Publisher(layout, store), layout, "base")
        return original(spec, timeout_s=timeout_s)

    monkeypatch.setattr(engine, "_verify", republish_then_verify)
    before = ProposalSet(layout, store).state().generation
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert fired, "the fixture never republished anything"
    assert record.verdict == "unresolvable"
    assert record.reason == "stale_proposal_inputs"
    assert "base" in record.detail
    # Nothing written, and no blocks: an unresolvable solve computed nothing to
    # tier, so it claims no determinism tier either.
    assert ProposalSet(layout, store).state().generation == before
    assert record.solver_core == {} and record.verification == {}
    assert not record.proposal_id


def test_the_solve_vocabulary_is_closed_in_both_directions() -> None:
    """Clause 36 (iv): no decorative member, and no member the doc asserts but omits.

    ``no_writeback_grammar`` is not a refusal name here and must not become
    one: the guarantee is a schema fact, and re-introducing the spelling would
    put a safeguard nobody can trigger back where a structural one now stands.
    ``insufficient_solve_seeds`` is a **bench-harness** refusal (the
    ``insufficient_scan_seeds`` construction) and belongs to
    ``VALIDATION.md``'s vocabulary, never to a solve's — conflating the two
    would make either set unfalsifiable.
    """
    from hephaestus.core import placement

    families = (
        placement.SOLVE_REQUEST_REFUSALS,
        placement.SOLVE_RESOLUTION_REFUSALS,
        placement.SOLVE_RUNTIME_REFUSALS,
    )
    names = {name for family in families for name in family}
    for absent in ("no_writeback_grammar", "insufficient_solve_seeds"):
        assert absent not in names
        assert absent not in json.dumps(PROPOSAL_DOCUMENT_SCHEMA)

    # (a) the other direction: no DECORATIVE member. Every name is exercised by
    # a clause of G13A or G13B, or is one 13C alone can reach — and the
    # deferred set is a literal, so "unexercised" cannot hide as "not listed".
    from hephaestus.core.assembly import UNRESOLVABLE_REASONS

    unaccounted = names - _EXERCISED_HERE - DEFERRED_TO_13C - EXERCISED_BY_13A
    unaccounted -= set(UNRESOLVABLE_REASONS)
    assert not unaccounted, f"refusal names no clause exercises: {sorted(unaccounted)}"
    assert names >= DEFERRED_TO_13C, "a deferred name left the vocabulary"


#: The refusal names a G13B clause fires by name in this suite. Kept beside
#: the coverage assertion rather than derived from it: a set computed from the
#: tests would agree with itself by construction.
_EXERCISED_HERE: frozenset[str] = frozenset(
    {
        "no_free_variables",
        "no_ground_part",
        "free_part_is_jointed",
        "free_part_in_no_constraint",
        "undeclared_weighting",
        "undeclared_regularization",
        "not_an_objective_kind",
        "pose_bound_constraint_in_transform_space",
        "unknown_constraint",
        "withdrawn_constraint",
        "missing_provenance",
        "tolerance_below_determinism_floor",
        "stale_proposal_inputs",
        "solver_timeout",
        "iteration_ceiling",
        "non_rigid_iterate",
        "solver_residual_disagreement",
    }
)


def _declared_property_names(node: Any) -> set[str]:
    """Every property name the schema declares, at any depth."""
    out: set[str] = set()
    if isinstance(node, dict):
        body = cast("dict[str, Any]", node)
        properties = body.get("properties")
        if isinstance(properties, dict):
            out.update(cast("dict[str, Any]", properties))
        for value in body.values():
            out |= _declared_property_names(value)
    elif isinstance(node, list):
        for value in cast("list[Any]", node):
            out |= _declared_property_names(value)
    return out


def _closed_objects(node: Any) -> int:
    """How many objects in a schema declare ``additionalProperties: false``."""
    count = 0
    if isinstance(node, dict):
        body = cast("dict[str, Any]", node)
        if body.get("type") == "object" and body.get("additionalProperties") is False:
            count += 1
        for value in body.values():
            count += _closed_objects(value)
    elif isinstance(node, list):
        for value in cast("list[Any]", node):
            count += _closed_objects(value)
    return count


def _all_keys(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in cast("dict[str, Any]", node).items():
            out.append(key)
            out.extend(_all_keys(value))
    elif isinstance(node, list):
        for value in cast("list[Any]", node):
            out.extend(_all_keys(value))
    return out


def _all_strings(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for value in cast("dict[str, Any]", node).values():
            out.extend(_all_strings(value))
    elif isinstance(node, list):
        for value in cast("list[Any]", node):
            out.extend(_all_strings(value))
    return out


# ==========================================================================
# the route the refusal relocates the capability to, demonstrated end to end


def test_an_operator_applies_a_proposal_through_the_ordinary_authoring_path(
    bench_copy: tuple[ProjectLayout, OpStore],
) -> None:
    """The round trip: propose, author the edit, rebuild, and the mate holds.

    This is the clause the whole reversal is FOR. ``SOLVER.md`` §1.3's decision
    is that the solver proposes and that applying stays an authoring act
    through the existing ``edit_part`` / ``write_part`` / ``set_params``
    surface — so the diff shows up in git as a normal one, carrying the
    author's intent, and the provenance stays a function of ``input_hashes``
    (P1) with git still holding design state (P2).

    The steps below are exactly what an operator does:

    1. **propose** — the record says move the lug by (+10, +10, -30) mm with no
       rotation, and ``check_assembly`` still reports ``c-seat`` violated;
    2. **author** — a human reads the translation and decides which STATEMENT
       expresses it. Here it is the ``Pos`` that seats the lug, edited through
       ``edit_part`` under the ordinary optimistic-hash contract. Stage 13
       computed none of this: it refused to guess whether the intent belonged
       in that literal, in an ``hc`` name or in a ``Param``, and three of those
       four answers would change other parts;
    3. **rebuild** — an ordinary ``build_part``, publishing an ordinary
       artifact whose identity is a function of the script;
    4. **re-measure** — ``check_assembly`` now reports every mate satisfied,
       measured from DELIVERED geometry, which is the only way a constraint
       verdict has ever been produced in this repo.

    The diff is asserted to be two changed LINES, because "a reviewer reads that;
    nobody reads a 3x4 matrix" (P4) is the property the whole refusal protects.
    """
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
    from hephaestus.core.assembly import AssemblyEvaluator
    from hephaestus.core.project_store.store import ProjectStore
    from hephaestus.testing.ledger import seed_minimal_ledger
    from hephaestus.testing.tools_fixture import Project

    layout, store = bench_copy
    cad = CadOps(layout, store)
    seed_minimal_ledger(cad)
    project = Project(
        root=layout.root,
        layout=layout,
        store=store,
        cad=cad,
        dispatcher=ToolDispatcher(ProjectStore(layout, store), cad=cad),
        _n=[0],
    )
    orchestrator = Principal(session_id="op", profile="orchestrator", part=None)

    # 1. propose
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert record.verdict == "converged_at_tolerance", record.detail
    part = cast("dict[str, Any]", cast("list[Any]", record.placements[0]["parts"])[0])
    translation = [float(value) for value in cast("list[Any]", part["translation_mm"])]
    assert translation == pytest.approx([10.0, 10.0, -30.0], abs=1e-3)
    assert float(cast("float", part["angle_deg"])) == pytest.approx(0.0, abs=1e-3)

    before = AssemblyEvaluator(layout, store).evaluate(list(SEATED))
    assert {row.id for row in before.constraints if row.state == "violated"} >= {
        "c-seat",
        "c-bore",
    }

    # 2. author the edit - through the ordinary TOOL, on the ordinary
    #    optimistic-hash contract. A human read "+10, +10, -30" and decided
    #    which statements express it; Stage 13 computed none of that, and
    #    refused to guess whether the intent belonged in these literals, in an
    #    `hc` name or in a `Param` - three of those four answers change other
    #    parts.
    script_path = layout.root / "parts" / "lug.py"
    original = script_path.read_text(encoding="utf-8")
    for old_str, new_str in (
        ("body = Pos(10.0, 10.0, 45.0)", "body = Pos(20.0, 20.0, 15.0)"),
        ("body - Pos(10.0, 10.0, 45.0)", "body - Pos(20.0, 20.0, 15.0)"),
    ):
        snapshot = cast(
            "dict[str, Any]", project.call("read_part", {"name": "lug"}, principal=orchestrator)
        )
        applied = cast(
            "dict[str, Any]",
            project.call(
                "edit_part",
                {
                    "name": "lug",
                    "expected_hash": str(snapshot["content_hash"]),
                    "old_str": old_str,
                    "new_str": new_str,
                },
                principal=orchestrator,
            ),
        )
        assert applied["applied"] is True, applied

    # The diff a reviewer reads: two changed lines, and they are POSITION
    # statements, not a matrix. Nobody reads a 3x4; nobody can author one either.
    edited = script_path.read_text(encoding="utf-8")
    changed = [
        (a, b) for a, b in zip(original.splitlines(), edited.splitlines(), strict=True) if a != b
    ]
    assert len(changed) == 2, changed
    assert all("Pos(20.0, 20.0, 15.0)" in line for _a, line in changed)

    # 3. rebuild through the ordinary path
    built = cast(
        "dict[str, Any]", project.call("build_part", {"name": "lug"}, principal=orchestrator)
    )
    assert built["status"] == "ok", built
    assert built["current"] is True

    # 4. re-measure: the mates hold now, measured from DELIVERED geometry,
    #    which is the only way a constraint verdict has ever been produced here.
    after = AssemblyEvaluator(layout, store).evaluate(list(SEATED))
    states = {row.id: row.state for row in after.constraints}
    assert states == dict.fromkeys(SEATED, "satisfied"), states

    # And the proposal is now stale, because the geometry it was computed
    # against has moved - the honest report, not an error, and not a clearing.
    views = proposal_views(ProposalSet(layout, store).state(), _current_ref(layout, store))
    assert views[0]["stale"] is True
    assert views[0]["changed_refs"] == ["lug"]
