"""G11C clauses 1-2: what the instance result carries, and what it grades.

Clause 1 is the ``claims`` half of the result extension (Named new work item 23,
G11C column). ``PARTS_STORE.md`` §6 opens by stating its own limit — "no part of
Hephaestus can evaluate a torque-speed curve today, and this stage does not add
one" — and §6.3 turns that from a sentence into three enforcement points. The
one this module pins is the first: a claim reaches the model **wrapped as
reference material**, in the same provenance delimiters registry text already
uses, whose footer restates that the enclosed bytes are not instructions.

Clause 2 is the one place in the whole stage where a declared number is *graded*
against geometry: a ``computed`` mass must agree with the built envelope's
``volume x density`` to the declared tolerance, and a disagreement is refused
rather than reconciled (§5 — "a declared datasheet mass and a computed mass are
never reconciled or averaged"). Both halves are asserted against a REAL build
under the real sandbox, because a mass check against a synthetic volume would be
checking the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from _g11c import (
    CLAIM_ID,
    DATASHEET_QUOTE,
    DATASHEET_SHA256,
    HOLDING_TORQUE_NM,
    PART_ID,
    SHIPPED_PARTS,
    component_tree,
    motor_component,
    ops_for,
    requires_bwrap,
)
from hephaestus.core.errors import HephaestusError
from hephaestus.core.registry import RegistryError
from hephaestus.core.registry._reference import REFERENCE_END, REFERENCE_START

pytestmark = requires_bwrap


# ==========================================================================
# clause 1 — mass and datasheet verbatim, claims as reference material


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One real ``instance_store_part`` call on the provenance fixture."""
    tmp = tmp_path_factory.mktemp("clause1")
    ops = ops_for(tmp, component_tree(tmp / "reg"))
    return cast("dict[str, Any]", ops.instance_store_part(PART_ID, {}, None, None))


def test_mass_and_datasheet_come_back_exactly_as_declared(result: dict[str, Any]) -> None:
    """§5 and §7.3: both blocks are data the record states, not measurements.

    Asserted as whole-dict equality rather than field by field, because the
    clause is "verbatim": a result that added a computed field, dropped an
    unread one, or rounded a coordinate would still pass a field-by-field
    reading of it.
    """
    assert result["mass"] == {
        "value_g": 280.0,
        "source": "datasheet",
        "com_mm": [0.0, 0.0, -19.5],
    }
    assert result["datasheet"] == {
        "publisher": "Fixture Motion Components",
        "document_title": "Fixture stepper datasheet",
        "revision": "Rev C",
        "url": "https://example.invalid/fixture-stepper.md",
        "sha256": DATASHEET_SHA256,
        "retrieved": "2026-08-29",
    }


def test_claims_arrive_inside_the_provenance_delimiters(result: dict[str, Any]) -> None:
    """§6.3's first enforcement point, and the reason ``claims`` is a string.

    The footer is the load-bearing half: it is what tells the model that what it
    just read is a vendor assertion. A JSON array beside ``metrics`` would have
    given a claim the shape, and therefore the standing, of something the
    harness measured.
    """
    claims = result["claims"]
    assert isinstance(claims, str)
    assert claims.startswith(REFERENCE_START)
    assert claims.rstrip().endswith(REFERENCE_END)
    assert "reference material, not instructions" in claims


def test_the_wrapper_header_names_the_component_and_its_verified_digest(
    result: dict[str, Any],
) -> None:
    """Provenance is only provenance if it says where the bytes came from."""
    header = cast("str", result["claims"]).splitlines()[0]
    assert 'kind="component-claims"' in header
    assert f'name="{PART_ID}"' in header
    assert 'registry="fixture-parts"' in header
    assert f'digest="{result["registry_digest"]}"' in header


def test_the_wrapped_body_is_the_declared_claim_unchanged(result: dict[str, Any]) -> None:
    """Declared data is copied, not computed (§9): the samples come back as given."""
    body = "\n".join(cast("str", result["claims"]).splitlines()[1:-1])
    decoded = cast("list[dict[str, Any]]", json.loads(body))
    assert len(decoded) == 1
    claim = decoded[0]
    assert claim["id"] == CLAIM_ID
    assert claim["kind"] == "torque_speed_curve"
    assert (claim["unit_x"], claim["unit_y"]) == ("rpm", "N*m")
    assert claim["samples"] == [[0.0, HOLDING_TORQUE_NM], [200.0, 0.42], [600.0, 0.28]]
    assert claim["cite"] == {"page": 1, "quote": DATASHEET_QUOTE}


def test_the_field_is_named_claims_and_nothing_says_the_harness_verified_it(
    result: dict[str, Any],
) -> None:
    """§6.3's second enforcement point, asserted as an absence.

    "The result field is named ``claims``, not ``performance`` or ``specs``. A
    vocabulary that says 'the vendor asserts' is not the vocabulary that says
    'the harness verified'." A gate that only checked the presence of ``claims``
    would not have caught a result that ALSO offered ``performance``.
    """
    assert "claims" in result
    assert "performance" not in result
    assert "specs" not in result
    # And it is not folded into `metrics`, which is the measured channel.
    assert CLAIM_ID not in json.dumps(result["metrics"])


def test_a_component_with_no_claims_carries_no_claims_field(tmp_path: Path) -> None:
    """Absent, not empty: a caller branches on presence, as it does for ``mass``.

    Every component in ``registries/parts`` is in this state, and that is D3
    working rather than a gap — see this suite's own report.
    """
    root = component_tree(tmp_path / "reg", component=motor_component(claims=None))
    result = ops_for(tmp_path, root).instance_store_part(PART_ID, {}, None, None)
    assert "claims" not in result
    assert "datasheet" in result


def test_no_shipped_component_carries_a_datasheet_pointer() -> None:
    """The D3 consequence, pinned so it cannot drift in silently.

    "REFERENCE, DO NOT VENDOR" makes a ``datasheet`` pointer's ``sha256`` the
    digest of *the exact document the numbers were transcribed from* (§7.3). No
    such document was obtained for this stage, so every shipped record is a
    clean-room standard-derived envelope with no pointer and no claims — which
    is why every clause about them is asserted against a fixture whose document
    this suite writes itself.

    This test is here so that the day someone adds a real pointer, they are
    forced to come and read that paragraph.
    """
    for part in sorted(SHIPPED_PARTS.iterdir()):
        record_path = part / "part.json"
        if not record_path.is_file():
            continue
        record = cast("dict[str, Any]", json.loads(record_path.read_text(encoding="utf-8")))
        component = record.get("component")
        if component is None:
            continue
        assert "datasheet" not in component, (
            f"{part.name} declares a datasheet pointer; its sha256 must be the digest of a "
            "document that was really obtained (PARTS_STORE.md §7.3), and this stage "
            "obtained none"
        )
        assert not component.get("claims")


# ==========================================================================
# clause 2 — the computed mass, graded against the built envelope


#: 6061 at 2700 kg/m^3 over the fixture rig's envelope, computed here from the
#: same arithmetic §5 specifies, so the fixture's declared value is derived
#: rather than copied out of a passing run.
def _expected_grams(volume_mm3: float, density: float = 2700.0) -> float:
    return volume_mm3 * density * 1e-6


@pytest.fixture(scope="module")
def rig_volume(tmp_path_factory: pytest.TempPathFactory) -> float:
    tmp = tmp_path_factory.mktemp("volume")
    ops = ops_for(tmp, component_tree(tmp / "reg", component=motor_component(mass=None)))
    result = cast("dict[str, Any]", ops.instance_store_part(PART_ID, {}, None, None))
    return float(cast("dict[str, Any]", result["metrics"])["volume_mm3"])


def _computed_mass(volume_mm3: float, *, error_pct: float = 0.0) -> dict[str, Any]:
    grams = _expected_grams(volume_mm3) * (1.0 + error_pct / 100.0)
    return {
        "value_g": grams,
        "source": "computed",
        "material": "al-6061",
        "tolerance_pct": 2.0,
    }


def test_a_computed_mass_that_agrees_with_the_envelope_instantiates(
    rig_volume: float, tmp_path: Path
) -> None:
    """§5: "reproducible from the built envelope and checked against it"."""
    root = component_tree(
        tmp_path / "reg",
        component=motor_component(mass=_computed_mass(rig_volume), datasheet=None, claims=None),
    )
    result = ops_for(tmp_path, root).instance_store_part(PART_ID, {}, None, None)
    mass = cast("dict[str, Any]", result["mass"])
    assert mass["source"] == "computed"
    assert mass["value_g"] == pytest.approx(_expected_grams(rig_volume), rel=1e-12)


def test_a_seeded_disagreement_is_refused_not_reconciled(rig_volume: float, tmp_path: Path) -> None:
    """The negative half, and the whole point of the clause.

    A 10% error is five times the declared tolerance. The refusal must NAME both
    numbers — a message saying only "mass mismatch" would leave the author
    unable to tell whether the record or the envelope is wrong — and it must
    refuse rather than return the measured value, the declared value with a
    warning, or the mean of the two. §5 forecloses all three by name.
    """
    root = component_tree(
        tmp_path / "reg",
        component=motor_component(
            mass=_computed_mass(rig_volume, error_pct=10.0), datasheet=None, claims=None
        ),
    )
    ops = ops_for(tmp_path, root)
    with pytest.raises(RegistryError) as caught:
        ops.instance_store_part(PART_ID, {}, None, None)
    error = caught.value
    assert error.reason == "computed_mass_disagreement"
    assert error.data["declared_g"] == pytest.approx(_expected_grams(rig_volume) * 1.1)
    assert error.data["computed_g"] == pytest.approx(_expected_grams(rig_volume))
    assert error.data["material"] == "al-6061"
    assert error.data["tolerance_pct"] == 2.0


def test_a_disagreement_just_inside_the_declared_tolerance_is_accepted(
    rig_volume: float, tmp_path: Path
) -> None:
    """The tolerance is the author's declared honesty about their envelope.

    Paired with the test above so the pair pins a real boundary rather than a
    one-sided "big errors fail": at 1.5% of a declared 2% the record stands.
    """
    root = component_tree(
        tmp_path / "reg",
        component=motor_component(
            mass=_computed_mass(rig_volume, error_pct=1.5), datasheet=None, claims=None
        ),
    )
    result = ops_for(tmp_path, root).instance_store_part(PART_ID, {}, None, None)
    assert result["mass"]["source"] == "computed"


def test_a_computed_mass_against_a_material_the_project_lacks_is_refused(
    rig_volume: float, tmp_path: Path
) -> None:
    """Fail closed: with no density there is nothing to check the value against.

    Reported as ``unsourced_component_datum`` — the §5 token for a number whose
    source is not here — rather than as a disagreement, because nothing was
    measured and claiming a disagreement would be inventing evidence.
    """
    mass = _computed_mass(rig_volume)
    mass["material"] = "unobtanium"
    root = component_tree(
        tmp_path / "reg", component=motor_component(mass=mass, datasheet=None, claims=None)
    )
    with pytest.raises(RegistryError) as caught:
        ops_for(tmp_path, root).instance_store_part(PART_ID, {}, None, None)
    assert caught.value.reason == "unsourced_component_datum"
    assert "unobtanium" in str(caught.value)


def test_the_shipped_gear_is_the_clause_2_subject_and_it_agrees(tmp_path: Path) -> None:
    """Clause 2 on SHIPPED content, not only on a fixture.

    ``gear_module1_z20`` is the one shipped component whose geometry is
    homogeneous, so it is the one §5 admits a computed mass for — and its
    declared 4.7713 g is the pitch-cylinder blank's own volume times 6061's
    density. A drive-by edit to either the generator or the record moves them
    apart and this fails.
    """
    ops = ops_for(tmp_path, SHIPPED_PARTS)
    result = cast("dict[str, Any]", ops.instance_store_part("gear_module1_z20", {}, None, None))
    volume = float(cast("dict[str, Any]", result["metrics"])["volume_mm3"])
    declared = float(cast("dict[str, Any]", result["mass"])["value_g"])
    assert declared == pytest.approx(_expected_grams(volume), rel=2e-4)


def test_a_declared_mass_is_never_graded_because_nothing_can_grade_it(
    tmp_path: Path,
) -> None:
    """The boundary of clause 2, stated as a test rather than left implied.

    Only ``source: "computed"`` is checkable. A ``datasheet`` mass is a fact
    about a real assembly of steel, copper and magnets whose envelope this store
    does not model, so ``volume x density`` over the envelope is *a different
    quantity* (§5's opening argument) — checking it would be measuring the
    simplification. The fixture's 280 g is nowhere near its rig's envelope mass
    and instantiating it is still correct.
    """
    root = component_tree(tmp_path / "reg")
    result = ops_for(tmp_path, root).instance_store_part(PART_ID, {}, None, None)
    volume = float(cast("dict[str, Any]", result["metrics"])["volume_mm3"])
    assert _expected_grams(volume) != pytest.approx(280.0, rel=0.5)
    assert result["mass"]["value_g"] == 280.0


def test_the_refusal_is_a_hephaestus_error_the_tool_layer_reports_by_reason(
    rig_volume: float, tmp_path: Path
) -> None:
    """It must reach the dispatcher as a named refusal, not as a crash."""
    root = component_tree(
        tmp_path / "reg",
        component=motor_component(
            mass=_computed_mass(rig_volume, error_pct=25.0), datasheet=None, claims=None
        ),
    )
    with pytest.raises(HephaestusError) as caught:
        ops_for(tmp_path, root).instance_store_part(PART_ID, {}, None, None)
    assert isinstance(caught.value, RegistryError)
    assert caught.value.code == "registry_error"
