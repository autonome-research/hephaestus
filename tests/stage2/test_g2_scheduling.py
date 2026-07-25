"""G2 tool scheduling: sequential mutations and ``ask_user`` isolation.

Gate clause: *"Tool scheduling tests prove interactive/mutating tools are
sequential; mixed ``ask_user``/mutation batches are preflighted in both source
orders, all siblings are blocked, and no mutation occurs before an answer."*

Pi executes tool calls in parallel by default, so both halves are asserted from
what **Python** observed: the recorder timestamps every ``py.tool_dispatch``
entry/exit, and the ``py.ask_user`` suspension is timestamped by the answerer.

* sequencing — two mutating calls emitted in one assistant message must reach
  the core one at a time (disjoint execution intervals), in source order;
* isolation — a batch mixing ``ask_user`` with a mutating sibling must block
  *every* sibling with ``ask_user_must_be_alone`` while the question proceeds,
  in **both** source orders, and no mutation may reach the core before the
  answer; the mutation is re-issued in a later turn.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from _g2 import G2Harness, RequestInfo, text, tool_call, tool_calls
from hephaestus.core import tools_decl

WIDGET = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

body = Box(p.w, 10.0, 4.0)
body.label = "body"
part.geometry = body
"""


def _plant(harness: G2Harness, *names: str) -> None:
    for name in names:
        (harness.project_root / "parts" / f"{name}.py").write_text(WIDGET, encoding="utf-8")


def test_mutating_tools_in_one_batch_are_executed_one_at_a_time(harness: G2Harness) -> None:
    """Two sequential-declared calls in one assistant message never overlap."""
    _plant(harness, "widget", "bracket")
    assert tools_decl.get_tool("build_part").sequential is True

    harness.set_script(
        [
            tool_calls(
                ("build_part", {"name": "widget"}, "call_0"),
                ("build_part", {"name": "bracket"}, "call_1"),
            ),
            text("both built"),
        ]
    )
    session_id = harness.create_session("orchestrator", session_id="g2-sequential")
    result = harness.prompt(session_id, "build both parts", timeout=1200)
    assert result.status == "completed"

    builds = harness.recorder.by_tool("build_part")
    assert len(builds) == 2, harness.recorder.tools()
    assert [record.arguments["name"] for record in builds] == ["widget", "bracket"]
    assert all(record.ok for record in builds)
    # Each build takes real time; sequential execution means disjoint intervals.
    first, second = builds
    assert first.done > first.at, "the first build was instantaneous; timing is not meaningful"
    assert second.at >= first.done, (
        "declared-sequential tools overlapped: "
        f"[{first.at:.3f}, {first.done:.3f}] vs [{second.at:.3f}, {second.done:.3f}]"
    )


@pytest.mark.parametrize("ask_first", [True, False], ids=["ask_user_first", "mutation_first"])
def test_ask_user_batch_blocks_every_sibling(harness: G2Harness, ask_first: bool) -> None:
    _plant(harness, "widget")
    question = (
        "ask_user",
        {"question": "Widen the widget?", "options": ["yes", "no"], "allow_free_text": False},
        "call_q",
    )
    mutation = (
        "edit_part",
        {
            "name": "widget",
            "expected_hash": "unknown-hash",
            "old_str": "20.0",
            "new_str": "30.0",
        },
        "call_m",
    )
    batch = tool_calls(question, mutation) if ask_first else tool_calls(mutation, question)

    seen: dict[str, Any] = {}
    answered_at: list[float] = []

    def answerer(params: dict[str, Any]) -> Any:
        answered_at.append(time.monotonic())
        return "yes"

    def after_batch(info: RequestInfo) -> dict[str, Any]:
        seen["body"] = info.body_text
        return text("acknowledged")

    harness.set_script([batch, after_batch])
    session_id = harness.create_session("orchestrator", session_id="g2-preflight")
    result = harness.prompt(session_id, "ask, then widen", answerer=answerer, timeout=600)
    assert result.status == "completed"

    # The question was asked…
    assert len(answered_at) == 1, "ask_user never suspended the run"
    # …and every sibling was blocked while it was open.
    body = str(seen["body"])
    assert "ask_user_must_be_alone" in body, (
        "the blocked sibling's result must name ask_user_must_be_alone"
    )
    mutations = harness.recorder.by_tool("edit_part")
    assert all(record.at > answered_at[0] for record in mutations), (
        "a mutation reached the core before the question was answered"
    )
    assert not any(record.ok for record in mutations), (
        "a blocked sibling must not mutate anything in the question's turn"
    )
    assert (harness.project_root / "parts" / "widget.py").read_text(encoding="utf-8") == WIDGET


def test_mutation_is_accepted_in_a_later_turn_after_the_answer(harness: G2Harness) -> None:
    """The sanctioned shape: question first, mutation in the turn after the answer."""
    _plant(harness, "widget")
    answered_at: list[float] = []

    def answerer(params: dict[str, Any]) -> Any:
        answered_at.append(time.monotonic())
        return "yes"

    def after_answer(info: RequestInfo) -> dict[str, Any]:
        from _g2 import last_tool_result

        assert last_tool_result(info)["selection"] == "yes"
        return tool_call("read_part", {"name": "widget"}, "call_r")

    def mutate(info: RequestInfo) -> dict[str, Any]:
        from _g2 import last_tool_result

        current = last_tool_result(info)
        return tool_call(
            "edit_part",
            {
                "name": "widget",
                "expected_hash": current["content_hash"],
                "old_str": "20.0",
                "new_str": "30.0",
            },
            "call_m",
        )

    harness.set_script(
        [
            tool_call(
                "ask_user",
                {"question": "Widen it?", "options": ["yes", "no"], "allow_free_text": False},
                "call_q",
            ),
            after_answer,
            mutate,
            text("widened"),
        ]
    )
    session_id = harness.create_session("orchestrator", session_id="g2-after-answer")
    result = harness.prompt(session_id, "confirm, then widen", answerer=answerer, timeout=600)
    assert result.status == "completed"

    edits = harness.recorder.by_tool("edit_part")
    assert len(edits) == 1 and edits[0].ok
    assert edits[0].at > answered_at[0], "the mutation must follow the answer"
    assert "30.0" in (harness.project_root / "parts" / "widget.py").read_text(encoding="utf-8")


def test_read_only_tools_are_not_declared_sequential() -> None:
    """Read-only render/measure stay parallel-capable (digest §1)."""
    for name in ("inspect_part", "measure", "read_part", "read_artifact", "list_skills"):
        assert tools_decl.get_tool(name).sequential is False
    for name in ("ask_user", "build_part", "edit_part", "set_params", "export_part"):
        assert tools_decl.get_tool(name).sequential is True
