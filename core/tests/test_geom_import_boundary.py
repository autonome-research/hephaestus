"""Import-graph boundary for ``hephaestus.geom``: geometry without the engine.

:mod:`hephaestus.geom` states its contract in the package docstring — pure
geometry services over build123d/OCP shapes, with **no** executor, **no**
project store, and nothing from the server or agent packages. That contract is
what makes the geometry layer reusable outside the CAD pipeline (external
benchmark scoring, solid diffing, rule packs under test), so it is worth
enforcing mechanically rather than by review.

Two passes, mirroring ``tests/stage0a/test_import_boundary.py``:

- a static ``ast`` pass over every module under ``core/src/hephaestus/geom``,
  which pins the *declared* dependencies (an allowlist of leaf
  ``hephaestus.core`` value modules, plus the ``opstore.types`` JSON alias);
- a **subprocess** runtime pass that imports every ``hephaestus.geom`` module
  in a fresh interpreter and inspects ``sys.modules``. It has to be a
  subprocess: in a full-suite run the CAD suites have already imported the
  executor, so an in-process assertion would measure the session rather than
  the package boundary.

``opstore``: ``geom.kerf`` and ``geom.nesting`` take ``opstore.types`` for the
``JSONValue`` alias only, and reach it transitively through
``hephaestus.core.types``/``hephaestus.core.dfm.types`` besides. The alias is a
stdlib-only type declaration, not the durability substrate, so the static pass
pins the import to ``opstore.types`` and forbids every other ``opstore``
module (``db``, ``wal``, ``blobs``, ``leases``, …) — geometry may name the JSON
shape, it may never open a store.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "core" / "src" / "hephaestus" / "geom"

#: Leaf ``hephaestus.core`` modules geometry may depend on: error types, the
#: §8 value records, the addressing index and the cut-file layer convention.
#: None of them reaches the executor, the store or a sandbox.
ALLOWED_CORE_MODULES = frozenset(
    {
        "hephaestus.core.addressing",
        "hephaestus.core.cutfile",
        "hephaestus.core.dfm.types",
        "hephaestus.core.errors",
        "hephaestus.core.types",
    }
)

#: The only ``opstore`` module geometry may name (the ``JSONValue`` alias).
ALLOWED_OPSTORE_MODULES = frozenset({"opstore.types"})

#: Top-level packages that must never appear in the runtime import closure.
FORBIDDEN_TOP_LEVEL = frozenset({"agent", "pi", "thread_phase"})

#: Dotted prefixes that must never appear in the runtime import closure. The
#: executor and the project store are the two the package contract names; the
#: server-side packages follow because geometry must not know about agents.
FORBIDDEN_PREFIXES = (
    "hephaestus.core.executor",
    "hephaestus.core.project_store",
    "hephaestus.core.checks",
    "hephaestus.core.registry",
    "hephaestus.core.render",
    "hephaestus.core.cli",
    "hephaestus.core.lint",
    "hephaestus.core.toolgen",
    "hephaestus.core.tools_decl",
    "hephaestus.mcp",
    "hephaestus.agent_bridge",
    "hephaestus.bench",
    "hephaestus.contract",
)


def _module_files() -> list[Path]:
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, f"no modules found under {PACKAGE_DIR}"
    return files


def _dotted_names() -> list[str]:
    names: list[str] = []
    for path in _module_files():
        rel = path.relative_to(PACKAGE_DIR).with_suffix("")
        names.append(
            "hephaestus.geom"
            if rel.name == "__init__"
            else "hephaestus.geom." + ".".join(rel.parts)
        )
    return names


def _imported_modules(path: Path) -> set[str]:
    """Dotted module names imported by ``path`` (relative imports resolved)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add("hephaestus.geom")
            elif node.module is not None:
                names.add(node.module)
    return names


def test_declared_hephaestus_imports_stay_inside_the_allowlist() -> None:
    """No geom module may name a ``hephaestus`` module outside geom + the allowlist."""
    violations: list[str] = []
    for path in _module_files():
        for name in sorted(_imported_modules(path)):
            if not name.startswith("hephaestus"):
                continue
            if name == "hephaestus.geom" or name.startswith("hephaestus.geom."):
                continue
            if name in ALLOWED_CORE_MODULES:
                continue
            violations.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert not violations, "geom imports a hephaestus module outside its allowlist:\n" + "\n".join(
        violations
    )


def test_declared_opstore_imports_are_the_json_alias_only() -> None:
    """Geometry may name the JSON shape; it may never open a store."""
    violations: list[str] = []
    for path in _module_files():
        for name in sorted(_imported_modules(path)):
            if not (name == "opstore" or name.startswith("opstore.")):
                continue
            if name in ALLOWED_OPSTORE_MODULES:
                continue
            violations.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert not violations, "geom imports an opstore runtime module:\n" + "\n".join(violations)


def test_import_closure_excludes_executor_store_and_agents() -> None:
    """Importing every geom module in a fresh interpreter pulls in no forbidden module."""
    program = textwrap.dedent(
        """
        import importlib, json, sys
        for name in json.loads(sys.argv[1]):
            importlib.import_module(name)
        print(json.dumps(sorted(sys.modules)))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program, json.dumps(_dotted_names())],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"importing hephaestus.geom failed:\n{result.stderr}"
    loaded: list[str] = json.loads(result.stdout)

    forbidden = sorted(
        name
        for name in loaded
        if name.partition(".")[0] in FORBIDDEN_TOP_LEVEL
        or any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PREFIXES)
    )
    assert not forbidden, "hephaestus.geom pulled in forbidden modules:\n" + "\n".join(forbidden)


def test_geom_public_surface_is_importable_without_the_engine() -> None:
    """The advertised ``__all__`` resolves in a fresh interpreter, on its own."""
    program = textwrap.dedent(
        """
        import hephaestus.geom as geom
        missing = [n for n in geom.__all__ if not hasattr(geom, n)]
        assert not missing, missing
        print(len(geom.__all__))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"hephaestus.geom public surface broken:\n{result.stderr}"
    assert int(result.stdout.strip()) > 0
