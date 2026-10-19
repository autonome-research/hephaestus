# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Renderer preparation refusal regressions; no Docker or native CAD required."""

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from hephaestus.core.executor.sandbox.oci import TransportResult, TransportTimeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
live = importlib.import_module("macos_renderer_check")
prepare = importlib.import_module("macos_prepare_renderer")


class Transport:
    def __init__(self, create):
        self.create = create

    def run(self, argv, **kwargs):
        if "create" in argv:
            if isinstance(self.create, Exception):
                raise self.create
            return TransportResult(0, self.create, b"")
        return TransportResult(0, b"", b"")


@pytest.mark.parametrize("create", [b"a" * 64 + b"\n", b"not-an-id\n", TransportTimeout()])
def test_preparation_absence_cannot_settle_unknown_create(tmp_path, create):
    smoke = live.RendererSmoke(tmp_path)
    smoke.docker = ("docker",)
    smoke.transport = Transport(create)
    name = "heph-macos-owned-synthetic"
    smoke.owned.append(name)
    if isinstance(create, bytes) and create == b"a" * 64 + b"\n":
        smoke.command(("docker", "create", "--name", name))
        pending = False
    else:
        with pytest.raises(live.StageFailure):
            smoke.command(("docker", "create", "--name", name))
        pending = True
    smoke.cleanup()  # independent synthetic empty inventory is NOT create settlement
    state = json.loads((tmp_path / "build-ownership.json").read_text())
    assert state[name]["pending"] is pending
    assert smoke.report["checks"]["cleanup"]["status"] == ("failed" if pending else "passed")
    assert smoke.report["accepted"] is False


@pytest.mark.parametrize("mutation", ["huge", "symlink", "hardlink", "digest", "valid"])
def test_cached_download_admission_precedes_write(tmp_path, mutation):
    cache, output = tmp_path / "cache", tmp_path / "output"
    cache.mkdir()
    payload = b"pinned-test-fixture"
    leaf = cache / "package.whl"
    leaf.write_bytes(payload)
    item = {
        "filename": leaf.name,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "url": "https://files.pythonhosted.org/package.whl",
    }
    if mutation == "huge":
        with leaf.open("wb") as stream:
            stream.truncate(256 * 1024**2)
    elif mutation in ("symlink", "hardlink"):
        target = cache / "target"
        leaf.rename(target)
        if mutation == "symlink":
            leaf.symlink_to(target)
        else:
            os.link(target, leaf)
    elif mutation == "digest":
        leaf.write_bytes(b"x" * len(payload))
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"packages": [item]}))
    if mutation == "valid":
        prepare.fetch_locked(lock, output, cache)
        assert (output / leaf.name).read_bytes() == payload
    else:
        with pytest.raises((OSError, ValueError)):
            prepare.fetch_locked(lock, output, cache)
        assert not list(output.iterdir())


@pytest.mark.parametrize(
    "missing",
    [
        "containment",
        "rgb",
        "selection_masks",
        "kernel_section",
        "linked_glb",
        "cleanup",
        "renderer_worker_passed",
        "renderer_cleanup_passed",
        "executor_stage_passed",
    ],
)
def test_renderer_gate_requires_each_fresh_collector_stage(missing):
    # Synthetic gate structure only, never live evidence or a report importer.
    report = {
        "accepted": False,
        "renderer_worker_passed": True,
        "renderer_cleanup_passed": True,
        "executor_stage_passed": True,
        "checks": {
            k: {"status": "passed"}
            for k in (
                "containment",
                "rgb",
                "selection_masks",
                "kernel_section",
                "linked_glb",
                "cleanup",
            )
        },
    }
    assert live.renderer_passed(report)
    if missing in report:
        del report[missing]
    else:
        del report["checks"][missing]
    assert not live.renderer_passed(report)
    assert report["accepted"] is False
