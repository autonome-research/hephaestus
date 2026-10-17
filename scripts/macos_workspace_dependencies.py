# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Install the native workspace's non-CAD subset, exactly from uv.lock.

No lock resolution/upgrades and no host CAD/kernel packages. Existing .venv is
preserved; on a new checkout create it with the documented Python interpreter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

from macos_milestone_smoke import ROOT, Smoke, StageFailure, report_path
from macos_workspace import document

HOST_ROOTS = ("numpy", "starlette", "uvicorn", "websockets", "httpx", "jsonschema", "pypdf")


def host_lock():
    packages = {}
    for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]:
        packages.setdefault(package["name"], []).append(package)
    pending, seen, lines, versions = list(HOST_ROOTS), set(), [], {}
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        candidates = packages[name]
        if len(candidates) != 1:
            # uv's committed universal lock forks NumPy at Python 3.12. This
            # local launcher supports 3.13/3.14 Darwin only; require BOTH exact
            # non-Windows branch declarations rather than choosing the last
            # version or re-resolving the dependency graph.
            markers = {
                "python_full_version >= '3.14' and sys_platform != 'win32'",
                "python_full_version >= '3.12' and python_full_version < '3.14' "
                "and sys_platform != 'win32'",
            }
            candidates = [
                p for p in candidates if markers.issubset(p.get("resolution-markers", []))
            ]
        if len(candidates) != 1:
            raise StageFailure("ambiguous locked host dependency: " + name)
        package = candidates[0]
        if "registry" not in package["source"]:
            raise StageFailure("host subset must use locked public binary packages")
        pending.extend(d["name"] for d in package.get("dependencies", []))
        hashes = sorted({wheel["hash"] for wheel in package.get("wheels", [])})
        if not hashes:
            raise StageFailure("missing hash-locked binary dependency: " + name)
        versions[name] = package["version"]
        lines.append(
            name + "==" + package["version"] + " " + " ".join("--hash=" + h for h in hashes)
        )
    return "\n".join(sorted(lines)) + "\n", versions


def preflight(smoke):
    """Revalidate installed host pins and actually rebuild the frozen web sources."""
    _, expected = host_lock()
    _, raw = smoke.command(
        (
            str(ROOT / ".venv/bin/python"),
            "-c",
            "import importlib.metadata,json,sys; "
            "assert (3,13) <= sys.version_info[:2] <= (3,14); "
            "print(json.dumps({'python':sys.version,'packages': "
            "{n:importlib.metadata.version(n) for n in " + repr(sorted(expected)) + "}}))",
        )
    )
    actual = json.loads(raw)
    if actual["packages"] != expected:
        raise StageFailure("host dependency skew; run macos_workspace_dependencies.py")
    node, pnpm = shutil.which("node"), shutil.which("pnpm")
    if not node or not pnpm:
        raise StageFailure("Node/pinned pnpm required; see local launch instructions")
    package = json.loads((ROOT / "web/package.json").read_text())
    env = {
        "PATH": str(Path(pnpm).parent)
        + ":"
        + str(Path(node).parent)
        + ":/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": str(ROOT / "dist/macos-tool-home"),
        "LANG": "C",
        "CI": "true",
    }
    Path(env["HOME"]).mkdir(mode=0o700, exist_ok=True)
    previous = Path.cwd()
    try:
        os.chdir(ROOT / "web")
        for args in (
            ("--version",),
            (
                "install",
                "--frozen-lockfile",
                "--store-dir",
                str(ROOT / "dist/macos-pnpm-store"),
                "--network-concurrency=2",
                "--fetch-retries=0",
                "--fetch-timeout=30000",
            ),
            ("build",),
        ):
            result = smoke.transport.run(
                (node, pnpm, *args),
                input=b"",
                timeout=180 if args[0] == "install" else 90,
                stdout_limit=512 * 1024,
                stderr_limit=128 * 1024,
                env=env,
            )
            (smoke.directory / ("web-" + args[0].replace("--", "") + ".log")).write_bytes(
                result.stdout + result.stderr
            )
            if result.returncode:
                raise StageFailure("frozen web build/pnpm failed")
            if (
                args == ("--version",)
                and result.stdout.decode().strip() != package["packageManager"].split("@")[1]
            ):
                raise StageFailure("pnpm runtime differs from web pin")
    finally:
        os.chdir(previous)
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not chrome.is_file():
        raise StageFailure("native installed Google Chrome is required")
    expected_web = {**package["dependencies"], **package["devDependencies"]}
    actual_web = {
        name: json.loads((ROOT / "web/node_modules" / name / "package.json").read_text())["version"]
        for name in expected_web
    }
    if actual_web != expected_web:
        raise StageFailure("installed web dependency differs from exact package pin")
    smoke.report["workspace_dependencies"] = {
        "web_packages": actual_web,
        **actual,
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "web_lock_sha256": hashlib.sha256((ROOT / "web/pnpm-lock.yaml").read_bytes()).hexdigest(),
        "playwright": actual_web["@playwright/test"],
        "chrome_executable_sha256": hashlib.sha256(chrome.read_bytes()).hexdigest(),
    }
    smoke.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args()
    smoke = Smoke(report_path(args.report_dir))
    requirements, versions = host_lock()
    lock = smoke.directory / "host-requirements.lock"
    lock.write_text(requirements)
    uv = shutil.which("uv")
    if uv is None or not (ROOT / ".venv/bin/python").exists():
        raise StageFailure("create project-local .venv first; uv is required")
    smoke.command(
        (
            uv,
            "pip",
            "install",
            "--python",
            str(ROOT / ".venv/bin/python"),
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(lock),
        ),
        timeout=180,
    )
    document(smoke.directory / "installed-pins.json", versions)
    print("Installed locked non-CAD host dependencies; next frozen web install/build (see docs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
