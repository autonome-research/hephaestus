"""G0A import-graph boundary: opstore imports only the stdlib and itself.

Walks every module under ``opstore/src/opstore`` with ``ast`` and asserts:

- every import resolves to the stdlib or to ``opstore`` itself;
- no forbidden domain/runtime imports (build123d, OCP, hephaestus/core, Pi,
  thread-phase, node bindings, third-party packages);
- no module in the package imports ``subprocess`` at all, so opstore cannot
  spawn node/pi/thread-phase (or anything else).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "opstore" / "src" / "opstore"

FORBIDDEN_TOP_LEVEL = {
    "build123d",
    "OCP",
    "hephaestus",
    "core",
    "pi",
    "thread_phase",
    "node",
    "subprocess",
}


def _module_files() -> list[Path]:
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, f"no modules found under {PACKAGE_DIR}"
    return files


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import stays inside the package
                names.add("opstore")
            elif node.module is not None:
                names.add(node.module.partition(".")[0])
    return names


def test_every_import_is_stdlib_or_opstore() -> None:
    allowed = set(sys.stdlib_module_names) | {"opstore"}
    violations: list[str] = []
    for path in _module_files():
        for name in sorted(_imported_top_levels(path)):
            if name not in allowed:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert not violations, "non-stdlib/non-opstore imports found:\n" + "\n".join(violations)


def test_no_forbidden_imports() -> None:
    violations: list[str] = []
    for path in _module_files():
        for name in sorted(_imported_top_levels(path) & FORBIDDEN_TOP_LEVEL):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert not violations, "forbidden imports found:\n" + "\n".join(violations)


def test_import_graph_closure_via_runtime() -> None:
    """Belt and braces: importing every opstore module pulls in no forbidden module."""
    import importlib

    for path in _module_files():
        rel = path.relative_to(PACKAGE_DIR).with_suffix("")
        dotted = "opstore" if rel.name == "__init__" else "opstore." + ".".join(rel.parts)
        importlib.import_module(dotted)
    loaded = {name.partition(".")[0] for name in sys.modules}
    assert not loaded & (FORBIDDEN_TOP_LEVEL - {"subprocess"})
