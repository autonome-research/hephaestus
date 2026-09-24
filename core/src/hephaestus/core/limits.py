"""Engine-side reader for ``schemas/bridge_limits.json`` (architecture §5).

The §5 numeric limits live in one JSON file; every side of the system loads that
same file rather than duplicating a literal. This module is the engine's loader,
so the CAD core can honour a §5 cap (the dual text budget on registry pages)
without importing the agent-facing tool contract — :mod:`hephaestus.core` must
not depend on :mod:`hephaestus.contract`.

An explicit override is honoured via the ``HEPHAESTUS_BRIDGE_LIMITS``
environment variable, matching the bridge and TypeScript loaders.

Stage 14B adds the CAM sampling limits (CAM.md §5.3, §5.7) here as engine
constants next to the loader, so the declaration path
(:mod:`hephaestus.core.project_store.cam`), the resolution/generation path
(:mod:`hephaestus.core.machining`) and their gates all read one definition:

* :data:`CAM_SIM_SAMPLES_MAX` — the cap on the **computed total** simulation
  samples across every move of a setup, checked at **generation** time
  (``sample_cap_exceeded``), because the total is a function of generated
  toolpath length and does not exist at declaration;
* :data:`CAM_OP_PASS_BOUND_MAX` — the closed-form declaration-time sieve
  (``op_sample_bound_exceeded``): ``levels x loops_bound`` from an operation
  entry's own numbers and the named stock's extents, deliberately loose and
  deliberately **not** the sample cap;
* :func:`cam_min_resolvable_mm3` — the published §5.3 resolution-floor
  formula over ``(step_mm, r, doc_mm)`` with its two frozen constants,
  compared at **resolution** time (``budget_below_resolution``).
"""

from __future__ import annotations

import json
import math
import os
from importlib import resources
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CAM_KERNEL_NOISE_MM3",
    "CAM_OP_PASS_BOUND_MAX",
    "CAM_RESOLUTION_K",
    "CAM_SIM_SAMPLES_MAX",
    "cam_min_resolvable_mm3",
    "limits_document",
    "limits_path",
]

#: Cap on the computed per-setup simulation sample total (CAM.md §5.3/§5.7).
#: Checked at generation, where the total exists; the refusal names the total
#: and the operation whose moves pushed it over.
CAM_SIM_SAMPLES_MAX: Final[int] = 200000

#: Cap on the declaration-time ``levels x loops_bound`` pass product
#: (CAM.md §4.3/§5.7) — a cheap arithmetic sieve over an operation entry's own
#: declared numbers and the named stock's ``extents_mm``, with no registry, no
#: artifact and no geometry in the loop. It bounds passes, not samples.
CAM_OP_PASS_BOUND_MAX: Final[int] = 20000

#: Margin factor inside the §5.3 resolution-floor formula: a budget is
#: resolvable only an order of magnitude above the sampling artefact it must
#: be distinguished from — the same 10x separation CAM.md §4.4 demands of
#: every gate fixture.
CAM_RESOLUTION_K: Final[float] = 10.0

#: Absolute term inside that formula: three orders above ``OVERLAP_EPS_MM3 =
#: 1e-9`` (``geom/measure.py:59``), the repo's existing "this is not a real
#: overlap" epsilon. Neither constant is tuned.
CAM_KERNEL_NOISE_MM3: Final[float] = 1e-6


def cam_min_resolvable_mm3(step_mm: float, r_mm: float, doc_mm: float) -> float:
    """The §5.3 resolution floor: the smallest volume a budget may claim to reject.

    A swept solid is a union of discrete tool placements; between two
    placements spaced ``step_mm`` apart along a straight move the union
    under-fills a scallop whose maximum depth is the sagitta ``h`` over a
    chord of ``step_mm`` and an axial height bounded by ``doc_mm``. The floor
    is the frozen formula::

        max(CAM_KERNEL_NOISE_MM3, CAM_RESOLUTION_K * step_mm * h * doc_mm)
        where h = r - sqrt(max(0.0, r*r - (step_mm/2)**2))

    Compared at **resolution** time only (``budget_below_resolution``): the
    tool radius binds through an operation, and a setup entry names no tool.
    """
    for name, value in (("step_mm", step_mm), ("r_mm", r_mm), ("doc_mm", doc_mm)):
        if value <= 0.0 or not math.isfinite(value):
            raise ValueError(f"{name} must be a positive number (got {value})")
    sagitta = r_mm - math.sqrt(max(0.0, r_mm * r_mm - (step_mm / 2.0) * (step_mm / 2.0)))
    return max(CAM_KERNEL_NOISE_MM3, CAM_RESOLUTION_K * step_mm * sagitta * doc_mm)

#: Where ``core/hatch_build.py`` stages the repo's ``schemas/bridge_limits.json``.
_DATA_NAME: Final[str] = "_data/bridge_limits.json"


def limits_path() -> Path:
    """Locate ``schemas/bridge_limits.json``.

    Three layouts, in priority order:

    1. ``HEPHAESTUS_BRIDGE_LIMITS`` — an explicit override, matching the bridge
       and TypeScript loaders.
    2. **Packaged data.** The wheel ships the file at
       ``hephaestus/core/_data/bridge_limits.json``. There is no second copy in
       the source tree: ``core/hatch_build.py`` stages the repo's one
       ``schemas/bridge_limits.json`` at build time, so the single-source-of-truth
       property survives packaging rather than being traded away for it.
    3. The repo walk-up, for a source checkout or editable install.

    Step 2 is why an installed wheel works at all. This module is imported
    transitively by ``hephaestus.core.registry`` *at import time*, so before
    Stage 7H a wheel install failed on `import hephaestus.core` with
    ``FileNotFoundError`` — the walk-up climbs out of ``site-packages`` and
    finds nothing.
    """
    override = os.environ.get("HEPHAESTUS_BRIDGE_LIMITS")
    if override:
        return Path(override)

    packaged = Path(str(resources.files(__package__ or "hephaestus.core"))) / _DATA_NAME
    if packaged.is_file():
        return packaged

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "schemas" / "bridge_limits.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"schemas/bridge_limits.json not found: no packaged copy at {packaged}, "
        f"and none above {here}"
    )


def limits_document() -> dict[str, Any]:
    """The parsed limits document."""
    with limits_path().open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data
