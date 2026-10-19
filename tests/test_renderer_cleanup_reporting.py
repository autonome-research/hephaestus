# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Failure injection only: real collector/report and preparation cleanup, no Docker/CAD."""

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
workspace = importlib.import_module("macos_workspace_check")
renderer = importlib.import_module("macos_renderer_check")
preparation = importlib.import_module("macos_prepare_renderer")
probe = importlib.import_module("macos_probe_executor")
smoke_module = importlib.import_module("macos_milestone_smoke")


class InventoryTransport:
    """Synthetic successful removals/inventory, not evidence of actual cleanup."""

    def run(self, argv, **kwargs):
        from hephaestus.core.executor.sandbox.oci import TransportResult

        return TransportResult(0, b"", b"")


@pytest.fixture
def collector(tmp_path, monkeypatch):
    smoke = smoke_module.Smoke(tmp_path / "milestone")
    smoke.docker = ("synthetic-docker",)
    smoke.transport = InventoryTransport()
    created = []
    real_renderer = renderer.RendererSmoke

    def make_renderer(*args, **kwargs):
        child = real_renderer(*args, **kwargs)
        child.transport = InventoryTransport()
        created.append(child)
        return child

    monkeypatch.setattr(renderer, "RendererSmoke", make_renderer)
    monkeypatch.setattr(real_renderer, "native_dependencies", lambda self: None)
    monkeypatch.setattr(probe, "resolve_image", lambda *a, **kw: "synthetic@sha256:" + "a" * 64)
    monkeypatch.setattr(workspace, "browser", lambda *a: None)
    return smoke, created


@pytest.mark.parametrize(
    "failure",
    ["preparation", "preparation_cleanup", "pending_create", "cleanup_raises", "missing_cleanup"],
)
def test_preparation_failure_preserved_with_independent_cleanup(collector, monkeypatch, failure):
    smoke, children = collector
    original = ValueError("original preparation failure")
    cleanup_calls = []

    def prepare(child):
        # Explicit ownership, including an ambiguous create despite empty inventory.
        child.owned.append("heph-macos-synthetic")
        child.report["build_ownership"] = {
            child.owned[0]: {
                "id": None if failure == "pending_create" else "a" * 64,
                "pending": failure == "pending_create",
            }
        }
        real_cleanup = child.cleanup

        def cleanup():
            cleanup_calls.append(True)
            if failure == "cleanup_raises":
                raise OSError("independent cleanup exception")
            real_cleanup()
            if failure == "preparation_cleanup":
                child.check("cleanup", "failed", "injected unsettled preparation owner")
            elif failure == "missing_cleanup":
                del child.report["checks"]["cleanup"]

        child.cleanup = cleanup
        raise original

    monkeypatch.setattr(preparation, "prepare", prepare)
    monkeypatch.setattr(renderer, "live", lambda *a: pytest.fail("live must not start"))
    with pytest.raises(ValueError) as caught:
        workspace.later_stages(smoke)
    assert caught.value is original and cleanup_calls == [True]
    assert len(children) == 1
    report = json.loads((smoke.directory / "report.json").read_text())
    assert report["renderer_stage_error"] == "ValueError: original preparation failure"
    assert report["renderer_live_phase"] == "not_started"
    assert report["renderer_cleanup"]["live_phase"] == "not_started"
    assert report["renderer_cleanup"]["live_acknowledged"] is False
    assert report["renderer_cleanup_passed"] is False  # No fabricated live ACK / waiver.
    assert report["accepted"] is False
    errors = report["renderer_cleanup"]["errors"]
    assert any("ACK missing" in e for e in errors)
    if failure == "preparation":
        assert report["renderer_cleanup"]["preparation"]["status"] == "passed"
        assert len(errors) == 1
    else:
        assert any("preparation cleanup" in e for e in errors)
    if failure == "pending_create":
        assert "unsettled preparation create" in str(errors)
    if failure == "cleanup_raises":
        assert "independent cleanup exception" in str(errors)


@pytest.mark.parametrize("ack", [None, False, True, 1, "true", "unknown"])
@pytest.mark.parametrize("fails", [False, True])
def test_attempted_live_always_requires_real_ack_and_preserves_primary(
    collector, monkeypatch, ack, fails
):
    smoke, children = collector
    original = RuntimeError("original live launch failure")
    monkeypatch.setattr(preparation, "prepare", lambda child: "tag")

    def live(child, image, executor):
        # Persisted BEFORE any possible live acquisition, including partial launch.
        persisted = json.loads((executor.directory / "report.json").read_text())
        assert persisted["renderer_live_phase"] == "attempted"
        if ack is not None:
            child.report["renderer_cleanup_passed"] = ack
        if fails:
            raise original
        for name in ("rgb", "selection_masks", "kernel_section", "linked_glb"):
            child.check(name, "passed", "synthetic result")
        child.report["render_integration"] = {"synthetic": True}

    monkeypatch.setattr(renderer, "live", live)
    if fails:
        with pytest.raises(RuntimeError) as caught:
            workspace.later_stages(smoke)
        assert caught.value is original
        assert smoke.report["renderer_stage_error"] == "RuntimeError: original live launch failure"
    elif ack is not True:
        with pytest.raises(smoke_module.StageFailure, match="cleanup incomplete"):
            workspace.later_stages(smoke)
    else:
        workspace.later_stages(smoke)
    assert children[0].report["checks"]["cleanup"]["status"] == "passed"
    assert smoke.report["renderer_live_phase"] == ("attempted" if fails else "returned")
    assert smoke.report["renderer_cleanup_passed"] is (ack is True)
    assert smoke.report["accepted"] is False  # Neither synthetic stages nor cleanup suffice.
    assert bool(smoke.report["renderer_cleanup"]["errors"]) is (ack is not True)


@pytest.mark.parametrize("cleanup_fault", ["close", "verify", "save", None])
def test_real_live_collector_retains_probe_error_and_independent_cleanup(
    collector, monkeypatch, cleanup_fault
):
    smoke, children = collector
    (smoke.directory / "build").mkdir()
    (smoke.directory / "build/final.brep").write_bytes(b"synthetic-not-CAD")
    smoke.docker = ("/synthetic/docker", "--context", "desktop-linux")
    monkeypatch.setattr(preparation, "prepare", lambda child: "tag")
    original = RuntimeError("original live probe failure")
    calls = []

    class Renderer:
        def __init__(self, config):
            assert smoke.report["renderer_live_phase"] == "attempted"
            if cleanup_fault == "save":
                child = children[0]
                real_save = child.save

                def save():
                    child.save = real_save
                    raise OSError("live cleanup report unavailable")

                child.save = save

        def probe(self):
            raise original

        def close(self):
            calls.append("close")
            if cleanup_fault == "close":
                raise OSError("live close failure")

    def verify(child, config):
        calls.append("verify")
        if cleanup_fault == "verify":
            raise ValueError("missing live completion/reap ACK")

    monkeypatch.setattr(renderer, "OciRenderer", Renderer)
    monkeypatch.setattr(renderer, "verify_cleanup", verify)
    with pytest.raises(RuntimeError) as caught:
        workspace.later_stages(smoke)
    assert caught.value is original
    assert calls == (["close"] if cleanup_fault == "close" else ["close", "verify"])
    assert children[0].report["renderer_live_error"] == "RuntimeError: original live probe failure"
    assert smoke.report["renderer_stage_error"] == "RuntimeError: original live probe failure"
    assert smoke.report["renderer_cleanup_passed"] is (cleanup_fault is None)
    if cleanup_fault is not None:
        assert children[0].report["renderer_live_cleanup_errors"]
        assert len(smoke.report["renderer_cleanup"]["errors"]) == 2
    assert smoke.report["accepted"] is False


def test_nested_preparation_diagnostics_reach_top_level(collector, monkeypatch):
    smoke, _ = collector
    original = ValueError("original preparation attach failure")

    def prepare(child):
        child.report["preparation_cleanup_errors"] = ["independent removal uncertainty"]
        raise original

    monkeypatch.setattr(preparation, "prepare", prepare)
    with pytest.raises(ValueError) as caught:
        workspace.later_stages(smoke)
    assert caught.value is original
    report = json.loads((smoke.directory / "report.json").read_text())
    assert report["renderer_stage_error"] == "ValueError: original preparation attach failure"
    assert "independent removal uncertainty" in report["renderer_cleanup"]["errors"]
    assert report["renderer_cleanup_passed"] is False
    assert report["accepted"] is False


def test_constructor_failure_is_attempted_not_absence(collector, monkeypatch):
    smoke, _ = collector
    (smoke.directory / "build").mkdir()
    (smoke.directory / "build/final.brep").write_bytes(b"synthetic-not-CAD")
    smoke.docker = ("/synthetic/docker", "--context", "desktop-linux")
    monkeypatch.setattr(preparation, "prepare", lambda child: "tag")

    def constructor(config):
        assert smoke.report["renderer_live_phase"] == "attempted"
        raise RuntimeError("partial live construction")

    monkeypatch.setattr(renderer, "OciRenderer", constructor)
    with pytest.raises(RuntimeError, match="partial live construction"):
        workspace.later_stages(smoke)
    assert smoke.report["renderer_cleanup"]["live_phase"] == "attempted"
    assert smoke.report["renderer_cleanup_passed"] is False


@pytest.mark.parametrize("persistence_failure", [False, True])
def test_top_level_reports_original_error_without_promoting_failed_acceptance(
    collector, monkeypatch, persistence_failure
):
    smoke, _ = collector
    real_save = smoke.save
    failed_saves = []

    def save():
        if persistence_failure and "renderer_cleanup" in smoke.report and not failed_saves:
            failed_saves.append(True)
            raise OSError("cleanup report temporarily unavailable")
        real_save()

    monkeypatch.setattr(smoke, "save", save)
    executor = importlib.import_module("macos_executor_check")
    dependencies = importlib.import_module("macos_workspace_dependencies")
    monkeypatch.setattr(smoke, "preflight", lambda: None)
    monkeypatch.setattr(dependencies, "preflight", lambda s: None)
    monkeypatch.setattr(executor, "run_executor_stages", lambda s: None)
    monkeypatch.setattr(executor, "finish_executor", lambda s: None)

    def fail(child):
        raise ValueError("original archive refusal")

    monkeypatch.setattr(preparation, "prepare", fail)
    assert smoke.run() == 1
    report = json.loads((smoke.directory / "report.json").read_text())
    assert report["milestone_error"] == "ValueError: original archive refusal"
    assert report["checks"]["workspace"]["detail"] == report["milestone_error"]
    assert report["checks"]["cleanup"]["status"] == "failed"
    assert report["renderer_cleanup"]["preparation"]["status"] == "passed"
    assert report["accepted"] is False
    assert len(failed_saves) == int(persistence_failure)
    if persistence_failure:
        assert "cleanup report persistence" in str(report["renderer_cleanup"]["errors"])
    # Even hypothetical later filled stage flags cannot erase a primary failure.
    for record in smoke.report["checks"].values():
        record["status"] = "passed"
    smoke.report.update(
        executor_stage_passed=True,
        renderer_cleanup_passed=True,
        workspace_cleanup_passed=True,
        browser_evidence={"passed": True},
    )
    smoke.save()
    assert smoke.report["accepted"] is False


@pytest.mark.parametrize(
    "record", [None, {}, {"pending": False, "id": None}, {"pending": 0, "id": "a" * 64}]
)
def test_preparation_missing_settlement_is_not_empty_inventory(collector, record):
    smoke, _ = collector
    smoke.owned.append("heph-macos-unknown")
    if record is not None:
        smoke.report["build_ownership"] = {smoke.owned[0]: record}
    smoke.cleanup()
    assert smoke.report["checks"]["cleanup"]["status"] == "failed"
    assert smoke.report["accepted"] is False


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "state",
        "binding",
        "launch",
        "reap",
        "final",
        "final-pid",
        "final-bool",
        "observer",
        "nested-journal",
    ],
)
def test_real_live_cleanup_requires_durable_provenance_not_process_absence(collector, fault):
    from types import SimpleNamespace

    smoke, _ = collector
    directory = smoke.directory / "supervisor"
    directory.mkdir(mode=0o700)
    config = SimpleNamespace(directory=directory, binding=lambda: {"synthetic": True})
    journal_path = directory / "ownership"
    with renderer.OwnershipJournal(journal_path, config.binding()):
        pass
    operation = directory / "operation-00"
    operation.mkdir()
    for name, record in {
        "owner": {"pid": 12345},
        "owner-final": {"pid": 12345, "commands_finished": True},
        "reaped": {"pid": 12345, "exitcode": 0},
    }.items():
        (operation / (name + ".json")).write_text(json.dumps(record))
    state_path = journal_path / "state.json"
    state = json.loads(state_path.read_text())
    if fault == "state":
        state_path.unlink()
    elif fault in {"binding", "launch", "reap"}:
        if fault == "binding":
            state["binding"] = {"other": True}
        elif fault == "launch":
            state["launch_pending"] = True
        else:
            state["clients"] = {"12345": {"reaped": False}}
        state_path.write_text(json.dumps(state))
    elif fault == "final":
        (operation / "owner-final.json").unlink()
    elif fault in {"final-pid", "final-bool"}:
        (operation / "owner-final.json").write_text(
            json.dumps(
                {
                    "pid": 999 if fault == "final-pid" else 12345,
                    "commands_finished": 1 if fault == "final-bool" else True,
                }
            )
        )
    elif fault == "observer":
        with renderer.OwnershipJournal(operation / "observer-ownership", config.binding()) as j:
            j.launching_client()
    elif fault == "nested-journal":
        nested = directory / "render-01"
        nested.mkdir()
        operation.rename(nested / operation.name)
    if fault is None:
        renderer.verify_cleanup(smoke, config)
        assert (smoke.directory / "renderer-final-inventory.json").is_file()
    else:
        with pytest.raises((smoke_module.StageFailure, renderer.SandboxDeniedError, OSError)):
            renderer.verify_cleanup(smoke, config)
        assert not (smoke.directory / "renderer-final-inventory.json").exists()
        if fault == "state":
            assert not state_path.exists()  # verification must not create replacement evidence
