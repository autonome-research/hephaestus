# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""A real ``server/http`` app over a real project, in-process.

``INTERFACE.md`` §14's Tier 1 half is pytest against ``core/render/*`` and
``server/http``, so the harness has to be the **real** stack: a real opstore, a
real :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher`, the real
Starlette app, and a real bearer check. Only two things are doubled, and both
for speed rather than fidelity:

* the executor backend is the unsafe local one (``serve_mode=False``), exactly as
  ``hephaestus.testing.tools_fixture`` already does for the dispatch tests — a
  bwrap probe per test would make the suite unrunnable, and *what* the sandbox
  is has no bearing on the HTTP contract;
* the transport is ``starlette.testclient``, which drives the ASGI app directly:
  no socket, no port, no server process.

Everything the tests actually assert — the route table, the key ladder, the
error mapping, the artifact enumeration — is the shipped code.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import httpx
from hephaestus.http.app import build_app
from hephaestus.http.runtime import WorkspaceRuntime
from hephaestus.testing.fake_agent import FakeAgent
from starlette.applications import Starlette
from starlette.testclient import TestClient, WebSocketTestSession

__all__ = ["WORKSPACE_TOKEN", "Workspace", "uuid7", "workspace"]


def uuid7(at: float | None = None) -> str:
    """A UUIDv7 whose embedded timestamp is ``at`` (default: now).

    The stdlib has no v7 generator before 3.14 and the repo needs one on three
    lanes (``tests/stage3``, ``server/tests/test_mcp_unit``, and the REST key
    ladder), so it lives here rather than a fourth time in a test file.
    ``at`` exists because §2.5's first-sight freshness rung is only testable with
    a key whose timestamp is deliberately old.
    """
    millis = int((time.time() if at is None else at) * 1000)
    raw = bytearray(millis.to_bytes(6, "big") + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 9562 variant
    return str(uuid.UUID(bytes=bytes(raw)))


#: A fixed test bearer. Real serves mint a random one per serve; a fixed value
#: here keeps the 401 assertions readable and is never written to disk.
WORKSPACE_TOKEN: str = "test-workspace-token"


class Workspace:
    """A :class:`TestClient` that authenticates, plus the runtime behind it.

    ``starlette.testclient`` reaches ``httpx`` through a lazy import that pyright
    cannot follow, so the two members that cross that boundary — the app and each
    response — are narrowed here once instead of at every call site.
    """

    def __init__(
        self,
        runtime: WorkspaceRuntime,
        app: Starlette,
        client: httpx.Client,
        agent: FakeAgent | None = None,
    ) -> None:
        self.runtime = runtime
        self.app = app
        #: The attached fake agent runtime, when ``workspace(agent=True)``.
        self.agent = agent
        # ``TestClient`` *is* an ``httpx.Client``; narrowing to the base is what
        # makes `.request` and `.close` typed, since starlette's lazy httpx
        # import leaves the subclass's inherited members unresolved.
        self.client: httpx.Client = client
        self.root = runtime.root

    # -- requests ----------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        key: str | None = None,
        token: str | None = WORKSPACE_TOKEN,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """One API call. ``path`` is relative to ``/api/v1``.

        ``token=None`` omits the ``Authorization`` header entirely, which is how
        the 401 row of §2.4 is exercised.
        """
        sent: dict[str, str] = dict(headers or {})
        if token is not None:
            sent["Authorization"] = f"Bearer {token}"
        if key is not None:
            sent["Idempotency-Key"] = key
        return self.client.request(method, f"/api/v1{path}", json=json, headers=sent, params=params)

    def events(
        self, *, token: str | None = WORKSPACE_TOKEN, subprotocol: bool = False
    ) -> WebSocketTestSession:
        """Open the §2.7 ``GET /events`` socket.

        Two auth forms, both served: the ``Authorization`` header (normative in
        §2.2, and what a non-browser client uses) and the subprotocol form a
        browser is obliged to use because the WebSocket API has nowhere to put a
        header. ``token=None`` omits both, which is how the refused upgrade is
        exercised.
        """
        from hephaestus.http.events_ws import BEARER_SUBPROTOCOL

        client = cast("TestClient", self.client)
        if token is not None and subprotocol:
            return client.websocket_connect(
                "/api/v1/events", subprotocols=[BEARER_SUBPROTOCOL, token]
            )
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        return client.websocket_connect("/api/v1/events", headers=headers)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def raw(
        self, method: str, path: str, *, content: bytes, key: str | None = None
    ) -> httpx.Response:
        """A call whose body is exact bytes — the only way to test §2.5's scalar rule.

        ``json=`` would re-serialize through a JSON encoder, which is precisely
        the layer the unpaired-surrogate and malformed-body tests must bypass.
        """
        headers = {
            "Authorization": f"Bearer {self.runtime.token}",
            "Content-Type": "application/json",
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return self.client.request(method, f"/api/v1{path}", content=content, headers=headers)

    # -- the dispatch side of the §14 parity lane --------------------------

    def dispatch(self, tool: str, arguments: dict[str, Any], *, entry: str) -> Any:
        """The same call through ``ToolDispatcher``, bypassing HTTP entirely.

        §14's parity lane runs the same mutation / replay / conflict / paging
        cases through HTTP *and* through dispatch and asserts the outcomes are
        equal. This is the second lane, and it deliberately constructs the
        invocation the way the bridge does rather than the way the route does —
        two derivations, one dispatcher.
        """
        principal = self.runtime.dispatch_principal()
        return self.runtime.dispatcher.dispatch(
            principal,
            {
                "session_id": principal.session_id,
                "run_id": "parity",
                "tool": tool,
                "arguments": arguments,
                "invocation": {
                    "session_id": principal.session_id,
                    "entry_id": entry,
                    "ordinal": 0,
                    "provider_call_id": "parity",
                },
            },
        )


@contextmanager
def workspace(
    root: Path, *, scaffold: bool = True, broken: bool = False, agent: bool = False
) -> Generator[Workspace]:
    """Open a workspace app over ``root`` (scaffolding the fixture project first).

    ``agent=True`` attaches a :class:`~hephaestus.testing.fake_agent.FakeAgent`
    as the §2.7/§2.8 session backend: a **real** ``EventPump`` over this
    project's admission control, with a scripted callback where a Pi session
    would be. Without it the session routes refuse by name
    (``agent_unavailable``), which is what a serve with no provider config does.
    """
    from hephaestus.testing.ledger import seed_minimal_ledger
    from hephaestus.testing.tools_fixture import scaffold as scaffold_tools_project

    if scaffold:
        scaffold_tools_project(root, broken=broken)
    runtime = WorkspaceRuntime.open(root, token=WORKSPACE_TOKEN, serve_mode=False)
    seed_minimal_ledger(runtime.cad)
    fake_agent: FakeAgent | None = None
    if agent:
        fake_agent = FakeAgent(runtime.store.admission)
        runtime.attach_sessions(fake_agent)
    app = build_app(runtime)
    # Narrowed at construction: pyright narrows a declared type to the assigned
    # one, and `TestClient`'s inherited members are unresolved behind
    # starlette's lazy httpx import.
    client = cast("httpx.Client", TestClient(app))
    try:
        yield Workspace(runtime, app, client, agent=fake_agent)
    finally:
        client.close()
        if runtime.sessions is not None:
            runtime.sessions.close()
        runtime.close()
