# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Synthesize a scan fixture from an analytic solid (``MESH_INGEST.md`` §7.5).

    uv run python scripts/synthesize_scan_fixture.py --check
    uv run python scripts/synthesize_scan_fixture.py --write

A real limb scan has no ground truth: nobody knows where the limb's surface
*actually* was, so a corpus task seeded with one could only ever grade a part
against another measurement. Every scan fixture in this repository is therefore
**synthesized from an analytic solid** — tessellate, export, seed — which is the
only way the corpus and the §6.6 round-trip clause can have a truth to compare
against. The analytic solid is the answer; the mesh is what a scanner would have
handed you if it had been perfect.

What this deliberately does NOT do:

* it does not add noise, holes or drift. A fixture whose defects were invented
  here would grade a run against this script's imagination of a scanner. The
  §3 quality record's job is to *report* the defects a real file carries;
  fabricating some would make the corpus measure the fabrication.
* it does not weld or reorder. The exported STL is the tessellator's own output,
  so the fixture exercises the whole §1.5 pipeline — including the weld — rather
  than arriving pre-canonicalized.

Determinism: the fixtures are **committed**, and ``--check`` re-synthesizes them
and compares bytes. OCCT's tessellation is deterministic for a pinned kernel, so
a mismatch means the kernel moved, which is a re-baseline decision (a PR), not
something a test run may do silently. That is the ``verification.md`` golden rule
applied to an input rather than to an output.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Fixture:
    """One synthesized scan: where it lands, and the solid it is the truth of."""

    path: Path
    #: Built lazily: importing build123d costs seconds and ``--help`` should not.
    solid: Callable[[], Any]
    note: str


def _cylinder() -> Any:
    from build123d import Cylinder

    return Cylinder(radius=25.0, height=60.0)


def _boss() -> Any:
    from build123d import Box

    return Box(40.0, 30.0, 20.0)


FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        path=REPO / "corpus" / "tasks" / "scan-socket-cuff" / "seed" / "imports" / "limb.stl",
        solid=_cylinder,
        note="R25 x 60 cylinder: the residual-limb stand-in whose clearance is computable",
    ),
    Fixture(
        path=REPO / "corpus" / "tasks" / "scan-boss-relief" / "seed" / "imports" / "boss.stl",
        solid=_boss,
        note="40 x 30 x 20 box: a scanned boss a relief frame must clear on four sides",
    ),
)


def synthesize(fixture: Fixture) -> bytes:
    """``tessellate -> export`` for one fixture, through the harness's own renderer.

    The renderer is used rather than a second tessellator for the reason
    ``MESH_INGEST.md`` §2.1 gives: ``render.tessellate`` owns B-rep -> triangles
    and its deflection constants are golden provenance. A fixture generator with
    its own deflections would be a second implementation of exactly that.
    """
    import numpy as np
    import trimesh
    from hephaestus.core.render.tessellate import tessellate

    tessellation = tessellate(cast("Any", fixture.solid()))
    vertex_blocks: list[Any] = []
    triangle_blocks: list[Any] = []
    offset = 0
    for solid in tessellation.solids:
        for face in solid.faces:
            points = np.asarray(face.vertices, dtype=np.float64).reshape(-1, 3)
            triangles = np.asarray(face.triangles, dtype=np.int64).reshape(-1, 3)
            vertex_blocks.append(points)
            triangle_blocks.append(triangles + offset)
            offset += points.shape[0]
    mesh = trimesh.Trimesh(
        vertices=np.vstack(vertex_blocks), faces=np.vstack(triangle_blocks), process=False
    )
    data = mesh.export(file_type="stl")
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="(re)write every fixture")
    group.add_argument("--check", action="store_true", help="re-synthesize and compare bytes")
    args = parser.parse_args(argv)

    failed = False
    for fixture in FIXTURES:
        data = synthesize(fixture)
        rel = fixture.path.relative_to(REPO)
        if args.write:
            fixture.path.parent.mkdir(parents=True, exist_ok=True)
            fixture.path.write_bytes(data)
            print(f"wrote {rel} ({len(data)} bytes) — {fixture.note}")
            continue
        if not fixture.path.is_file():
            print(f"MISSING {rel}", file=sys.stderr)
            failed = True
        elif fixture.path.read_bytes() != data:
            print(
                f"DRIFT {rel}: the committed fixture is not what this kernel "
                "tessellates. That is a re-baseline decision, not a test failure to "
                "paper over — MESH_INGEST.md §8 Tier 3.",
                file=sys.stderr,
            )
            failed = True
        else:
            print(f"ok {rel}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
