"""sha256 content-addressing helpers.

Contract (DESIGN.md "Core conventions"): every hash string is
``"sha256:" + hexdigest``. Canonical payload hash = sha256 over canonical JSON
(sorted keys, ``separators=(",", ":")``, ``ensure_ascii=False``, UTF-8). No
Unicode normalization is applied.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from opstore.types import JSONValue

HASH_PREFIX = "sha256:"
_HASH_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_CHUNK = 1 << 20


def sha256_bytes(data: bytes) -> str:
    """``"sha256:<hex>"`` of raw bytes."""
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """``"sha256:<hex>"`` of a file's contents, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return HASH_PREFIX + digest.hexdigest()


def canonical_json(value: JSONValue) -> str:
    """Canonical JSON text: sorted keys, compact separators, raw (non-ASCII) unicode."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_canonical_json(value: JSONValue) -> str:
    """Canonical payload hash: sha256 over UTF-8 canonical JSON."""
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def is_hash(value: str) -> bool:
    """True iff ``value`` is a well-formed ``sha256:<64 lowercase hex>`` string."""
    return _HASH_RE.match(value) is not None


def hex_of(value: str) -> str:
    """Hex digest portion of a well-formed hash string (raises ValueError otherwise)."""
    if not is_hash(value):
        raise ValueError(f"not a sha256 hash string: {value!r}")
    return value[len(HASH_PREFIX) :]
