"""Stage 3 MCP unit tests: in-process ``fastmcp.Client`` against the real app.

Everything here drives the app the way a stock MCP client does — ``list_tools``
plus ``call_tool`` over the in-memory transport, with no Hephaestus code on the
client side other than the assertions. The project underneath is the same real
scaffold the dispatch tests use (``tools_fixture``), so calls land in the real
:class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher` /
:class:`~hephaestus.agent_bridge.cad_ops.CadOps` over a real opstore.

Tests are ordinary synchronous functions driving one ``asyncio.run`` scenario
each (the convention already used by the bridge tests), so no pytest async
plugin is required.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from hephaestus.core.errors import UnsafeRefusedError
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.tools_decl import TOOLS_BY_NAME
from hephaestus.mcp.app import EXTRA_TOOL_NAMES, HephaestusMCP, build_app
from hephaestus.mcp.idempotency import IDEMPOTENCY_META_KEY
from mcp.types import ImageContent, TextContent
from tools_fixture import scaffold

AnyClient = Client[Any]


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
    """Drive one async scenario to completion."""
    asyncio.run(scenario())


def structured(result: Any) -> dict[str, Any]:
    """The structured content of a tool result (tests always assert on it)."""
    content = cast("dict[str, Any] | None", result.structured_content)
    assert content is not None
    return content


def result_meta(result: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", result.meta) if result.meta else {}


async def open_project(client: AnyClient, root: Path) -> dict[str, Any]:
    return structured(await client.call_tool("open_project", {"path": str(root)}))


def rewind_request_id(client: AnyClient, to: int) -> None:
    """Make the next call reuse an earlier JSON-RPC request id (a stock client's shape)."""
    cast("Any", client.session)._request_id = to


def next_request_id(client: AnyClient) -> int:
    return int(cast("Any", client.session)._request_id)


# -- tool surface ----------------------------------------------------------


def test_tool_listing_matches_canonical_names(runtime: HephaestusMCP) -> None:
    """Listed tools = the canonical surface + exactly the documented extras."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            listed = {tool.name for tool in await client.list_tools()}
        canonical = set(TOOLS_BY_NAME)
        assert canonical <= listed
        assert listed - canonical == set(EXTRA_TOOL_NAMES)

    run(scenario)


def test_declarations_carry_the_canonical_input_schema(runtime: HephaestusMCP) -> None:
    """Schemas are generated, not hand-written: they equal the canonical params."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        for name, decl in TOOLS_BY_NAME.items():
            assert tools[name].inputSchema == decl.params, name
            meta: dict[str, Any] = tools[name].meta or {}
            block = cast("dict[str, Any]", meta["hephaestus.dev/tool"])
            assert block["profiles"] == list(decl.profiles)
            assert block["idempotent"] is decl.idempotent

    run(scenario)


def test_committed_mcp_document_is_not_stale() -> None:
    """``schemas/mcp/tools.json`` is generated output; regenerating changes nothing."""
    from hephaestus.core import toolgen

    path = toolgen.repo_root() / "schemas" / "mcp" / "tools.json"
    committed = path.read_text(encoding="utf-8")
    assert committed == toolgen.generate_mcp_document(), "rerun `toolgen mcp`"
    assert toolgen.generate_mcp_document() == toolgen.generate_mcp_document()


def test_registered_declarations_come_from_the_generator(runtime: HephaestusMCP) -> None:
    """The live MCP surface is the generated document, not a parallel hand-written one."""
    from hephaestus.core import toolgen

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            listed = {tool.name: tool for tool in await client.list_tools()}
        for declaration in toolgen.mcp_declarations():
            name = str(declaration["name"])
            assert listed[name].inputSchema == declaration["inputSchema"]
            assert listed[name].description == declaration["description"]
            meta: dict[str, Any] = listed[name].meta or {}
            expected = cast("dict[str, Any]", declaration["_meta"])
            # FastMCP adds its own "fastmcp" block; ours must survive verbatim.
            assert {k: meta[k] for k in expected} == expected

    run(scenario)


# -- project binding -------------------------------------------------------


def test_open_project_and_list_parts(runtime: HephaestusMCP, project_root: Path) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            opened = await open_project(client, project_root)
            assert opened["status"] == "ok"
            assert opened["root"] == str(project_root.resolve())
            assert opened["parts"] == ["bracket", "widget"]

            listed = structured(await client.call_tool("list_parts", {}))
            rows = [cast("dict[str, Any]", p) for p in cast("list[Any]", listed["parts"])]
            assert [row["name"] for row in rows] == ["bracket", "widget"]
            assert rows[0]["path"] == "parts/bracket.py"
            assert str(rows[0]["content_hash"]).startswith("sha256:")

    run(scenario)


def test_project_tools_refuse_without_an_open_project(runtime: HephaestusMCP) -> None:
    """The mcp principal is orchestrator-equivalent, but bound by open_project."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            out = await client.call_tool("read_part", {"name": "widget"}, raise_on_error=False)
            assert out.is_error
            assert structured(out)["reason"] == "no_project_open"

    run(scenario)


def test_read_part_dispatches_through_the_shared_dispatcher(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            out = structured(await client.call_tool("read_part", {"name": "widget"}))
            assert "PARAMS" in str(out["script"])
            assert str(out["content_hash"]).startswith("sha256:")

    run(scenario)


def test_invalid_arguments_are_rejected_against_the_canonical_schema(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            bad_pattern = await client.call_tool(
                "read_part", {"name": "Widget"}, raise_on_error=False
            )
            assert bad_pattern.is_error
            assert structured(bad_pattern)["reason"] == "invalid_params"
            unknown = await client.call_tool(
                "read_part", {"name": "widget", "bogus": 1}, raise_on_error=False
            )
            assert unknown.is_error
            assert structured(unknown)["reason"] == "invalid_params"

    run(scenario)


def test_orchestrator_only_tools_are_available_to_the_mcp_principal(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """A local MCP client is orchestrator-equivalent: project scope is allowed."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            out = structured(await client.call_tool("read_globals", {}))
            assert "SHELF_W" in str(out["script"])

    run(scenario)


# -- idempotency -----------------------------------------------------------


def test_same_id_same_payload_replays_the_recorded_result(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """A stock client sends no metadata: the key is MCP session + request id."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            args = {"name": "gadget", "template": "solid"}
            request_id = next_request_id(client)
            first = structured(await client.call_tool("create_part", args))

            rewind_request_id(client, request_id)
            replay = await client.call_tool("create_part", args)
            assert structured(replay) == first
            assert result_meta(replay).get("hephaestus.dev/replayed") is True

            listed = structured(await client.call_tool("list_parts", {}))
            names = [cast("dict[str, Any]", p)["name"] for p in cast("list[Any]", listed["parts"])]
            assert names.count("gadget") == 1

    run(scenario)


def test_same_id_different_payload_is_rejected(runtime: HephaestusMCP, project_root: Path) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            request_id = next_request_id(client)
            await client.call_tool("create_part", {"name": "gadget", "template": "solid"})

            rewind_request_id(client, request_id)
            out = await client.call_tool(
                "create_part", {"name": "other", "template": "solid"}, raise_on_error=False
            )
            assert out.is_error
            assert structured(out)["reason"] == "idempotency_key_reuse"

    run(scenario)


def test_defaults_do_not_change_the_payload_identity(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """Spelling a schema default explicitly still hashes as the same payload."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            request_id = next_request_id(client)
            first = structured(await client.call_tool("create_part", {"name": "gizmo"}))
            rewind_request_id(client, request_id)
            replay = await client.call_tool("create_part", {"name": "gizmo", "template": "blank"})
            assert not replay.is_error
            assert structured(replay) == first

    run(scenario)


def test_read_only_tools_are_freely_retryable(runtime: HephaestusMCP, project_root: Path) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            request_id = next_request_id(client)
            first = structured(await client.call_tool("read_part", {"name": "widget"}))
            rewind_request_id(client, request_id)
            again = await client.call_tool("read_part", {"name": "bracket"})
            assert not again.is_error
            assert structured(again)["script"] != first["script"]

    run(scenario)


# -- ask_user --------------------------------------------------------------


def test_ask_user_round_trips_through_elicitation(runtime: HephaestusMCP) -> None:
    async def handler(message: str, response_type: Any, params: Any, context: Any) -> Any:
        assert "chamfer" in message
        return ElicitResult(action="accept", content=response_type(value="chamfer"))

    async def scenario() -> None:
        async with Client(runtime.app, elicitation_handler=handler) as client:
            out = structured(
                await client.call_tool(
                    "ask_user",
                    {"question": "fillet or chamfer?", "options": ["fillet", "chamfer"]},
                )
            )
            assert out == {"selection": "chamfer"}

    run(scenario)


def test_ask_user_declined_is_a_discriminated_error(runtime: HephaestusMCP) -> None:
    async def handler(message: str, response_type: Any, params: Any, context: Any) -> Any:
        return ElicitResult(action="decline")

    async def scenario() -> None:
        async with Client(runtime.app, elicitation_handler=handler) as client:
            out = await client.call_tool(
                "ask_user", {"question": "q?", "options": ["a"]}, raise_on_error=False
            )
            assert out.is_error
            assert structured(out)["reason"] == "question_declined"

    run(scenario)


def test_ask_user_falls_back_to_structured_content_and_follow_up(
    runtime: HephaestusMCP,
) -> None:
    """No elicitation capability => documented fallback + the follow-up call."""

    async def scenario() -> None:
        async with Client(runtime.app) as client:
            pending = structured(
                await client.call_tool(
                    "ask_user",
                    {"question": "fillet or chamfer?", "options": ["fillet", "chamfer"]},
                )
            )
            assert pending["status"] == "question_pending"
            assert pending["reason"] == "elicitation_unsupported"
            follow_up = cast("dict[str, Any]", pending["follow_up"])
            assert follow_up["tool"] == "answer_question"
            question_id = cast("dict[str, Any]", follow_up["arguments"])["question_id"]

            answered = structured(
                await client.call_tool(
                    "answer_question", {"question_id": question_id, "selection": "fillet"}
                )
            )
            assert answered == {"selection": "fillet"}

            again = await client.call_tool(
                "answer_question",
                {"question_id": question_id, "selection": "fillet"},
                raise_on_error=False,
            )
            assert again.is_error
            assert structured(again)["reason"] == "unknown_question"

    run(scenario)


def test_fallback_answer_must_be_one_of_the_offered_options(runtime: HephaestusMCP) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            pending = structured(
                await client.call_tool(
                    "ask_user",
                    {"question": "which?", "options": ["a", "b"], "allow_free_text": False},
                )
            )
            arguments = cast(
                "dict[str, Any]", cast("dict[str, Any]", pending["follow_up"])["arguments"]
            )
            out = await client.call_tool(
                "answer_question",
                {"question_id": arguments["question_id"], "selection": "z"},
                raise_on_error=False,
            )
            assert out.is_error
            assert structured(out)["reason"] == "invalid_answer"

    run(scenario)


# -- executor policy -------------------------------------------------------


def test_serve_mode_refuses_the_unsafe_local_executor() -> None:
    """``heph serve`` never runs the unsafe backend — flag or no flag."""
    with pytest.raises(UnsafeRefusedError) as excinfo:
        HephaestusMCP(serve_mode=True, backend=UnsafeLocalBackend())
    assert excinfo.value.code == "unsafe_refused"


def test_serve_verb_is_registered_and_parses_both_transports() -> None:
    from hephaestus.core.cli import build_parser
    from hephaestus.mcp.cli_serve import parse_http_address

    args = build_parser().parse_args(["serve", "--mcp", "--http", "127.0.0.1:9123"])
    assert args.mcp is True
    assert parse_http_address(args.http) == ("127.0.0.1", 9123)
    assert parse_http_address("9123") == ("127.0.0.1", 9123)
    stdio = build_parser().parse_args(["serve", "--mcp"])
    assert stdio.http is None


def test_non_serve_runtime_keeps_the_unsafe_backend_for_tests() -> None:
    runtime = HephaestusMCP(backend=UnsafeLocalBackend())
    try:
        assert runtime.serve_mode is False
    finally:
        runtime.close()


# -- content shaping -------------------------------------------------------


def test_text_content_mirrors_the_structured_result(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    async def scenario() -> None:
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            out = await client.call_tool("read_part", {"name": "bracket"})
            blocks = [b for b in out.content if isinstance(b, TextContent)]
            assert blocks
            assert json.loads(blocks[0].text) == structured(out)
            assert not [b for b in out.content if isinstance(b, ImageContent)]

    run(scenario)


# -- explicit _meta key (tested separately from the derived-key contract) ---


def test_explicit_meta_key_is_honored(runtime: HephaestusMCP, project_root: Path) -> None:
    """A client needing cross-request reconciliation may pin the key in ``_meta``."""

    async def scenario() -> None:
        key = _fresh_uuid7()
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            args = {"name": "sprocket", "template": "solid"}
            first = structured(
                await client.call_tool("create_part", args, meta={IDEMPOTENCY_META_KEY: key})
            )
            # A *different* request id carrying the same explicit key still replays.
            replay = await client.call_tool("create_part", args, meta={IDEMPOTENCY_META_KEY: key})
            assert structured(replay) == first
            assert result_meta(replay).get("hephaestus.dev/replayed") is True

            conflict = await client.call_tool(
                "create_part",
                {"name": "sprocket2", "template": "solid"},
                meta={IDEMPOTENCY_META_KEY: key},
                raise_on_error=False,
            )
            assert conflict.is_error
            assert structured(conflict)["reason"] == "idempotency_key_reuse"

    run(scenario)


def test_stale_uuidv7_meta_key_fails_the_freshness_check(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """First-sight explicit UUIDv7 keys must be within five minutes of server time."""

    async def scenario() -> None:
        stale = "017f3c00-0000-7000-8000-00000000dead"  # a 2022 UUIDv7 timestamp
        async with Client(runtime.app) as client:
            await open_project(client, project_root)
            out = await client.call_tool(
                "create_part",
                {"name": "stale_part", "template": "solid"},
                meta={IDEMPOTENCY_META_KEY: stale},
                raise_on_error=False,
            )
            assert out.is_error
            assert structured(out)["reason"] == "key_timestamp_skew"

    run(scenario)


def _fresh_uuid7() -> str:
    """A UUIDv7 whose embedded timestamp is now (the freshness contract)."""
    import time
    import uuid

    millis = int(time.time() * 1000)
    value = (millis << 80) | (0x7 << 76) | (0x2 << 62) | 0x1234
    return str(uuid.UUID(int=value))
