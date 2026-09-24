"""The ``tools`` registry's cutter-record index (CAM.md §3.5; Stage 14A).

A tool record is pure data — the ``parts`` record shape with different fields:
identity, cutter geometry, a **mandatory** ``holder`` block, sourced ``feeds``
entries, and a ``simplifications`` list that is safety content, not
documentation. Two rules are load-bearing and enforced here, at index time, by
name:

* **no ``holder`` block, no record** (``tool_missing_holder``) — without a
  declared holder envelope there is no collision claim to make at all, so a
  holderless record would make every collision check on it ``undeclared_scene``;
* **every ``feeds`` entry carries a ``source``** (``tool_feed_missing_source``)
  — a number that commands a machine is never invented (CAM.md §1.2), so a
  feed with no stated origin is refused rather than trusted.

Unlike ``parts`` (generator scripts) and ``dfm`` (predicates), the ``tools``
registry carries **no executable content**: there is no reason for a cutter to
be a program, and every reason for it not to be. The digest, pin and verify
machinery is the existing one, unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._errors import RegistryError, RegistryRefusal
from ._fields import opt_str, req_str, str_tuple
from ._layout import MANIFEST_FILENAME, Registry

__all__ = ["ToolFeedEntry", "ToolHolder", "ToolRecord", "ToolsIndex", "parse_tool_record"]


def _req_num(record: Mapping[str, Any], key: str, *, source: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(
            f"{source}: {key!r} is required and must be a number", kind="contract"
        )
    return float(value)


def _opt_num(record: Mapping[str, Any], key: str, default: float = 0.0, *, source: str) -> float:
    value = record.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"{source}: {key!r} must be a number", kind="contract")
    return float(value)


@dataclass(frozen=True)
class ToolHolder:
    """The declared holder envelope — the collision body above the shank.

    Mandatory on every record: the holder is load-bearing, because without it
    there is no collision claim to make at all (CAM.md §3.5).
    """

    kind: str
    envelope: str
    diameter_mm: float
    length_mm: float
    taper_deg: float = 0.0

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind,
            "envelope": self.envelope,
            "diameter_mm": self.diameter_mm,
            "length_mm": self.length_mm,
            "taper_deg": self.taper_deg,
        }


@dataclass(frozen=True)
class ToolFeedEntry:
    """One transported ``(material, op)`` feeds row, with its mandatory source.

    Feeds are transported, gated, never derived (CAM.md §3.6): the ``source``
    string states where the numbers came from, and an entry without one is
    refused at load.
    """

    material: str
    op: str
    rpm: float
    feed_mm_min: float
    source: str
    plunge_mm_min: float = 0.0
    doc_mm: float = 0.0
    woc_mm: float = 0.0

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "material": self.material,
            "op": self.op,
            "rpm": self.rpm,
            "feed_mm_min": self.feed_mm_min,
            "plunge_mm_min": self.plunge_mm_min,
            "doc_mm": self.doc_mm,
            "woc_mm": self.woc_mm,
            "source": self.source,
        }


@dataclass(frozen=True)
class ToolRecord:
    """One tool-library record (CAM.md §3.5): pure data, no executable content."""

    id: str
    kind: str
    diameter_mm: float
    flutes: int
    flute_length_mm: float
    shank_diameter_mm: float
    overall_length_mm: float
    stickout_mm: float
    holder: ToolHolder
    corner_radius_mm: float = 0.0
    max_doc_mm: float = 0.0
    max_woc_mm: float = 0.0
    feeds: tuple[ToolFeedEntry, ...] = ()
    simplifications: tuple[str, ...] = ()
    license: str = ""
    registry: str = ""
    digest: str = ""

    def feed_for(self, material: str, op: str) -> ToolFeedEntry | None:
        """The ``(material, op)`` feeds entry, or None (never a derived number)."""
        for entry in self.feeds:
            if entry.material == material and entry.op == op:
                return entry
        return None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "kind": self.kind,
            "diameter_mm": self.diameter_mm,
            "corner_radius_mm": self.corner_radius_mm,
            "flutes": self.flutes,
            "flute_length_mm": self.flute_length_mm,
            "shank_diameter_mm": self.shank_diameter_mm,
            "overall_length_mm": self.overall_length_mm,
            "stickout_mm": self.stickout_mm,
            "holder": self.holder.to_json(),
            "max_doc_mm": self.max_doc_mm,
            "max_woc_mm": self.max_woc_mm,
            "feeds": [entry.to_json() for entry in self.feeds],
            "simplifications": list(self.simplifications),
            "license": self.license,
            "registry": self.registry,
            "registry_digest": self.digest,
        }


def _parse_holder(record: Mapping[str, Any], *, tool_id: str, source: str) -> ToolHolder:
    raw = record.get("holder")
    if raw is None:
        raise RegistryRefusal(
            "tool_missing_holder",
            f"{source}: tool {tool_id!r} declares no 'holder' block; the holder is "
            "load-bearing — without it there is no collision claim to make at all, and "
            "every collision check on this tool would be undeclared_scene (CAM.md §3.5)",
            detail={"tool": tool_id},
        )
    if not isinstance(raw, dict):
        raise ValidationError(f"{source}: 'holder' must be an object", kind="contract")
    holder = cast("Mapping[str, Any]", raw)
    return ToolHolder(
        kind=req_str(holder, "kind", source=f"{source} holder"),
        envelope=req_str(holder, "envelope", source=f"{source} holder"),
        diameter_mm=_req_num(holder, "diameter_mm", source=f"{source} holder"),
        length_mm=_req_num(holder, "length_mm", source=f"{source} holder"),
        taper_deg=_opt_num(holder, "taper_deg", source=f"{source} holder"),
    )


def _parse_feeds(
    record: Mapping[str, Any], *, tool_id: str, source: str
) -> tuple[ToolFeedEntry, ...]:
    raw = record.get("feeds")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError(f"{source}: 'feeds' must be a list of entries", kind="contract")
    entries: list[ToolFeedEntry] = []
    for index, item in enumerate(cast("list[Any]", raw)):
        if not isinstance(item, dict):
            raise ValidationError(f"{source}: feeds[{index}] must be an object", kind="contract")
        entry = cast("Mapping[str, Any]", item)
        entry_source = f"{source} feeds[{index}]"
        source_text = entry.get("source")
        if not isinstance(source_text, str) or not source_text:
            raise RegistryRefusal(
                "tool_feed_missing_source",
                f"{entry_source}: tool {tool_id!r} carries a feeds entry with no 'source'; "
                "a number that commands a machine is never invented (CAM.md §1.2), so a "
                "feed with no stated origin is refused at load",
                detail={"tool": tool_id, "feeds_index": index},
            )
        entries.append(
            ToolFeedEntry(
                material=req_str(entry, "material", source=entry_source),
                op=req_str(entry, "op", source=entry_source),
                rpm=_req_num(entry, "rpm", source=entry_source),
                feed_mm_min=_req_num(entry, "feed_mm_min", source=entry_source),
                plunge_mm_min=_opt_num(entry, "plunge_mm_min", source=entry_source),
                doc_mm=_opt_num(entry, "doc_mm", source=entry_source),
                woc_mm=_opt_num(entry, "woc_mm", source=entry_source),
                source=source_text,
            )
        )
    return tuple(entries)


def parse_tool_record(
    record: Mapping[str, Any], *, source: str, registry: str = "", digest: str = ""
) -> ToolRecord:
    """One validated tool record; every content rule is a named refusal."""
    tool_id = req_str(record, "id", source=source)
    flutes_raw = record.get("flutes", 0)
    if isinstance(flutes_raw, bool) or not isinstance(flutes_raw, int):
        raise ValidationError(f"{source}: 'flutes' must be an integer", kind="contract")
    return ToolRecord(
        id=tool_id,
        kind=req_str(record, "kind", source=source),
        diameter_mm=_req_num(record, "diameter_mm", source=source),
        corner_radius_mm=_opt_num(record, "corner_radius_mm", source=source),
        flutes=flutes_raw,
        flute_length_mm=_req_num(record, "flute_length_mm", source=source),
        shank_diameter_mm=_req_num(record, "shank_diameter_mm", source=source),
        overall_length_mm=_req_num(record, "overall_length_mm", source=source),
        stickout_mm=_req_num(record, "stickout_mm", source=source),
        holder=_parse_holder(record, tool_id=tool_id, source=source),
        max_doc_mm=_opt_num(record, "max_doc_mm", source=source),
        max_woc_mm=_opt_num(record, "max_woc_mm", source=source),
        feeds=_parse_feeds(record, tool_id=tool_id, source=source),
        simplifications=str_tuple(record, "simplifications"),
        license=opt_str(record, "license"),
        registry=registry,
        digest=digest,
    )


class ToolsIndex:
    """The ``tools`` registry's record index, keyed by tool id."""

    def __init__(self, registry: Registry | None) -> None:
        self._registry = registry
        self._tools: dict[str, ToolRecord] = {}
        if registry is None:
            return
        source = f"{registry.root / MANIFEST_FILENAME} [[tools]]"
        for item in registry.manifest.tools:
            listed = cast("Mapping[str, Any]", item)
            tool_id = req_str(listed, "id", source=source)
            path = registry.root / opt_str(listed, "file", f"{tool_id}.json")
            if not path.is_file():
                raise ValidationError(f"{source}: {path} is missing", kind="contract")
            try:
                raw: object = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{path}: invalid JSON: {exc}", kind="contract") from exc
            if not isinstance(raw, dict):
                raise ValidationError(f"{path}: must be a JSON object", kind="contract")
            record = parse_tool_record(
                cast("Mapping[str, Any]", raw),
                source=str(path),
                registry=registry.name,
                digest=registry.digest,
            )
            if record.id != tool_id:
                raise ValidationError(
                    f"{path}: record id {record.id!r} does not match the manifest's {tool_id!r}",
                    kind="contract",
                )
            if tool_id in self._tools:
                raise ValidationError(f"{source}: duplicate tool id {tool_id!r}", kind="contract")
            self._tools[tool_id] = record

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def has(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def get(self, tool_id: str) -> ToolRecord:
        """One record by id; an unknown id lists the known ones."""
        record = self._tools.get(tool_id)
        if record is None:
            raise RegistryError(
                "unknown_tool",
                f"no tool {tool_id!r} in the tools registry; tools: "
                + (", ".join(self.ids()) or "(none)"),
                data={"candidates": list(self.ids())},
            )
        return record

    def listing(self) -> list[dict[str, JSONValue]]:
        return [self._tools[tool_id].to_json() for tool_id in self.ids()]
