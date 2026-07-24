"""BuildResult / CheckReport / Warning / ErrorRecord records.

Mirrors ``script_contract.md`` §8 exactly — every field of the build-result
record, including the full ``error`` object with ``built_through``,
``last_good``, ``last_good_artifact_ref`` and ``hint`` — plus the CheckReport
shape from ``architecture.md`` §3.4 (check-set generation, immutable bundle
ref, per-file hashes, geometry ``project_snapshot_ref``, per-check
pass + measured).

Every record serializes with ``to_json()`` (a JSON-ready dict) and rebuilds
with ``from_json()``. The committed JSON Schema at
``core/schemas/build_result.schema.json`` (draft 2020-12) validates the
``BuildResult.to_json()`` output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeVar, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

BuildStatus = Literal["ok", "failed"]

_T = TypeVar("_T")


def _req(data: Mapping[str, JSONValue], key: str, kind: type[_T]) -> _T:
    """Required field of an exact runtime type (bool never passes as int)."""
    if key not in data:
        raise ValidationError(f"missing required field {key!r}", kind="contract")
    raw = data[key]
    if kind in (int, float) and isinstance(raw, bool):
        raise ValidationError(f"field {key!r}: expected {kind.__name__}, got bool", kind="contract")
    checked: object = raw
    if kind is float and isinstance(raw, int) and not isinstance(raw, bool):
        checked = float(raw)
    if not isinstance(checked, kind):
        raise ValidationError(
            f"field {key!r}: expected {kind.__name__}, got {type(checked).__name__}",
            kind="contract",
        )
    return cast("_T", checked)


def _opt_str(data: Mapping[str, JSONValue], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"field {key!r}: expected str or null", kind="contract")
    return value


def _triple(data: Mapping[str, JSONValue], key: str) -> tuple[float, float, float]:
    values = cast("list[JSONValue]", _req(data, key, list))
    if len(values) != 3 or not all(
        isinstance(v, int | float) and not isinstance(v, bool) for v in values
    ):
        raise ValidationError(f"field {key!r}: expected [x, y, z] numbers", kind="contract")
    x, y, z = (float(cast("int | float", v)) for v in values)
    return (x, y, z)


def _str_map(data: Mapping[str, JSONValue], key: str) -> dict[str, str]:
    raw = cast("dict[str, JSONValue]", _req(data, key, dict))
    out: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(value, str):
            raise ValidationError(f"field {key}[{name!r}]: expected str", kind="contract")
        out[name] = value
    return out


@dataclass(frozen=True)
class InputHashes:
    """§8 ``input_hashes``: the immutable snapshot identity of a build."""

    script: str
    hc_dependencies: str
    part_params: str
    effective_params: str
    toolchain: str

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "script": self.script,
            "hc_dependencies": self.hc_dependencies,
            "part_params": self.part_params,
            "effective_params": self.effective_params,
            "toolchain": self.toolchain,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> InputHashes:
        return cls(
            script=_req(data, "script", str),
            hc_dependencies=_req(data, "hc_dependencies", str),
            part_params=_req(data, "part_params", str),
            effective_params=_req(data, "effective_params", str),
            toolchain=_req(data, "toolchain", str),
        )


@dataclass(frozen=True)
class AuditHashes:
    """§8 ``audit_hashes``: audit-only hashes, never invalidators by themselves."""

    globals_source: str
    project_param_state: str

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "globals_source": self.globals_source,
            "project_param_state": self.project_param_state,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> AuditHashes:
        return cls(
            globals_source=_req(data, "globals_source", str),
            project_param_state=_req(data, "project_param_state", str),
        )


@dataclass(frozen=True)
class Metrics:
    """§8 ``metrics`` for the built compound (kernel-computed)."""

    solids: int
    faces: int
    bbox_mm: tuple[float, float, float]
    volume_mm3: float
    sealed: bool
    genus: int
    edges: int | None = None
    area_mm2: float | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "solids": self.solids,
            "faces": self.faces,
            "bbox_mm": list(self.bbox_mm),
            "volume_mm3": self.volume_mm3,
            "sealed": self.sealed,
            "genus": self.genus,
        }
        if self.edges is not None:
            out["edges"] = self.edges
        if self.area_mm2 is not None:
            out["area_mm2"] = self.area_mm2
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> Metrics:
        edges = data.get("edges")
        area = data.get("area_mm2")
        if edges is not None and (isinstance(edges, bool) or not isinstance(edges, int)):
            raise ValidationError("field 'edges': expected int or absent", kind="contract")
        if area is not None and (isinstance(area, bool) or not isinstance(area, int | float)):
            raise ValidationError("field 'area_mm2': expected number or absent", kind="contract")
        return cls(
            solids=_req(data, "solids", int),
            faces=_req(data, "faces", int),
            bbox_mm=_triple(data, "bbox_mm"),
            volume_mm3=_req(data, "volume_mm3", float),
            sealed=_req(data, "sealed", bool),
            genus=_req(data, "genus", int),
            edges=edges,
            area_mm2=None if area is None else float(area),
        )


@dataclass(frozen=True)
class CheckResult:
    """One CHECKS entry outcome: pass/fail plus the measured value."""

    passed: bool
    measured: JSONValue

    def to_json(self) -> dict[str, JSONValue]:
        return {"pass": self.passed, "measured": self.measured}

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> CheckResult:
        if "measured" not in data:
            raise ValidationError("missing required field 'measured'", kind="contract")
        return cls(passed=_req(data, "pass", bool), measured=data["measured"])


@dataclass(frozen=True)
class GeometryEntry:
    """One row of §8 ``geometries``: exactly the resolvable label namespace."""

    label: str
    solids: int

    def to_json(self) -> dict[str, JSONValue]:
        return {"label": self.label, "solids": self.solids}

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> GeometryEntry:
        return cls(label=_req(data, "label", str), solids=_req(data, "solids", int))


@dataclass(frozen=True)
class Warning:
    """§8 ``warnings`` entry, e.g. kind ``tag_descriptor_changed`` (§5.3)."""

    kind: str
    detail: str
    tag: str | None = None
    evidence: Mapping[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"kind": self.kind}
        if self.tag is not None:
            out["tag"] = self.tag
        out["detail"] = self.detail
        if self.evidence is not None:
            out["evidence"] = dict(self.evidence)
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> Warning:
        evidence_raw = data.get("evidence")
        evidence: Mapping[str, JSONValue] | None = None
        if evidence_raw is not None:
            if not isinstance(evidence_raw, dict):
                raise ValidationError("field 'evidence': expected object", kind="contract")
            evidence = cast("dict[str, JSONValue]", evidence_raw)
        return cls(
            kind=_req(data, "kind", str),
            detail=_req(data, "detail", str),
            tag=_opt_str(data, "tag"),
            evidence=evidence,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Warning):
            return NotImplemented
        return (
            self.kind == other.kind
            and self.detail == other.detail
            and self.tag == other.tag
            and (dict(self.evidence) if self.evidence is not None else None)
            == (dict(other.evidence) if other.evidence is not None else None)
        )

    def __hash__(self) -> int:
        return hash((self.kind, self.detail, self.tag))


@dataclass(frozen=True)
class BuiltThrough:
    """§8 ``error.built_through``: last successfully executed statement."""

    line: int
    statement: str

    def to_json(self) -> dict[str, JSONValue]:
        return {"line": self.line, "statement": self.statement}

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> BuiltThrough:
        return cls(line=_req(data, "line", int), statement=_req(data, "statement", str))


@dataclass(frozen=True)
class LastGood:
    """§8 ``error.last_good``: metrics of the last-good checkpoint geometry."""

    bodies: int
    solids: int
    size_mm: tuple[float, float, float]
    volume_mm3: float
    sealed: bool
    genus: int

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "bodies": self.bodies,
            "solids": self.solids,
            "size_mm": list(self.size_mm),
            "volume_mm3": self.volume_mm3,
            "sealed": self.sealed,
            "genus": self.genus,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> LastGood:
        return cls(
            bodies=_req(data, "bodies", int),
            solids=_req(data, "solids", int),
            size_mm=_triple(data, "size_mm"),
            volume_mm3=_req(data, "volume_mm3", float),
            sealed=_req(data, "sealed", bool),
            genus=_req(data, "genus", int),
        )


@dataclass(frozen=True)
class ErrorRecord:
    """§8 ``error``: the complete failed-build error object."""

    line: int
    col: int
    type: str
    message: str
    frame: tuple[str, ...]
    built_through: BuiltThrough | None
    last_good: LastGood | None
    last_good_artifact_ref: str | None
    hint: str

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "line": self.line,
            "col": self.col,
            "type": self.type,
            "message": self.message,
            "frame": list(self.frame),
            "built_through": None if self.built_through is None else self.built_through.to_json(),
            "last_good": None if self.last_good is None else self.last_good.to_json(),
            "last_good_artifact_ref": self.last_good_artifact_ref,
            "hint": self.hint,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ErrorRecord:
        raw_frame = cast("list[JSONValue]", _req(data, "frame", list))
        frame: list[str] = []
        for item in raw_frame:
            if not isinstance(item, str):
                raise ValidationError("field 'frame': expected list of str", kind="contract")
            frame.append(item)
        built_through_raw = data.get("built_through")
        built_through: BuiltThrough | None = None
        if built_through_raw is not None:
            if not isinstance(built_through_raw, dict):
                raise ValidationError("field 'built_through': expected object", kind="contract")
            built_through = BuiltThrough.from_json(cast("dict[str, JSONValue]", built_through_raw))
        last_good_raw = data.get("last_good")
        last_good: LastGood | None = None
        if last_good_raw is not None:
            if not isinstance(last_good_raw, dict):
                raise ValidationError("field 'last_good': expected object", kind="contract")
            last_good = LastGood.from_json(cast("dict[str, JSONValue]", last_good_raw))
        return cls(
            line=_req(data, "line", int),
            col=_req(data, "col", int),
            type=_req(data, "type", str),
            message=_req(data, "message", str),
            frame=tuple(frame),
            built_through=built_through,
            last_good=last_good,
            last_good_artifact_ref=_opt_str(data, "last_good_artifact_ref"),
            hint=_req(data, "hint", str),
        )


@dataclass(frozen=True)
class BuildResult:
    """§8 build-result record: machine-readable form, every field."""

    part: str
    status: BuildStatus
    current: bool
    artifact_ref: str | None
    project_snapshot_ref: str | None
    input_hashes: InputHashes
    audit_hashes: AuditHashes
    metrics: Metrics | None
    checks: Mapping[str, CheckResult]
    geometries: tuple[GeometryEntry, ...]
    params: Mapping[str, int | float]
    source_map_ref: str | None
    warnings: tuple[Warning, ...]
    error: ErrorRecord | None

    def __post_init__(self) -> None:
        if self.status not in ("ok", "failed"):
            raise ValidationError(f"invalid status: {self.status!r}", kind="contract")
        if self.status == "failed" and self.error is None:
            raise ValidationError("failed build requires an error record", kind="contract")
        if self.status == "ok" and self.error is not None:
            raise ValidationError("ok build must not carry an error record", kind="contract")
        if self.current and self.status != "ok":
            raise ValidationError("only status='ok' builds may be current", kind="contract")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "part": self.part,
            "status": self.status,
            "current": self.current,
            "artifact_ref": self.artifact_ref,
            "project_snapshot_ref": self.project_snapshot_ref,
            "input_hashes": self.input_hashes.to_json(),
            "audit_hashes": self.audit_hashes.to_json(),
            "metrics": None if self.metrics is None else self.metrics.to_json(),
            "checks": {name: check.to_json() for name, check in self.checks.items()},
            "geometries": [entry.to_json() for entry in self.geometries],
            "params": dict(self.params),
            "source_map_ref": self.source_map_ref,
            "warnings": [warning.to_json() for warning in self.warnings],
            "error": None if self.error is None else self.error.to_json(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> BuildResult:
        status = _req(data, "status", str)
        if status not in ("ok", "failed"):
            raise ValidationError(f"invalid status: {status!r}", kind="contract")
        metrics_raw = data.get("metrics")
        metrics: Metrics | None = None
        if metrics_raw is not None:
            if not isinstance(metrics_raw, dict):
                raise ValidationError("field 'metrics': expected object or null", kind="contract")
            metrics = Metrics.from_json(cast("dict[str, JSONValue]", metrics_raw))
        checks_raw = cast("dict[str, JSONValue]", _req(data, "checks", dict))
        checks: dict[str, CheckResult] = {}
        for name, value in checks_raw.items():
            if not isinstance(value, dict):
                raise ValidationError(f"check {name!r}: expected object", kind="contract")
            checks[name] = CheckResult.from_json(cast("dict[str, JSONValue]", value))
        geometries_raw = cast("list[JSONValue]", _req(data, "geometries", list))
        geometries: list[GeometryEntry] = []
        for item in geometries_raw:
            if not isinstance(item, dict):
                raise ValidationError("geometries: expected list of objects", kind="contract")
            geometries.append(GeometryEntry.from_json(cast("dict[str, JSONValue]", item)))
        params_raw = cast("dict[str, JSONValue]", _req(data, "params", dict))
        params: dict[str, int | float] = {}
        for name, value in params_raw.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValidationError(f"param {name!r}: expected number", kind="contract")
            params[name] = value
        warnings_raw = cast("list[JSONValue]", _req(data, "warnings", list))
        warnings: list[Warning] = []
        for item in warnings_raw:
            if not isinstance(item, dict):
                raise ValidationError("warnings: expected list of objects", kind="contract")
            warnings.append(Warning.from_json(cast("dict[str, JSONValue]", item)))
        error_raw = data.get("error")
        error: ErrorRecord | None = None
        if error_raw is not None:
            if not isinstance(error_raw, dict):
                raise ValidationError("field 'error': expected object or null", kind="contract")
            error = ErrorRecord.from_json(cast("dict[str, JSONValue]", error_raw))
        return cls(
            part=_req(data, "part", str),
            status=status,
            current=_req(data, "current", bool),
            artifact_ref=_opt_str(data, "artifact_ref"),
            project_snapshot_ref=_opt_str(data, "project_snapshot_ref"),
            input_hashes=InputHashes.from_json(
                cast("dict[str, JSONValue]", _req(data, "input_hashes", dict))
            ),
            audit_hashes=AuditHashes.from_json(
                cast("dict[str, JSONValue]", _req(data, "audit_hashes", dict))
            ),
            metrics=metrics,
            checks=checks,
            geometries=tuple(geometries),
            params=params,
            source_map_ref=_opt_str(data, "source_map_ref"),
            warnings=tuple(warnings),
            error=error,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BuildResult):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __hash__(self) -> int:
        return hash((self.part, self.status, self.artifact_ref))


@dataclass(frozen=True)
class CheckReport:
    """architecture §3.4 check report: one immutable check-set generation run."""

    part: str
    check_set_generation: int
    check_bundle_ref: str
    file_hashes: Mapping[str, str] = field(default_factory=dict[str, str])
    project_snapshot_ref: str | None = None
    checks: Mapping[str, CheckResult] = field(default_factory=dict[str, "CheckResult"])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "part": self.part,
            "check_set_generation": self.check_set_generation,
            "check_bundle_ref": self.check_bundle_ref,
            "file_hashes": dict(self.file_hashes),
            "project_snapshot_ref": self.project_snapshot_ref,
            "checks": {name: check.to_json() for name, check in self.checks.items()},
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> CheckReport:
        checks_raw = cast("dict[str, JSONValue]", _req(data, "checks", dict))
        checks: dict[str, CheckResult] = {}
        for name, value in checks_raw.items():
            if not isinstance(value, dict):
                raise ValidationError(f"check {name!r}: expected object", kind="contract")
            checks[name] = CheckResult.from_json(cast("dict[str, JSONValue]", value))
        return cls(
            part=_req(data, "part", str),
            check_set_generation=_req(data, "check_set_generation", int),
            check_bundle_ref=_req(data, "check_bundle_ref", str),
            file_hashes=_str_map(data, "file_hashes"),
            project_snapshot_ref=_opt_str(data, "project_snapshot_ref"),
            checks=checks,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CheckReport):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __hash__(self) -> int:
        return hash((self.part, self.check_set_generation, self.check_bundle_ref))


__all__: Sequence[str] = (
    "AuditHashes",
    "BuildResult",
    "BuildStatus",
    "BuiltThrough",
    "CheckReport",
    "CheckResult",
    "ErrorRecord",
    "GeometryEntry",
    "InputHashes",
    "LastGood",
    "Metrics",
    "Warning",
)
