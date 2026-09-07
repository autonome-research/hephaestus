"""The ``list_parts`` projection — one serializer for CLI, MCP, and HTTP.

``INTERFACE.md`` §0.1 / §2.3: ``GET /parts`` returns this body, and so does
``heph part list --json``. The function used to live in
``hephaestus.agent_bridge.project_projections`` because MCP and HTTP were the
only callers; the CLI is a third, and it may not import the server package.

The **build-status vocabulary** lives here too, for the same layering reason.
``GET /parts/{part}/build``'s ``status`` and this listing's ``build_status`` are
one closed three-value set, and the projection that serves the build route is in
``hephaestus.http.projections`` — a module core may not import. So the rule is
written once *below* both (:func:`part_build_status`) and the build projection
calls it, rather than each spelling out its own ``ok`` / ``error`` /
``not_built``. Two spellings of one vocabulary is exactly the drift
``audit-2026-09-04`` J-web-viewport-7 asks a test to make impossible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal

from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.types import BuildResult

__all__ = [
    "BUILD_STATUS_VALUES",
    "PartBuildStatus",
    "list_parts_projection",
    "part_build_status",
]

#: The build axis's closed vocabulary as the **routes** serve it, in the order a
#: reader meets it: a published success, a published failure, and the named
#: absence. Distinct from :data:`hephaestus.core.types.BuildStatus`, which is the
#: two-value vocabulary of the *record* (``ok`` / ``failed``) and has no way to
#: say "nothing was ever published" because a record that does not exist cannot
#: carry a status.
BUILD_STATUS_VALUES: Final[tuple[str, ...]] = ("ok", "error", "not_built")

PartBuildStatus = Literal["ok", "error", "not_built"]


def part_build_status(result: BuildResult | None) -> PartBuildStatus:
    """The build axis's status for one part, from the record the routes read.

    ``result`` is what ``GET /parts/{part}/build`` projects: the current
    successful build when there is one, else the most-recent published failure,
    else ``None``. ``None`` is ``not_built`` — a named absence, not a 404 and not
    an empty success (§6.3: silence never reads as a pass).
    """
    if result is None:
        return "not_built"
    return "ok" if result.status == "ok" else "error"


def list_parts_projection(root: Path, project_store: ProjectStore) -> dict[str, Any]:
    """The ``list_parts`` body: ``[{name, path, content_hash, snapshot_ref,
    build_status}]``.

    ``path`` is relative to the project root — a client API never learns an
    absolute filesystem path it could try to hand back (``INTERFACE.md`` §2.3:
    no route takes a raw filesystem path).

    ``build_status`` is the build axis hoisted into the listing
    (``audit-2026-09-04`` J-web-viewport-7). §4.5's landing default was "the
    alphabetically first part the server lists", which correlates with nothing an
    operator cares about and in the shipped fixture is the one part that has
    never been built — so the first screen was an absence and every panel below
    it an empty state. The client-side alternative (read each part's build route
    and pick) is rejected: it would make the landing part depend on request
    timing, which is worse than a stable wrong answer. With the field here the
    default is a one-line pick over a document the client already has, and no
    extra request.

    The two reads behind it are the **same two** ``GET /parts/{part}/build``
    makes, in the same order and with the same preference for a current success
    over a later failure, and the status token comes from the one
    :func:`part_build_status` both call. They are lock-free pointer reads
    (:meth:`Publisher.current_result`, :meth:`Publisher.last_failure_result`), no
    rebuild and no freshness comparison: this route answers "is there anything to
    show", not "is what is shown up to date".

    The ``Publisher`` is constructed over the project store's **own** lock
    manager rather than a fresh one. Two ``LockManager`` owners inside one
    process would be two writers over one project's leases, which is the thing
    §2.1's "one process owns the leases" exists to prevent — and these reads take
    no lock at all, so sharing the owner costs nothing and cannot introduce a
    second one by accident.
    """
    publisher = Publisher(project_store.layout, project_store.store, locks=project_store.locks)
    parts: list[dict[str, Any]] = []
    for name in project_store.list_parts():
        snapshot = project_store.read_part(name)
        current = publisher.current_result(name)
        record = current if current is not None else publisher.last_failure_result(name)
        parts.append(
            {
                "name": name,
                "path": str(snapshot.path.relative_to(root)),
                "content_hash": snapshot.content_hash,
                "snapshot_ref": snapshot.snapshot_ref,
                "build_status": part_build_status(record),
            }
        )
    return {"status": "ok", "parts": parts}
