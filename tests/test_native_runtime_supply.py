# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""No network: exact snapshot admission, redirects and downloaded byte integrity."""

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker/executor"))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_native_runtime as native  # noqa: E402
import macos_prepare_renderer as renderer  # noqa: E402


def test_both_arm64_locks_preserve_identical_expat_closure():
    for role in ("executor", "renderer"):
        lock = native._load_lock(ROOT / f"docker/{role}/native-arm64.lock.json", "arm64")
        item = next(p for p in lock["packages"] if p["filename"] == native.EXPAT_PIN[0])
        assert (item["filename"], item["sha256"], item["size"]) == native.EXPAT_PIN
        assert item["url"] == native.EXPAT_SNAPSHOT


@pytest.mark.parametrize(
    "mutation",
    ["host", "http", "port", "user", "query", "fragment", "address", "filename", "hash", "size"],
)
def test_snapshot_allowlist_is_exact(tmp_path, mutation):
    filename, digest, size = native.EXPAT_PIN
    url = native.EXPAT_SNAPSHOT
    if mutation == "host":
        url = url.replace("snapshot.debian.org", "snapshot.debian.org.evil.test")
    elif mutation == "http":
        url = url.replace("https:", "http:")
    elif mutation == "port":
        url = url.replace(".org/", ".org:444/")
    elif mutation == "user":
        url = url.replace("https://", "https://user@")
    elif mutation == "query":
        url += "?redirect=other"
    elif mutation == "fragment":
        url += "#fragment"
    elif mutation == "address":
        url = url[:-1] + "0"
    elif mutation == "filename":
        filename = "other.deb"
    elif mutation == "hash":
        digest = "a" * 64
    elif mutation == "size":
        size += 1
    item = {"filename": filename, "sha256": digest, "size": size, "url": url}
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"architecture": "arm64", "packages": [item]}))
    with pytest.raises(ValueError, match="integrity policy"):
        native._load_lock(lock, "arm64")
    with pytest.raises(ValueError, match="integrity policy"):
        renderer.fetch_locked(lock, tmp_path / "output")


@pytest.mark.parametrize(
    "url", ["http://deb.debian.org/x", "https://evil.test/x", native.EXPAT_SNAPSHOT]
)
def test_redirects_refuse_even_other_allowlisted_sources(url):
    with pytest.raises(ValueError, match="redirects"):
        native.NoRedirect().redirect_request(None, None, 302, "", {}, url)


@pytest.mark.parametrize("fault", ["valid", "hash", "short", "oversize"])
def test_downloader_checks_received_bytes_and_removes_partial(tmp_path, monkeypatch, fault):
    data = b"fixed bytes"
    item = {
        "filename": "test.deb",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "url": "https://deb.debian.org/debian/pool/test.deb",
    }
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"architecture": "arm64", "packages": [item]}))
    body = {"valid": data, "hash": b"x" * len(data), "short": data[:-1], "oversize": data + b"x"}[
        fault
    ]

    class Opener:
        def open(self, url, timeout):
            assert url == item["url"] and timeout == 60
            return io.BytesIO(body)

    def opener(handler):
        assert isinstance(handler, native.NoRedirect)
        return Opener()

    monkeypatch.setattr(native.urllib.request, "build_opener", opener)
    output = tmp_path / "output"
    if fault == "valid":
        native.fetch(lock, output, "arm64")
        assert (output / "test.deb").read_bytes() == data
    else:
        with pytest.raises(ValueError, match=r"integrity|size"):
            native.fetch(lock, output, "arm64")
        assert list(output.iterdir()) == []


def test_renderer_download_disallows_redirects_and_bounds_curl(tmp_path, monkeypatch):
    data = b"wheel"
    item = {
        "filename": "test.whl",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "url": "https://files.pythonhosted.org/test.whl",
    }
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"packages": [item]}))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[:2] == ("/usr/bin/curl", "--disable")
        assert argv[argv.index("--max-redirs") + 1] == "0"
        assert argv[argv.index("--proto") + 1] == "=https"
        assert argv[argv.index("--max-filesize") + 1] == str(len(data))
        assert kwargs == {"check": True, "timeout": 310}
        Path(argv[-1]).write_bytes(data)

    monkeypatch.setattr(renderer.subprocess, "run", run)
    renderer.fetch_locked(lock, tmp_path / "output")
    assert len(calls) == 1


def test_renderer_curl_ignores_user_config_without_network(tmp_path, monkeypatch):
    # A config could enable insecure TLS or add unbounded extra transfers. Use an
    # invalid option as a canary, then a forbidden file URL to avoid any network.
    home = tmp_path / "home"
    home.mkdir()
    (home / ".curlrc").write_text("review-invalid-option = true\n")
    for key in ("HOME", "CURL_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(key, str(home))
    item = {
        "filename": "test.whl",
        "sha256": "a" * 64,
        "size": 1,
        "url": "https://files.pythonhosted.org/test.whl",
    }
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"packages": [item]}))
    real_run = subprocess.run
    results = []

    def run(argv, **kwargs):
        args = list(argv)
        args[args.index(item["url"])] = lock.as_uri()
        result = real_run(args, capture_output=True, timeout=10)
        results.append(result)
        result.check_returncode()

    monkeypatch.setattr(renderer.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        renderer.fetch_locked(lock, tmp_path / "output")
    assert len(results) == 1 and results[0].returncode == 1
    assert b"review-invalid-option" not in results[0].stderr
    assert b"disabled" in results[0].stderr
    assert not (tmp_path / "output/test.whl").exists()
