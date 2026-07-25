"""The ``skills`` registry's content index.

Skill pages are *contextual* untrusted content: markdown files listed by the
manifest, validated to exist and to sit beneath the registry root at index time,
and handed to a model only through the provenance wrapper. This module owns the
index and the entry; the paging and wrapping live in :mod:`._reference`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._errors import RegistryError
from ._fields import opt_str, req_str
from ._layout import MANIFEST_FILENAME, Registry

__all__ = ["SKILL_ARTIFACT_KIND", "SkillEntry", "SkillsIndex"]

#: Artifact kind minted for a skill page snapshot (``read_artifact`` pages it).
SKILL_ARTIFACT_KIND: Final[str] = "skill"

_SKILL_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class SkillEntry:
    """One markdown skill reference plus its registry provenance."""

    name: str
    summary: str
    path: Path
    registry: str
    digest: str

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def tokens(self) -> int:
        """Coarse token estimate (~4 UTF-8 bytes per token), at least 1."""
        return max(1, math.ceil(len(self.read_bytes()) / 4))


class SkillsIndex:
    """The ``skills`` registry's content index (``load_skill`` / ``list_skills``)."""

    def __init__(self, registry: Registry | None) -> None:
        self._registry = registry
        self._entries: dict[str, SkillEntry] = {}
        if registry is None:
            return
        for item in registry.manifest.skills:
            record = cast("Mapping[str, Any]", item)
            source = f"{registry.root / MANIFEST_FILENAME} [[skills]]"
            name = req_str(record, "name", source=source)
            if not _SKILL_NAME_RE.match(name):
                raise ValidationError(
                    f"{source}: skill name {name!r} must match {_SKILL_NAME_RE.pattern}",
                    kind="contract",
                )
            file_name = opt_str(record, "file") or f"{name}.md"
            path = registry.root / file_name
            if PurePosixPath(file_name).is_absolute() or ".." in PurePosixPath(file_name).parts:
                raise ValidationError(
                    f"{source}: skill file {file_name!r} must be relative and beneath the registry",
                    kind="contract",
                )
            if not path.is_file():
                raise ValidationError(f"{source}: skill file {path} is missing", kind="contract")
            self._entries[name] = SkillEntry(
                name=name,
                summary=opt_str(record, "summary"),
                path=path,
                registry=registry.name,
                digest=registry.digest,
            )

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, name: str) -> SkillEntry:
        entry = self._entries.get(name)
        if entry is None:
            raise RegistryError(
                "unknown_skill",
                f"no skill named {name!r}; available skills: "
                + (", ".join(self.names()) or "(none)"),
                data={"candidates": list(self.names())},
            )
        return entry

    def listing(self) -> list[dict[str, JSONValue]]:
        return [
            {
                "name": entry.name,
                "summary": entry.summary,
                "tokens": entry.tokens(),
                "registry": entry.registry,
                "registry_digest": entry.digest,
            }
            for entry in (self._entries[name] for name in self.names())
        ]
