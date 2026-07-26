"""G2: a scripted fake model drives EVERY generated tool through the real bridge.

Gate clause: *"Tests use a scripted fake model to drive every generated Pi custom
tool through the real Node/Python bridge, including images, ``ask_user`` …"*.

One orchestrator session, one prompt, one chain of 30 turns — every tool in
``tools_decl`` is called exactly once, in a dependency-respecting order, with the
arguments built from the *previous* tool's real result (hashes, refs, ids). The
model never sees a stub: each call travels model -> Pi loop -> ToolProxy (TypeBox
validation + trusted invocation) -> ``py.tool_dispatch``/``py.delegate``/
``py.ask_user`` -> ``hephaestus.core`` and back through result validation.

Coverage the gate names explicitly and this chain exercises:

* **images** — ``inspect_part`` renders ride back inline as public ``image``
  events and as image content blocks in the model request;
* **ask_user** — a real suspension answered by a scripted answerer;
* **registry family** — skills/materials/parts-store served from the hash-pinned
  ``registries/`` tree, with skill text inside provenance delimiters;
* **delegation family** — ``delegate_part_agent`` over ``py.delegate`` with a
  durable child terminal, then ``get_delegation_status`` / ``cancel_delegation``;
* **export** — a frozen source artifact with source/export hashes on disk.

The per-tool *semantics* are covered by the package-local suites; what this file
adds is the end-to-end proof that the full declared surface is reachable through
the packaged sidecar with schema-valid arguments and schema-valid results.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from _g2 import (
    G2Harness,
    RequestInfo,
    assert_stream_shape,
    called_tools,
    events_of,
    last_tool_result,
    payload_of,
    text,
    tool_call,
)
from hephaestus.core import tools_decl

WIDGET_SCRIPT = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, 6.0)
body.label = "widget_body"
part.geometry = body
part.description = "G2 surface widget"

CHECKS = {
    "wide_enough": lambda m: m.bbox("part")[0] >= 10.0,
}
"""

#: (tool, build-arguments-from-what-we-have-seen). Order is dependency order.
Step = tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]


def _steps() -> list[Step]:
    def seen_get(seen: dict[str, Any], tool: str, key: str, default: Any = None) -> Any:
        result = cast("dict[str, Any]", seen.get(tool) or {})
        return result.get(key, default)

    return [
        # -- registry (contextual + executable) ----------------------------
        ("list_skills", lambda seen: {}),
        ("load_skill", lambda seen: {"name": "build123d-idioms", "limit_lines": 40}),
        ("search_materials", lambda seen: {"query": "plywood"}),
        ("search_parts_store", lambda seen: {"query": "screw", "max_results": 3}),
        (
            "instance_store_part",
            lambda seen: {
                "id": str(cast("list[Any]", seen["search_parts_store"])[0]["id"]),
                "params": {},
            },
        ),
        # -- authoring -----------------------------------------------------
        ("create_part", lambda seen: {"name": "widget", "template": "blank"}),
        (
            "write_part",
            lambda seen: {
                "name": "widget",
                "expected_hash": seen_get(seen, "create_part", "content_hash"),
                "script": WIDGET_SCRIPT,
            },
        ),
        ("read_part", lambda seen: {"name": "widget"}),
        (
            "edit_part",
            lambda seen: {
                "name": "widget",
                "expected_hash": seen_get(seen, "read_part", "content_hash"),
                "old_str": "G2 surface widget",
                "new_str": "G2 surface widget (edited)",
            },
        ),
        # -- project globals ------------------------------------------------
        ("read_globals", lambda seen: {}),
        (
            "edit_globals",
            lambda seen: {
                "expected_hash": seen_get(seen, "read_globals", "content_hash"),
                "old_str": "PARAMS = {}",
                "new_str": "PARAMS = {}\n\nSHELF_W = 100.0",
            },
        ),
        # -- requirement ledger (VALIDATION.md §2, before any geometry) ------
        (
            "record_requirements",
            lambda seen: {
                "entries": [
                    {
                        "id": "R1",
                        "text": "widget is 40 mm wide in X",
                        "source": "specified",
                        "quote": "exercise the whole tool surface",
                        "value": 40.0,
                        "unit": "mm",
                        "applies_to": "widget",
                    },
                    {
                        "id": "R2",
                        "text": "widget stays at least 10 mm wide",
                        "source": "derived",
                        "from": ["R1"],
                        "value": 10.0,
                        "unit": "mm",
                        "applies_to": "widget",
                    },
                ]
            },
        ),
        ("read_requirements", lambda seen: {}),
        (
            "update_requirement",
            lambda seen: {"id": "R1", "value": 44.0, "text": "widget is 44 mm wide in X"},
        ),
        # -- parameters + geometry -----------------------------------------
        (
            "set_params",
            lambda seen: {
                "scope": "part",
                "name": "widget",
                "values": {"width": 44.0},
                "expected_state_hash": seen_get(seen, "read_part", "part_param_state_hash"),
            },
        ),
        ("build_part", lambda seen: {"name": "widget"}),
        ("inspect_part", lambda seen: {"name": "widget", "views": ["iso"]}),
        ("measure", lambda seen: {"kind": "bbox", "a": "part", "part": "widget"}),
        ("run_checks", lambda seen: {"scope": "part", "name": "widget"}),
        (
            "read_artifact",
            lambda seen: {
                "ref": seen_get(seen, "build_part", "artifact_ref"),
                "max_bytes": 4096,
            },
        ),
        ("export_part", lambda seen: {"name": "widget", "format": "stl"}),
        ("run_dfm", lambda seen: {"name": "widget", "process": "laser_cut"}),
        ("generate_drawing", lambda seen: {"name": "widget", "kind": "dimensioned"}),
        ("generate_doc", lambda seen: {"name": "widget", "kind": "bom"}),
        (
            "query_snapshot",
            lambda seen: {"name": "widget", "question": "does the widget look square?"},
        ),
        # -- project checks -------------------------------------------------
        ("list_project_checks", lambda seen: {}),
        (
            "create_project_check",
            lambda seen: {"name": "cross_part_fit", "description": "widget stays wide"},
        ),
        ("read_project_check", lambda seen: {"name": "cross_part_fit"}),
        (
            "edit_project_check",
            lambda seen: {
                "name": "cross_part_fit",
                "expected_hash": seen_get(seen, "read_project_check", "content_hash"),
                "old_str": '"placeholder": lambda m: True,',
                "new_str": '"widget_wide": lambda m: m.bbox("widget/part")[0] >= 10.0,',
            },
        ),
        # -- delegation -----------------------------------------------------
        (
            "delegate_part_agent",
            lambda seen: {
                "part": "widget",
                "prompt": "tighten the widget fillets",
                "delivery": "prompt",
                "deadline_seconds": 60,
            },
        ),
        (
            "get_delegation_status",
            lambda seen: {
                "delegation_ref": seen_get(seen, "delegate_part_agent", "delegation_ref")
            },
        ),
        (
            "cancel_delegation",
            lambda seen: {
                "delegation_ref": seen_get(seen, "delegate_part_agent", "delegation_ref")
            },
        ),
        # -- interaction ----------------------------------------------------
        (
            "ask_user",
            lambda seen: {
                "question": "Ship it?",
                "options": ["yes", "no"],
                "allow_free_text": False,
            },
        ),
    ]


class Chain:
    """Drives the step list, feeding each tool the previous tool's real result."""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = steps
        self.index = 0
        self.seen: dict[str, Any] = {}
        self.failure: str | None = None

    def __call__(self, info: RequestInfo) -> dict[str, Any]:
        if self.index > 0:
            result = last_tool_result(info)
            # Array-valued results (the registry search tools) arrive wrapped.
            unwrapped = result["_value"] if set(result) == {"_value"} else result
            self.seen[self.steps[self.index - 1][0]] = unwrapped
        if self.index >= len(self.steps):
            return text("SURFACE COMPLETE")
        name, build = self.steps[self.index]
        self.index += 1
        try:
            arguments = build(self.seen)
        except Exception as exc:
            self.failure = f"{name}: could not build arguments from prior results: {exc!r}"
            return text("SURFACE ABORTED")
        return tool_call(name, arguments, f"call_{self.index}")


@pytest.fixture
def surface(tmp_path: Any, sidecar_dist: Any) -> Any:
    from _g2 import scaffold_project

    # The chain records its own ledger and asserts its generations, so the
    # project must start with none (VALIDATION.md §2).
    project = scaffold_project(tmp_path / "surface", seed_ledger=False)
    harness = G2Harness(project, sidecar_dist, snapshot=True, sandbox=True)
    try:
        yield harness
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_every_generated_tool_flows_through_the_real_bridge(surface: G2Harness) -> None:
    steps = _steps()
    assert [name for name, _ in steps] != [], "no steps"
    # The chain must cover the declared surface exactly once.
    assert sorted(name for name, _ in steps) == sorted(tools_decl.tool_names())

    chain = Chain(steps)
    surface.set_script([chain] * (len(steps) + 1))

    answered: list[dict[str, Any]] = []

    def answerer(params: dict[str, Any]) -> Any:
        answered.append(params)
        return "yes"

    session_id = surface.create_session("orchestrator", session_id="g2-surface")
    result = surface.prompt(
        session_id, "exercise the whole tool surface", answerer=answerer, timeout=1800
    )

    assert chain.failure is None, chain.failure
    assert result.status == "completed"
    assert_stream_shape(result)

    seen = chain.seen
    # Every tool produced a result the proxy accepted against its result schema.
    assert set(seen) == set(tools_decl.tool_names()), (
        f"tools without a result: {set(tools_decl.tool_names()) - set(seen)}"
    )

    # -- the public narrative lists every tool once, in order ---------------
    narrative = called_tools(result)
    assert narrative == [name for name, _ in steps]

    # -- registry: contextual content is provenance-delimited ---------------
    skills = cast("list[Any]", seen["list_skills"])
    assert {entry["name"] for entry in skills} >= {"build123d-idioms", "sheet-goods-and-joinery"}
    skill = cast("dict[str, Any]", seen["load_skill"])
    assert "BEGIN REFERENCE" in skill["content"] or "REFERENCE" in skill["content"]
    assert skill["artifact_ref"].startswith("artifact:")
    materials = cast("list[Any]", seen["search_materials"])
    assert any("plywood" in str(entry["id"]) for entry in materials)
    store = cast("list[Any]", seen["search_parts_store"])
    assert store and {"id", "name", "params"} <= set(store[0])
    instanced = cast("dict[str, Any]", seen["instance_store_part"])
    # With a probed sandbox the generator really runs; without one the tool is a
    # discriminated capability_error — never a quiet unsandboxed execution.
    assert "script_fragment" in instanced or instanced.get("code") == "capability_not_available"

    # -- authoring: CAS hashes chained through the real store ---------------
    assert seen["write_part"]["applied"] is True
    assert seen["edit_part"]["applied"] is True
    script_path = surface.project_root / "parts" / "widget.py"
    assert "(edited)" in script_path.read_text(encoding="utf-8")
    assert seen["edit_globals"]["status"] == "applied"
    assert "SHELF_W" in (surface.project_root / "globals.py").read_text(encoding="utf-8")

    # -- requirement ledger: immutable generations, no open assumptions ------
    recorded = cast("dict[str, Any]", seen["record_requirements"])
    assert recorded["status"] == "ok" and recorded["generation"] == 1
    assert recorded["artifact_ref"].startswith("artifact:requirements:")
    assert [entry["id"] for entry in cast("list[Any]", recorded["entries"])] == ["R1", "R2"]
    read_back = cast("dict[str, Any]", seen["read_requirements"])
    assert read_back["artifact_ref"] == recorded["artifact_ref"]
    updated = cast("dict[str, Any]", seen["update_requirement"])
    assert updated["generation"] == 2
    assert updated["artifact_ref"] != recorded["artifact_ref"]
    assert cast("list[Any]", updated["entries"])[0]["value"] == 44.0
    # Nothing here is an assumption, so the §3 gate has nothing to block on.
    assert updated["unresolved_material"] == []

    # -- parameters + geometry ---------------------------------------------
    assert seen["set_params"]["effective"]["width"] == 44.0
    build = cast("dict[str, Any]", seen["build_part"])
    assert build["status"] == "ok" and build["current"] is True
    assert build["artifact_ref"].startswith("artifact:build:")
    inspect = cast("dict[str, Any]", seen["inspect_part"])
    assert inspect["status"] == "ok" and inspect["render_artifact_refs"]
    images = events_of(result, "image")
    assert images, "inspect_part must stream at least one public image event"
    assert payload_of(images[0])["mimeType"] == "image/png"
    assert seen["measure"]["units"] == "mm"
    assert seen["run_checks"]["checks"]["wide_enough"]["pass"] is True
    assert seen["read_artifact"]["total_bytes"] > 0

    # -- export: frozen source + hashed bytes on disk -----------------------
    export = cast("dict[str, Any]", seen["export_part"])
    assert export["source_artifact_ref"] == build["artifact_ref"]
    assert export["paths"] and export["export_hashes"]
    for path in cast("list[str]", export["paths"]):
        assert (surface.project_root / path).exists() or path.startswith("/")

    # -- documents: both files exported, dimensions in the result -----------
    drawing = cast("dict[str, Any]", seen["generate_drawing"])
    assert drawing["source_artifact_ref"] == build["artifact_ref"]
    assert drawing["paths"] == [drawing["pdf"], drawing["svg"]]
    assert any(dimension["text"] for dimension in cast("list[Any]", drawing["dimensions"]))
    for path in cast("list[str]", drawing["paths"]):
        assert (surface.project_root / path).exists()
    doc = cast("dict[str, Any]", seen["generate_doc"])
    assert doc["source_artifact_ref"] == build["artifact_ref"]
    assert "Bill of materials" in doc["markdown"]
    for path in cast("list[str]", doc["paths"]):
        assert (surface.project_root / path).exists()

    # -- query_snapshot: text + refs only, never child images ---------------
    snapshot = cast("dict[str, Any]", seen["query_snapshot"])
    assert snapshot["status"] == "ok" and snapshot["answer"]
    assert snapshot["usage"]["turns"] == 1
    assert all("data" not in str(ref) for ref in snapshot["render_artifacts"])

    # -- project checks ------------------------------------------------------
    assert seen["list_project_checks"]["status"] == "ok"
    assert seen["create_project_check"]["content_hash"]
    assert seen["edit_project_check"]["status"] == "applied"

    # -- delegation: one stable child, one terminal, replayable status -------
    delegated = cast("dict[str, Any]", seen["delegate_part_agent"])
    assert delegated["status"] == "completed"
    assert delegated["child_run_id"] and delegated["delegation_ref"]
    assert delegated["result_artifact_ref"]
    status = cast("dict[str, Any]", seen["get_delegation_status"])
    assert status["child_run_id"] == delegated["child_run_id"]
    assert status["status"] == "completed"
    # Cancelling an already-terminal delegation returns the unchanged terminal.
    assert seen["cancel_delegation"]["status"] == "completed"
    assert surface.runtime.delegation_runner.children == [delegated["child_run_id"]]

    # -- ask_user: a real suspension, surfaced as question/answer events -----
    assert len(answered) == 1 and answered[0]["question"] == "Ship it?"
    questions = events_of(result, "question")
    answers = events_of(result, "answer")
    assert len(questions) == 1 and len(answers) == 1
    assert questions[0]["seq"] < answers[0]["seq"]
    assert seen["ask_user"]["selection"] == "yes"

    # -- every dispatch carried trusted invocation metadata ------------------
    records = surface.recorder.calls
    assert records, "no dispatch reached Python"
    for record in records:
        assert record.invocation.get("session_id") == session_id
        assert record.invocation.get("entry_id")
        assert record.invocation.get("provider_call_id")
    assert len({record.invocation_id for record in records}) == len(records)
