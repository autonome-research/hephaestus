"""Canonical hashing for build inputs, reusing ``opstore.hashing``.

Provides the §8 ``input_hashes`` ingredients: script/source text hashes,
canonical effective-parameter hashing, the consumed-``hc`` projection hash,
the ``PARAMS`` declaration hash, and the pinned toolchain hash (python +
build123d + OCP exact versions via ``importlib.metadata``).

Every hash string is ``"sha256:<hex>"``; canonical JSON is sorted-key,
compact-separator, UTF-8 (``opstore.hashing.canonical_json``).
"""

from __future__ import annotations

import importlib.metadata
import math
import platform
from collections.abc import Mapping

from hephaestus.core.errors import ValidationError
from hephaestus.core.params import Param, params_declaration_json
from opstore.hashing import (
    canonical_json,
    is_hash,
    sha256_bytes,
    sha256_canonical_json,
)
from opstore.types import JSONValue

__all__ = [
    "canonical_json",
    "consumed_hc_hash",
    "effective_params_hash",
    "hash_text",
    "is_hash",
    "params_declaration_hash",
    "sha256_bytes",
    "sha256_canonical_json",
    "toolchain_fingerprint",
    "toolchain_hash",
]

#: Distribution names probed for the OCP kernel, in order (variant builds).
OCP_DIST_CANDIDATES: tuple[str, ...] = (
    "cadquery-ocp",
    "cadquery-ocp-novtk",
    "cadquery-ocp-proxy",
    "OCP",
)


def hash_text(text: str) -> str:
    """``"sha256:<hex>"`` of UTF-8 source text (script / globals.py hashing)."""
    return sha256_bytes(text.encode("utf-8"))


def _canonical_number(name: str, value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(
            f"parameter {name!r}: expected a number, got {type(value).__name__}",
            kind="contract",
        )
    if not math.isfinite(value):
        raise ValidationError(
            f"parameter {name!r}: non-finite value {value!r} cannot be hashed",
            kind="contract",
        )
    return value


def canonical_effective_params(params: Mapping[str, int | float]) -> dict[str, int | float]:
    """Validated canonical form of an effective-parameter mapping.

    Values must be finite numbers (bools rejected); int and float values stay
    distinct (``5`` and ``5.0`` hash differently, mirroring §3 type
    inference). Key order is irrelevant — hashing sorts keys.
    """
    return {name: _canonical_number(name, value) for name, value in params.items()}


def effective_params_hash(params: Mapping[str, int | float]) -> str:
    """§8 ``input_hashes.effective_params``: canonical hash of effective values."""
    canonical = canonical_effective_params(params)
    return sha256_canonical_json({k: canonical[k] for k in sorted(canonical)})


def consumed_hc_hash(consumed: Mapping[str, JSONValue]) -> str:
    """§8 ``input_hashes.hc_dependencies``: hash of the consumed-``hc`` projection.

    ``consumed`` maps exactly the ``hc`` names this part read to their
    effective values. Only this projection invalidates the part — full
    ``globals.py`` state is an audit hash, not an invalidator.
    """
    return sha256_canonical_json(dict(consumed))


def params_declaration_hash(params: Mapping[str, Param]) -> str:
    """§8 ``input_hashes.part_params``: hash of the ``PARAMS`` declaration."""
    return sha256_canonical_json(params_declaration_json(params))


def _dist_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def toolchain_fingerprint() -> dict[str, JSONValue]:
    """Exact toolchain identity: python, build123d, and OCP dist versions.

    OCP ships under variant distribution names; every installed candidate is
    recorded (name -> version, name-sorted) so the hash pins the exact kernel.
    Raises ``validation_error`` (kind ``contract``) if build123d or any OCP
    distribution is missing — an unpinnable toolchain must not hash.
    """
    build123d_version = _dist_version("build123d")
    if build123d_version is None:
        raise ValidationError("build123d distribution not installed", kind="contract")
    ocp: dict[str, JSONValue] = {}
    for name in OCP_DIST_CANDIDATES:
        version = _dist_version(name)
        if version is not None:
            ocp[name] = version
    if not ocp:
        raise ValidationError(
            f"no OCP distribution found (probed: {', '.join(OCP_DIST_CANDIDATES)})",
            kind="contract",
        )
    return {
        "python": platform.python_version(),
        "build123d": build123d_version,
        "ocp": {k: ocp[k] for k in sorted(ocp)},
    }


def toolchain_hash() -> str:
    """§8 ``input_hashes.toolchain``: canonical hash of the toolchain fingerprint."""
    return sha256_canonical_json(toolchain_fingerprint())
