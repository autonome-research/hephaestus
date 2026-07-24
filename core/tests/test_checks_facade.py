"""Measurement facade: addressing-bound, traced, part- and project-scoped."""

from __future__ import annotations

import pytest
from hephaestus.core.checks.approx import Triple, approx
from hephaestus.core.checks.facade import (
    GeometrySource,
    MeasurementEntry,
    part_measurement,
    project_measurement,
)
from hephaestus.core.errors import AddressingError
from test_checks_helpers import (
    ARM,
    PLATE,
    PRIMARY_PART,
    FakeOps,
    bracket_source,
    primary_source,
)


class TestPartScoped:
    def test_binary_and_trace(self) -> None:
        ops = FakeOps(interferences={frozenset({PLATE, "primary:label:rib:1"}): 1.25})
        m = part_measurement("primary", primary_source(), ops=ops)
        assert m.interference("plate", "rib") == 1.25
        assert m.trace == (MeasurementEntry(op="interference", args=("plate", "rib"), value=1.25),)
        assert m.measured_json() == 1.25

    def test_bbox_returns_elementwise_triple(self) -> None:
        ops = FakeOps(bboxes={PRIMARY_PART: (380.0, 280.0, 250.0)})
        m = part_measurement("primary", primary_source(), ops=ops)
        box = m.bbox("part")
        assert isinstance(box, Triple)
        assert box <= (380.5, 280.5, 250.5)
        assert not (box <= (379.0, 280.5, 250.5))
        assert m.measured_json() == [380.0, 280.0, 250.0]

    def test_unary_ops(self) -> None:
        ops = FakeOps(
            volumes={PRIMARY_PART: 1000.0},
            sealed_map={PRIMARY_PART: True},
            genus_map={PRIMARY_PART: 0},
        )
        m = part_measurement("primary", primary_source(), ops=ops)
        assert m.volume("part") == 1000.0
        assert m.sealed("part") is True
        assert m.genus("part") == 0

    def test_mass_density_resolution(self) -> None:
        ops = FakeOps(volumes={PRIMARY_PART: 2000.0})
        default = part_measurement("primary", primary_source(), ops=ops)
        assert default.mass("part") == 2.0  # implicit density 1.0
        bound = part_measurement("primary", primary_source(), ops=ops, density=7.85)
        assert bound.mass("part") == pytest.approx(15.7)
        assert bound.mass("part", density=2.0) == 4.0  # explicit wins

    def test_selector_grammar_reaches_addressing(self) -> None:
        ops = FakeOps(volumes={"primary:label:rib:2": 7.0, "primary:label:rib:*": 11.0})
        m = part_measurement("primary", primary_source(), ops=ops)
        assert m.volume("rib#2") == 7.0
        assert m.volume("rib#*") == 11.0

    def test_addressing_error_lists_candidates(self) -> None:
        m = part_measurement("primary", primary_source(), ops=FakeOps())
        with pytest.raises(AddressingError) as excinfo:
            m.volume("plat")
        assert "plate" in excinfo.value.candidates

    def test_part_scope_rejects_other_parts(self) -> None:
        m = part_measurement("primary", primary_source(), ops=FakeOps())
        with pytest.raises(AddressingError):
            m.volume("bracket/arm")

    def test_approx_integration(self) -> None:
        ops = FakeOps()  # unknown pair -> 0.0 interference
        m = part_measurement("primary", primary_source(), ops=ops)
        assert m.interference("plate", "rib") == approx(0, abs=1e-6)


class TestProjectScoped:
    def make_project(self, ops: FakeOps) -> dict[str, GeometrySource]:
        _ = ops
        return {"primary": primary_source(), "bracket": bracket_source()}

    def test_cross_part_measurement(self) -> None:
        ops = FakeOps(clearances={frozenset({PLATE, ARM}): 2.5})
        m = project_measurement(self.make_project(ops), ops=ops)
        assert m.clearance("primary/plate", "bracket/arm") == 2.5

    def test_current_part_default(self) -> None:
        ops = FakeOps(volumes={ARM: 42.0})
        m = project_measurement(self.make_project(ops), current_part="bracket", ops=ops)
        assert m.volume("arm") == 42.0

    def test_no_current_part_requires_prefix(self) -> None:
        m = project_measurement(self.make_project(FakeOps()), ops=FakeOps())
        with pytest.raises(AddressingError):
            m.volume("arm")

    def test_unknown_part_lists_known_parts(self) -> None:
        m = project_measurement(self.make_project(FakeOps()), ops=FakeOps())
        with pytest.raises(AddressingError) as excinfo:
            m.volume("gusset/arm")
        assert "bracket" in excinfo.value.message or "bracket" in excinfo.value.candidates

    def test_per_part_densities(self) -> None:
        ops = FakeOps(volumes={ARM: 1000.0})
        m = project_measurement(self.make_project(ops), ops=ops, densities={"bracket": 2.7})
        assert m.mass("bracket/arm") == 2.7


class TestTrace:
    def test_empty_trace_measured_none(self) -> None:
        m = part_measurement("primary", primary_source(), ops=FakeOps())
        assert m.measured_json() is None

    def test_multi_measurement_trace(self) -> None:
        ops = FakeOps(sealed_map={PRIMARY_PART: True}, genus_map={PRIMARY_PART: 1})
        m = part_measurement("primary", primary_source(), ops=ops)
        assert m.sealed("part") and m.genus("part") == 1
        assert m.measured_json() == [
            {"op": "sealed", "args": ["part"], "value": True},
            {"op": "genus", "args": ["part"], "value": 1},
        ]

    def test_determinism(self) -> None:
        ops = FakeOps(volumes={PRIMARY_PART: 123.456})
        values: set[float] = set()
        for _ in range(50):
            m = part_measurement("primary", primary_source(), ops=ops)
            values.add(m.volume("part"))
        assert values == {123.456}
