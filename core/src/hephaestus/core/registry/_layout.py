"""The on-disk shape of one registry: ``registry.toml`` and verify-on-load.

Every registry kind shares one format (architecture §3.6) — a directory holding
a versioned manifest plus content. Loading is the only place integrity is
enforced: with a pin the tree is hashed *before* any content is read for use,
and a mismatch refuses the load outright.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._digest import merkle_digest
from ._errors import RegistryIntegrityError
from ._fields import entries, opt_str, req_str, table

__all__ = [
    "BUNDLED_KINDS",
    "MANIFEST_FILENAME",
    "Registry",
    "RegistryKind",
    "RegistryManifest",
    "load_registry",
    "parse_manifest",
]

#: Manifest filename inside every registry directory.
MANIFEST_FILENAME: Final[str] = "registry.toml"

#: Registry kinds Hephaestus ships.
BUNDLED_KINDS: Final[tuple[str, ...]] = ("skills", "parts", "materials", "dfm")

RegistryKind = Literal["skills", "parts", "materials", "dfm"]
_KINDS: Final[frozenset[str]] = frozenset({"skills", "parts", "materials", "dfm"})


@dataclass(frozen=True)
class RegistryManifest:
    """Parsed ``registry.toml``: identity plus the content index."""

    name: str
    kind: RegistryKind
    version: str
    license: str = ""
    description: str = ""
    skills: tuple[Mapping[str, JSONValue], ...] = ()
    parts: tuple[Mapping[str, JSONValue], ...] = ()
    materials: tuple[Mapping[str, JSONValue], ...] = ()
    packs: tuple[Mapping[str, JSONValue], ...] = ()


def parse_manifest(text: str, *, source: str = MANIFEST_FILENAME) -> RegistryManifest:
    """Parse a ``registry.toml``; malformed input is a contract validation error."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"{source}: invalid TOML: {exc}", kind="contract") from exc
    data = cast("Mapping[str, Any]", raw)
    header = table(data, "registry", source=source)
    if not header:
        raise ValidationError(f"{source}: a [registry] table is required", kind="contract")
    kind = req_str(header, "kind", source=source)
    if kind not in _KINDS:
        raise ValidationError(
            f"{source}: registry kind {kind!r} is not one of {', '.join(sorted(_KINDS))}",
            kind="contract",
        )
    return RegistryManifest(
        name=req_str(header, "name", source=source),
        kind=cast("RegistryKind", kind),
        version=req_str(header, "version", source=source),
        license=opt_str(header, "license"),
        description=opt_str(header, "description"),
        skills=cast("tuple[Mapping[str, JSONValue], ...]", entries(data, "skills", source=source)),
        parts=cast("tuple[Mapping[str, JSONValue], ...]", entries(data, "parts", source=source)),
        materials=cast(
            "tuple[Mapping[str, JSONValue], ...]", entries(data, "materials", source=source)
        ),
        packs=cast("tuple[Mapping[str, JSONValue], ...]", entries(data, "packs", source=source)),
    )


@dataclass(frozen=True)
class Registry:
    """One loaded registry: its root, manifest, and verified content digest."""

    root: Path
    manifest: RegistryManifest
    digest: str
    pinned: bool

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def kind(self) -> RegistryKind:
        return self.manifest.kind


def load_registry(root: Path, *, expected_digest: str | None = None) -> Registry:
    """Load the registry at ``root``, verifying it against ``expected_digest``.

    With a pin, the tree is hashed *before* any content is read for use, and a
    mismatch raises :class:`RegistryIntegrityError` — the registry does not load
    at all. Without a pin the digest is still computed and reported (so
    ``heph registry pin`` can record it) but nothing is verified; callers that
    require pinning check :attr:`Registry.pinned`.
    """
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValidationError(f"{root} has no {MANIFEST_FILENAME}", kind="contract")
    digest = merkle_digest(root)
    if expected_digest is not None and digest != expected_digest:
        raise RegistryIntegrityError(
            f"registry at {root} hashes to {digest} but is pinned at {expected_digest}; "
            "refusing to load (run 'heph registry update' to re-pin deliberately)",
            expected=expected_digest,
            actual=digest,
            root=root,
        )
    manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"), source=str(manifest_path))
    return Registry(root=root, manifest=manifest, digest=digest, pinned=expected_digest is not None)
