"""Stage 3 MCP tests that touch geometry: image-bearing results and both transports.

Separated from ``test_mcp_unit.py`` because these exercise the real executor and
a real HTTP server, so they are the slow half of the MCP unit suite.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from hephaestus.core.tools_decl import MAX_IMAGES_PER_RESULT
from hephaestus.mcp.app import HephaestusMCP, build_app
from hephaestus.testing.tools_fixture import scaffold
from mcp.types import ImageContent


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return scaffold(tmp_path / "proj")


@pytest.fixture
def runtime() -> Iterator[HephaestusMCP]:
    _, rt = build_app()
    try:
        yield rt
    finally:
        rt.close()


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(scenario())


def structured(result: Any) -> dict[str, Any]:
    content = cast("dict[str, Any] | None", result.structured_content)
    assert content is not None
    return content


async def open_project(client: Client[Any], root: Path) -> dict[str, Any]:
    return structured(await client.call_tool("open_project", {"path": str(root)}))


def test_inspect_part_returns_image_content_and_artifact_refs(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """Images ride as MCP image content; the artifact refs stay in the result."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            built = structured(await client.call_tool("build_part", {"name": "widget"}))
            assert built["status"] == "ok"

            out = await client.call_tool("inspect_part", {"name": "widget", "views": ["iso", "+X"]})
            payload = structured(out)
            images = [block for block in out.content if isinstance(block, ImageContent)]
            assert 1 <= len(images) <= MAX_IMAGES_PER_RESULT
            assert all(block.mimeType == "image/png" for block in images)
            assert payload["render_artifact_refs"]
            described = [cast("dict[str, Any]", d) for d in cast("list[Any]", payload["images"])]
            assert len(described) == len(images)
            # The base64 payload moves to the image blocks; the description stays.
            assert all("data" not in row for row in described)
            assert all(row["inline"] is True for row in described)
            assert all(str(row["render_artifact_ref"]).startswith("artifact:") for row in described)

    run(scenario)


def test_build_replay_returns_the_recorded_result(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """build_part is an idempotency-contract member: a same-id retry never rebuilds."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            session = cast("Any", client.session)
            request_id = int(session._request_id)
            first = structured(await client.call_tool("build_part", {"name": "widget"}))
            session._request_id = request_id
            replay = await client.call_tool("build_part", {"name": "widget"})
            assert structured(replay) == first
            meta: dict[str, Any] = replay.meta or {}
            assert meta.get("hephaestus.dev/replayed") is True

    run(scenario)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_streamable_http_serves_the_same_app(runtime: HephaestusMCP, project_root: Path) -> None:
    """One app, two transports: the HTTP surface is the stdio surface.

    The stock client sends no REST-only header — idempotency still derives from
    MCP session + request id, exactly as over stdio.
    """

    async def scenario() -> None:
        port = _free_port()
        server = asyncio.create_task(
            runtime.app.run_async(transport="http", host="127.0.0.1", port=port, show_banner=False)
        )
        url = f"http://127.0.0.1:{port}/mcp"
        try:
            for _ in range(100):
                await asyncio.sleep(0.05)
                try:
                    async with Client(url) as client:
                        await client.ping()
                    break
                except Exception:
                    continue
            else:  # pragma: no cover - server never came up
                pytest.fail("streamable HTTP server did not start")

            async with Client(url) as client:
                listed = {tool.name for tool in await client.list_tools()}
                assert {"open_project", "list_parts", "build_part"} <= listed
                await open_project(client, project_root)
                session = cast("Any", client.session)
                request_id = int(session._request_id)
                first = structured(await client.call_tool("create_part", {"name": "over_http"}))
                session._request_id = request_id
                replay = await client.call_tool("create_part", {"name": "over_http"})
                assert structured(replay) == first
                meta: dict[str, Any] = replay.meta or {}
                assert meta.get("hephaestus.dev/replayed") is True
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    run(scenario)
