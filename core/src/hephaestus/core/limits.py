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
from pathlib import Path
from typing import Any

__all__ = ["limits_document", "limits_path"]


def limits_path() -> Path:
    """Locate ``schemas/bridge_limits.json`` by walking up from this module."""
    override = os.environ.get("HEPHAESTUS_BRIDGE_LIMITS")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "schemas" / "bridge_limits.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("schemas/bridge_limits.json not found above " + str(here))


def limits_document() -> dict[str, Any]:
    """The parsed limits document."""
    with limits_path().open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data
