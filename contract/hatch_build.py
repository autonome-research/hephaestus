# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Stage ``schemas/bridge_limits.json`` into ``hephaestus-contract`` as package data.

The §5 numeric limits live in exactly one file that Python, the agent bridge,
and the TypeScript sidecar all read, so a cap cannot be raised on one side of
the system alone. ``hephaestus.contract.tools_decl`` reads it *at import time* (the delegation
deadline bounds are module constants), which makes it a hard packaging
dependency: a wheel without it fails on ``import hephaestus.contract``.

``hephaestus-contract`` declares no dependencies at all — it is the canonical
tool-surface contract and must stay importable on its own — so it carries its
own staged copy rather than reaching into ``hephaestus-core`` for one.

A plain ``force-include`` of ``../schemas/bridge_limits.json`` cannot do this.
``uv build`` produces an sdist first and then builds the wheel *from that
sdist*, where the repo root — and therefore ``../schemas`` — no longer exists.

So the file is copied into the package before either target is collected: from
the repo when building in a checkout, and already present (carried by the sdist)
when building from one. The single-source-of-truth property survives packaging
without committing a second copy under ``src/``, which would be one more file to
forget to update.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

TARGET = Path("src") / "hephaestus" / "contract" / "_data" / "bridge_limits.json"
SOURCE_REL = Path("schemas") / "bridge_limits.json"


class LimitsBuildHook(BuildHookInterface[Any]):
    """Copy the canonical limits document into the package before collection."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        target = root / TARGET

        source: Path | None = None
        for parent in [root, *root.parents]:
            candidate = parent / SOURCE_REL
            if candidate.is_file():
                source = candidate
                break

        if source is None:
            # Building from an sdist: the copy staged when the sdist was built
            # is the only one there is, and it must be present.
            if target.is_file():
                return
            raise RuntimeError(
                f"cannot find {SOURCE_REL} above {root}, and no staged copy at {target}. "
                "hephaestus.contract imports it at import time; a wheel without it is broken."
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
