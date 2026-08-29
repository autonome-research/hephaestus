# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Re-baseline ``tests/stage4/goldens/context/`` (``INTERFACE.md`` §7A.3, §19.19).

Run it, then **read the diff**. The context block is the one artefact in this
system that reaches a model's context window without a human reading it first,
which is exactly why §7A.3 asks for a golden family: "so a change to what the
agent is told is a diff in a review rather than a change nobody can see". A
re-baseline that is not reviewed defeats the entire mechanism.

It materializes and builds the public workspace fixture — the same one
``tests/stage4/conftest.py`` uses — and writes one ``<case>.txt`` per case in
:data:`hephaestus.testing.workspace_fixture.CONTEXT_GOLDEN_CASES`, which is the
same table the test reads, so the script and the test cannot disagree about
which cases exist.

    uv run python scripts/rebaseline_context_goldens.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path


def main() -> int:
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.http.context import compose_context, parse_envelope
    from hephaestus.http.runtime import (  # pyright: ignore[reportPrivateUsage]
        WorkspaceRuntime,
        _backend_for,  # pyright: ignore[reportPrivateUsage]
    )
    from hephaestus.testing.workspace_fixture import (
        CONTEXT_GOLDEN_CASES,
        CONTEXT_GOLDEN_DIR,
        GATE_PARTS,
        materialize_workspace_fixture,
        resolve_context_case,
        stage4_goldens,
    )

    scratch = Path(tempfile.mkdtemp(prefix="heph-context-goldens-"))
    try:
        root = scratch / "workspace"
        materialize_workspace_fixture(root)
        layout = load_project(root)
        store = open_store(layout)
        try:
            cad = CadOps(layout, store, backend=_backend_for(layout, True))
            for part in GATE_PARTS:
                result = cad.build_part(part, op_id=f"context-golden-{part}")
                if result.get("status") != "ok":
                    print(f"fixture part {part!r} did not build: {result}", file=sys.stderr)
                    return 1
        finally:
            store.close()

        runtime = WorkspaceRuntime.open(root, token="rebaseline", serve_mode=True)
        try:
            out = stage4_goldens() / CONTEXT_GOLDEN_DIR
            out.mkdir(parents=True, exist_ok=True)
            build = runtime.cad.current_build("tread")
            assert build is not None
            build_ref = str(build.artifact_ref)
            for name, envelope in CONTEXT_GOLDEN_CASES:
                resolved = resolve_context_case(envelope, build_ref)
                composed = compose_context(runtime, parse_envelope(resolved))
                (out / f"{name}.txt").write_text(composed.block, encoding="utf-8")
                print(f"wrote {out / f'{name}.txt'} ({len(composed.block)} bytes)")
        finally:
            runtime.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
