# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Sew goldens and their provenance (``MESH_INGEST.md`` §8 Tier 3).

OCCT's sewing is a tolerance-driven merge whose output topology this project
does **not** claim is stable across OCCT builds. So a sew golden records what
§8 Tier 3 permits — face and vertex counts, the shell count, the
``BRepCheck_Analyzer`` verdict and the analyzer's status list — and **never
bytes**. That is the most a sew can honestly offer, and saying so is cheaper
than a flaky golden.

It is also valid for exactly one ``(container image digest, OCCT version)``
pair, which is ``verification.md``'s golden-provenance rule extended from the
renderer to the kernel. A mismatched pair **invalidates** the golden: this
module refuses to compare, by name, rather than comparing and reporting a
difference that says nothing about the code under test. An OCCT bump is a
re-baseline PR, exactly as a renderer digest bump is
(``repo_conventions.md``:186-194).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

__all__ = [
    "GOLDEN_DIR",
    "REBASELINE_ENV",
    "SewGoldenProvenanceError",
    "load_sew_golden",
    "rebaselining",
    "write_sew_golden",
]

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens"

#: Regeneration happens only through this switch, the meta-test contract
#: ``core/render/goldens.py`` already holds the renderer to: a golden that
#: rewrote itself on every run could never fail, which is the same as not having
#: one. Set it, run the suite, and commit the diff with the change that caused
#: it — that is the re-baseline PR ``verification.md`` asks for.
REBASELINE_ENV = "HEPHAESTUS_REBASELINE_SEW_GOLDENS"


def rebaselining() -> bool:
    """Whether this run is allowed to rewrite the committed sew goldens."""
    import os

    return bool(os.environ.get(REBASELINE_ENV))


class SewGoldenProvenanceError(AssertionError):
    """A sew golden was recorded for a different (image, OCCT) pair than this one.

    An ``AssertionError`` on purpose: the correct response to an invalidated
    golden is a re-baseline PR, and the failure must read like a demand for one
    rather than like a numeric mismatch a reader might paper over.
    """


def _paths(name: str, directory: Path | None = None) -> tuple[Path, Path]:
    root = GOLDEN_DIR if directory is None else directory
    return root / f"{name}.json", root / f"{name}.provenance.json"


def write_sew_golden(name: str, payload: dict[str, Any], *, directory: Path | None = None) -> None:
    """Record a sew golden and stamp the pair it is valid for."""
    from hephaestus.core.mesh_solid import sew_provenance

    root = GOLDEN_DIR if directory is None else directory
    root.mkdir(parents=True, exist_ok=True)
    golden_path, provenance_path = _paths(name, directory)
    golden_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    provenance_path.write_text(
        json.dumps(
            {
                "golden": f"{name}.json",
                "rule": (
                    "MESH_INGEST.md §8 Tier 3: valid only for this (container image "
                    "digest, OCCT version) pair. An OCCT bump is a re-baseline PR."
                ),
                "records": "counts and the BRepCheck verdict, never sewn bytes",
                **sew_provenance(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def load_sew_golden(
    name: str,
    *,
    provenance: dict[str, str] | None = None,
    directory: Path | None = None,
) -> dict[str, Any]:
    """The recorded golden, or a refusal when its provenance pair does not match.

    ``provenance`` overrides the live pair, which is how the gate proves the
    invalidation fires without needing a second OCCT installed.
    """
    from hephaestus.core.mesh_solid import sew_provenance

    golden_path, provenance_path = _paths(name, directory)
    if not golden_path.exists() or not provenance_path.exists():
        raise SewGoldenProvenanceError(
            f"sew golden {name!r} has no recorded provenance sidecar; a sew golden "
            "without its (image, OCCT) pair cannot be revalidated and is not a golden"
        )
    recorded = cast("dict[str, Any]", json.loads(provenance_path.read_text(encoding="utf-8")))
    live = dict(sew_provenance()) if provenance is None else dict(provenance)
    for key in ("image_digest", "occt_version"):
        if recorded.get(key) != live.get(key):
            raise SewGoldenProvenanceError(
                f"sew golden {name!r} was recorded for {key}={recorded.get(key)!r} and "
                f"this run is {live.get(key)!r}. The golden is INVALID for this pair "
                "and is not compared: OCCT's sewing is a tolerance-driven merge whose "
                "topology is not claimed stable across builds, so a difference here "
                "would say nothing about the code under test. Re-baseline in a PR "
                "carrying the bump (MESH_INGEST.md §8 Tier 3, verification.md)."
            )
    return cast("dict[str, Any]", json.loads(golden_path.read_text(encoding="utf-8")))
