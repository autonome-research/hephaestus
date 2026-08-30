# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Run one snippet in a FRESH interpreter and read its JSON back.

``MESH_INGEST.md`` §8 binds two of its three determinism tiers *across
processes*, and the reason is not ceremony: numpy's reduction order, dict
iteration and OCCT's own internal caches are all per-process state, and an
in-process "run it twice" assertion would agree with itself for reasons that
have nothing to do with reproducibility. So these clauses spawn.

Each call pays a full ``build123d`` import (~2.3 s), which is why the suite
spawns twice per clause and no more.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

__all__ = ["run_json"]

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_json(body: str, *, timeout_s: float = 600.0) -> dict[str, Any]:
    """Run ``body`` in a fresh interpreter; it must ``print(json.dumps(...))`` once.

    ``sys.path`` carries this directory so the snippet can import ``_g12b``, and
    the repo root so it can find the product exactly as the suite does.
    """
    script = textwrap.dedent(
        f"""
        import json, sys
        sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
        sys.path.insert(0, {str(REPO_ROOT)!r})
        {textwrap.indent(textwrap.dedent(body), " " * 8).lstrip()}
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=REPO_ROOT,
        check=False,
    )
    assert completed.returncode == 0, (
        f"determinism child failed ({completed.returncode}):\n{completed.stderr[-4000:]}"
    )
    payload = completed.stdout.strip().splitlines()[-1]
    return cast("dict[str, Any]", json.loads(payload))
