# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Khronos negative controls; no CAD kernel or renderer is used here."""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest
from _khronos import BINARY_ENV, LOCK, REQUIRE_ENV, validate_glb, validator_binary


def _glb(document: dict[str, object]) -> bytes:
    payload = json.dumps(document).encode()
    payload += b" " * (-len(payload) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload), len(payload), 0x4E4F534A) + payload


@pytest.mark.parametrize("explicit", [False, True])
def test_missing_required_validator_fails_not_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, explicit: bool
) -> None:
    monkeypatch.setenv(REQUIRE_ENV, "1")
    monkeypatch.setenv("PATH", str(tmp_path))
    if explicit:
        monkeypatch.setenv(BINARY_ENV, str(tmp_path / "missing-validator"))
        with pytest.raises(pytest.fail.Exception, match="Khronos validator missing"):
            validator_binary()
    else:
        monkeypatch.delenv(BINARY_ENV, raising=False)
        with pytest.raises(AssertionError, match="requires an explicit"):
            validator_binary()


def test_wrong_required_executable_fails_integrity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    impostor = tmp_path / "gltf_validator"
    impostor.write_text("not the official binary")
    impostor.chmod(0o755)
    monkeypatch.setenv(REQUIRE_ENV, "1")
    monkeypatch.setenv(BINARY_ENV, str(impostor))
    with pytest.raises(AssertionError, match="SHA-256 mismatch"):
        validator_binary()


@pytest.mark.parametrize(
    ("payload", "issue"),
    [
        (b"not a GLB", "GLB_UNEXPECTED_END_OF_HEADER"),
        (_glb({"asset": {"version": "1.0"}}), "UNKNOWN_ASSET_MAJOR_VERSION"),
    ],
    ids=["malformed-container", "invalid-gltf-semantics"],
)
def test_real_khronos_rejects_bad_glb(tmp_path: Path, payload: bytes, issue: str) -> None:
    binary = validator_binary()
    path = tmp_path / "bad.glb"
    path.write_bytes(payload)
    with pytest.raises(AssertionError, match=r"Khronos rejected.*exit 1") as failure:
        validate_glb(binary, path)
    # Prove the real validator produced error diagnostics, not merely an exec failure.
    assert issue in str(failure.value)
    assert '"numErrors": 1' in str(failure.value)
    print(f"Real Khronos rejected {issue}: exit 1, numErrors=1", flush=True)


def test_real_khronos_accepts_minimal_glb(tmp_path: Path) -> None:
    binary = validator_binary()
    path = tmp_path / "minimal.glb"
    path.write_bytes(_glb({"asset": {"version": "2.0"}}))
    assert validate_glb(binary, path)["issues"]["numErrors"] == 0


def test_validator_invocation_failure_is_not_validation(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_glb(str(tmp_path / "missing"), tmp_path / "unused.glb")


@pytest.mark.parametrize(
    ("returncode", "stdout", "error"),
    [
        (7, "", AssertionError),
        (0, "", ValueError),
        (0, "{}", KeyError),
        (0, json.dumps({"validatorVersion": LOCK["version"], "issues": {}}), KeyError),
        (
            0,
            json.dumps({"validatorVersion": LOCK["version"], "issues": {"numErrors": 1}}),
            AssertionError,
        ),
    ],
    ids=["nonzero-exit", "missing-report", "empty-report", "missing-error-count", "errors"],
)
def test_failed_or_incomplete_reports_never_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: str,
    error: type[Exception],
) -> None:
    # Deliberate protocol doubles ONLY for failure controls, never acceptance.
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["failure-control"], returncode, stdout, "diagnostic")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(error):
        validate_glb("failure-control", tmp_path / "unused.glb")
