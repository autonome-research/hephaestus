"""Bounded parameter declarations, validation, and override merging (§3).

``Param(default, min=..., max=..., doc="", step=None)`` declares a bounded
numeric parameter. Integer defaults declare integer params; float defaults
declare floats. Overrides are validated against bounds; violations raise the
structured ``param_out_of_bounds`` error naming every offending parameter,
and merging is all-or-nothing: either every override is valid and the full
effective mapping is returned, or nothing is applied.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from hephaestus.core.errors import ParamOutOfBoundsError, ValidationError
from opstore.types import JSONValue

ParamType = Literal["int", "float"]

PARAMS_NAME = "PARAMS"


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


@dataclass(frozen=True)
class Param:
    """One bounded numeric parameter (§3): positional default, min, max.

    ``doc`` and ``step`` are EXTENSIONs. The declared type is inferred from
    ``default``: an ``int`` default declares an integer parameter, a ``float``
    default declares a float parameter.
    """

    default: int | float
    min: int | float
    max: int | float
    doc: str = ""
    step: int | float | None = None

    def __post_init__(self) -> None:
        for label, value in (("default", self.default), ("min", self.min), ("max", self.max)):
            if not _is_number(value):
                raise ValidationError(
                    f"Param {label} must be int or float, got {type(value).__name__}",
                    kind="contract",
                )
            if not math.isfinite(value):
                raise ValidationError(
                    f"Param {label} must be finite, got {value!r}", kind="contract"
                )
        if self.step is not None:
            if not _is_number(self.step):
                raise ValidationError(
                    f"Param step must be int, float, or None, got {type(self.step).__name__}",
                    kind="contract",
                )
            if not math.isfinite(self.step) or self.step <= 0:
                raise ValidationError(
                    f"Param step must be positive, got {self.step!r}", kind="contract"
                )
        if not isinstance(cast("object", self.doc), str):
            raise ValidationError(
                f"Param doc must be str, got {type(self.doc).__name__}", kind="contract"
            )
        if self.min > self.max:
            raise ValidationError(
                f"Param bounds inverted: min={self.min!r} > max={self.max!r}", kind="contract"
            )
        if not (self.min <= self.default <= self.max):
            raise ValidationError(
                f"Param default {self.default!r} outside bounds [{self.min!r}, {self.max!r}]",
                kind="contract",
            )

    @property
    def type(self) -> ParamType:
        """Inferred parameter type: ``"int"`` iff the default is an int."""
        return "int" if isinstance(self.default, int) else "float"

    def coerce(self, value: int | float | str, *, name: str) -> int | float:
        """Coerce a raw override value (possibly a CLI string) to this param's type.

        Raises ``validation_error`` (kind ``contract``) when the value cannot
        represent this parameter's type; bounds are NOT checked here.
        """
        if isinstance(value, str):
            try:
                parsed: int | float = int(value, 10) if self.type == "int" else float(value)
            except ValueError:
                raise ValidationError(
                    f"parameter {name!r}: cannot parse {value!r} as {self.type}",
                    kind="contract",
                ) from None
            value = parsed
        if not _is_number(value):
            raise ValidationError(
                f"parameter {name!r}: expected a number, got {type(value).__name__}",
                kind="contract",
            )
        if not math.isfinite(value):
            raise ValidationError(
                f"parameter {name!r}: value must be finite, got {value!r}", kind="contract"
            )
        if self.type == "int":
            if isinstance(value, float):
                if not value.is_integer():
                    raise ValidationError(
                        f"parameter {name!r}: expected an integer, got {value!r}",
                        kind="contract",
                    )
                value = int(value)
            return value
        return float(value)

    def in_bounds(self, value: int | float) -> bool:
        """True iff ``value`` satisfies ``min <= value <= max``."""
        return self.min <= value <= self.max

    def to_json(self) -> dict[str, JSONValue]:
        """Canonical JSON form of the declaration (drives clients and hashing)."""
        out: dict[str, JSONValue] = {
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "type": self.type,
        }
        if self.doc:
            out["doc"] = self.doc
        if self.step is not None:
            out["step"] = self.step
        return out


def extract_params(namespace: Mapping[str, object]) -> dict[str, Param]:
    """Extract and validate the ``PARAMS`` dict from an executed script namespace.

    Absent ``PARAMS`` yields an empty dict. A malformed declaration (non-dict
    ``PARAMS``, non-str key, non-``Param`` value) raises ``validation_error``
    (kind ``contract``).
    """
    raw = namespace.get(PARAMS_NAME)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError(
            f"{PARAMS_NAME} must be a dict, got {type(raw).__name__}", kind="contract"
        )
    items = cast("dict[object, object]", raw)
    out: dict[str, Param] = {}
    for key, value in items.items():
        if not isinstance(key, str) or not key:
            raise ValidationError(
                f"{PARAMS_NAME} keys must be non-empty str, got {key!r}", kind="contract"
            )
        if not isinstance(value, Param):
            raise ValidationError(
                f"{PARAMS_NAME}[{key!r}] must be a Param, got {type(value).__name__}",
                kind="contract",
            )
        out[key] = value
    return out


def merge_overrides(
    params: Mapping[str, Param],
    overrides: Mapping[str, int | float | str],
) -> dict[str, int | float]:
    """Merge overrides onto declared defaults, all-or-nothing.

    Returns the complete effective mapping (every declared parameter, in
    declaration order). Unknown override names raise ``validation_error``
    (kind ``contract``) listing the known parameters; any out-of-bounds value
    raises ``param_out_of_bounds`` naming EVERY offending parameter. On any
    failure nothing is applied.
    """
    unknown = sorted(name for name in overrides if name not in params)
    if unknown:
        known = ", ".join(sorted(params)) or "(none declared)"
        raise ValidationError(
            f"unknown parameter(s) {', '.join(repr(n) for n in unknown)}; "
            f"declared parameters: {known}",
            kind="contract",
        )
    coerced: dict[str, int | float] = {}
    violations: list[str] = []
    detail: list[str] = []
    for name, raw in overrides.items():
        param = params[name]
        value = param.coerce(raw, name=name)
        if not param.in_bounds(value):
            violations.append(name)
            detail.append(f"{name}={value!r} outside [{param.min!r}, {param.max!r}]")
        else:
            coerced[name] = value
    if violations:
        ordered = sorted(violations)
        raise ParamOutOfBoundsError(
            "parameter(s) out of bounds: " + "; ".join(sorted(detail)),
            params=tuple(ordered),
        )
    return {name: coerced.get(name, param.default) for name, param in params.items()}


def params_declaration_json(params: Mapping[str, Param]) -> dict[str, JSONValue]:
    """Canonical JSON form of a full ``PARAMS`` declaration (name-sorted)."""
    return {name: params[name].to_json() for name in sorted(params)}


def _number_const(node: ast.expr) -> int | float | None:
    """A finite numeric ``Constant``, or ``None`` if the node is not one."""
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value):
        return None
    return value


def _str_const(node: ast.expr | None) -> str | None:
    if node is None or not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return node.value


def _param_from_call(node: ast.expr) -> Param | None:
    """Rebuild a ``Param`` from a literal ``Param(...)`` AST call, or ``None``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "Param":
        return None
    values: dict[str, object] = {}
    if node.args:
        default = _number_const(node.args[0])
        if default is None or len(node.args) > 1:
            return None
        values["default"] = default
    for keyword in node.keywords:
        if keyword.arg is None:
            return None
        if keyword.arg in {"default", "min", "max", "step"}:
            number = _number_const(keyword.value)
            if number is None:
                return None
            values[keyword.arg] = number
        elif keyword.arg == "doc":
            doc = _str_const(keyword.value)
            if doc is None:
                return None
            values["doc"] = doc
        else:
            return None
    default = values.get("default")
    minimum = values.get("min")
    maximum = values.get("max")
    if (
        not isinstance(default, int | float)
        or not isinstance(minimum, int | float)
        or not isinstance(maximum, int | float)
    ):
        return None
    raw_step = values.get("step")
    step: int | float | None = (
        None if isinstance(raw_step, bool) or not isinstance(raw_step, int | float) else raw_step
    )
    raw_doc = values.get("doc", "")
    doc = raw_doc if isinstance(raw_doc, str) else ""
    try:
        return Param(default=default, min=minimum, max=maximum, doc=doc, step=step)
    except ValidationError:
        return None


def static_params(source: str) -> tuple[dict[str, Param], tuple[str, ...]]:
    """Read a ``PARAMS = {...}`` assignment without executing the script.

    Returns ``(literal declarations, key names in source order)``. A key whose
    value is not a fully-literal ``Param(...)`` is listed in the names but
    omitted from the declaration map — the CLI can still name it, and a last
    published build can still supply its effective value. A syntax error or a
    missing ``PARAMS`` yields empty results; that is a named absence, not a
    guess.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}, ()
    names: list[str] = []
    declarations: dict[str, Param] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == PARAMS_NAME for target in stmt.targets
        ):
            continue
        mapping = stmt.value
        if not isinstance(mapping, ast.Dict):
            continue
        for key_node, value_node in zip(mapping.keys, mapping.values, strict=False):
            name = _str_const(key_node)
            if name is None or not name:
                continue
            names.append(name)
            param = _param_from_call(value_node)
            if param is not None:
                declarations[name] = param
    return declarations, tuple(names)
