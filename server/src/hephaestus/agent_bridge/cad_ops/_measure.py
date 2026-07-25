"""The ``measure`` tool: geometry resolution, the ``m`` facade, resolved refs.

Measurement always runs over *artifact-reloaded* geometry, never a live build, so
what is measured is exactly what a ref names. Resolution has three modes: an
explicit ``artifact_ref`` (single part only), an explicit ``project_snapshot_ref``,
or the implicit path — one part's current successful build when a single part is
addressed, otherwise one coherent project snapshot assembled on the spot (an
incoherent project is the discriminated ``incoherent_project_snapshot`` refusal).

The result reports the units for the kind and every artifact ref that was
actually read, so a caller can re-measure the identical geometry later.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.checks.facade import GeometrySource, project_measurement
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.projections import SnapshotRejectedError
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

_MEASURE_UNITS: Final[dict[str, str]] = {
    "interference": "mm^3",
    "clearance": "mm",
    "distance": "mm",
    "bbox": "mm",
    "volume": "mm^3",
    "mass": "g",
    "sealed": "bool",
    "genus": "count",
}

_BINARY_MEASURE_KINDS: Final[frozenset[str]] = frozenset({"interference", "clearance", "distance"})


class MeasureOps(CadOpsState):
    """Resolve the geometry a measurement addresses and evaluate it."""

    def measure(
        self,
        kind: str,
        a: str,
        b: str | None,
        *,
        part: str | None,
        artifact_ref: str | None,
        project_snapshot_ref: str | None,
    ) -> dict[str, Any]:
        """The ``m`` facade as a tool: resolve geometry, measure, report refs."""
        if kind not in _MEASURE_UNITS:
            raise CadOpError("invalid_params", f"unknown measure kind {kind!r}")
        if (kind in _BINARY_MEASURE_KINDS) != (b is not None):
            raise CadOpError(
                "invalid_params",
                f"measure kind {kind!r} "
                + ("requires" if kind in _BINARY_MEASURE_KINDS else "forbids")
                + " selector 'b'",
            )
        if artifact_ref is not None and project_snapshot_ref is not None:
            raise CadOpError(
                "invalid_params", "artifact_ref and project_snapshot_ref are mutually exclusive"
            )
        selectors = [a] + ([b] if b is not None else [])
        qualified = {s.split("/", 1)[0] for s in selectors if "/" in s}
        current = part or (sorted(qualified)[0] if qualified else None)
        with self._scratch("heph-measure-") as scratch:
            sources, refs = self._measure_sources(
                selectors,
                qualified,
                current,
                artifact_ref=artifact_ref,
                project_snapshot_ref=project_snapshot_ref,
                scratch=Path(scratch),
            )
            measurement = project_measurement(sources, current_part=current)
            value: JSONValue
            if kind == "interference":
                value = measurement.interference(a, cast("str", b))
            elif kind == "clearance":
                value = measurement.clearance(a, cast("str", b))
            elif kind == "distance":
                value = measurement.distance(a, cast("str", b))
            elif kind == "bbox":
                triple = measurement.bbox(a)
                value = [triple[0], triple[1], triple[2]]
            elif kind == "volume":
                value = measurement.volume(a)
            elif kind == "mass":
                value = measurement.mass(a)
            elif kind == "sealed":
                value = measurement.sealed(a)
            else:
                value = measurement.genus(a)
        return {
            "value": value,
            "units": _MEASURE_UNITS[kind],
            "detail": {
                "kind": kind,
                "args": selectors,
                "measured": measurement.measured_json(),
                "parts": sorted(sources),
            },
            "resolved_artifact_refs": refs,
        }

    def _measure_sources(
        self,
        selectors: Sequence[str],
        qualified: set[str],
        current: str | None,
        *,
        artifact_ref: str | None,
        project_snapshot_ref: str | None,
        scratch: Path,
    ) -> tuple[dict[str, GeometrySource], list[str]]:
        """Resolve the geometry each selector needs, plus the exact refs used."""
        publisher = self._publisher()
        unqualified = any("/" not in s for s in selectors)
        addressed: set[str] = set(qualified)
        if unqualified and current is not None:
            addressed.add(current)
        if artifact_ref is not None:
            if len(addressed) > 1:
                raise CadOpError(
                    "invalid_params",
                    "artifact_ref selects one part; cross-part selectors need a snapshot",
                )
            name = current or (sorted(addressed)[0] if addressed else None)
            if name is None:
                raise CadOpError("invalid_params", "artifact_ref requires a part context")
            return ({name: self._artifact_geometry(artifact_ref, scratch)}, [artifact_ref])
        if project_snapshot_ref is not None:
            return self._snapshot_sources(project_snapshot_ref, scratch)
        if len(addressed) <= 1:
            name = current or (sorted(addressed)[0] if addressed else None)
            if name is None:
                raise CadOpError("invalid_params", "measure requires a part context")
            result = publisher.current_result(name)
            if result is None or result.artifact_ref is None:
                raise AddressingError(
                    f"part {name!r} has no current successful build to measure",
                    selector=name,
                    candidates=self._layout.part_names(),
                )
            return (
                {name: self._artifact_geometry(result.artifact_ref, scratch)},
                [result.artifact_ref],
            )
        # Cross-part: one coherent project-snapshot manifest.
        try:
            snapshot = publisher.projections.assemble_snapshot(self._layout.part_names())
        except SnapshotRejectedError as exc:
            raise CadOpError(
                "incoherent_project_snapshot",
                exc.message,
                data={"issues": [issue.to_json() for issue in exc.issues]},
            ) from exc
        return self._snapshot_sources(snapshot.ref, scratch)
