"""Measurement facade ``m`` bound to built geometry (§6 / tool_schema §measure).

A :class:`Measurement` resolves geometry selectors via ``addressing.py``
(part-scoped or project-scoped with cross-part ``"<part>/<selector>"``
addressing) and computes values through a :class:`KernelOps` backend. The
production backend (:func:`default_kernel_ops`) binds lazily to
``hephaestus.core.kernel.{metrics,measure}``; tests and non-geometry callers
may inject any :class:`KernelOps` implementation.

Every measurement is appended to a deterministic trace so the checks engine
can report the measured values behind each predicate (§8 ``checks`` —
``{"pass": ..., "measured": ...}``). Facades are cheap; the engine binds a
fresh one per check so traces never mix.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast, final, runtime_checkable

from hephaestus.core.addressing import GeometryIndex, Resolution, resolve_in_project
from hephaestus.core.checks.approx import Triple
from opstore.types import JSONValue

__all__ = [
    "GeometrySource",
    "KernelOps",
    "MappedGeometry",
    "Measurement",
    "MeasurementEntry",
    "default_kernel_ops",
    "part_measurement",
    "project_measurement",
]

#: Density used for ``m.mass`` when neither the call nor the part supplies one.
DEFAULT_DENSITY = 1.0


@runtime_checkable
class GeometrySource(Protocol):
    """Built geometry of one part: its addressing index plus shape lookup.

    ``shape`` maps a :class:`Resolution` (from ``addressing.resolve``) to an
    opaque shape object understood by the bound :class:`KernelOps`. The
    executor provides the production implementation after a build.
    """

    @property
    def index(self) -> GeometryIndex: ...

    def shape(self, resolution: Resolution) -> object: ...


@dataclass(frozen=True)
class MappedGeometry:
    """Simple :class:`GeometrySource`: an index plus a resolution->shape callable."""

    index: GeometryIndex
    resolver: Callable[[Resolution], object]

    def shape(self, resolution: Resolution) -> object:
        return self.resolver(resolution)


class KernelOps(Protocol):
    """Kernel measurement backend over opaque shape objects (all values in mm)."""

    def interference(self, a: object, b: object) -> float: ...

    def clearance(self, a: object, b: object) -> float: ...

    def distance(self, a: object, b: object) -> float: ...

    def mass(self, shape: object, density: float) -> float: ...

    def bbox(self, shape: object) -> tuple[float, float, float]: ...

    def volume(self, shape: object) -> float: ...

    def sealed(self, shape: object) -> bool: ...

    def genus(self, shape: object) -> int: ...


class _MetricsLike(Protocol):
    """Duck-typed view of the kernel ``metrics()`` result (foundation Metrics)."""

    @property
    def bbox_mm(self) -> tuple[float, float, float]: ...

    @property
    def volume_mm3(self) -> float: ...

    @property
    def sealed(self) -> bool: ...

    @property
    def genus(self) -> int: ...


class _LazyKernelOps:
    """Production backend: binds ``hephaestus.core.kernel`` at first call.

    Import happens per call site so this module stays importable (and the
    engine testable) before/without the geometry kernel; kernel ``metrics()``
    is duck-typed on the foundation ``Metrics`` field names.
    """

    @staticmethod
    def _measure_fn(name: str) -> Callable[..., object]:
        module = importlib.import_module("hephaestus.core.kernel.measure")
        return cast("Callable[..., object]", getattr(module, name))

    @staticmethod
    def _metrics(shape: object) -> _MetricsLike:
        module = importlib.import_module("hephaestus.core.kernel.metrics")
        fn = cast("Callable[[object], _MetricsLike]", module.metrics)
        return fn(shape)

    def interference(self, a: object, b: object) -> float:
        return float(cast("float", self._measure_fn("interference")(a, b)))

    def clearance(self, a: object, b: object) -> float:
        return float(cast("float", self._measure_fn("clearance")(a, b)))

    def distance(self, a: object, b: object) -> float:
        return float(cast("float", self._measure_fn("distance")(a, b)))

    def mass(self, shape: object, density: float) -> float:
        return float(cast("float", self._measure_fn("mass")(shape, density)))

    def bbox(self, shape: object) -> tuple[float, float, float]:
        raw = self._metrics(shape).bbox_mm
        return (float(raw[0]), float(raw[1]), float(raw[2]))

    def volume(self, shape: object) -> float:
        return float(self._metrics(shape).volume_mm3)

    def sealed(self, shape: object) -> bool:
        return bool(self._metrics(shape).sealed)

    def genus(self, shape: object) -> int:
        return int(self._metrics(shape).genus)


def default_kernel_ops() -> KernelOps:
    """The production :class:`KernelOps` backed by ``hephaestus.core.kernel``."""
    return _LazyKernelOps()


@dataclass(frozen=True)
class MeasurementEntry:
    """One recorded facade call: operation, selector arguments, computed value."""

    op: str
    args: tuple[str, ...]
    value: JSONValue


@final
class Measurement:
    """The ``m`` facade: selector-addressed measurements over built geometry.

    Selectors follow §7 exactly (``"part"``, tags, labels with ``#k``/``#*``,
    binding names, cross-part ``"<part>/<selector>"``); addressing failures
    raise ``addressing_error`` listing candidates. Construct via
    :func:`part_measurement` or :func:`project_measurement`.
    """

    def __init__(
        self,
        *,
        sources: Mapping[str, GeometrySource],
        current_part: str | None,
        ops: KernelOps | None = None,
        densities: Mapping[str, float] | None = None,
    ) -> None:
        self._sources: dict[str, GeometrySource] = dict(sources)
        self._current = current_part
        self._ops: KernelOps = ops if ops is not None else default_kernel_ops()
        self._densities: dict[str, float] = dict(densities or {})
        self._trace: list[MeasurementEntry] = []

    @property
    def trace(self) -> tuple[MeasurementEntry, ...]:
        """Every measurement made through this facade, in call order."""
        return tuple(self._trace)

    def measured_json(self) -> JSONValue:
        """§8 ``measured`` value: None / the single value / a list of call records."""
        if not self._trace:
            return None
        if len(self._trace) == 1:
            return self._trace[0].value
        return [
            {"op": entry.op, "args": list(entry.args), "value": entry.value}
            for entry in self._trace
        ]

    def _resolve(self, selector: str) -> tuple[str, object]:
        indexes = {name: source.index for name, source in self._sources.items()}
        part, resolution = resolve_in_project(selector, indexes, current_part=self._current)
        return part, self._sources[part].shape(resolution)

    def _record(self, op: str, args: tuple[str, ...], value: JSONValue) -> None:
        self._trace.append(MeasurementEntry(op=op, args=args, value=value))

    def interference(self, a: str, b: str) -> float:
        """Overlap volume (mm^3) between two addressed geometries."""
        _, shape_a = self._resolve(a)
        _, shape_b = self._resolve(b)
        value = float(self._ops.interference(shape_a, shape_b))
        self._record("interference", (a, b), value)
        return value

    def clearance(self, a: str, b: str) -> float:
        """Minimum separation (mm) between two addressed geometries."""
        _, shape_a = self._resolve(a)
        _, shape_b = self._resolve(b)
        value = float(self._ops.clearance(shape_a, shape_b))
        self._record("clearance", (a, b), value)
        return value

    def distance(self, a: str, b: str) -> float:
        """Distance (mm) between two addressed features/topology."""
        _, shape_a = self._resolve(a)
        _, shape_b = self._resolve(b)
        value = float(self._ops.distance(shape_a, shape_b))
        self._record("distance", (a, b), value)
        return value

    def bbox(self, selector: str) -> Triple:
        """Axis-aligned bbox extents (mm) as an elementwise-comparable Triple."""
        _, shape = self._resolve(selector)
        x, y, z = self._ops.bbox(shape)
        value = Triple(x, y, z)
        self._record("bbox", (selector,), [value[0], value[1], value[2]])
        return value

    def volume(self, selector: str) -> float:
        """Volume (mm^3) of the addressed geometry."""
        _, shape = self._resolve(selector)
        value = float(self._ops.volume(shape))
        self._record("volume", (selector,), value)
        return value

    def mass(self, selector: str, density: float | None = None) -> float:
        """Mass (g) at the explicit density, else the part's density, else 1.0 g/cm^3."""
        part, shape = self._resolve(selector)
        effective = density if density is not None else self._densities.get(part, DEFAULT_DENSITY)
        value = float(self._ops.mass(shape, float(effective)))
        self._record("mass", (selector,), value)
        return value

    def sealed(self, selector: str) -> bool:
        """True when the addressed geometry is a sealed (manifold) solid."""
        _, shape = self._resolve(selector)
        value = bool(self._ops.sealed(shape))
        self._record("sealed", (selector,), value)
        return value

    def genus(self, selector: str) -> int:
        """Topological genus of the addressed geometry."""
        _, shape = self._resolve(selector)
        value = int(self._ops.genus(shape))
        self._record("genus", (selector,), value)
        return value


def part_measurement(
    part: str,
    source: GeometrySource,
    *,
    ops: KernelOps | None = None,
    density: float | None = None,
) -> Measurement:
    """Part-scoped facade: selectors resolve inside ``part`` only (§6 CHECKS)."""
    densities = {} if density is None else {part: density}
    return Measurement(sources={part: source}, current_part=part, ops=ops, densities=densities)


def project_measurement(
    sources: Mapping[str, GeometrySource],
    *,
    current_part: str | None = None,
    ops: KernelOps | None = None,
    densities: Mapping[str, float] | None = None,
) -> Measurement:
    """Project-scoped facade: cross-part ``"<part>/<selector>"`` addressing enabled."""
    return Measurement(sources=sources, current_part=current_part, ops=ops, densities=densities)
