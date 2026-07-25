"""Typed declaration of the full Stage 2 tool surface (single source of truth).

This module is the *authoritative* description of every tool in ``tool_schema.md``
that is in Stage 2 scope. :mod:`hephaestus.core.toolgen` renders it to the
committed canonical JSON Schema files (``schemas/tools/*.schema.json``), the Pi
TypeBox module (``agent/src/tools/schema.gen.ts``), and — from Stage 3 — the MCP
declarations. Those artifacts, this declaration, and the ``tool_schema.md``
headings are drift-tested against each other in CI.

Scope (mission Stage 2): the full ``tool_schema.md`` surface **except**
``run_dfm``, ``generate_drawing``, ``generate_doc``, and the deferred ``run_fea``
/ ``import_geometry``. ``export_part`` keeps ``layout="nested_sheet"`` in the
schema (permitted only with ``format="dxf"|"svg"``) but the runtime returns
``capability_not_available`` until Stage 6.

Every numeric limit referenced here (prompt UTF-8 cap, delegation deadline
bounds, max images per result) is read from ``schemas/bridge_limits.json`` — no
limit literal is duplicated. The custom JSON Schema keyword
``x-hephaestus-maxUtf8Bytes`` is emitted on the fields it guards and enforced by
every validator after ordinary JSON Schema validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "IDENT_PATTERN",
    "PROFILES",
    "STAGE2_EXCLUDED_TOOLS",
    "TOOLS",
    "TOOLS_BY_NAME",
    "Profile",
    "ToolDecl",
    "get_tool",
    "limits_document",
    "tool_names",
]

# Normalized identifier grammar for part / new-part / project-check names.
IDENT_PATTERN: Final[str] = r"^[a-z][a-z0-9_]{0,63}$"

Profile = str  # one of PROFILES
PROFILES: Final[tuple[str, ...]] = ("part", "orchestrator", "quick_edit")

# Documented in tool_schema.md but explicitly out of Stage 2 scope; the drift
# test subtracts these from the heading set before comparing with TOOLS.
STAGE2_EXCLUDED_TOOLS: Final[frozenset[str]] = frozenset(
    {"run_dfm", "generate_drawing", "generate_doc", "run_fea", "import_geometry"}
)

JsonSchema = dict[str, Any]


def _find_limits_file() -> Path:
    import os

    override = os.environ.get("HEPHAESTUS_BRIDGE_LIMITS")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "schemas" / "bridge_limits.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("schemas/bridge_limits.json not found above " + str(here))


def limits_document() -> dict[str, Any]:
    with _find_limits_file().open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


_LIMITS: Final[dict[str, Any]] = limits_document()
PROMPT_MAX_UTF8_BYTES: Final[int] = int(_LIMITS["prompt"]["max_utf8_bytes"])
DEADLINE_MIN: Final[int] = int(_LIMITS["timeouts"]["delegation"]["deadline_min_seconds"])
DEADLINE_DEFAULT: Final[int] = int(_LIMITS["timeouts"]["delegation"]["deadline_default_seconds"])
DEADLINE_MAX: Final[int] = int(_LIMITS["timeouts"]["delegation"]["deadline_max_seconds"])
MAX_IMAGES_PER_RESULT: Final[int] = int(_LIMITS["image"]["max_images_per_result"])
READ_ARTIFACT_PAGE_MAX: Final[int] = 49152  # 48 KiB default page; a tool default, not a §5 cap


def _empty_max_utf8() -> dict[str, int]:
    return {}


@dataclass(frozen=True)
class ToolDecl:
    """One tool's full contract: parameters, result, metadata, availability."""

    name: str
    summary: str
    params: JsonSchema
    result: JsonSchema
    profiles: tuple[str, ...]
    sequential: bool
    idempotent: bool
    max_utf8_fields: dict[str, int] = field(default_factory=_empty_max_utf8)


# --- small schema builders -------------------------------------------------


def _obj(
    props: dict[str, JsonSchema],
    required: list[str],
    *,
    additional: bool = False,
    extra: dict[str, Any] | None = None,
) -> JsonSchema:
    schema: JsonSchema = {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": additional,
    }
    if extra:
        schema.update(extra)
    return schema


def _enum(values: list[str], default: str | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "string", "enum": values}
    if default is not None:
        schema["default"] = default
    return schema


def _ident() -> JsonSchema:
    return {"type": "string", "pattern": IDENT_PATTERN}


def _dict(value_schema: JsonSchema | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "object"}
    if value_schema is not None:
        schema["additionalProperties"] = value_schema
    return schema


_STR: Final[JsonSchema] = {"type": "string"}
_INT: Final[JsonSchema] = {"type": "integer"}
_NUM: Final[JsonSchema] = {"type": "number"}
_BOOL: Final[JsonSchema] = {"type": "boolean"}


def _result(*variants: JsonSchema) -> JsonSchema:
    if len(variants) == 1:
        return variants[0]
    return {"oneOf": list(variants)}


def _ok(props: dict[str, JsonSchema], required: list[str]) -> JsonSchema:
    # Result variant objects are lenient (server may add provenance fields) but
    # pin the documented/required shape.
    return _obj(props, required, additional=True)


# --- the paging fields shared by every read-family result ------------------

_PAGING_FIELDS: Final[dict[str, JsonSchema]] = {
    "truncated": _BOOL,
    "oversized_line": _BOOL,
    "oversized_line_offset_bytes": _INT,
    "next_offset_bytes": _INT,
}

_CONFLICT_FIELDS: Final[dict[str, JsonSchema]] = {
    "current_hash": _STR,
    "current_script": _STR,
    "current_truncated": _BOOL,
    "current_oversized_line": _BOOL,
    "current_oversized_line_offset_bytes": _INT,
    "current_next_offset_bytes": _INT,
    "current_snapshot_ref": _STR,
    "base_snapshot_ref": _STR,
    "attempted_snapshot_ref": _STR,
}


# --- individual tool declarations ------------------------------------------


def _create_part() -> ToolDecl:
    return ToolDecl(
        name="create_part",
        summary="Create parts/<name>.py from a template; fails without mutation if it exists.",
        params=_obj(
            {
                "name": _ident(),
                "template": _enum(["blank", "sheet", "solid", "from_store"], "blank"),
                "description": {"type": "string", "default": ""},
            },
            ["name"],
        ),
        result=_ok(
            {
                "path": _STR,
                "initial_script": _STR,
                "content_hash": _STR,
                "snapshot_ref": _STR,
                "part_param_state_hash": _STR,
                "project_param_state_hash": _STR,
            },
            ["path", "content_hash", "snapshot_ref"],
        ),
        profiles=("orchestrator",),
        sequential=True,
        idempotent=True,
    )


def _read_part() -> ToolDecl:
    return ToolDecl(
        name="read_part",
        summary="Read a part script (raw + numbered chunks) with optimistic hashes.",
        params=_obj(
            {
                "name": _ident(),
                "offset_line": {"type": "integer", "minimum": 1, "default": 1},
                "limit_lines": {"type": "integer", "minimum": 1, "default": 2000},
            },
            ["name"],
        ),
        result=_ok(
            {
                "script": _STR,
                "numbered_script": _STR,
                "params": _dict(),
                "line_count": _INT,
                "content_hash": _STR,
                "snapshot_ref": _STR,
                "part_param_state_hash": _STR,
                "project_param_state_hash": _STR,
                **_PAGING_FIELDS,
            },
            ["script", "content_hash", "snapshot_ref", "truncated"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _edit_part() -> ToolDecl:
    return ToolDecl(
        name="edit_part",
        summary="Exact-match string replacement under optimistic CAS with conflict payload.",
        params=_obj(
            {
                "name": _ident(),
                "expected_hash": _STR,
                "old_str": _STR,
                "new_str": _STR,
            },
            ["name", "expected_hash", "old_str", "new_str"],
        ),
        result=_ok(
            {
                "applied": _BOOL,
                "diff": _STR,
                "line": _INT,
                "content_hash": _STR,
                "snapshot_ref": _STR,
                "journal_ref": _STR,
                "conflict": _obj(_CONFLICT_FIELDS, [], additional=True),
            },
            ["applied"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


def _write_part() -> ToolDecl:
    return ToolDecl(
        name="write_part",
        summary="Whole-file replacement with the same optimistic-CAS/journal contract.",
        params=_obj(
            {
                "name": _ident(),
                "expected_hash": _STR,
                "script": _STR,
            },
            ["name", "expected_hash", "script"],
        ),
        result=_ok(
            {
                "applied": _BOOL,
                "diff": _STR,
                "content_hash": _STR,
                "snapshot_ref": _STR,
                "journal_ref": _STR,
                "conflict": _obj(_CONFLICT_FIELDS, [], additional=True),
            },
            ["applied"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


def _build_part() -> ToolDecl:
    return ToolDecl(
        name="build_part",
        summary="Run the incremental executor against an immutable snapshot; re-run CHECKS.",
        params=_obj(
            {"name": _ident(), "params": {"type": "object", "default": {}}},
            ["name"],
        ),
        result=_ok(
            {
                "status": _STR,
                "artifact_ref": _STR,
                "current": _BOOL,
                "project_snapshot_ref": _STR,
                "effective_params": _dict(),
                "toolchain_hashes": _dict(),
            },
            ["status"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


def _set_params() -> ToolDecl:
    # name required unless scope is explicitly "project" (default scope is part).
    conditional = [
        {
            "if": {"not": {"properties": {"scope": {"const": "project"}}, "required": ["scope"]}},
            "then": {"required": ["name"], "properties": {"name": _ident()}},
        },
        {
            "if": {"properties": {"scope": {"const": "project"}}, "required": ["scope"]},
            "then": {"properties": {"name": {"type": "null"}}},
        },
    ]
    return ToolDecl(
        name="set_params",
        summary="Persist bounds-validated parameter overrides (part or project scope).",
        params=_obj(
            {
                "values": _dict({"anyOf": [_NUM, {"type": "null"}]}),
                "expected_state_hash": _STR,
                "scope": _enum(["part", "project"], "part"),
                "name": {"anyOf": [_ident(), {"type": "null"}], "default": None},
            },
            ["values", "expected_state_hash"],
            extra={"allOf": conditional},
        ),
        result=_ok(
            {
                "effective": _dict(),
                "rejected": {"type": "array"},
                "stale_parts": {"type": "array", "items": _STR},
                "state_hash": _STR,
                "journal_ref": _STR,
                "conflict": _obj(
                    {
                        "current_state_hash": _STR,
                        "current_values": _dict(),
                        "base_snapshot_ref": _STR,
                        "attempted_snapshot_ref": _STR,
                    },
                    [],
                    additional=True,
                ),
            },
            ["effective", "rejected"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


def _read_globals() -> ToolDecl:
    return ToolDecl(
        name="read_globals",
        summary="Read globals.py with paging and optimistic hashes (orchestrator only).",
        params=_obj(
            {
                "offset_line": {"type": "integer", "minimum": 1, "default": 1},
                "limit_lines": {"type": "integer", "minimum": 1, "default": 2000},
            },
            [],
        ),
        result=_ok(
            {
                "script": _STR,
                "numbered_script": _STR,
                "content_hash": _STR,
                "snapshot_ref": _STR,
                "project_param_state_hash": _STR,
                **_PAGING_FIELDS,
            },
            ["script", "content_hash", "snapshot_ref", "truncated"],
        ),
        profiles=("orchestrator",),
        sequential=False,
        idempotent=False,
    )


def _edit_globals() -> ToolDecl:
    return ToolDecl(
        name="edit_globals",
        summary="Exact-match edit of globals.py; validates in the secure sandbox (orchestrator).",
        params=_obj(
            {"expected_hash": _STR, "old_str": _STR, "new_str": _STR},
            ["expected_hash", "old_str", "new_str"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "applied"},
                    "diff": _STR,
                    "content_hash": _STR,
                    "snapshot_ref": _STR,
                    "journal_ref": _STR,
                },
                ["status", "content_hash", "snapshot_ref"],
            ),
            _ok(
                {
                    "status": {"const": "validation_error"},
                    "kind": _enum(
                        ["syntax", "contract", "sandbox", "evaluation", "invalid_overrides"]
                    ),
                    "diagnostics": _STR,
                    "invalid_overrides": {"type": "array"},
                },
                ["status", "kind"],
            ),
            _ok(
                {
                    "status": {"const": "conflict"},
                    "kind": {"const": "stale_hash"},
                    **_CONFLICT_FIELDS,
                },
                ["status", "kind"],
            ),
        ),
        profiles=("orchestrator",),
        sequential=True,
        idempotent=True,
    )


def _list_project_checks() -> ToolDecl:
    return ToolDecl(
        name="list_project_checks",
        summary="Authoritative cursor-paged discovery of project checks (orchestrator).",
        params=_obj(
            {
                "cursor": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
            },
            [],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "items": {
                        "type": "array",
                        "items": _obj(
                            {"name": _STR, "content_hash": _STR, "summary": _STR},
                            ["name", "content_hash"],
                            additional=True,
                        ),
                    },
                    "total": _INT,
                    "check_set_generation": _STR,
                    "check_set_ref": _STR,
                    "next_cursor": _STR,
                },
                ["status", "items", "check_set_ref"],
            ),
            _ok(
                {
                    "status": {"const": "invalid_check_generation"},
                    "check_set_generation": _STR,
                    "check_set_ref": _STR,
                    "diagnostics_ref": _STR,
                },
                ["status"],
            ),
        ),
        profiles=("orchestrator",),
        sequential=False,
        idempotent=False,
    )


def _create_project_check() -> ToolDecl:
    return ToolDecl(
        name="create_project_check",
        summary="Create checks/<name>.py from a safe cross-part template (orchestrator).",
        params=_obj(
            {"name": _ident(), "description": {"type": "string", "default": ""}},
            ["name"],
        ),
        result=_ok(
            {
                "path": _STR,
                "initial_script": _STR,
                "content_hash": _STR,
                "snapshot_ref": _STR,
            },
            ["path", "content_hash", "snapshot_ref"],
        ),
        profiles=("orchestrator",),
        sequential=True,
        idempotent=True,
    )


def _read_project_check() -> ToolDecl:
    return ToolDecl(
        name="read_project_check",
        summary="Read a project check with paging and optimistic hashes (orchestrator).",
        params=_obj(
            {
                "name": _ident(),
                "offset_line": {"type": "integer", "minimum": 1, "default": 1},
                "limit_lines": {"type": "integer", "minimum": 1, "default": 2000},
            },
            ["name"],
        ),
        result=_ok(
            {
                "script": _STR,
                "numbered_script": _STR,
                "content_hash": _STR,
                "snapshot_ref": _STR,
                **_PAGING_FIELDS,
            },
            ["script", "content_hash", "snapshot_ref", "truncated"],
        ),
        profiles=("orchestrator",),
        sequential=False,
        idempotent=False,
    )


def _edit_project_check() -> ToolDecl:
    return ToolDecl(
        name="edit_project_check",
        summary="Exact-match edit of a project check; validates in the check sandbox.",
        params=_obj(
            {
                "name": _ident(),
                "expected_hash": _STR,
                "old_str": _STR,
                "new_str": _STR,
            },
            ["name", "expected_hash", "old_str", "new_str"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "applied"},
                    "diff": _STR,
                    "content_hash": _STR,
                    "snapshot_ref": _STR,
                    "journal_ref": _STR,
                },
                ["status", "content_hash", "snapshot_ref"],
            ),
            _ok(
                {
                    "status": {"const": "validation_error"},
                    "kind": _enum(["syntax", "contract", "sandbox", "evaluation"]),
                    "diagnostics": _STR,
                },
                ["status", "kind"],
            ),
            _ok(
                {
                    "status": {"const": "conflict"},
                    "kind": {"const": "stale_hash"},
                    **_CONFLICT_FIELDS,
                },
                ["status", "kind"],
            ),
        ),
        profiles=("orchestrator",),
        sequential=True,
        idempotent=True,
    )


def _inspect_part() -> ToolDecl:
    conditional = [
        # section_plane required iff channel="section"; null/absent otherwise.
        {
            "if": {"properties": {"channel": {"const": "section"}}, "required": ["channel"]},
            "then": {"required": ["section_plane"], "properties": {"section_plane": _STR}},
            "else": {"properties": {"section_plane": {"type": "null"}}},
        },
        # non-default mask_mode only when channel="mask".
        {
            "if": {"not": {"properties": {"channel": {"const": "mask"}}, "required": ["channel"]}},
            "then": {"properties": {"mask_mode": {"const": "solid"}}},
        },
        # artifact_ref XOR last_good=true.
        {
            "if": {"properties": {"last_good": {"const": True}}, "required": ["last_good"]},
            "then": {"properties": {"artifact_ref": {"type": "null"}}},
        },
    ]
    return ToolDecl(
        name="inspect_part",
        summary="Render current/immutable geometry to inline images + artifact refs.",
        params=_obj(
            {
                "name": _ident(),
                "views": {
                    "type": "array",
                    "items": _STR,
                    "minItems": 1,
                    "maxItems": MAX_IMAGES_PER_RESULT,
                    "default": ["iso", "+X"],
                },
                "channel": _enum(["rgb", "mask", "section"], "rgb"),
                "mask_mode": _enum(["solid", "selection"], "solid"),
                "section_plane": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "explode": {"type": "number", "default": 0.0},
                "last_good": {"type": "boolean", "default": False},
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "focus": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["name"],
            extra={"allOf": conditional},
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "source_artifact_ref": _STR,
                    "images": {"type": "array"},
                    "render_artifact_refs": {"type": "array", "items": _STR},
                    "mask_legend": _STR,
                    "mask_legend_ref": _STR,
                    "mask_legend_truncated": _BOOL,
                    "selection_table_ref": _STR,
                    "selection_bundles": {"type": "array"},
                },
                ["status", "source_artifact_ref", "render_artifact_refs"],
            ),
            _ok(
                {
                    "status": {"const": "capability_error"},
                    "code": {"const": "image_model_required"},
                    "source_artifact_ref": _STR,
                    "render_artifact_refs": {"type": "array", "items": _STR},
                    "message": _STR,
                },
                ["status", "code"],
            ),
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _query_snapshot() -> ToolDecl:
    return ToolDecl(
        name="query_snapshot",
        summary="Ephemeral vision child answers a question over 1-4 fresh renders.",
        params=_obj(
            {
                "name": _ident(),
                "question": _STR,
                "views": {
                    "type": "array",
                    "items": _STR,
                    "minItems": 1,
                    "maxItems": MAX_IMAGES_PER_RESULT,
                    "default": ["iso"],
                },
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["name", "question"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "answer": _STR,
                    "render_artifacts": {"type": "array", "items": _STR},
                    "usage": _dict(),
                },
                ["status", "answer"],
            ),
            _ok(
                {
                    "status": {"const": "capability_error"},
                    "code": {"const": "capability_not_available"},
                    "message": _STR,
                },
                ["status", "code"],
            ),
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _read_artifact() -> ToolDecl:
    return ToolDecl(
        name="read_artifact",
        summary="Byte-cursor paging over model-readable text/JSON artifacts.",
        params=_obj(
            {
                "ref": _STR,
                "offset_bytes": {"type": "integer", "minimum": 0, "default": 0},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": READ_ARTIFACT_PAGE_MAX,
                    "default": READ_ARTIFACT_PAGE_MAX,
                },
            },
            ["ref"],
        ),
        result=_result(
            _ok(
                {
                    "content": _STR,
                    "mime_type": _STR,
                    "offset_bytes": _INT,
                    "next_offset_bytes": _INT,
                    "total_bytes": _INT,
                    "truncated": _BOOL,
                },
                ["content", "mime_type", "offset_bytes", "total_bytes", "truncated"],
            ),
            _ok(
                {
                    "error": {"const": "invalid_utf8_offset"},
                    "offset_bytes": _INT,
                    "total_bytes": _INT,
                },
                ["error"],
            ),
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _measure() -> ToolDecl:
    binary_kinds = ["interference", "clearance", "distance"]
    conditional = [
        {
            "if": {"properties": {"kind": {"enum": binary_kinds}}, "required": ["kind"]},
            "then": {"required": ["b"], "properties": {"b": _STR}},
            "else": {"properties": {"b": {"type": "null"}}},
        },
        {"not": {"required": ["artifact_ref", "project_snapshot_ref"]}},
    ]
    return ToolDecl(
        name="measure",
        summary="Metric facade: interference/clearance/distance/bbox/volume/mass/sealed/genus.",
        params=_obj(
            {
                "kind": _enum(
                    [
                        "interference",
                        "clearance",
                        "distance",
                        "bbox",
                        "volume",
                        "mass",
                        "sealed",
                        "genus",
                    ]
                ),
                "a": _STR,
                "b": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "part": {"anyOf": [_ident(), {"type": "null"}], "default": None},
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "project_snapshot_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["kind", "a"],
            extra={"allOf": conditional},
        ),
        result=_ok(
            {
                "value": {},
                "units": _STR,
                "detail": {},
                "resolved_artifact_refs": {"type": "array", "items": _STR},
            },
            ["value", "units"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _run_checks() -> ToolDecl:
    conditional = [
        {
            "if": {"not": {"properties": {"scope": {"const": "project"}}, "required": ["scope"]}},
            "then": {"required": ["name"], "properties": {"name": _ident()}},
        },
        {
            "if": {"properties": {"scope": {"const": "project"}}, "required": ["scope"]},
            "then": {"properties": {"name": {"type": "null"}}},
        },
    ]
    return ToolDecl(
        name="run_checks",
        summary="Re-run persistent CHECKS (part) or cross-part checks (project).",
        params=_obj(
            {
                "scope": _enum(["part", "project"], "part"),
                "name": {"anyOf": [_ident(), {"type": "null"}], "default": None},
                "project_snapshot_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            [],
            extra={"allOf": conditional},
        ),
        result=_result(
            _ok({"status": _STR}, ["status"]),
            _ok(
                {
                    "status": {"const": "invalid_check_generation"},
                    "check_set_generation": _STR,
                    "check_set_ref": _STR,
                    "diagnostics_ref": _STR,
                },
                ["status"],
            ),
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _load_skill() -> ToolDecl:
    return ToolDecl(
        name="load_skill",
        summary="Load a bounded skill page inside provenance delimiters (reference only).",
        params=_obj(
            {
                "name": _STR,
                "offset_line": {"type": "integer", "minimum": 1, "default": 1},
                "limit_lines": {"type": "integer", "minimum": 1, "default": 2000},
            },
            ["name"],
        ),
        result=_ok(
            {
                "content": _STR,
                "artifact_ref": _STR,
                **_PAGING_FIELDS,
            },
            ["content", "artifact_ref", "truncated"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _list_skills() -> ToolDecl:
    return ToolDecl(
        name="list_skills",
        summary="List available skills with summaries and token estimates.",
        params=_obj({}, []),
        result={
            "type": "array",
            "items": _obj(
                {"name": _STR, "summary": _STR, "tokens": _INT},
                ["name", "summary", "tokens"],
                additional=True,
            ),
        },
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _search_parts_store() -> ToolDecl:
    return ToolDecl(
        name="search_parts_store",
        summary="Search parametric hardware generators in the pinned parts store.",
        params=_obj(
            {"query": _STR, "max_results": {"type": "integer", "minimum": 1, "default": 5}},
            ["query"],
        ),
        result={
            "type": "array",
            "items": _obj(
                {"id": _STR, "name": _STR, "params": _dict(), "preview": _STR},
                ["id", "name"],
                additional=True,
            ),
        },
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _instance_store_part() -> ToolDecl:
    return ToolDecl(
        name="instance_store_part",
        summary="Instance a store generator, returning a placed script fragment.",
        params=_obj(
            {
                "id": _STR,
                "params": _dict(),
                "pos": {"anyOf": [_dict(), {"type": "null"}], "default": None},
            },
            ["id", "params"],
        ),
        result=_ok({"script_fragment": _STR}, ["script_fragment"]),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


def _search_materials() -> ToolDecl:
    return ToolDecl(
        name="search_materials",
        summary="Search the materials registry (density, forms, thicknesses, notes).",
        params=_obj({"query": _STR}, ["query"]),
        result={
            "type": "array",
            "items": _obj(
                {
                    "id": _STR,
                    "name": _STR,
                    "density": _NUM,
                    "forms": {"type": "array", "items": _STR},
                    "thicknesses": {"type": "array"},
                    "notes": _STR,
                },
                ["id", "name"],
                additional=True,
            ),
        },
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


_DELEGATION_TERMINAL = ["failed", "cancelled", "timed_out", "interrupted"]


def _delegate_part_agent() -> ToolDecl:
    return ToolDecl(
        name="delegate_part_agent",
        summary="Delegate a prompt to an existing part's leased session (orchestrator only).",
        params=_obj(
            {
                "part": _ident(),
                "prompt": {"type": "string", "x-hephaestus-maxUtf8Bytes": PROMPT_MAX_UTF8_BYTES},
                "delivery": _enum(["prompt", "follow_up"], "prompt"),
                "deadline_seconds": {
                    "type": "integer",
                    "minimum": DEADLINE_MIN,
                    "maximum": DEADLINE_MAX,
                    "default": DEADLINE_DEFAULT,
                },
            },
            ["part", "prompt"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "completed"},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                    "result_artifact_ref": _STR,
                },
                ["status", "part_session_id", "child_run_id", "delegation_ref"],
            ),
            _ok(
                {
                    "status": {"const": "queued"},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                },
                ["status", "part_session_id", "child_run_id", "delegation_ref"],
            ),
            _ok(
                {
                    "status": {"enum": _DELEGATION_TERMINAL},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                    "error": {},
                },
                ["status", "part_session_id", "child_run_id", "delegation_ref"],
            ),
            _ok(
                {
                    "status": {"const": "rejected"},
                    "reason": _enum(
                        [
                            "part_busy",
                            "queue_full",
                            "no_run_slot",
                            "prompt_too_large",
                            "scope_denied",
                            "session_busy",
                            "invalid_part",
                        ]
                    ),
                    "part_session_id": _STR,
                },
                ["status", "reason"],
            ),
        ),
        profiles=("orchestrator",),
        sequential=True,
        idempotent=True,
        max_utf8_fields={"prompt": PROMPT_MAX_UTF8_BYTES},
    )


def _get_delegation_status() -> ToolDecl:
    return ToolDecl(
        name="get_delegation_status",
        summary="Observe a delegation's queued/running/terminal state (orchestrator).",
        params=_obj({"delegation_ref": _STR}, ["delegation_ref"]),
        result=_result(
            _ok(
                {
                    "status": {"enum": ["queued", "running"]},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                },
                ["status", "delegation_ref"],
            ),
            _ok(
                {
                    "status": {"const": "completed"},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                    "result_artifact_ref": _STR,
                },
                ["status", "delegation_ref"],
            ),
            _ok(
                {
                    "status": {"enum": _DELEGATION_TERMINAL},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                    "error": {},
                },
                ["status", "delegation_ref"],
            ),
        ),
        profiles=("orchestrator",),
        sequential=False,
        idempotent=False,
    )


def _cancel_delegation() -> ToolDecl:
    return ToolDecl(
        name="cancel_delegation",
        summary="Idempotently cancel a queued/running delegation (orchestrator).",
        params=_obj({"delegation_ref": _STR}, ["delegation_ref"]),
        result=_result(
            _ok(
                {
                    "status": {"const": "cancelled"},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                },
                ["status", "delegation_ref"],
            ),
            _ok(
                {
                    "status": {"enum": ["completed", "failed", "timed_out", "interrupted"]},
                    "part_session_id": _STR,
                    "child_run_id": _STR,
                    "delegation_ref": _STR,
                    "result_artifact_ref": _STR,
                    "error": {},
                },
                ["status", "delegation_ref"],
            ),
        ),
        profiles=("orchestrator",),
        sequential=True,
        idempotent=True,
    )


def _ask_user() -> ToolDecl:
    return ToolDecl(
        name="ask_user",
        summary="Structured question; suspends the loop until answered.",
        params=_obj(
            {
                "question": _STR,
                "options": {"type": "array", "items": _STR},
                "allow_free_text": {"type": "boolean", "default": True},
                "multi": {"type": "boolean", "default": False},
            },
            ["question", "options"],
        ),
        result=_ok({"selection": {}}, ["selection"]),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=False,
    )


def _export_part() -> ToolDecl:
    conditional = [
        {
            "if": {"properties": {"layout": {"const": "nested_sheet"}}, "required": ["layout"]},
            "then": {"properties": {"format": {"enum": ["dxf", "svg"]}}},
        },
    ]
    return ToolDecl(
        name="export_part",
        summary="Export a frozen successful build artifact (Stage 2: as_built layout only).",
        params=_obj(
            {
                "name": _ident(),
                "format": _enum(["step", "dxf", "svg", "gltf", "3mf", "stl"]),
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "target": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "layout": _enum(["as_built", "nested_sheet"], "as_built"),
            },
            ["name", "format"],
            extra={"allOf": conditional},
        ),
        result=_ok(
            {
                "paths": {"type": "array", "items": _STR},
                "source_artifact_ref": _STR,
                "source_input_hashes": _dict(),
                "export_hashes": _dict(),
            },
            ["paths", "source_artifact_ref"],
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


TOOLS: Final[tuple[ToolDecl, ...]] = (
    _create_part(),
    _read_part(),
    _edit_part(),
    _write_part(),
    _build_part(),
    _set_params(),
    _read_globals(),
    _edit_globals(),
    _list_project_checks(),
    _create_project_check(),
    _read_project_check(),
    _edit_project_check(),
    _inspect_part(),
    _query_snapshot(),
    _read_artifact(),
    _measure(),
    _run_checks(),
    _load_skill(),
    _list_skills(),
    _search_parts_store(),
    _instance_store_part(),
    _search_materials(),
    _delegate_part_agent(),
    _get_delegation_status(),
    _cancel_delegation(),
    _ask_user(),
    _export_part(),
)

TOOLS_BY_NAME: Final[dict[str, ToolDecl]] = {t.name: t for t in TOOLS}


def tool_names() -> tuple[str, ...]:
    return tuple(t.name for t in TOOLS)


def get_tool(name: str) -> ToolDecl:
    return TOOLS_BY_NAME[name]
