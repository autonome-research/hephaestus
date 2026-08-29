# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Every read of the shared connection takes the connection lock.

``db.py``'s contract says threads share **one** ``sqlite3.Connection``
(``check_same_thread=False``) and that in-process correctness rests on
``_txn_lock``. That was written about *transactions*, and reads were left bare —
which held only for as long as no read ran concurrently with a write on the hot
path.

It stopped holding on 2026-08-28, when ``INTERFACE.md`` §19.40 wired
``Gc.admission_guard()`` into ``Publisher.freeze_inputs``: every build now reads
``pins``, ``links``, the protected-root pointers and the whole ``blobs`` table
before it executes, and builds run concurrently. The observed failure was
``sqlite3.InterfaceError("bad parameter or other API misuse")`` raised out of
``BlobStore.read_pointer``, reproducing in 3 of 5 runs of
``server/tests/test_request_binding.py::test_two_concurrent_runs_each_read_their_own_request``
and in 1 of 10 once only ``Gc``'s own reads were locked — i.e. the hazard was
never confined to the code the guard added; the guard only made it reachable.

So the rule is now the whole module's, and it is asserted structurally rather
than by a race. A stress test can only ever fail *sometimes*; this one fails
**always** the moment a new bare read is added, which is the property that keeps
the rule true a year from now. It is the ``no-derived-fact`` precedent applied to
concurrency.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Final

import pytest
from opstore.db import Database

from opstore import OpStore

SRC: Final[Path] = Path(__file__).resolve().parents[1] / "src" / "opstore"

#: A read issued straight on the shared connection object. Anything matching
#: this outside :meth:`Database.transaction` / :meth:`Database.reading` is a
#: statement stepped with no in-process serialization at all.
_BARE_READ: Final[re.Pattern[str]] = re.compile(r"(?:self\._db|self)\.conn\.execute\(")

#: ``db.py`` owns the connection: its ``BEGIN``/``COMMIT``/``ROLLBACK`` and the
#: connect-time ``PRAGMA``s are the only statements that legitimately address
#: ``self.conn`` directly, because they *are* the locking primitive.
_OWNER: Final[str] = "db.py"


def test_no_module_reads_the_shared_connection_without_the_lock() -> None:
    """Only ``db.py`` touches ``conn.execute`` directly; everyone else takes a lock.

    Failure means a new read was added on the bare connection. The fix is one
    line — wrap it in ``with self._db.reading() as conn:`` — not an exemption:
    the crash it produces is an ``InterfaceError`` from a thread that had nothing
    to do with the code that caused it, which is the most expensive kind of bug
    this repository can ship.
    """
    offenders: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        if path.name == _OWNER:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _BARE_READ.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == [], (
        "these read the shared sqlite connection without Database.reading():\n"
        + "\n".join(offenders)
    )


def test_the_owner_only_addresses_the_connection_for_the_locking_primitive() -> None:
    """``db.py``'s own bare statements are the transaction control words alone.

    Without this the exemption above would be a hole: a read added to ``db.py``
    would inherit the owner's licence for no reason. ``connect`` and ``_migrate``
    are outside the rule and only they are: both run before ``connect`` returns,
    so no other thread can be holding the object yet — the pragmas and the schema
    bootstrap have nobody to race.
    """
    text = (SRC / _OWNER).read_text(encoding="utf-8")
    body = text.split("def close(", 1)[1].split("def _migrate(", 1)[0]
    statements = re.findall(r"self\.conn\.execute\(\s*\n?\s*(.{0,24})", body)
    for statement in statements:
        assert statement.startswith(('"BEGIN', '"ROLLBACK', '"COMMIT')), (
            f"db.py issues {statement!r} on the bare connection; only the "
            "transaction control words may skip the lock"
        )


def test_reading_is_reentrant_with_a_transaction_on_one_thread(tmp_path: Path) -> None:
    """A read composed of other reads, or nested in a write, must not deadlock.

    ``Gc.reachable()`` does exactly this — one ``reading()`` around two more —
    and ``Gc.collect()`` takes leases (which transact) between reads.
    """
    db = Database.connect(tmp_path / "state.db")
    try:
        with db.reading() as conn:
            assert conn.execute("SELECT 1").fetchone() is not None
            with db.reading() as inner:
                assert inner.execute("SELECT 1").fetchone() is not None
        with db.transaction() as conn:
            conn.execute("INSERT INTO pins(ref, created_at) VALUES('sha256:aa', 1.0)")
            with db.reading() as inner:
                assert inner.execute("SELECT COUNT(*) AS n FROM pins").fetchone()["n"] == 1
    finally:
        db.close()


def test_a_read_and_a_write_thread_do_not_misuse_the_connection(tmp_path: Path) -> None:
    """The behavioural half: the two threads that produced the original crash.

    Deliberately secondary to the static check above — it reproduces a race and
    so can only ever be evidence, not proof. It is here because the static rule
    describes a mechanism, and a mechanism nobody has run once is a guess.
    """
    store = OpStore.create(tmp_path / "st")
    try:
        for index in range(200):
            store.gc.pin(f"sha256:{index:064x}")
        failures: list[BaseException] = []
        stop = threading.Event()

        def writing() -> None:
            index = 0
            while not stop.is_set():
                try:
                    store.blobs.put(f"payload-{index}".encode())
                except BaseException as exc:  # pragma: no cover - the regression itself
                    failures.append(exc)
                    return
                index += 1

        def reading() -> None:
            for _ in range(300):
                try:
                    store.gc.usage()
                except BaseException as exc:  # pragma: no cover - the regression itself
                    failures.append(exc)
                    return

        writer = threading.Thread(target=writing)
        reader = threading.Thread(target=reading)
        writer.start()
        reader.start()
        reader.join(timeout=120)
        stop.set()
        writer.join(timeout=120)
        assert failures == [], repr(failures[0]) if failures else ""
    finally:
        store.close()


@pytest.mark.parametrize("method", ["has", "size", "retention_class"])
def test_the_blob_reads_still_answer_the_same_thing(tmp_path: Path, method: str) -> None:
    """The lock changed serialization, not answers."""
    store = OpStore.create(tmp_path / "st")
    try:
        blob = store.blobs.put(b"hello")
        answer = getattr(store.blobs, method)(blob)
        assert answer in (True, 5, "default")
        assert store.blobs.read_pointer("nothing") is None
    finally:
        store.close()
