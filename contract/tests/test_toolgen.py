"""toolgen determinism + cross-artifact drift tests.

Guards that the committed JSON Schemas and the generated TypeBox module stay in
lockstep with the Python declaration and ``tool_schema.md``:

* determinism: two generation runs produce identical bytes;
* freshness: the committed artifacts equal a fresh generation;
* drift: the tool names agree across tools_decl, the committed
  ``schemas/tools/*.schema.json`` files, the ``schema.gen.ts`` ``TOOL_NAMES``
  export, and ``tool_schema.md`` (headings minus documented Stage-2 exclusions;
  every declared tool has a ``name(`` signature in the doc).
"""

from __future__ import annotations

import re
from pathlib import Path

from hephaestus.contract import toolgen, tools_decl


def _root() -> Path:
    return toolgen.repo_root()


def test_json_schema_generation_is_deterministic() -> None:
    assert toolgen.generate_json_schemas() == toolgen.generate_json_schemas()


def test_typebox_generation_is_deterministic() -> None:
    assert toolgen.generate_typebox_module() == toolgen.generate_typebox_module()


def test_committed_json_schemas_are_fresh() -> None:
    root = _root()
    for rel, text in toolgen.generate_json_schemas().items():
        committed = (root / rel).read_text(encoding="utf-8")
        assert committed == text, f"{rel} is stale; rerun `toolgen all`"


def test_committed_typebox_is_fresh() -> None:
    root = _root()
    committed = (root / "agent" / "src" / "tools" / "schema.gen.ts").read_text(encoding="utf-8")
    assert committed == toolgen.generate_typebox_module(), "schema.gen.ts is stale; rerun toolgen"


def test_committed_json_files_match_declared_tools() -> None:
    tools_dir = _root() / "schemas" / "tools"
    on_disk = {p.name.removesuffix(".schema.json") for p in tools_dir.glob("*.schema.json")}
    assert on_disk == set(tools_decl.tool_names())


def _typebox_tool_names(root: Path) -> set[str]:
    text = (root / "agent" / "src" / "tools" / "schema.gen.ts").read_text(encoding="utf-8")
    match = re.search(r"export const TOOL_NAMES = \[(.*?)\] as const;", text, re.DOTALL)
    assert match, "TOOL_NAMES export not found"
    return set(re.findall(r'"([a-z0-9_]+)"', match.group(1)))


def test_typebox_tool_names_match_declaration() -> None:
    assert _typebox_tool_names(_root()) == set(tools_decl.tool_names())


def _md_heading_tools(md: str) -> set[str]:
    names: set[str] = set()
    for line in md.splitlines():
        if line.startswith("### "):
            for token in line[4:].split("/"):
                token = token.strip()
                if re.fullmatch(r"[a-z][a-z0-9_]+", token):
                    names.add(token)
    return names


def _md_signature_tools(md: str) -> set[str]:
    # A tool signature starts a line at column 0 inside a code fence: `name(`.
    return set(re.findall(r"^([a-z][a-z0-9_]+)\(", md, re.MULTILINE))


def test_no_drift_between_declaration_and_tool_schema_md() -> None:
    md = (_root() / "tool_schema.md").read_text(encoding="utf-8")
    decl = set(tools_decl.tool_names())
    excluded = set(tools_decl.STAGE2_EXCLUDED_TOOLS)

    # Direction 1: every heading tool (minus documented Stage-2 exclusions) is declared.
    headings = _md_heading_tools(md)
    missing_from_decl = headings - excluded - decl
    assert not missing_from_decl, f"md headings missing from decl: {missing_from_decl}"

    # Direction 2: every declared tool has a signature in the doc.
    signatures = _md_signature_tools(md)
    assert decl <= signatures, f"declared tools missing a signature: {decl - signatures}"

    # Sanity: no declared tool is one of the documented exclusions.
    assert decl.isdisjoint(excluded)


def test_full_tool_surface_is_47_tools() -> None:
    # 27 Stage-2 tools, the Stage 2V requirement-ledger family, the Stage 6
    # manufacturing tools (run_dfm, generate_drawing, generate_doc), the
    # Stage 8A read-only reference pair (INGEST.md §2), the Stage 8B
    # comparison tool (COMPARE.md §2), the Stage 8C constraint quartet
    # (ASSEMBLY.md §3), and the KINEMATICS.md Stage 9A kinematics tools
    # (the joint and pose quartets plus check_motion, §6) — declared
    # additions, not drift.
    assert len(tools_decl.tool_names()) == 47
    assert len(set(tools_decl.tool_names())) == 47
    assert {"record_requirements", "read_requirements", "update_requirement"} <= set(
        tools_decl.tool_names()
    )
    assert {"run_dfm", "generate_drawing", "generate_doc"} <= set(tools_decl.tool_names())
    assert {"list_references", "read_reference"} <= set(tools_decl.tool_names())
    assert "compare_solids" in tools_decl.tool_names()
    # ASSEMBLY.md §3: model-writable, because declaring a mate is cheap,
    # reversible and measured — unlike a reference, which is operator-only.
    assert {
        "declare_constraint",
        "update_constraint",
        "read_constraints",
        "check_assembly",
    } <= set(tools_decl.tool_names())
    # KINEMATICS.md Stage 9A (§6): the joint and pose sets ride the same
    # compelled-honesty decision — model-writable, generational, never erasing.
    assert {
        "declare_joint",
        "update_joint",
        "read_joints",
        "declare_pose",
        "update_pose",
        "read_poses",
        "check_motion",
    } <= set(tools_decl.tool_names())


def test_delegate_prompt_carries_max_utf8_keyword() -> None:
    doc = toolgen.schema_document(tools_decl.get_tool("delegate_part_agent"))
    prompt = doc["parameters"]["properties"]["prompt"]
    assert prompt["x-hephaestus-maxUtf8Bytes"] == tools_decl.PROMPT_MAX_UTF8_BYTES
