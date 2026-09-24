# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Stage the core import package into the executor-only distribution.

The executor image must not install ``hephaestus-core``: that distribution's
metadata intentionally includes the renderer stack.  This private image-only
distribution packages the same reviewed Python sources with worker-only runtime
metadata.  It is never published as an end-user package.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

TARGET = Path("src") / "hephaestus"
CORE_SOURCE = Path("core") / "src" / "hephaestus"
SCHEMA_SOURCE = Path("schemas") / "bridge_limits.json"
SCHEMA_TARGET = TARGET / "core" / "_data" / "bridge_limits.json"


class ExecutorPackageBuildHook(BuildHookInterface[Any]):
    """Copy core sources before hatchling collects an sdist or wheel."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version, build_data
        root = Path(self.root)
        source_root: Path | None = None
        repository_root: Path | None = None
        for parent in (root, *root.parents):
            candidate = parent / CORE_SOURCE
            schema = parent / SCHEMA_SOURCE
            if candidate.is_dir() and schema.is_file():
                source_root = candidate
                repository_root = parent
                break

        target = root / TARGET
        if source_root is None or repository_root is None:
            # A wheel built from the generated sdist already carries the staged
            # tree. Refuse any partial sdist rather than producing a broken wheel.
            if target.is_dir() and (root / SCHEMA_TARGET).is_file():
                return
            raise RuntimeError("executor package cannot locate complete staged core sources")

        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            source_root,
            target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "_data"),
        )
        schema_target = root / SCHEMA_TARGET
        schema_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository_root / SCHEMA_SOURCE, schema_target)
