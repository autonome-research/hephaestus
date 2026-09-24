# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""One reproducibility run for Gate G14C clause 16 (not a test module).

Invoked as ``python _g14c_run.py <project root>`` — a FRESH interpreter each
time, the ``tests/stage14a`` two-process precedent — it resolves and
generates the reference setup, runs the removal simulation, and prints one
canonical JSON document: the serialized move list's digest, the sample grid,
and the simulation record. Two processes must print identical bytes within
the pinned CI image.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def reproducibility_document(root: Path) -> dict[str, object]:
    import _g14c as g
    from hephaestus.core.assembly import AnchorResolver
    from hephaestus.core.cam_check import check_setup, grid_placements
    from hephaestus.core.machining import generate_setup, resolve_setup
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.publication import Publisher

    from opstore import sha256_bytes

    layout = load_project(root)
    store = open_store(layout)
    try:
        scratch = root / ".heph" / "repro-scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
        resolved = resolve_setup(
            layout, store, "s-op1", **g.check_kwargs(), scratch=scratch, resolver=resolver
        )
        program = generate_setup(resolved)
        steps = {op.entry.id: op.step_mm for op in resolved.operations}
        grid = [
            [op.op_id, index, [round(c, 9) for c in point]]
            for op in program.operations
            for index, point in grid_placements(op.moves, steps[op.op_id])
        ]
        status = check_setup(layout, store, "s-op1", **g.check_kwargs())
        assert status.simulation is not None, [dict(r) for r in status.refusals]
        return {
            "move_list_sha256": sha256_bytes(program.move_list.serialize()),
            "moves": len(program.move_list),
            "grid": grid,
            "simulation": status.simulation.to_json(),
        }
    finally:
        store.close()


def main() -> int:
    document = reproducibility_document(Path(sys.argv[1]))
    json.dump(document, sys.stdout, sort_keys=True, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
