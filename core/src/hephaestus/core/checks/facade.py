"""Measurement facade ``m`` bound to built geometry (§6 / tool_schema §measure).

A :class:`Measurement` resolves geometry selectors via ``addressing.py``
(part-scoped or project-scoped with cross-part ``"<part>/<selector>"``
addressing) and computes values through a :class:`KernelOps` backend. The
production backend (:func:`default_kernel_ops`) binds lazily to
``hephaestus.geom.{metrics,measure}``; tests and non-geometry callers
may inject any :class:`KernelOps` implementation.

Every measurement is appended to a deterministic trace so the checks engine
can report the measured values behind each predicate (§8 ``checks`` —
``{"pass": ..., "measured": ...}``). Facades are cheap; the engine binds a
fresh one per check so traces never mix.

``m.diff`` (``COMPARE.md`` §2) is the one call whose second operand is not a
selector: it names a whole comparison *target* — another part, or a file under
``imports/``. Import targets are resolved by an injected callable rather than by
this module, because who may read ``imports/`` and under what confinement is a
project question, not a measurement one.

``m.at_pose`` / ``m.sweep`` (``KINEMATICS.md`` §4, the ``script_contract.md``
§6 amendment) are the two project-scope motion read surfaces, on exactly the
``m.diff`` discriminated-facade mechanism: a posed-context factory and a
sweep-result resolver are injected by the caller that owns the run — they
resolve against the run's FROZEN snapshot and motion generations
(``KINEMATICS.md`` §2, last bullet), which is a project question this module
cannot answer — and a facade carrying neither (every part-scope facade, per
the scope rule: part scripts declare no joints) refuses each call by name AT
EVALUATION, never by inspecting predicate bodies.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, final, runtime_checkable

from hephaestus.core.addressing import GeometryIndex, Resolution, resolve_in_project
from hephaestus.core.checks.approx import Triple
from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

__all__ = [
    "ALIGN_MODES",
    "IMPORT_TARGET_PREFIX",
    "PART_TARGET_PREFIX",
    "DiffFacts",
    "GeometrySource",
    "ImportResolver",
    "KernelOps",
    "MappedGeometry",
    "Measurement",
    "MeasurementEntry",
    "PosedContextFactory",
    "PosedMeasurement",
    "PosedPlacement",
    "SweepFacts",
    "SweepResolver",
    "default_kernel_ops",
    "part_measurement",
    "project_measurement",
]

#: ``COMPARE.md`` §1 alignment modes, mirrored here so the facade can refuse an
#: unknown one without importing the geometry layer.
ALIGN_MODES: tuple[str, ...] = ("as_posed", "principal")

#: ``m.diff`` target naming another part of this project.
PART_TARGET_PREFIX = "part:"

#: ``m.diff`` target naming a file beneath the project's ``imports/``.
IMPORT_TARGET_PREFIX = "import:"

#: Resolves an ``imports/``-relative path to a shape the bound ops understand.
ImportResolver = Callable[[str], object]

#: Resolves a declared motion-check id to its §4 result record (a
#: ``SweepResult.to_json`` mapping), evaluated against the run's frozen
#: snapshot. Injected like :data:`ImportResolver`; a named refusal it raises
#: (unknown id, withdrawn entry, motion timeout) is the predicate's outcome.
SweepResolver = Callable[[str], Mapping[str, JSONValue]]

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


@runtime_checkable
class PosedPlacement(Protocol):
    """Rigid placement of every part at one resolved pose (``KINEMATICS.md`` §4).

    ``place`` maps a part's resolved shape to a *placed copy* at the pose's
    forward-kinematics transform (a static part comes back at identity). The
    production implementation lives with the engine's motion machinery — the
    facade never decides where geometry sits, it only measures what the
    placement hands back.
    """

    @property
    def pose_id(self) -> str: ...

    def place(self, part: str, shape: object) -> object: ...


#: Resolves a declared pose id to a :class:`PosedPlacement` over the run's
#: frozen snapshot and motion state (``KINEMATICS.md`` §2, last bullet). A
#: named refusal it raises (unknown pose, orphaned pose, unresolvable joint)
#: is the predicate's outcome, exactly like an import-target refusal.
PosedContextFactory = Callable[[str], PosedPlacement]


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

    def diff(self, a: object, b: object, align: str) -> Mapping[str, JSONValue]: ...


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
    """Production backend: binds ``hephaestus.geom`` at first call.

    Import happens per call site so this module stays importable (and the
    engine testable) before/without the geometry kernel; kernel ``metrics()``
    is duck-typed on the foundation ``Metrics`` field names.
    """

    @staticmethod
    def _measure_fn(name: str) -> Callable[..., object]:
        module = importlib.import_module("hephaestus.geom.measure")
        return cast("Callable[..., object]", getattr(module, name))

    @staticmethod
    def _metrics(shape: object) -> _MetricsLike:
        module = importlib.import_module("hephaestus.geom.metrics")
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

    def diff(self, a: object, b: object, align: str) -> Mapping[str, JSONValue]:
        import dataclasses

        module = importlib.import_module("hephaestus.geom.compare")
        fn = cast("Callable[..., object]", module.solid_diff)
        # ``SolidDiff`` and everything it nests are frozen dataclasses, so
        # ``asdict`` IS the JSON shape — the facade never re-derives field names
        # and can therefore never drift from the record COMPARE.md §1 defines.
        return cast(
            "Mapping[str, JSONValue]", dataclasses.asdict(cast("Any", fn(a, b, align=align)))
        )


def default_kernel_ops() -> KernelOps:
    """The production :class:`KernelOps` backed by ``hephaestus.geom``."""
    return _LazyKernelOps()


# --------------------------------------------------------------------------
# diff facts (COMPARE.md §2: the CHECKS view of one SolidDiff)


def _number(raw: Mapping[str, JSONValue], key: str) -> float:
    value = raw.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _count(raw: Mapping[str, JSONValue], key: str) -> int:
    value = raw.get(key)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _section(raw: Mapping[str, JSONValue], key: str) -> Mapping[str, JSONValue]:
    value = raw.get(key)
    return cast("Mapping[str, JSONValue]", value) if isinstance(value, dict) else {}


def _triple(raw: Mapping[str, JSONValue], key: str) -> Triple:
    value = raw.get(key)
    if isinstance(value, list | tuple) and len(cast("list[JSONValue]", value)) == 3:
        items = list(cast("list[JSONValue]", value))
        return Triple(*(float(cast("float", item)) for item in items))
    return Triple(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class DiffFacts:
    """One ``SolidDiff`` as a CHECKS predicate reads it (``COMPARE.md`` §2).

    Flattened on purpose: an acceptance check asserts a *number* against a named
    tolerance, so ``m.diff("bracket", "import:target.step").iou >= 0.995`` must
    reach ``iou`` without walking the record. Nothing is dropped — :attr:`raw`
    is the whole nested ``SolidDiff`` (volume/surface/topology, both censuses),
    and it is what the check report records as the measured value.

    Facts, never a verdict: ``align`` says which question these numbers answer,
    and ``a_samples``/``b_samples`` say how coarse the surface figures are, so a
    predicate can refuse to trust a chamfer computed from four points.
    """

    align: str
    iou: float
    common_mm3: float
    a_only_mm3: float
    b_only_mm3: float
    chamfer_mm: float
    max_deviation_mm: float
    a_to_b_mean_mm: float
    b_to_a_mean_mm: float
    a_samples: int
    b_samples: int
    solids_delta: int
    faces_delta: int
    edges_delta: int
    genus_delta: int
    sealed_changed: bool
    a_volume_mm3: float
    b_volume_mm3: float
    a_bbox_mm: Triple
    b_bbox_mm: Triple
    raw: Mapping[str, JSONValue]

    @classmethod
    def from_json(cls, raw: Mapping[str, JSONValue]) -> DiffFacts:
        """Flatten a ``dataclasses.asdict(SolidDiff)`` mapping."""
        volume = _section(raw, "volume")
        surface = _section(raw, "surface")
        topology = _section(raw, "topology")
        align = raw.get("align")
        return cls(
            align=align if isinstance(align, str) else "as_posed",
            iou=_number(volume, "iou"),
            common_mm3=_number(volume, "common_mm3"),
            a_only_mm3=_number(volume, "a_only_mm3"),
            b_only_mm3=_number(volume, "b_only_mm3"),
            chamfer_mm=_number(surface, "chamfer_mm"),
            max_deviation_mm=_number(surface, "max_deviation_mm"),
            a_to_b_mean_mm=_number(surface, "a_to_b_mean_mm"),
            b_to_a_mean_mm=_number(surface, "b_to_a_mean_mm"),
            a_samples=_count(surface, "a_samples"),
            b_samples=_count(surface, "b_samples"),
            solids_delta=_count(topology, "solids_delta"),
            faces_delta=_count(topology, "faces_delta"),
            edges_delta=_count(topology, "edges_delta"),
            genus_delta=_count(topology, "genus_delta"),
            sealed_changed=bool(topology.get("sealed_changed")),
            a_volume_mm3=_number(raw, "a_volume_mm3"),
            b_volume_mm3=_number(raw, "b_volume_mm3"),
            a_bbox_mm=_triple(raw, "a_bbox_mm"),
            b_bbox_mm=_triple(raw, "b_bbox_mm"),
            raw=dict(raw),
        )


# --------------------------------------------------------------------------
# sweep facts (KINEMATICS.md §4: the CHECKS view of one motion-check result)


@dataclass(frozen=True)
class SweepFacts:
    """One motion-check result as a CHECKS predicate reads it (§4 ``m.sweep``).

    Flattened on the :class:`DiffFacts` rule: a predicate asserts
    ``m.sweep("mc-elbow-clear").verdict == "holds_at_samples"`` or reads the
    worst sample's number without walking the record. ``verdict`` is a
    spelling from the §4 closed set — facts, never re-decided here — and
    :attr:`raw` is the whole ``SweepResult`` record, which is what the check
    report records as the measured value.
    """

    id: str
    kind: str
    verdict: str
    samples_evaluated: int
    grid_total: int
    samples_per_axis: int
    unit: str
    worst_values: Mapping[str, float]
    worst_measured: float | None
    min_mm: float | None
    tol_mm: float | None
    miss_mm: float | None
    target_point_mm: Triple | None
    reason: str | None
    detail: str | None
    raw: Mapping[str, JSONValue]

    @classmethod
    def from_json(cls, raw: Mapping[str, JSONValue]) -> SweepFacts:
        """Flatten a ``SweepResult.to_json`` mapping."""
        worst = _section(raw, "worst")
        worst_values: dict[str, float] = {}
        for name, value in _section(worst, "values").items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                worst_values[name] = float(value)
        target_raw = raw.get("target_point_mm")
        target: Triple | None = None
        if isinstance(target_raw, list) and len(cast("list[JSONValue]", target_raw)) == 3:
            items = cast("list[JSONValue]", target_raw)
            if all(isinstance(item, int | float) and not isinstance(item, bool) for item in items):
                target = Triple(*(float(cast("float", item)) for item in items))
        return cls(
            id=str(raw.get("id", "")),
            kind=str(raw.get("kind", "")),
            verdict=str(raw.get("verdict", "")),
            samples_evaluated=_count(raw, "samples_evaluated"),
            grid_total=_count(raw, "grid_total"),
            samples_per_axis=_count(raw, "samples_per_axis"),
            unit=str(raw.get("unit", "")),
            worst_values=worst_values,
            worst_measured=_opt_number(worst, "measured"),
            min_mm=_opt_number(raw, "min_mm"),
            tol_mm=_opt_number(raw, "tol_mm"),
            miss_mm=_opt_number(raw, "miss_mm"),
            target_point_mm=target,
            reason=_opt_str_field(raw, "reason"),
            detail=_opt_str_field(raw, "detail"),
            raw=dict(raw),
        )


def _opt_number(raw: Mapping[str, JSONValue], key: str) -> float | None:
    value = raw.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _opt_str_field(raw: Mapping[str, JSONValue], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


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
        imports: ImportResolver | None = None,
        at_pose: PosedContextFactory | None = None,
        sweep: SweepResolver | None = None,
    ) -> None:
        self._sources: dict[str, GeometrySource] = dict(sources)
        self._current = current_part
        self._ops: KernelOps = ops if ops is not None else default_kernel_ops()
        self._densities: dict[str, float] = dict(densities or {})
        self._imports = imports
        self._at_pose = at_pose
        self._sweep = sweep
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

    def _motion_scope_refusal(self, call: str) -> ValidationError:
        """The §4 scope refusal, at evaluation — the ``m.diff`` import precedent.

        ``KINEMATICS.md`` §4: enforcement sits where the existing scope rules
        live — this facade simply was not handed the motion resolvers, so the
        call cannot be answered here, and saying so by name is the whole
        mechanism. No load-time pass over predicate bodies exists anywhere.
        """
        return ValidationError(
            f"{call} cannot be resolved here: this measurement is not bound to a "
            "project run's frozen motion state — at_pose and sweep are project-scope "
            "read surfaces, and part-scope CHECKS may not call them "
            "(script_contract.md §6, KINEMATICS.md §4)",
            kind="contract",
        )

    def at_pose(self, pose_id: str) -> PosedMeasurement:
        """Posed measurement context at one declared pose (``KINEMATICS.md`` §4).

        Project scope only: the returned context's ``interference`` /
        ``clearance`` / ``distance`` measure the posed configuration — each
        addressed shape placed by the pose's forward-kinematics transform over
        the run's frozen snapshot. A facade without the injected posed-context
        factory (every part-scope facade) refuses by name at evaluation.
        """
        if self._at_pose is None:
            raise self._motion_scope_refusal(f"m.at_pose({pose_id!r})")
        return PosedMeasurement(self, self._at_pose(pose_id))

    def sweep(self, check_id: str) -> SweepFacts:
        """One declared motion check's result record (``KINEMATICS.md`` §4).

        Project scope only, same rule as :meth:`at_pose`. The facts, never a
        verdict of this facade's own: the record's ``verdict`` comes from the
        §4 closed set as the engine decided it, and the whole record is what
        the check report records as the measured value.
        """
        if self._sweep is None:
            raise self._motion_scope_refusal(f"m.sweep({check_id!r})")
        raw = self._sweep(check_id)
        facts = SweepFacts.from_json(raw)
        self._record("sweep", (check_id,), cast("JSONValue", dict(raw)))
        return facts

    def _resolve_target(self, target: str) -> object:
        """The shape a ``m.diff`` target names (``COMPARE.md`` §2)."""
        if target.startswith(PART_TARGET_PREFIX):
            name = target[len(PART_TARGET_PREFIX) :]
            if not name:
                raise ValidationError(f"diff target {target!r} names no part", kind="contract")
            _, shape = self._resolve(f"{name}/part")
            return shape
        if target.startswith(IMPORT_TARGET_PREFIX):
            path = target[len(IMPORT_TARGET_PREFIX) :]
            if not path:
                raise ValidationError(
                    f"diff target {target!r} names no imports/ file", kind="contract"
                )
            if self._imports is None:
                raise ValidationError(
                    f"diff target {target!r} cannot be resolved here: this measurement is "
                    "not bound to a project's imports/ (COMPARE.md §2)",
                    kind="contract",
                )
            return self._imports(path)
        raise ValidationError(
            f"diff target {target!r} must be {PART_TARGET_PREFIX!r}<part> or "
            f"{IMPORT_TARGET_PREFIX!r}<path under imports/> (COMPARE.md §2)",
            kind="contract",
        )

    def diff(self, a: str, target: str, align: str = "as_posed") -> DiffFacts:
        """Solid-diff facts between an addressed geometry and a target.

        ``COMPARE.md`` §1-§2: the facts, never a verdict — the threshold is the
        predicate's, which is exactly why a check reads like
        ``m.diff("bracket", "import:target.step").iou >= 0.995``. ``align``
        defaults to ``"as_posed"`` (a moved part *is* different); pass
        ``"principal"`` to compare canonical poses instead. The measured value
        recorded for the report is the whole ``SolidDiff``, so the evidence
        behind a failing check is every number, not the one that was read.
        """
        if align not in ALIGN_MODES:
            raise ValidationError(
                f"diff align must be one of {', '.join(ALIGN_MODES)}, got {align!r}",
                kind="contract",
            )
        _, shape_a = self._resolve(a)
        shape_b = self._resolve_target(target)
        raw = self._ops.diff(shape_a, shape_b, align)
        facts = DiffFacts.from_json(raw)
        self._record("diff", (a, target, align), cast("JSONValue", dict(raw)))
        return facts


@final
class PosedMeasurement:
    """``m.at_pose(pose_id)``: the posed configuration, measured (§4).

    Deliberately three calls — ``interference`` / ``clearance`` / ``distance``
    are exactly what ``KINEMATICS.md`` §4 grants the posed context, and a
    closed surface cannot silently grow a posed ``mass`` nobody specified.
    Selectors resolve through the parent facade (same addressing, same frozen
    sources); each resolved shape is then placed by the pose's transform
    before the kernel measures, and every call lands in the PARENT facade's
    trace (op ``at_pose.<call>``, the pose id in its args) so the report
    shows which configuration each number was taken at.
    """

    def __init__(self, measurement: Measurement, placement: PosedPlacement) -> None:
        self._m = measurement
        self._placement = placement

    @property
    def pose_id(self) -> str:
        return self._placement.pose_id

    def _posed(self, selector: str) -> object:
        part, shape = self._m._resolve(selector)  # pyright: ignore[reportPrivateUsage]
        return self._placement.place(part, shape)

    def _measure(
        self, op: str, a: str, b: str, compute: Callable[[object, object], float]
    ) -> float:
        value = float(compute(self._posed(a), self._posed(b)))
        self._m._record(  # pyright: ignore[reportPrivateUsage]
            f"at_pose.{op}", (self.pose_id, a, b), value
        )
        return value

    def interference(self, a: str, b: str) -> float:
        """Overlap volume (mm^3) between two geometries at this pose."""
        return self._measure("interference", a, b, self._m._ops.interference)  # pyright: ignore[reportPrivateUsage]

    def clearance(self, a: str, b: str) -> float:
        """Minimum separation (mm) between two geometries at this pose."""
        return self._measure("clearance", a, b, self._m._ops.clearance)  # pyright: ignore[reportPrivateUsage]

    def distance(self, a: str, b: str) -> float:
        """Distance (mm) between two addressed geometries at this pose."""
        return self._measure("distance", a, b, self._m._ops.distance)  # pyright: ignore[reportPrivateUsage]


def part_measurement(
    part: str,
    source: GeometrySource,
    *,
    ops: KernelOps | None = None,
    density: float | None = None,
    imports: ImportResolver | None = None,
) -> Measurement:
    """Part-scoped facade: selectors resolve inside ``part`` only (§6 CHECKS)."""
    densities = {} if density is None else {part: density}
    return Measurement(
        sources={part: source},
        current_part=part,
        ops=ops,
        densities=densities,
        imports=imports,
    )


def project_measurement(
    sources: Mapping[str, GeometrySource],
    *,
    current_part: str | None = None,
    ops: KernelOps | None = None,
    densities: Mapping[str, float] | None = None,
    imports: ImportResolver | None = None,
    at_pose: PosedContextFactory | None = None,
    sweep: SweepResolver | None = None,
) -> Measurement:
    """Project-scoped facade: cross-part ``"<part>/<selector>"`` addressing enabled.

    ``at_pose`` / ``sweep`` are the §4 motion read surfaces, injected by the
    caller that owns the run's frozen snapshot (``KINEMATICS.md`` §2, last
    bullet). Only this constructor accepts them: :func:`part_measurement`
    deliberately has no such parameters, which IS the scope enforcement.
    """
    return Measurement(
        sources=sources,
        current_part=current_part,
        ops=ops,
        densities=densities,
        imports=imports,
        at_pose=at_pose,
        sweep=sweep,
    )
