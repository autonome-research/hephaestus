# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""No consumer package reads the shared store connection without ``reading()``.

`opstore/tests/test_db_read_lock.py` already asserts this — for
`opstore/src/opstore` alone. The rule it enforces is not local to that package:
`Database` hands out ONE connection shared by every thread
(``check_same_thread=False``), and `Database.reading`'s own docstring names the
consequence of going around it, ``sqlite3.InterfaceError: bad parameter or
other API misuse``, raised "from a thread that had nothing to do with the code
that caused it".

The packages that consume the store had no such check, and thirteen reads had
accumulated on the bare connection across five modules. One of them fired: `GET
/parts/{part}/exports` answered **500 internal_error** with that exact
`InterfaceError` out of `export_records` (CI run 34418449613,
`web/e2e/export.spec.ts`). Every HTTP read handler runs on a worker thread
(``asyncio.to_thread``), so each of the thirteen was one concurrent write away
from the same 500.

**Why this is structural and not a reproduction.** The interleaving is not
reproducible in-process on CPython 3.13 — the `sqlite3` module serializes
`execute` on one connection object, so a two-thread loop here goes green while
the property is broken. That is precisely what makes a scan the mechanism and a
scenario test a decoy: the guarantee has to hold for the read nobody has
written yet, and only the source can be asked about that.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

#: The packages that consume `opstore` and therefore inherit its threading rule.
#: `opstore` itself is covered by `opstore/tests/test_db_read_lock.py`, which
#: also licenses `db.py`'s own BEGIN/COMMIT/ROLLBACK.
_ROOTS: Final[tuple[str, ...]] = ("server/src", "core/src", "contract/src", "bench/src")


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "schemas" / "bridge_limits.json").is_file():
            return parent
    raise AssertionError("repository root not found")


def _literal(node: ast.expr) -> str:
    """A string literal or f-string's literal parts; ``""`` for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "…"`` strings, so a SQL constant can be resolved.

    The schema bootstraps are written as constants (``_CREATE_TABLE``), and a
    scan that could not follow one name would have to either flag them — noise
    on a statement that has nobody to race — or exempt every unreadable
    argument, which is the hole this check exists to close.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        value = getattr(node, "value", None)
        if value is None:
            continue
        text = _literal(value)
        if not text:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = text
    return constants


def _sql_text(node: ast.expr, constants: dict[str, str]) -> str:
    """The SQL a call site passes, resolving a module-level constant by name."""
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    return _literal(node)


#: The only statements allowed on the bare connection: schema bootstrap, run
#: once while a store is being constructed. Everything else — a read, a write,
#: or SQL this scan cannot read because it was built in a variable — must take
#: `reading()` or `transaction()`.
_CONSTRUCTION_DDL: Final[tuple[str, ...]] = ("CREATE ", "ALTER ", "PRAGMA ")


def _bare_statements(root: Path) -> list[str]:
    """``<expr>.db.conn.execute(…)`` call sites that are not construction DDL."""
    offenders: list[str] = []
    for rel in _ROOTS:
        for path in sorted((root / rel).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            constants = _module_constants(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr != "execute" or not node.args:
                    continue
                conn = node.func.value
                if not (isinstance(conn, ast.Attribute) and conn.attr == "conn"):
                    continue
                owner = conn.value
                # `store.db.conn` and `self._db.conn` are the same object by two
                # names; `opstore`'s own check matches both for the same reason.
                if not (isinstance(owner, ast.Attribute) and owner.attr in {"db", "_db"}):
                    continue
                sql = _sql_text(node.args[0], constants).lstrip().upper()
                if not sql.startswith(_CONSTRUCTION_DDL):
                    # Unreadable SQL (built in a variable) lands here too, and
                    # deliberately: a scan that cannot tell what a statement is
                    # must not license it.
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    return offenders


def test_no_consumer_statement_runs_on_the_raw_shared_connection() -> None:
    """Only construction-time schema bootstrap may address the connection.

    ``CREATE TABLE IF NOT EXISTS`` and its ``PRAGMA``/``ALTER`` companions run
    once while a store is being built, before a second thread can hold the
    object, so they have nobody to race — the same exemption `opstore`'s own
    check gives ``connect``/``_migrate``. Everything else takes a lock.

    The fix for a failure here is one line, never an exemption:
    ``with <store>.db.reading() as conn:`` for a read, ``transaction()`` for a
    write, and address ``conn``.
    """
    offenders = _bare_statements(_repo_root())
    assert offenders == [], (
        "these statements bypass Database.reading()/transaction(); each one "
        "raises sqlite3.InterfaceError('bad parameter or other API misuse') on "
        "some thread the moment a write runs concurrently:\n  " + "\n  ".join(offenders)
    )
