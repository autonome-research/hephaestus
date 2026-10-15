# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Provisioning failure controls and CI wiring, not substitutes for real GLB validation."""

from __future__ import annotations

import hashlib
import io
import json
import runpy
import sys
import tarfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
INSTALLER = SimpleNamespace(**runpy.run_path(str(REPO / "scripts/install_gltf_validator.py")))


def _archive() -> tuple[bytes, dict[str, str]]:
    """Explicit synthetic archive for extraction tests; never executed as a validator."""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:xz") as bundle:
        for name in ("gltf_validator", "LICENSE", "NOTICES"):
            entry = tarfile.TarInfo(name)
            entry.size = len(name)
            bundle.addfile(entry, io.BytesIO(name.encode()))
    archive = stream.getvalue()
    return archive, {
        "version": "test-only",
        "sha256": hashlib.sha256(archive).hexdigest(),
        "binary_sha256": hashlib.sha256(b"gltf_validator").hexdigest(),
    }


def test_installer_checks_archive_before_writing(tmp_path: Path) -> None:
    archive, lock = _archive()
    with pytest.raises(ValueError, match="archive SHA-256 mismatch"):
        INSTALLER.install(archive + b"tampered", tmp_path / "tool", lock)
    assert not (tmp_path / "tool").exists()


def test_installer_checks_binary_before_writing(tmp_path: Path) -> None:
    archive, lock = _archive()
    lock["binary_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="executable SHA-256 mismatch"):
        INSTALLER.install(archive, tmp_path / "tool", lock)
    assert not (tmp_path / "tool").exists()


def test_installer_keeps_licenses_and_refuses_replacement(tmp_path: Path) -> None:
    archive, lock = _archive()
    destination = tmp_path / "tool"
    binary = INSTALLER.install(archive, destination, lock)
    assert binary.read_bytes() == b"gltf_validator"
    assert binary.stat().st_mode & 0o777 == 0o755
    assert (destination / "LICENSE").read_bytes() == b"LICENSE"
    assert (destination / "NOTICES").read_bytes() == b"NOTICES"
    with pytest.raises(FileExistsError):
        INSTALLER.install(archive, destination, lock)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("download failed"),
        urllib.error.HTTPError("url", 404, "absent", {}, None),
    ],
)
def test_download_failure_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    monkeypatch.setattr(INSTALLER.platform, "system", lambda: "Linux")
    monkeypatch.setattr(INSTALLER.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(sys, "argv", ["install_gltf_validator.py", str(tmp_path / "tool")])

    def download(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(INSTALLER.urllib.request, "urlopen", download)
    with pytest.raises(type(error)):
        INSTALLER.main()
    assert not (tmp_path / "tool").exists()


def test_ci_requires_the_locked_tool_and_both_actual_http_tests() -> None:
    ci = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["render-goldens"]
    assert job["env"]["HEPHAESTUS_REQUIRE_GLTF_VALIDATOR"] == "1"
    assert job["env"]["HEPHAESTUS_GLTF_VALIDATOR"] == (
        "${{ runner.temp }}/gltf-validator/gltf_validator"
    )
    runs = [step["run"] for step in job["steps"] if "run" in step]
    install = 'uv run python scripts/install_gltf_validator.py "$RUNNER_TEMP/gltf-validator"'
    controls = "uv run pytest server/tests/test_khronos_validator.py -vv -s"
    validate = next(run for run in runs if "::test_the_khronos_validator_accepts_the_glb" in run)
    assert "::test_the_khronos_validator_binary_is_present_when_required" in validate
    assert "-vv -s" in validate
    assert runs.index(install) < runs.index(controls) < runs.index(validate)
    lock = json.loads((REPO / "docker/ci/gltf-validator.lock.json").read_text())
    assert lock["url"] == (
        f"{lock['repository']}/releases/download/{lock['version']}/"
        f"gltf_validator-{lock['version']}-linux64.tar.xz"
    )
    assert len(lock["sha256"]) == len(lock["binary_sha256"]) == 64
