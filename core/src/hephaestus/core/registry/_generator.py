"""The store-generator fragment contract: parse, check, and render an instance.

Instancing rewrites a generator body mechanically, so the source must be
unambiguous. A generator declares three marker regions (``params`` / ``bind`` /
``body``), reaches its body only through ``_name = p.name`` binds, keeps every
module-scope name underscore-prefixed, and ends with ``part.geometry = <name>``
naming the instance root. :func:`parse_generator` enforces exactly that;
:func:`render_fragment` emits the generator's own body verbatim, renamed under a
per-instance prefix and placed, so two pasted instances cannot collide.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from hephaestus.core.errors import ValidationError

from ._errors import RegistryError
from ._parts import StorePart

__all__ = [
    "BIND_MARKER",
    "BODY_MARKER",
    "PARAMS_MARKER",
    "GeneratorSource",
    "instance_prefix",
    "parse_generator",
    "render_fragment",
]

PARAMS_MARKER: Final[str] = "# --- hephaestus-store: params ---"
BIND_MARKER: Final[str] = "# --- hephaestus-store: bind ---"
BODY_MARKER: Final[str] = "# --- hephaestus-store: body ---"

_FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset({"hc", "tag", "check", "CHECKS"})

_PLACEMENT_KEYS: Final[tuple[str, ...]] = ("x", "y", "z", "rx", "ry", "rz")


@dataclass(frozen=True)
class GeneratorSource:
    """A parsed, contract-checked store generator.

    ``bound_names`` is every module-scope name the bind and body regions assign;
    ``root_name`` is the name the final ``part.geometry = <name>`` statement
    publishes, i.e. the instance root a fragment places.
    """

    script: str
    params_region: str
    bind_region: str
    body_region: str
    param_names: tuple[str, ...]
    bound_names: tuple[str, ...] = field(default=())
    root_name: str = ""


def _module_bound_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()

    def record(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                record(element)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.For):
            record(node.target)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    record(item.optional_vars)
    return names


def parse_generator(script: str, *, source: str = "generator.py") -> GeneratorSource:
    """Parse and contract-check a store generator (see the module docstring).

    Enforced, because instancing rewrites the body mechanically and must not
    guess: exactly one ``params``/``bind``/``body`` marker in that order; the
    params region declares only ``PARAMS``; the bind region is exactly one
    ``_<name> = p.<name>`` line per declared parameter; the body never touches
    ``p``, ``hc``, ``tag``, ``check`` or ``CHECKS``; every module-scope name the
    bind/body regions assign is underscore-prefixed; and the last body statement
    is ``part.geometry = <name>``.
    """
    for marker in (PARAMS_MARKER, BIND_MARKER, BODY_MARKER):
        if script.count(marker) != 1:
            raise ValidationError(
                f"{source}: expected exactly one {marker!r} marker", kind="contract"
            )
    params_at = script.index(PARAMS_MARKER)
    bind_at = script.index(BIND_MARKER)
    body_at = script.index(BODY_MARKER)
    if not params_at < bind_at < body_at:
        raise ValidationError(
            f"{source}: markers must appear in params -> bind -> body order", kind="contract"
        )
    params_region = script[params_at + len(PARAMS_MARKER) : bind_at].strip("\n")
    bind_region = script[bind_at + len(BIND_MARKER) : body_at].strip("\n")
    body_region = script[body_at + len(BODY_MARKER) :].strip("\n")

    try:
        params_tree = ast.parse(params_region)
        bind_tree = ast.parse(bind_region)
        body_tree = ast.parse(body_region)
    except SyntaxError as exc:
        raise ValidationError(f"{source}: invalid Python: {exc}", kind="syntax") from exc

    param_names = _check_params_region(params_tree, source=source)
    _check_bind_region(bind_tree, param_names, source=source)
    bound = (_module_bound_names(bind_tree) | _module_bound_names(body_tree)) - {"part"}
    offending = sorted(name for name in bound if not name.startswith("_"))
    if offending:
        raise ValidationError(
            f"{source}: module-scope generator names must be underscore-prefixed; "
            f"got {', '.join(offending)}",
            kind="contract",
        )
    root_name = _check_body_region(body_tree, source=source)
    return GeneratorSource(
        script=script,
        params_region=params_region,
        bind_region=bind_region,
        body_region=body_region,
        param_names=param_names,
        bound_names=tuple(sorted(bound)),
        root_name=root_name,
    )


def _check_params_region(tree: ast.Module, *, source: str) -> tuple[str, ...]:
    statements = [node for node in tree.body if not isinstance(node, ast.Expr)]
    if len(statements) != 1 or not isinstance(statements[0], ast.Assign):
        raise ValidationError(
            f"{source}: the params region must contain exactly one PARAMS assignment",
            kind="contract",
        )
    assign = statements[0]
    targets = assign.targets
    if len(targets) != 1 or not isinstance(targets[0], ast.Name) or targets[0].id != "PARAMS":
        raise ValidationError(f"{source}: the params region must assign PARAMS", kind="contract")
    if not isinstance(assign.value, ast.Dict):
        raise ValidationError(f"{source}: PARAMS must be a dict literal", kind="contract")
    names: list[str] = []
    for key in assign.value.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValidationError(f"{source}: PARAMS keys must be string literals", kind="contract")
        names.append(key.value)
    return tuple(names)


def _check_bind_region(tree: ast.Module, param_names: Sequence[str], *, source: str) -> None:
    seen: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr):
            continue
        bad = ValidationError(
            f"{source}: the bind region accepts only '_<name> = p.<name>' statements",
            kind="contract",
        )
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise bad
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Attribute):
            raise bad
        base = value.value
        if not isinstance(base, ast.Name) or base.id != "p":
            raise bad
        if target.id != f"_{value.attr}":
            raise ValidationError(
                f"{source}: bind '{target.id} = p.{value.attr}' must bind '_{value.attr}'",
                kind="contract",
            )
        seen.append(value.attr)
    if sorted(seen) != sorted(param_names):
        declared = ", ".join(param_names) or "(none)"
        bound = ", ".join(seen) or "(none)"
        raise ValidationError(
            f"{source}: the bind region must bind every declared parameter exactly once "
            f"(declared: {declared}; bound: {bound})",
            kind="contract",
        )


def _check_body_region(tree: ast.Module, *, source: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise ValidationError(
                f"{source}: the generator body must not reference {node.id!r} "
                "(store generators are pure geometry)",
                kind="contract",
            )
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id == "p":
                raise ValidationError(
                    f"{source}: the body reads p.{node.attr}; parameters reach the body "
                    "only through the bind region",
                    kind="contract",
                )
            if isinstance(base, ast.Name) and base.id == "part" and node.attr != "geometry":
                raise ValidationError(
                    f"{source}: the body must not set part.{node.attr}", kind="contract"
                )
    if not tree.body:
        raise ValidationError(f"{source}: the body region is empty", kind="contract")
    last = tree.body[-1]
    bad = ValidationError(
        f"{source}: the last body statement must be 'part.geometry = <name>'", kind="contract"
    )
    if not isinstance(last, ast.Assign) or len(last.targets) != 1:
        raise bad
    target = last.targets[0]
    if not isinstance(target, ast.Attribute) or target.attr != "geometry":
        raise bad
    base = target.value
    if not isinstance(base, ast.Name) or base.id != "part":
        raise bad
    if not isinstance(last.value, ast.Name):
        raise ValidationError(
            f"{source}: 'part.geometry' must be assigned a bare name (the instance root)",
            kind="contract",
        )
    return last.value.id


def _literal(value: int | float) -> str:
    if isinstance(value, int):
        return repr(value)
    return repr(float(value))


def instance_prefix(part_id: str, params: Mapping[str, int | float], pos: object) -> str:
    """Deterministic, collision-resistant local-name prefix for one instance."""
    payload = json.dumps(
        {"id": part_id, "params": {k: params[k] for k in sorted(params)}, "pos": pos},
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )
    suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:6]
    return f"_{part_id}_{suffix}"


def _placement(pos: Mapping[str, Any] | None) -> tuple[str, str]:
    """``(placement expression prefix, human description)`` for a ``pos`` dict."""
    if not pos:
        return "", "at the part origin"
    unknown = sorted(key for key in pos if key not in _PLACEMENT_KEYS)
    if unknown:
        raise RegistryError(
            "invalid_params",
            f"pos accepts only {', '.join(_PLACEMENT_KEYS)}; got {', '.join(unknown)}",
        )
    values: dict[str, float] = {}
    for key in _PLACEMENT_KEYS:
        raw = pos.get(key, 0.0)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise RegistryError("invalid_params", f"pos[{key!r}] must be a number")
        if not math.isfinite(float(raw)):
            raise RegistryError("invalid_params", f"pos[{key!r}] must be finite")
        values[key] = float(raw)
    factors: list[str] = []
    if any(values[key] for key in ("x", "y", "z")):
        factors.append(
            f"Pos({_literal(values['x'])}, {_literal(values['y'])}, {_literal(values['z'])})"
        )
    if any(values[key] for key in ("rx", "ry", "rz")):
        factors.append(
            f"Rot({_literal(values['rx'])}, {_literal(values['ry'])}, {_literal(values['rz'])})"
        )
    if not factors:
        return "", "at the part origin"
    expression = " * ".join(factors) + " * "
    description = (
        f"at ({values['x']:g}, {values['y']:g}, {values['z']:g}) mm"
        f", rotated ({values['rx']:g}, {values['ry']:g}, {values['rz']:g})deg"
    )
    return expression, description


def render_fragment(
    generator: GeneratorSource,
    part: StorePart,
    effective: Mapping[str, int | float],
    pos: Mapping[str, Any] | None,
) -> str:
    """Render the placed ``script_fragment`` for one generator instance.

    The fragment is the generator's own body verbatim, with (a) the bind region
    replaced by literal effective values, (b) every module-scope name renamed
    under a per-instance prefix so pasting two instances into one script cannot
    collide, and (c) the trailing ``part.geometry = <root>`` statement replaced
    by a placement binding the model composes into its own ``part.geometry``.
    """
    prefix = instance_prefix(part.id, effective, dict(pos) if pos else None)
    placement, described = _placement(pos)
    rename = {name: f"{prefix}{name}" for name in generator.bound_names}

    def apply(text: str) -> str:
        out = text
        for old in sorted(rename, key=len, reverse=True):
            out = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", rename[old], out)
        return out

    binds = "\n".join(
        f"{rename['_' + name]} = {_literal(effective[name])}" for name in generator.param_names
    )
    body_lines = apply(generator.body_region).splitlines()
    # Drop the generator's own publication statement; a fragment is an instance,
    # not a part.
    root = rename[generator.root_name]
    kept = [line for line in body_lines if not line.strip().startswith("part.geometry")]
    header = [
        f"# {part.name} — parts-store instance {described}.",
        f"# registry: {part.registry} @ {part.digest}   id: {part.id}",
        "# Reference geometry from a pinned registry: review it, then compose",
        f"#   {prefix} into part.geometry (e.g. Compound(children=[..., {prefix}])).",
    ]
    tail = [
        f"{prefix} = {placement}{root}",
        f'{prefix}.label = "{part.id}"',
    ]
    if binds:
        return "\n".join([*header, "", binds, *kept, *tail, ""])
    return "\n".join([*header, "", *kept, *tail, ""])
