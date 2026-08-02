"""Engine-side reader for ``schemas/bridge_limits.json`` (architecture §5).

The §5 numeric limits live in one JSON file; every side of the system loads that
same file rather than duplicating a literal. This module is the engine's loader,
so the CAD core can honour a §5 cap (the dual text budget on registry pages)
without importing the agent-facing tool contract — :mod:`hephaestus.core` must
not depend on :mod:`hephaestus.contract`.

An explicit override is honoured via the ``HEPHAESTUS_BRIDGE_LIMITS``
environment variable, matching the bridge and TypeScript loaders.
"""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any, Final

__all__ = ["limits_document", "limits_path"]

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
