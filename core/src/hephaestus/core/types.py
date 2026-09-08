"""BuildResult / CheckReport / Warning / ErrorRecord records.

Mirrors ``script_contract.md`` §8 exactly — every field of the build-result
record, including the full ``error`` object with ``built_through``,
``last_good``, ``last_good_artifact_ref`` and ``hint``, plus the incremental
executor's per-statement ``checkpoints`` (architecture §3.1) — and the
CheckReport shape from ``architecture.md`` §3.4 (check-set generation,
immutable bundle ref, per-file hashes, geometry ``project_snapshot_ref``,
per-check pass + measured).

Every record serializes with ``to_json()`` (a JSON-ready dict) and rebuilds
with ``from_json()``. The committed JSON Schema at
``core/schemas/build_result.schema.json`` (draft 2020-12) validates the
``BuildResult.to_json()`` output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, TypeVar, cast, get_args

from hephaestus.core.errors import ValidationError
from hephaestus.core.params import Param, params_declaration_json
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


def _str_tuple(data: Mapping[str, JSONValue], key: str) -> tuple[str, ...]:
    raw = cast("list[JSONValue]", _req(data, key, list))
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValidationError(f"field {key!r}: expected list of str", kind="contract")
        out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class InputHashes:
    """§8 ``input_hashes``: the immutable snapshot identity of a build."""

    script: str
    hc_dependencies: str
    part_params: str
    effective_params: str
    toolchain: str
    #: ``INGEST.md`` §1: ``{path relative to imports/: sha256}`` for every STEP
    #: file this build imported. A changed file is a changed input — it
    #: invalidates the current pointer exactly as an edited script does.
    imports: Mapping[str, str] = field(default_factory=dict[str, str])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "script": self.script,
            "hc_dependencies": self.hc_dependencies,
            "part_params": self.part_params,
            "effective_params": self.effective_params,
            "toolchain": self.toolchain,
            "imports": {name: self.imports[name] for name in sorted(self.imports)},
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> InputHashes:
        # ``imports`` is absent from records written before Stage 8A; an empty
        # map is the honest reading of "this build imported nothing".
        imports = _str_map(data, "imports") if "imports" in data else {}
        return cls(
            script=_req(data, "script", str),
            hc_dependencies=_req(data, "hc_dependencies", str),
            part_params=_req(data, "part_params", str),
            effective_params=_req(data, "effective_params", str),
            toolchain=_req(data, "toolchain", str),
            imports=imports,
        )


#: The closed vocabulary of build inputs a *reader* can re-compare — the
#: :class:`InputHashes` legs whose live value can move under an already
#: published build. Named once because three surfaces have to mean the same five
#: words by it: ``Publisher.freshness`` produces them, ``build_projection``
#: serves them as ``stale_inputs``, and the composer's context block reads them
#: back to the model (audit-2026-09-04 B-5). A ``Literal`` rather than a bare
#: ``str`` so a sixth name cannot arrive by typo — the closed set is checked
#: where a mismatch is *constructed*, not where it is rendered.
#:
#: ``effective_params`` is deliberately absent. An override is an input to the
#: build that *ran*, recorded on the record; changing one asks for a new build
#: rather than making an old one untrue, and publication's own revalidation does
#: not compare it either.
BuildInput = Literal["script", "toolchain", "part_params", "imports", "hc_dependencies"]

#: :data:`BuildInput`'s members as a value, in comparison order.
BUILD_INPUTS: Final[tuple[BuildInput, ...]] = get_args(BuildInput)


#: The closed unit set a mesh or point-cloud import must declare
#: (``MESH_INGEST.md`` §1.3). STL, PLY, OBJ, OFF and XYZ carry no unit, so the
#: declaration is the only honest source: "300 units across so probably mm" is
#: a guess dressed as a measurement, and a limb scan is exactly the size where
#: the guess is plausible and wrong.
#:
#: **It lives here rather than in** :mod:`hephaestus.geom.mesh` **because of
#: who reads it.** ``heph import add --units`` and ``heph scan --units`` need
#: the four strings to *register* their parsers — on every ``heph``
#: invocation, before any verb runs — and reaching them through the geometry
#: package imported build123d, OCP, scikit-learn, scipy and sympy for a
#: four-string tuple: 1.7 s of the CLI's 2.9 s startup (ledger J-cli-startup-5,
#: root cause RC-2). This module is already on the geometry package's
#: dependency allowlist and costs about 8 ms, and
#: :mod:`hephaestus.geom.mesh` re-exports both names, so every existing import
#: path still resolves. Hard-coding the four values at the CLI instead would
#: have forked ``MESH_INGEST.md``'s normative unit set into a second literal
#: with nothing pinning them together — which is exactly the hazard
#: ``hephaestus.geom.__init__``'s docstring warns about for the solver.
MeshUnits = Literal["mm", "cm", "m", "in"]

#: :data:`MeshUnits`'s members as a value, in declaration order (the order the
#: ``--units`` choices and every refusal sentence list them in). Derived from
#: the ``Literal`` rather than transcribed beside it, on the
#: :data:`BUILD_INPUTS` precedent above: the tuple and the type cannot drift.
MESH_UNITS: Final[tuple[MeshUnits, ...]] = get_args(MeshUnits)


@dataclass(frozen=True)
class BuildFreshness:
    """Whether a published build's recorded inputs still match the live ones.

    A **read-time** fact, recomputed on every read, and deliberately NOT the
    same thing as :attr:`BuildResult.current`. ``current`` is publication state
    (``architecture.md`` §3.5): this build won the part's current pointer, and
    that stays true no matter what is edited afterwards. Freshness is the other
    half a reader needs and no record could carry — whether the inputs the build
    was computed from are still the inputs on disk.

    Conflating the two is audit-2026-09-04 B-5: ``GET /parts/{part}/build``
    served ``current: true`` for a build whose script had since been edited, and
    the header chip rendered that as the literal words "up to date".

    :attr:`changed_inputs` is a subset of :data:`BUILD_INPUTS` in that fixed
    order — the comparison order, not an alphabetical one, so ``script`` (the
    leg that subsumes ``part_params``) is always named first.
    """

    #: The inputs whose live value no longer matches the recorded hash. Empty
    #: means fresh; there is no third state, because a freshness that could not
    #: be computed is reported as the ABSENCE of a ``BuildFreshness`` rather
    #: than as an empty one (§6.3: silence must not read as a pass).
    changed_inputs: tuple[BuildInput, ...] = ()
    #: The live script hash the comparison read, or ``None`` when the part file
    #: is gone. Carried because one other reader needs exactly the hash this
    #: comparison saw: ``GET /parts/{part}/build`` surfaces a recorded failure
    #: only when that failure is about the script as it stands NOW, and a second
    #: read of the file could answer a different question than this one did.
    live_script_hash: str | None = None

    @property
    def fresh(self) -> bool:
        """``True`` when every recorded input still matches the live one."""
        return not self.changed_inputs


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
class StatementCheckpoint:
    """One incremental-executor per-statement checkpoint (architecture §3.1).

    The worker records these after every top-level statement that completed:
    index, source span, names bound, and shape-binding names. ``statement`` is
    the verbatim source slice so a Timeline (or a repair loop) can name the
    stop without slicing the script itself. ``artifact_ref`` is set only when
    publication minted a blob for that stop — today that is the last-good
    checkpoint of a failed build, never an invented per-statement BRep.
    """

    index: int
    line: int
    statement: str
    span: tuple[int, int, int, int]
    bound: tuple[str, ...]
    shapes: tuple[str, ...]
    artifact_ref: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "index": self.index,
            "line": self.line,
            "statement": self.statement,
            "span": list(self.span),
            "bound": list(self.bound),
            "shapes": list(self.shapes),
            "artifact_ref": self.artifact_ref,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> StatementCheckpoint:
        span_raw = cast("list[JSONValue]", _req(data, "span", list))
        if len(span_raw) != 4 or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in span_raw
        ):
            raise ValidationError("field 'span': expected four integers", kind="contract")
        span = cast("tuple[int, int, int, int]", tuple(span_raw))
        return cls(
            index=_req(data, "index", int),
            line=_req(data, "line", int),
            statement=_req(data, "statement", str),
            span=span,
            bound=_str_tuple(data, "bound"),
            shapes=_str_tuple(data, "shapes"),
            artifact_ref=_opt_str(data, "artifact_ref"),
        )


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
    #: §5.2 manufacturing metadata as the WORKER evaluated it — the runtime
    #: truth, so an f-string over ``hc`` values is carried exactly like a
    #: literal. Empty map on records written before 2026-08-03 (the worker
    #: always computed this; the record used to drop it, which forced every
    #: downstream reader into literal-only static script parsing — the
    #: nest-gusset "missing" blank_size the model had in fact written).
    metadata: Mapping[str, str] = field(default_factory=dict[str, str])
    #: Incremental-executor per-statement checkpoints. Empty on records written
    #: before this field existed — the worker always recorded them; the §8
    #: record used to drop them, which left ``GET /parts/{part}/build`` unable
    #: to name the stops the Timeline is a projection of.
    checkpoints: tuple[StatementCheckpoint, ...] = ()
    #: Every ``CHECKS`` name the worker *registered*, sorted — which is not the
    #: same set as :attr:`checks`'s keys: a declared check that failed to
    #: register leaves no result, so an empty ``checks`` map alone cannot say
    #: whether the part declares none or declares some that did not run
    #: (audit-2026-09-04 J-cli-startup-9, root cause RC-6). The worker has
    #: always emitted ``check_names``; the §8 record used to drop it, which is
    #: the third time this exact omission has been repaired here — see
    #: :attr:`metadata` and :attr:`checkpoints` above.
    #:
    #: ``()`` on records written before this field existed, and on a build that
    #: registered none. The two are distinguished where it matters — by
    #: :meth:`~hephaestus.core.project_store.publication.Publisher.recorded_check_names`,
    #: which asks whether the stored document carries the key at all — because
    #: the one caller that acts on "this part declares no checks"
    #: (``run_checks``'s no-rebuild fast path) must not act on a record that
    #: never claimed it.
    check_names: tuple[str, ...] = ()
    #: The part's ``PARAMS`` declaration as the worker evaluated it — bounds,
    #: defaults, steps and docs, not just the *hash* of them that
    #: :attr:`InputHashes.part_params` keeps. Without it no reader can answer
    #: "what are this part's bounds?" from the current build, and
    #: ``GET /parts/{part}/params`` fell back to a multi-second sandboxed
    #: rebuild to recover a dict the worker had already computed and handed
    #: back (RC-6, ledger J-cli-startup-7). Serialized through
    #: :func:`~hephaestus.core.params.params_declaration_json`, the SAME
    #: canonical form :attr:`InputHashes.part_params` hashes — a second JSON
    #: shape for one declaration inside one record is the drift this field
    #: exists to end. Empty on records written before it existed.
    params_declaration: Mapping[str, Param] = field(default_factory=dict[str, "Param"])

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
            "metadata": dict(self.metadata),
            "checkpoints": [checkpoint.to_json() for checkpoint in self.checkpoints],
            "check_names": list(self.check_names),
            "params_declaration": params_declaration_json(self.params_declaration),
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
            # Absent from pre-2026-08-03 records; {} is the honest reading.
            metadata=_str_map(data, "metadata") if "metadata" in data else {},
            # Absent from records written before the HTTP Timeline projection;
            # () is the honest reading of "this build named no statement stops".
            checkpoints=_checkpoints(data) if "checkpoints" in data else (),
            # Absent on a record written before the field existed; `()` is the
            # honest reading, on the `metadata`/`checkpoints` precedent above.
            check_names=_str_tuple(data, "check_names") if "check_names" in data else (),
            params_declaration=_params_declaration(data),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BuildResult):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __hash__(self) -> int:
        return hash((self.part, self.status, self.artifact_ref))


#: What a check report is *about*. The record was defined for the part-scope
#: case and grew a project scope that had nowhere to put its subject, so both
#: project-scope callers satisfied the mandatory ``part`` field by passing the
#: PROJECT name — a value that is not a part, and that reading refuses
#: (audit-2026-09-04 J-agent-results-9).
CheckScope = Literal["part", "project"]


@dataclass(frozen=True)
class CheckReport:
    """architecture §3.4 check report: one immutable check-set generation run.

    The subject is scope-aware: :attr:`scope` discriminates, :attr:`part` is
    the part a part-scope run measured (``None`` in project scope, never the
    project name wearing a part's field), and :attr:`project` is the project
    both scopes belong to — genuinely useful provenance, in its own field.
    """

    #: ``None`` in project scope. Kept first, and still positional, so every
    #: existing construction site keeps working.
    part: str | None
    check_set_generation: int
    check_bundle_ref: str
    file_hashes: Mapping[str, str] = field(default_factory=dict[str, str])
    project_snapshot_ref: str | None = None
    #: Defaults to ``"part"``, which is what a record written before this field
    #: existed means: project scope did not record a scope, but neither did it
    #: exist as a *declared* one, and every stored report must still load.
    scope: CheckScope = "part"
    #: The project the run belongs to, in either scope. ``None`` on a record
    #: written before this field existed.
    project: str | None = None
    #: The frozen motion-state generations a run that resolved motion state
    #: measured against (``KINEMATICS.md`` §4: joint/pose/motion-check set
    #: generations, recorded alongside ``project_snapshot_ref`` so motion
    #: evidence is replayable like every other kind). ``None`` when no check
    #: in the run touched ``m.at_pose``/``m.sweep``.
    motion_generations: Mapping[str, int] | None = None
    checks: Mapping[str, CheckResult] = field(default_factory=dict[str, "CheckResult"])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "scope": self.scope,
            "part": self.part,
            "project": self.project,
            "check_set_generation": self.check_set_generation,
            "check_bundle_ref": self.check_bundle_ref,
            "file_hashes": dict(self.file_hashes),
            "project_snapshot_ref": self.project_snapshot_ref,
            "motion_generations": (
                None if self.motion_generations is None else dict(self.motion_generations)
            ),
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
        motion_raw = data.get("motion_generations")
        motion: dict[str, int] | None = None
        if motion_raw is not None:
            if not isinstance(motion_raw, dict):
                raise ValidationError(
                    "motion_generations must be an object of generations or null",
                    kind="contract",
                )
            motion = {}
            for name, value in cast("Mapping[str, JSONValue]", motion_raw).items():
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValidationError(
                        f"motion_generations[{name!r}] must be an integer generation",
                        kind="contract",
                    )
                motion[name] = value
        raw_scope = data.get("scope", "part")
        if raw_scope not in ("part", "project"):
            raise ValidationError(f"invalid check-report scope: {raw_scope!r}", kind="contract")
        scope: CheckScope = "project" if raw_scope == "project" else "part"
        return cls(
            part=_opt_str(data, "part"),
            check_set_generation=_req(data, "check_set_generation", int),
            check_bundle_ref=_req(data, "check_bundle_ref", str),
            file_hashes=_str_map(data, "file_hashes"),
            project_snapshot_ref=_opt_str(data, "project_snapshot_ref"),
            motion_generations=motion,
            checks=checks,
            scope=scope,
            project=_opt_str(data, "project"),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CheckReport):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __hash__(self) -> int:
        return hash((self.scope, self.part, self.check_set_generation, self.check_bundle_ref))


def _params_declaration(data: Mapping[str, JSONValue]) -> dict[str, Param]:
    """``params_declaration`` rebuilt into ``Param`` records; ``{}`` when absent."""
    raw = data.get("params_declaration")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Param] = {}
    for name, entry in cast("Mapping[str, JSONValue]", raw).items():
        if not isinstance(entry, dict):
            raise ValidationError(f"params_declaration[{name!r}]: expected object", kind="contract")
        decl = cast("Mapping[str, JSONValue]", entry)
        bounds = (decl.get("default"), decl.get("min"), decl.get("max"))
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in bounds):
            raise ValidationError(
                f"params_declaration[{name!r}]: default/min/max must be numbers", kind="contract"
            )
        doc = decl.get("doc")
        raw_step = decl.get("step")
        numeric_step = isinstance(raw_step, int | float) and not isinstance(raw_step, bool)
        out[name] = Param(
            default=cast("int | float", bounds[0]),
            min=cast("int | float", bounds[1]),
            max=cast("int | float", bounds[2]),
            doc=doc if isinstance(doc, str) else "",
            step=cast("int | float", raw_step) if numeric_step else None,
        )
    return out


def _checkpoints(data: Mapping[str, JSONValue]) -> tuple[StatementCheckpoint, ...]:
    raw = cast("list[JSONValue]", _req(data, "checkpoints", list))
    out: list[StatementCheckpoint] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("checkpoints: expected list of objects", kind="contract")
        out.append(StatementCheckpoint.from_json(cast("dict[str, JSONValue]", item)))
    return tuple(out)


__all__: Sequence[str] = (
    "BUILD_INPUTS",
    "MESH_UNITS",
    "AuditHashes",
    "BuildFreshness",
    "BuildInput",
    "BuildResult",
    "BuildStatus",
    "BuiltThrough",
    "CheckReport",
    "CheckResult",
    "CheckScope",
    "ErrorRecord",
    "GeometryEntry",
    "InputHashes",
    "LastGood",
    "MeshUnits",
    "Metrics",
    "StatementCheckpoint",
    "Warning",
)
