# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Refuse to build a ``hephaestus-server`` wheel without an intact sidecar.

The bundled sidecar is gitignored build output staged by
``scripts/stage_sidecar.py``. Without this hook, forgetting that step produces a
wheel that installs fine, passes import smoke, and then fails at the first
``heph agent`` with a resolver error — the worst possible place to discover it,
because the artifact is already published.

So the packaging failure is moved to the only moment it is cheap: build time.
The hook re-verifies the manifest rather than merely checking that files exist,
because a stale sidecar (bundle rebuilt, staging not re-run) is exactly as
broken as a missing one and looks identical to a directory listing.

Deliberately self-contained — no import from ``hephaestus`` — because a build
backend runs in an isolated environment where this project is not installed.
The format it validates is owned by
``hephaestus.agent_bridge.sidecar.write_manifest``; ``tests/stage7h`` asserts the
two agree.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

SIDECAR = Path("src") / "hephaestus" / "agent_bridge" / "_sidecar"
MANIFEST_NAME = "MANIFEST.json"

_STAGE_HINT = (
    "Build it with:\n"
    "  pnpm --dir agent install --frozen-lockfile\n"
    "  pnpm --dir agent run bundle\n"
    "  uv run python scripts/stage_sidecar.py"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class SidecarBuildHook(BuildHookInterface[Any]):
    """Verify the staged sidecar before hatchling collects any file."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        # ``version`` is hatchling's build flavor: "standard" for a real wheel,
        # "editable" for a dev install (``uv sync``, ``pip install -e``). The
        # sidecar requirement is a RELEASE-artifact property: a dev tree
        # resolves its sidecar from the repo (agent/build) and must be able to
        # ``uv sync`` on a bare checkout — CI's every Python job does exactly
        # that (run 30758605794 failed workspace-wide when this hook demanded
        # a staged sidecar from ``build_editable``).
        if version == "editable":
            self.app.display_info("editable build: packaged-sidecar check deferred to wheel build")
            return
        root = Path(self.root) / SIDECAR
        if not root.is_dir():
            raise RuntimeError(f"no packaged sidecar at {root}.\n{_STAGE_HINT}")

        manifest_path = root / MANIFEST_NAME
        if not manifest_path.is_file():
            raise RuntimeError(f"packaged sidecar has no {MANIFEST_NAME}: {root}\n{_STAGE_HINT}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries: dict[str, str] = manifest["entries"]

        on_disk = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != MANIFEST_NAME
        }
        if missing := sorted(set(entries) - on_disk):
            raise RuntimeError(
                f"packaged sidecar is missing {len(missing)} manifested file(s): "
                f"{', '.join(missing[:5])}\n{_STAGE_HINT}"
            )
        if extra := sorted(on_disk - set(entries)):
            raise RuntimeError(
                f"packaged sidecar carries {len(extra)} file(s) absent from its manifest: "
                f"{', '.join(extra[:5])}\n{_STAGE_HINT}"
            )
        for rel, expected in entries.items():
            actual = _sha256(root / rel)
            if actual != expected:
                raise RuntimeError(
                    f"packaged sidecar file {rel} does not match its manifest digest — the "
                    f"bundle was rebuilt without re-staging.\n{_STAGE_HINT}"
                )

        self.app.display_info(
            f"packaged sidecar {manifest.get('version', '?')} verified ({len(entries)} files)"
        )
