"""Typed exceptions with stable structured error codes for hephaestus.core.

Vocabulary fixed by ``core/DESIGN.md``: ``addressing_error`` (carries
candidates), ``param_out_of_bounds`` (names the parameter),
``sandbox_denied``, ``unsafe_refused``, ``validation_error`` with kinds
``syntax | contract | sandbox | evaluation``, ``conflict``,
``incoherent_project_snapshot``, ``check_set_drift``,
``invalid_check_generation``. Callers dispatch on ``code`` (or the exception
type); message text is informational only.
"""

from __future__ import annotations

from typing import Literal

ValidationKind = Literal["syntax", "contract", "sandbox", "evaluation"]

VALIDATION_KINDS: tuple[ValidationKind, ...] = (
    "syntax",
    "contract",
    "sandbox",
    "evaluation",
)


class HephaestusError(Exception):
    """Base class for all hephaestus.core errors; carries a stable ``code``."""

    code: str = "hephaestus_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AddressingError(HephaestusError):
    """A geometry selector was ambiguous or resolved to nothing (§7).

    ``candidates`` lists the concrete resolvable names that matched
    ambiguously, or the near-misses when nothing matched — never empty
    prose without alternatives when alternatives exist.
    """

    code = "addressing_error"

    def __init__(
        self,
        message: str,
        *,
        selector: str,
        candidates: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.selector = selector
        self.candidates = candidates


class ParamOutOfBoundsError(HephaestusError):
    """A parameter override violated its declared bounds; names the parameter.

    ``params`` carries every offending parameter name (all-or-nothing merge
    reports the complete set); ``param`` is the first for convenience.
    """

    code = "param_out_of_bounds"

    def __init__(self, message: str, *, params: tuple[str, ...]) -> None:
        if not params:
            raise ValueError("ParamOutOfBoundsError requires at least one parameter name")
        super().__init__(message)
        self.params = params

    @property
    def param(self) -> str:
        """First offending parameter name."""
        return self.params[0]


class SandboxDeniedError(HephaestusError):
    """The secure sandbox denied an operation or is unavailable (fail closed)."""

    code = "sandbox_denied"


class UnsafeRefusedError(HephaestusError):
    """--unsafe-local-executor refused (registry content, serve, or not requested)."""

    code = "unsafe_refused"


class ValidationError(HephaestusError):
    """A script/input failed validation; ``kind`` discriminates the failure class."""

    code = "validation_error"

    def __init__(self, message: str, *, kind: ValidationKind) -> None:
        super().__init__(message)
        if kind not in VALIDATION_KINDS:
            raise ValueError(f"invalid validation kind: {kind!r}")
        self.kind: ValidationKind = kind


class ConflictError(HephaestusError):
    """Concurrent mutation conflict (e.g. external drift detected at publication)."""

    code = "conflict"


class IncoherentProjectSnapshotError(HephaestusError):
    """A project snapshot manifest failed its coherence check and was rejected."""

    code = "incoherent_project_snapshot"


class CheckSetDriftError(HephaestusError):
    """The check set changed while being captured; the capture was abandoned."""

    code = "check_set_drift"


class InvalidCheckGenerationError(HephaestusError):
    """The check-set generation is persisted invalid; execution fails closed."""

    code = "invalid_check_generation"
