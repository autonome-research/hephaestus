"""Shared fakes for the checks tests: string-id shapes + deterministic kernel ops.

Not a test module — imported by test_checks_*.py. Shapes are opaque string
ids of the form ``<part>:<kind>:<name>:<occurrence>`` so tests can pin exact
values per resolved selection without any geometry kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hephaestus.core.addressing import GeometryIndex, Resolution
from hephaestus.core.checks.facade import MappedGeometry


def make_source(part: str, index: GeometryIndex) -> MappedGeometry:
    """A GeometrySource whose shapes are string ids encoding the resolution."""

    def resolver(resolution: Resolution) -> str:
        if resolution.fused:
            occ = "*"
        elif resolution.occurrences:
            occ = str(resolution.occurrences[0])
        else:
            occ = "-"
        return f"{part}:{resolution.kind}:{resolution.name}:{occ}"

    return MappedGeometry(index=index, resolver=resolver)


@dataclass
class FakeOps:
    """Deterministic kernel backend over string shape ids (KernelOps-compatible)."""

    volumes: dict[str, float] = field(default_factory=dict[str, float])
    bboxes: dict[str, tuple[float, float, float]] = field(
        default_factory=dict[str, tuple[float, float, float]]
    )
    interferences: dict[frozenset[str], float] = field(default_factory=dict[frozenset[str], float])
    clearances: dict[frozenset[str], float] = field(default_factory=dict[frozenset[str], float])
    distances: dict[frozenset[str], float] = field(default_factory=dict[frozenset[str], float])
    sealed_map: dict[str, bool] = field(default_factory=dict[str, bool])
    genus_map: dict[str, int] = field(default_factory=dict[str, int])

    def _pair(self, table: dict[frozenset[str], float], a: object, b: object) -> float:
        return table.get(frozenset({str(a), str(b)}), 0.0)

    def interference(self, a: object, b: object) -> float:
        return self._pair(self.interferences, a, b)

    def clearance(self, a: object, b: object) -> float:
        return self._pair(self.clearances, a, b)

    def distance(self, a: object, b: object) -> float:
        return self._pair(self.distances, a, b)

    def mass(self, shape: object, density: float) -> float:
        return self.volumes.get(str(shape), 0.0) * density / 1000.0

    def bbox(self, shape: object) -> tuple[float, float, float]:
        return self.bboxes.get(str(shape), (0.0, 0.0, 0.0))

    def volume(self, shape: object) -> float:
        return self.volumes.get(str(shape), 0.0)

    def sealed(self, shape: object) -> bool:
        return self.sealed_map.get(str(shape), True)

    def genus(self, shape: object) -> int:
        return self.genus_map.get(str(shape), 0)


PRIMARY_INDEX = GeometryIndex(
    labels=("plate", "rib", "rib"),
    bindings={"pins": 3},
    tags=frozenset({"top_face"}),
)
BRACKET_INDEX = GeometryIndex(labels=("arm",), bindings={}, tags=frozenset())

PLATE = "primary:label:plate:0"
RIB = "primary:label:rib:1"
ARM = "bracket:label:arm:0"
PRIMARY_PART = "primary:part:part:-"


def primary_source() -> MappedGeometry:
    return make_source("primary", PRIMARY_INDEX)


def bracket_source() -> MappedGeometry:
    return make_source("bracket", BRACKET_INDEX)
