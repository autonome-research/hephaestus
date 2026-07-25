"""G2: a fresh project, completed end to end with only model-visible tools.

Gate clause: *"A fresh-project scripted session uses only model-visible tools to
edit shared globals, create two consuming parts, discover/create/edit a
persistent cross-part check, and delegate work."*

The session starts against a bare ``heph init``-shaped project (manifest, empty
``globals.py``, empty ``parts/`` and ``checks/``) and does everything through the
tool surface the model is actually offered — no fixture writes files behind its
back, and nothing but the advertised tools is used:

    read_globals -> edit_globals (shared params + a shared constant)
      -> create_part/write_part/build_part  x2, both consuming those globals
      -> list_project_checks (discovery) -> create_project_check
      -> read_project_check -> edit_project_check (a real cross-part predicate)
      -> run_checks(scope="project") over the frozen check set
      -> delegate_part_agent to one of the parts

Then the on-disk state is asserted directly: both part scripts, the edited
globals, the check file under ``checks/``, both builds current, and the project
check report naming the authored predicate.
"""

from __future__ import annotations

from typing import Any, cast

from _g2 import (
    G2Harness,
    RequestInfo,
    assert_stream_shape,
    called_tools,
    last_tool_result,
    text,
    tool_call,
)

GLOBALS_NEW = """PARAMS = {
    "wall": Param(3.0, min=1.0, max=10.0),
}

SHELF_W = 120.0"""

SHELF = """PARAMS = {
    "depth": Param(60.0, min=20.0, max=200.0),
}

body = Box(hc.SHELF_W, p.depth, hc.wall)
body.label = "shelf_body"
part.geometry = body
"""

GUSSET = """PARAMS = {
    "rise": Param(40.0, min=10.0, max=100.0),
}

body = Box(hc.wall, 30.0, p.rise)
body.label = "gusset_body"
part.geometry = body
"""

CROSS_PART_CHECK = '"shelf_is_wide": lambda m: m.bbox("shelf/part")[0] >= 100.0,'


def test_fresh_project_scripted_session(harness: G2Harness) -> None:
    seen: dict[str, Any] = {}
    offered: list[str] = []
    steps: list[Any] = []

    def remember(key: str) -> Any:
        def turn(info: RequestInfo) -> dict[str, Any]:
            if not offered:
                offered.extend(sorted(info.tool_names))
            seen[key] = last_tool_result(info)
            return steps[len(seen) - 1](info)

        return turn

    # Each entry consumes the previous result and issues the next call.
    steps = [
        lambda info: tool_call(
            "edit_globals",
            {
                "expected_hash": seen["read_globals"]["content_hash"],
                "old_str": "PARAMS = {}",
                "new_str": GLOBALS_NEW,
            },
            "call_0",
        ),
        lambda info: tool_call("create_part", {"name": "shelf", "template": "blank"}, "call_0"),
        lambda info: tool_call(
            "write_part",
            {
                "name": "shelf",
                "expected_hash": seen["create_shelf"]["content_hash"],
                "script": SHELF,
            },
            "call_0",
        ),
        lambda info: tool_call("build_part", {"name": "shelf"}, "call_0"),
        lambda info: tool_call("create_part", {"name": "gusset", "template": "blank"}, "call_0"),
        lambda info: tool_call(
            "write_part",
            {
                "name": "gusset",
                "expected_hash": seen["create_gusset"]["content_hash"],
                "script": GUSSET,
            },
            "call_0",
        ),
        lambda info: tool_call("build_part", {"name": "gusset"}, "call_0"),
        lambda info: tool_call("list_project_checks", {}, "call_0"),
        lambda info: tool_call(
            "create_project_check",
            {"name": "assembly_fit", "description": "shelf and gusset agree"},
            "call_0",
        ),
        lambda info: tool_call("read_project_check", {"name": "assembly_fit"}, "call_0"),
        lambda info: tool_call(
            "edit_project_check",
            {
                "name": "assembly_fit",
                "expected_hash": seen["read_check"]["content_hash"],
                "old_str": '"placeholder": lambda m: True,',
                "new_str": CROSS_PART_CHECK,
            },
            "call_0",
        ),
        lambda info: tool_call("run_checks", {"scope": "project"}, "call_0"),
        lambda info: tool_call(
            "delegate_part_agent",
            {"part": "gusset", "prompt": "raise the gusset to 50 mm", "delivery": "prompt"},
            "call_0",
        ),
        lambda info: text("PROJECT READY"),
    ]

    keys = [
        "read_globals",
        "edit_globals",
        "create_shelf",
        "write_shelf",
        "build_shelf",
        "create_gusset",
        "write_gusset",
        "build_gusset",
        "list_checks",
        "create_check",
        "read_check",
        "edit_check",
        "project_checks",
        "delegated",
    ]

    harness.set_script([tool_call("read_globals", {}, "call_0"), *[remember(key) for key in keys]])
    session_id = harness.create_session("orchestrator", session_id="g2-fresh")
    result = harness.prompt(session_id, "set up the shelf project from scratch", timeout=1800)

    assert result.status == "completed"
    assert_stream_shape(result)

    # -- only model-visible tools were used --------------------------------
    used = called_tools(result)
    unoffered = set(used) - set(offered)
    assert not unoffered, f"used tools the model was never offered: {unoffered}"
    assert used == [
        "read_globals",
        "edit_globals",
        "create_part",
        "write_part",
        "build_part",
        "create_part",
        "write_part",
        "build_part",
        "list_project_checks",
        "create_project_check",
        "read_project_check",
        "edit_project_check",
        "run_checks",
        "delegate_part_agent",
    ]

    # -- shared globals were edited through the tool ------------------------
    assert seen["edit_globals"]["status"] == "applied"
    globals_text = (harness.project_root / "globals.py").read_text(encoding="utf-8")
    assert '"wall": Param(3.0' in globals_text and "SHELF_W = 120.0" in globals_text

    # -- two parts, both consuming those globals, both built current --------
    for name, source in (("shelf", SHELF), ("gusset", GUSSET)):
        path = harness.project_root / "parts" / f"{name}.py"
        assert path.read_text(encoding="utf-8") == source
        assert "hc." in source
    for key in ("build_shelf", "build_gusset"):
        build = cast("dict[str, Any]", seen[key])
        assert build["status"] == "ok", build
        assert build["current"] is True
        assert build["artifact_ref"].startswith("artifact:build:")
    # The shelf really used the shared constant (120 mm wide).
    assert seen["build_shelf"]["effective_params"]["depth"] == 60.0

    # -- discovery -> create -> edit of a persistent cross-part check -------
    discovery = cast("dict[str, Any]", seen["list_checks"])
    assert discovery["status"] == "ok"
    assert discovery["items"] == [], "a fresh project starts with no project checks"
    assert seen["create_check"]["path"].endswith("checks/assembly_fit.py")
    check_file = harness.project_root / "checks" / "assembly_fit.py"
    assert check_file.exists()
    assert seen["edit_check"]["status"] == "applied"
    assert "shelf_is_wide" in check_file.read_text(encoding="utf-8")

    # …and it is a persistent check: the project run executes it by name.
    report = cast("dict[str, Any]", seen["project_checks"])
    assert report["status"] == "ok" and report["scope"] == "project"
    assert report["checks"]["assembly_fit:shelf_is_wide"]["pass"] is True
    assert report["check_set_ref"].startswith("artifact:check-bundle:")
    assert report["project_snapshot_ref"].startswith("artifact:project-snapshot:")

    # -- work handed to a part session, with child terminal evidence --------
    delegated = cast("dict[str, Any]", seen["delegated"])
    assert delegated["status"] == "completed"
    assert delegated["part_session_id"] == "part:gusset"
    assert delegated["result_artifact_ref"]

    # -- nothing bypassed authz: every dispatch was the orchestrator's ------
    assert {record.session_id for record in harness.recorder.calls} == {session_id}
    assert all(record.ok for record in harness.recorder.calls)
