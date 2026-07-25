"""Dispatch authz matrix + idempotent replay through the real opstore/project store."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.dispatch import (
    MUTATION_TOOLS,
    REGISTRY_TOOLS,
    DispatchError,
    Principal,
    ToolDispatcher,
)
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from opstore.errors import KeyPayloadMismatchError


@pytest.fixture
def dispatcher(tmp_path: Path) -> Iterator[ToolDispatcher]:
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    (root / "globals.py").write_text("WALL = 2.0\n", encoding="utf-8")
    (root / "parts" / "widget.py").write_text("# widget\n", encoding="utf-8")
    (root / "parts" / "bracket.py").write_text("# bracket\n", encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    yield ToolDispatcher(ProjectStore(layout, store))
    store.close()


def _params(tool: str, args: dict[str, object], **inv: object) -> dict[str, object]:
    return {
        "session_id": "s1",
        "run_id": "r1",
        "tool": tool,
        "arguments": args,
        "invocation": {
            "session_id": "s1",
            "entry_id": "e1",
            "ordinal": 1,
            "provider_call_id": "c0",
            **inv,
        },
    }


ORCH = Principal(session_id="s1", profile="orchestrator", part=None)
PART_WIDGET = Principal(session_id="s2", profile="part", part="widget")
QUICK_WIDGET = Principal(session_id="s3", profile="quick_edit", part="widget")


# -- profile availability --------------------------------------------------


def test_part_session_cannot_delegate(dispatcher: ToolDispatcher) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(
            PART_WIDGET, _params("delegate_part_agent", {"part": "widget", "prompt": "x"})
        )
    assert ei.value.reason == "scope_denied"


def test_part_session_cannot_edit_globals(dispatcher: ToolDispatcher) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(
            PART_WIDGET,
            _params("edit_globals", {"expected_hash": "h", "old_str": "a", "new_str": "b"}),
        )
    assert ei.value.reason == "scope_denied"


def test_orchestrator_may_read_globals(dispatcher: ToolDispatcher) -> None:
    result = dispatcher.dispatch(ORCH, _params("read_globals", {}))
    assert result["script"] == "WALL = 2.0\n"


# -- object scope ----------------------------------------------------------


def test_part_session_cannot_read_foreign_part(dispatcher: ToolDispatcher) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(PART_WIDGET, _params("read_part", {"name": "bracket"}))
    assert ei.value.reason == "scope_denied"


def test_part_session_reads_own_part(dispatcher: ToolDispatcher) -> None:
    result = dispatcher.dispatch(PART_WIDGET, _params("read_part", {"name": "widget"}))
    assert result["script"] == "# widget\n"
    assert result["content_hash"].startswith("sha256:")


def test_quick_edit_cannot_address_foreign_part(dispatcher: ToolDispatcher) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(
            QUICK_WIDGET, _params("measure", {"kind": "bbox", "a": "x", "part": "bracket"})
        )
    assert ei.value.reason == "scope_denied"


def test_part_session_rejects_nameless_project_scope(dispatcher: ToolDispatcher) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(
            PART_WIDGET,
            _params("run_checks", {"scope": "project"}),
        )
    assert ei.value.reason == "scope_denied"


def test_orchestrator_addresses_any_part(dispatcher: ToolDispatcher) -> None:
    result = dispatcher.dispatch(ORCH, _params("read_part", {"name": "bracket"}))
    assert result["script"] == "# bracket\n"


# -- wired mutations + idempotent replay -----------------------------------


def test_create_part_then_idempotent_replay(dispatcher: ToolDispatcher) -> None:
    p = _params("create_part", {"name": "gusset", "template": "solid"})
    first = dispatcher.dispatch(ORCH, p)
    assert first["replayed"] is False
    assert first["content_hash"].startswith("sha256:")
    # same trusted invocation id + same payload -> recorded outcome replays
    second = dispatcher.dispatch(ORCH, p)
    assert second["replayed"] is True
    assert second["content_hash"] == first["content_hash"]


def test_same_invocation_different_payload_fails(dispatcher: ToolDispatcher) -> None:
    dispatcher.dispatch(ORCH, _params("create_part", {"name": "boss", "template": "blank"}))
    # reuse the SAME invocation id with a different payload (different template)
    with pytest.raises(KeyPayloadMismatchError):
        dispatcher.dispatch(ORCH, _params("create_part", {"name": "boss", "template": "solid"}))


def test_edit_part_cas_and_conflict(dispatcher: ToolDispatcher) -> None:
    read = dispatcher.dispatch(PART_WIDGET, _params("read_part", {"name": "widget"}))
    good = dispatcher.dispatch(
        PART_WIDGET,
        _params(
            "edit_part",
            {
                "name": "widget",
                "expected_hash": read["content_hash"],
                "old_str": "# widget\n",
                "new_str": "# widget v2\n",
            },
        ),
    )
    assert good["applied"] is True
    assert good["content_hash"] != read["content_hash"]
    # a stale expected_hash conflicts without mutating
    stale = dispatcher.dispatch(
        PART_WIDGET,
        _params(
            "edit_part",
            {
                "name": "widget",
                "expected_hash": read["content_hash"],
                "old_str": "# widget v2\n",
                "new_str": "# widget v3\n",
            },
            entry_id="e2",
        ),
    )
    assert stale["applied"] is False
    assert "conflict" in stale


def test_distinct_invocation_ids_across_entries_are_unique() -> None:
    from hephaestus.agent_bridge.dispatch import Invocation

    a = Invocation.from_params("sess", {"entry_id": "e1", "ordinal": 0, "provider_call_id": "c0"})
    b = Invocation.from_params("sess", {"entry_id": "e2", "ordinal": 0, "provider_call_id": "c0"})
    assert a.op_id != b.op_id  # repeated provider id, distinct entries


# -- stubs -----------------------------------------------------------------


def test_registry_tools_are_typed_not_implemented(dispatcher: ToolDispatcher) -> None:
    for tool in REGISTRY_TOOLS:
        args: dict[str, object] = {"name": "x"} if tool == "load_skill" else {"query": "q"}
        if tool == "list_skills":
            args = {}
        if tool == "instance_store_part":
            args = {"id": "i", "params": {}}
        with pytest.raises(DispatchError) as ei:
            dispatcher.dispatch(ORCH, _params(tool, args))
        assert ei.value.reason == "not_implemented"


def test_unknown_tool_rejected(dispatcher: ToolDispatcher) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(ORCH, _params("frobnicate", {}))
    assert ei.value.reason == "unknown_tool"


def test_mutation_set_matches_idempotent_flag() -> None:
    assert "create_part" in MUTATION_TOOLS
    assert "read_part" not in MUTATION_TOOLS
    assert "delegate_part_agent" in MUTATION_TOOLS
