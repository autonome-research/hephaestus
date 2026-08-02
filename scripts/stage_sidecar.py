# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Stage the bundled Node sidecar into ``hephaestus-server`` as package data.

This is the step between ``pnpm --dir agent run bundle`` and ``uv build``. It
copies the bundle into ``server/src/hephaestus/agent_bridge/_sidecar/``, distils
the esbuild metafile into a small ``AUDIT.json``, and writes the SHA-256
``MANIFEST.json`` the supervisor verifies before every spawn.

Why the sidecar lives inside ``hephaestus-server`` rather than the aggregate
``hephaestus-cad`` distribution: the code that resolves and spawns it is
``hephaestus.agent_bridge``. Shipping the payload in the same distribution as
its only consumer means ``pip install hephaestus-server`` is self-consistent,
and there is no way to assemble an installation whose bridge and sidecar come
from different releases.

``AUDIT.json`` exists so the shipped wheel is self-describing for the G7H
native-addon / ``openai`` audit. Walking a 14 MB bundle for import edges at test
time would be guesswork; the build knows the module graph exactly, so it records
the two findings the gate asks about and the test asserts over facts rather than
regexes.

Usage::

    pnpm --dir agent install --frozen-lockfile
    pnpm --dir agent run bundle
    uv run python scripts/stage_sidecar.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "agent" / "build" / "sidecar"
STAGE_DIR = REPO_ROOT / "server" / "src" / "hephaestus" / "agent_bridge" / "_sidecar"
METAFILE = BUNDLE_DIR / "meta.json"

sys.path.insert(0, str(REPO_ROOT / "server" / "src"))

from hephaestus.agent_bridge.sidecar import (  # noqa: E402
    MANIFEST_NAME,
    verify_sidecar,
    write_manifest,
)

#: The manifest and the metafile are build inputs, not sidecar payload.
_EXCLUDED = frozenset({MANIFEST_NAME, "meta.json", "AUDIT.json"})

#: Bare specifiers the bundle may leave unresolved — ws's optional native
#: accelerators, required inside a try/catch. Mirrors ``ALLOWED_EXTERNALS`` in
#: ``agent/scripts/bundle.mjs``; the audit records them so the gate can assert
#: nothing *else* escaped.
ALLOWED_EXTERNALS = ("bufferutil", "utf-8-validate")


def _npm_package(input_path: str) -> str | None:
    """The npm package an esbuild input path belongs to, if any."""
    marker = input_path.rfind("node_modules/")
    if marker < 0:
        return None
    rest = input_path[marker + len("node_modules/") :].split("/")
    if rest[0].startswith("@") and len(rest) > 1:
        return f"{rest[0]}/{rest[1]}"
    return rest[0]


def _audit(metafile: Path) -> dict[str, Any]:
    """Distil the esbuild metafile into the facts the G7H audit asserts over.

    Two findings carry gate weight, both from ``repo_conventions.md``:

    * **thread-phase must not drag in ``openai``.** The bundle *does* contain the
      ``openai`` SDK, but every import edge into it originates in
      ``@earendil-works/pi-ai``'s provider adapters — pi's own OpenAI-compatible
      transport, which the fake-model lane exercises deliberately. The
      thread-phase edge count is recorded so the gate asserts it is zero rather
      than asserting the SDK is absent, which would be false and would have to be
      waived.
    * **no required native addon.** Recorded as the set of unresolved bare
      specifiers; ``.node`` files are audited directly off the shipped tree.
    """
    meta: dict[str, Any] = json.loads(metafile.read_text(encoding="utf-8"))
    inputs: dict[str, Any] = meta.get("inputs", {})

    packages = sorted({pkg for path in inputs if (pkg := _npm_package(path)) is not None})

    openai_importers: set[str] = set()
    thread_phase_openai_edges = 0
    for path, node in inputs.items():
        node_imports: Iterable[dict[str, Any]] = node.get("imports", [])
        for edge in node_imports:
            target = str(edge.get("path", ""))
            if "node_modules/openai/" not in target:
                continue
            owner = _npm_package(path)
            if owner == "openai":
                continue  # openai's own internal edges
            openai_importers.add(owner or "<sidecar source>")
            if owner == "@autonome-research/thread-phase":
                thread_phase_openai_edges += 1

    return {
        "bundler": "esbuild",
        "allowed_externals": list(ALLOWED_EXTERNALS),
        "npm_packages": packages,
        "openai": {
            "present": "openai" in packages,
            "importers": sorted(openai_importers),
            "thread_phase_edges": thread_phase_openai_edges,
        },
    }


def _version() -> str:
    """The sidecar version: ``agent/package.json``'s, the artifact's own."""
    pkg = json.loads((REPO_ROOT / "agent" / "package.json").read_text(encoding="utf-8"))
    return str(pkg["version"])


def _smoke(root: Path) -> None:
    """Spawn both entry points and require each to actually start.

    Bundling breaks things that a type-checker cannot see. Two real examples
    from staging this artifact the first time: the sidecar read
    ``schemas/bridge_limits.json`` at a path that only exists in the repo, and
    the workflow runner's ``import.meta.url`` entry-point guard stopped matching
    once code splitting hoisted its body into a shared chunk — so it exited 0 at
    every spawn and the failure surfaced, three respawns later, as "sidecar is
    not running".

    Both were silent at build time and expensive to diagnose downstream. Each
    entry is therefore spawned here with its stdin closed: a healthy sidecar
    logs its startup banner and exits 0, a broken one dies non-zero or never
    announces itself. This is a build-time gate, not a test — a sidecar that
    cannot start must never reach a wheel.
    """
    node = shutil.which("node")
    if node is None:
        print("warning: node absent; skipping sidecar startup smoke", file=sys.stderr)
        return
    for name, rel in (("main", "main.js"), ("runner", "workflows/runner.js")):
        proc = subprocess.run(
            [node, str(root / rel)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        output = proc.stdout + proc.stderr
        if proc.returncode != 0:
            raise SystemExit(
                f"staged sidecar {name} entry failed to start (rc={proc.returncode}):\n{output}"
            )
        if "started" not in output:
            raise SystemExit(
                f"staged sidecar {name} entry exited {proc.returncode} without starting.\n"
                f"It never logged its banner, so it was loaded but never ran — check the\n"
                f"entry-point guard against the bundle's chunk layout.\n{output}"
            )


def stage() -> Path:
    """Copy, audit, and manifest the bundle. Returns the staged root."""
    if not BUNDLE_DIR.is_dir():
        raise SystemExit(
            f"no bundle at {BUNDLE_DIR}\nrun: pnpm --dir agent install --frozen-lockfile "
            "&& pnpm --dir agent run bundle"
        )
    if not METAFILE.is_file():
        raise SystemExit(f"no esbuild metafile at {METAFILE}; re-run the bundle")

    audit = _audit(METAFILE)

    shutil.rmtree(STAGE_DIR, ignore_errors=True)
    STAGE_DIR.mkdir(parents=True)
    for source in sorted(BUNDLE_DIR.rglob("*")):
        if not source.is_file() or source.name in _EXCLUDED:
            continue
        target = STAGE_DIR / source.relative_to(BUNDLE_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    (STAGE_DIR / "AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    manifest = write_manifest(STAGE_DIR, version=_version())
    verify_sidecar(STAGE_DIR)  # never ship a manifest we cannot immediately verify
    _smoke(STAGE_DIR)

    total = sum((STAGE_DIR / rel).stat().st_size for rel in manifest.entries)
    print(
        f"staged sidecar {manifest.version} -> {STAGE_DIR}\n"
        f"  {len(manifest.entries)} files, {total / 1e6:.1f} MB\n"
        f"  openai importers: {', '.join(audit['openai']['importers']) or 'none'}\n"
        f"  thread-phase -> openai edges: {audit['openai']['thread_phase_edges']}"
    )
    return STAGE_DIR


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    stage()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
