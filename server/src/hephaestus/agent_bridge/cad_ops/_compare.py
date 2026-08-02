"""``compare_solids``: how far a part is from a target, as facts (COMPARE.md §2).

The editing loop's convergence signal. ``import_step`` puts a vendor solid in
the project, the model edits, and this tool answers "how far am I from it?" — so
the *harness* measures convergence instead of the model asserting it.

Deliberately thin. Operand resolution and the measurement live in
:mod:`hephaestus.core.project_compare` because ``heph diff`` resolves the same
two operands and must produce the same numbers; all this module owns is the
model-facing half — turning each named core refusal into the stable machine
token a model branches on, and never letting one escape as an internal error.

Read-only and freely retryable: nothing here writes, publishes or stores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.executor.imports import ImportResolutionError
from hephaestus.core.project_compare import (
    ALIGN_MODES,
    IMPORT_TARGET_PREFIX,
    PART_TARGET_PREFIX,
    CompareRefusal,
    CompareTimeout,
    ProjectComparer,
)
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["ALIGN_MODES", "IMPORT_TARGET_PREFIX", "PART_TARGET_PREFIX", "CompareOps"]

#: ``ImportResolutionError.reason`` -> the tool's refusal token. The resolver's
#: own vocabulary is preserved rather than flattened to one code: "the file is
#: not there" and "that path leaves the project" are different facts, and a
#: model must be able to tell them apart.
_IMPORT_REFUSALS: Final[dict[str, str]] = {
    "invalid_import_path": "invalid_import_path",
    "import_not_found": "unknown_import",
    "path_confinement": "path_confinement",
    "unreadable_import": "unreadable_import",
    "unreadable_step": "unreadable_step",
}

#: :class:`CompareRefusal.reason` -> the tool's refusal token.
_COMPARE_REFUSALS: Final[dict[str, str]] = {
    "compare_timeout": "compare_timeout",
    "invalid_align": "invalid_params",
    "invalid_target": "invalid_params",
    "missing_artifact": "invalid_params",
    "no_solid_geometry": "no_solid_geometry",
    "unreadable_step": "unreadable_step",
}


class CompareOps(CadOpsState):
    """The ``compare_solids`` tool (COMPARE.md §2)."""

    def compare_solids(self, part: str, target: str, *, align: str = "as_posed") -> dict[str, Any]:
        """Compare ``part``'s current build against ``target``; return the facts."""
        comparer = ProjectComparer(self._layout, self._store)
        with self._scratch("heph-compare-") as scratch:
            try:
                comparison = comparer.compare(part, target, align=align, scratch=Path(scratch))
            except ImportResolutionError as exc:
                raise CadOpError(
                    _IMPORT_REFUSALS.get(exc.reason, "unknown_import"),
                    exc.message,
                    data={"path": exc.path, "reason": exc.reason},
                ) from exc
            except CompareTimeout as exc:
                # COMPARE.md §5: the ceiling kill is a structured refusal the
                # model can read — the streamed partial facts ride inline, and
                # ``lost`` names the halves that never arrived.
                raise CadOpError(
                    "compare_timeout",
                    exc.message,
                    data={
                        "timeout_s": exc.timeout_s,
                        "partial": cast("JSONValue", exc.partial),
                        "lost": cast("JSONValue", list(exc.lost)),
                    },
                ) from exc
            except CompareRefusal as exc:
                raise CadOpError(
                    _COMPARE_REFUSALS.get(exc.reason, "invalid_params"), exc.message
                ) from exc
        return dict(comparison.to_json())
