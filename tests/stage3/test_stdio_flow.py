"""Gate G3, stdio: a stock MCP client drives the whole flow over ``heph serve --mcp``.

The gate clause this file discharges:

    a scripted MCP client (no Hephaestus code on the client side) connects over
    stdio, opens a public clean-room fixture project, and completes create ->
    edit -> build -> inspect (receives images) -> measure -> export STEP; the
    exported STEP re-imports with matching volume.

The server is a *subprocess* — ``uv run heph serve --mcp``, the command a user
configures in an MCP client — launched by the official ``mcp`` SDK's stdio
transport. The client side imports only the SDK (plus OCP for the re-import
check); :func:`test_stdio_client_modules_import_no_hephaestus` enforces that
mechanically over the four scripted-client modules, rather than by convention.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import pytest
from _stock_client import (
    PLATE_VOLUME_MM3,
    RawStdioClient,
    ask_user_round_trip,
    elicitation_answerer,
    fixture_project,
    raw_structured,
    run_flow,
    stdio_client_for,
    step_solid_count_and_volume,
)

#: G3's exact clause: the re-imported volume matches within 1e-3 relative.
VOLUME_RTOL = 1e-3


def test_stdio_full_flow_exports_a_step_that_reimports_with_matching_volume(
    tmp_path: Path,
) -> None:
    """create -> edit -> build -> inspect -> measure -> export, then OCP re-import."""
    root = fixture_project(tmp_path)

    async def scenario() -> None:
        async with stdio_client_for() as session:
            outcome = await run_flow(session, root)

        assert outcome.image_count >= 1
        assert set(outcome.image_mime_types) == {"image/png"}
        assert all(ref.startswith("artifact:render:") for ref in outcome.render_artifact_refs)
        assert outcome.measured_units == "mm^3"
        assert outcome.measured_volume == pytest.approx(PLATE_VOLUME_MM3, rel=1e-9)

        exported = [root / path for path in outcome.export_paths]
        step_files = [path for path in exported if path.suffix == ".step"]
        assert step_files, outcome.export_paths
        for path in step_files:
            assert path.is_file(), path

        # The gate's exact clause: OCCT re-reads the bytes the exporter wrote.
        solids, volume = step_solid_count_and_volume(step_files[0])
        assert solids == 1, f"expected one solid in the STEP, got {solids}"
        assert abs(volume - outcome.measured_volume) <= VOLUME_RTOL * outcome.measured_volume

    asyncio.run(scenario())


def test_stdio_ask_user_round_trips_through_mcp_elicitation() -> None:
    """``ask_user`` maps to MCP elicitation; a scripted client answers mid-call."""
    seen: dict[str, Any] = {}

    async def scenario() -> None:
        async with stdio_client_for(elicitation_answerer("chamfer", seen)) as session:
            answered = await ask_user_round_trip(session, seen)
        assert answered == {"selection": "chamfer"}
        assert "chamfer" in str(seen["message"])

    asyncio.run(scenario())


def test_stdio_ask_user_falls_back_when_the_client_cannot_elicit() -> None:
    """A client without the elicitation capability gets the documented fallback.

    ``tool_schema.md`` §ask_user's fallback is structured content plus a named
    follow-up call; the raw client advertises no capabilities, so this is the
    path a pre-elicitation MCP client actually takes.
    """
    with RawStdioClient() as client:
        client.initialize()
        pending = raw_structured(
            client.call_tool(
                "ask_user", {"question": "fillet or chamfer?", "options": ["fillet", "chamfer"]}, 10
            )
        )
        assert pending["status"] == "question_pending"
        assert pending["reason"] == "elicitation_unsupported"
        follow_up: dict[str, Any] = dict(pending["follow_up"])
        assert follow_up["tool"] == "answer_question"
        question_id = dict(follow_up["arguments"])["question_id"]

        answered = raw_structured(
            client.call_tool(
                "answer_question", {"question_id": question_id, "selection": "chamfer"}, 11
            )
        )
        assert answered == {"selection": "chamfer"}


#: The scripted-client modules: the ones whose whole point is having no
#: Hephaestus code on the client side. (``test_parity`` deliberately imports the
#: bridge and the MCP app in-process — it compares the two surfaces, so it is a
#: different kind of test and is not covered by this rule.)
CLIENT_MODULES = (
    "_stock_client.py",
    "test_stdio_flow.py",
    "test_http_flow.py",
    "test_idempotency.py",
)


def test_stdio_client_modules_import_no_hephaestus() -> None:
    """Structural enforcement: no scripted-client module may import ``hephaestus``.

    The gate's claim is about a client with no Hephaestus code on its side, so
    an accidental helper import would silently void it. Parsing the modules is
    stronger than inspecting ``sys.modules`` (the server subprocess imports the
    package by design, and pytest plugins may drag in anything).
    """
    here = Path(__file__).resolve().parent
    modules = [here / name for name in CLIENT_MODULES]
    for module in modules:
        assert module.is_file(), module
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module)
        offenders = sorted(
            name for name in imported if name == "hephaestus" or name.startswith("hephaestus.")
        )
        assert not offenders, f"{module.name} imports Hephaestus code: {offenders}"
