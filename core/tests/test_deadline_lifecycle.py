# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Deterministic progression, synthetic daemon responses; NOT Mac sleep evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from hephaestus.core import deadline as clocks
from hephaestus.core.deadline import Deadline
from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox.oci import OciBackend, TransportResult
from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal
from hephaestus.core.executor.sandbox.oci_supervisor import SupervisedOciBackend, SupervisorConfig
from test_sandbox_oci import CONTAINER_ID, IDENTITY, IMAGE, FakeTransport, passing, runtime, spec


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize("cleanup_jump", [False, True])
def test_expired_create_does_not_start_and_cleanup_has_its_own_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, advance: bool, cleanup_jump: bool
) -> None:
    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])

    class Transport(FakeTransport):
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
            result = super().run(
                argv,
                input=input,
                timeout=timeout,
                stdout_limit=stdout_limit,
                stderr_limit=stderr_limit,
                env=env,
                stdout_consumer=stdout_consumer,
            )
            if advance and "create" in argv:
                now[0] += 21_000_000_000
            if cleanup_jump and "rm" in argv:
                now[0] += 31_000_000_000
            return result

    results = [TransportResult(0, (CONTAINER_ID + "\n").encode(), b"")]
    if not advance:
        results.append(TransportResult(0, b"worker", b""))
    results.extend(
        [
            TransportResult(0, b'{"Running":false,"ExitCode":0,"OOMKilled":false}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such container"),
        ]
    )
    transport = Transport(results)
    out = tmp_path / "out"
    out.mkdir()
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
        if cleanup_jump:
            with pytest.raises(SandboxDeniedError, match="cleanup was ambiguous"):
                backend.execute(spec(out), b'{"out_dir":"."}')
            with pytest.raises(SandboxDeniedError):
                journal.require_clean()
        else:
            result = backend.execute(spec(out), b'{"out_dir":"."}')
            assert result.timed_out is advance
            journal.require_clean()
        commands = [call[0] for call in transport.calls]
        assert any("start" in argv for argv in commands) is not advance
        assert any("rm" in argv for argv in commands)  # expired work still gets cleanup


def test_expired_session_refuses_owner_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    deadline = Deadline.after(10)
    config = SupervisorConfig(
        runtime(),
        IMAGE,
        "linux/amd64",
        tmp_path / "supervision",
        IDENTITY,
        deadline=deadline,
    )
    with SupervisedOciBackend(config) as backend:
        now[0] += 10_000_000_000
        report = backend.probe()
        assert not report.available
        assert report.reason is not None and "deadline expired" in report.reason
        assert not list(config.directory.glob("operation-*"))
        assert backend.last_owner_pid is None
