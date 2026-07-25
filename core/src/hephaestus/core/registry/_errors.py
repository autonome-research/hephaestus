"""Typed refusals every registry operation raises.

One error class carries a stable machine ``reason`` token; the integrity
subclass additionally carries the digest pair that failed so a caller can report
exactly which tree drifted from its pin.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hephaestus.core.errors import HephaestusError
from opstore.types import JSONValue

__all__ = ["RegistryError", "RegistryIntegrityError"]


class RegistryError(HephaestusError):
    """A registry operation refused; ``reason`` is a stable machine token.

    Reasons: ``registry_integrity``, ``unknown_skill``, ``unknown_store_part``,
    ``invalid_params``, ``generator_failed``, ``capability_not_available``,
    ``sandbox_denied``, ``unsafe_refused``.
    """

    code = "registry_error"

    def __init__(
        self, reason: str, message: str, *, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.data: dict[str, JSONValue] = dict(data or {})


class RegistryIntegrityError(RegistryError):
    """A registry tree does not hash to its pin; loading fails closed."""

    code = "registry_integrity"

    def __init__(self, message: str, *, expected: str, actual: str, root: Path) -> None:
        super().__init__(
            "registry_integrity",
            message,
            data={"expected_digest": expected, "actual_digest": actual, "root": str(root)},
        )
        self.expected = expected
        self.actual = actual
        self.root = root
