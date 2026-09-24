# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Gate G14B clause 1: geom boundary tests admit ``toolpath`` as a pure service.

The authority is ``core/tests/test_geom_import_boundary.py`` — the AST
allowlist pass and the subprocess import-closure pass — run here **with
``toolpath`` present**, exactly as G8C admitted ``constraints`` and G9A
admitted ``kinematics``. The suite is executed as-is in a subprocess rather
than re-implemented, so this clause cannot drift from the boundary contract
it cites.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOUNDARY_SUITE = REPO / "core" / "tests" / "test_geom_import_boundary.py"


def test_toolpath_is_a_geom_module_the_boundary_suite_sees() -> None:
    """``hephaestus.geom.toolpath`` exists where the boundary tests discover it."""
    assert (REPO / "core" / "src" / "hephaestus" / "geom" / "toolpath.py").is_file()
    text = BOUNDARY_SUITE.read_text(encoding="utf-8")
    # The discovery is by rglob, so presence needs no allowlist edit; what the
    # allowlist must keep true is that toolpath's imports stay inside it.
    assert 'PACKAGE_DIR = REPO_ROOT / "core" / "src" / "hephaestus" / "geom"' in text


def test_boundary_suite_passes_with_toolpath_present() -> None:
    """Both boundary passes (AST allowlist + subprocess closure) stay green."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(BOUNDARY_SUITE), "-q"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
    )
    assert result.returncode == 0, f"geom boundary broke with toolpath:\n{result.stdout}"


def test_toolpath_imports_stay_inside_the_geom_allowlist() -> None:
    """A direct restatement of the AST rule for the new module, for locality."""
    import ast

    source = (REPO / "core" / "src" / "hephaestus" / "geom" / "toolpath.py").read_text("utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    hephaestus_imports = {name for name in imported if name.startswith("hephaestus")}
    assert hephaestus_imports <= {"hephaestus.core.cutfile"}, hephaestus_imports
    opstore_imports = {name for name in imported if name.startswith("opstore")}
    assert opstore_imports <= {"opstore.types"}, opstore_imports
