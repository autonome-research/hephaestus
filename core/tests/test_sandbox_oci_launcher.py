"""Daemon-free tests for the OCI executor protocol and launcher."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

import pytest
from hephaestus.core.executor.sandbox import _oci_probe_worker as probe
from hephaestus.core.executor.sandbox import oci_launcher as launcher
from hephaestus.core.executor.sandbox.oci_protocol import (
    APPROVED_MODULES,
    BUILD_WORKER,
    DFM_WORKER,
    MAX_ADDRESS_SPACE_BYTES,
    MAX_CPU_SECONDS,
    MAX_NPROC,
    PROBE_WORKER,
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    approved_module_for_worker_args,
    diagnostic_bytes,
    manifest_bytes,
    manifest_record,
)


def test_protocol_manifest_is_exact_and_canonical() -> None:
    assert PROTOCOL_NAME == "hephaestus.oci-executor"
    assert PROTOCOL_VERSION == 1
    assert frozenset({BUILD_WORKER, DFM_WORKER, PROBE_WORKER}) == APPROVED_MODULES
    assert manifest_bytes() == manifest_bytes()
    assert manifest_bytes().endswith(b"\n") and manifest_bytes().count(b"\n") == 1
    assert json.loads(manifest_bytes()) == manifest_record()
    assert manifest_record()["workers"] == sorted(APPROVED_MODULES)


@pytest.mark.parametrize("module", sorted(APPROVED_MODULES))
def test_worker_args_require_exact_m_form(module: str) -> None:
    assert approved_module_for_worker_args(("-m", module)) == module


@pytest.mark.parametrize(
    "args",
    [
        ("-c", "pass"),
        ("-m", BUILD_WORKER, "extra"),
        (BUILD_WORKER,),
        ("-m", "executor.worker"),
        ("-m", BUILD_WORKER + ".suffix"),
        ("-m", BUILD_WORKER[:-1]),
        ("-m", ""),
    ],
)
def test_worker_args_refuse_every_near_match(args: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        approved_module_for_worker_args(args)


def test_diagnostic_is_one_canonical_line() -> None:
    assert diagnostic_bytes("worker_not_allowed") == (
        b'{"code":"worker_not_allowed","component":"oci_launcher",'
        b'"diagnostic_version":1,"protocol_version":1}\n'
    )


def test_parse_exact_valid_run() -> None:
    parsed = launcher.parse_argv(
        (
            "run",
            "1",
            BUILD_WORKER,
            str(MAX_CPU_SECONDS),
            str(MAX_ADDRESS_SPACE_BYTES),
            str(MAX_NPROC),
        )
    )
    assert parsed == launcher.LaunchRequest(
        PROTOCOL_VERSION,
        BUILD_WORKER,
        MAX_CPU_SECONDS,
        MAX_ADDRESS_SPACE_BYTES,
        MAX_NPROC,
    )


@pytest.mark.parametrize(
    "value",
    ["", "0", "-1", "+1", "01", " 1", "1 ", "\uff11", "9" * 1000],
)
def test_limit_parser_refuses_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        launcher.parse_argv(("run", "1", BUILD_WORKER, value, "1", "1"))


def test_limit_parser_refuses_values_above_caps() -> None:
    for position, value in (
        (3, str(MAX_CPU_SECONDS + 1)),
        (4, str(MAX_ADDRESS_SPACE_BYTES + 1)),
        (5, str(MAX_NPROC + 1)),
    ):
        args = ["run", "1", BUILD_WORKER, "1", "1", "1"]
        args[position] = value
        with pytest.raises(ValueError):
            launcher.parse_argv(args)


def test_apply_rlimits_orders_core_first_and_never_relaxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = launcher.LaunchRequest(1, BUILD_WORKER, 100, 1000, 100)
    calls: list[tuple[int, tuple[int, int]]] = []
    inherited = {
        launcher.resource.RLIMIT_CORE: (5, 5),
        launcher.resource.RLIMIT_CPU: (50, 60),
        launcher.resource.RLIMIT_AS: (800, 900),
    }
    data = getattr(launcher.resource, "RLIMIT_DATA", None)
    nproc = getattr(launcher.resource, "RLIMIT_NPROC", None)
    if data is not None:
        inherited[data] = (700, 750)
    if nproc is not None:
        inherited[nproc] = (70, 80)

    monkeypatch.setattr(launcher.resource, "getrlimit", lambda kind: inherited[kind])
    monkeypatch.setattr(
        launcher.resource, "setrlimit", lambda kind, value: calls.append((kind, value))
    )
    launcher.apply_rlimits(request)

    assert calls[0] == (launcher.resource.RLIMIT_CORE, (0, 0))
    assert (launcher.resource.RLIMIT_CPU, (50, 60)) in calls
    assert (launcher.resource.RLIMIT_AS, (800, 900)) in calls
    if data is not None:
        assert (data, (700, 750)) in calls
    if nproc is not None:
        assert (nproc, (70, 80)) in calls


def test_limit_failure_prevents_exec_and_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    executed = False

    def fail_limits(request: launcher.LaunchRequest) -> None:
        raise OSError("attacker-controlled text")

    def mark_exec(request: launcher.LaunchRequest) -> NoReturn:
        nonlocal executed
        executed = True
        raise AssertionError

    monkeypatch.setattr(launcher, "apply_rlimits", fail_limits)
    monkeypatch.setattr(launcher, "exec_worker", mark_exec)
    code = launcher.main(("run", "1", BUILD_WORKER, "1", "1", "1"))
    captured = capsys.readouterr()
    assert code == launcher.EXIT_RLIMIT
    assert not executed
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "code": "resource_limit_failed",
        "component": "oci_launcher",
        "diagnostic_version": 1,
        "protocol_version": 1,
    }
    assert "attacker" not in captured.err


def test_exec_worker_uses_absolute_interpreter_and_fixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: tuple[str, list[str], dict[str, str]] | None = None

    def fake_execve(path: str, argv: list[str], env: dict[str, str]) -> NoReturn:
        nonlocal seen
        seen = path, argv, env
        raise OSError

    monkeypatch.setattr(launcher.os, "execve", fake_execve)
    with pytest.raises(OSError):
        launcher.exec_worker(launcher.LaunchRequest(1, BUILD_WORKER, 1, 1, 1))
    assert seen is not None
    assert seen == (
        sys.executable,
        [sys.executable, "-I", "-m", BUILD_WORKER],
        dict(launcher.FIXED_WORKER_ENV),
    )
    assert Path(seen[0]).is_absolute()


def test_launcher_refusal_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert launcher.main(("run", "2", BUILD_WORKER, "1", "1", "1")) == 65
    assert json.loads(capsys.readouterr().err)["code"] == "protocol_version_mismatch"
    assert launcher.main(("run", "1", "not.allowed", "1", "1", "1")) == 66
    assert json.loads(capsys.readouterr().err)["code"] == "worker_not_allowed"


def test_probe_schema_size_nonce_and_deterministic_response() -> None:
    nonce = "a" * 64
    request = probe.parse_request(
        json.dumps({"nonce": nonce, "protocol_version": 1}).encode("ascii")
    )
    with pytest.raises(probe.ProbeRequestError):
        probe.parse_request(b"x" * 1025)
    with pytest.raises(probe.ProbeRequestError):
        probe.parse_request(b'{"nonce":"a","protocol_version":1}')
    with pytest.raises(probe.ProbeRequestError):
        probe.parse_request(
            json.dumps({"nonce": nonce, "protocol_version": 1, "extra": 1}).encode()
        )

    values = {
        getattr(probe.resource, name): (index, index)
        for index, name in enumerate(
            ("RLIMIT_AS", "RLIMIT_CORE", "RLIMIT_CPU", "RLIMIT_DATA", "RLIMIT_NPROC"),
            start=1,
        )
        if hasattr(probe.resource, name)
    }
    result = json.loads(
        probe.probe_bytes(
            request,
            getrlimit=values.__getitem__,
            geteuid=lambda: 65532,
            getegid=lambda: 65532,
        )
    )
    assert result["effective_uid"] == 65532
    assert result["effective_gid"] == 65532
    assert result["identity_matches"] is True
    assert result["kind"] == "hephaestus_executor_probe"
    assert result["nonce"] == nonce
    assert result["non_root"] is True
    assert result["protocol_version"] == 1


def test_probe_reports_wrong_numeric_identity() -> None:
    request = probe.ProbeRequest(nonce="b" * 64, protocol_version=1)
    result = probe.probe_record(
        request,
        getrlimit=lambda _kind: (1, 1),
        geteuid=lambda: 501,
        getegid=lambda: 20,
    )
    assert result["effective_uid"] == 501
    assert result["effective_gid"] == 20
    assert result["non_root"] is True
    assert result["identity_matches"] is False
