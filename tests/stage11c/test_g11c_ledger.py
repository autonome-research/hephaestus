"""G11C clauses 3-4: the citable path, end to end, and the component citation.

Clause 3 walks ``PARTS_STORE.md`` §7.4's three steps with nothing mocked: the
operator registers a document the way ``heph reference add`` does, the model
records a ``specified`` requirement citing ``{reference, page, quote}``, ``heph
lint`` passes it, and a ``CHECKS`` threshold naming that ledger id satisfies
``unsourced_constant``. §7.4 opens by saying this path "already exists end to
end and this spec adds no mechanism to it" — so the clause's real job is to
prove that sentence rather than to test new code, and a suite that only
exercised the new fields would have left it unproven.

Clause 4 is the one new join (Named new work item 27): ``cite`` gains
``component`` and ``claim``, both-or-neither, each resolved against the
project's pinned registries, on the *existing* refusal path — ``invalid_requirement``
with nothing written. The last assertion is the compatibility one: a citation
carrying neither field is accepted and checked exactly as before, which is what
keeps every stored ledger generation from before this stage readable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from _g11c import (
    CLAIM_ID,
    DATASHEET_NAME,
    DATASHEET_QUOTE,
    PART_ID,
    component_tree,
    make_project,
    register_reference,
)
from hephaestus.agent_bridge.cad_ops._base import CadOpError
from hephaestus.core.lint import lint_requirements, lint_script

#: A part script whose one threshold is the datasheet's holding torque, named
#: after the ledger entry that sources it (the check-name citation form
#: ``_unsourced_constant_findings`` accepts).
SCRIPT_WITH_CITED_THRESHOLD = """PARAMS = {}
body = Box(20.0, 20.0, 5.0)
part.geometry = body
part.description = "a stand"
part.process = "cnc_mill"

CHECKS = {
    "torque_headroom_R1": lambda m: 0.44 > 0.2,
}
"""


def _project(tmp_path: Path, **kwargs: Any) -> Any:
    tree = component_tree(tmp_path / "registry")
    return make_project(tmp_path / "project", registries={"fixture-parts": tree}, **kwargs)


def _cite(**overrides: Any) -> dict[str, Any]:
    cite: dict[str, Any] = {
        "reference": DATASHEET_NAME,
        "page": 1,
        "quote": DATASHEET_QUOTE,
    }
    cite.update(overrides)
    return {key: value for key, value in cite.items() if value is not None}


def _entry(cite: dict[str, Any], entry_id: str = "R1") -> dict[str, Any]:
    return {
        "id": entry_id,
        "text": "the motor's holding torque is 0.44 N*m",
        "source": "specified",
        "cite": cite,
    }


# ==========================================================================
# clause 3 — the ledger path, end to end


def test_the_whole_citable_path_holds_with_nothing_mocked(tmp_path: Path) -> None:
    """§7.4 steps 1-3, in order, each step's output feeding the next.

    Written as ONE test on purpose: the clause is "end to end", and three
    independent tests of three steps would pass even if the steps did not
    compose — which is exactly the failure mode "the citable path already
    exists" has to rule out.
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)

    # 1. the operator registers their own copy (operator-side, content-addressed)
    entry = register_reference(project, DATASHEET_BYTES)
    assert entry.kind == "document"
    assert entry.pages == 1

    # 2. the model records a `specified` requirement citing it
    state = project.cad.record_requirements([_entry(_cite())], op_id=project.op_id())
    (recorded,) = state.entries
    assert recorded.cite is not None
    assert recorded.cite.reference == DATASHEET_NAME

    # 3a. `heph lint` passes it: the quote really is in the stored extracted text
    pages = {entry.name: project.references().pages(entry)}
    assert lint_requirements([recorded.to_json()], "", references=pages) == ()

    # 3b. …and a CHECKS threshold naming that ledger id satisfies unsourced_constant
    findings = lint_script(SCRIPT_WITH_CITED_THRESHOLD, ledger_ids=[recorded.id])
    assert [f.code for f in findings if f.code == "unsourced_constant"] == []


def test_the_same_threshold_is_unsourced_without_the_citation(tmp_path: Path) -> None:
    """The control for step 3b: the check name is what carries the citation.

    Without it the identical script reports the identical literal. A clause that
    only asserted the passing half would pass against a rule that never fires.
    """
    findings = lint_script(SCRIPT_WITH_CITED_THRESHOLD, ledger_ids=[])
    assert [f.code for f in findings if f.code == "unsourced_constant"]


def test_a_page_past_the_end_is_invalid_requirement_with_nothing_written(
    tmp_path: Path,
) -> None:
    """``VALIDATION.md:126-129``, re-asserted on the path §7.4 routes through.

    "Nothing written" is the half worth testing: a refusal that still advanced a
    generation would leave the ledger carrying a fabricated citation, and the
    next reader could not tell.
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)
    register_reference(project, DATASHEET_BYTES)
    before = project.cad.ledger_state()
    with pytest.raises(CadOpError) as caught:
        project.cad.record_requirements([_entry(_cite(page=9))], op_id=project.op_id())
    assert caught.value.reason == "invalid_requirement"
    assert "past the end" in caught.value.message
    after = project.cad.ledger_state()
    assert (after.generation, after.entries) == (before.generation, before.entries)


# ==========================================================================
# clause 4 — the component-claim citation


def test_a_component_claim_citation_round_trips(tmp_path: Path) -> None:
    """§7.4: the two fields survive ``record_requirements`` / ``read_requirements``.

    Read back from a *fresh* :meth:`ledger_state`, so the assertion is about
    what was stored rather than about the object the write returned — the
    citation is only a join if it is still there on the next read.
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)
    register_reference(project, DATASHEET_BYTES)
    project.cad.record_requirements(
        [_entry(_cite(component=PART_ID, claim=CLAIM_ID))], op_id=project.op_id()
    )
    (stored,) = project.cad.ledger_state().entries
    assert stored.cite is not None
    assert (stored.cite.component, stored.cite.claim) == (PART_ID, CLAIM_ID)
    assert stored.cite.names_component_claim
    document = cast("dict[str, Any]", stored.to_json())
    assert cast("dict[str, Any]", document["cite"])["component"] == PART_ID
    assert cast("dict[str, Any]", document["cite"])["claim"] == CLAIM_ID


@pytest.mark.parametrize(
    ("supplied", "missing"),
    [({"component": PART_ID}, "claim"), ({"claim": CLAIM_ID}, "component")],
)
def test_half_a_join_is_incomplete_component_cite(
    supplied: dict[str, Any], missing: str, tmp_path: Path
) -> None:
    """Both present or both absent, and the refusal names the missing half.

    A component with no claim id does not say which number was transcribed; a
    claim id with no component does not say whose. Silently ignoring the field
    that was supplied is how a decorative field starts.
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)
    register_reference(project, DATASHEET_BYTES)
    with pytest.raises(CadOpError) as caught:
        project.cad.record_requirements([_entry(_cite(**supplied))], op_id=project.op_id())
    assert caught.value.reason == "incomplete_component_cite"
    assert missing in caught.value.message
    assert project.cad.ledger_state().generation == 0


def test_an_unknown_component_id_is_invalid_requirement_with_nothing_written(
    tmp_path: Path,
) -> None:
    """A citation of a component the project's registries do not carry.

    Refused on the *existing* path (``invalid_requirement``, nothing written)
    for the same reason ``INGEST.md`` §2 refuses an unknown reference: it is not
    a weaker provenance record, it is a fabricated one.
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)
    register_reference(project, DATASHEET_BYTES)
    with pytest.raises(CadOpError) as caught:
        project.cad.record_requirements(
            [_entry(_cite(component="no_such_component", claim=CLAIM_ID))],
            op_id=project.op_id(),
        )
    assert caught.value.reason == "invalid_requirement"
    assert "no_such_component" in caught.value.message
    assert project.cad.ledger_state().generation == 0


def test_an_unknown_claim_id_is_invalid_requirement_with_nothing_written(
    tmp_path: Path,
) -> None:
    """The other half: the component resolves, the claim does not.

    §6.1 makes ``claims[].id`` unique within a record precisely so this refusal
    is unambiguous — "resolves to exactly one claim or the ledger op refuses".
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)
    register_reference(project, DATASHEET_BYTES)
    with pytest.raises(CadOpError) as caught:
        project.cad.record_requirements(
            [_entry(_cite(component=PART_ID, claim="no_such_claim"))], op_id=project.op_id()
        )
    assert caught.value.reason == "invalid_requirement"
    assert "no_such_claim" in caught.value.message
    assert "declares no claim" in caught.value.message
    assert project.cad.ledger_state().generation == 0


def test_a_citation_carrying_neither_field_is_accepted_and_checked_as_before(
    tmp_path: Path,
) -> None:
    """The compatibility clause, and the reason ``to_json`` omits absent fields.

    Every ledger generation written before this stage carries a three-field
    cite. It must still validate, still round-trip, and still be checked by
    ``INGEST.md`` §2's reference rule and by nothing else — a stored document
    that grew two ``null`` keys would be a silent schema migration of immutable
    content-addressed state.
    """
    from _g11c import DATASHEET_BYTES

    project = _project(tmp_path)
    register_reference(project, DATASHEET_BYTES)
    project.cad.record_requirements([_entry(_cite())], op_id=project.op_id())
    (stored,) = project.cad.ledger_state().entries
    assert stored.cite is not None
    assert (stored.cite.component, stored.cite.claim) == (None, None)
    assert not stored.cite.names_component_claim
    document = cast("dict[str, Any]", cast("dict[str, Any]", stored.to_json())["cite"])
    assert set(document) == {"reference", "page", "quote"}
    # …and the INGEST.md §2 check still decides it exactly as it did before.
    pages = {DATASHEET_NAME: project.references().pages(project.references().get(DATASHEET_NAME))}
    assert lint_requirements([stored.to_json()], "", references=pages) == ()


def test_the_component_half_is_checked_after_the_reference_half(tmp_path: Path) -> None:
    """Order matters in the report, not only in the code.

    A cite whose reference does not resolve has nothing for the component half
    to be a citation *of*; naming the component problem first would send the
    author to fix the second thing that is wrong.
    """
    project = _project(tmp_path)  # no reference registered at all
    with pytest.raises(CadOpError) as caught:
        project.cad.record_requirements(
            [_entry(_cite(component="no_such_component", claim="no_such_claim"))],
            op_id=project.op_id(),
        )
    assert "not registered" in caught.value.message
    assert "no_such_component" not in caught.value.message
