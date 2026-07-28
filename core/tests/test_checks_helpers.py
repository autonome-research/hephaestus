"""Shared fakes for the checks tests: string-id shapes + deterministic kernel ops.

Not a test module — imported by test_checks_*.py. Shapes are opaque string
ids of the form ``<part>:<kind>:<name>:<occurrence>`` so tests can pin exact
values per resolved selection without any geometry kernel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from hephaestus.core.addressing import GeometryIndex, Resolution
from hephaestus.core.checks.facade import MappedGeometry
from opstore.types import JSONValue


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
    #: ``m.diff`` iou per unordered shape-id pair (default: identical solids).
    ious: dict[frozenset[str], float] = field(default_factory=dict[frozenset[str], float])
    #: ``m.diff`` chamfer (mm) per unordered pair (default: coincident surfaces).
    chamfers: dict[frozenset[str], float] = field(default_factory=dict[frozenset[str], float])
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

    def diff(self, a: object, b: object, align: str) -> Mapping[str, JSONValue]:
        """A ``dataclasses.asdict(SolidDiff)``-shaped record, without a kernel.

        The field names are the geom record's (COMPARE.md §1) because the facade
        flattens exactly those; ``core/tests/test_geom_compare.py`` is where the
        real numbers are asserted.
        """
        pair = frozenset({str(a), str(b)})
        iou = self.ious.get(pair, 1.0)
        chamfer = self.chamfers.get(pair, 0.0)
        volume = self.volumes.get(str(a), 0.0)
        census: dict[str, JSONValue] = {
            "solids": 1,
            "faces": 6,
            "edges": 12,
            "planar_faces": 6,
            "cylindrical_faces": 0,
            "other_faces": 0,
            "genus": 0,
            "sealed": True,
        }
        return {
            "align": align,
            "volume": {
                "common_mm3": volume * iou,
                "a_only_mm3": volume * (1.0 - iou),
                "b_only_mm3": 0.0,
                "iou": iou,
                "align": align,
            },
            "surface": {
                "a_to_b_mean_mm": chamfer,
                "b_to_a_mean_mm": chamfer,
                "chamfer_mm": chamfer,
                "max_deviation_mm": chamfer,
                "a_samples": 64,
                "b_samples": 64,
                "align": align,
            },
            "topology": {
                "a": dict(census),
                "b": dict(census),
                "solids_delta": 0,
                "faces_delta": 0,
                "edges_delta": 0,
                "planar_faces_delta": 0,
                "cylindrical_faces_delta": 0,
                "other_faces_delta": 0,
                "genus_delta": 0,
                "sealed_changed": False,
            },
            "a_bbox_mm": list(self.bboxes.get(str(a), (0.0, 0.0, 0.0))),
            "b_bbox_mm": list(self.bboxes.get(str(b), (0.0, 0.0, 0.0))),
            "a_volume_mm3": volume,
            "b_volume_mm3": self.volumes.get(str(b), volume),
        }


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
