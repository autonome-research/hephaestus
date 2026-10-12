# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Harness bookkeeping only; these tests are NOT live milestone evidence."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "scripts/macos_milestone_smoke.py"))
REQUIRED = MODULE["REQUIRED"]
Smoke = MODULE["Smoke"]
accepted = MODULE["accepted"]
report_path = MODULE["report_path"]


def test_acceptance_requires_every_named_check() -> None:
    checks = {name: {"status": "passed"} for name in REQUIRED}
    assert accepted(checks)
    for name in REQUIRED:
        for status in ("failed", "blocked", "unimplemented", "skipped", "pending"):
            altered = {**checks, name: {"status": status}}
            assert not accepted(altered), (name, status)
        assert not accepted({key: value for key, value in checks.items() if key != name})


def test_initial_report_never_claims_evidence(tmp_path: Path) -> None:
    Smoke(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())
    assert not report["accepted"]
    assert report["commands"] == []
    assert report["screenshots"] == []
    assert report["owned_containers"] == []
    assert report["checks"]["browser"]["status"] == "blocked"
    assert report["checks"]["containment"]["detail"] == "not run"


@pytest.mark.parametrize("failure", [RuntimeError("preflight failed"), KeyboardInterrupt()])
def test_failure_and_interrupt_write_report_and_cleanup(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    class RefusingSmoke(Smoke):
        def preflight(self) -> None:
            raise failure

    smoke = RefusingSmoke(tmp_path)
    assert smoke.run() == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["checks"]["preflight"]["status"] == "failed"
    assert report["checks"]["cleanup"]["status"] == "passed"
    assert report["checks"]["containment"]["status"] == "blocked"
    assert not report["accepted"]
    assert report["finished_at"] >= report["started_at"]


def test_cleanup_only_addresses_recorded_resources(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    class InventorySmoke(Smoke):
        def command(
            self,
            argv: tuple[str, ...],
            *,
            timeout: float = 30,
            require: bool = True,
        ) -> tuple[int, str]:
            del timeout, require
            calls.append(argv)
            return 0, "someone-elses-resource\n"

    smoke = InventorySmoke(tmp_path)
    smoke.docker = ("docker", "--host", "unix:///owned-endpoint")
    smoke.owned.append("owned-container")
    smoke.report["owned_image_tags"].append("owned:image")
    smoke.cleanup()
    assert calls == [
        (*smoke.docker, "rm", "--force", "owned-container"),
        (*smoke.docker, "ps", "-a", "--format", "{{.Names}}"),
        (*smoke.docker, "image", "rm", "owned:image"),
        (*smoke.docker, "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"),
    ]
    assert smoke.report["checks"]["cleanup"]["status"] == "passed"


def test_cleanup_inventory_failure_is_not_absence(tmp_path: Path) -> None:
    class BrokenDaemonSmoke(Smoke):
        def command(
            self,
            argv: tuple[str, ...],
            *,
            timeout: float = 30,
            require: bool = True,
        ) -> tuple[int, str]:
            del argv, timeout, require
            raise OSError("daemon unavailable")

    smoke = BrokenDaemonSmoke(tmp_path)
    smoke.owned.append("owned-container")
    smoke.cleanup()
    assert smoke.report["checks"]["cleanup"]["status"] == "failed"
    assert not smoke.report["accepted"]


def test_report_location_refuses_overwrite_and_outside_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside this checkout"):
        report_path(str(tmp_path))
    with pytest.raises(ValueError, match="must be new"):
        report_path(str(ROOT / "scripts"))
    with pytest.raises(ValueError, match="OCI mount"):
        report_path(str(ROOT / "dist" / "unsafe,name"))
