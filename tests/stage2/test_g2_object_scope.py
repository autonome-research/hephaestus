"""G2 object scope: a bound session cannot escape its part, even by name.

Gate clause: *"Object-scope tests prove part/quick-edit sessions cannot read,
create, mutate, build, or parameterize another part even by supplying its name,
and reject nameless ``set_params(scope="project")`` / ``run_checks(scope=
"project")``"*, plus *"scope tests prove those project tools are absent from
part/quick-edit sessions."*

Two levels, because the gate needs both:

* **authz matrix** — every verb (read / create / mutate / build / parameterize /
  measure / render / export / check) against a *foreign* part id, for the part
  and quick-edit profiles, must be ``scope_denied``; the same verbs against the
  bound part must get past authz. Cross-part measurement selectors
  (``"<part>/<selector>"``) are denied too, and nameless project-scope
  ``set_params`` / ``run_checks`` are orchestrator-only.
* **model-visible surface** — through the real sidecar, a part session's model
  is never even offered the orchestrator families, and a denial reaches it as the
  stable ``scope_denied`` token rather than prose.
"""

from __future__ import annotations

from typing import Any

import pytest
from _g2 import PART_WIDGET, QUICK_WIDGET, G2Harness, Project, RequestInfo, text, tool_call
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core import tools_decl

BOUND = "widget"
FOREIGN = "bracket"

#: (verb, tool, arguments addressing the FOREIGN part).
FOREIGN_CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ("read", "read_part", {"name": FOREIGN}),
    ("create", "create_part", {"name": FOREIGN}),
    (
        "mutate",
        "edit_part",
        {"name": FOREIGN, "expected_hash": "deadbeef", "old_str": "a", "new_str": "b"},
    ),
    ("mutate", "write_part", {"name": FOREIGN, "expected_hash": "deadbeef", "script": "x = 1"}),
    ("build", "build_part", {"name": FOREIGN}),
    (
        "parameterize",
        "set_params",
        {"scope": "part", "name": FOREIGN, "values": {"w": 1.0}, "expected_state_hash": "h"},
    ),
    ("render", "inspect_part", {"name": FOREIGN}),
    ("measure", "measure", {"kind": "bbox", "a": "part", "part": FOREIGN}),
    ("measure", "measure", {"kind": "clearance", "a": f"{FOREIGN}/part", "b": "part"}),
    ("check", "run_checks", {"scope": "part", "name": FOREIGN}),
    ("export", "export_part", {"name": FOREIGN, "format": "stl"}),
    ("snapshot", "query_snapshot", {"name": FOREIGN, "question": "what is this?"}),
]

#: Orchestrator-only families a bound session must not reach at all.
PROJECT_ONLY_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("read_globals", {}),
    ("edit_globals", {"expected_hash": "h", "old_str": "a", "new_str": "b"}),
    ("list_project_checks", {}),
    ("create_project_check", {"name": "fit"}),
    ("read_project_check", {"name": "fit"}),
    ("edit_project_check", {"name": "fit", "expected_hash": "h", "old_str": "a", "new_str": "b"}),
    ("create_part", {"name": "another"}),
    ("delegate_part_agent", {"part": BOUND, "prompt": "do it"}),
    ("get_delegation_status", {"delegation_ref": "ref-1"}),
    ("cancel_delegation", {"delegation_ref": "ref-1"}),
]


@pytest.mark.parametrize("principal", [PART_WIDGET, QUICK_WIDGET], ids=["part", "quick_edit"])
@pytest.mark.parametrize(
    ("verb", "tool", "arguments"),
    FOREIGN_CALLS,
    ids=[f"{verb}-{tool}" for verb, tool, _ in FOREIGN_CALLS],
)
def test_bound_session_cannot_address_a_foreign_part(
    project: Project, principal: Any, verb: str, tool: str, arguments: dict[str, Any]
) -> None:
    with pytest.raises(DispatchError) as exc:
        project.call(tool, arguments, principal=principal)
    assert exc.value.reason == "scope_denied", (verb, tool)
    # The refusal names either the foreign object or the unavailable tool
    # (``create_part`` is denied one layer earlier, by profile availability).
    assert FOREIGN in str(exc.value) or tool in str(exc.value)


@pytest.mark.parametrize("principal", [PART_WIDGET, QUICK_WIDGET], ids=["part", "quick_edit"])
@pytest.mark.parametrize(
    ("tool", "arguments"), PROJECT_ONLY_CALLS, ids=[tool for tool, _ in PROJECT_ONLY_CALLS]
)
def test_project_only_tools_are_absent_from_bound_sessions(
    project: Project, principal: Any, tool: str, arguments: dict[str, Any]
) -> None:
    with pytest.raises(DispatchError) as exc:
        project.call(tool, arguments, principal=principal)
    assert exc.value.reason == "scope_denied", tool
    assert tool in str(exc.value)


@pytest.mark.parametrize("principal", [PART_WIDGET, QUICK_WIDGET], ids=["part", "quick_edit"])
def test_nameless_project_scope_is_rejected(project: Project, principal: Any) -> None:
    for tool, arguments in (
        ("set_params", {"scope": "project", "values": {"wall": 3.0}, "expected_state_hash": "h"}),
        ("run_checks", {"scope": "project"}),
    ):
        with pytest.raises(DispatchError) as exc:
            project.call(tool, arguments, principal=principal)
        assert exc.value.reason == "scope_denied", tool
        assert "project" in str(exc.value)


@pytest.mark.parametrize("principal", [PART_WIDGET, QUICK_WIDGET], ids=["part", "quick_edit"])
def test_bound_session_reaches_its_own_part(project: Project, principal: Any) -> None:
    """Positive control: the same verbs on the bound part are never scope_denied."""
    own_calls = [
        (tool, {**arguments, **({"name": BOUND} if "name" in arguments else {})})
        for _verb, tool, arguments in FOREIGN_CALLS
        if tool not in {"create_part", "measure"}
    ]
    own_calls.append(("measure", {"kind": "bbox", "a": "part", "part": BOUND}))
    own_calls.append(("run_checks", {"scope": "part"}))  # name defaults to the bound part
    for tool, arguments in own_calls:
        try:
            project.call(tool, arguments, principal=principal)
        except DispatchError as exc:
            assert exc.reason != "scope_denied", (tool, arguments)
        except Exception:
            pass


def test_registry_skill_name_is_not_a_part_name(project: Project) -> None:
    """``load_skill(name=…)`` names a skill; the bound part must not constrain it."""
    try:
        project.call("load_skill", {"name": "build123d-idioms"}, principal=PART_WIDGET)
    except DispatchError as exc:
        assert exc.reason != "scope_denied"


# --------------------------------------------------------------------------
# through the real bridge


def test_part_session_model_never_sees_the_project_families(harness: G2Harness) -> None:
    """The model's own tool list is the profile allowlist — no orchestrator tools."""
    offered: dict[str, list[str]] = {}

    def capture(profile: str) -> Any:
        def turn(info: RequestInfo) -> dict[str, Any]:
            offered[profile] = sorted(info.tool_names)
            return text(f"{profile} ready")

        return turn

    part_session = harness.create_session("part", part="widget", session_id="g2-scope-part")
    harness.set_script([capture("part")])
    harness.prompt(part_session, "introduce yourself", timeout=300)

    quick_session = harness.create_session("quick_edit", part="widget", session_id="g2-scope-quick")
    harness.set_script([capture("quick_edit")])
    harness.prompt(quick_session, "introduce yourself", timeout=300)

    orchestrator = harness.create_session("orchestrator", session_id="g2-scope-orch")
    harness.set_script([capture("orchestrator")])
    harness.prompt(orchestrator, "introduce yourself", timeout=300)

    for profile in ("part", "quick_edit", "orchestrator"):
        expected = sorted(
            name
            for name in tools_decl.tool_names()
            if profile in tools_decl.get_tool(name).profiles
        )
        assert offered[profile] == expected, profile

    project_only = {tool for tool, _ in PROJECT_ONLY_CALLS}
    assert project_only.isdisjoint(offered["part"])
    assert project_only.isdisjoint(offered["quick_edit"])
    assert project_only <= set(offered["orchestrator"])
    # No Pi built-in coding tool leaked into any profile.
    for names in offered.values():
        assert not ({"bash", "read", "edit", "write", "shell", "glob", "grep"} & set(names))


def test_scope_denial_reaches_the_model_as_a_stable_token(harness: G2Harness) -> None:
    """A cross-part read is refused by Python authz, not by the model's manners."""
    (harness.project_root / "parts" / "bracket.py").write_text(
        "part.geometry = Box(1.0, 1.0, 1.0)\n", encoding="utf-8"
    )
    seen: dict[str, Any] = {}

    def after_denial(info: RequestInfo) -> dict[str, Any]:
        seen["body"] = info.body_text
        return text("denied" if "scope_denied" in info.body_text else "not-denied")

    harness.set_script([tool_call("read_part", {"name": "bracket"}, "call_0"), after_denial])
    session_id = harness.create_session("part", part="widget", session_id="g2-scope-denial")
    result = harness.prompt(session_id, "read the bracket part", timeout=300)

    assert result.status == "completed"
    record = harness.recorder.first("read_part")
    assert record.ok is False and record.reason == "scope_denied"
    assert "scope_denied" in str(seen["body"])
