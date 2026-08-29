"""G11C clauses 5-7: the two lint rules the store⇄project seam needs.

Clause 5 is ``uncited_component_datum`` (item 26). ``PARTS_STORE.md`` §6.3 names
the failure it catches precisely: the model reads 0.44 out of the tool result and
writes it into a ``CHECKS`` predicate, where it now looks exactly like a number
the harness derived. That is "the 'retype the number from the tool result' path
that ``mating_features`` currently *depends* on".

Clauses 6 and 7 are ``datasheet_digest_mismatch`` (item 28), and they are a pair
that has to be read together. §7.4 records that an earlier draft proposed to
*infer* the join — select the candidate reference **by** ``sha256`` equality with
the component's ``datasheet.sha256``, then report a mismatch **if the digests
differ**. A set defined by equality contains no unequal member, so that rule
could never fire: it was **logically empty**, and no pytest could have been
written to it. The findings audit's repair was to make the join precise rather
than to drop the check, so the join is now *operator-declared* through the ledger
cite's ``component`` / ``claim`` fields — and the rule is decidable in both
directions. Clause 6 is the positive direction; clause 7 is the negative one,
"the negative clause the earlier, digest-inferred formulation could not have
had", and it is the reason this module tests silence as hard as it tests firing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _g11c import (
    CLAIM_ID,
    DATASHEET_BYTES,
    DATASHEET_NAME,
    DATASHEET_QUOTE,
    DATASHEET_SHA256,
    HOLDING_TORQUE_NM,
    OTHER_BYTES,
    PART_ID,
    component_tree,
    make_project,
    register_reference,
    sha256_of,
)
from hephaestus.core.lint import (
    ComponentClaimFacts,
    ComponentDatum,
    lint_component_citations,
    lint_script,
)

#: The retyped-datum script: the threshold IS the claim's declared value.
RETYPED = """PARAMS = {}
body = Box(20.0, 20.0, 5.0)
part.geometry = body
part.description = "a motor stand"
part.process = "cnc_mill"

CHECKS = {
    "torque_floor": lambda m: 0.44 > 0.2,
}
"""

#: The same script with the citation added — one comment, nothing else.
CITED = RETYPED.replace(
    '"torque_floor": lambda m: 0.44 > 0.2,',
    '"torque_floor": lambda m: 0.44 > 0.2,  # R1',
)

CLAIM_DATA: tuple[ComponentDatum, ...] = (
    ComponentDatum(value=HOLDING_TORQUE_NM, component=PART_ID, claim=CLAIM_ID),
    ComponentDatum(value=0.42, component=PART_ID, claim=CLAIM_ID),
    ComponentDatum(value=200.0, component=PART_ID, claim=CLAIM_ID),
)


def _codes(findings: Any) -> list[str]:
    return [finding.code for finding in findings]


# ==========================================================================
# clause 5 — uncited_component_datum


def test_a_retyped_claim_value_in_checks_is_reported() -> None:
    findings = [
        f
        for f in lint_script(RETYPED, ledger_ids=[], component_data=CLAIM_DATA)
        if f.code == "uncited_component_datum"
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warning"
    assert finding.name == "torque_floor"
    assert PART_ID in finding.message
    assert CLAIM_ID in finding.message


def test_the_finding_stops_once_the_citation_is_added() -> None:
    """The other half of the clause, and the only one that proves it is a *lint*.

    A rule that fired on every match of a vendor number would be a ban on using
    the store's own data. What §6.3 asks for is that the number be *sourced*, so
    naming the ledger entry beside it is the fix — one comment, nothing else in
    the script changes.
    """
    findings = lint_script(CITED, ledger_ids=["R1"], component_data=CLAIM_DATA)
    assert "uncited_component_datum" not in _codes(findings)


def test_naming_the_check_after_the_entry_also_counts() -> None:
    """The same two citation forms ``unsourced_constant`` already accepts.

    Reusing them rather than inventing a third is mission rule 6 applied to a
    lint: an author who has learned one citation form has learned both rules.
    """
    named = RETYPED.replace('"torque_floor"', '"torque_floor_R1"')
    findings = lint_script(named, ledger_ids=["R1"], component_data=CLAIM_DATA)
    assert "uncited_component_datum" not in _codes(findings)


def test_a_threshold_that_matches_no_claim_is_not_reported_as_one() -> None:
    """Narrower than ``unsourced_constant`` on purpose.

    An uncited 0.31 is still an uncited threshold — ``unsourced_constant`` says
    so — but it is not a retyped vendor number, and saying it was would be a
    false accusation the author cannot act on.
    """
    other = RETYPED.replace("0.44", "0.31")
    findings = lint_script(other, ledger_ids=[], component_data=CLAIM_DATA)
    assert "uncited_component_datum" not in _codes(findings)
    assert "unsourced_constant" in _codes(findings)


def test_both_rules_fire_on_the_same_literal_and_say_different_things() -> None:
    """Deliberate overlap, stated rather than tidied away.

    ``unsourced_constant`` says "this threshold has no provenance";
    ``uncited_component_datum`` says "and it is a vendor assertion you retyped,
    from this component and this claim". Collapsing them would lose the second
    sentence, which is the one that tells the author what to cite.
    """
    findings = lint_script(RETYPED, ledger_ids=[], component_data=CLAIM_DATA)
    on_line = [
        f
        for f in findings
        if f.line == RETYPED.splitlines().index('    "torque_floor": lambda m: 0.44 > 0.2,') + 1
    ]
    assert {f.code for f in on_line} == {"unsourced_constant", "uncited_component_datum"}


def test_the_rule_is_off_when_the_project_carries_no_component_data() -> None:
    """No data, no finding — the same posture the reference-text resolution takes.

    A project with no ``parts`` registry at all must not start reporting
    thresholds it has no way to attribute.
    """
    assert "uncited_component_datum" not in _codes(lint_script(RETYPED, ledger_ids=[]))


def test_a_zero_valued_claim_sample_is_not_matched() -> None:
    """A NAMED limit, so it is a decision rather than an accident.

    Every ``CHECKS`` map contains zeros. A claim sample at the origin — and the
    fixture's torque curve starts at 0 rpm — would otherwise report every one of
    them, and the rule would be noise instead of evidence. The cost is stated:
    a threshold that really is a retyped zero is not caught here.
    """
    script = RETYPED.replace("0.44 > 0.2", "m.volume('part') > 0.0")
    data = (*CLAIM_DATA, ComponentDatum(value=0.0, component=PART_ID, claim=CLAIM_ID))
    findings = lint_script(script, ledger_ids=[], component_data=data)
    assert "uncited_component_datum" not in _codes(findings)


# ==========================================================================
# clauses 6-7 — datasheet_digest_mismatch, both directions


def _facts(sha256: str | None = None) -> dict[str, ComponentClaimFacts]:
    return {
        PART_ID: ComponentClaimFacts(
            claim_ids=frozenset({CLAIM_ID}),
            datasheet_sha256=DATASHEET_SHA256 if sha256 is None else sha256,
        )
    }


def _ledger_entry(**cite: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "reference": DATASHEET_NAME,
        "page": 1,
        "quote": DATASHEET_QUOTE,
    }
    base.update(cite)
    return {"id": "R1", "text": "holding torque", "source": "specified", "cite": base}


def test_a_declared_join_on_drifted_bytes_fires_exactly_once(tmp_path: Path) -> None:
    """Clause 6, positively: same document, different bytes.

    The two digests are computed here from two real byte strings that differ by
    a revision letter, so the fixture cannot pass by asserting a constant
    against itself. The finding must name the component, the claim, the
    reference and BOTH digests — a reader has to be able to tell which of the
    two is the one they have.
    """
    drifted = sha256_of(OTHER_BYTES)
    assert drifted != DATASHEET_SHA256
    findings = lint_component_citations(
        [_ledger_entry(component=PART_ID, claim=CLAIM_ID)],
        reference_digests={DATASHEET_NAME: drifted},
        components=_facts(),
    )
    assert len(findings) == 1
    (finding,) = findings
    assert finding.code == "datasheet_digest_mismatch"
    assert finding.severity == "error"
    assert finding.name == "R1"
    for token in (PART_ID, CLAIM_ID, DATASHEET_NAME, drifted, DATASHEET_SHA256):
        assert token in finding.message


def test_re_registering_the_matching_bytes_makes_it_silent() -> None:
    """The repair, measured: the same ledger entry, the right document."""
    findings = lint_component_citations(
        [_ledger_entry(component=PART_ID, claim=CLAIM_ID)],
        reference_digests={DATASHEET_NAME: DATASHEET_SHA256},
        components=_facts(),
    )
    assert findings == ()


def test_it_is_silent_when_no_ledger_entry_names_a_component_claim() -> None:
    """**Clause 7**, the clause an inferred join could not have had.

    A project carrying a component and an unrelated registered reference whose
    sha256 differs from that component's produces NO finding. Nothing is
    inferred from the mere co-presence of a reference and a component — which is
    exactly what the digest-inferred formulation would have done, firing on
    every project carrying any unrelated drawing.
    """
    findings = lint_component_citations(
        [_ledger_entry()],  # a plain INGEST.md §2 cite: no component, no claim
        reference_digests={DATASHEET_NAME: sha256_of(OTHER_BYTES)},
        components=_facts(),
    )
    assert findings == ()


def test_it_is_silent_for_a_project_carrying_no_references_at_all() -> None:
    """Clause 7's second half: nothing registered, nothing to compare, no finding."""
    assert (
        lint_component_citations(
            [_ledger_entry(component=PART_ID, claim=CLAIM_ID)],
            reference_digests={},
            components=_facts(),
        )
        == ()
    )


def test_it_is_silent_with_an_empty_ledger() -> None:
    assert (
        lint_component_citations(
            [], reference_digests={DATASHEET_NAME: sha256_of(OTHER_BYTES)}, components=_facts()
        )
        == ()
    )


def test_clause_7_holds_against_a_real_project_with_the_datasheet_block_intact(
    tmp_path: Path,
) -> None:
    """Clause 7 end to end, including its last sentence.

    "In both cases the component's ``datasheet`` audit-trail fields are still
    present in the ``instance_store_part`` result, unchanged." Silence is not
    the component's provenance being dropped — the pointer is still an audit
    trail naming exactly which document to obtain (§7.4), it is simply not a
    verified citation, and the vocabulary does not claim it is.
    """
    from hephaestus.core.registry import PartsIndex, load_registry

    tree = component_tree(tmp_path / "registry")
    project = make_project(tmp_path / "project", registries={"fixture-parts": tree})
    # An unrelated registered reference whose bytes are NOT the datasheet's.
    entry = register_reference(project, OTHER_BYTES, name="unrelated-drawing.md")
    assert entry.sha256 != DATASHEET_SHA256
    # A ledger entry that cites it — with no component claim named.
    project.cad.record_requirements(
        [
            {
                "id": "R1",
                "text": "the plate is 60 mm square",
                "source": "specified",
                "cite": {"reference": "unrelated-drawing.md", "page": 1, "quote": "Frame size 17"},
            }
        ],
        op_id=project.op_id(),
    )
    stored = [e.to_json() for e in project.cad.ledger_state().entries]
    component = PartsIndex(load_registry(tree)).get(PART_ID).component
    assert component is not None and component.datasheet is not None
    findings = lint_component_citations(
        stored,
        reference_digests={entry.name: entry.sha256},
        components={
            PART_ID: ComponentClaimFacts(
                claim_ids=frozenset(claim.id for claim in component.claims),
                datasheet_sha256=component.datasheet.sha256,
            )
        },
    )
    assert findings == ()
    # …and the pointer is untouched: still all six §7.3 fields.
    assert set(component.datasheet.to_json()) == {
        "publisher",
        "document_title",
        "revision",
        "url",
        "sha256",
        "retrieved",
    }


def test_a_cite_naming_a_claim_the_component_does_not_declare_is_reported() -> None:
    """A lint-time backstop for a state the ledger op refuses at write time.

    Registries can be re-pinned after a ledger generation was written, so a
    citation that resolved then may not resolve now. Reported as
    ``unsourced_requirement`` — the existing token for "cites something this
    project does not carry" — rather than as a digest mismatch, because no
    digests were compared.
    """
    findings = lint_component_citations(
        [_ledger_entry(component=PART_ID, claim="retired_claim")],
        reference_digests={DATASHEET_NAME: DATASHEET_SHA256},
        components=_facts(),
    )
    assert [f.code for f in findings] == ["unsourced_requirement"]
    assert "retired_claim" in findings[0].message


def test_a_component_with_no_datasheet_cannot_be_the_right_hand_side() -> None:
    """§6.1's first closure rule, seen from the other end.

    "A non-empty ``claims`` list requires the record's ``datasheet`` block …
    without it, a ``cite`` could name a claim of a component with no datasheet
    and ``datasheet_digest_mismatch`` would have no right-hand side." The parser
    makes that state unreachable from a validly indexed record; this rule stays
    total over it anyway rather than raising.
    """
    findings = lint_component_citations(
        [_ledger_entry(component=PART_ID, claim=CLAIM_ID)],
        reference_digests={DATASHEET_NAME: DATASHEET_SHA256},
        components={PART_ID: ComponentClaimFacts(frozenset({CLAIM_ID}), None)},
    )
    assert [f.code for f in findings] == ["unsourced_requirement"]


def test_the_datasheet_bytes_this_suite_cites_really_contain_the_quote() -> None:
    """The fixture's own honesty check.

    Every clause above rests on a document whose digest this suite computes. If
    the quote were not in it, the ledger would be citing a page that does not
    say what the claim says — and the whole chain would be testing a fabricated
    provenance record.
    """
    assert DATASHEET_QUOTE in DATASHEET_BYTES.decode("utf-8")
    assert str(HOLDING_TORQUE_NM) in DATASHEET_QUOTE


@pytest.mark.parametrize("half", ["component", "claim"])
def test_half_a_join_in_a_stored_document_is_ignored_not_half_applied(half: str) -> None:
    """Defence in depth against a hand-edited state document.

    The ledger op refuses ``incomplete_component_cite`` before such an entry can
    be stored, so this state is only reachable by editing CAS content by hand.
    The rule must then decline to join rather than guess the missing half.
    """
    cite = {"component": PART_ID, "claim": CLAIM_ID}
    del cite[half]
    findings = lint_component_citations(
        [_ledger_entry(**cite)],
        reference_digests={DATASHEET_NAME: sha256_of(OTHER_BYTES)},
        components=_facts(),
    )
    assert findings == ()


# ==========================================================================
# the CLI seam: `heph lint` really feeds both rules


def test_heph_lint_resolves_the_component_facts_from_the_pinned_registries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rule nothing wires up is a rule that never fires.

    ``lint.py`` imports no registry — both rules take their right-hand side as
    injected data, which is what keeps it AST-and-JSON analysis. That makes the
    *resolution* a separate seam, and an unexercised one would leave
    ``uncited_component_datum`` unreachable through the command an author
    actually runs. Driven through ``main`` rather than through the helpers so
    the argument plumbing is exercised too.
    """
    from hephaestus.core.cli import main

    tree = component_tree(tmp_path / "registry")
    project = make_project(tmp_path / "project", registries={"fixture-parts": tree})
    register_reference(project, DATASHEET_BYTES)
    (project.root / "parts" / "stand.py").write_text(RETYPED, encoding="utf-8")
    ledger = project.root / "requirements.json"
    ledger.write_text(
        json.dumps([{"id": "R1", "text": "torque", "source": "specified", "quote": "torque"}]),
        encoding="utf-8",
    )
    request = project.root / "request.txt"
    request.write_text("the motor's torque matters\n", encoding="utf-8")

    code = main(
        [
            "lint",
            str(project.root / "parts" / "stand.py"),
            "--requirements",
            str(ledger),
            "--request",
            str(request),
            "--json",
        ]
    )
    findings = json.loads(capsys.readouterr().out)
    codes = [finding["code"] for finding in findings]
    assert "uncited_component_datum" in codes, (
        "the CLI did not resolve the pinned registry's claim values, so the rule "
        "is unreachable through the command an author runs"
    )
    # The quote really is in the request, so nothing here is an error: the new
    # rule is a WARNING, and a project retyping a vendor number does not have
    # its lint exit non-zero because of it.
    assert code == 0


def test_heph_lint_reports_a_digest_mismatch_it_can_see(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The §7.4 join through the same command, on drifted bytes.

    The reference registered here is a *different revision* of the fixture
    datasheet, so its digest is not the one the component's pointer names — and
    the ledger entry declares the join, which is what makes the comparison
    legal at all.
    """
    from hephaestus.core.cli import main

    tree = component_tree(tmp_path / "registry")
    project = make_project(tmp_path / "project", registries={"fixture-parts": tree})
    register_reference(project, OTHER_BYTES)
    (project.root / "parts" / "stand.py").write_text(CITED, encoding="utf-8")
    ledger = project.root / "requirements.json"
    ledger.write_text(
        json.dumps(
            [
                {
                    "id": "R1",
                    "text": "holding torque",
                    "source": "specified",
                    "cite": {
                        "reference": DATASHEET_NAME,
                        "page": 1,
                        "quote": DATASHEET_QUOTE,
                        "component": PART_ID,
                        "claim": CLAIM_ID,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    request = project.root / "request.txt"
    request.write_text("mount the motor\n", encoding="utf-8")

    main(
        [
            "lint",
            str(project.root / "parts" / "stand.py"),
            "--requirements",
            str(ledger),
            "--request",
            str(request),
            "--json",
        ]
    )
    findings = json.loads(capsys.readouterr().out)
    mismatch = [f for f in findings if f["code"] == "datasheet_digest_mismatch"]
    assert len(mismatch) == 1
    assert PART_ID in mismatch[0]["message"]
    # …and the citation stopped the retyped-datum rule, on the same run.
    assert "uncited_component_datum" not in [f["code"] for f in findings]
