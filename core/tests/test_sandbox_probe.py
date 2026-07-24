"""probe.py tests: fail-closed detection, per-store caching, secure_backend
factory, unsafe refusal policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from hephaestus.core.errors import SandboxDeniedError, UnsafeRefusedError
from hephaestus.core.executor.sandbox.base import CapabilityReport, ExecBackend
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap
from hephaestus.core.executor.sandbox.probe import (
    PROBE_CACHE_FILENAME,
    REQUIRED_FEATURES,
    cached_probe,
    probe_bwrap,
    refuse_unsafe,
    secure_backend,
)

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="bwrap sandbox requires Linux with bubblewrap installed",
)


def strip_bwrap_from_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_bin))


@requires_bwrap
class TestProbePasses:
    def test_probe_reports_available_with_all_features(self, tmp_path: Path) -> None:
        report = probe_bwrap(scratch_dir=tmp_path)
        assert report.backend == "bwrap"
        assert report.available
        assert report.reason is None
        assert report.probed_at is not None
        for feature in REQUIRED_FEATURES:
            assert report.features.get(feature) is True, feature

    def test_backend_probe_method_delegates(self, tmp_path: Path) -> None:
        report = BwrapBackend().probe()
        assert report.available
        assert report.backend == "bwrap"


@requires_bwrap
class TestCache:
    def test_cached_probe_writes_then_reuses(self, tmp_path: Path) -> None:
        store_root = tmp_path / ".heph"
        first = cached_probe(store_root, scratch_dir=tmp_path)
        assert first.available
        cache_file = store_root / PROBE_CACHE_FILENAME
        assert cache_file.is_file()
        second = cached_probe(store_root, scratch_dir=tmp_path)
        # identical probed_at proves the second call was a cache hit, not a re-probe
        assert second == first

    def test_corrupt_cache_reprobes(self, tmp_path: Path) -> None:
        store_root = tmp_path / ".heph"
        store_root.mkdir()
        (store_root / PROBE_CACHE_FILENAME).write_text("{not json")
        report = cached_probe(store_root, scratch_dir=tmp_path)
        assert report.available
        # cache healed with a valid passing entry
        entry = json.loads((store_root / PROBE_CACHE_FILENAME).read_text())
        assert entry["report"]["available"] is True

    def test_stale_cache_invalidated_when_bwrap_disappears(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store_root = tmp_path / ".heph"
        assert cached_probe(store_root, scratch_dir=tmp_path).available
        strip_bwrap_from_path(monkeypatch, tmp_path)
        report = cached_probe(store_root, scratch_dir=tmp_path)
        assert not report.available
        assert report.reason is not None and "not on PATH" in report.reason


class TestFailClosed:
    def test_probe_unavailable_without_bwrap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strip_bwrap_from_path(monkeypatch, tmp_path)
        report = probe_bwrap()
        assert isinstance(report, CapabilityReport)
        assert not report.available
        assert report.reason is not None and "not on PATH" in report.reason
        assert report.backend == "bwrap"

    def test_secure_backend_raises_sandbox_denied_without_bwrap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strip_bwrap_from_path(monkeypatch, tmp_path)
        store_root = tmp_path / ".heph"
        with pytest.raises(SandboxDeniedError) as excinfo:
            secure_backend(store_root)
        assert excinfo.value.code == "sandbox_denied"
        assert "sandbox_unavailable" in excinfo.value.message
        # failures are never cached
        assert not (store_root / PROBE_CACHE_FILENAME).exists()

    def test_failed_probe_never_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strip_bwrap_from_path(monkeypatch, tmp_path)
        store_root = tmp_path / ".heph"
        report = cached_probe(store_root)
        assert not report.available
        assert not (store_root / PROBE_CACHE_FILENAME).exists()


@requires_bwrap
class TestSecureBackendFactory:
    def test_returns_probed_bwrap_backend(self, tmp_path: Path) -> None:
        backend = secure_backend(tmp_path / ".heph", scratch_dir=tmp_path)
        assert isinstance(backend, BwrapBackend)
        assert isinstance(backend, ExecBackend)
        assert backend.name == "bwrap"


class TestUnsafeRefusal:
    def test_registry_content_refused(self) -> None:
        with pytest.raises(UnsafeRefusedError) as excinfo:
            refuse_unsafe(registry_content=True)
        assert excinfo.value.code == "unsafe_refused"
        assert "registry" in excinfo.value.message

    def test_serve_refused(self) -> None:
        with pytest.raises(UnsafeRefusedError):
            refuse_unsafe(registry_content=False, serve=True)

    def test_registry_refusal_wins_even_under_serve(self) -> None:
        with pytest.raises(UnsafeRefusedError):
            refuse_unsafe(registry_content=True, serve=True)

    def test_local_debug_content_not_refused(self) -> None:
        refuse_unsafe(registry_content=False, serve=False)
