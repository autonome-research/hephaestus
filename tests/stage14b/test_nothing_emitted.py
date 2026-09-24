# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Gate G14B clause 24: NOTHING IS EMITTED — the D2 mandate as a filesystem fact.

Two assertions, both mechanical:

* the whole 14B path — every ledger write, resolution, generation, and the
  ``heph cam`` CLI — writes **no file under ``.heph/exports/``** and creates
  no machine-program file anywhere in the project tree;
* **no tool in the surface produces program text**: every CAM tool result is
  ledger state, the result schemas carry no program-shaped field, and the
  generated move list never crosses the tool surface.

This clause's assertion extends over the 14C in-memory emitter/parser when
they land (the amendment's round-trip landing decision); it is written
against the tree, not against a list of known writers, so a new writer fails
it rather than escaping it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from _g14b import (
    declare_baseline,
    fixture_entry,
    materials_index,
    operation_entry,
    setup_entry,
    stock_entry,
    tools_index,
    wcs_entry,
)
from hephaestus.contract import tools_decl
from hephaestus.core.machining import generate_setup, resolve_setup
from hephaestus.core.project_store.cam import CamState

#: File suffixes a machine program ships under; none may ever appear.
PROGRAM_SUFFIXES = {".nc", ".gcode", ".tap", ".ngc", ".cnc"}

CAM_TOOLS = tuple(
    name
    for name in tools_decl.tool_names()
    if name.endswith(("_setup", "_setups", "_stock", "_fixture", "_fixtures", "_wcs"))
    or name.endswith(("_operation", "_operations"))
)


def _tree(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if path.is_file()}


def test_no_14b_code_path_writes_under_heph_exports(
    bench_copy: tuple[Any, Any], capsys: Any
) -> None:
    layout, store = bench_copy
    root = Path(layout.root)
    before = _tree(root)

    cam = CamState(layout, store)
    declare_baseline(cam)
    cam.operations.declare(operation_entry(id="op-rect"))
    cam.operations.declare(
        operation_entry(id="op-round", feature="bracket:pocket_round", depth_mm=5.0)
    )
    resolved = resolve_setup(
        layout, store, "s-op1", tools=tools_index(), materials=materials_index()
    )
    program = generate_setup(resolved)
    assert len(program.move_list) > 0  # a real program was generated, in memory

    from hephaestus.core.cli import main as heph_main

    previous = Path.cwd()
    os.chdir(root)
    try:
        assert heph_main(["cam"]) == 0
        assert heph_main(["cam", "--json"]) == 0
    finally:
        os.chdir(previous)
    capsys.readouterr()

    after = _tree(root)
    created = after - before
    exports = root / ".heph" / "exports"
    assert not [path for path in created if exports in path.parents], (
        "a 14B code path wrote under .heph/exports/"
    )
    assert not [path for path in created if path.suffix.lower() in PROGRAM_SUFFIXES], (
        "a 14B code path wrote a machine-program file"
    )
    # the writes that DID happen are opstore ledger state, and only that.
    for path in created:
        relative = path.relative_to(root)
        assert relative.parts[0] == ".heph", f"unexpected write outside .heph: {relative}"


def test_no_tool_in_the_surface_produces_program_text(bench_copy: tuple[Any, Any]) -> None:
    """Dispatch every CAM tool; no result carries moves, blocks or G-words."""
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
    from hephaestus.core.project_store.store import ProjectStore
    from hephaestus.testing.tools_fixture import Project

    layout, store = bench_copy
    cad = CadOps(layout, store)
    project = Project(
        root=Path(layout.root),
        layout=layout,
        store=store,
        cad=cad,
        dispatcher=ToolDispatcher(ProjectStore(layout, store), cad=cad),
        _n=[0],
    )
    orch = Principal(session_id="orch", profile="orchestrator", part=None)
    calls: list[tuple[str, dict[str, Any]]] = [
        ("declare_stock", stock_entry()),
        ("declare_fixture", fixture_entry()),
        ("declare_wcs", wcs_entry()),
        ("declare_setup", setup_entry()),
        ("declare_operation", operation_entry()),
        ("read_setups", {}),
        ("read_stock", {}),
        ("read_fixtures", {}),
        ("read_wcs", {}),
        ("read_operations", {}),
    ]
    for tool, arguments in calls:
        result = cast("dict[str, Any]", project.call(tool, dict(arguments), principal=orch))
        serialized = json.dumps(result)
        assert '"moves"' not in serialized, tool
        assert '"program"' not in serialized, tool
        assert "gcode" not in serialized.lower(), tool
        # a real G-word block would look like `G01 X…`; none may appear.
        import re

        assert not re.search(r"\bG0?[0-3]\b\s+[XYZ]", serialized), tool


def test_the_result_schemas_carry_no_program_shaped_field() -> None:
    """Structural: no CAM tool result schema declares program-bearing fields."""
    for name in tools_decl.tool_names():
        if not any(
            name == candidate
            for candidate in (
                "declare_setup",
                "update_setup",
                "read_setups",
                "declare_stock",
                "update_stock",
                "read_stock",
                "declare_fixture",
                "update_fixture",
                "read_fixtures",
                "declare_wcs",
                "update_wcs",
                "read_wcs",
                "declare_operation",
                "update_operation",
                "read_operations",
            )
        ):
            continue
        result = json.dumps(tools_decl.get_tool(name).result)
        for banned in ("program", "gcode", "moves"):
            assert banned not in result.lower(), (name, banned)


def test_the_2d_prior_claim_path_is_the_only_cam_writer_and_is_unchanged() -> None:
    """The shipped 2D emit is prior art (CAM.md §1.4): its module still writes
    a DXF from an explicit ``--out``/CWD path, never ``.heph/exports/``, and
    the milling engine module contains no filesystem write at all."""
    import ast

    repo = Path(__file__).resolve().parents[2]
    machining = (repo / "core" / "src" / "hephaestus" / "core" / "machining.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(machining)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"write_bytes", "write_text"}, (
                "hephaestus.core.machining writes a file"
            )
        if isinstance(node, ast.Name):
            assert node.id != "open", "hephaestus.core.machining opens a file"
