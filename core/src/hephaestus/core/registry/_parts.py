"""The ``parts`` registry's generator index.

Each store part is a directory holding ``part.json`` (metadata plus the declared
params schema) and ``generator.py`` (the *executable* content, run only under a
secure sandbox by :class:`~hephaestus.core.registry.RegistryOps`). This module
indexes and searches them; it never executes anything.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._errors import RegistryError
from ._fields import opt_str, req_str, str_tuple
from ._layout import MANIFEST_FILENAME, Registry
from ._search import score

__all__ = ["PartsIndex", "StorePart"]

_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class StorePart:
    """One parts-store generator: metadata, params schema, and its script."""

    id: str
    name: str
    summary: str
    keywords: tuple[str, ...]
    params: Mapping[str, JSONValue]
    preview: str
    script_path: Path
    registry: str
    digest: str

    def read_script(self) -> str:
        return self.script_path.read_text(encoding="utf-8")

    def search_result(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "name": self.name,
            "params": dict(self.params),
            "preview": self.preview,
            "registry": self.registry,
            "registry_digest": self.digest,
        }


class PartsIndex:
    """The ``parts`` registry's generator index (``search_parts_store``)."""

    def __init__(self, registry: Registry | None) -> None:
        self._registry = registry
        self._parts: dict[str, StorePart] = {}
        if registry is None:
            return
        for item in registry.manifest.parts:
            record = cast("Mapping[str, Any]", item)
            source = f"{registry.root / MANIFEST_FILENAME} [[parts]]"
            part_id = req_str(record, "id", source=source)
            if not _ID_RE.match(part_id):
                raise ValidationError(
                    f"{source}: part id {part_id!r} must match {_ID_RE.pattern}", kind="contract"
                )
            directory = registry.root / opt_str(record, "dir", part_id)
            metadata_path = directory / "part.json"
            script_path = directory / "generator.py"
            for path in (metadata_path, script_path):
                if not path.is_file():
                    raise ValidationError(f"{source}: {path} is missing", kind="contract")
            raw_meta: object = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(raw_meta, dict):
                raise ValidationError(f"{metadata_path}: must be a JSON object", kind="contract")
            meta = cast("Mapping[str, Any]", raw_meta)
            raw_params = meta.get("params")
            params: dict[str, JSONValue] = (
                cast("dict[str, JSONValue]", dict(cast("Mapping[str, Any]", raw_params)))
                if isinstance(raw_params, dict)
                else {}
            )
            self._parts[part_id] = StorePart(
                id=part_id,
                name=opt_str(meta, "name", part_id),
                summary=opt_str(meta, "summary"),
                keywords=str_tuple(meta, "keywords"),
                params=params,
                preview=opt_str(meta, "preview") or opt_str(meta, "summary"),
                script_path=script_path,
                registry=registry.name,
                digest=registry.digest,
            )

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._parts))

    def get(self, part_id: str) -> StorePart:
        part = self._parts.get(part_id)
        if part is None:
            raise RegistryError(
                "unknown_store_part",
                f"no store part {part_id!r}; available ids: " + (", ".join(self.ids()) or "(none)"),
                data={"candidates": list(self.ids())},
            )
        return part

    def search(self, query: str, max_results: int) -> list[dict[str, JSONValue]]:
        scored: list[tuple[int, str]] = []
        for part_id in self.ids():
            part = self._parts[part_id]
            matched = score(query, (part.id, part.name, part.summary, " ".join(part.keywords)))
            if matched:
                scored.append((matched, part_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self._parts[part_id].search_result() for _matched, part_id in scored[:max_results]]
