# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Installer argv and real subprocess confinement controls, not CAD acceptance."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import macos_workspace_check as browser  # noqa: E402
import macos_workspace_dependencies as dependencies  # noqa: E402
from hephaestus.core.deadline import Deadline  # noqa: E402
from hephaestus.core.executor.sandbox.oci import RUNTIME_ENV, TransportResult  # noqa: E402
from macos_milestone_smoke import Smoke  # noqa: E402
from macos_owned_paths import private_directory  # noqa: E402


@pytest.mark.parametrize("cache", ["default", "--no-cache", "--cache-dir"])
@pytest.mark.parametrize("report_leaf", ["dist/report", "report"])
def test_installer_effective_argv_and_sanitized_environment(
    tmp_path, monkeypatch, cache, report_leaf
):
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").touch()
    (tmp_path / "dist").mkdir()
    calls = []

    class Transport:
        def run(self, argv, **kwargs):
            calls.append((argv, kwargs))
            return TransportResult(0, b"", b"")

    def smoke(path):
        result = Smoke(path)
        result.transport = Transport()
        return result

    monkeypatch.setenv("UV_CACHE_DIR", "/unowned-cache")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-forward")
    monkeypatch.setattr(dependencies, "ROOT", tmp_path)
    monkeypatch.setattr(dependencies, "Smoke", smoke)
    monkeypatch.setattr(dependencies, "report_path", lambda value: Path(value))
    monkeypatch.setattr(dependencies.shutil, "which", lambda name: "/reviewed/uv")
    monkeypatch.setattr(dependencies, "host_lock", lambda: ("locked-hash-lines", {"test": "1"}))
    report = tmp_path / report_leaf
    args = ["installer", "--report-dir", str(report)]
    if cache != "default":
        args.append(cache)
    if cache == "--cache-dir":
        args.append(str(tmp_path / "dist/cache"))
    monkeypatch.setattr(sys, "argv", args)
    assert dependencies.main() == 0
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert kwargs["env"] == RUNTIME_ENV
    assert argv[:5] == (
        "/usr/bin/env",
        "HOME=" + str(report / "installer/home"),
        "TMPDIR=" + str(report / "installer/tmp"),
        "UV_HTTP_TIMEOUT=30",
        "UV_HTTP_RETRIES=0",
    )
    assert argv[5:8] == ("/reviewed/uv", "--no-config", "--no-python-downloads")
    assert ("--no-cache" in argv) is (cache != "--cache-dir")
    if cache == "--cache-dir":
        assert argv[argv.index("--cache-dir") + 1] == str(tmp_path / "dist/cache")
    assert "--require-hashes" in argv and "--only-binary=:all:" in argv
    assert argv[argv.index("--index-url") + 1] == "https://pypi.org/simple"
    assert argv[argv.index("--keyring-provider") + 1] == "disabled"
    assert kwargs["timeout"] <= 180


@pytest.mark.parametrize("flag", ["--cache-dir", "--temp-dir"])
@pytest.mark.parametrize("fault", ["existing", "escape", "symlink"])
def test_installer_invalid_path_never_launches(tmp_path, monkeypatch, flag, fault):
    root = tmp_path / "fixture"
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").touch()
    (root / "dist").mkdir()
    target = root / "dist/target"
    if fault == "existing":
        target.mkdir()
    elif fault == "escape":
        target = tmp_path / "outside"
    else:
        target.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(dependencies, "ROOT", root)
    monkeypatch.setattr(dependencies, "report_path", lambda value: Path(value))
    monkeypatch.setattr(dependencies.shutil, "which", lambda name: "/reviewed/uv")
    monkeypatch.setattr(dependencies, "host_lock", lambda: ("locked", {}))
    monkeypatch.setattr(Smoke, "command", lambda *a, **kw: pytest.fail("installer launched"))
    monkeypatch.setattr(
        sys, "argv", ["installer", "--report-dir", str(root / "dist/report"), flag, str(target)]
    )
    with pytest.raises(ValueError):
        dependencies.main()


def test_cache_flags_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["installer", "--report-dir", "unused", "--no-cache", "--cache-dir", "unused"]
    )
    with pytest.raises(SystemExit) as exc:
        dependencies.main()
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "fault", ["escape", "parent", "existing", "symlink", "ancestor", "file", "control"]
)
def test_owned_paths_refuse_without_adoption(tmp_path, fault):
    root = tmp_path / "fixture"
    root.mkdir()
    path = root / "owned"
    if fault == "escape":
        path = tmp_path / "outside"
    elif fault == "parent":
        path = root / "sub/../owned"
    elif fault == "existing":
        path.mkdir()
    elif fault in {"symlink", "ancestor"}:
        path.symlink_to(tmp_path, target_is_directory=True)
        if fault == "ancestor":
            path /= "child"
    elif fault == "file":
        path.touch()
    elif fault == "control":
        path = root / "bad\nname"
    with pytest.raises(ValueError):
        private_directory(path, root)
    assert not (tmp_path / "child").exists()


def test_browser_real_child_receives_only_owned_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER_SECRET", "never-forward")
    code = (
        "import json,os,pathlib,sys,tempfile; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps("
        "{'launch_pending':False,'closed':True,'pid':None})); "
        "print(json.dumps({'env':dict(os.environ),'tmp':tempfile.gettempdir()}))"
    )
    smoke = SimpleNamespace(report={}, save=lambda: None, deadline=Deadline.after(20))
    browser.run_browser_client(
        smoke, [sys.executable, "-c", code, str(tmp_path / "browser-owner.json")], tmp_path
    )
    result = json.loads((tmp_path / "client.log").read_text())
    # macOS CoreFoundation adds this at Python startup; it is not inherited
    # from the collector or a provider. Every other child key remains closed.
    if sys.platform == "darwin":
        result["env"].pop("__CF_USER_TEXT_ENCODING", None)
    assert result["env"] == {
        **RUNTIME_ENV,
        "HOME": str(tmp_path / "runtime/home"),
        "TMPDIR": str(tmp_path / "runtime/tmp"),
    }
    assert result["tmp"] == str(tmp_path / "runtime/tmp")
    owner = json.loads((tmp_path / "client-owner.json").read_text())
    assert owner["reaped"] and not owner["launch_pending"]
    assert owner["paths"] == smoke.report["browser_command"]["paths"]
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("fault", ["spawn", "home", "ownership"])
def test_browser_pre_spawn_failure_cleans_owned_scratch(tmp_path, monkeypatch, fault):
    real_private = browser.private_directory
    calls = []

    def private(path, root):
        if fault == "home" and path.name == "home":
            raise OSError("initialization failure")
        return real_private(path, root)

    def spawn(*args, **kwargs):
        calls.append(args)
        raise OSError("spawn failure")

    def document(*args):
        raise OSError("ownership failure")

    monkeypatch.setattr(browser, "private_directory", private)
    monkeypatch.setattr(browser.subprocess, "Popen", spawn)
    if fault == "ownership":
        monkeypatch.setattr(browser, "document", document)
    with pytest.raises(OSError):
        browser.run_browser_client(
            SimpleNamespace(deadline=Deadline.after(20)), ["unused"], tmp_path
        )
    assert len(calls) == (1 if fault == "spawn" else 0)
    assert not (tmp_path / "runtime").exists()


def test_image_preparation_without_old_wheelhouse(tmp_path, monkeypatch):
    import macos_prepare_executor
    import macos_prepare_renderer
    import macos_prepare_workspace as workspace
    import macos_probe_executor

    instances, downloads = [], []

    class Preparation:
        def __init__(self, directory, wheelhouse, **kwargs):
            self.directory, self.wheelhouse = directory, wheelhouse
            self.deadline = Deadline.after(20)
            self.docker = ("synthetic-not-launched",)
            self.report = {"checks": {"cleanup": {"status": "passed"}}}
            instances.append(self)

        def preflight(self):
            pass

        def native_dependencies(self):
            downloads.append(self.wheelhouse)

        def cleanup(self, *, retain_images):
            assert retain_images is True

    report = tmp_path / "report"
    report.mkdir()
    monkeypatch.setattr(sys, "argv", ["prepare", "--report-dir", str(report)])
    monkeypatch.setattr(workspace, "report_path", lambda value: Path(value))
    monkeypatch.setattr(workspace, "RendererSmoke", Preparation)
    monkeypatch.setattr(workspace, "preflight", lambda smoke: None)
    monkeypatch.setattr(workspace.signal, "signal", lambda *args: None)
    monkeypatch.setattr(macos_prepare_executor, "prepare", lambda smoke: "executor")
    monkeypatch.setattr(macos_prepare_renderer, "prepare", lambda smoke: "renderer")
    monkeypatch.setattr(macos_probe_executor, "resolve_image", lambda smoke, image, **kw: image)
    assert workspace.main() == 0
    assert len(instances) == 2
    assert downloads == [None, report / "download/wheels"]
    assert json.loads((report / "images.json").read_text()) == {
        "executor": "executor",
        "renderer": "renderer",
    }


@pytest.mark.parametrize(
    "state", [None, {"launch_pending": True, "closed": False}, {"closed": True}]
)
def test_unsettled_browser_profile_is_retained(tmp_path, state):
    # A dead Node is not evidence that a detached Chrome never launched.
    code = (
        "pass"
        if state is None
        else (
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("
            + repr(json.dumps(state))
            + ")"
        )
    )
    smoke = SimpleNamespace(report={}, save=lambda: None, deadline=Deadline.after(20))
    browser.run_browser_client(
        smoke, [sys.executable, "-c", code, str(tmp_path / "browser-owner.json")], tmp_path
    )
    assert (tmp_path / "runtime").is_dir()
    if state is None:
        assert not (tmp_path / "browser-owner.json").exists()
    else:
        assert json.loads((tmp_path / "browser-owner.json").read_text()) == state


def test_browser_rejects_symlink_before_spawn(tmp_path, monkeypatch):
    (tmp_path / "runtime").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="symlink"):
        browser.run_browser_client(
            SimpleNamespace(deadline=Deadline.after(20)), ["unused"], tmp_path
        )
    assert (tmp_path / "runtime").is_symlink()
