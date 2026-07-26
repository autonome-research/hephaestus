"""The ``materials`` registry's record index.

A material is one JSON record — density, stock forms, available thicknesses and
free-text notes — listed by the manifest. Density is required and numeric
because downstream mass estimates depend on it; everything else is optional.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._fields import num_tuple, opt_str, req_str, str_tuple
from ._layout import MANIFEST_FILENAME, Registry
from ._search import score

__all__ = ["Material", "MaterialsIndex"]

#: Word tokens of a free-text spec / a record's identity fields.
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Material:
    """One materials record (``search_materials``)."""

    id: str
    name: str
    density: float
    forms: tuple[str, ...]
    thicknesses: tuple[float, ...]
    notes: str
    keywords: tuple[str, ...] = ()
    registry: str = ""
    digest: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "name": self.name,
            "density": self.density,
            "forms": list(self.forms),
            "thicknesses": list(self.thicknesses),
            "notes": self.notes,
            "registry": self.registry,
            "registry_digest": self.digest,
        }


class MaterialsIndex:
    """The ``materials`` registry's record index (``search_materials``)."""

    def __init__(self, registry: Registry | None) -> None:
        self._registry = registry
        self._materials: dict[str, Material] = {}
        if registry is None:
            return
        for item in registry.manifest.materials:
            record = cast("Mapping[str, Any]", item)
            source = f"{registry.root / MANIFEST_FILENAME} [[materials]]"
            material_id = req_str(record, "id", source=source)
            path = registry.root / opt_str(record, "file", f"{material_id}.json")
            if not path.is_file():
                raise ValidationError(f"{source}: {path} is missing", kind="contract")
            raw: object = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValidationError(f"{path}: must be a JSON object", kind="contract")
            meta = cast("Mapping[str, Any]", raw)
            density = meta.get("density")
            if isinstance(density, bool) or not isinstance(density, int | float):
                raise ValidationError(
                    f"{path}: 'density' must be a number (kg/m^3)", kind="contract"
                )
            self._materials[material_id] = Material(
                id=material_id,
                name=opt_str(meta, "name", material_id),
                density=float(density),
                forms=str_tuple(meta, "forms"),
                thicknesses=num_tuple(meta, "thicknesses"),
                notes=opt_str(meta, "notes"),
                keywords=str_tuple(meta, "keywords"),
                registry=registry.name,
                digest=registry.digest,
            )

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._materials))

    def get(self, material_id: str) -> Material | None:
        """One record by id, or None (callers decide whether absence is an error)."""
        return self._materials.get(material_id)

    def match(self, spec: str) -> Material | None:
        """Best record for a free-text ``part.material_spec``, or None.

        The §5.2 metadata fields are free text, so resolving one to a registry
        record is a *search*, not a lookup. Identity wins over prose: a record is
        ranked first by how many of the spec's words appear as whole words in its
        id, name or keywords, and only then by :meth:`search`'s substring score.
        Without that split, ``"PLA filament"`` resolves to PETG, whose notes
        happen to mention PLA. Ties break on id, so the answer is deterministic,
        and no match at all is None — never a guess at the first record.
        """
        terms = set(_WORD_RE.findall(spec.lower()))
        if not terms:
            return None
        ranked: list[tuple[int, int, str]] = []
        for material_id in self.ids():
            material = self._materials[material_id]
            identity = set(_WORD_RE.findall(material.id.lower()))
            identity |= set(_WORD_RE.findall(material.name.lower()))
            identity |= {keyword.lower() for keyword in material.keywords}
            strong = len(terms & identity)
            weak = score(
                spec,
                (material.notes, " ".join(material.forms), " ".join(material.keywords)),
            )
            if strong or weak:
                ranked.append((-strong, -weak, material_id))
        if not ranked:
            return None
        ranked.sort()
        return self._materials[ranked[0][2]]

    def search(self, query: str) -> list[dict[str, JSONValue]]:
        scored: list[tuple[int, str]] = []
        for material_id in self.ids():
            material = self._materials[material_id]
            matched = score(
                query,
                (
                    material.id,
                    material.name,
                    material.notes,
                    " ".join(material.forms),
                    " ".join(material.keywords),
                ),
            )
            if matched:
                scored.append((matched, material_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self._materials[mid].to_json() for _matched, mid in scored]
