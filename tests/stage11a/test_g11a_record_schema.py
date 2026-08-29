"""G11A clauses 4-7 and 10-14: the component record's closed vocabularies.

Every clause here is a *refusal at index time*, and every one of them is
therefore also a refusal at publish, because ``validate_content`` builds the
index (``_publish.py:50-63``). That chain is asserted once, in
``test_every_index_refusal_also_refuses_publication``, rather than repeated
per clause — but it is asserted, because "the index refuses" and "the tree
cannot ship" are different claims and only the second one is the control.

The refusals are named tokens, not prose: ``RegistryRefusal.reason`` is what a
caller branches on, so that is what these tests assert. The message is checked
only where a clause says the refusal must *name* something (the missing
interface, the offending parameter, the sample index), because naming it is the
difference between a refusal an author can act on and one they cannot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _g11a import DATASHEET, component_tree, index_of, motor_component
from hephaestus.core.registry import (
    COMPONENT_CLASSES,
    INTERFACE_CLASSES,
    RegistryRefusal,
    publish_registry,
)


def refuse(tmp_path: Path, component: dict[str, Any], **kwargs: Any) -> RegistryRefusal:
    """Index a one-part tree around ``component`` and return the refusal."""
    root = component_tree(tmp_path / "tree", component, **kwargs)
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    return caught.value


def accept(tmp_path: Path, component: dict[str, Any], **kwargs: Any) -> None:
    root = component_tree(tmp_path / "tree", component, **kwargs)
    assert index_of(root).component_ids() == ("stepper_nema17_frame",)


# ==========================================================================
# the negative control on the whole section: §1's own example


#: ``PARTS_STORE.md`` §1's worked ``stepper_nema17_frame`` record, verbatim —
#: **plus** ``simplifications``, which the printed example omits and §1's own
#: prose requires ("a required non-empty list on any component whose geometry is
#: an envelope"). The prose is the rule and the example is illustrative, so the
#: parser follows the prose; the gap is recorded here rather than resolved by
#: quietly making the field optional.
SPEC_EXAMPLE: dict[str, Any] = {
    "class": "motor",
    "series": {"family": "nema", "size": "17", "standard": "NEMA ICS 16-2001"},
    "license": "Apache-2.0",
    "data_license": "facts-only",
    "simplifications": ["frame envelope only; no winding or connector detail"],
    "interfaces": [
        {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
        {"name": "pilot_bore", "class": "cylindrical_face", "role": "pilot"},
        {"name": "shaft", "class": "cylindrical_face", "role": "shaft"},
        {"name": "shaft_axis", "class": "circular_edge", "role": "axis"},
        {"name": "bolt_1", "class": "cylindrical_face", "role": "mount_hole"},
    ],
    "mass": {"value_g": 280.0, "source": "datasheet", "com_mm": [0.0, 0.0, -19.5]},
    "datasheet": DATASHEET,
    "claims": [
        {
            "id": "torque_speed",
            "kind": "torque_speed_curve",
            "unit_x": "rpm",
            "unit_y": "N*m",
            "samples": [[0, 0.44], [200, 0.42], [600, 0.28], [1200, 0.11]],
            "cite": {"page": 3, "quote": "Holding torque 0.44 N-m"},
        }
    ],
}


def test_the_specs_own_worked_example_parses_and_round_trips(tmp_path: Path) -> None:
    """A vocabulary that refuses the document's own example is a defect, not a
    stricter gate — the same negative-control discipline §2.1 applies to the
    interface region, applied to the record."""
    root = component_tree(tmp_path / "tree", SPEC_EXAMPLE)
    part = index_of(root).get("stepper_nema17_frame")
    record = part.component
    assert record is not None
    assert record.component_class == "motor"
    assert record.interface_names == (
        "mount_face",
        "pilot_bore",
        "shaft",
        "shaft_axis",
        "bolt_1",
    )
    assert record.mass is not None and record.mass.value_g == 280.0
    assert record.mass.com_mm == (0.0, 0.0, -19.5)
    assert record.datasheet is not None and record.datasheet.revision == "Rev C"
    assert [claim.id for claim in record.claims] == ["torque_speed"]
    assert record.claims[0].samples[0] == (0.0, 0.44)
    # Declared data is copied, not computed (§9): the samples come back as given.
    payload = record.to_json()
    assert payload["datasheet"] == DATASHEET
    assert payload["class"] == "motor"


# ==========================================================================
# clause 4 — the class vocabulary is closed


def test_an_unknown_component_class_is_refused_and_lists_the_valid_set(
    tmp_path: Path,
) -> None:
    refusal = refuse(tmp_path, motor_component(**{"class": "flux_capacitor"}))
    assert refusal.reason == "unknown_component_kind"
    for valid in COMPONENT_CLASSES:
        assert valid in refusal.message, "the refusal must list the valid set"
    assert "flux_capacitor" in refusal.message


@pytest.mark.parametrize("component_class", COMPONENT_CLASSES)
def test_every_declared_class_is_accepted_with_its_required_interfaces(
    component_class: str, tmp_path: Path
) -> None:
    """The negative control on clause 4: a closed set that refuses its own
    members would be a defect, not a stricter gate."""
    from hephaestus.core.registry import REQUIRED_INTERFACE_ROLES

    roles = REQUIRED_INTERFACE_ROLES[component_class]
    interfaces = [{"name": role, "class": "cylindrical_face", "role": role} for role in roles] or [
        {"name": "body", "class": "solid", "role": "body"}
    ]
    accept(
        tmp_path,
        motor_component(**{"class": component_class, "interfaces": interfaces}),
    )


# ==========================================================================
# clause 5 — required interfaces per class


@pytest.mark.parametrize(
    ("component_class", "keep", "missing"),
    [
        ("motor", "mount_face", "shaft"),
        ("motor", "shaft", "mount_face"),
        ("bearing", "bore", "outer"),
        ("bearing", "outer", "bore"),
    ],
)
def test_a_record_missing_a_required_interface_names_it(
    component_class: str, keep: str, missing: str, tmp_path: Path
) -> None:
    component = motor_component(
        **{
            "class": component_class,
            "interfaces": [{"name": keep, "class": "cylindrical_face", "role": keep}],
        }
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "missing_required_interface"
    assert missing in refusal.message
    assert refusal.detail["missing"] == [missing]


# ==========================================================================
# clause 6 — duplicate identifiers, both kinds


def test_a_duplicate_interface_name_is_refused_naming_the_repeat(tmp_path: Path) -> None:
    component = motor_component(
        interfaces=[
            {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
            {"name": "shaft", "class": "cylindrical_face", "role": "shaft"},
            {"name": "shaft", "class": "cylindrical_face", "role": "pilot"},
        ]
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "duplicate_interface_name"
    assert "'shaft'" in refusal.message


def test_a_duplicate_claim_id_is_refused_naming_the_repeat(tmp_path: Path) -> None:
    claim = {
        "id": "torque_speed",
        "kind": "torque_speed_curve",
        "unit_x": "rpm",
        "unit_y": "N*m",
        "samples": [[0, 0.44], [600, 0.28]],
        "cite": {"page": 3, "quote": "Holding torque 0.44 N-m"},
    }
    component = motor_component(datasheet=DATASHEET, claims=[claim, dict(claim)])
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "duplicate_claim_id"
    assert "'torque_speed'" in refusal.message


# ==========================================================================
# clause 7 — the interface-class vocabulary is closed


def test_an_unknown_interface_class_is_refused(tmp_path: Path) -> None:
    component = motor_component(
        interfaces=[
            {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
            {"name": "shaft", "class": "conical_face", "role": "shaft"},
        ]
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "unknown_interface_class"
    for valid in INTERFACE_CLASSES:
        assert valid in refusal.message


# ==========================================================================
# clause 10 — unsourced_component_datum, all four cases


def test_a_datasheet_mass_with_no_datasheet_block_is_unsourced(tmp_path: Path) -> None:
    component = motor_component(mass={"value_g": 280.0, "source": "datasheet"})
    assert refuse(tmp_path, component).reason == "unsourced_component_datum"


def test_a_standard_mass_with_no_series_standard_is_unsourced(tmp_path: Path) -> None:
    component = motor_component(
        series={"family": "nema", "size": "17"},
        mass={"value_g": 280.0, "source": "standard"},
    )
    assert refuse(tmp_path, component).reason == "unsourced_component_datum"


def test_a_claim_with_no_cite_is_unsourced(tmp_path: Path) -> None:
    component = motor_component(
        datasheet=DATASHEET,
        claims=[
            {
                "id": "torque_speed",
                "kind": "torque_speed_curve",
                "unit_x": "rpm",
                "unit_y": "N*m",
                "samples": [[0, 0.44], [600, 0.28]],
            }
        ],
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "unsourced_component_datum"
    assert "torque_speed" in refusal.message


def test_a_non_empty_claims_list_with_no_datasheet_block_is_unsourced(tmp_path: Path) -> None:
    """§6.1's closure rule — the one that makes §7.4's join *total*.

    Without it a ledger ``cite`` could name a claim of a component with no
    datasheet, and ``datasheet_digest_mismatch`` would have no right-hand side.
    """
    component = motor_component(
        claims=[
            {
                "id": "torque_speed",
                "kind": "torque_speed_curve",
                "unit_x": "rpm",
                "unit_y": "N*m",
                "samples": [[0, 0.44], [600, 0.28]],
                "cite": {"page": 3, "quote": "Holding torque 0.44 N-m"},
            }
        ]
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "unsourced_component_datum"
    assert "datasheet" in refusal.message


def test_a_sourced_record_is_accepted(tmp_path: Path) -> None:
    """The negative control on clause 10."""
    accept(
        tmp_path,
        motor_component(
            datasheet=DATASHEET,
            mass={"value_g": 280.0, "source": "datasheet", "com_mm": [0.0, 0.0, -19.5]},
            claims=[
                {
                    "id": "torque_speed",
                    "kind": "torque_speed_curve",
                    "unit_x": "rpm",
                    "unit_y": "N*m",
                    "samples": [[0, 0.44], [200, 0.42], [600, 0.28], [1200, 0.11]],
                    "cite": {"page": 3, "quote": "Holding torque 0.44 N-m"},
                }
            ],
        ),
    )


# ==========================================================================
# clause 11 — mass_source_conflict


def test_a_datasheet_mass_and_a_computed_material_conflict(tmp_path: Path) -> None:
    component = motor_component(
        datasheet=DATASHEET,
        mass={"value_g": 280.0, "source": "datasheet", "material": "steel_1018"},
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "mass_source_conflict"
    assert "steel_1018" in refusal.message


# ==========================================================================
# clause 12 — inertia_out_of_scope


@pytest.mark.parametrize("field", ["inertia", "inertia_tensor", "moi", "inertia_kg_mm2"])
def test_an_inertia_tensor_is_refused_naming_the_field(field: str, tmp_path: Path) -> None:
    refusal = refuse(tmp_path, motor_component(**{field: [1.0, 2.0, 3.0]}))
    assert refusal.reason == "inertia_out_of_scope"
    assert field in refusal.message
    assert refusal.detail["field"] == field


def test_an_inertia_tensor_hidden_in_the_mass_block_is_refused_too(tmp_path: Path) -> None:
    component = motor_component(
        datasheet=DATASHEET,
        mass={"value_g": 280.0, "source": "datasheet", "inertia": [1.0, 2.0, 3.0]},
    )
    refusal = refuse(tmp_path, component)
    assert refusal.reason == "inertia_out_of_scope"
    assert refusal.detail["field"] == "mass.inertia"


# ==========================================================================
# clause 13 — malformed_performance_curve, six cases, each naming a sample index


def _with_curve(**curve: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "torque_speed",
        "kind": "torque_speed_curve",
        "unit_x": "rpm",
        "unit_y": "N*m",
        "samples": [[0, 0.44], [600, 0.28]],
        "cite": {"page": 3, "quote": "Holding torque 0.44 N-m"},
    }
    entry.update(curve)
    return motor_component(datasheet=DATASHEET, claims=[entry])


@pytest.mark.parametrize(
    ("label", "curve", "sample"),
    [
        ("one sample", {"samples": [[0, 0.44]]}, 1),
        ("non-finite", {"samples": [[0, 0.44], [float("inf"), 0.28]]}, 1),
        ("non-increasing x", {"samples": [[600, 0.44], [600, 0.28]]}, 1),
        ("negative y", {"samples": [[0, 0.44], [600, -0.1]]}, 1),
        ("increasing y", {"samples": [[0, 0.28], [600, 0.44]]}, 1),
    ],
)
def test_a_malformed_curve_is_refused_naming_the_sample_index(
    label: str, curve: dict[str, Any], sample: int, tmp_path: Path
) -> None:
    refusal = refuse(tmp_path, _with_curve(**curve))
    assert refusal.reason == "malformed_performance_curve", label
    assert refusal.detail["sample"] == sample, label
    assert refusal.detail["claim"] == "torque_speed"


@pytest.mark.parametrize(
    ("axis", "curve"),
    [("x", {"unit_x": "furlongs"}), ("y", {"unit_y": "foot-pounds"})],
)
def test_an_undeclared_unit_is_refused(axis: str, curve: dict[str, Any], tmp_path: Path) -> None:
    refusal = refuse(tmp_path, _with_curve(**curve))
    assert refusal.reason == "malformed_performance_curve"
    assert refusal.detail["axis"] == axis


# ==========================================================================
# clause 14 — the datasheet pointer block


@pytest.mark.parametrize(
    "field", ["publisher", "document_title", "revision", "url", "sha256", "retrieved"]
)
def test_each_missing_datasheet_field_is_refused_in_turn(field: str, tmp_path: Path) -> None:
    block = {key: value for key, value in DATASHEET.items() if key != field}
    refusal = refuse(tmp_path, motor_component(datasheet=block))
    assert refusal.reason == "malformed_datasheet_pointer"
    assert refusal.detail["field"] == field


def test_a_sha256_without_the_prefix_is_refused(tmp_path: Path) -> None:
    block = dict(DATASHEET, sha256="9f" * 32)
    refusal = refuse(tmp_path, motor_component(datasheet=block))
    assert refusal.reason == "malformed_datasheet_pointer"
    assert refusal.detail["field"] == "sha256"


# ==========================================================================
# §1's "resolved, not preserved", and the index->publish chain


@pytest.mark.parametrize("key", ["envelope", "mating_features", "origin", "simplifications"])
def test_a_component_may_not_keep_a_retired_metadata_key(key: str, tmp_path: Path) -> None:
    """Leaving an unread key beside a read one teaches the next author that
    either is fine — which is exactly how ``mating_features`` happened."""
    root = component_tree(tmp_path / "tree", motor_component(), extra_meta={key: {"anything": 1.0}})
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    assert caught.value.reason == "retired_metadata_key"
    assert key in caught.value.message


def test_every_index_refusal_also_refuses_publication(tmp_path: Path) -> None:
    """The control is not "the index complains" — it is "the tree cannot ship"."""
    root = component_tree(tmp_path / "tree", motor_component(**{"class": "flux_capacitor"}))
    with pytest.raises(RegistryRefusal) as caught:
        publish_registry(root)
    assert caught.value.reason == "unknown_component_kind"
