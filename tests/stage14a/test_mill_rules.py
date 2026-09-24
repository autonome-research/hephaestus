# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14A clauses 6 and 7: the five §6.2 rules, and the declared machining block.

Clause 6 — each rule fires on a fixture with a known violation and does not
fire on a compliant fixture, with correct ``rule_id``, offending tag,
artifact-bound topology descriptor and resolved ``source_artifact_ref`` (the
G6 clause shape); the accessibility rule additionally proves it is computable
from the existing ``DfmContext`` accessors. Clause 7 — the materials machining
block resolves, and each pack parameter that reads it gets the declared
number, never the prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _g14a import (
    al6061_record,
    compliant_fixture,
    materials_index,
    mill_fixture,
    mill_pack,
    run_in_process,
)
from hephaestus.core.dfm import TopologyDescriptor
from hephaestus.core.dfm.context import DfmContext
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import MaterialsIndex, load_registry
from opstore.types import JSONValue

ARTIFACT_REF = "artifact:build:sha256:g14a-mill"


def _measured(finding: object) -> dict[str, JSONValue]:
    """Narrow a finding's free-form ``measured`` payload to the dict it is."""
    measured = getattr(finding, "measured", None)
    assert isinstance(measured, dict), f"finding measured payload is not a dict: {measured!r}"
    return measured


RULES = (
    "cnc_mill.min_internal_radius_vs_tool",
    "cnc_mill.pocket_depth_vs_tool_diameter",
    "cnc_mill.min_web_thickness",
    "cnc_mill.bore_aspect_ratio",
    "cnc_mill.single_axis_accessibility",
)


# -- clause 6: each rule, both directions, in the G6 shape -------------------


def test_every_mill_rule_fires_on_the_mill_fixture(tmp_path: Path) -> None:
    outcomes = run_in_process(
        mill_pack(),
        mill_fixture(),
        tmp_path,
        part="block",
        artifact_ref=ARTIFACT_REF,
        metadata={"material_spec": "6061 aluminium plate", "stock_form": "plate"},
        material=al6061_record(),
    )
    assert set(outcomes) == set(RULES)
    assert all(outcome.status == "violations" for outcome in outcomes.values()), {
        rule_id: (outcome.status, outcome.error) for rule_id, outcome in outcomes.items()
    }

    corner = outcomes["cnc_mill.min_internal_radius_vs_tool"].findings[0]
    assert corner.severity == "error"
    assert corner.suggested_bound == pytest.approx(1.5)
    assert "0.300 mm" in corner.message

    pocket = outcomes["cnc_mill.pocket_depth_vs_tool_diameter"].findings[0]
    assert pocket.suggested_bound == pytest.approx(12.0)
    assert "chatter" in pocket.message

    web = outcomes["cnc_mill.min_web_thickness"].findings[0]
    assert web.suggested_bound == pytest.approx(1.0)
    assert len(web.topology) == 2, "a web names both of its faces"

    bore = outcomes["cnc_mill.bore_aspect_ratio"].findings[0]
    assert bore.suggested_bound == pytest.approx(6.0)

    access = outcomes["cnc_mill.single_axis_accessibility"].findings[0]
    assert "spindle" in access.message


def test_no_mill_rule_fires_on_the_compliant_fixture(tmp_path: Path) -> None:
    outcomes = run_in_process(
        mill_pack(),
        compliant_fixture(),
        tmp_path,
        part="plate",
        artifact_ref=ARTIFACT_REF,
        material=al6061_record(),
    )
    assert set(outcomes) == set(RULES)
    assert all(outcome.status == "ok" for outcome in outcomes.values()), {
        rule_id: (outcome.status, outcome.error, [f.message for f in outcome.findings])
        for rule_id, outcome in outcomes.items()
    }
    assert all(not outcome.findings for outcome in outcomes.values())


def test_findings_carry_the_g6_clause_shape(tmp_path: Path) -> None:
    """Correct rule_id, artifact-bound topology descriptor, and the resolved
    source artifact ref, on every finding of every rule."""
    outcomes = run_in_process(
        mill_pack(),
        mill_fixture(),
        tmp_path,
        part="block",
        artifact_ref=ARTIFACT_REF,
        material=al6061_record(),
    )
    for rule_id, outcome in outcomes.items():
        for finding in outcome.findings:
            assert finding.rule_id == rule_id
            assert finding.source_artifact_ref == ARTIFACT_REF
            assert finding.topology, "every finding points at topology"
            for descriptor in finding.topology:
                # Never a bare mask id: (kind, solid_id, topology_index).
                assert set(descriptor.to_json()) == {
                    "kind",
                    "solid_id",
                    "topology_index",
                    "tag",
                }
                assert descriptor.kind in ("face", "edge")
                assert descriptor.solid_id is not None
                assert descriptor.topology_index is not None


def test_a_tagged_bore_is_reported_by_name(tmp_path: Path) -> None:
    """The offending-tag half of the G6 shape: tag the deep bore's face and the
    finding names it."""
    brep = mill_fixture()
    untagged = run_in_process(mill_pack(), brep, tmp_path / "a", artifact_ref=ARTIFACT_REF)
    descriptor = untagged["cnc_mill.bore_aspect_ratio"].findings[0].topology[0]
    assert descriptor.tag is None

    tagged = run_in_process(
        mill_pack(),
        brep,
        tmp_path / "b",
        artifact_ref=ARTIFACT_REF,
        tags={
            "drill_dowel_bore": TopologyDescriptor(
                kind="face",
                solid_id=descriptor.solid_id,
                topology_index=descriptor.topology_index,
                tag="drill_dowel_bore",
            )
        },
    )
    candidates = [f for f in tagged["cnc_mill.bore_aspect_ratio"].findings if f.tags]
    assert len(candidates) == 1, "exactly the tagged bore is reported by name"
    finding = candidates[0]
    assert finding.tags == ("drill_dowel_bore",)
    assert finding.topology[0].tag == "drill_dowel_bore"
    assert finding.source_artifact_ref == ARTIFACT_REF


def test_the_accessibility_rule_is_computable_from_the_existing_context() -> None:
    """CAM.md §11 item 5 left the decision to this clause: either the predicate
    is written from the existing accessors, or a context extension is asserted
    present. It IS written from the existing accessors — every ``ctx.<name>``
    the predicate source touches exists on ``DfmContext`` today, so no
    extension was needed and none was made."""
    rule = mill_pack().rule("cnc_mill.single_axis_accessibility")
    source = rule.read_predicate()
    touched = set(re.findall(r"\bctx\.([a-z_]+)", source))
    assert touched, "the predicate reads the context"
    missing = {name for name in touched if not hasattr(DfmContext, name)}
    assert not missing, f"accessibility predicate needs accessors DfmContext lacks: {missing}"
    # And the two geometric accessors §6.2 names are the ones actually used.
    assert {"holes", "planar_faces"} <= touched


# -- clause 7: the declared machining block ----------------------------------


def test_the_materials_machining_block_resolves_to_declared_numbers() -> None:
    index = materials_index()
    for material_id in ("al-6061", "plywood-baltic-birch"):
        material = index.get(material_id)
        assert material is not None
        assert material.machining, f"{material_id} declares a machining block (CAM.md §6.2)"
        for key, value in material.machining.items():
            assert isinstance(value, float), f"{material_id} machining.{key} is a number"
    aluminium = index.get("al-6061")
    assert aluminium is not None
    # The exact numbers the notes prose carried, now declared (CAM.md §6.2):
    # "3 mm end mill => 1.5 mm minimum internal radius", "about 4x", "roughly 1 mm".
    assert aluminium.machining["min_internal_radius_mm"] == pytest.approx(1.5)
    assert aluminium.machining["max_depth_diameter_ratio"] == pytest.approx(4.0)
    assert aluminium.machining["min_web_mm"] == pytest.approx(1.0)
    # The prose is still there — reference content — but is not what resolves.
    assert "roughly 1 mm" in aluminium.notes


def test_each_pack_parameter_reading_the_block_gets_the_declared_number(
    tmp_path: Path,
) -> None:
    """Hand the pack a material whose machining numbers differ from both the
    pack defaults and the prose; every finding bound must be the material's
    declared number — provably read from the block, not from [params] and not
    from notes."""
    record: dict[str, JSONValue] = al6061_record()
    record["machining"] = {
        "min_internal_radius_mm": 2.5,
        "max_depth_diameter_ratio": 3.0,
        "min_web_mm": 2.0,
    }
    record["notes"] = "prose says 9 mm corners, 9x pockets and 9 mm webs — and is never read"
    outcomes = run_in_process(
        mill_pack(),
        mill_fixture(),
        tmp_path,
        artifact_ref=ARTIFACT_REF,
        material=record,
    )

    corner = outcomes["cnc_mill.min_internal_radius_vs_tool"].findings[0]
    assert corner.suggested_bound == pytest.approx(2.5)
    assert _measured(corner)["radius_floor_source"] == "material"

    pocket = outcomes["cnc_mill.pocket_depth_vs_tool_diameter"].findings[0]
    assert pocket.suggested_bound == pytest.approx(3.0 * 3.0), "tool 3 mm x declared 3.0 ratio"
    assert _measured(pocket)["limit_ratio_source"] == "material"

    web = outcomes["cnc_mill.min_web_thickness"].findings[0]
    assert web.suggested_bound == pytest.approx(2.0)
    assert _measured(web)["web_floor_source"] == "material"


def test_without_a_block_the_pack_defaults_govern_and_say_so(tmp_path: Path) -> None:
    record: dict[str, JSONValue] = al6061_record()
    record.pop("machining", None)
    outcomes = run_in_process(
        mill_pack(), mill_fixture(), tmp_path, artifact_ref=ARTIFACT_REF, material=record
    )
    corner = outcomes["cnc_mill.min_internal_radius_vs_tool"].findings[0]
    assert corner.suggested_bound == pytest.approx(1.5)
    assert _measured(corner)["radius_floor_source"] == "pack"


def test_a_machining_block_carrying_prose_is_refused_at_load(tmp_path: Path) -> None:
    """The block exists so a predicate never reads notes; a record smuggling
    prose back in through it is refused at index time, by the field."""
    root = tmp_path / "materials"
    root.mkdir()
    (root / "registry.toml").write_text(
        '[registry]\nname = "m"\nkind = "materials"\nversion = "0.0.1"\n'
        'license = "Apache-2.0"\n\n[[materials]]\nid = "prose"\nfile = "prose.json"\n',
        encoding="utf-8",
    )
    (root / "prose.json").write_text(
        '{"id": "prose", "density": 1000.0, "machining": {"min_web_mm": "roughly 1 mm"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as caught:
        MaterialsIndex(load_registry(root))
    assert "min_web_mm" in caught.value.message
    assert "not prose" in caught.value.message
