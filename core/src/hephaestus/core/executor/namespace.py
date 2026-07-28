"""The §2 injected namespace: the entire API surface a part script sees.

Builds the execution globals for part scripts and ``globals.py``:
``build123d`` complete (``from build123d import *``), ``math``, ``Param`` /
``PARAMS`` / ``p`` (§3), ``hc`` (§4, read-tracking), ``part`` (§5), ``tag``
(§5.3), ``check`` / ``CHECKS`` / ``approx`` (§6), ``import_step`` (INGEST.md
§1) — and nothing else.
``open``, ``__import__``, ``exec``/``eval``/``compile``, filesystem and
network access are absent from the builtins; attempting a well-known denied
name raises ``sandbox_denied``, which the worker surfaces as a build error.
This whitelist is defense in depth, not the security boundary — the OS
sandbox is (architecture §3.1).
"""

from __future__ import annotations

import builtins as _builtins
import math as _math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.params import Param, extract_params, merge_overrides

if TYPE_CHECKING:
    from hephaestus.core.executor.tags import TagRegistry
    from opstore.types import JSONValue

#: §5.2 manufacturing-metadata field names (schema'd for lint, free-text valued).
METADATA_FIELDS: tuple[str, ...] = (
    "description",
    "material_spec",
    "process",
    "stock_form",
    "blank_size",
    "general_tolerance",
    "finish",
    "assembly_method",
    "joint",
)

#: The §2 injected name for STEP ingest (``INGEST.md`` §1).
_IMPORT_STEP = "import_step"

#: Builtins deliberately absent; attempting them raises ``sandbox_denied``.
DENIED_BUILTINS: tuple[str, ...] = (
    "open",
    "__import__",
    "exec",
    "eval",
    "compile",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "memoryview",
    "globals",
    "locals",
    "vars",
)

#: Non-exception builtins allowed in part scripts.
_ALLOWED_BUILTINS: tuple[str, ...] = (
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "complex",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "hash",
    "hex",
    "id",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "oct",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "classmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
    "True",
    "False",
    "None",
    "NotImplemented",
    "Ellipsis",
)


def _denier(name: str) -> Callable[..., object]:
    def denied(*_args: object, **_kwargs: object) -> object:
        raise SandboxDeniedError(
            f"{name!r} is not available in part scripts; the injected namespace "
            "is the entire API surface (script contract §2)"
        )

    denied.__name__ = f"denied_{name}"
    return denied


def safe_builtins() -> dict[str, object]:
    """The restricted ``__builtins__`` mapping for script execution."""
    out: dict[str, object] = {}
    for name in _ALLOWED_BUILTINS:
        if hasattr(_builtins, name):
            out[name] = getattr(_builtins, name)
    for name, value in vars(_builtins).items():
        if isinstance(value, type) and issubclass(value, BaseException):
            out[name] = value
    for name in DENIED_BUILTINS:
        out[name] = _denier(name)
    return out


def jsonify(value: object) -> JSONValue:
    """Best-effort JSON projection of a namespace value (hashing/consumption)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        items = list(value)  # pyright: ignore[reportUnknownArgumentType]
        return [jsonify(item) for item in items]
    if isinstance(value, dict):
        raw: dict[object, object] = dict(value)  # pyright: ignore[reportUnknownArgumentType]
        return {str(k): jsonify(v) for k, v in raw.items()}
    return repr(value)


class ParamState:
    """PARAMS publication state for one scope (part or project).

    ``PARAMS`` MUST appear before first use of ``p`` (§3): the proxy raises a
    contract error until :meth:`publish` runs. Publication extracts and
    validates the declaration, then merges overrides all-or-nothing
    (``param_out_of_bounds`` naming every offender).
    """

    def __init__(self, *, scope: str, overrides: Mapping[str, int | float | str]) -> None:
        self.scope = scope
        self.overrides: dict[str, int | float | str] = dict(overrides)
        self.declared: dict[str, Param] | None = None
        self.effective: dict[str, int | float] | None = None

    @property
    def published(self) -> bool:
        return self.effective is not None

    def publish(self, namespace: Mapping[str, object]) -> None:
        """Extract PARAMS from ``namespace`` and merge overrides (all-or-nothing)."""
        self.declared = extract_params(namespace)
        self.effective = merge_overrides(self.declared, self.overrides)

    def finalize(self) -> None:
        """Called after the last statement: overrides without PARAMS are a contract error."""
        if self.effective is None:
            if self.overrides:
                names = ", ".join(sorted(self.overrides))
                raise ValidationError(
                    f"{self.scope} parameter overrides given ({names}) but the script "
                    "declares no PARAMS",
                    kind="contract",
                )
            self.declared = {}
            self.effective = {}


class ParamProxy:
    """The ``p`` object: attribute reads of effective parameter values."""

    def __init__(self, state: ParamState) -> None:
        object.__setattr__(self, "_state", state)

    def __getattr__(self, name: str) -> int | float:
        state: ParamState = object.__getattribute__(self, "_state")
        if name.startswith("__"):
            raise AttributeError(name)
        if state.effective is None:
            raise ValidationError(
                f"p.{name} read before PARAMS was declared; PARAMS must appear "
                "before first use of p (script contract §3)",
                kind="contract",
            )
        if name not in state.effective:
            declared = ", ".join(sorted(state.effective)) or "(none)"
            raise ValidationError(
                f"unknown parameter p.{name}; declared parameters: {declared}",
                kind="contract",
            )
        return state.effective[name]

    def __setattr__(self, name: str, value: object) -> None:
        raise ValidationError(
            f"p.{name} is read-only; parameters are set via PARAMS defaults and "
            "build-request overrides",
            kind="contract",
        )


class HcNamespace:
    """The ``hc`` object: read-only project-shared names with read tracking (§4)."""

    def __init__(self, values: Mapping[str, object]) -> None:
        object.__setattr__(self, "_values", dict(values))
        object.__setattr__(self, "_consumed", set())

    def __getattr__(self, name: str) -> object:
        values: dict[str, object] = object.__getattribute__(self, "_values")
        if name.startswith("__"):
            raise AttributeError(name)
        if name not in values:
            available = ", ".join(sorted(values)) or "(none)"
            raise AttributeError(
                f"hc.{name} is not defined in globals.py; available names: {available}"
            )
        consumed: set[str] = object.__getattribute__(self, "_consumed")
        consumed.add(name)
        return values[name]

    def __setattr__(self, name: str, value: object) -> None:
        raise ValidationError(
            f"hc.{name} is read-only from part scripts; edit globals.py instead",
            kind="contract",
        )

    def consumed_names(self) -> tuple[str, ...]:
        consumed: set[str] = object.__getattribute__(self, "_consumed")
        return tuple(sorted(consumed))

    def consumed_projection(self) -> dict[str, JSONValue]:
        """Exactly the consumed name -> value mapping (JSON-projected, name-sorted)."""
        values: dict[str, object] = object.__getattribute__(self, "_values")
        return {name: jsonify(values[name]) for name in self.consumed_names()}

    def names(self) -> tuple[str, ...]:
        values: dict[str, object] = object.__getattribute__(self, "_values")
        return tuple(sorted(values))


class FeatureMetadata:
    """Per-feature metadata bag: ``part.feature(name).<field> = "..."`` (§5.3)."""

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_fields", {})

    def __setattr__(self, name: str, value: object) -> None:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        fields[name] = value

    def __getattr__(self, name: str) -> object:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        if name in fields:
            return fields[name]
        raise AttributeError(name)

    def to_json(self) -> dict[str, JSONValue]:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        return {name: jsonify(value) for name, value in fields.items()}


class PartOutput:
    """The ``part`` output object (§5): geometry, metadata fields, features."""

    def __init__(self) -> None:
        object.__setattr__(self, "_fields", {})
        object.__setattr__(self, "_features", {})

    def __setattr__(self, name: str, value: object) -> None:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        fields[name] = value

    def __getattr__(self, name: str) -> object:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        if name in fields:
            return fields[name]
        raise AttributeError(name)

    def feature(self, name: str) -> FeatureMetadata:
        """Per-feature metadata joined on the tag name (§5.3)."""
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError("part.feature(name) requires a non-empty name", kind="contract")
        features: dict[str, FeatureMetadata] = object.__getattribute__(self, "_features")
        if name not in features:
            features[name] = FeatureMetadata(name)
        return features[name]

    @property
    def geometry_value(self) -> object | None:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        return fields.get("geometry")

    def metadata(self) -> dict[str, JSONValue]:
        """The §5.2 string-valued metadata fields that were assigned."""
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        return {name: jsonify(fields[name]) for name in METADATA_FIELDS if name in fields}

    def feature_metadata(self) -> dict[str, dict[str, JSONValue]]:
        features: dict[str, FeatureMetadata] = object.__getattribute__(self, "_features")
        return {name: feature.to_json() for name, feature in features.items()}


class ImportRegistry:
    """The ``import_step`` implementation inside the worker (``INGEST.md`` §1).

    Harness-resolved, never script I/O: the executor read, hashed and converted
    each declared file OUTSIDE the sandbox and staged the BRep in this build's
    input area. ``import_step(name)`` is therefore a lookup plus a
    deserialization — it opens exactly one staged path and never a project
    path, so the §2 rule that the namespace has no filesystem access still
    holds exactly as written.

    ``failures`` carries the resolver's verdict for a declared name that could
    not be staged (missing file, unreadable STEP, refused path). Raising it
    HERE, when the statement runs, is what makes an unresolvable import a §8
    build error at the ``import_step`` statement rather than an opaque
    pre-build exception.
    """

    def __init__(
        self,
        staged: Mapping[str, Path],
        *,
        failures: Mapping[str, str] | None = None,
    ) -> None:
        self._staged = dict(staged)
        self._failures = dict(failures or {})
        self.used: list[str] = []

    def import_step(self, name: str) -> object:
        """Deserialize the staged shape for ``name`` (script contract §2)."""
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError(
                "import_step(name) requires a non-empty path relative to imports/",
                kind="contract",
            )
        failure = self._failures.get(name)
        if failure is not None:
            raise ValidationError(failure, kind="contract")
        staged = self._staged.get(name)
        if staged is None:
            available = ", ".join(sorted(self._staged)) or "(none)"
            raise ValidationError(
                f"import_step({name!r}): no such import was staged for this build; "
                f"imports are resolved from the declared string literals in this script "
                f"(staged: {available})",
                kind="contract",
            )
        from hephaestus.geom.step_io import shape_from_brep

        # Deserialized afresh per call: two ``import_step`` calls on one file
        # must yield two independent shapes, never one aliased object a later
        # placement could move under both names.
        shape = shape_from_brep(staged.read_bytes(), source=name)
        self._record(name)
        return shape

    def _record(self, name: str) -> None:
        if name not in self.used:
            self.used.append(name)


class Approx:
    """§6 ``approx(value, abs=tol)``: deterministic tolerant numeric comparison."""

    def __init__(self, value: float, *, abs: float = 1e-9) -> None:
        if abs < 0:
            raise ValidationError("approx tolerance must be non-negative", kind="contract")
        self.value = float(value)
        self.abs = float(abs)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, bool) or not isinstance(other, int | float):
            return NotImplemented
        return _math.fabs(float(other) - self.value) <= self.abs

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return NotImplemented
        return not eq

    def __hash__(self) -> int:
        return hash((self.value, self.abs))

    def __repr__(self) -> str:
        return f"approx({self.value!r}, abs={self.abs!r})"


def approx(value: float, *, abs: float = 1e-9) -> Approx:
    """§6 comparator: ``m.interference(...) == approx(0, abs=1e-6)``."""
    return Approx(value, abs=abs)


class CheckRegistry:
    """Collects checks registered imperatively via ``check(name, predicate)``."""

    def __init__(self) -> None:
        self._checks: dict[str, object] = {}

    def register(self, name: str, predicate: object) -> None:
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError(
                "check(name, predicate) requires a non-empty name", kind="contract"
            )
        if not callable(predicate):
            raise ValidationError(f"check {name!r}: predicate must be callable", kind="contract")
        self._checks[name] = predicate

    def collected(self) -> dict[str, object]:
        return dict(self._checks)


def _build123d_exports() -> dict[str, object]:
    import build123d

    return {name: getattr(build123d, name) for name in build123d.__all__}


def build_namespace(
    *,
    param_state: ParamState,
    hc: HcNamespace | None = None,
    part: PartOutput | None = None,
    tag_registry: TagRegistry | None = None,
    check_registry: CheckRegistry | None = None,
    imports: ImportRegistry | None = None,
) -> dict[str, object]:
    """Assemble the §2 injected namespace as execution globals.

    Part mode passes ``part`` + ``tag_registry`` (+ ``imports``, INGEST.md §1);
    globals mode omits them (globals.py declares values, not geometry — §4).
    ``__builtins__`` is the restricted mapping from :func:`safe_builtins`.
    """
    namespace: dict[str, object] = {}
    namespace.update(_build123d_exports())
    namespace["math"] = _math
    namespace["Param"] = Param
    namespace["p"] = ParamProxy(param_state)
    if hc is not None:
        namespace["hc"] = hc
    if part is not None:
        namespace["part"] = part
    if tag_registry is not None:
        namespace["tag"] = tag_registry.tag
    if check_registry is not None:
        namespace["check"] = check_registry.register
    if imports is not None:
        namespace[_IMPORT_STEP] = imports.import_step
    namespace["approx"] = approx
    namespace["__builtins__"] = safe_builtins()
    namespace["__name__"] = "__hephaestus_script__"
    return namespace


def injected_names(namespace: Mapping[str, object]) -> frozenset[str]:
    """The injected key set — used to identify script-bound names afterwards."""
    return frozenset(namespace)
