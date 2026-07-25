"""Argument validation + default normalization against the canonical schemas.

MCP clients are stock: nothing on the client side validates a tool call against
``schemas/tools/<name>.schema.json`` before it reaches us, and FastMCP does not
validate arguments for a server-supplied ``inputSchema``. This module therefore
enforces the canonical parameter schema itself, over exactly the draft-2020-12
subset ``hephaestus.core.tools_decl`` emits (``type``, ``enum``/``const``,
``properties``/``required``/``additionalProperties``, ``items`` with
``minItems``/``maxItems``, ``pattern``, ``minimum``/``maximum``, ``anyOf``,
``allOf`` with ``if``/``then``/``else``, ``not``, and ``default``) plus the
custom ``x-hephaestus-maxUtf8Bytes`` keyword, which — exactly as on the Pi and
bridge boundaries — is enforced *after* ordinary schema validation and measured
on exact UTF-8 bytes with unpaired surrogates rejected as
``invalid_unicode_scalar``.

:func:`normalize_arguments` returns the validated arguments with every declared
default materialized. That normalized document — never the raw client payload —
is what the idempotency payload hash covers, so a replay that spells a default
explicitly hashes identically to one that omits it.
"""

from __future__ import annotations

import re
from typing import Any, Final, cast

from hephaestus.agent_bridge.limits import LimitError, enforce_max_utf8_bytes

__all__ = ["SchemaError", "normalize_arguments", "validate_instance"]

_MAX_UTF8_KEYWORD: Final[str] = "x-hephaestus-maxUtf8Bytes"
_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


class SchemaError(ValueError):
    """An argument document violated the canonical parameter schema."""

    def __init__(self, message: str, *, path: str = "") -> None:
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path
        self.detail = message


def _compiled(pattern: str) -> re.Pattern[str]:
    cached = _PATTERN_CACHE.get(pattern)
    if cached is None:
        cached = re.compile(pattern)
        _PATTERN_CACHE[pattern] = cached
    return cached


def _type_matches(kind: str, value: Any) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "null":
        return value is None
    return True  # pragma: no cover - tools_decl emits no other type


def _matches(schema: dict[str, Any], value: Any) -> bool:
    """True iff ``value`` validates, used for the boolean-valued keywords."""
    try:
        validate_instance(schema, value)
    except SchemaError:
        return False
    return True


def validate_instance(schema: dict[str, Any], value: Any, *, path: str = "") -> None:
    """Validate ``value`` against ``schema``; raise :class:`SchemaError` if invalid."""
    if not schema:
        return

    if "const" in schema and value != schema["const"]:
        raise SchemaError(f"must equal {schema['const']!r}", path=path)
    if "enum" in schema:
        allowed: list[Any] = schema["enum"]
        if value not in allowed:
            raise SchemaError(f"must be one of {allowed!r}", path=path)

    declared = schema.get("type")
    kinds: list[str] = (
        [declared]
        if isinstance(declared, str)
        else [str(k) for k in cast("list[Any]", declared)]
        if isinstance(declared, list)
        else []
    )
    if kinds and not any(_type_matches(kind, value) for kind in kinds):
        raise SchemaError(f"expected {'|'.join(kinds)}, got {type(value).__name__}", path=path)

    if "anyOf" in schema or "oneOf" in schema:
        variants = cast("list[dict[str, Any]]", schema.get("anyOf") or schema.get("oneOf") or [])
        if not any(_matches(variant, value) for variant in variants):
            raise SchemaError("matches none of the permitted variants", path=path)
    if "not" in schema and _matches(cast("dict[str, Any]", schema["not"]), value):
        raise SchemaError("matches an excluded variant", path=path)

    for clause in cast("list[dict[str, Any]]", schema.get("allOf", [])):
        _validate_conditional(clause, value, path=path)
    _validate_conditional(schema, value, path=path)

    if isinstance(value, str):
        _validate_string(schema, value, path=path)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(schema, value, path=path)
    elif isinstance(value, list):
        _validate_array(schema, cast("list[Any]", value), path=path)
    elif isinstance(value, dict):
        _validate_object(schema, cast("dict[str, Any]", value), path=path)


def _validate_conditional(schema: dict[str, Any], value: Any, *, path: str) -> None:
    if "if" not in schema:
        return
    branch = "then" if _matches(cast("dict[str, Any]", schema["if"]), value) else "else"
    sub = schema.get(branch)
    if isinstance(sub, dict):
        validate_instance(cast("dict[str, Any]", sub), value, path=path)


def _validate_string(schema: dict[str, Any], value: str, *, path: str) -> None:
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and _compiled(pattern).match(value) is None:
        raise SchemaError(f"does not match {pattern!r}", path=path)
    cap = schema.get(_MAX_UTF8_KEYWORD)
    if isinstance(cap, int):
        try:
            enforce_max_utf8_bytes(value, cap, field=path or "value")
        except LimitError as exc:
            raise SchemaError(f"{exc.code}: {exc}", path=path) from exc


def _validate_number(schema: dict[str, Any], value: float, *, path: str) -> None:
    low = schema.get("minimum")
    high = schema.get("maximum")
    if isinstance(low, (int, float)) and value < low:
        raise SchemaError(f"must be >= {low}", path=path)
    if isinstance(high, (int, float)) and value > high:
        raise SchemaError(f"must be <= {high}", path=path)


def _validate_array(schema: dict[str, Any], value: list[Any], *, path: str) -> None:
    low = schema.get("minItems")
    high = schema.get("maxItems")
    if isinstance(low, int) and len(value) < low:
        raise SchemaError(f"needs at least {low} items", path=path)
    if isinstance(high, int) and len(value) > high:
        raise SchemaError(f"allows at most {high} items", path=path)
    items = schema.get("items")
    if isinstance(items, dict):
        item_schema = cast("dict[str, Any]", items)
        for index, item in enumerate(value):
            validate_instance(item_schema, item, path=f"{path}[{index}]")


def _validate_object(schema: dict[str, Any], value: dict[str, Any], *, path: str) -> None:
    props = cast("dict[str, Any]", schema.get("properties") or {})
    for key in cast("list[str]", schema.get("required", [])):
        if key not in value:
            raise SchemaError(f"missing required property {key!r}", path=path)
    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        sub = cast("dict[str, Any] | None", props.get(key))
        if sub is not None:
            validate_instance(sub, item, path=f"{path}.{key}" if path else str(key))
            continue
        if additional is False:
            raise SchemaError(f"unknown property {key!r}", path=path or "arguments")
        if isinstance(additional, dict):
            validate_instance(
                cast("dict[str, Any]", additional),
                item,
                path=f"{path}.{key}" if path else str(key),
            )


def _apply_defaults(schema: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    props = cast("dict[str, Any]", schema.get("properties") or {})
    filled = dict(value)
    for key, sub in props.items():
        if key in filled or not isinstance(sub, dict):
            continue
        if "default" in sub:
            filled[key] = sub["default"]
    return filled


def normalize_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate ``arguments`` and return them with declared defaults materialized.

    Defaults are applied *after* validation so an explicitly-supplied value is
    validated as written, and so the normalized document is byte-identical
    whether or not the client spelled a default out.
    """
    validate_instance(schema, arguments, path="")
    return _apply_defaults(schema, arguments)
