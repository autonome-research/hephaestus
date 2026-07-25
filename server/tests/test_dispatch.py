"""Dispatch authz matrix + idempotent replay through the real opstore/project store."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.dispatch import (
    CAD_TOOLS,
    DELEGATION_TOOLS,
    MUTATION_TOOLS,
    NOT_IMPLEMENTED_TOOLS,
    REGISTRY_TOOLS,
    STORE_TOOLS,
    DispatchError,
    Principal,
    ToolDispatcher,
)
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.tools_decl import TOOLS_BY_NAME, tool_names
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


def test_registry_tools_are_typed_not_implemented_without_the_registry(
    dispatcher: ToolDispatcher,
) -> None:
    # This dispatcher has no RegistryOps wired; the family degrades to a typed
    # refusal instead of half-serving unpinned content. (test_dispatch_registry
    # covers the wired routes.)
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


def test_ask_user_never_routes_through_tool_dispatch(dispatcher: ToolDispatcher) -> None:
    # ask_user travels as its own bridge method (py.ask_user) so the run can
    # suspend on the human answer; reaching tool_dispatch is a wiring bug.
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(ORCH, _params("ask_user", {"question": "q", "options": ["a"]}))
    assert ei.value.reason == "not_implemented"


def test_mutation_set_matches_idempotent_flag() -> None:
    assert "create_part" in MUTATION_TOOLS
    assert "read_part" not in MUTATION_TOOLS
    assert "delegate_part_agent" in MUTATION_TOOLS


# -- tool-surface audit ----------------------------------------------------


def _committed_tool_names() -> set[str]:
    """Tool names as they appear in the committed canonical JSON Schemas."""
    schemas_dir = repo_root() / "schemas" / "tools"
    names: set[str] = set()
    for path in sorted(schemas_dir.glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        names.add(str(document["x-hephaestus-tool"]["name"]))
    return names


def test_committed_schemas_match_the_declaration() -> None:
    assert _committed_tool_names() == set(tool_names())


def test_every_declared_tool_has_exactly_one_dispatch_disposition() -> None:
    """The routing table covers the whole surface, with no tool in two families."""
    families = (STORE_TOOLS, CAD_TOOLS, REGISTRY_TOOLS, DELEGATION_TOOLS, NOT_IMPLEMENTED_TOOLS)
    covered: set[str] = set()
    for family in families:
        assert not (covered & family), covered & family
        covered |= family
    assert covered == _committed_tool_names()


def test_only_ask_user_never_routes_through_tool_dispatch() -> None:
    # ask_user is the one declared tool py.tool_dispatch deliberately never
    # serves: it travels as py.ask_user so the run can suspend on the answer.
    assert {"ask_user"} == NOT_IMPLEMENTED_TOOLS
    assert not (REGISTRY_TOOLS & NOT_IMPLEMENTED_TOOLS)


# -- authz matrix over the whole surface -----------------------------------

ORCHESTRATOR_ONLY: frozenset[str] = frozenset(
    name for name, decl in TOOLS_BY_NAME.items() if decl.profiles == ("orchestrator",)
)

#: Minimal schema-valid arguments per tool, used only to reach the authz gate.
_ARGS: dict[str, dict[str, object]] = {
    "create_part": {"name": "gusset"},
    "read_part": {"name": "widget"},
    "edit_part": {"name": "widget", "expected_hash": "h", "old_str": "a", "new_str": "b"},
    "write_part": {"name": "widget", "expected_hash": "h", "script": "x"},
    "build_part": {"name": "widget"},
    "set_params": {"values": {}, "expected_state_hash": "h", "name": "widget"},
    "read_globals": {},
    "edit_globals": {"expected_hash": "h", "old_str": "a", "new_str": "b"},
    "list_project_checks": {},
    "create_project_check": {"name": "fit"},
    "read_project_check": {"name": "fit"},
    "edit_project_check": {"name": "fit", "expected_hash": "h", "old_str": "a", "new_str": "b"},
    "inspect_part": {"name": "widget"},
    "query_snapshot": {"name": "widget", "question": "q"},
    "read_artifact": {"ref": "artifact:build:sha256:" + "0" * 64},
    "measure": {"kind": "bbox", "a": "part", "part": "widget"},
    "run_checks": {"name": "widget"},
    "load_skill": {"name": "booleans"},
    "list_skills": {},
    "search_parts_store": {"query": "m5"},
    "instance_store_part": {"id": "m5", "params": {}},
    "search_materials": {"query": "ply"},
    "delegate_part_agent": {"part": "widget", "prompt": "x"},
    "get_delegation_status": {"delegation_ref": "dg-1"},
    "cancel_delegation": {"delegation_ref": "dg-1"},
    "ask_user": {"question": "q", "options": ["a"]},
    "export_part": {"name": "widget", "format": "step"},
}


@pytest.mark.parametrize("tool", sorted(ORCHESTRATOR_ONLY))
@pytest.mark.parametrize("principal", [PART_WIDGET, QUICK_WIDGET])
def test_orchestrator_only_tools_deny_scoped_sessions(
    dispatcher: ToolDispatcher, tool: str, principal: Principal
) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatcher.dispatch(principal, _params(tool, dict(_ARGS[tool])))
    assert ei.value.reason == "scope_denied"


@pytest.mark.parametrize("tool", sorted(set(tool_names()) - ORCHESTRATOR_ONLY))
@pytest.mark.parametrize("principal", [PART_WIDGET, QUICK_WIDGET])
def test_scoped_sessions_reach_past_authz_for_their_own_part(
    dispatcher: ToolDispatcher, tool: str, principal: Principal
) -> None:
    """Availability, not success: the call must fail for a *routing* reason, if at all."""
    try:
        dispatcher.dispatch(principal, _params(tool, dict(_ARGS[tool])))
    except DispatchError as exc:
        assert exc.reason != "scope_denied", tool


def test_argument_matrix_covers_every_declared_tool() -> None:
    assert set(_ARGS) == set(tool_names())
