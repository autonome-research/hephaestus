"""G0B adapter clause: typed crash recovery at every publication boundary.

Each boundary — source write, build publication, check-set mutation, and
synthetic-export publication — is driven in a subprocess that ``os._exit(42)``s
at an injected ``OPSTORE_CRASH_POINT``. The surviving parent reopens the
store, runs recovery, and asserts one deterministic typed outcome per
boundary — never a partial file, half-published pointer, or mixed check
generation — identical across every crash point.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _adapter_helpers import DEFAULT_SCRIPT, build_for_crash, make_project
from hephaestus.core.checks.engine import CheckSet
from hephaestus.core.project_store.layout import open_store
from hephaestus.core.project_store.publication import Publisher, current_pointer
from hephaestus.core.project_store.store import ProjectStore

from opstore import sha256_bytes

HELPERS_DIR = Path(__file__).resolve().parent

#: File-WAL boundaries (source writes, check file installs, export installs).
FILE_WAL_POINTS = (
    "blobs.put.after_file_fsync",
    "after_blob_fsync",
    "after_prepared",
    "after_install",
    "after_committed",
)
#: Pointer-publish boundaries (build bundles, check-set generations).
PUBLISH_POINTS = (
    "blobs.put.after_rename",
    "publish.after_prepared",
    "publish.after_swap",
    "publish.after_committed",
)


def _run_crashing_child(runner_source: str, tmp_path: Path, point: str, *argv: str) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(runner_source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(runner), str(HELPERS_DIR), *argv],
        env={**os.environ, "OPSTORE_CRASH_POINT": point},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 42, (
        f"child did not crash at {point!r}:\n{result.stdout}\n{result.stderr}"
    )


CHILD_PREAMBLE = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.locks import LockManager
    from opstore.types import EnvCrashHook

    project_root = Path(sys.argv[2])
    layout = load_project(project_root)
    # Short lease TTL: leases a crashed child leaves behind must expire so the
    # retrying parent can liveness-reclaim them.
    store = open_store(layout, crash_hook=EnvCrashHook())
    locks = LockManager(store, lease_ttl_s=0.5)
    """
).lstrip()


# --------------------------------------------------------------------------
# source publication boundary


SOURCE_RUNNER = CHILD_PREAMBLE + textwrap.dedent(
    """
    from hephaestus.core.project_store.store import ProjectStore

    parts = ProjectStore(layout, store, locks=locks)
    base = sys.argv[3]
    content = sys.argv[4]
    parts.write_part("widget", content, base_hash=base, op_id="src-crash")
    print("no-crash")
    """
)

NEW_SOURCE = "part.geometry = None  # crashed write\n"


class TestSourceBoundary:
    @pytest.mark.parametrize("point", FILE_WAL_POINTS)
    def test_single_typed_outcome_from_every_point(self, tmp_path: Path, point: str) -> None:
        layout = make_project(tmp_path / "proj")
        open_store(layout).close()
        base_hash = sha256_bytes(DEFAULT_SCRIPT.encode())
        _run_crashing_child(SOURCE_RUNNER, tmp_path, point, str(layout.root), base_hash, NEW_SOURCE)

        store = open_store(layout)
        try:
            recovery = store.recover()
            # Typed recovery: every resolved op completes or reapplies —
            # a crashed cooperative write never synthesizes a conflict.
            assert all(o.action != "conflicted" for o in recovery.wal)
            live = layout.part_path("widget").read_text(encoding="utf-8")
            # No torn state: the live file is wholly old or wholly new.
            assert live in (DEFAULT_SCRIPT, NEW_SOURCE)
            # The retry converges every crash point to the same final state.
            parts = ProjectStore(layout, store)
            outcome = parts.write_part("widget", NEW_SOURCE, base_hash=base_hash, op_id="src-crash")
            assert layout.part_path("widget").read_text(encoding="utf-8") == NEW_SOURCE
            assert outcome.snapshot.content_hash == sha256_bytes(NEW_SOURCE.encode())
            # And is idempotent from here on.
            again = parts.write_part("widget", NEW_SOURCE, base_hash=base_hash, op_id="src-crash")
            assert again.replayed
        finally:
            store.close()


# --------------------------------------------------------------------------
# build publication boundary


BUILD_RUNNER = CHILD_PREAMBLE + textwrap.dedent(
    """
    from _adapter_helpers import build_for_crash
    from hephaestus.core.project_store.publication import Publisher

    out_dir = Path(sys.argv[3])
    publisher = Publisher(layout, store, locks=locks)
    build = build_for_crash(layout, out_dir)
    outcome = publisher.publish_build(build, op_id="build-crash")
    print("no-crash", outcome.kind)
    """
)


class TestBuildBoundary:
    @pytest.mark.parametrize("point", PUBLISH_POINTS)
    def test_current_pointer_single_outcome_from_every_point(
        self, tmp_path: Path, point: str
    ) -> None:
        layout = make_project(tmp_path / "proj")
        open_store(layout).close()
        out_dir = tmp_path / "out"
        _run_crashing_child(BUILD_RUNNER, tmp_path, point, str(layout.root), str(out_dir))

        store = open_store(layout)
        try:
            recovery = store.recover()
            assert all(o.action != "conflicted" for o in recovery.wal)
            pointer_before = store.blobs.read_pointer(current_pointer("widget"))
            publisher = Publisher(layout, store)
            outcome = publisher.publish_build(build_for_crash(layout, out_dir), op_id="build-crash")
            assert outcome.kind == "current"
            pointer_after = store.blobs.read_pointer(current_pointer("widget"))
            # Never a third state: untouched or already-final, then final.
            assert pointer_before in (None, pointer_after)
            assert pointer_after == outcome.record_blob
            stored = publisher.current_result("widget")
            assert stored is not None
            assert stored.current is True
            assert stored.artifact_ref == outcome.artifact_ref
            state = publisher.projections.state()
            assert state.projections["widget"].artifact_ref == outcome.artifact_ref
            assert state.stale == {}
        finally:
            store.close()


# --------------------------------------------------------------------------
# check-set publication boundary


CHECK_RUNNER = CHILD_PREAMBLE + textwrap.dedent(
    """
    from hephaestus.core.checks.engine import CheckSet

    layout.checks_dir.mkdir(exist_ok=True)
    content = sys.argv[3]
    check_set = CheckSet(layout.checks_dir, store, lease_ttl_s=0.5)
    check_set.current()  # settle generation 0 before the mutation
    check_set.write_check("fit.py", content, op_id="check-crash")
    print("no-crash")
    """
)

CHECK_CONTENT = "CHECKS = {'fits': lambda m: True}\n"


class TestCheckBoundary:
    @pytest.mark.parametrize("point", FILE_WAL_POINTS + PUBLISH_POINTS[1:])
    def test_exactly_one_generation_advance_or_whole_rollback(
        self, tmp_path: Path, point: str
    ) -> None:
        layout = make_project(tmp_path / "proj")
        layout.checks_dir.mkdir(exist_ok=True)
        open_store(layout).close()
        _run_crashing_child(CHECK_RUNNER, tmp_path, point, str(layout.root), CHECK_CONTENT)

        store = open_store(layout)
        try:
            check_set = CheckSet(layout.checks_dir, store)
            # Lock acquisition resolves PREPARED rows and the intent first.
            state = check_set.current()
            new_hash = sha256_bytes(CHECK_CONTENT.encode())
            live_path = layout.checks_dir / "fit.py"
            live = live_path.read_text(encoding="utf-8") if live_path.is_file() else None
            # Exactly one generation advance, or a whole rollback:
            assert state.generation in (0, 1)
            if state.generation == 1:
                assert state.origin == "cooperative"
                assert state.files == {"fit.py": new_hash}
                assert live == CHECK_CONTENT
            else:
                # Rolled wholly back: changed content is never visible under
                # the prior cooperative generation.
                assert state.files == {}
                assert live is None
            # The frozen bundle agrees with the exposed generation exactly.
            bundle = check_set.capture()
            assert bundle.state.generation == state.generation
            assert dict(bundle.state.files) == dict(state.files)
            if state.generation == 1:
                assert bundle.contents == {"fit.py": CHECK_CONTENT}
            # Recovery is stable: a second acquisition changes nothing.
            assert check_set.current() == state
        finally:
            store.close()


# --------------------------------------------------------------------------
# synthetic-export publication boundary


EXPORT_RUNNER = CHILD_PREAMBLE + textwrap.dedent(
    """
    from _adapter_helpers import build_for_crash
    from hephaestus.core.project_store.publication import Publisher

    out_dir = Path(sys.argv[3])
    publisher = Publisher(layout, store, locks=locks)
    build = build_for_crash(layout, out_dir)
    published = publisher.publish_build(build, op_id="seed-current")
    assert published.kind == "current", published.details
    import os
    os.environ["OPSTORE_CRASH_POINT"] = os.environ["EXPORT_CRASH_POINT"]
    publisher.publish_export(
        name="widget.step",
        data=b"exported bytes",
        source_artifact_ref=published.artifact_ref,
        op_id="export-crash",
    )
    print("no-crash")
    """
)


class TestExportBoundary:
    @pytest.mark.parametrize("point", FILE_WAL_POINTS)
    def test_no_unpinned_delivered_export_from_any_point(self, tmp_path: Path, point: str) -> None:
        layout = make_project(tmp_path / "proj")
        open_store(layout).close()
        out_dir = tmp_path / "out"
        runner = tmp_path / "runner.py"
        runner.write_text(EXPORT_RUNNER, encoding="utf-8")
        # The seed publication must not crash: the point is armed only for
        # the export step via EXPORT_CRASH_POINT indirection.
        result = subprocess.run(
            [sys.executable, str(runner), str(HELPERS_DIR), str(layout.root), str(out_dir)],
            env={
                **{k: v for k, v in os.environ.items() if k != "OPSTORE_CRASH_POINT"},
                "EXPORT_CRASH_POINT": point,
            },
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 42, (
            f"child did not crash at {point!r}:\n{result.stdout}\n{result.stderr}"
        )

        store = open_store(layout)
        try:
            recovery = store.recover()
            assert all(o.action != "conflicted" for o in recovery.wal)
            target = layout.exports_dir / "widget.step"
            # No torn file: absent, or wholly the exported bytes.
            if target.is_file():
                assert target.read_bytes() == b"exported bytes"
            publisher = Publisher(layout, store)
            published = publisher.current_result("widget")
            assert published is not None
            assert published.artifact_ref is not None
            outcome = publisher.publish_export(
                name="widget.step",
                data=b"exported bytes",
                source_artifact_ref=published.artifact_ref,
                op_id="export-crash",
            )
            # Deterministic single outcome: installed, pinned, provenance-linked.
            assert target.read_bytes() == b"exported bytes"
            assert outcome.pinned
            assert outcome.blob_hash in store.gc.pins()
            assert outcome.blob_hash in store.gc.reachable()
            retry = publisher.publish_export(
                name="widget.step",
                data=b"exported bytes",
                source_artifact_ref=published.artifact_ref,
                op_id="export-crash",
            )
            assert retry.replayed
        finally:
            store.close()
