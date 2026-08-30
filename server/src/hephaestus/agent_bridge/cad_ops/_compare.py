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
from hephaestus.core.scan_compare import (
    SCAN_TARGET_PREFIX,
    ProjectScanComparer,
    ScanRefusal,
    ScanTimeout,
)
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = [
    "ALIGN_MODES",
    "IMPORT_TARGET_PREFIX",
    "PART_TARGET_PREFIX",
    "SCAN_ALIGN_MODES",
    "SCAN_TARGET_PREFIX",
    "CompareOps",
]

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

#: The ``MESH_INGEST.md`` §6.5 alignment modes for ``compare_to_scan``.
#: ``principal`` is deliberately not here: it is refused by name.
SCAN_ALIGN_MODES: Final[tuple[str, ...]] = ("as_posed", "declared")

#: :class:`~hephaestus.core.scan_compare.ScanRefusal.reason` -> the tool's
#: refusal token. The §10 comparison codes pass through UNCHANGED — a model
#: branching on ``scan_principal_unavailable`` or ``scan_neighborhood_overflow``
#: is branching on the fact the geometry layer stated, not on a token this
#: layer invented for it — and only this layer's own operand vocabulary is
#: mapped onto the generic ``invalid_params``.
_SCAN_REFUSALS: Final[dict[str, str]] = {
    "scan_timeout": "scan_timeout",
    "scan_target_unsupported": "scan_target_unsupported",
    "scan_principal_unavailable": "scan_principal_unavailable",
    "scan_iou_unavailable": "scan_iou_unavailable",
    "scan_neighborhood_overflow": "scan_neighborhood_overflow",
    # A comparison with nothing to sample on one side (§6.4, §10). It reaches
    # here as its own token rather than as ``invalid_params`` for the reason the
    # rest do: the model's next move differs — "give the part surface to
    # measure" is not "you passed a bad parameter" — and a §10 code flattened
    # into a generic one at the tool boundary is a named refusal the caller
    # cannot act on.
    "scan_unmeasurable": "scan_unmeasurable",
    "declared_transform_not_rigid": "declared_transform_not_rigid",
    "invalid_align": "invalid_params",
    "invalid_target": "invalid_params",
    "missing_artifact": "invalid_params",
    "unreadable_scan": "unreadable_scan",
}

#: :class:`CompareRefusal.reason` -> the tool's refusal token.
_COMPARE_REFUSALS: Final[dict[str, str]] = {
    "compare_timeout": "compare_timeout",
    "invalid_align": "invalid_params",
    "invalid_target": "invalid_params",
    "missing_artifact": "invalid_params",
    "no_solid_geometry": "no_solid_geometry",
    "scan_target_unsupported": "scan_target_unsupported",
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

    def compare_to_scan(
        self,
        part: str,
        scan: str,
        *,
        units: str,
        align: str = "as_posed",
        declared_transform: list[float] | None = None,
    ) -> dict[str, Any]:
        """Measure ``part``'s current build against a scan (``MESH_INGEST.md`` §7.2).

        The one new tool of Stage 12, and it is thin for the same reason
        ``compare_solids`` is: operand resolution and the measurement live in
        :mod:`hephaestus.core.scan_compare` because ``heph scan check`` resolves
        the same two operands, so the number an operator sees and the number a
        model sees are the same number.

        ``scan`` accepts either the bare ``imports/``-relative path or the
        ``scan:`` prefixed form the ``CHECKS`` facade uses — the same string a
        script would write, so a model reading a failing ``m.scan_diff`` can
        paste the target straight in.
        """
        # Imported here, not at module scope: ``geom.compare`` pulls OCP (1.7 s
        # measured), and the agent bridge is imported to answer a schema request
        # as often as to run a comparison.
        from hephaestus.geom.compare import ScanCompareError

        target = scan if scan.startswith(SCAN_TARGET_PREFIX) else f"{SCAN_TARGET_PREFIX}{scan}"
        comparer = ProjectScanComparer(self._layout, self._store)
        with self._scratch("heph-scan-") as scratch:
            try:
                comparison = comparer.compare(
                    part,
                    target,
                    units=units,
                    align=align,
                    declared_transform=declared_transform,
                    scratch=Path(scratch),
                )
            except ImportResolutionError as exc:
                raise CadOpError(
                    _IMPORT_REFUSALS.get(exc.reason, "unknown_import"),
                    exc.message,
                    data={"path": exc.path, "reason": exc.reason},
                ) from exc
            except ScanTimeout as exc:
                # §7.3: the ceiling kill is a structured refusal the model can
                # read — the cheap facts it did compute ride inline, and
                # ``lost`` names the directions that never arrived.
                raise CadOpError(
                    "scan_timeout",
                    exc.message,
                    data={
                        "timeout_s": exc.timeout_s,
                        "partial": cast("JSONValue", exc.partial),
                        "lost": cast("JSONValue", list(exc.lost)),
                    },
                ) from exc
            except ScanRefusal as exc:
                raise CadOpError(
                    _SCAN_REFUSALS.get(exc.reason, "invalid_params"),
                    exc.message,
                    data={"reason": exc.reason},
                ) from exc
            except ScanCompareError as exc:
                # The geom layer's own refusal type, which is NOT a
                # ``ScanRefusal``: ``align="principal"`` is refused by
                # ``refuse_scan_principal`` before any operand is resolved, and
                # ``scan_unmeasurable`` can be raised on a direct (unbounded)
                # call. Until the third repair pass neither was caught here, so
                # the tool let a named §10 refusal escape as an internal error —
                # "never letting one escape as an internal error" is this
                # module's own stated job, and this is the case it missed.
                raise CadOpError(
                    _SCAN_REFUSALS.get(exc.reason, "invalid_params"),
                    exc.message,
                    data={"reason": exc.reason},
                ) from exc
        return dict(comparison.to_json())
