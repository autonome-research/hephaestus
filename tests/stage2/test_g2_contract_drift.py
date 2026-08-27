"""G2 contract drift: Python declaration / committed JSON / TypeBox / docs.

Gate clause: *"Contract tests prove the Python declaration, committed JSON
Schema, Pi TypeBox schema, MCP schema, and ``tool_schema.md`` do not drift."*

``server/tests/test_toolgen.py`` already proves the *name* set and byte-level
freshness of the generated artifacts. This module proves the part that a stale
regeneration would still pass: the **shapes**. For every one of the 27 declared
tools it cross-checks, field by field,

* committed ``schemas/tools/<tool>.schema.json`` vs the Python declaration —
  parameter names, required set, defaults, enums, nullability, the
  ``x-hephaestus-maxUtf8Bytes`` keyword, and the ``x-hephaestus-tool`` flags;
* the generated TypeBox module (``agent/src/tools/schema.gen.ts``) — the same
  parameter names, the same optionality (``Type.Optional``), the same per-tool
  ``meta`` block (profiles / sequential / idempotent / maxUtf8Fields), and one
  ``TOOLS`` entry per tool wired to its own params/result schemas;
* ``tool_schema.md`` — the documented signature's argument names *and order*,
  its documented defaults, and, for every result variant, that each schema-
  required output field is actually documented.

The MCP schema is Stage 3; ``toolgen`` emits it from the same declaration, so
the Stage-2 leg is the declaration -> {JSON, TypeBox, docs} triangle.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from _g2 import REPO
from hephaestus.core import toolgen, tools_decl

TOOL_NAMES: list[str] = list(tools_decl.tool_names())
SCHEMA_TS = REPO / "agent" / "src" / "tools" / "schema.gen.ts"
TOOL_SCHEMA_MD = REPO / "tool_schema.md"
SCHEMAS_DIR = REPO / "schemas" / "tools"

#: Tools whose documented result is a named record defined elsewhere in the doc
#: (prose type, not an inline field list). Their *parameters* are still checked.
_NAMED_RESULT_DOCS: frozenset[str] = frozenset({"build_part", "run_checks"})


# --------------------------------------------------------------------------
# tiny parsers (TypeBox module + markdown signatures)


def _split_top_level(body: str) -> list[str]:
    """Split a brace/bracket/paren-balanced argument list on top-level commas."""
    parts: list[str] = []
    depth = 0
    in_string = False
    current: list[str] = []
    for ch in body:
        if in_string:
            current.append(ch)
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
            continue
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _typebox_object_properties(expr: str) -> dict[str, bool]:
    """``Type.Object({ "a": X, "b": Type.Optional(Y) }, …)`` -> {name: optional}."""
    inner = expr[expr.index("{") + 1 :]
    depth = 1
    end = 0
    in_string = False
    for i, ch in enumerate(inner):
        if in_string:
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                end = i
                break
    props: dict[str, bool] = {}
    for entry in _split_top_level(inner[:end]):
        match = re.match(r'^"([^"]+)"\s*:\s*(.*)$', entry, re.DOTALL)
        if match is None:
            continue
        props[match.group(1)] = match.group(2).lstrip().startswith("Type.Optional(")
    return props


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


def _ts_source() -> str:
    return SCHEMA_TS.read_text(encoding="utf-8")


def _ts_params(tool: str, source: str) -> dict[str, bool]:
    marker = f"export const {_camel(tool)}Params: TSchema = "
    start = source.index(marker) + len(marker)
    line = source[start : source.index("\n", start)]
    assert line.startswith("Type.Object("), f"{tool} params are not a TypeBox object"
    return _typebox_object_properties(line)


def _ts_meta(tool: str, source: str) -> dict[str, Any]:
    marker = f'"{tool}": {{\n    meta: {{ '
    start = source.index(marker) + len(marker)
    body = source[start : source.index(" },\n", start)]
    meta: dict[str, Any] = {}
    for entry in _split_top_level(body):
        key, _, raw = entry.partition(":")
        text = raw.strip()
        if text in {"true", "false"}:
            meta[key.strip()] = text == "true"
        elif text.startswith(("[", "{")):
            meta[key.strip()] = json.loads(text)
        else:
            meta[key.strip()] = json.loads(text) if text.startswith('"') else text
    return meta


@pytest.fixture(scope="module")
def ts_source() -> str:
    return _ts_source()


@pytest.fixture(scope="module")
def md_source() -> str:
    return TOOL_SCHEMA_MD.read_text(encoding="utf-8")


def _md_signature(tool: str, md: str) -> tuple[str, str]:
    """The documented ``tool(args…)`` signature and its ``-> result`` block."""
    match = re.search(rf"^{tool}\(", md, re.MULTILINE)
    assert match, f"{tool} has no signature in tool_schema.md"
    start = match.start()
    depth = 0
    end = start
    for i in range(start, len(md)):
        ch = md[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    signature = md[start + len(tool) + 1 : end]
    rest = md[end + 1 :]
    stop = re.search(r"^(```|[a-z][a-z0-9_]*\()", rest, re.MULTILINE)
    return signature, rest[: stop.start()] if stop else rest


def _md_params(signature: str) -> list[tuple[str, str | None]]:
    """``[(name, default_or_None)]`` from a documented signature."""
    cleaned = re.sub(r"#[^\n]*", "", signature)  # strip trailing `# maxItems=4` notes
    params: list[tuple[str, str | None]] = []
    for entry in _split_top_level(cleaned):
        match = re.match(r"^([a-z_][a-z0-9_]*)\s*:", entry)
        if match is None:
            continue
        _, _, after = entry.partition("=")
        default = after.strip() or None if "=" in entry else None
        params.append((match.group(1), default))
    return params


# --------------------------------------------------------------------------
# declaration <-> committed JSON


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_committed_json_matches_declaration_shape(tool: str) -> None:
    """The committed schema is byte-equal to a fresh generation of the same tool."""
    fresh = toolgen.schema_document(tools_decl.get_tool(tool))
    committed = cast(
        "dict[str, Any]", json.loads((SCHEMAS_DIR / f"{tool}.schema.json").read_text("utf-8"))
    )
    assert committed == fresh, f"{tool}.schema.json drifted from tools_decl"
    meta = cast("dict[str, Any]", committed["x-hephaestus-tool"])
    decl = tools_decl.get_tool(tool)
    assert meta["profiles"] == list(decl.profiles)
    assert meta["sequential"] is decl.sequential
    assert meta["idempotent"] is decl.idempotent
    assert meta["maxUtf8Fields"] == dict(decl.max_utf8_fields)


def test_max_utf8_keyword_is_carried_in_every_artifact(ts_source: str) -> None:
    """``x-hephaestus-maxUtf8Bytes`` survives into JSON *and* TypeBox meta."""
    declared = {
        name: dict(tools_decl.get_tool(name).max_utf8_fields)
        for name in TOOL_NAMES
        if tools_decl.get_tool(name).max_utf8_fields
    }
    assert declared, "at least delegate_part_agent.prompt must carry the keyword"
    for tool, fields in declared.items():
        document = cast(
            "dict[str, Any]", json.loads((SCHEMAS_DIR / f"{tool}.schema.json").read_text("utf-8"))
        )
        properties = cast("dict[str, Any]", document["parameters"]["properties"])
        for field, limit in fields.items():
            assert properties[field]["x-hephaestus-maxUtf8Bytes"] == limit
        assert _ts_meta(tool, ts_source)["maxUtf8Fields"] == fields
    assert declared["delegate_part_agent"]["prompt"] == tools_decl.PROMPT_MAX_UTF8_BYTES


# --------------------------------------------------------------------------
# declaration <-> generated TypeBox


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_typebox_params_and_meta_match_declaration(tool: str, ts_source: str) -> None:
    document = toolgen.schema_document(tools_decl.get_tool(tool))
    parameters = cast("dict[str, Any]", document["parameters"])
    declared_props = cast("dict[str, Any]", parameters.get("properties", {}))
    required = set(cast("list[str]", parameters.get("required", [])))

    ts_props = _ts_params(tool, ts_source)
    assert set(ts_props) == set(declared_props), f"{tool}: TypeBox parameter names drifted"
    for name, optional in ts_props.items():
        assert optional is (name not in required), (
            f"{tool}.{name}: TypeBox optionality disagrees with the JSON `required` set"
        )

    meta = _ts_meta(tool, ts_source)
    decl = tools_decl.get_tool(tool)
    assert meta["name"] == tool
    assert meta["profiles"] == list(decl.profiles)
    assert meta["sequential"] is decl.sequential
    assert meta["idempotent"] is decl.idempotent
    assert f"    params: {_camel(tool)}Params,\n" in ts_source
    assert f"    result: {_camel(tool)}Result,\n" in ts_source


def test_typebox_declares_every_tool_exactly_once(ts_source: str) -> None:
    entries = re.findall(r'^  "([a-z0-9_]+)": \{$', ts_source, re.MULTILINE)
    assert entries == TOOL_NAMES, "TOOLS map order/content drifted from tools_decl"
    names = re.search(r"export const TOOL_NAMES = \[(.*?)\] as const;", ts_source, re.DOTALL)
    assert names is not None
    assert re.findall(r'"([a-z0-9_]+)"', names.group(1)) == TOOL_NAMES


# --------------------------------------------------------------------------
# declaration <-> tool_schema.md


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_documented_signature_matches_declared_parameters(tool: str, md_source: str) -> None:
    """Documented argument names, order, and defaults match the canonical schema."""
    signature, _result = _md_signature(tool, md_source)
    documented = _md_params(signature)
    document = toolgen.schema_document(tools_decl.get_tool(tool))
    parameters = cast("dict[str, Any]", document["parameters"])
    properties = cast("dict[str, Any]", parameters.get("properties", {}))
    required = set(cast("list[str]", parameters.get("required", [])))

    assert [name for name, _ in documented] == list(properties), (
        f"{tool}: tool_schema.md argument names/order drifted from the schema"
    )
    for name, default in documented:
        spec = cast("dict[str, Any]", properties[name])
        if default is None:
            # An undocumented default must be a genuinely required parameter, or a
            # nullable one the doc writes as `x: T|null` (both mean "no value" is
            # a caller decision, never a hidden server-side default).
            nullable = "null" in json.dumps(spec)
            assert name in required or nullable, (
                f"{tool}.{name}: documented without a default but optional in the schema"
            )
            continue
        assert name not in required, f"{tool}.{name}: documented default on a required parameter"
        if default in {"[...]"}:  # doc shorthand for a long literal default
            continue
        expected = spec.get("default")
        parsed: Any
        try:
            parsed = json.loads(default.replace("'", '"'))
        except json.JSONDecodeError:
            parsed = default
        assert parsed == expected, (
            f"{tool}.{name}: documented default {default!r} != schema default {expected!r}"
        )


@pytest.mark.parametrize("tool", [name for name in TOOL_NAMES if name not in _NAMED_RESULT_DOCS])
def test_documented_result_covers_every_required_output_field(tool: str, md_source: str) -> None:
    """Every schema-required result field of every variant is documented."""
    _signature, documented = _md_signature(tool, md_source)
    document = toolgen.schema_document(tools_decl.get_tool(tool))
    result = cast("dict[str, Any]", document["result"])
    variants = cast("list[dict[str, Any]]", result.get("oneOf") or result.get("anyOf") or [result])
    for variant in variants:
        if variant.get("type") == "array":
            variant = cast("dict[str, Any]", variant.get("items", {}))
        for field in cast("list[str]", variant.get("required", [])):
            assert re.search(rf"\b{re.escape(field)}\b", documented), (
                f"{tool}: required result field {field!r} is missing from tool_schema.md"
            )


def test_stage2_surface_excludes_deferred_tools_everywhere(md_source: str) -> None:
    """The Stage-2 exclusions are absent from every generated artifact."""
    for excluded in tools_decl.STAGE2_EXCLUDED_TOOLS:
        assert excluded not in TOOL_NAMES
        assert not (SCHEMAS_DIR / f"{excluded}.schema.json").exists()
        assert f'"{excluded}"' not in _ts_source()
        # …but the doc still describes them (they are deferred, not deleted;
        # the deferred ones are written inline rather than as a signature block).
        assert re.search(rf"\b{excluded}\(", md_source), (
            f"{excluded} must remain documented as a deferred tool"
        )
    # nested_sheet is schema-permitted but Stage-2 unavailable.
    export = cast(
        "dict[str, Any]", json.loads((SCHEMAS_DIR / "export_part.schema.json").read_text("utf-8"))
    )
    layout = cast("dict[str, Any]", export["parameters"]["properties"]["layout"])
    assert layout["enum"] == ["as_built", "nested_sheet"]
    assert layout["default"] == "as_built"


def test_committed_schema_files_match_the_declared_surface() -> None:
    on_disk = {path.name.removesuffix(".schema.json") for path in SCHEMAS_DIR.glob("*.json")}
    assert on_disk == set(TOOL_NAMES)
    # 33 through Stage 7; +2 for the INGEST.md §2 reference pair (Stage 8A);
    # +1 for COMPARE.md §2 compare_solids (Stage 8B); +4 for the ASSEMBLY.md §3
    # constraint quartet (Stage 8C); +7 for the KINEMATICS.md Stage 9A
    # kinematics tools (the joint and pose quartets plus check_motion, §6).
    assert len(TOOL_NAMES) == 47


def test_sequential_declarations_cover_the_normative_list() -> None:
    """digest §1: the interactive/mutating tools that MUST declare sequential."""
    normative = {
        "ask_user",
        "create_part",
        "edit_part",
        "write_part",
        "edit_globals",
        "create_project_check",
        "edit_project_check",
        "set_params",
        "build_part",
        "export_part",
        "delegate_part_agent",
        "cancel_delegation",
        # VALIDATION.md §2: ledger writes advance a generation, so they serialize.
        "record_requirements",
        "update_requirement",
    }
    sequential = {name for name in TOOL_NAMES if tools_decl.get_tool(name).sequential}
    assert normative <= sequential, f"missing sequential declarations: {normative - sequential}"
    # Read-only render/measure stay parallel.
    for parallel in (
        "inspect_part",
        "measure",
        "read_part",
        "read_artifact",
        "run_checks",
        "read_requirements",
    ):
        assert not tools_decl.get_tool(parallel).sequential


def test_orchestrator_only_families_are_declared_orchestrator_only() -> None:
    """Globals, project checks and the delegation family are orchestrator-only."""
    orchestrator_only = {
        "read_globals",
        "edit_globals",
        "list_project_checks",
        "create_project_check",
        "read_project_check",
        "edit_project_check",
        "create_part",
        "delegate_part_agent",
        "get_delegation_status",
        "cancel_delegation",
    }
    # The requirement ledger is the orchestrator's and a delegated part agent's
    # (VALIDATION.md §2/§3); a quick-edit session never authors interpretation.
    ledger_family = {"record_requirements", "read_requirements", "update_requirement"}
    # References are the canonical pipeline's, plus the reviewer's: an image
    # citation is lint-unverifiable, so §5's reviewer must be able to open the
    # drawing itself (INGEST.md §2). A quick-edit session interprets nothing, so
    # it reads no reference material either.
    reference_family = {"list_references", "read_reference"}
    # COMPARE.md §2 declares compare_solids on the CANONICAL PIPELINE only
    # ("part + orchestrator profiles"): converging on a target is interpretation
    # work with a ledger behind it, not a quick edit, and the §5 reviewer reads
    # published evidence rather than re-running comparisons.
    comparison_family = {"compare_solids"}
    # ASSEMBLY.md §3 declares the constraint quartet on the CANONICAL PIPELINE
    # only ("part + orchestrator profiles"): declaring a cross-part mate is
    # interpretation work with a ledger behind it, not a quick edit, and the §5
    # reviewer is HANDED the assembly status rather than re-measuring it (a
    # reviewer that could write constraints would be grading its own claim).
    constraint_family = {
        "declare_constraint",
        "update_constraint",
        "read_constraints",
        "check_assembly",
    }
    # KINEMATICS.md Stage 9A (§6) applies the 8C quartet decision unchanged:
    # the joint and pose sets are canonical-pipeline surfaces ("part +
    # orchestrator profiles"), for exactly the constraint family's reasons.
    kinematics_family = {
        "declare_joint",
        "update_joint",
        "read_joints",
        "declare_pose",
        "update_pose",
        "read_poses",
        "check_motion",
    }
    for name in TOOL_NAMES:
        profiles = set(tools_decl.get_tool(name).profiles)
        if name in orchestrator_only:
            assert profiles == {"orchestrator"}, f"{name} leaked outside the orchestrator"
        elif (
            name in ledger_family
            or name in comparison_family
            or name in constraint_family
            or name in kinematics_family
        ):
            assert profiles == {"part", "orchestrator"}, f"{name} profiles drifted"
        elif name in reference_family:
            assert profiles == {"part", "orchestrator", "reviewer"}, f"{name} profiles drifted"
        else:
            assert "part" in profiles and "quick_edit" in profiles, name


def test_generated_artifacts_are_reproducible(tmp_path: Path) -> None:
    """Regenerating into a scratch tree reproduces the committed bytes exactly."""
    for rel, text in toolgen.generate_json_schemas().items():
        assert (REPO / rel).read_text(encoding="utf-8") == text, f"{rel} is stale"
    assert SCHEMA_TS.read_text(encoding="utf-8") == toolgen.generate_typebox_module()
    scratch = tmp_path / "again.ts"
    scratch.write_text(toolgen.generate_typebox_module(), encoding="utf-8")
    assert scratch.read_text(encoding="utf-8") == SCHEMA_TS.read_text(encoding="utf-8")
