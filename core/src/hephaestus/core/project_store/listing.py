"""The ``list_parts`` projection — one serializer for CLI, MCP, and HTTP.

``INTERFACE.md`` §0.1 / §2.3: ``GET /parts`` returns this body, and so does
``heph part list --json``. The function used to live in
``hephaestus.agent_bridge.project_projections`` because MCP and HTTP were the
only callers; the CLI is a third, and it may not import the server package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hephaestus.core.project_store.store import ProjectStore

__all__ = ["list_parts_projection"]


def list_parts_projection(root: Path, project_store: ProjectStore) -> dict[str, Any]:
    """The ``list_parts`` body: ``[{name, path, content_hash, snapshot_ref}]``.

    ``path`` is relative to the project root — a client API never learns an
    absolute filesystem path it could try to hand back (``INTERFACE.md`` §2.3:
    no route takes a raw filesystem path).
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
