"""The local validity floor: is this STEP file a solid at all?

``EXTERNAL_EVAL.md`` §2/§3: the leaderboard's ground truth is private, so the
only thing an adapter can check locally is the gate that *zeroes* a sample —
validity. This module is that gate and nothing more: sealed (watertight),
positive volume, finite bounding box, read through ``geom.step_io``.

It is deliberately weaker than the benchmark's own ``is_valid`` (which also runs
``BRepCheck_Analyzer`` and a closed-orientable-manifold tessellation check).
That is why the benchmark's own ``sanity_check_submission.py`` is executed at
packaging time in addition to this: passing here is necessary, never sufficient,
and no output of this module is ever labelled a score.

Only ``hephaestus.geom`` is imported — no executor, no project store (COMPARE.md
§3: external scoring must run where those do not exist).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["ValidityFacts", "step_validity"]


@dataclass(frozen=True)
class ValidityFacts:
    """What was measured on one candidate STEP file, and why it failed if it did."""

    path: Path
    readable: bool
    sealed: bool
    volume_mm3: float
    bbox_mm: tuple[float, float, float]
    #: Named floor failures: ``unreadable_step``, ``unsealed``,
    #: ``non_positive_volume``, ``non_finite_bbox``.
    failures: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "readable": self.readable,
            "sealed": self.sealed,
            "volume_mm3": self.volume_mm3,
            "bbox_mm": list(self.bbox_mm),
            "failures": list(self.failures),
            "error": self.error,
        }


def step_validity(path: Path) -> ValidityFacts:
    """Apply the floor to one STEP file. An unreadable file fails; it never raises.

    A benchmark has to be able to report on a broken submission alongside the
    others — the same rule ``scoring.score_step_files`` follows.
    """
    from hephaestus.geom.metrics import bbox_mm, is_sealed, shape_volume
    from hephaestus.geom.step_io import StepReadError, read_step

    try:
        shape = read_step(path)
    except (StepReadError, OSError) as exc:
        return ValidityFacts(
            path=path,
            readable=False,
            sealed=False,
            volume_mm3=0.0,
            bbox_mm=(0.0, 0.0, 0.0),
            failures=("unreadable_step",),
            error=str(exc),
        )
    sealed = is_sealed(shape)
    volume = shape_volume(shape)
    try:
        bbox = bbox_mm(shape)
    except Exception as exc:  # pragma: no cover - a shape with no bounding box
        return ValidityFacts(
            path=path,
            readable=True,
            sealed=sealed,
            volume_mm3=volume,
            bbox_mm=(0.0, 0.0, 0.0),
            failures=("non_finite_bbox",),
            error=f"{type(exc).__name__}: {exc}",
        )
    failures: list[str] = []
    if not sealed:
        failures.append("unsealed")
    if not (volume > 0.0):
        failures.append("non_positive_volume")
    if not all(math.isfinite(value) for value in bbox):
        failures.append("non_finite_bbox")
    return ValidityFacts(
        path=path,
        readable=True,
        sealed=sealed,
        volume_mm3=volume,
        bbox_mm=bbox,
        failures=tuple(failures),
    )
