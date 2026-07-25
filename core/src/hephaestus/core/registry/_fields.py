"""Typed field readers shared by every registry manifest and content parser.

Registry data arrives as untyped TOML/JSON mappings. These helpers narrow one
field at a time and raise a ``contract`` :class:`ValidationError` naming the
source file when the shape is wrong, so a malformed registry reports *where* it
is malformed rather than surfacing a ``TypeError`` deep in an index.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from hephaestus.core.errors import ValidationError

__all__ = ["entries", "num_tuple", "opt_str", "req_str", "str_tuple", "table"]


def table(data: Mapping[str, Any], key: str, *, source: str) -> Mapping[str, Any]:
    """The ``[key]`` sub-table, or an empty mapping when absent."""
    raw = data.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError(f"{source}: [{key}] must be a table", kind="contract")
    return cast("Mapping[str, Any]", raw)


def entries(data: Mapping[str, Any], key: str, *, source: str) -> tuple[Mapping[str, Any], ...]:
    """The ``[[key]]`` array of tables, or an empty tuple when absent."""
    raw = data.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError(f"{source}: [[{key}]] must be an array of tables", kind="contract")
    out: list[Mapping[str, Any]] = []
    for item in cast("list[Any]", raw):
        if not isinstance(item, dict):
            raise ValidationError(f"{source}: [[{key}]] entries must be tables", kind="contract")
        out.append(cast("Mapping[str, Any]", item))
    return tuple(out)


def req_str(data: Mapping[str, Any], key: str, *, source: str) -> str:
    """A required non-empty string field."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(
            f"{source}: {key!r} is required and must be a non-empty string", kind="contract"
        )
    return value


def opt_str(data: Mapping[str, Any], key: str, default: str = "") -> str:
    """An optional string field, falling back to ``default``."""
    value = data.get(key)
    return value if isinstance(value, str) else default


def str_tuple(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """An optional list field, stringified element-wise."""
    raw = data.get(key)
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in cast("list[Any]", raw))


def num_tuple(data: Mapping[str, Any], key: str) -> tuple[float, ...]:
    """An optional list field, keeping only its finite numeric elements."""
    raw = data.get(key)
    if not isinstance(raw, list):
        return ()
    out: list[float] = []
    for item in cast("list[Any]", raw):
        if isinstance(item, bool) or not isinstance(item, int | float):
            continue
        out.append(float(item))
    return tuple(out)
