"""Typed refusals every registry operation raises.

One error class carries a stable machine ``reason`` token; the integrity
subclass additionally carries the digest pair that failed so a caller can report
exactly which tree drifted from its pin.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hephaestus.core.errors import HephaestusError, ValidationError
from opstore.types import JSONValue

__all__ = ["RegistryError", "RegistryIntegrityError", "RegistryRefusal"]


class RegistryRefusal(ValidationError):
    """A registry *content* rule refused, carrying a stable machine ``reason``.

    ``PARTS_STORE.md`` §1 names every component-record refusal as a token
    (``unknown_component_kind``, ``missing_required_interface``, …) and the
    gates assert the token, not the prose. Index-time refusals must nevertheless
    stay :class:`ValidationError`\\ s: ``validate_content`` runs inside
    ``publish_registry`` and ``heph registry publish`` reports a
    ``ValidationError`` as "does not validate and was not published"
    (``cli_registry.py``). Subclassing rather than introducing a parallel error
    class is what keeps one refusal path (mission rule 6) while still giving the
    caller a token to branch on; the token is also prefixed onto the message so
    the CLI names it without knowing the type.
    """

    def __init__(
        self, reason: str, message: str, *, detail: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(f"{reason}: {message}", kind="contract")
        self.reason = reason
        self.detail: dict[str, JSONValue] = dict(detail or {})


class RegistryError(HephaestusError):
    """A registry operation refused; ``reason`` is a stable machine token.

    Reasons: ``registry_integrity``, ``unknown_skill``, ``unknown_store_part``,
    ``ambiguous_component_id``, ``invalid_params``, ``generator_failed``,
    ``capability_not_available``, ``sandbox_denied``, ``unsafe_refused``,
    ``invalid_instance_name``, ``interface_class_mismatch``,
    ``interface_not_placed``, ``interface_placement_drift``,
    ``computed_mass_disagreement``, ``unsourced_component_datum``.
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
