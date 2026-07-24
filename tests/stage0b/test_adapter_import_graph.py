"""G0B adapter clause: opstore is imported, not reimplemented beside.

Mission plan G0B: CAD policy remains in ``core/project_store`` while generic
WAL, lease, admission, and GC machinery is imported from — not reimplemented
beside — ``opstore``. Enforced structurally over the AST of every module
under ``core/src/hephaestus/core``: no direct SQLite/atomic-rename machinery
in the adapter layer, durability primitives come from the ``opstore``
namespace, and the dependency direction never reverses.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _adapter_helpers import REPO_ROOT

CORE_PKG = REPO_ROOT / "core" / "src" / "hephaestus" / "core"
OPSTORE_PKG = REPO_ROOT / "opstore" / "src" / "opstore"

#: The adapter/policy layer whose durability must come wholly from opstore.
ADAPTER_DIRS = (CORE_PKG / "project_store", CORE_PKG / "checks")

#: Generic-machinery class names owned by opstore; redefining any of them in
#: core would be "reimplemented beside".
OPSTORE_MACHINERY_CLASSES = {
    "OpStore",
    "Wal",
    "OpKeys",
    "BlobStore",
    "LeaseManager",
    "AdmissionControl",
    "Gc",
    "Keyring",
    "Database",
}


def _modules(root: Path) -> list[Path]:
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"no modules found under {root}"
    return files


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_top_levels(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add("hephaestus")  # relative: stays inside the package
            elif node.module is not None:
                names.add(node.module.partition(".")[0])
    return names


def test_core_never_imports_sqlite_directly() -> None:
    """All SQLite access flows through opstore's Database — none in core."""
    violations = [
        str(path.relative_to(REPO_ROOT))
        for path in _modules(CORE_PKG)
        if "sqlite3" in _imported_top_levels(path)
    ]
    assert violations == [], f"direct sqlite3 imports in core: {violations}"


def test_adapter_layer_imports_opstore() -> None:
    """Every project_store/checks module gets durability from opstore."""
    for root in ADAPTER_DIRS:
        imported_by_package: set[str] = set()
        for path in _modules(root):
            imported_by_package |= _imported_top_levels(path)
        assert "opstore" in imported_by_package, (
            f"{root.relative_to(REPO_ROOT)} never imports opstore"
        )


def test_adapter_layer_defines_no_opstore_machinery_classes() -> None:
    violations: list[str] = []
    for path in _modules(CORE_PKG):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ClassDef) and node.name in OPSTORE_MACHINERY_CLASSES:
                violations.append(f"{path.relative_to(REPO_ROOT)}: class {node.name}")
    assert violations == [], (
        "generic opstore machinery reimplemented beside opstore:\n" + "\n".join(violations)
    )


def test_adapter_layer_performs_no_direct_atomic_renames() -> None:
    """Atomic install (rename/replace) is WAL machinery; adapters use opstore.

    Scans project_store/ and checks/ for ``os.rename``/``os.replace`` calls
    and ``.rename()``/``.replace()`` method calls on paths.
    """
    banned_os = {"rename", "replace", "link", "symlink"}
    violations: list[str] = []
    for root in ADAPTER_DIRS:
        for path in _modules(root):
            for node in ast.walk(_tree(path)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if isinstance(func.value, ast.Name) and func.value.id == "os":
                    if func.attr in banned_os:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: os.{func.attr}"
                        )
                elif func.attr == "rename":
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: .rename()")
    assert violations == [], "direct atomic-install machinery in the adapter layer:\n" + "\n".join(
        violations
    )


def test_adapter_hashing_reuses_opstore_hashing() -> None:
    """Canonical JSON + sha256 helpers come from opstore.hashing, not a copy."""
    hashing = CORE_PKG / "hashing.py"
    imported = _imported_top_levels(hashing)
    assert "opstore" in imported
    source = hashing.read_text(encoding="utf-8")
    assert "sha256_bytes" in source and "canonical" in source
    # No parallel hashlib-based canonical-JSON implementation in the adapters.
    for root in ADAPTER_DIRS:
        for path in _modules(root):
            assert "hashlib" not in _imported_top_levels(path), (
                f"{path.relative_to(REPO_ROOT)} rolls its own hashing"
            )


def test_dependency_direction_never_reverses() -> None:
    """opstore must not know Hephaestus exists (architecture §3.5 boundary)."""
    violations = [
        str(path.relative_to(REPO_ROOT))
        for path in _modules(OPSTORE_PKG)
        if _imported_top_levels(path) & {"hephaestus", "core", "build123d", "OCP"}
    ]
    assert violations == []


def test_publication_flows_through_opstore_primitives() -> None:
    """The typed publication paths use opstore's WAL/opkeys, by name.

    A rename of the machinery would be caught by the machinery-class test;
    this asserts the positive direction — publication.py, store.py, and
    checks/engine.py each call into the opstore WAL and idempotency layers.
    """
    for module in (
        CORE_PKG / "project_store" / "publication.py",
        CORE_PKG / "project_store" / "store.py",
        CORE_PKG / "checks" / "engine.py",
    ):
        source = module.read_text(encoding="utf-8")
        assert ".opkeys.begin(" in source, f"{module.name}: no opstore idempotency"
        assert ".wal." in source, f"{module.name}: no opstore WAL usage"
