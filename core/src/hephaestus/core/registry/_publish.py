"""Publishing a registry: validate the tree end-to-end, then state its digest.

Pinning (:mod:`._pins`) is the *consumer* half of registry trust; publishing is
the producer half. ``heph registry publish`` refuses to state a digest for a
tree it could not fully read: the manifest parses, every content index for the
registry's kind builds (skill files exist, store parts have a generator and a
metadata file, materials records are numeric, DFM packs bind every rule to a
predicate and every predicate to declared parameters), and only then is the
Merkle root computed and recorded.

The :class:`PublicationRecord` is the artifact a publisher distributes beside
the tree. It carries the root digest *and* every leaf ``(path, digest)``, so a
consumer that sees a mismatch learns exactly which files were added, removed or
edited instead of only that "the hash changed". Verification is pure and
offline — :func:`verify_publication` needs the tree and the record, nothing
else.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._dfm import DfmIndex
from ._digest import merkle_digest, tree_leaves
from ._errors import RegistryIntegrityError
from ._layout import Registry, load_registry
from ._materials import MaterialsIndex
from ._parts import PartsIndex
from ._skills import SkillsIndex

__all__ = [
    "PUBLICATION_VERSION",
    "LeafDrift",
    "PublicationRecord",
    "publish_registry",
    "validate_content",
    "verify_publication",
]

#: Schema version of a publication record.
PUBLICATION_VERSION: Final[int] = 1


def validate_content(registry: Registry) -> dict[str, int]:
    """Build every content index for ``registry``'s kind; return entry counts.

    This is what makes ``publish`` an end-to-end act rather than a hash: a
    registry whose manifest lists a file that is missing, a store part without a
    generator, or a DFM rule reading an undeclared parameter raises here and is
    never published.
    """
    kind = registry.kind
    if kind == "skills":
        return {"skills": len(SkillsIndex(registry).names())}
    if kind == "parts":
        return {"parts": len(PartsIndex(registry).ids())}
    if kind == "materials":
        return {"materials": len(MaterialsIndex(registry).ids())}
    index = DfmIndex(registry)
    return {
        "packs": len(index.processes()),
        "rules": sum(len(index.get(process).rules) for process in index.processes()),
    }


@dataclass(frozen=True)
class LeafDrift:
    """One file that differs between a publication record and a tree on disk."""

    path: str
    status: str  # "added" | "removed" | "modified"
    expected: str | None
    actual: str | None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "path": self.path,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class PublicationRecord:
    """A publisher's signed-off statement about one registry tree.

    ``digest`` is the Merkle root a consumer pins; ``leaves`` is the full
    ``(relative path, leaf digest)`` list the root was built from, kept so
    :func:`verify_publication` can name the drifted files.
    """

    name: str
    kind: str
    version: str
    license: str
    digest: str
    leaves: tuple[tuple[str, str], ...]
    counts: Mapping[str, int]
    published_at: str = ""
    record_version: int = PUBLICATION_VERSION

    @property
    def leaf_count(self) -> int:
        return len(self.leaves)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "record_version": self.record_version,
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "license": self.license,
            "digest": self.digest,
            "leaf_count": self.leaf_count,
            "counts": {key: value for key, value in sorted(self.counts.items())},
            "published_at": self.published_at,
            "leaves": [{"path": path, "digest": digest} for path, digest in self.leaves],
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> PublicationRecord:
        """Parse a publication record; a malformed record is a contract error."""
        source = "publication record"
        digest = data.get("digest")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ValidationError(f"{source}: 'digest' must be a sha256 ref", kind="contract")
        leaves_raw = data.get("leaves", [])
        if not isinstance(leaves_raw, list):
            raise ValidationError(f"{source}: 'leaves' must be a list", kind="contract")
        leaves: list[tuple[str, str]] = []
        for item in cast("list[JSONValue]", leaves_raw):
            if not isinstance(item, dict):
                raise ValidationError(f"{source}: leaf entries must be objects", kind="contract")
            entry = cast("Mapping[str, JSONValue]", item)
            path = entry.get("path")
            leaf = entry.get("digest")
            if not isinstance(path, str) or not isinstance(leaf, str):
                raise ValidationError(
                    f"{source}: every leaf needs a string 'path' and 'digest'", kind="contract"
                )
            leaves.append((path, leaf))
        counts_raw = data.get("counts", {})
        counts: dict[str, int] = {}
        if isinstance(counts_raw, dict):
            for key, value in counts_raw.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    counts[str(key)] = value
        version_raw = data.get("record_version", PUBLICATION_VERSION)
        return cls(
            name=_text(data, "name"),
            kind=_text(data, "kind"),
            version=_text(data, "version"),
            license=_text(data, "license"),
            digest=digest,
            leaves=tuple(leaves),
            counts=counts,
            published_at=_text(data, "published_at"),
            record_version=version_raw if isinstance(version_raw, int) else PUBLICATION_VERSION,
        )


def _text(data: Mapping[str, JSONValue], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def publish_registry(root: Path, *, published_at: str = "") -> PublicationRecord:
    """Validate the tree at ``root`` end-to-end and return its publication record."""
    registry = load_registry(root)
    counts = validate_content(registry)
    return PublicationRecord(
        name=registry.manifest.name,
        kind=registry.kind,
        version=registry.manifest.version,
        license=registry.manifest.license,
        digest=merkle_digest(root),
        leaves=tree_leaves(root),
        counts=counts,
        published_at=published_at,
    )


def publication_drift(root: Path, record: PublicationRecord) -> tuple[LeafDrift, ...]:
    """Per-file differences between ``record`` and the tree at ``root``."""
    actual = dict(tree_leaves(root))
    expected = dict(record.leaves)
    drift: list[LeafDrift] = []
    for path in sorted(set(expected) | set(actual)):
        want = expected.get(path)
        have = actual.get(path)
        if want == have:
            continue
        status = "removed" if have is None else ("added" if want is None else "modified")
        drift.append(LeafDrift(path=path, status=status, expected=want, actual=have))
    return tuple(drift)


def verify_publication(root: Path, record: PublicationRecord) -> str:
    """Verify the tree at ``root`` against ``record``; return the verified digest.

    Fails closed with :class:`RegistryIntegrityError` whose ``data['drift']``
    lists every added/removed/modified file — the consumer's half of publishing.
    """
    digest = merkle_digest(root)
    if digest == record.digest:
        return digest
    drift = publication_drift(root, record)
    detail = ", ".join(f"{item.status} {item.path}" for item in drift[:8]) or "no file differs"
    error = RegistryIntegrityError(
        f"registry at {root} hashes to {digest} but publication record "
        f"{record.name!r} states {record.digest}; {detail}",
        expected=record.digest,
        actual=digest,
        root=root,
    )
    error.data["drift"] = [item.to_json() for item in drift]
    raise error
