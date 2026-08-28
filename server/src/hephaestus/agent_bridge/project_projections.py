# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Project projections shared by every serving surface.

``INTERFACE.md`` §2.3 says ``GET /project`` returns "the ``open_project``
projection, **same serializer** as ``mcp/app.py``". That is mission rule 6 in a
sentence, and it has a direction: the MCP app is part of the headless serve
surface and the workspace API explicitly is **not** (``INTERFACE.md`` §0, the
2026-07-26 ordering amendment: ``server/http`` "is a web client API, not part of
the headless surface", and nothing in G7H may come to depend on it). So the
shared serializer cannot live in :mod:`hephaestus.http`, and it cannot be
duplicated. It lives here, above both, and both import it.

This module deliberately holds only projections that are shared *across
transports*. A projection with one caller belongs next to that caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.store import ProjectStore

__all__ = [
    "CAPABILITY_KEYS",
    "list_parts_projection",
    "open_project_projection",
]

#: ``GET /project``'s ``capabilities`` map, closed.
#:
#: TIGHTENING (binds ``INTERFACE.md`` §2.3's ``GET /project`` row). The spec
#: names the field once and never enumerates it. An open map here would be
#: exactly the "compute a fact client-side because the server declined to offer
#: it" §0.1 forbids — the client would learn to sniff keys. It is therefore
#: closed at the two **server** facts the Stage 4/5 panels actually branch on,
#: and any addition is an amendment rather than a key someone slipped in:
#:
#: * ``secure_executor`` — a probed secure backend exists, so builds can run.
#:   When false, ``capability_not_available`` is the expected answer from every
#:   build-shaped route, and §6.4's DFM panel renders its explanatory refusal
#:   card rather than an empty list.
#: * ``git`` — the project root is a git work tree, so §2.9's projection routes
#:   have something to project. When false the Versions panel is absent, not
#:   empty.
CAPABILITY_KEYS: Final[tuple[str, ...]] = ("secure_executor", "git")


def open_project_projection(
    layout: ProjectLayout,
    project_store: ProjectStore,
    *,
    serve_mode: bool,
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """The ``open_project`` body: root, name, units, parts, serve mode.

    Called by ``mcp/app.py``'s ``open_project`` verb and by ``GET /project``.
    ``capabilities`` is the web-only addition (§2.3) and is omitted for MCP,
    whose client is the agent and has no panels to hide.
    """
    payload: dict[str, Any] = {
        "status": "ok",
        "root": str(layout.root),
        "name": layout.manifest.name,
        "units": layout.manifest.units,
        "parts": list(project_store.list_parts()),
        "serve_mode": serve_mode,
    }
    if capabilities is not None:
        payload["capabilities"] = {
            key: bool(capabilities.get(key, False)) for key in CAPABILITY_KEYS
        }
    return payload


def list_parts_projection(root: Path, project_store: ProjectStore) -> dict[str, Any]:
    """The ``list_parts`` body: ``[{name, path, content_hash, snapshot_ref}]``.

    ``path`` is relative to the project root — a client API never learns an
    absolute filesystem path it could try to hand back (§2.3: no route takes a
    raw filesystem path).
    """
    parts: list[dict[str, Any]] = []
    for name in project_store.list_parts():
        snapshot = project_store.read_part(name)
        parts.append(
            {
                "name": name,
                "path": str(snapshot.path.relative_to(root)),
                "content_hash": snapshot.content_hash,
                "snapshot_ref": snapshot.snapshot_ref,
            }
        )
    return {"status": "ok", "parts": parts}
