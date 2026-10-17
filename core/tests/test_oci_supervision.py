"""Host race/fault regressions. Synthetic daemon bytes are NOT live OCI evidence."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Never

import pytest
from _oci_json import integer, record
from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.cancellation import (
    Cancellation,
    ExecutionCancelled,
    current_cancellation,
    run_cancellable,
)
from hephaestus.core.executor.sandbox.base import SandboxSpec
from hephaestus.core.executor.sandbox.oci import (
    OciBackend,
    OciRuntime,
    SubprocessTransport,
    TransportResult,
    TransportTimeout,
)
from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal
from hephaestus.core.executor.sandbox.oci_supervisor import (
    SupervisedOciBackend,
    SupervisorConfig,
    reconcile,
)
from test_sandbox_oci import (
    CONTAINER_ID,
    IDENTITY,
    IMAGE,
    NAME,
    FakeTransport,
    passing,
    runtime,
    spec,
)


@pytest.fixture
def config(tmp_path: Path) -> SupervisorConfig:
    daemon = tmp_path / "daemon"
    daemon.mkdir()
    source = Path(__file__).parent / "fixtures" / "oci_supervisor_cli.py"
    cli = tmp_path / "synthetic-cli"
    paths = [str(Path(p).resolve()) for p in sys.path if p]
    cli.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path[:0] = {paths!r}\n"
        f"sys.argv.insert(1, {str(daemon)!r})\n"
        f"exec(compile(open({str(source)!r}).read(), {str(source)!r}, 'exec'))\n"
    )
    cli.chmod(0o700)
    return SupervisorConfig(
        OciRuntime(
            "docker",
            cli,
            ("--context", "desktop-linux"),
            "unix:///synthetic.sock",
            "Docker Desktop",
        ),
        IMAGE,
        "linux/amd64",
        tmp_path / "supervision",
        IDENTITY,
    )


def edge(path: Path, timeout: float = 20) -> None:
    """Named positive edge with a hang detector; never a negative sleep assertion."""
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            pytest.fail(f"positive edge never arrived: {path}")
        time.sleep(0.01)


def out_spec(tmp_path: Path, **kwargs: object) -> SandboxSpec:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return spec(out, **kwargs)


def test_journal_pre_submission_fsync_restore_and_unknown_absence(tmp_path: Path) -> None:
    binding: dict[str, object] = {"image": IMAGE}
    with OwnershipJournal(tmp_path / "owned", binding) as journal:
        journal.submitted(NAME)
        assert json.loads((tmp_path / "owned/state.json").read_text())["containers"][NAME][
            "pending"
        ]
        journal.absent(NAME, None)
    with OwnershipJournal(tmp_path / "owned", binding) as restored:
        assert restored.pending
        with pytest.raises(SandboxDeniedError, match="reconciliation"):
            restored.require_clean()
        restored.settled(NAME, CONTAINER_ID)
        restored.require_clean()
    with pytest.raises(SandboxDeniedError, match="binding"):
        OwnershipJournal(tmp_path / "owned", {"image": "changed"})


@pytest.mark.parametrize(
    "mutation",
    ["version", "float-version", "missing-launch", "launch-type", "client-type"],
)
def test_restored_journal_schema_rejects_skew(tmp_path: Path, mutation: str) -> None:
    directory = tmp_path / "owned"
    with OwnershipJournal(directory, {}) as journal:
        state = record(journal.state)
    if mutation == "version":
        state["version"] = 2
    elif mutation == "float-version":
        state["version"] = 1.0
    elif mutation == "missing-launch":
        state.pop("launch_pending")
    elif mutation == "launch-type":
        state["launch_pending"] = 0
    else:
        record(state["clients"])["123"] = {"reaped": 1}
    (directory / "state.json").write_text(json.dumps(state))
    with pytest.raises(SandboxDeniedError):
        OwnershipJournal(directory, {})


def test_spawn_gap_is_durable_before_pid_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*_: object, **__: object) -> Never:
        raise OSError("injected spawn failure")

    monkeypatch.setattr(subprocess, "Popen", failed)
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        with pytest.raises(OSError, match="spawn failure"):
            SubprocessTransport(ownership=journal).run(
                (sys.executable, "-c", "pass"),
                input=b"",
                timeout=5,
                stdout_limit=1024,
                stderr_limit=1024,
                env={},
            )
        assert journal.pending and journal.state["launch_pending"]
        assert journal.state["clients"] == {}
    with OwnershipJournal(tmp_path / "owned", {}) as restored:
        assert restored.pending


def test_journal_lock_and_permissions(tmp_path: Path) -> None:
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        with pytest.raises(BlockingIOError):
            OwnershipJournal(tmp_path / "owned", {})
        journal.require_clean()
    (tmp_path / "owned").chmod(0o755)
    with pytest.raises(SandboxDeniedError, match="private"):
        OwnershipJournal(tmp_path / "owned", {})


@pytest.mark.parametrize(
    "failure",
    [
        TransportTimeout(),
        OSError("daemon disconnected"),
        KeyboardInterrupt(),
        RuntimeError("death"),
    ],
)
def test_create_fault_retains_durable_pending_even_when_absent(
    tmp_path: Path, failure: BaseException
) -> None:
    absent = TransportResult(1, b"", b"no such container")
    transport = FakeTransport([failure, *([absent] * 5)])
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        backend = OciBackend(
            runtime(),
            IMAGE,
            "linux/amd64",
            identity=IDENTITY,
            transport=transport,
            ownership=journal,
        )
        passing(backend)
        with pytest.raises(SandboxDeniedError, match="settlement"):
            backend.execute(out_spec(tmp_path), b'{"out_dir":"."}')
        assert journal.pending
        assert all(r["pending"] for r in journal.state["containers"].values())
    with (
        OwnershipJournal(tmp_path / "owned", {}) as restored,
        pytest.raises(SandboxDeniedError, match="reconciliation"),
    ):
        OciBackend(runtime(), IMAGE, "linux/amd64", identity=IDENTITY, ownership=restored)


def test_delayed_create_cancel_waits_for_ack_then_reaps_known_container(tmp_path: Path) -> None:
    started, release = threading.Event(), threading.Event()

    class Delayed(FakeTransport):
        def run(
            self,
            argv: Sequence[str],
            *,
            input: bytes,
            timeout: float,
            stdout_limit: int,
            stderr_limit: int,
            env: Mapping[str, str],
            stdout_consumer: Callable[[bytes], None] | None = None,
        ) -> TransportResult:
            if "create" in argv:
                # Positive proof the exact owned name is durable before submission.
                record = json.loads((tmp_path / "owned/state.json").read_text())
                assert record["containers"][argv[argv.index("--name") + 1]]["pending"]
                started.set()
                assert release.wait(5), "delayed create release not delivered"
            return super().run(
                argv,
                input=input,
                timeout=timeout,
                stdout_limit=stdout_limit,
                stderr_limit=stderr_limit,
                env=env,
                stdout_consumer=stdout_consumer,
            )

    transport = Delayed(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportResult(0, b'{"Running":false,"ExitCode":0,"OOMKilled":false}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such object"),
        ]
    )
    with Cancellation() as control, OwnershipJournal(tmp_path / "owned", {}) as journal:
        backend = OciBackend(
            runtime(),
            IMAGE,
            "linux/amd64",
            identity=IDENTITY,
            transport=transport,
            ownership=journal,
            cancellation=control,
        )
        passing(backend)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(backend.execute, out_spec(tmp_path), b'{"out_dir":"."}')
            assert started.wait(5), "create was not submitted"
            control.cancel()
            release.set()
            with pytest.raises(ExecutionCancelled, match="user_cancel"):
                future.result(timeout=5)
        assert not journal.pending
        assert not any("start" in call[0] for call in transport.calls)
        assert any("rm" in call[0] for call in transport.calls)


def test_recovery_removes_acknowledged_resource_not_unrelated(tmp_path: Path) -> None:
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        journal.submitted(NAME)
        journal.settled(NAME, CONTAINER_ID)
    transport = FakeTransport(
        [
            TransportResult(0, b'{"Running":false,"ExitCode":137,"OOMKilled":false}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such container"),
        ]
    )
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        backend = OciBackend(
            runtime(), IMAGE, "linux/amd64", identity=IDENTITY, transport=transport
        )
        backend.reconcile_owned(journal)
        journal.require_clean()
        assert all(call[0][-1] == CONTAINER_ID for call in transport.calls)


def test_recovery_does_not_kill_reused_pid_or_settle_unknown_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        journal.submitted(NAME)
        journal.client(os.getpid(), reaped=False)

    def forbidden_kill(*_: object) -> Never:
        pytest.fail("must not signal restored PID")

    monkeypatch.setattr(os, "kill", forbidden_kill)
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        backend = OciBackend(
            runtime(),
            IMAGE,
            "linux/amd64",
            identity=IDENTITY,
            transport=FakeTransport([TransportResult(1, b"", b"no such container")]),
        )
        with pytest.raises(SandboxDeniedError, match="reconciliation"):
            backend.reconcile_owned(journal)
        assert journal.pending


def test_transport_delivered_cancel_reaps_client_and_preserves_kind(tmp_path: Path) -> None:
    ready = threading.Event()

    def consume(_: bytes) -> None:
        ready.set()

    with Cancellation() as control, OwnershipJournal(tmp_path / "owned", {}) as journal:
        transport = SubprocessTransport(cancellation=control, ownership=journal)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(
                transport.run,
                (
                    sys.executable,
                    "-c",
                    "import time; print('ready',flush=True); time.sleep(10)",
                    "start",
                ),
                input=b"",
                timeout=15,
                stdout_limit=1024,
                stderr_limit=1024,
                env={},
                stdout_consumer=consume,
            )
            assert ready.wait(5), "client never reached running edge"
            control.cancel()
            with pytest.raises(ExecutionCancelled):
                future.result(timeout=5)
        assert journal.state["clients"]
        assert all(r["reaped"] for r in journal.state["clients"].values())


def test_transport_reaps_real_client_child_group(tmp_path: Path) -> None:
    # Finite trusted local client fixture; not a container workload/backdoor.
    program = (
        "import os,time; pid=os.fork(); "
        'exec("if pid == 0:\\n os.close(0); os.close(1); os.close(2); time.sleep(10)\\n'
        'else:\\n print(pid,flush=True)")'
    )
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        result = SubprocessTransport(ownership=journal).run(
            (sys.executable, "-c", program),
            input=b"",
            timeout=5,
            stdout_limit=1024,
            stderr_limit=1024,
            env={},
        )
        assert result.returncode == 0
        child_pid = int(result.stdout)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        journal.require_clean()


def test_async_cleanup_failure_is_not_masked_as_user_cancel() -> None:
    entered = threading.Event()

    def worker() -> Never:
        control = current_cancellation.get()
        assert control is not None
        entered.set()
        import selectors

        with selectors.DefaultSelector() as selector:
            selector.register(control.reader, selectors.EVENT_READ)
            assert selector.select(5)
        raise SandboxDeniedError("cleanup uncertain")

    async def scenario() -> None:
        task = asyncio.create_task(run_cancellable(worker))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(SandboxDeniedError, match="cleanup uncertain"):
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())


def test_async_cancellation_waits_for_real_sync_cleanup() -> None:
    entered, delivered, cleanup = threading.Event(), threading.Event(), threading.Event()

    def worker() -> None:
        control = current_cancellation.get()
        assert control is not None
        entered.set()
        import selectors

        with selectors.DefaultSelector() as selector:
            selector.register(control.reader, selectors.EVENT_READ)
            assert selector.select(5), "cancellation not delivered to sync worker"
        delivered.set()
        assert cleanup.wait(5), "cleanup release missing"
        control.check()

    async def scenario() -> None:
        task = asyncio.create_task(run_cancellable(worker))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        assert await asyncio.to_thread(delivered.wait, 5)
        assert not task.done()  # positive delivered edge, not a fixed sleep
        task.cancel()  # repeated cancellation must not abandon cleanup
        cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())


def test_supervisor_real_spawn_probe_execute_and_reuse(
    config: SupervisorConfig, tmp_path: Path
) -> None:
    with SupervisedOciBackend(config) as backend:
        report = backend.probe()
        assert report.available, report.reason
        result = backend.execute(out_spec(tmp_path), b'{"out_dir":"."}')
        assert result.exit_code == 0 and not result.timed_out
        assert result.execution_identity == backend.execution_identity()
        assert backend.last_directory is not None
        evidence = json.loads((backend.last_directory / "result.json").read_text())
        assert evidence["accepted"] is False
        assert evidence["terminal"]["OOMKilled"] is False
        assert (backend.last_directory / "reaped.json").exists()
        assert (backend.last_directory / "owner-final.json").exists()
    with SupervisedOciBackend(config):
        pass  # ordinary settled executions do not poison restored reuse
    assert not list((tmp_path / "daemon").glob("*.json"))


@pytest.mark.parametrize("stop", ["user", "caller", "timeout", "remove-failure"])
def test_supervisor_running_delivery_and_cleanup(
    config: SupervisorConfig, tmp_path: Path, stop: str
) -> None:
    daemon = tmp_path / "daemon"
    (daemon / "hold-worker").touch()
    with SupervisedOciBackend(config) as backend:
        report = backend.probe()
        assert report.available, report.reason
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(
                backend.execute, out_spec(tmp_path, wall_clock_s=3), b'{"out_dir":"."}'
            )
            edge(daemon / "worker-entered")
            observed = backend.observe_running()
            assert record(observed["state"])["Running"] is True
            if stop == "remove-failure":
                (daemon / "fail-remove").touch()
            if stop != "timeout":
                assert backend.cancel_active("caller_cancel" if stop == "caller" else "user_cancel")
            if stop in {"user", "caller"}:
                with pytest.raises(ExecutionCancelled):
                    future.result(timeout=15)
            elif stop == "remove-failure":
                with pytest.raises(SandboxDeniedError, match="cleanup"):
                    future.result(timeout=15)
            else:
                result = future.result(timeout=15)
                assert result.timed_out and result.exit_code == 137
        assert backend.last_directory is not None
        evidence = json.loads((backend.last_directory / "result.json").read_text())
        assert (
            evidence["outcome"]
            == {
                "user": "user_cancel",
                "caller": "caller_cancel",
                "timeout": "timeout",
                "remove-failure": "failure",
            }[stop]
        )
        assert evidence["terminal"] == {"Running": False, "ExitCode": 137, "OOMKilled": False}
        commands = [
            json.loads(p.read_text()) for p in backend.last_directory.glob("command-*.json")
        ]
        assert any("kill" in c["argv"] and c.get("returncode") == 0 for c in commands)
        if stop in {"user", "caller"}:
            received = json.loads((backend.last_directory / "stop-received.json").read_text())
            assert received["monotonic_ns"] > integer(observed["monotonic_ns"])
            assert received["reason"] == evidence["outcome"]
        if stop == "remove-failure":
            (daemon / "fail-remove").unlink()
            reconcile(config)
        else:
            assert not list(daemon.glob("*.json"))


def test_restored_dead_owner_refuses_even_without_known_create(config: SupervisorConfig) -> None:
    config.directory.mkdir(mode=0o700)
    operation = config.directory / "operation-00"
    operation.mkdir()
    (operation / "request.json").write_text("{}")
    with pytest.raises(SandboxDeniedError, match="unfinished"):
        SupervisedOciBackend(config)


def test_cancellation_evidence_disk_failure_still_delivers_cleanup(
    config: SupervisorConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephaestus.core.executor.sandbox import oci_supervisor

    daemon = tmp_path / "daemon"
    (daemon / "hold-worker").touch()
    with SupervisedOciBackend(config) as backend, ThreadPoolExecutor(1) as pool:
        assert backend.probe().available
        future = pool.submit(backend.execute, out_spec(tmp_path), b'{"out_dir":"."}')
        edge(daemon / "worker-entered")
        real = oci_supervisor.save_evidence

        def failing(path: Path, value: object) -> None:
            if path.name == "stop-request.json":
                raise OSError("evidence disk full")
            real(path, value)

        monkeypatch.setattr(oci_supervisor, "save_evidence", failing)
        with pytest.raises(OSError, match="disk full"):
            backend.cancel_active()
        with pytest.raises(ExecutionCancelled):
            future.result(timeout=10)
        assert not list(daemon.glob("*.json"))
        assert backend.last_directory is not None
        assert not (backend.last_directory / "stop-request.json").exists()


def test_supervisor_cancel_during_create_is_delivered_without_losing_ack(
    config: SupervisorConfig, tmp_path: Path
) -> None:
    daemon = tmp_path / "daemon"
    (daemon / "delay-create").touch()
    with SupervisedOciBackend(config) as backend, ThreadPoolExecutor(1) as pool:
        future = pool.submit(backend.probe)
        edge(daemon / "create-entered")
        assert backend.cancel_active()
        assert backend.last_directory is not None
        edge(backend.last_directory / "stop-received.json")
        # The acknowledgement is held, so cancellation has not killed the client.
        assert not future.done()
        (daemon / "release-create").touch()
        with pytest.raises(ExecutionCancelled):
            future.result(timeout=10)
        state = json.loads((config.directory / "ownership/state.json").read_text())
        assert all(not r["pending"] and r["absent"] for r in state["containers"].values())
        assert all(r["reaped"] for r in state["clients"].values())
    assert not list(daemon.glob("*.json"))


def test_parent_process_death_delivers_eof_and_cleans_worker(
    config: SupervisorConfig, tmp_path: Path
) -> None:
    import pickle

    daemon = tmp_path / "daemon"
    (daemon / "hold-worker").touch()
    request = tmp_path / "parent-request.bin"
    request.write_bytes(pickle.dumps((config, out_spec(tmp_path))))
    parent = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import pickle,sys; from hephaestus.core.executor.sandbox.oci_supervisor import "
            "SupervisedOciBackend; c,s=pickle.load(open(sys.argv[1],'rb')); "
            "b=SupervisedOciBackend(c); assert b.probe().available; "
            'b.execute(s,b\'{\\"out_dir\\":\\".\\"}\')',
            str(request),
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        edge(daemon / "worker-entered")
        parent.kill()  # exact live Popen child, not a restored PID or name sweep
        parent.wait(timeout=5)
        directory = config.directory / "operation-01"
        edge(directory / "owner-final.json")
        evidence = json.loads((directory / "result.json").read_text())
        assert evidence["outcome"] == "parent_closed", evidence
        assert not list(daemon.glob("*.json"))
        # Independent cleanup completed; no claim of waitpid by the dead parent.
        assert not (directory / "reaped.json").exists()
        with SupervisedOciBackend(config):
            pass
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)


def test_owner_death_during_create_keeps_pending_after_resource_recovery(
    config: SupervisorConfig, tmp_path: Path
) -> None:
    daemon = tmp_path / "daemon"
    with SupervisedOciBackend(config) as backend:
        assert backend.probe().available
        (daemon / "delay-create").touch()
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(backend.execute, out_spec(tmp_path), b'{"out_dir":"."}')
            edge(daemon / "create-entered")
            assert backend.last_owner_pid is not None
            os.kill(backend.last_owner_pid, signal.SIGKILL)
            (daemon / "release-create").touch()  # bounded synthetic client may now exit
            with pytest.raises(SandboxDeniedError, match="owner disconnected"):
                future.result(timeout=10)
        with pytest.raises(SandboxDeniedError, match="reconciliation"):
            reconcile(config)
        assert not list(daemon.glob("*.json"))  # resource reclamation, NOT settlement
    with pytest.raises(SandboxDeniedError, match="unfinished"):
        SupervisedOciBackend(config)


@pytest.mark.parametrize("failure", ["timeout", "wait-error"])
def test_lost_owner_reap_ack_refuses_reuse_after_actual_child_exit(
    config: SupervisorConfig, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original_wait = subprocess.Popen[bytes].wait
    children: list[subprocess.Popen[bytes]] = []

    def lost_wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        children.append(process)
        assert len(children) == 1, "unknown owner ACK must not be retried"
        assert timeout is not None
        if failure == "wait-error":
            raise OSError("wait acknowledgement lost")
        raise subprocess.TimeoutExpired(process.args, timeout)

    with SupervisedOciBackend(config) as backend:
        try:
            with monkeypatch.context() as patch:
                patch.setattr(subprocess.Popen, "wait", lost_wait)
                assert not backend.probe().available
        finally:
            if children:
                original_wait(children[0], timeout=10)
        assert len(children) == 1 and children[0].returncode == 0
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        assert backend.last_directory is not None
        assert (backend.last_directory / "owner-final.json").is_file()
        assert not (backend.last_directory / "reaped.json").exists()
        with pytest.raises(SandboxDeniedError, match="settlement evidence missing"):
            backend.require_settled()
        report = backend.probe()
        assert not report.available and report.reason is not None
        assert "session closed" in report.reason
        assert len(list(config.directory.glob("operation-*"))) == 1


def test_local_reaping_failure_retains_durable_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephaestus.core.executor.sandbox.oci import TransportReapError

    def failed(*_: object) -> Never:
        raise TransportReapError("injected group-reap uncertainty")

    monkeypatch.setattr(SubprocessTransport, "_reap_group", failed)
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        with pytest.raises(TransportReapError):
            SubprocessTransport(ownership=journal).run(
                (sys.executable, "-c", "print('finite')"),
                input=b"",
                timeout=5,
                stdout_limit=1024,
                stderr_limit=1024,
                env={},
            )
        assert journal.pending
        assert any(not r["reaped"] for r in journal.state["clients"].values())


def test_journal_failure_prevents_create_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with OwnershipJournal(tmp_path / "owned", {}) as journal:
        transport = FakeTransport()
        backend = OciBackend(
            runtime(),
            IMAGE,
            "linux/amd64",
            identity=IDENTITY,
            transport=transport,
            ownership=journal,
        )
        passing(backend)

        def fail() -> Never:
            raise OSError("injected disk full")

        monkeypatch.setattr(journal, "_save", fail)
        with pytest.raises(OSError, match="disk full"):
            backend.execute(out_spec(tmp_path), b'{"out_dir":"."}')
        assert transport.calls == []


def test_workspace_projection_uses_actual_injection_without_loading_cad() -> None:
    # Execute the actual dependency-free projection method in isolation. This is
    # a wiring unit, NOT a WorkspaceRuntime.open/browser integration test.
    import ast
    from types import SimpleNamespace

    from hephaestus.core.executor.sandbox.base import CapabilityReport

    source = Path(__file__).parents[2] / "server/src/hephaestus/http/runtime.py"
    module = ast.parse(source.read_text())
    cls = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "WorkspaceRuntime"
    )
    method = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_secure_executor_available"
    )
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    project = namespace["_secure_executor_available"]
    assert callable(project)
    for available, unsafe, name in (
        (True, False, "oci-docker"),
        (False, False, "oci-docker"),
        (True, True, "oci-docker"),
        (True, False, "wrong"),
    ):

        def probe(n: str = name, a: bool = available) -> CapabilityReport:
            return CapabilityReport(n, a, None if a else "blocked")

        backend = SimpleNamespace(name="oci-docker", unsafe=unsafe, probe=probe)
        assert project(SimpleNamespace(backend=backend)) is (
            available and not unsafe and name == "oci-docker"
        )


def test_experimental_limits_before_spawn(
    config: SupervisorConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from _execution_identity import identity

    backend = SupervisedOciBackend(config)
    monkeypatch.setattr(backend, "_identity", identity())
    with pytest.raises(SandboxDeniedError, match="limits"):
        backend.execute(out_spec(tmp_path, wall_clock_s=181), b"{}")
    assert backend.last_owner_pid is None
    backend.close()


@pytest.mark.parametrize("capture", [None, "not bytes", 7, b"x" * 9, b"bounded"])
def test_evidence_exception_capture_is_bounded_and_never_fabricated(
    tmp_path: Path, capture: object
) -> None:
    from hephaestus.core.executor.sandbox.oci_supervisor import EvidenceTransport

    class CaptureError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("original transport failure")
            self.stdout = capture
            self.stderr = capture

    failure = CaptureError()
    transport = EvidenceTransport(FakeTransport([failure]), tmp_path)
    with pytest.raises(CaptureError) as caught:
        transport.run(("synthetic",), input=b"", timeout=1, stdout_limit=8, stderr_limit=8, env={})
    assert caught.value is failure
    evidence = json.loads((tmp_path / "command-001.json").read_text())
    assert evidence["error"] == "CaptureError"
    for channel in ("stdout", "stderr"):
        if capture == b"bounded":
            assert evidence[channel]["bytes"] == 7
            assert evidence[channel]["prefix_base64"] == "Ym91bmRlZA=="
        else:
            assert evidence[channel] == {"available": False}
    assert "returncode" not in evidence


def test_evidence_raising_capture_property_preserves_original_failure(tmp_path: Path) -> None:
    from hephaestus.core.executor.sandbox.oci_supervisor import EvidenceTransport

    class BrokenCapture(RuntimeError):
        @property
        def stdout(self) -> bytes:
            raise ValueError("capture unavailable")

    failure = BrokenCapture("original failure")
    transport = EvidenceTransport(FakeTransport([failure]), tmp_path)
    with pytest.raises(BrokenCapture) as caught:
        transport.run(("synthetic",), input=b"", timeout=1, stdout_limit=8, stderr_limit=8, env={})
    assert caught.value is failure
    evidence = json.loads((tmp_path / "command-001.json").read_text())
    assert evidence["stdout"] == evidence["stderr"] == {"available": False}
    assert evidence["error"] == "BrokenCapture"
