# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Offline policy coverage, NOT verification of real pinned download bytes."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docker/executor"))
renderer = importlib.import_module("macos_prepare_renderer")
native = importlib.import_module("fetch_native_runtime")
LOCKS = sorted((ROOT / "docker/executor").glob("native-*.lock.json")) + sorted(
    (ROOT / "docker/renderer").glob("*-arm64.lock.json")
)
ITEMS = [
    pytest.param(path, item, id=f"{path.parent.name}/{path.name}/{item['filename']}")
    for path in LOCKS
    for item in json.loads(path.read_text())["packages"]
]
ARCHIVE = next(
    item
    for item in json.loads((ROOT / "docker/renderer/python-arm64.lock.json").read_text())[
        "packages"
    ]
    if item["filename"] == "PyOpenGL-3.1.0.tar.gz"
)


def lock_file(tmp_path, item, architecture="arm64"):
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"architecture": architecture, "packages": [item]}))
    return lock


class FetchReached(Exception):
    """Stop at the real fetch boundary; never substitute fake expected hashes."""


def check_curl(argv, kwargs, item):
    assert argv[:2] == ("/usr/bin/curl", "--disable")
    assert "--insecure" not in argv and "-k" not in argv
    for flag, value in (
        ("--max-redirs", "0"),
        ("--proto", "=https"),
        ("--proto-redir", "=https"),
        ("--connect-timeout", "15"),
        ("--max-time", "300"),
        ("--max-filesize", str(item["size"])),
    ):
        assert argv[argv.index(flag) + 1] == value
    assert argv[-3] == item["url"]
    assert Path(argv[-1]).name == item["filename"]
    assert kwargs == {"check": True, "timeout": 310}


@pytest.mark.parametrize("source,item", ITEMS)
def test_every_committed_json_item_reaches_actual_fetch_policy(tmp_path, monkeypatch, source, item):
    """Admission only: original hashes stay intact and no fake body is accepted."""
    lock = lock_file(tmp_path, item)
    calls = []

    def run(argv, **kwargs):
        check_curl(argv, kwargs, item)
        calls.append(argv)
        raise FetchReached

    monkeypatch.setattr(renderer.subprocess, "run", run)
    with pytest.raises(FetchReached):
        renderer.fetch_locked(lock, tmp_path / "renderer")
    assert len(calls) == 1
    assert not list((tmp_path / "renderer").iterdir())

    if source.name.startswith("native-"):
        architecture = source.name.split("-")[1].split(".")[0]
        policy_fields = {key: item[key] for key in ("filename", "url", "size", "sha256")}
        assert policy_fields in native._load_lock(source, architecture)["packages"]
        lock = lock_file(tmp_path, item, architecture)
        urls = []

        class Opener:
            def open(self, url, timeout):
                assert timeout == 60
                urls.append(url)
                raise FetchReached

        def opener(handler):
            assert isinstance(handler, native.NoRedirect)
            return Opener()

        monkeypatch.setattr(native.urllib.request, "build_opener", opener)
        with pytest.raises(FetchReached):
            native.fetch(lock, tmp_path / "native", architecture)
        assert urls == [item["url"]]
        assert not list((tmp_path / "native").iterdir())


@pytest.mark.parametrize(
    "mutation",
    [
        {"url": ARCHIVE["url"].replace("https:", "http:")},
        {"url": ARCHIVE["url"].replace(".org/", ".org.evil.test/")},
        {"url": ARCHIVE["url"].replace(".org/", ".org:443/")},
        {"url": ARCHIVE["url"].replace("https://", "https://user:secret@")},
        {"url": ARCHIVE["url"] + "?download=1"},
        {"url": ARCHIVE["url"] + "?"},
        {"url": ARCHIVE["url"] + "#fragment"},
        {"url": ARCHIVE["url"] + "#"},
        {"url": ARCHIVE["url"].replace("/9c/", "/9d/")},
        {"url": ARCHIVE["url"].replace("PyOpenGL", "Other")},
        {"filename": "Other.tar.gz"},
        {"filename": "../PyOpenGL-3.1.0.tar.gz"},
        {"filename": "PyOpenGL-3.1.0.whl"},
        {"filename": "PyOpenGL-3.1.0.zip"},
        {"sha256": "0" * 64},
        {"size": ARCHIVE["size"] + 1},
        {"name": "other"},
        {"version": "3.1.1"},
        {"url": "https://files.pythonhosted.org/Other.tar.gz", "filename": "Other.tar.gz"},
        {"url": "https://deb.debian.org/debian/pool/Other.tar.gz", "filename": "Other.tar.gz"},
        {"url": "https://files.pythonhosted.org/Other.zip", "filename": "Other.zip"},
    ],
)
def test_only_reviewed_archive_tuple_admitted_before_cache_or_fetch(
    tmp_path, monkeypatch, mutation
):
    item = {**ARCHIVE, **mutation}
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / ARCHIVE["filename"]).write_bytes(b"untrusted cache")
    monkeypatch.setattr(renderer.subprocess, "run", lambda *a, **k: pytest.fail("network reached"))
    monkeypatch.setattr(
        renderer, "_locked_bytes", lambda *a: pytest.fail("cache admission reached")
    )
    with pytest.raises(ValueError):
        renderer.fetch_locked(lock_file(tmp_path, item), tmp_path / "out", cache)
    assert not list((tmp_path / "out").iterdir())


@pytest.mark.parametrize(
    "mutation",
    [
        {"url": None},
        {"url": 12},
        {"url": "https://[invalid"},
        {"url": "\n" + ARCHIVE["url"]},
        {"url": ARCHIVE["url"] + "\t"},
        {"filename": None},
        {"sha256": None},
        {"sha256": "g" * 64},
        {"sha256": "a" * 63},
        {"size": True},
        {"size": float(ARCHIVE["size"])},
        {"size": "1172688"},
        {"size": 0},
        {"size": -1},
        {"size": 64 * 1024**2 + 1},
    ],
)
def test_malformed_archive_refused_without_fetch(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(renderer.subprocess, "run", lambda *a, **k: pytest.fail("network reached"))
    with pytest.raises(ValueError):
        renderer.fetch_locked(lock_file(tmp_path, {**ARCHIVE, **mutation}), tmp_path / "out")
    assert not list((tmp_path / "out").iterdir())


@pytest.mark.parametrize(
    "fault", ["digest", "short", "oversize", "symlink", "dangling", "hardlink"]
)
def test_archive_cache_integrity_before_staging(tmp_path, monkeypatch, fault):
    cache = tmp_path / "cache"
    cache.mkdir()
    leaf = cache / ARCHIVE["filename"]
    size = ARCHIVE["size"] + {"short": -1, "oversize": 1}.get(fault, 0)
    leaf.write_bytes(b"x" * size)  # Never pretend these are the real pinned bytes.
    if fault in ("symlink", "dangling", "hardlink"):
        target = cache / "target"
        leaf.rename(target)
        if fault == "hardlink":
            os.link(target, leaf)
        else:
            leaf.symlink_to(target if fault == "symlink" else cache / "absent")
    monkeypatch.setattr(renderer.subprocess, "run", lambda *a, **k: pytest.fail("network reached"))
    with pytest.raises((ValueError, OSError)):
        renderer.fetch_locked(lock_file(tmp_path, ARCHIVE), tmp_path / "out", cache)
    assert not list((tmp_path / "out").iterdir())


@pytest.mark.parametrize("dangling", [False, True])
def test_archive_target_symlink_never_reaches_curl(tmp_path, monkeypatch, dangling):
    output = tmp_path / "out"
    output.mkdir()
    target = tmp_path / "target"
    if not dangling:
        target.write_bytes(b"preserve")
    (output / ARCHIVE["filename"]).symlink_to(target)
    monkeypatch.setattr(renderer.subprocess, "run", lambda *a, **k: pytest.fail("network reached"))
    with pytest.raises(ValueError, match="symlink"):
        renderer.fetch_locked(lock_file(tmp_path, ARCHIVE), output)
    assert not target.exists() if dangling else target.read_bytes() == b"preserve"


def test_archive_redirect_failure_is_not_retried_or_admitted(tmp_path, monkeypatch):
    calls = []

    def redirect(argv, **kwargs):
        check_curl(argv, kwargs, ARCHIVE)
        calls.append(argv)
        raise subprocess.CalledProcessError(47, argv)  # curl's redirect-limit refusal

    monkeypatch.setattr(renderer.subprocess, "run", redirect)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        renderer.fetch_locked(lock_file(tmp_path, ARCHIVE), tmp_path / "out")
    assert caught.value.returncode == 47 and len(calls) == 1
    assert not list((tmp_path / "out").iterdir())


@pytest.mark.parametrize("fault", ["digest", "short", "oversize"])
def test_archive_downloaded_bytes_checked_against_unchanged_pin(tmp_path, monkeypatch, fault):
    def download(argv, **kwargs):
        check_curl(argv, kwargs, ARCHIVE)
        size = ARCHIVE["size"] + {"short": -1, "oversize": 1}.get(fault, 0)
        Path(argv[-1]).write_bytes(b"x" * size)

    monkeypatch.setattr(renderer.subprocess, "run", download)
    with pytest.raises(ValueError, match=r"hash/size|type/size"):
        renderer.fetch_locked(lock_file(tmp_path, ARCHIVE), tmp_path / "out")


@pytest.mark.parametrize("count,size", [(129, 1), (3, 64 * 1024**2)])
def test_aggregate_bounds_precede_fetch(tmp_path, monkeypatch, count, size):
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"packages": [{**ARCHIVE, "size": size}] * count}))
    monkeypatch.setattr(renderer.subprocess, "run", lambda *a, **k: pytest.fail("network reached"))
    with pytest.raises(ValueError, match="aggregate"):
        renderer.fetch_locked(lock, tmp_path / "out")


def test_archive_build_remains_offline_in_bounded_preparation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    preparation = importlib.import_module("macos_preparation")
    calls = []

    def prepare_files(smoke, route, destination, wheels):
        assert route == "package"
        destination.mkdir(parents=True)
        wheels.mkdir()

    monkeypatch.setattr(preparation, "prepare_files", prepare_files)
    smoke = SimpleNamespace(
        directory=tmp_path,
        report={"owned_image_tags": []},
        docker=("synthetic-docker",),
        save=lambda: None,
        command=lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    renderer.prepare(smoke)
    assert len(calls) == 3
    for argv, kwargs in calls[:2]:
        assert argv[0] == sys.executable
        assert Path(argv[1]).name == "macos_prepare_renderer.py"
        assert kwargs == {"timeout": 900}
        assert "pip" not in argv  # host only fetches and verifies bytes
    argv, kwargs = calls[-1]
    assert argv[:2] == ("synthetic-docker", "build")
    for flag, value in (("--network", "none"), ("--platform", "linux/arm64")):
        assert argv[argv.index(flag) + 1] == value
    assert "--pull=false" in argv and kwargs == {"timeout": 480}
    assert [argv[i + 1] for i, arg in enumerate(argv) if arg == "--ulimit"] == [
        "data=2147483648:2147483648",
        "cpu=120:120",
        "nproc=256:256",
    ]
    recipe = (ROOT / "docker/renderer/Dockerfile").read_text()
    wheel_step = next(line for line in recipe.splitlines() if "pip wheel" in line)
    assert wheel_step.startswith("RUN --network=none ")
    assert all(
        flag in wheel_step
        for flag in (
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--require-hashes",
            "-r /build/pyopengl-source.lock",
        )
    )
