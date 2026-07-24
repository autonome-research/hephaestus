"""Check-set generation protocol (architecture §3.4) over opstore primitives."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest
from hephaestus.core.checks.engine import (
    BUNDLE_REF_PREFIX,
    INTENT_POINTER,
    STATE_POINTER,
    CheckSet,
    CheckSetState,
    run_bundle,
)
from hephaestus.core.checks.facade import GeometrySource
from hephaestus.core.errors import (
    CheckSetDriftError,
    InvalidCheckGenerationError,
    ValidationError,
)
from test_checks_helpers import ARM, PLATE, FakeOps, bracket_source, primary_source

from opstore import OpStore, sha256_bytes

CLEAR_CHECK = textwrap.dedent(
    """
    CHECKS = {
        "bracket_clears_plate": lambda m: m.interference("primary/plate", "bracket/arm")
        == approx(0, abs=1e-6),
        "gap": lambda m: m.clearance("primary/plate", "bracket/arm") >= approx(2.0, abs=0.1),
    }
    """
).lstrip()

CLEAR_CHECK_V2 = CLEAR_CHECK.replace("abs=0.1", "abs=0.2")

BROKEN_SYNTAX = "CHECKS = {\n"


def make_env(tmp_path: Path) -> tuple[OpStore, CheckSet, Path]:
    store = OpStore.create(tmp_path / "store")
    checks_dir = tmp_path / "checks"
    checks_dir.mkdir()
    return store, CheckSet(checks_dir, store), checks_dir


def project_sources() -> dict[str, GeometrySource]:
    return {"primary": primary_source(), "bracket": bracket_source()}


class TestGenerationLifecycle:
    def test_initial_generation(self, tmp_path: Path) -> None:
        store, checkset, _ = make_env(tmp_path)
        state = checkset.current()
        assert state.generation == 0
        assert state.origin == "initial"
        assert state.status == "valid"
        assert dict(state.files) == {}
        assert checkset.current() == state  # stable
        store.close()

    def test_create_and_edit_increment_generation(self, tmp_path: Path) -> None:
        store, checkset, checks_dir = make_env(tmp_path)
        base = checkset.current().generation
        created = checkset.write_check("clearances.py", CLEAR_CHECK, op_id="op-create")
        assert created.generation == base + 1
        assert created.origin == "cooperative"
        assert created.status == "valid"
        assert created.files["clearances.py"] == sha256_bytes(CLEAR_CHECK.encode())
        assert (checks_dir / "clearances.py").read_text() == CLEAR_CHECK
        edited = checkset.write_check("clearances.py", CLEAR_CHECK_V2, op_id="op-edit")
        assert edited.generation == base + 2
        assert (checks_dir / "clearances.py").read_text() == CLEAR_CHECK_V2
        assert checkset.current().generation == base + 2  # read does not advance
        store.close()

    def test_bundle_ref_and_state_roundtrip(self, tmp_path: Path) -> None:
        store, checkset, _ = make_env(tmp_path)
        state = checkset.write_check("clearances.py", CLEAR_CHECK, op_id="op-1")
        assert state.bundle_ref.startswith(BUNDLE_REF_PREFIX + "sha256:")
        assert CheckSetState.from_json(state.to_json()) == state
        store.close()

    def test_invalid_write_rejected_before_commit(self, tmp_path: Path) -> None:
        store, checkset, checks_dir = make_env(tmp_path)
        before = checkset.current()
        with pytest.raises(ValidationError) as excinfo:
            checkset.write_check("broken.py", BROKEN_SYNTAX, op_id="op-bad")
        assert excinfo.value.kind == "syntax"
        assert not (checks_dir / "broken.py").exists()
        assert checkset.current() == before
        store.close()

    def test_write_check_rejects_path_tricks(self, tmp_path: Path) -> None:
        store, checkset, _ = make_env(tmp_path)
        for name in ("../evil.py", "sub/dir.py", "noext", ".."):
            with pytest.raises(ValidationError):
                checkset.write_check(name, "CHECKS = {}", op_id="op-x")
        store.close()


class TestCaptureAndRun:
    def test_capture_returns_frozen_bundle(self, tmp_path: Path) -> None:
        store, checkset, checks_dir = make_env(tmp_path)
        state = checkset.write_check("clearances.py", CLEAR_CHECK, op_id="op-1")
        bundle = checkset.capture()
        assert bundle.state == state
        assert bundle.contents == {"clearances.py": CLEAR_CHECK}
        # Bundle content comes from CAS blobs: mutating the fs afterwards
        # does not change an already-captured bundle.
        (checks_dir / "clearances.py").write_text(CLEAR_CHECK_V2)
        assert bundle.contents == {"clearances.py": CLEAR_CHECK}
        store.close()

    def test_cross_part_run_pass_and_fail(self, tmp_path: Path) -> None:
        store, checkset, _ = make_env(tmp_path)
        state = checkset.write_check("clearances.py", CLEAR_CHECK, op_id="op-1")
        passing_ops = FakeOps(clearances={frozenset({PLATE, ARM}): 2.5})
        report = checkset.run(
            project_sources(),
            part="bracket",
            ops=passing_ops,
            project_snapshot_ref="artifact:project-snapshot:sha256:" + "0" * 64,
        )
        assert report.part == "bracket"
        assert report.check_set_generation == state.generation
        assert report.check_bundle_ref == state.bundle_ref
        assert report.file_hashes == dict(state.files)
        assert report.checks["clearances:bracket_clears_plate"].passed is True
        assert report.checks["clearances:bracket_clears_plate"].measured == 0.0
        assert report.checks["clearances:gap"].passed is True
        assert report.checks["clearances:gap"].measured == 2.5

        failing_ops = FakeOps(interferences={frozenset({PLATE, ARM}): 4.2})
        failing = checkset.run(project_sources(), part="bracket", ops=failing_ops)
        # A failing check fails the report, never the run.
        assert failing.checks["clearances:bracket_clears_plate"].passed is False
        assert failing.checks["clearances:bracket_clears_plate"].measured == 4.2
        assert failing.checks["clearances:gap"].passed is False
        store.close()

    def test_report_json_shape(self, tmp_path: Path) -> None:
        store, checkset, _ = make_env(tmp_path)
        checkset.write_check("clearances.py", CLEAR_CHECK, op_id="op-1")
        report = checkset.run(project_sources(), part="bracket", ops=FakeOps())
        data = report.to_json()
        assert data["project_snapshot_ref"] is None
        checks = data["checks"]
        assert isinstance(checks, dict)
        entry = checks["clearances:bracket_clears_plate"]
        assert isinstance(entry, dict)
        assert set(entry) == {"pass", "measured"}
        store.close()


class TestExternalImport:
    def test_stable_direct_change_imports_exactly_once(self, tmp_path: Path) -> None:
        store, checkset, checks_dir = make_env(tmp_path)
        base = checkset.write_check("clearances.py", CLEAR_CHECK, op_id="op-1")
        (checks_dir / "external.py").write_text("CHECKS = {'ok': lambda m: True}\n")
        imported = checkset.current()
        assert imported.generation == base.generation + 1
        assert imported.origin == "external_import"
        assert set(imported.files) == {"clearances.py", "external.py"}
        # A second acquisition sees a matching tree: no further generation.
        assert checkset.current() == imported
        assert checkset.capture().state == imported
        store.close()

    def test_invalid_external_file_fails_closed_with_diagnostics(self, tmp_path: Path) -> None:
        store, checkset, checks_dir = make_env(tmp_path)
        base = checkset.current()
        (checks_dir / "broken.py").write_text(BROKEN_SYNTAX)
        state = checkset.current()
        # Never omitted: the malformed file is a persisted, discriminated
        # invalid generation, not a silently skipped file.
        assert state.generation == base.generation + 1
        assert state.status == "invalid"
        assert state.diagnostics is not None
        diagnostics = checkset.diagnostics(state)
        assert isinstance(diagnostics, list)
        first = diagnostics[0]
        assert isinstance(first, dict)
        assert first["file"] == "broken.py"
        assert first["kind"] == "syntax"

        bundle = checkset.capture()
        assert bundle.state.status == "invalid"
        assert bundle.diagnostics == diagnostics
        with pytest.raises(InvalidCheckGenerationError) as excinfo:
            run_bundle(bundle, project_sources(), part="bracket", ops=FakeOps())
        assert "broken.py" in str(excinfo.value)
        store.close()

    def test_drift_detected_when_tree_keeps_changing(self, tmp_path: Path) -> None:
        store = OpStore.create(tmp_path / "store")
        checks_dir = tmp_path / "checks"
        checks_dir.mkdir()
        counter = {"n": 0}

        def keep_writing() -> None:
            counter["n"] += 1
            (checks_dir / "hot.py").write_text(f"CHECKS = {{'v{counter['n']}': lambda m: True}}\n")

        drifting = CheckSet(checks_dir, store, on_between_scans=keep_writing)
        (checks_dir / "hot.py").write_text("CHECKS = {'v0': lambda m: True}\n")
        with pytest.raises(CheckSetDriftError):
            drifting.current()
        # Once writes settle the same tree imports exactly once.
        stable = CheckSet(checks_dir, store)
        state = stable.current()
        assert state.origin in ("initial", "external_import")
        assert stable.current() == state
        store.close()


class TestConcurrency:
    def test_concurrent_edit_never_yields_mixed_bundle(self, tmp_path: Path) -> None:
        root = tmp_path / "store"
        store = OpStore.create(root)
        checks_dir = tmp_path / "checks"
        checks_dir.mkdir()
        CheckSet(checks_dir, store).write_check(
            "war.py", "CHECKS = {'v0': lambda m: True}\n", op_id="seed"
        )
        versions = [f"CHECKS = {{'v{i}': lambda m: True}}\n" for i in range(0, 9)]
        captured: list[object] = []
        errors: list[BaseException] = []

        def writer() -> None:
            handle = OpStore.open(root)
            try:
                checkset = CheckSet(checks_dir, handle)
                for i, content in enumerate(versions[1:], start=1):
                    checkset.write_check("war.py", content, op_id=f"race-{i}")
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)
            finally:
                handle.close()

        def reader() -> None:
            handle = OpStore.open(root)
            try:
                checkset = CheckSet(checks_dir, handle)
                for _ in range(16):
                    captured.append(checkset.capture())
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)
            finally:
                handle.close()

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert errors == []
        from hephaestus.core.checks.engine import CheckBundle

        generations: list[int] = []
        for bundle in captured:
            assert isinstance(bundle, CheckBundle)
            # Wholly one generation: contents hash exactly to the recorded
            # file hashes of the generation the report claims.
            assert set(bundle.contents) == set(bundle.state.files)
            for rel, text in bundle.contents.items():
                assert sha256_bytes(text.encode()) == bundle.state.files[rel]
            assert bundle.contents["war.py"] in versions
            generations.append(bundle.state.generation)
        assert generations == sorted(generations)  # monotonic under the lock
        store.close()


RUNNER = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    from opstore import OpStore
    from opstore.types import EnvCrashHook

    from hephaestus.core.checks.engine import CheckSet

    root, checks_dir, op_id, content_file = sys.argv[1:5]
    store = OpStore.open(Path(root), crash_hook=EnvCrashHook())
    checkset = CheckSet(Path(checks_dir), store, lease_ttl_s=0.5)
    checkset.write_check("racy.py", Path(content_file).read_text(), op_id=op_id)
    store.close()
    print("no-crash")
    """
).lstrip()


class TestCrashRecovery:
    @pytest.mark.parametrize(
        ("point", "advances"),
        [
            ("after_blob_fsync", False),  # before the typed WAL row: wholly old
            ("after_prepared", True),  # file WAL prepared: recovery reapplies
            ("after_committed", True),  # file landed, publication pending
            ("publish.after_prepared", True),  # publication boundary
            ("publish.after_swap", True),  # generation CAS-swapped, not COMMITTED
            ("publish.after_committed", True),  # committed, intent uncleared
        ],
    )
    def test_crash_recovers_exactly_one_generation_advance(
        self, tmp_path: Path, point: str, advances: bool
    ) -> None:
        root = tmp_path / "store"
        store = OpStore.create(root)
        checks_dir = tmp_path / "checks"
        checks_dir.mkdir()
        baseline = CheckSet(checks_dir, store).write_check(
            "clearances.py", CLEAR_CHECK, op_id="seed"
        )
        store.close()

        content_file = tmp_path / "candidate.py"
        new_content = "CHECKS = {'after_crash': lambda m: True}\n"
        content_file.write_text(new_content)
        runner = tmp_path / "runner.py"
        runner.write_text(RUNNER)
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                str(root),
                str(checks_dir),
                f"crash-{point}",
                str(content_file),
            ],
            env={**os.environ, "OPSTORE_CRASH_POINT": point},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 42, result.stderr

        reopened = OpStore.open(root)
        checkset = CheckSet(checks_dir, reopened)
        recovered = checkset.current()
        if advances:
            # Exactly one generation advance, with the mutation fully visible.
            assert recovered.generation == baseline.generation + 1
            assert recovered.origin == "cooperative"
            assert (checks_dir / "racy.py").read_text() == new_content
            assert recovered.files["racy.py"] == sha256_bytes(new_content.encode())
        else:
            # Wholly rolled back: no generation advance, no file.
            assert recovered.generation == baseline.generation
            assert not (checks_dir / "racy.py").exists()
        # The intent is cleared and the state pointer is coherent.
        assert reopened.blobs.read_pointer(INTENT_POINTER) is None
        pointer = reopened.blobs.read_pointer(STATE_POINTER)
        assert pointer is not None
        stored = json.loads(reopened.blobs.get(pointer).decode())
        assert stored["generation"] == recovered.generation
        # Recovery is idempotent and the check set keeps working afterwards.
        assert checkset.current() == recovered
        after = checkset.write_check("clearances.py", CLEAR_CHECK_V2, op_id="post-crash")
        assert after.generation == recovered.generation + 1
        reopened.close()
