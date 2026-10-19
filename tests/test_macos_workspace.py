# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Host regressions only; never substitutes for the fresh native browser smoke."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contract/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hephaestus.core.deadline import Deadline  # noqa: E402
from hephaestus.core.executor.sandbox.base import CapabilityReport, Rlimits  # noqa: E402
from hephaestus.http.runtime import WorkspaceRuntime  # noqa: E402


class Backend:
    name = "oci-docker"
    unsafe = False

    def probe(self):
        return CapabilityReport(self.name, True)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "parts").mkdir()
    (tmp_path / "hephaestus.toml").write_text('name = "workspace-regression"\nunits = "mm"\n')
    return tmp_path


def test_full_http_import_does_not_load_kernel():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import hephaestus.http.app; import sys; "
            "assert not any(n.split('.')[0] in {'build123d','OCP','pyrender','numpy'} "
            "for n in sys.modules)",
        ],
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                str(ROOT / p / "src") for p in ("core", "server", "opstore", "contract")
            ),
        },
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_explicit_backend_projection_and_limits_survive_reload(project):
    backend = Backend()
    limits = Rlimits(120, 2 * 1024**3, 256)
    renderer = object()
    runtime = WorkspaceRuntime.open(
        project,
        token="test-only",
        backend=backend,
        renderer=renderer,
        serve_mode=True,
        build_rlimits=limits,
        build_wall_clock_s=120,
        render_size=(320, 240),
    )
    try:
        for _ in range(2):
            assert runtime._secure_executor_available() is True
            assert runtime.cad._backend is backend
            assert runtime.cad._renderer is renderer
            assert runtime.cad._build_rlimits == limits
            assert runtime.cad._build_wall_clock_s == 120
            assert runtime.cad._render_dimensions() == {"width": 320, "height": 240}
            assert runtime.agent is None and runtime.sessions is None
            runtime.reload_manifest()
    finally:
        runtime.close()


def test_unsafe_injection_still_refuses(project):
    backend = Backend()
    backend.unsafe = True
    with pytest.raises(Exception, match="unsafe"):
        WorkspaceRuntime.open(project, token="test-only", backend=backend, serve_mode=True)


def test_api_auth_and_injected_capability(project):
    from hephaestus.http.app import build_app
    from starlette.testclient import TestClient

    runtime = WorkspaceRuntime.open(project, token="test-only", backend=Backend(), serve_mode=True)
    try:
        with TestClient(build_app(runtime)) as client:
            assert client.get("/api/v1/project").status_code == 401
            result = client.get("/api/v1/project", headers={"Authorization": "Bearer test-only"})
            assert result.status_code == 200
            assert result.json()["capabilities"]["secure_executor"] is True
            assert runtime.agent is None
    finally:
        runtime.close()


def test_disabled_agent_attachment_survives_reload(project):
    from hephaestus.http.agent_attach import AttachRefused

    runtime = WorkspaceRuntime.open(
        project, token="test-only", backend=Backend(), allow_agent_attach=False
    )
    try:
        for _ in range(2):
            with pytest.raises(AttachRefused, match="disabled"):
                runtime.attach_agent()
            assert runtime.agent is None and runtime._spawn_pool is None
            runtime.reload_manifest()
    finally:
        runtime.close()


def test_shared_worker_admission_refuses_concurrency():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from hephaestus.core.errors import SandboxDeniedError
    from macos_workspace import serial_slot

    lock = threading.RLock()
    with ThreadPoolExecutor(max_workers=1) as pool, serial_slot(lock):

        def attempt():
            with pytest.raises(SandboxDeniedError, match="already active"), serial_slot(lock):
                pytest.fail("second heavy operation admitted")

        pool.submit(attempt).result(timeout=3)
    with serial_slot(lock):
        pass


def test_build_limits_reach_request_and_runner(project, monkeypatch):
    import hephaestus.agent_bridge.cad_ops._base as base

    limits = Rlimits(120, 2 * 1024**3, 256)
    runtime = WorkspaceRuntime.open(
        project, token="test-only", backend=Backend(), build_rlimits=limits, build_wall_clock_s=120
    )
    calls = []

    def capture(request, **kwargs):
        calls.append((request, kwargs))

    monkeypatch.setattr(base, "run_build", capture)
    try:
        runtime.cad._run(
            "part",
            "part.geometry = Box(1,1,1)",
            None,
            out_dir=project / "output",
            part_overrides={},
            project_overrides={},
        )
        assert len(calls) == 1
        assert calls[0][0].wall_clock_s == 120
        assert calls[0][1]["rlimits"] == limits
        assert calls[0][1]["backend"] is runtime.backend
    finally:
        runtime.close()


def test_locked_vocabulary_skew_refuses(monkeypatch):
    from types import SimpleNamespace

    from hephaestus.core.errors import ValidationError
    from hephaestus.core.executor.namespace import _build123d_exports

    monkeypatch.setitem(sys.modules, "build123d", SimpleNamespace(__all__=["UnexpectedName"]))
    with pytest.raises(ValidationError, match="vocabulary mismatch"):
        _build123d_exports()


def test_local_launcher_preserves_requirement_gate(project):
    import json

    from macos_workspace import dispatch_local, record_requirements

    runtime = WorkspaceRuntime.open(project, token="test-only", backend=Backend())
    try:
        result = dispatch_local(runtime, "build_part", {"name": "two_solids"})
        assert result["status"] == "clarification_required"
        assert result["reason"] == "no_ledger"
        specification = project / "requirements.json"
        request = "Two separate cuboids with total volume 162 mm3."
        specification.write_text(
            json.dumps(
                {
                    "request": request,
                    "entries": [
                        {"id": "R1", "text": request, "quote": request, "source": "specified"},
                    ],
                }
            )
        )
        evidence = record_requirements(runtime, specification)
        assert evidence["recorded"]["generation"] == 1
        assert runtime.cad.ledger_state().entries[0].quote == request
        specification.write_text(
            json.dumps(
                {
                    "request": request,
                    "entries": [
                        {
                            "id": "R2",
                            "text": "not supplied",
                            "quote": "fake quote",
                            "source": "specified",
                        },
                    ],
                }
            )
        )
        with pytest.raises(ValueError, match="quote"):
            record_requirements(runtime, specification)
        assert runtime.cad.ledger_state().generation == 1
    finally:
        runtime.close()


def test_unavailable_interference_never_imports_kernel():
    from hephaestus.agent_bridge.cad_ops._critique import interference_report

    result = interference_report((), solid_count=2, unavailable="remote API absent")
    assert result["pairs_measured"] == 0
    assert result["warnings"][0]["kind"] == "interference_unavailable"
    assert "build123d" not in sys.modules


def test_status_labels_alone_never_promote_milestone(tmp_path):
    from macos_milestone_smoke import REQUIRED, Smoke

    smoke = Smoke(tmp_path)
    smoke.report["checks"] = {name: {"status": "passed"} for name in REQUIRED}
    smoke.save()
    assert smoke.report["accepted"] is False


@pytest.mark.parametrize("fault", ["ownership", "persistent_write", "save", "reader", "interrupt"])
def test_browser_post_spawn_faults_reap_client_and_detached_child(tmp_path, monkeypatch, fault):
    import json
    import signal
    from types import SimpleNamespace

    import macos_workspace_check as check

    # Real POSIX client plus detached stand-in browser; positive readiness pipe
    # ensures injected faults occur after both exist. No browser/daemon acceptance.
    child_script = """
import json, os, pathlib, signal, subprocess, sys
child = subprocess.Popen(
    [sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)

def stop(sig, frame):
    child.terminate()
    child.wait(timeout=5)
    pathlib.Path(sys.argv[1]).write_text(json.dumps(
        {'launch_pending': False, 'closed': True, 'pid': child.pid}))
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
print(child.pid, flush=True)
signal.pause()
"""
    real_spawn, real_document = subprocess.Popen, check.document
    processes = []
    child_ids = []

    def spawn(*args, **kwargs):
        p = real_spawn(*args, **kwargs)
        processes.append(p)
        import selectors

        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            assert selector.select(5), "synthetic client readiness"
            child_ids.append(int(p.stdout.readline()))
        return p

    writes = 0

    def document(path, value):
        nonlocal writes
        writes += 1
        if (fault == "ownership" and writes == 2) or (fault == "persistent_write" and writes >= 2):
            raise OSError("injected ownership failure")
        if fault == "interrupt" and writes == 2:
            raise KeyboardInterrupt("injected post-spawn interruption")
        real_document(path, value)

    def save():
        if fault == "save":
            raise OSError("injected report save failure")

    monkeypatch.setattr(check.subprocess, "Popen", spawn)
    monkeypatch.setattr(check, "document", document)
    if fault == "reader":

        def start(self):
            raise RuntimeError("injected reader startup failure")

        monkeypatch.setattr(check.threading.Thread, "start", start)
    try:
        with pytest.raises((OSError, RuntimeError, KeyboardInterrupt)):
            check.run_browser_client(
                SimpleNamespace(report={}, save=save, deadline=Deadline.after(480)),
                [sys.executable, "-c", child_script, str(tmp_path / "browser-owner.json")],
                tmp_path,
            )
        assert len(processes) == 1 and processes[0].poll() == 0
        assert not (tmp_path / "runtime").exists()
        for pid in child_ids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        state = json.loads((tmp_path / "client-owner.json").read_text())
        assert state["launch_pending"] is (fault in {"ownership", "persistent_write", "interrupt"})
        assert state["reaped"] is (fault != "persistent_write")
    finally:
        for process in processes:
            if process.poll() is None:
                os.kill(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
