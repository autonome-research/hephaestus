# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Direct official CLI invocation for the HTTP GLB gate (no validation adapter)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REQUIRE_ENV = "HEPHAESTUS_REQUIRE_GLTF_VALIDATOR"
BINARY_ENV = "HEPHAESTUS_GLTF_VALIDATOR"
LOCK: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "docker/ci/gltf-validator.lock.json").read_text()
)


def validator_binary() -> str:
    required = os.environ.get(REQUIRE_ENV) == "1"
    configured = os.environ.get(BINARY_ENV)
    # Required CI uses ONLY the explicitly installed, integrity-locked binary.
    # A broken explicit path must never fall back to a different PATH tool.
    if required:
        assert configured, f"{REQUIRE_ENV}=1 requires an explicit {BINARY_ENV} path"
    binary = (
        shutil.which(configured)
        if configured
        else shutil.which("gltf_validator") or shutil.which("gltf-validator")
    )
    if binary is None:
        if required or configured:
            pytest.fail(f"Khronos validator missing: {BINARY_ENV}={configured!r}")
        pytest.skip("optional Khronos validator absent outside the required CI lane")
    assert binary is not None
    if required:
        assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == LOCK["binary_sha256"], (
            "Required Khronos executable SHA-256 mismatch"
        )
    # The official CLI has no --version. No arguments prints its banner and
    # exits 1 (upstream cmd_line.dart kErrorCode), NOT a successful validation.
    probe = subprocess.run([binary], capture_output=True, text=True, timeout=30, check=False)
    banner = f"glTF 2.0 Validator, version {LOCK['version']}\n"
    assert probe.returncode == 1 and (probe.stdout + probe.stderr).startswith(banner), (
        f"Khronos version/invocation failure ({probe.returncode}):\n{probe.stdout}{probe.stderr}"
    )
    return binary


def validate_glb(binary: str, path: Path) -> dict[str, Any]:
    # -o means JSON to STDOUT, not an output directory. Do not pass a config
    # that filters diagnostics, or accept missing/malformed reports as zero.
    completed = subprocess.run(
        [binary, "-r", "-o", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    diagnostic = (
        f"Khronos rejected {path.name} (exit {completed.returncode}):\n"
        f"{completed.stderr}\n{completed.stdout}"
    )
    assert completed.returncode == 0, diagnostic
    report: dict[str, Any] = json.loads(completed.stdout)
    assert report["validatorVersion"] == LOCK["version"], diagnostic
    assert type(report["issues"]["numErrors"]) is int, diagnostic
    assert report["issues"]["numErrors"] == 0, diagnostic
    print(
        f"Khronos {report['validatorVersion']}: {path.name}: "
        f"{json.dumps(report['issues'], sort_keys=True)}",
        flush=True,
    )
    return report
