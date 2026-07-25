"""Gate G3, streamable HTTP: the *same* stock-client flow, over the *same* app.

    The same stock-client flow passes over streamable HTTP with MCP
    session/request identity and no REST-only header; optional MCP ``_meta`` is
    tested separately.

So this module calls :func:`_stock_client.run_flow` — byte-for-byte the client
code ``test_stdio_flow`` runs — against ``heph serve --mcp --http`` on an
ephemeral port, and then pins the two properties the clause names:

* **MCP session identity** — the transport negotiates an ``Mcp-Session-Id``, and
  mutation identity is scoped to it: the same JSON-RPC request id in a *second*
  session is a new operation, not a replay.
* **no REST-only header** — every request header the stock client sends is
  recorded and asserted against the MCP/HTTP standard set, so nothing like an
  ``Idempotency-Key`` header is smuggled in to make the flow pass.

``_meta`` is deliberately absent here; ``test_idempotency`` covers it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from _stock_client import (
    PLATE_VOLUME_MM3,
    ask_user_round_trip,
    elicitation_answerer,
    fixture_project,
    free_port,
    http_server,
    run_flow,
    step_solid_count_and_volume,
    structured,
)
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

VOLUME_RTOL = 1e-3

#: Headers a standards-conforming MCP streamable-HTTP client may send. Anything
#: outside this set would be a REST-only channel the gate forbids.
ALLOWED_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "cache-control",
        "connection",
        "content-length",
        "content-type",
        "host",
        "last-event-id",
        "mcp-protocol-version",
        "mcp-session-id",
        "user-agent",
    }
)


@asynccontextmanager
async def http_session(
    url: str,
    *,
    elicitation_callback: Any = None,
    seen_headers: list[dict[str, str]] | None = None,
) -> AsyncIterator[tuple[ClientSession, Any]]:
    """A stock streamable-HTTP client session (optionally recording headers)."""

    http_client = create_mcp_http_client(timeout=httpx.Timeout(60.0, read=900.0))
    if seen_headers is not None:

        async def record(request: httpx.Request) -> None:
            seen_headers.append({k.lower(): v for k, v in request.headers.items()})

        http_client.event_hooks["request"].append(record)

    async with (
        http_client,
        streamable_http_client(url, http_client=http_client) as (
            read,
            write,
            get_session_id,
        ),
        ClientSession(read, write, elicitation_callback=elicitation_callback) as session,
    ):
        yield session, get_session_id


def test_http_full_flow_exports_a_step_that_reimports_with_matching_volume(
    tmp_path: Path,
) -> None:
    """The stdio flow, unchanged, over streamable HTTP — including the STEP check."""
    root = fixture_project(tmp_path)
    headers: list[dict[str, str]] = []

    async def scenario() -> None:
        with http_server(free_port()) as url:
            async with http_session(url, seen_headers=headers) as (session, get_session_id):
                outcome = await run_flow(session, root)
                session_id = get_session_id()

        assert session_id, "streamable HTTP negotiated no MCP session id"
        assert outcome.image_count >= 1
        assert set(outcome.image_mime_types) == {"image/png"}
        assert outcome.measured_volume == pytest.approx(PLATE_VOLUME_MM3, rel=1e-9)

        step_files = [root / p for p in outcome.export_paths if p.endswith(".step")]
        assert step_files, outcome.export_paths
        solids, volume = step_solid_count_and_volume(step_files[0])
        assert solids == 1, f"expected one solid in the STEP, got {solids}"
        assert abs(volume - outcome.measured_volume) <= VOLUME_RTOL * outcome.measured_volume

        # Identity rode in MCP's own header, and only MCP's headers were sent.
        assert any(row.get("mcp-session-id") == session_id for row in headers)
        unexpected = {key for row in headers for key in row} - ALLOWED_HEADERS
        assert not unexpected, f"stock client sent non-MCP headers: {sorted(unexpected)}"

    asyncio.run(scenario())


def test_http_mutation_identity_is_scoped_to_the_mcp_session(tmp_path: Path) -> None:
    """Session + request id, not a REST header: the same id in a new session is new work.

    A stock client cannot choose its JSON-RPC ids — the SDK allocates them — so
    the test rewinds the SDK's own counter to re-present an id, which is exactly
    what a client that reconnects and starts counting from 1 again does.
    """
    root = fixture_project(tmp_path)

    async def scenario() -> None:
        with http_server(free_port()) as url:
            async with http_session(url) as (session, _):
                await session.initialize()
                opened = structured(await session.call_tool("open_project", {"path": str(root)}))
                assert opened["status"] == "ok"
                request_id = _peek_request_id(session)
                first = await session.call_tool("create_part", {"name": "over_http"})
                _rewind_request_id(session, request_id)
                replay = await session.call_tool("create_part", {"name": "over_http"})
                assert structured(replay) == structured(first)
                assert (replay.meta or {}).get("hephaestus.dev/replayed") is True

            # A brand-new MCP session: the same id is a *different* key, so the
            # server really runs the mutation again — and it fails, because the
            # part now exists. Nothing outside the MCP session identifies it.
            async with http_session(url) as (session, _):
                await session.initialize()
                await session.call_tool("open_project", {"path": str(root)})
                _rewind_request_id(session, request_id)
                retried = await session.call_tool("create_part", {"name": "over_http"})
                assert retried.isError, structured(retried)
                assert (retried.meta or {}).get("hephaestus.dev/replayed") is None

    asyncio.run(scenario())


def test_http_ask_user_round_trips_through_mcp_elicitation() -> None:
    """Elicitation works over streamable HTTP, not just stdio."""
    seen: dict[str, Any] = {}

    async def scenario() -> None:
        with http_server(free_port()) as url:
            async with http_session(
                url, elicitation_callback=elicitation_answerer("fillet", seen)
            ) as (session, _):
                answered = await ask_user_round_trip(session, seen)
        assert answered == {"selection": "fillet"}
        # The elicitation really carried a schema the client filled in.
        assert sorted(seen["properties"]) == ["value"]

    asyncio.run(scenario())


def _peek_request_id(session: ClientSession) -> int:
    return int(session._request_id)


def _rewind_request_id(session: ClientSession, value: int) -> None:
    session._request_id = value
