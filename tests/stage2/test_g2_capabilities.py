"""G2 capability outcomes: discriminated ``capability_error`` results.

Gate clause: *"Capability tests use the active image model, fall back to
configured vision model for a text-only active model, and return schema-valid
discriminated ``image_model_required`` / ``capability_not_available`` outcomes
when needed."*

A capability refusal is a **successful, discriminated tool result**, not a
transport error: the model must be able to branch on ``status ==
"capability_error"`` and a stable ``code``. Each case below is driven through the
real bridge and then validated against the committed JSON Schema for that tool,
so a refusal that a client could not parse fails the gate.

Cases:

* ``query_snapshot`` with no vision child configured -> ``capability_not_available``;
* ``export_part(layout="nested_sheet")`` -> a schema-valid *success* (the layout
  shipped with Stage 6; the refusal it once returned no longer exists);
* ``instance_store_part`` with no probed sandbox -> ``capability_not_available``
  (never a quiet unsandboxed generator run);
* ``inspect_part`` against a text-only active model -> ``image_model_required``
  (Stage 2 wires no vision-model fallback, so the refusal is the outcome).
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from _g2 import REPO, G2Harness, RequestInfo, last_tool_result, text, tool_call

WIDGET = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

body = Box(p.w, 10.0, 4.0)
body.label = "body"
part.geometry = body
"""


def _result_schema(tool: str) -> dict[str, Any]:
    import json

    document = cast(
        "dict[str, Any]",
        json.loads((REPO / "schemas" / "tools" / f"{tool}.schema.json").read_text("utf-8")),
    )
    return cast("dict[str, Any]", document["result"])


def _capability_variant(tool: str) -> dict[str, Any] | None:
    """The tool's declared ``capability_error`` result variant, if it has one."""
    schema = _result_schema(tool)
    variants = cast("list[dict[str, Any]]", schema.get("oneOf") or schema.get("anyOf") or [schema])
    for variant in variants:
        status = cast("dict[str, Any]", variant.get("properties", {})).get("status", {})
        if cast("dict[str, Any]", status).get("const") == "capability_error":
            return variant
    return None


def _assert_capability(result: dict[str, Any], tool: str, code: str) -> None:
    """A refusal must be a discriminated result and validate against its schema."""
    assert result.get("status") == "capability_error", result
    assert result.get("code") == code, result
    assert _capability_variant(tool) is not None, (
        f"{tool} refused at runtime but declares no capability_error variant"
    )
    jsonschema.validate(result, _result_schema(tool))


def _run(harness: G2Harness, session: str, call: dict[str, Any], prompt: str) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def capture(info: RequestInfo) -> dict[str, Any]:
        seen["result"] = last_tool_result(info)
        return text("noted")

    harness.set_script([call, capture])
    outcome = harness.prompt(session, prompt, timeout=1200)
    assert outcome.status == "completed", outcome.status
    return cast("dict[str, Any]", seen["result"])


def test_query_snapshot_without_a_vision_child_is_capability_not_available(
    harness: G2Harness,
) -> None:
    """No multimodal provider -> a discriminated refusal, never a launched child."""
    (harness.project_root / "parts" / "widget.py").write_text(WIDGET, encoding="utf-8")
    session_id = harness.create_session("orchestrator", session_id="g2-cap-snapshot")
    result = _run(
        harness,
        session_id,
        tool_call("query_snapshot", {"name": "widget", "question": "is it square?"}, "call_0"),
        "look at the widget",
    )
    _assert_capability(result, "query_snapshot", "capability_not_available")
    # The refusal happened before any render work was attempted.
    assert harness.runtime.snapshot_caller is None


def test_nested_sheet_export_produces_a_schema_valid_result(harness: G2Harness) -> None:
    """``nested_sheet`` shipped with Stage 6: the same call now *succeeds*.

    The Stage-2 clause this case was written for is about discriminated,
    schema-valid tool outcomes; the layout it used as its example is no longer
    deferred, so the case asserts the implemented outcome against the same
    committed schema instead of asserting a refusal that can no longer happen.
    ``widget`` declares no ``part.blank_size``, so the blank is stated here.
    """
    (harness.project_root / "parts" / "widget.py").write_text(WIDGET, encoding="utf-8")
    session_id = harness.create_session("orchestrator", session_id="g2-cap-export")

    def then_export(info: RequestInfo) -> dict[str, Any]:
        return tool_call(
            "export_part",
            {
                "name": "widget",
                "format": "dxf",
                "layout": "nested_sheet",
                "blank": {"width_mm": 120.0, "height_mm": 80.0},
            },
            "call_1",
        )

    seen: dict[str, Any] = {}

    def capture(info: RequestInfo) -> dict[str, Any]:
        seen["result"] = last_tool_result(info)
        return text("noted")

    harness.set_script(
        [tool_call("build_part", {"name": "widget"}, "call_0"), then_export, capture]
    )
    outcome = harness.prompt(session_id, "export a nested sheet", timeout=1200)
    assert outcome.status == "completed"
    result = cast("dict[str, Any]", seen["result"])
    assert result.get("status") != "capability_error", result
    jsonschema.validate(result, _result_schema("export_part"))
    # …and the nested DXF is really on disk.
    exports = harness.project_root / ".heph" / "exports"
    assert any(exports.rglob("*.dxf"))


def test_store_generator_without_a_sandbox_is_capability_not_available(
    tmp_path: Any, sidecar_dist: Any
) -> None:
    """Executable registry content refuses to run rather than degrade."""
    from _g2 import scaffold_project

    project = scaffold_project(tmp_path / "nosandbox")
    harness = G2Harness(project, sidecar_dist, sandbox=False)
    try:
        session_id = harness.create_session("orchestrator", session_id="g2-cap-store")

        def then_instance(info: RequestInfo) -> dict[str, Any]:
            found = last_tool_result(info)
            entries = cast("list[Any]", found.get("_value", []))
            assert entries, found
            return tool_call(
                "instance_store_part", {"id": str(entries[0]["id"]), "params": {}}, "call_1"
            )

        seen: dict[str, Any] = {}

        def capture(info: RequestInfo) -> dict[str, Any]:
            seen["result"] = last_tool_result(info)
            return text("noted")

        harness.set_script(
            [
                tool_call("search_parts_store", {"query": "screw"}, "call_0"),
                then_instance,
                capture,
            ]
        )
        outcome = harness.prompt(session_id, "instance a screw", timeout=600)
        assert outcome.status == "completed"
        _assert_capability(
            cast("dict[str, Any]", seen["result"]),
            "instance_store_part",
            "capability_not_available",
        )
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_text_only_active_model_yields_image_model_required(
    tmp_path: Any, sidecar_dist: Any
) -> None:
    from _g2 import scaffold_project

    project = scaffold_project(tmp_path / "textonly")
    harness = G2Harness(project, sidecar_dist, vision=False)
    try:
        (project / "parts" / "widget.py").write_text(WIDGET, encoding="utf-8")
        session_id = harness.create_session("orchestrator", session_id="g2-cap-image")

        seen: dict[str, Any] = {}

        def then_inspect(info: RequestInfo) -> dict[str, Any]:
            return tool_call("inspect_part", {"name": "widget", "views": ["iso"]}, "call_1")

        def capture(info: RequestInfo) -> dict[str, Any]:
            seen["result"] = last_tool_result(info)
            seen["body"] = info.body_text
            return text("noted")

        harness.set_script(
            [tool_call("build_part", {"name": "widget"}, "call_0"), then_inspect, capture]
        )
        outcome = harness.prompt(session_id, "inspect the widget", timeout=1200)
        assert outcome.status == "completed"

        result = cast("dict[str, Any]", seen["result"])
        _assert_capability(result, "inspect_part", "image_model_required")
        # The refusal still names the artifacts that were rendered on disk.
        assert result.get("render_artifact_refs")
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_every_tool_that_can_refuse_declares_the_capability_variant() -> None:
    for tool in ("export_part", "instance_store_part"):
        variant = _capability_variant(tool)
        assert variant is not None, f"{tool} can refuse but declares no capability_error variant"
        properties = cast("dict[str, Any]", variant["properties"])
        assert properties["code"]["const"] == "capability_not_available"


def test_capability_variants_are_declared_and_discriminated() -> None:
    """The two codes are const-discriminated result variants, not free text."""
    for tool, code in (
        ("inspect_part", "image_model_required"),
        ("query_snapshot", "capability_not_available"),
    ):
        schema = _result_schema(tool)
        variants = cast(
            "list[dict[str, Any]]", schema.get("oneOf") or schema.get("anyOf") or [schema]
        )
        capability = [
            variant
            for variant in variants
            if cast("dict[str, Any]", variant.get("properties", {})).get("status", {}).get("const")
            == "capability_error"
        ]
        assert capability, f"{tool} declares no capability_error variant"
        properties = cast("dict[str, Any]", capability[0]["properties"])
        assert properties["code"]["const"] == code
        assert "code" in capability[0]["required"]
        # A well-formed refusal validates; a wrong code does not.
        jsonschema.validate({"status": "capability_error", "code": code}, schema)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"status": "capability_error", "code": "nope"}, schema)
