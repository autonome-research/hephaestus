"""The Merkle digest that pins a registry tree.

A registry's identity is the hash of its bytes: leaves bind path *and* content,
interior nodes are domain-separated, and the whole tree collapses to one
``sha256:<hex>`` root. Everything a project pins in ``hephaestus.toml`` and
everything ``heph registry update`` re-pins is a value produced here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Final

from hephaestus.core.errors import ValidationError

__all__ = ["merkle_digest", "tree_leaves"]

#: Path components never hashed (caches and VCS metadata are not content).
_IGNORED_COMPONENTS: Final[frozenset[str]] = frozenset({"__pycache__"})

_LEAF_TAG: Final[bytes] = b"heph-registry-leaf\x00"
_NODE_TAG: Final[bytes] = b"heph-registry-node\x00"
_EMPTY_TREE: Final[bytes] = b"heph-registry-empty"


def tree_leaves(root: Path) -> tuple[tuple[str, str], ...]:
    """``(posix relative path, leaf digest)`` for every file, path-sorted.

    Dotfiles/dot-directories and ``__pycache__`` are not content and are
    skipped; symlinks are not followed (a registry tree is plain bytes). The
    manifest itself is hashed like any other file, so tampering with
    ``registry.toml`` changes the digest too.
    """
    if not root.is_dir():
        raise ValidationError(f"registry root {root} is not a directory", kind="contract")
    leaves: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        parts = rel.parts
        if any(part.startswith(".") or part in _IGNORED_COMPONENTS for part in parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        rel_posix = PurePosixPath(*parts).as_posix()
        digest = hashlib.sha256(
            _LEAF_TAG + rel_posix.encode("utf-8") + b"\x00" + path.read_bytes()
        ).hexdigest()
        leaves.append((rel_posix, digest))
    return tuple(leaves)


def merkle_digest(root: Path) -> str:
    """``sha256:<hex>`` Merkle root over the registry tree.

    Leaves are ``sha256(tag || relative-path || NUL || content)`` sorted by
    relative path; interior nodes are ``sha256(tag || left || right)`` with an
    odd trailing node promoted unchanged. Path *and* content are bound into each
    leaf, so a rename is as detectable as an edit.
    """
    level: list[bytes] = [bytes.fromhex(digest) for _rel, digest in tree_leaves(root)]
    if not level:
        return "sha256:" + hashlib.sha256(_EMPTY_TREE).hexdigest()
    while len(level) > 1:
        nxt: list[bytes] = []
        for index in range(0, len(level) - 1, 2):
            nxt.append(hashlib.sha256(_NODE_TAG + level[index] + level[index + 1]).digest())
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return "sha256:" + level[0].hex()
