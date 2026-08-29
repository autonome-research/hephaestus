"""G11B clause 17: contract drift, the ``interfaces`` half of item 29.

G11A deliberately withheld this field. "A schema field no code can fill is not
evidence of anything", and until record ⇄ region set equality landed a declared
interface name was not evidence that the generator emits a tag for it — so
returning the list to a *model* would have advertised anchors that may not
exist. Both halves are now here, and together with G11A clause 15 this is the
whole of named new work item 29.

The two lists are deliberately different shapes, and that is the point:
``search_parts_store`` returns the names **as declared, unprefixed**, because
the instance prefix is not known until instantiation, while
``instance_store_part`` returns the **emitted** names — which is what an 8C
anchor or a Stage 9 joint actually spells.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g11b import (
    RIG_INTERFACES,
    SEAT_POS,
    component_tree,
    fragment_for,
    requires_bwrap,
    store_ops,
)
from hephaestus.contract import toolgen, tools_decl
from hephaestus.core.registry import RegistryOps, RegistrySet, load_registry

from opstore import OpStore

REPO: Path = Path(__file__).resolve().parents[2]


def _result_variants(tool: str) -> list[dict[str, Any]]:
    document = toolgen.schema_document(tools_decl.get_tool(tool))
    result = cast("dict[str, Any]", document["result"])
    variants = cast("list[dict[str, Any]]", result.get("oneOf") or [result])
    out: list[dict[str, Any]] = []
    for variant in variants:
        if variant.get("type") == "array":
            out.append(cast("dict[str, Any]", variant.get("items", {})))
        else:
            out.append(variant)
    return out


# ==========================================================================
# the declared surface


def test_the_tool_count_is_still_53() -> None:
    """No tool is added: the capability lands in the results, not on the surface."""
    assert len(tools_decl.tool_names()) == 53


def test_the_generated_artifacts_regenerate_identically_with_the_field_present() -> None:
    """All five: the JSON schemas, the TypeBox module, the MCP file, the docs."""
    generated = toolgen.generate_json_schemas()
    assert generated == toolgen.generate_json_schemas(), "generation is not deterministic"
    assert {Path(rel).name.removesuffix(".schema.json") for rel in generated} == set(
        tools_decl.tool_names()
    ), "the declaration is artifact one and the source of the rest"
    for rel, text in generated.items():
        assert (REPO / rel).read_text(encoding="utf-8") == text, f"{rel} is stale; rerun toolgen"
    ts = (REPO / "agent" / "src" / "tools" / "schema.gen.ts").read_text(encoding="utf-8")
    assert ts == toolgen.generate_typebox_module(), "schema.gen.ts is stale; rerun toolgen"
    mcp = (REPO / "schemas" / "mcp" / "tools.json").read_text(encoding="utf-8")
    assert mcp == toolgen.generate_mcp_document(), "schemas/mcp/tools.json is stale; rerun toolgen"


def test_the_fifth_artifact_carries_the_interfaces_field_too() -> None:
    """``tool_schema.md`` is the fifth, and neither stage-11 gate's command
    reached it: it is hand-maintained under ``contract/tests/test_toolgen.py``,
    which is not part of either command. The drift contract is re-asserted inside
    this gate, over the field this clause owns.
    """
    md = (REPO / "tool_schema.md").read_text(encoding="utf-8")
    declared = set(tools_decl.tool_names())
    signatures = set(re.findall(r"^([a-z][a-z0-9_]+)\(", md, re.MULTILINE))
    assert declared <= signatures, f"undocumented tools: {sorted(declared - signatures)}"
    assert declared.isdisjoint(set(tools_decl.STAGE2_EXCLUDED_TOOLS))
    assert "interfaces" in md, "item 29's other half must be documented, not only generated"


@pytest.mark.parametrize("tool", ["search_parts_store", "instance_store_part"])
def test_interfaces_is_declared_and_optional(tool: str) -> None:
    """Optional because a *legacy* store part carries none: a caller branches on presence."""
    found = False
    for variant in _result_variants(tool):
        properties = cast("dict[str, Any]", variant.get("properties", {}))
        if "interfaces" in properties:
            found = True
            assert "interfaces" not in cast("list[str]", variant.get("required", []))
            assert cast("dict[str, Any]", properties["interfaces"])["type"] == "array"
    assert found, f"{tool} does not declare 'interfaces'"


def test_the_two_interfaces_fields_carry_different_shapes() -> None:
    """Declared records on the search row; emitted NAMES on the instance result."""
    search = next(
        cast("dict[str, Any]", variant["properties"]["interfaces"])
        for variant in _result_variants("search_parts_store")
        if "interfaces" in cast("dict[str, Any]", variant.get("properties", {}))
    )
    assert cast("dict[str, Any]", search["items"])["type"] == "object"
    assert set(cast("dict[str, Any]", search["items"])["properties"]) == {"name", "class", "role"}
    instance = next(
        cast("dict[str, Any]", variant["properties"]["interfaces"])
        for variant in _result_variants("instance_store_part")
        if "interfaces" in cast("dict[str, Any]", variant.get("properties", {}))
    )
    assert cast("dict[str, Any]", instance["items"])["type"] == "string"


def test_the_instance_argument_is_declared_optional_under_the_ident_grammar() -> None:
    from hephaestus.contract.tools_decl import IDENT_PATTERN

    document = toolgen.schema_document(tools_decl.get_tool("instance_store_part"))
    params = cast("dict[str, Any]", document["parameters"])
    properties = cast("dict[str, Any]", params["properties"])
    assert "instance" not in cast("list[str]", params.get("required", []))
    variants = cast("list[dict[str, Any]]", properties["instance"]["anyOf"])
    assert {"type": "string", "pattern": IDENT_PATTERN} in variants
    assert {"type": "null"} in variants


# ==========================================================================
# both profiles dispatch it


@pytest.fixture
def bench(tmp_path: Path) -> Iterator[Any]:
    """The real dispatcher over a registry set carrying the rig component."""
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.agent_bridge.dispatch import ToolDispatcher
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.store import ProjectStore
    from hephaestus.testing.tools_fixture import scaffold

    parts = component_tree(tmp_path / "parts")
    root = tmp_path / "proj"
    scaffold(root)
    layout = load_project(root)
    store = OpStore.create(tmp_path / "store")
    dispatcher = ToolDispatcher(
        ProjectStore(layout, open_store(layout)),
        cad=CadOps(layout, open_store(layout)),
        registry=RegistryOps(
            RegistrySet({"parts": load_registry(parts)}),
            store,
            backend=BwrapBackend(),
            scratch_root=tmp_path / "scratch",
        ),
    )

    class Bench:
        def __init__(self) -> None:
            self._n = 0

        def call(self, tool: str, arguments: dict[str, Any], principal: Any) -> Any:
            self._n += 1
            return dispatcher.dispatch(
                principal,
                {
                    "session_id": principal.session_id,
                    "run_id": "run-1",
                    "tool": tool,
                    "arguments": arguments,
                    "invocation": {
                        "session_id": principal.session_id,
                        "entry_id": f"entry-{self._n}",
                        "ordinal": 1,
                        "provider_call_id": "call_0",
                    },
                },
            )

    try:
        yield Bench()
    finally:
        store.close()


def _principals() -> list[Any]:
    from hephaestus.testing.tools_fixture import ORCH, PART_WIDGET, QUICK_WIDGET

    return [ORCH, PART_WIDGET, QUICK_WIDGET]


@pytest.mark.parametrize("principal_index", [0, 1, 2])
def test_every_profile_dispatches_the_declared_interfaces_on_search(
    bench: Any, principal_index: int
) -> None:
    rows = cast(
        "list[dict[str, Any]]",
        bench.call("search_parts_store", {"query": "rig fixture"}, _principals()[principal_index]),
    )
    assert rows, "the fixture component must be findable"
    interfaces = cast("list[dict[str, Any]]", rows[0]["interfaces"])
    assert [entry["name"] for entry in interfaces] == [name for name, _c, _r in RIG_INTERFACES]


@requires_bwrap
@pytest.mark.parametrize("principal_index", [0, 1, 2])
def test_every_profile_dispatches_the_emitted_interfaces_on_instance(
    bench: Any, principal_index: int
) -> None:
    result = cast(
        "dict[str, Any]",
        bench.call(
            "instance_store_part",
            {"id": "rig", "params": {}, "pos": dict(SEAT_POS), "instance": "motor_a"},
            _principals()[principal_index],
        ),
    )
    assert cast("list[str]", result["interfaces"]) == [
        f"motor_a__{name}" for name, _c, _r in RIG_INTERFACES
    ]


@requires_bwrap
def test_the_emitted_names_are_exactly_the_fragments_tag_literals(tmp_path: Path) -> None:
    """The result is not a second, hand-maintained list of what the fragment did."""
    from _g11b import tag_names

    ops = store_ops(tmp_path)
    result = fragment_for(ops, params={}, pos=dict(SEAT_POS), instance="motor_a")
    assert tuple(cast("list[str]", result["interfaces"])) == tag_names(
        cast("str", result["script_fragment"])
    )


@requires_bwrap
def test_a_legacy_part_result_still_carries_no_interfaces(tmp_path: Path) -> None:
    """The field is component-only, so "carries no component fields" survives."""
    import json

    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

    root = component_tree(tmp_path / "legacy")
    meta_path = root / "rig" / "part.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["component"]
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    store = OpStore.create(tmp_path / "store")
    try:
        ops = RegistryOps(
            RegistrySet({"parts": load_registry(root)}),
            store,
            backend=BwrapBackend(),
            scratch_root=tmp_path / "scratch",
        )
        result = ops.instance_store_part("rig", {}, dict(SEAT_POS))
        assert "interfaces" not in result
        assert "mass" not in result
    finally:
        store.close()
