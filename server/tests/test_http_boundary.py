# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§1's boundary, as a mechanical test — and mission rule 6's proof.

``INTERFACE.md`` §1 draws the line:

    The client may compute **screen-space** quantities from server-supplied
    geometry […]. It may not compute, synthesize, reconcile, or infer **any
    value that appears in a result, a badge, a readout, a provenance answer, or
    a selection**.

The *client* half of that line is enforced in ``web/`` by the eslint rule
``heph/no-derived-fact`` and by the ``<Fact>`` primitive's ``data-source``
attribution (§4.6). The **server** half — the half that has to be true first, or
the client has nothing to attribute to — is what this file asserts:

1. ``server/http`` computes no engine value of its own. It imports no geometry
   kernel, no renderer, no check engine, and no build runner, so the closed list
   of §1 ("distances, volumes, masses, clearances, interference; section
   geometry; selection IDs […]; check verdicts, DFM findings […]; any re-count
   of anything a build result already counts") is unreachable from it by
   construction rather than by discipline.
2. Every tool-backed route reaches the engine through
   :meth:`ToolDispatcher.dispatch` and nowhere else — §2.2's "there is no
   bypass", asserted by watching the dispatcher rather than by reading the code.
3. The served surface **is** the closed route table of §2.3, in both directions.

§0.1 states mission rule 6 as the rule the spec follows literally, and the last
assertion here is its structural half: nothing in the headless surface
(``hephaestus.mcp``, ``hephaestus.agent_bridge``) imports ``hephaestus.http``,
because the 2026-07-26 ordering amendment says ``server/http`` "is a web client
API, not part of the headless surface" and nothing in G7H may come to depend on
it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.dispatch import ToolDispatcher
from hephaestus.http.app import API_PREFIX, ROUTE_TABLE, WEBSOCKET_ROUTES
from hephaestus.testing.workspace import uuid7, workspace
from starlette.routing import Route, WebSocketRoute

HTTP_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "hephaestus" / "http"
SERVER_SRC = Path(__file__).resolve().parents[1] / "src" / "hephaestus"

#: Modules whose import into ``hephaestus.http`` would mean the web layer had
#: acquired the ability to compute a §1 fact for itself. Each is the home of one
#: entry in §1's closed list.
FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "hephaestus.geom",  # distances, volumes, masses, clearances, interference
    "hephaestus.core.kernel",  # the OCCT boundary
    "hephaestus.core.render",  # section geometry, selection IDs, palettes
    "hephaestus.core.checks.engine",  # check verdicts
    "hephaestus.core.executor.runner",  # build results and their counts
    "hephaestus.core.dfm",  # DFM findings
    "hephaestus.core.motion",  # motion state
    "hephaestus.core.assembly",  # assembly state
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _package_imports(package: Path) -> dict[str, set[str]]:
    return {path.name: _imported_modules(path) for path in sorted(package.glob("*.py"))}


def test_http_imports_no_module_that_could_compute_a_section_one_fact() -> None:
    """§1's closed list is unreachable from ``server/http`` by construction.

    An import-level assertion rather than a call-level one on purpose: a call
    can be added without review noticing, and an import cannot be added without
    this test failing.
    """
    offenders: dict[str, set[str]] = {}
    for module, imports in _package_imports(HTTP_PACKAGE).items():
        hits = {
            name
            for name in imports
            for forbidden in FORBIDDEN_IMPORTS
            if name == forbidden or name.startswith(forbidden + ".")
        }
        if hits:
            offenders[module] = hits
    assert offenders == {}, (
        "server/http may not import a module that computes a §1 fact; "
        f"found {offenders}. Numbers, IDs, verdicts and provenance are the "
        "engine's — the web layer projects them, it does not produce them."
    )


def test_the_headless_surface_never_imports_the_web_client_api() -> None:
    """The 2026-07-26 ordering amendment, as a dependency-direction assertion.

    ``server/http`` is a web client API, not part of the headless surface.
    ``hephaestus.mcp`` and ``hephaestus.agent_bridge`` therefore import nothing
    from it; what the transports share lives above both (``project_projections``,
    ``core.artifacts``, ``core.checks.report``).
    """
    offenders: dict[str, set[str]] = {}
    for package in ("mcp", "agent_bridge"):
        for path in sorted((SERVER_SRC / package).rglob("*.py")):
            hits = {name for name in _imported_modules(path) if name.startswith("hephaestus.http")}
            if hits:
                offenders[str(path.relative_to(SERVER_SRC))] = hits
    assert offenders == {}, f"the headless surface must not depend on server/http: {offenders}"


def test_the_served_surface_is_exactly_the_closed_route_table(tmp_path: Path) -> None:
    """§2.3: "A route not listed here is not Stage 4/5 work" — both directions.

    AMENDMENT (§2.3, "Streams, history, git"): the table's ``GET /events`` row is
    a **WebSocket** upgrade, so the served surface is now two Starlette route
    classes rather than one. The assertion is unchanged in strength — set
    equality against the closed table, both directions — and gains a third
    obligation: every socket route must also be declared in
    :data:`WEBSOCKET_ROUTES`, so a row cannot silently change transport.
    """
    with workspace(tmp_path / "proj") as web:
        served: set[tuple[str, str]] = set()
        sockets: set[str] = set()
        for route in web.app.routes:
            assert isinstance(route, Route | WebSocketRoute)
            template = route.path.removeprefix(API_PREFIX)
            if isinstance(route, WebSocketRoute):
                sockets.add(template)
                served.add(("GET", template))
                continue
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    continue  # Starlette adds these; they serve no row
                served.add((method, template))
    assert served == set(ROUTE_TABLE)
    assert sockets == set(WEBSOCKET_ROUTES)


def test_no_delete_route_and_no_artifact_minting_route() -> None:
    """§2.3's named absences, asserted rather than merely written down.

    The workspace mints nothing (no ``POST /artifacts``) and deletes nothing (no
    ``DELETE`` anywhere). Both are refusals a future route could quietly
    contradict, so both are tests.
    """
    methods = {method for method, _ in ROUTE_TABLE}
    assert "DELETE" not in methods
    minting = [t for m, t in ROUTE_TABLE if m == "POST" and t.rstrip("/") == "/artifacts"]
    assert minting == []


def test_no_route_takes_a_raw_filesystem_path() -> None:
    """§2.3: no route that takes a raw filesystem path.

    Every path parameter in the table is a part name, an artifact ref, a run id,
    or a session id. A ``{path}`` segment would be a filesystem addressing
    surface, which this API deliberately does not have.
    """
    for _, template in ROUTE_TABLE:
        assert "{path" not in template, template


@pytest.mark.parametrize(
    ("method", "path", "tool"),
    [
        ("GET", "/parts/widget/script", "read_part"),
        ("POST", "/parts/widget/inspect", "inspect_part"),
    ],
)
def test_every_tool_route_reaches_the_engine_through_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, path: str, tool: str
) -> None:
    """§2.2: "Every tool route goes through ToolDispatcher.dispatch — no bypass."

    Watched rather than read: the dispatcher's own method records what it was
    asked for, so a route that grew a shortcut into ``CadOps`` would show up as
    an empty log rather than as a diff nobody re-read.
    """
    seen: list[str] = []
    original = ToolDispatcher.dispatch

    def spy(self: ToolDispatcher, principal: Any, params: dict[str, Any]) -> Any:
        seen.append(str(params.get("tool")))
        return original(self, principal, params)

    monkeypatch.setattr(ToolDispatcher, "dispatch", spy)
    with workspace(tmp_path / "proj") as web:
        seen.clear()
        response = web.request(method, path, json={} if method == "POST" else None)
    assert response.status_code in (200, 400), response.text
    assert tool in seen, f"{method} {path} did not reach ToolDispatcher.dispatch"


def test_the_dispatch_principal_is_orchestrator_and_is_not_a_session(tmp_path: Path) -> None:
    """§2.2: the workspace principal is not a Pi session and must not borrow one.

    ``profile="orchestrator"`` mirrors ``mcp/app.py``'s ``_MCP_PROFILE`` — a
    local operator with the project open is orchestrator-equivalent — while the
    identity is namespaced ``web:`` so it can never collide with a Pi session id
    or an MCP one in a ledger row.
    """
    with workspace(tmp_path / "proj") as web:
        principal = web.runtime.dispatch_principal()
        assert principal.profile == "orchestrator"
        assert principal.part is None
        assert principal.session_id.startswith("web:")
        assert web.runtime.workspace_principal().project_root == web.root


def test_the_web_layer_holds_no_second_copy_of_a_shared_contract(tmp_path: Path) -> None:
    """§19 item 5: ``page_text`` and ``report_json`` are called, not re-written.

    The route and the tool must return the *same* page for the same offset —
    that is what G5.8's "losslessly" means across two authorizations — and the
    only way to keep that true is for both to call one function. This asserts
    the equality that a second implementation would eventually break.
    """
    from hephaestus.core.artifacts import page_text

    with workspace(tmp_path / "proj") as web:
        built = web.post("/parts/widget/build", json={}, key=uuid7())
        assert built.status_code == 200, built.text
        parts = web.get("/parts").json()["parts"]
        ref = next(p["snapshot_ref"] for p in parts if p["name"] == "widget")

        route_page = web.get(f"/artifacts/{ref}/text", params={"offset_bytes": "0"}).json()
        tool_page = web.dispatch(
            "read_artifact", {"ref": ref, "offset_bytes": 0}, entry="parity-page"
        )
        blob = web.runtime.store.blobs.get(ref.split(":", 2)[2])
        shared = page_text(blob, 0, len(blob))

    assert route_page["content"] == tool_page["content"] == shared["content"]
    assert route_page["total_bytes"] == tool_page["total_bytes"] == shared["total_bytes"]
