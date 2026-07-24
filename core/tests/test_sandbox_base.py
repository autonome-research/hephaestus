"""ExecBackend protocol / SandboxSpec / CapabilityReport contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    ExecBackend,
    ExecOutcome,
    Rlimits,
    SandboxSpec,
)

RLIMITS = Rlimits(cpu_seconds=60, address_space_bytes=4 << 30, nproc=16)


def make_spec(tmp_path: Path) -> SandboxSpec:
    return SandboxSpec(
        worker_cmd=("python", "-m", "hephaestus.core.executor.worker"),
        ro_binds=(tmp_path / "project", tmp_path / "venv"),
        rw_out_dir=tmp_path / "out",
        rlimits=RLIMITS,
        wall_clock_s=30.0,
    )


class FakeBackend:
    """Minimal structural implementation of ExecBackend."""

    def __init__(self) -> None:
        self.executed: list[tuple[SandboxSpec, bytes]] = []

    @property
    def name(self) -> str:
        return "fake"

    def probe(self) -> CapabilityReport:
        return CapabilityReport(backend="fake", available=True, features={"userns": True})

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        self.executed.append((spec, stdin_payload))
        return ExecOutcome(exit_code=0, stdout=b"{}", stderr=b"")


class TestProtocol:
    def test_structural_conformance(self) -> None:
        backend = FakeBackend()
        assert isinstance(backend, ExecBackend)

    def test_execute_round_trip(self, tmp_path: Path) -> None:
        backend = FakeBackend()
        spec = make_spec(tmp_path)
        outcome = backend.execute(spec, b'{"script": ""}')
        assert outcome.exit_code == 0
        assert not outcome.timed_out
        assert backend.executed == [(spec, b'{"script": ""}')]

    def test_non_backend_rejected(self) -> None:
        assert not isinstance(object(), ExecBackend)


class TestSandboxSpec:
    def test_holds_worker_view(self, tmp_path: Path) -> None:
        spec = make_spec(tmp_path)
        assert spec.rw_out_dir == tmp_path / "out"
        assert spec.rlimits.cpu_seconds == 60
        assert len(spec.ro_binds) == 2

    def test_empty_worker_cmd_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            SandboxSpec(
                worker_cmd=(),
                ro_binds=(),
                rw_out_dir=tmp_path,
                rlimits=RLIMITS,
                wall_clock_s=30.0,
            )

    def test_nonpositive_wall_clock_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            SandboxSpec(
                worker_cmd=("python",),
                ro_binds=(),
                rw_out_dir=tmp_path,
                rlimits=RLIMITS,
                wall_clock_s=0.0,
            )


class TestRlimits:
    @pytest.mark.parametrize(
        ("cpu", "address_space", "nproc"),
        [(0, 1, 1), (1, 0, 1), (1, 1, 0), (-1, 1, 1)],
    )
    def test_nonpositive_limits_rejected(self, cpu: int, address_space: int, nproc: int) -> None:
        with pytest.raises(ValueError):
            Rlimits(cpu_seconds=cpu, address_space_bytes=address_space, nproc=nproc)


class TestCapabilityReport:
    def test_unavailable_requires_reason(self) -> None:
        with pytest.raises(ValueError):
            CapabilityReport(backend="bwrap", available=False)

    def test_fail_closed_report_carries_reason(self) -> None:
        report = CapabilityReport(
            backend="bwrap",
            available=False,
            reason="bwrap binary not found",
            features={"userns": False},
        )
        assert not report.available
        assert report.reason == "bwrap binary not found"

    def test_empty_backend_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            CapabilityReport(backend="", available=True)

    def test_equality_includes_features(self) -> None:
        a = CapabilityReport(backend="bwrap", available=True, features={"userns": True})
        b = CapabilityReport(backend="bwrap", available=True, features={"userns": True})
        c = CapabilityReport(backend="bwrap", available=True, features={"userns": False})
        assert a == b
        assert a != c
        assert a != "bwrap"
