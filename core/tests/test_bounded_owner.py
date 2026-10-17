"""Independent owners share deadline/drain machinery, but NEVER kill on terminal.

These children hold no CAD/container resources. Every real child has its own
10-second alarm; parent waits are bounded separately. The EOF marker is the
positive cleanup edge, not a sleep-based claim that a child probably exited.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from hephaestus.core.executor.bounded_pass import (
    ChildConnection,
    OwnerRefusal,
    run_independent_owner,
)

CHILD = """
import os, signal, sys
from multiprocessing.connection import Connection
from pathlib import Path
signal.alarm(10)
conn = Connection(int(sys.argv[1]))
marker = Path(sys.argv[2])
mode = sys.argv[3]
if mode == 'crash':
    conn.close()
    sys.exit(7)
if mode == 'cancel':
    assert conn.recv_bytes(64) == b'cancel'
if mode not in ('silent', 'start-failure'):
    try:
        conn.send_bytes(b'x' * 65 if mode == 'oversized' else b'terminal')
    except OSError:
        pass
try:
    conn.recv_bytes(64)
except (EOFError, OSError):
    marker.write_text('parent EOF; cleanup complete')
conn.close()
if mode == 'held-cleanup':
    import time
    while not marker.with_suffix('.release').exists():
        time.sleep(0.01)
sys.exit(9 if mode == 'bad-exit' else 0)
"""


@dataclass
class Evidence:
    pid: int | None = None
    connection: ChildConnection | None = None
    reaped: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])
    unreaped: bool = False

    def started(self, pid: int, connection: ChildConnection) -> None:
        self.pid, self.connection = pid, connection

    def acknowledge(self, pid: int, exitcode: int) -> None:
        # The callback cannot run before waitpid has actually reaped the child.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        self.reaped.append((pid, exitcode))

    def poison(self) -> None:
        self.unreaped = True

    def cancel(self) -> None:
        assert self.connection is not None
        self.connection.send_bytes(b"cancel")


def invoke(
    path: Path,
    mode: str,
    evidence: Evidence,
    *,
    cancel_fd: int | None = None,
    timeout_s: float = 3,
    reap_s: float = 10,
) -> bytes:
    def started(pid: int, connection: ChildConnection) -> None:
        evidence.started(pid, connection)
        if mode == "start-failure":
            raise OSError("owner record persistence failed")

    return run_independent_owner(
        lambda fd: (sys.executable, "-c", CHILD, str(fd), str(path), mode),
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        timeout_s=timeout_s,
        maximum=64,
        on_started=started,
        on_reaped=evidence.acknowledge,
        on_unreaped=evidence.poison,
        cancel_fd=cancel_fd,
        on_cancel=evidence.cancel,
        reap_s=reap_s,
    )


def assert_closed(evidence: Evidence) -> None:
    assert evidence.pid is not None
    assert evidence.connection is not None and evidence.connection.closed
    with pytest.raises(ProcessLookupError):
        os.kill(evidence.pid, 0)


def test_terminal_closes_control_and_waits_for_independent_cleanup(tmp_path: Path) -> None:
    evidence = Evidence()
    marker = tmp_path / "cleanup"
    assert invoke(marker, "terminal", evidence) == b"terminal"
    assert marker.read_text() == "parent EOF; cleanup complete"
    assert evidence.reaped == [(evidence.pid, 0)]
    assert not evidence.unreaped
    assert_closed(evidence)


def test_control_cancellation_is_delivered_before_terminal(tmp_path: Path) -> None:
    reader, writer = os.pipe()
    evidence = Evidence()
    try:
        os.write(writer, b"cancel-ready")
        marker = tmp_path / "cleanup"
        assert invoke(marker, "cancel", evidence, cancel_fd=reader) == b"terminal"
        assert marker.is_file()
        assert evidence.reaped == [(evidence.pid, 0)]
        assert_closed(evidence)
    finally:
        os.close(reader)
        os.close(writer)


def test_control_evidence_failure_is_not_misread_as_channel_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OSError("cancel evidence persistence failed")

    def fail(evidence: Evidence) -> None:
        assert evidence.connection is not None
        evidence.connection.send_bytes(b"cancel")
        raise failure

    monkeypatch.setattr(Evidence, "cancel", fail)
    reader, writer = os.pipe()
    evidence = Evidence()
    marker = tmp_path / "cleanup"
    try:
        os.write(writer, b"cancel-ready")
        with pytest.raises(OSError) as caught:
            invoke(marker, "cancel", evidence, cancel_fd=reader)
        assert caught.value is failure
        assert evidence.reaped == []
        assert marker.is_file()
        assert_closed(evidence)
    finally:
        os.close(reader)
        os.close(writer)


@pytest.mark.parametrize("mode", ["silent", "crash", "bad-exit", "oversized", "start-failure"])
def test_refusals_close_and_reap_without_acknowledging_success(tmp_path: Path, mode: str) -> None:
    evidence = Evidence()
    marker = tmp_path / "cleanup"
    error = OSError if mode == "start-failure" else OwnerRefusal
    with pytest.raises(error):
        invoke(marker, mode, evidence, timeout_s=0.25 if mode == "silent" else 3)
    if mode != "crash":
        assert marker.read_text() == "parent EOF; cleanup complete"
    assert evidence.reaped == []
    assert not evidence.unreaped
    assert_closed(evidence)


@pytest.mark.parametrize("failure", ["timeout", "wait-error"])
def test_lost_reap_acknowledgement_poisons_even_if_child_eventually_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original_wait = subprocess.Popen[bytes].wait
    children: list[subprocess.Popen[bytes]] = []

    def lost_wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        children.append(process)
        assert timeout is not None
        if failure == "wait-error":
            raise OSError("wait acknowledgement lost")
        raise subprocess.TimeoutExpired(process.args, timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", lost_wait)
    evidence = Evidence()
    marker = tmp_path / "cleanup"
    try:
        with pytest.raises(OSError if failure == "wait-error" else OwnerRefusal):
            invoke(marker, "terminal", evidence)
        assert evidence.unreaped
        assert evidence.reaped == []
        assert len(children) == 1  # no silent retry doubling the reap budget
    finally:
        for process in children:
            original_wait(process, timeout=10)
    assert marker.is_file()
    assert_closed(evidence)


def test_genuine_reap_timeout_poisons_before_the_child_is_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_wait = subprocess.Popen[bytes].wait
    children: list[subprocess.Popen[bytes]] = []

    def wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        assert timeout is not None and 0 < timeout <= 0.1
        children.append(process)
        return original_wait(process, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", wait)
    evidence = Evidence()
    marker = tmp_path / "cleanup"
    try:
        with pytest.raises(OwnerRefusal, match="cleanup deadline"):
            invoke(marker, "held-cleanup", evidence, reap_s=0.25)
        assert marker.read_text() == "parent EOF; cleanup complete"
        assert evidence.unreaped and evidence.reaped == []
        assert 1 <= len(children) <= 3  # ceil(0.25 / 0.1), one cleanup allowance
        assert all(process is children[0] for process in children)
        assert children[0].returncode is None  # still held, not inferred from a sleep
    finally:
        marker.with_suffix(".release").touch()
        if children:
            original_wait(children[0], timeout=10)
    assert evidence.unreaped and evidence.reaped == []  # late exit never upgrades the ACK
    assert_closed(evidence)


def test_durable_reap_record_failure_poisons_after_actual_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_self: Evidence, _pid: int, _exitcode: int) -> None:
        raise OSError("reap record persistence failed")

    monkeypatch.setattr(Evidence, "acknowledge", fail)
    evidence = Evidence()
    marker = tmp_path / "cleanup"
    with pytest.raises(OSError, match="reap record persistence"):
        invoke(marker, "terminal", evidence)
    assert evidence.unreaped and evidence.reaped == []
    assert marker.is_file()
    assert_closed(evidence)


def test_spawn_failure_closes_both_owned_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from multiprocessing.connection import Pipe

    from hephaestus.core.executor import bounded_pass

    real_pipe = Pipe
    ends: list[ChildConnection] = []

    def pipe(*, duplex: bool) -> tuple[ChildConnection, ChildConnection]:
        pair = real_pipe(duplex=duplex)
        ends.extend(pair)
        return pair

    monkeypatch.setattr(bounded_pass, "Pipe", pipe)
    evidence = Evidence()
    with pytest.raises(FileNotFoundError):
        run_independent_owner(
            lambda _fd: ("/nonexistent/heph-owner",),
            env={},
            timeout_s=1,
            maximum=64,
            on_started=evidence.started,
            on_reaped=evidence.acknowledge,
            on_unreaped=evidence.poison,
            on_cancel=evidence.cancel,
        )
    assert len(ends) == 2 and all(end.closed for end in ends)
    assert evidence.pid is None and not evidence.unreaped
