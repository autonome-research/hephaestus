"""Typed declaration of the full Stage 2 tool surface (single source of truth).

This module is the *authoritative* description of every tool in ``tool_schema.md``
that is in Stage 2 scope. :mod:`hephaestus.core.toolgen` renders it to the
committed canonical JSON Schema files (``schemas/tools/*.schema.json``), the Pi
TypeBox module (``agent/src/tools/schema.gen.ts``), and — from Stage 3 — the MCP
declarations. Those artifacts, this declaration, and the ``tool_schema.md``
headings are drift-tested against each other in CI.

Scope: the full ``tool_schema.md`` surface **except** the deferred ``run_fea`` /
``import_geometry``. ``run_dfm``, ``generate_drawing`` and ``generate_doc``
joined the surface with mission Stage 6. ``export_part`` keeps
``layout="nested_sheet"`` in the schema (permitted only with
``format="dxf"|"svg"``).

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
from typing import Any, Final, cast

__all__ = [
    "IDENT_PATTERN",
    "PROFILES",
    "REQUIREMENT_ID_PATTERN",
    "REQUIREMENT_SOURCES",
    "REVIEWER_TOOLS",
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

# Requirement-ledger entry ids (VALIDATION.md §2): "R1", "R12b", "wall_dir".
# Case-sensitive and deliberately wider than IDENT_PATTERN — a ledger id is a
# citation token that appears verbatim in CHECKS comments, not a filesystem name.
REQUIREMENT_ID_PATTERN: Final[str] = r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$"
# The three provenance classes a ledger entry may declare (VALIDATION.md §2).
REQUIREMENT_SOURCES: Final[tuple[str, ...]] = ("specified", "derived", "assumed")

Profile = str  # one of PROFILES
# ``reviewer`` (VALIDATION.md §5) is the independent termination-review child: a
# read-only measurement/render subset. Its availability is declared here, per
# tool, exactly like every other profile — the reviewer's inability to mutate the
# project is a property of this table, not of its prompt.
PROFILES: Final[tuple[str, ...]] = ("part", "orchestrator", "quick_edit", "reviewer")
#: The measurement/render subset a ``reviewer`` session may call (VALIDATION.md
#: §5). Declared as data so the structural "no mutation, no delegation" audit has
#: one place to read; every member also names ``reviewer`` in its ``profiles``.
REVIEWER_TOOLS: Final[frozenset[str]] = frozenset({"inspect_part", "measure", "read_artifact"})

# Documented in tool_schema.md but explicitly out of Stage 2 scope; the drift
# test subtracts these from the heading set before comparing with TOOLS.
STAGE2_EXCLUDED_TOOLS: Final[frozenset[str]] = frozenset({"run_fea", "import_geometry"})

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


def _capability(code: str) -> JsonSchema:
    """The discriminated ``capability_error`` result variant for one code.

    A capability refusal is a *successful, discriminated* tool result the model
    can branch on (``status == "capability_error"`` plus a stable ``code``) — it
    is never a transport error, so every tool that can refuse must declare it.
    """
    return _ok(
        {
            "status": {"const": "capability_error"},
            "code": {"const": code},
            "message": _STR,
        },
        ["status", "code"],
    )


#: Stage-deferred capability refusal (``export_part`` nested_sheet, store
#: generators without a probed sandbox).
_CAPABILITY_NOT_AVAILABLE: Final[JsonSchema] = _capability("capability_not_available")


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
        result=_result(
            _ok(
                {
                    "status": _STR,
                    "artifact_ref": _STR,
                    "current": _BOOL,
                    "project_snapshot_ref": _STR,
                    "effective_params": _dict(),
                    "toolchain_hashes": _dict(),
                    "critique": _CRITIQUE,
                },
                ["status"],
            ),
            _CLARIFICATION_REQUIRED,
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
        profiles=("part", "orchestrator", "quick_edit", "reviewer"),
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
            _CAPABILITY_NOT_AVAILABLE,
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
        profiles=("part", "orchestrator", "quick_edit", "reviewer"),
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
        profiles=("part", "orchestrator", "quick_edit", "reviewer"),
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
        result=_result(
            _ok({"script_fragment": _STR}, ["script_fragment"]),
            _CAPABILITY_NOT_AVAILABLE,
        ),
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


#: One concrete option of a clarification question (``VALIDATION.md`` §3): a
#: label and **the geometric consequence of choosing it**. The consequence is a
#: required field, not a convention, so "what did you mean?" cannot be asked
#: about a material assumption — the runtime refuses the question instead.
_CLARIFICATION_OPTION: Final[JsonSchema] = _obj(
    {"label": _STR, "consequence": _STR},
    ["label", "consequence"],
)

#: ``ask_user`` refusing to put a badly-shaped clarification to the user. It is a
#: discriminated *result* (the model corrects and re-asks), never an error, and
#: it is returned before any human is disturbed.
_INVALID_QUESTION: Final[JsonSchema] = _ok(
    {
        "status": {"const": "invalid_question"},
        "code": {"const": "clarification_question_shape"},
        "message": _STR,
        "problems": {"type": "array", "items": _STR},
    },
    ["status", "code", "message", "problems"],
)


def _ask_user() -> ToolDecl:
    return ToolDecl(
        name="ask_user",
        summary="Structured question; suspends the loop until answered.",
        params=_obj(
            {
                "question": _STR,
                "options": {
                    "type": "array",
                    "items": {"anyOf": [_STR, _CLARIFICATION_OPTION]},
                },
                "allow_free_text": {"type": "boolean", "default": True},
                "multi": {"type": "boolean", "default": False},
                "requirement_ids": {
                    "type": "array",
                    "items": {"type": "string", "pattern": REQUIREMENT_ID_PATTERN},
                    "default": [],
                },
            },
            ["question", "options"],
        ),
        result=_result(
            _ok({"selection": {}, "recorded": {"type": "array"}}, ["selection"]),
            _INVALID_QUESTION,
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=False,
    )


#: One requirement-ledger entry (``VALIDATION.md`` §2). The per-source
#: obligations (``specified`` needs ``quote``; ``derived`` needs ``from``;
#: ``assumed`` needs ``rationale`` + ``material``) are enforced structurally by
#: the ledger op, which refuses the whole batch — they are not prompt advice.
_REQUIREMENT_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": {"type": "string", "pattern": REQUIREMENT_ID_PATTERN},
        "text": _STR,
        "source": _enum(list(REQUIREMENT_SOURCES)),
        "quote": {"anyOf": [_STR, {"type": "null"}], "default": None},
        "from": {"type": "array", "items": _STR, "default": []},
        "rationale": {"anyOf": [_STR, {"type": "null"}], "default": None},
        "material": {"anyOf": [_BOOL, {"type": "null"}], "default": None},
        "value": {"anyOf": [_NUM, {"type": "null"}], "default": None},
        "unit": {"anyOf": [_STR, {"type": "null"}], "default": None},
        "applies_to": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    ["id", "text", "source"],
)

#: The same entry as it is *reported*: lenient, and carrying the two §3 fields a
#: clarification writes back (``asked`` when a question was raised, ``resolution``
#: when it was answered). Reporting is a strict superset of what a caller may
#: declare — those two are readable everywhere and writable only by the runtime.
_REQUIREMENT_ENTRY_OUT: Final[JsonSchema] = _ok(
    {
        **cast("dict[str, JsonSchema]", _REQUIREMENT_ENTRY["properties"]),
        "asked": _BOOL,
        "resolution": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "text", "source"],
)

#: The single result shape all three ledger tools share: the generation that is
#: now current, its immutable artifact ref, every entry, and the ids of material
#: assumptions still unresolved (what the §3 clarification gate blocks on).
_LEDGER_RESULT: Final[JsonSchema] = _ok(
    {
        "status": {"const": "ok"},
        "generation": _INT,
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
        "entries": {"type": "array", "items": _REQUIREMENT_ENTRY_OUT},
        "unresolved_material": {"type": "array", "items": _STR},
    },
    ["status", "generation", "artifact_ref", "entries", "unresolved_material"],
)

#: ``VALIDATION.md`` §3: the clarification gate's refusal of ``build_part``. It
#: is a discriminated result rather than an error because refusing to build on an
#: unconfirmed material assumption is a *normal outcome* the model must handle —
#: it carries the offending entries so the follow-up question can be written
#: straight from them. Consumed by ``_build_part`` below (module order is
#: irrelevant: the tool constructors run when ``TOOLS`` is built).
_CLARIFICATION_REQUIRED: Final[JsonSchema] = _ok(
    {
        "status": {"const": "clarification_required"},
        "generation": _INT,
        "entries": {"type": "array", "items": _REQUIREMENT_ENTRY_OUT},
        "unresolved_material": {"type": "array", "items": _STR},
        "message": _STR,
    },
    ["status", "entries", "message"],
)

#: One §4 critique warning. ``kind`` is the stable machine token
#: (``interference``, ``interference_pairs_capped``, ``interference_unavailable``,
#: ``not_sealed``, ``unmatched_request_number``, ``dimension_mismatch``); the
#: rest of each object is per-kind evidence, so the shape stays open.
_CRITIQUE_WARNING: Final[JsonSchema] = _ok({"kind": _STR, "message": _STR}, ["kind"])
_CRITIQUE_WARNINGS: Final[JsonSchema] = {"type": "array", "items": _CRITIQUE_WARNING}

#: ``VALIDATION.md`` §4: the post-build critique nobody asked for. It rides on
#: every *successful* ``build_part`` result and is computed by rule from the
#: build's own outputs — no extra tool call, no prompt instruction, no model
#: choice. ``warnings`` is the flattened union of the three sections' warnings.
#: ``prompt_number_diff`` is **absent** when the runtime holds no original
#: request text; it is never fabricated.
_CRITIQUE: Final[JsonSchema] = _ok(
    {
        "interference": _ok(
            {
                "solids": _INT,
                "pairs_total": _INT,
                "pairs_measured": _INT,
                "pairs_capped": _BOOL,
                "declared_intentional": {"type": "array", "items": _STR},
                "overlaps": {
                    "type": "array",
                    "items": _ok({"a": _STR, "b": _STR, "volume_mm3": _NUM}, ["a", "b"]),
                },
                "warnings": _CRITIQUE_WARNINGS,
            },
            ["solids", "pairs_total", "pairs_measured", "pairs_capped", "warnings"],
        ),
        "manifold": _ok(
            {
                "available": _BOOL,
                "sealed": _BOOL,
                "genus": _INT,
                "solids": _INT,
                "warnings": _CRITIQUE_WARNINGS,
            },
            ["available", "warnings"],
        ),
        "prompt_number_diff": _ok(
            {
                "numbers": {
                    "type": "array",
                    "items": _ok(
                        {
                            "value_mm": _NUM,
                            "unit": _STR,
                            "text": _STR,
                            "axis": {"anyOf": [_STR, {"type": "null"}]},
                            "matched": _BOOL,
                            "compared_to": _STR,
                            "dimension_mm": _NUM,
                        },
                        ["value_mm", "unit", "text", "axis"],
                    ),
                },
                "dimensions": _dict(_NUM),
                "warnings": _CRITIQUE_WARNINGS,
            },
            ["numbers", "dimensions", "warnings"],
        ),
        "warnings": _CRITIQUE_WARNINGS,
    },
    ["interference", "manifold", "warnings"],
)


def _record_requirements() -> ToolDecl:
    return ToolDecl(
        name="record_requirements",
        summary="Record requirement-ledger entries (upsert by id); advances one generation.",
        params=_obj(
            {"entries": {"type": "array", "items": _REQUIREMENT_ENTRY, "minItems": 1}},
            ["entries"],
        ),
        result=_LEDGER_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _read_requirements() -> ToolDecl:
    return ToolDecl(
        name="read_requirements",
        summary="Read the current requirement ledger generation and its open assumptions.",
        params=_obj({}, []),
        result=_LEDGER_RESULT,
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


def _update_requirement() -> ToolDecl:
    return ToolDecl(
        name="update_requirement",
        summary="Patch one ledger entry (text, material flag, value, unit); one generation.",
        # `asked`/`resolution` are deliberately absent: the clarification record is
        # written by the runtime from a real ask_user answer, never by the caller
        # (VALIDATION.md §3). Supplying one is refused with `invalid_requirement`.
        params=_obj(
            {
                "id": {"type": "string", "pattern": REQUIREMENT_ID_PATTERN},
                "text": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "source": {
                    "anyOf": [_enum(list(REQUIREMENT_SOURCES)), {"type": "null"}],
                    "default": None,
                },
                "quote": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "from": {
                    "anyOf": [{"type": "array", "items": _STR}, {"type": "null"}],
                    "default": None,
                },
                "rationale": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "material": {"anyOf": [_BOOL, {"type": "null"}], "default": None},
                "value": {"anyOf": [_NUM, {"type": "null"}], "default": None},
                "unit": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "applies_to": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["id"],
        ),
        result=_LEDGER_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


#: One artifact-bound topology address a finding points at (§ run_dfm). Never a
#: mutable mask id: ``solid_id``/``topology_index`` enumerate the *artifact*.
_TOPOLOGY_DESCRIPTOR: Final[JsonSchema] = _obj(
    {
        "kind": _enum(["solid", "face", "edge", "wire", "vertex", "other"]),
        "solid_id": _INT,
        "topology_index": _INT,
        "tag": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["kind", "solid_id", "topology_index"],
    additional=True,
)

_DFM_FINDING: Final[JsonSchema] = _obj(
    {
        "rule_id": _STR,
        "severity": _enum(["error", "warning", "info"]),
        "title": _STR,
        "message": _STR,
        "process": _STR,
        "source_artifact_ref": _STR,
        "tags": {"type": "array", "items": _STR},
        "topology": {"type": "array", "items": _TOPOLOGY_DESCRIPTOR},
        "measured": {},
        "suggested_bound": {"anyOf": [_NUM, {"type": "null"}]},
        "bound_unit": _STR,
    },
    ["rule_id", "severity", "title", "message", "source_artifact_ref", "topology"],
    additional=True,
)

_DFM_RULE_OUTCOME: Final[JsonSchema] = _obj(
    {
        "rule_id": _STR,
        "title": _STR,
        "severity": _STR,
        "status": _enum(["ok", "violations", "error"]),
        "findings": {"type": "array", "items": _DFM_FINDING},
        "params": _dict(_NUM),
        "error": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["rule_id", "status"],
    additional=True,
)


def _run_dfm() -> ToolDecl:
    conditional = [
        # One artifact resolution mode at a time: an explicit artifact ref and a
        # project snapshot cannot both name the geometry to check.
        {"not": {"required": ["artifact_ref", "project_snapshot_ref"]}},
    ]
    return ToolDecl(
        name="run_dfm",
        summary="Run the process rule pack against a resolved artifact; report findings.",
        params=_obj(
            {
                "name": _ident(),
                "process": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "project_snapshot_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["name"],
            extra={"allOf": conditional},
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "part": _STR,
                    "process": _STR,
                    "source_artifact_ref": _STR,
                    "resolved_from": _enum(["current", "artifact_ref", "project_snapshot"]),
                    "pack": _obj(
                        {
                            "name": _STR,
                            "version": _STR,
                            "registry": _STR,
                            "registry_digest": _STR,
                        },
                        [],
                        additional=True,
                    ),
                    "rules": {"type": "array", "items": _DFM_RULE_OUTCOME},
                    "findings": {"type": "array", "items": _DFM_FINDING},
                    "severity_counts": _dict(_INT),
                    "errored_rules": {"type": "array", "items": _STR},
                    "truncated": _BOOL,
                    "material": {},
                },
                ["status", "part", "process", "source_artifact_ref", "findings"],
            ),
            _CAPABILITY_NOT_AVAILABLE,
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=False,
        idempotent=False,
    )


#: The declared stock rectangle a ``nested_sheet`` export nests onto. Omitted,
#: the blank is read from the part's ``part.blank_size`` metadata; supplied, it
#: overrides it. Margin/spacing default in the nesting module, never here.
_BLANK: Final[JsonSchema] = _obj(
    {
        "width_mm": {"type": "number", "exclusiveMinimum": 0},
        "height_mm": {"type": "number", "exclusiveMinimum": 0},
        "margin_mm": {"type": "number", "minimum": 0},
        "spacing_mm": {"type": "number", "minimum": 0},
    },
    ["width_mm", "height_mm"],
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
        summary="Export a frozen successful build artifact (as_built or nested_sheet layout).",
        params=_obj(
            {
                "name": _ident(),
                "format": _enum(["step", "dxf", "svg", "gltf", "3mf", "stl"]),
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "target": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "layout": _enum(["as_built", "nested_sheet"], "as_built"),
                "blank": {"anyOf": [_BLANK, {"type": "null"}], "default": None},
            },
            ["name", "format"],
            extra={"allOf": conditional},
        ),
        result=_result(
            _ok(
                {
                    "paths": {"type": "array", "items": _STR},
                    "source_artifact_ref": _STR,
                    "source_input_hashes": _dict(),
                    "export_hashes": _dict(),
                },
                ["paths", "source_artifact_ref"],
            ),
            _CAPABILITY_NOT_AVAILABLE,
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


#: One drawn dimension: the text that appears on the sheet plus what it measures.
#: ``text`` is the exact string the PDF text layer carries (the G6 gate extracts
#: it), ``value``/``unit`` the machine-readable measurement behind it.
_DRAWN_DIMENSION: Final[JsonSchema] = _obj(
    {
        "id": _STR,
        "label": _STR,
        "text": _STR,
        "value": _NUM,
        "unit": _STR,
        "kind": _enum(["linear", "diameter", "thickness"]),
    },
    ["id", "label", "text", "value", "kind"],
    additional=True,
)


def _generate_drawing() -> ToolDecl:
    return ToolDecl(
        name="generate_drawing",
        summary="Dimensioned/assembly/exploded PDF+SVG drawing of a frozen build artifact.",
        params=_obj(
            {
                "name": _ident(),
                "kind": _enum(["dimensioned", "assembly", "exploded"], "dimensioned"),
                "sheet": _enum(["A4", "A3", "letter"], "A4"),
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "target": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["name", "kind"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "pdf": _STR,
                    "svg": _STR,
                    "paths": {"type": "array", "items": _STR},
                    "source_artifact_ref": _STR,
                    "source_input_hashes": _dict(),
                    "export_hashes": _dict(),
                    "kind": _STR,
                    "sheet": _STR,
                    "views": {"type": "array", "items": _STR},
                    "dimensions": {"type": "array", "items": _DRAWN_DIMENSION},
                    "title_block": _dict(_STR),
                    "replayed": _BOOL,
                },
                ["status", "pdf", "svg", "paths", "source_artifact_ref"],
            ),
            _CAPABILITY_NOT_AVAILABLE,
        ),
        profiles=("part", "orchestrator", "quick_edit"),
        sequential=True,
        idempotent=True,
    )


def _generate_doc() -> ToolDecl:
    return ToolDecl(
        name="generate_doc",
        summary="BOM / assembly instructions / spec for a frozen build artifact (md + JSON).",
        params=_obj(
            {
                "name": _ident(),
                "kind": _enum(["bom", "assembly_instructions", "spec"], "bom"),
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}], "default": None},
                "target": {"anyOf": [_STR, {"type": "null"}], "default": None},
            },
            ["name", "kind"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "markdown": _STR,
                    "markdown_truncated": _BOOL,
                    "doc": _STR,
                    "json": _STR,
                    "paths": {"type": "array", "items": _STR},
                    "source_artifact_ref": _STR,
                    "source_input_hashes": _dict(),
                    "export_hashes": _dict(),
                    "kind": _STR,
                    "items": _INT,
                    "replayed": _BOOL,
                },
                ["status", "markdown", "paths", "source_artifact_ref"],
            ),
            _CAPABILITY_NOT_AVAILABLE,
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
    _record_requirements(),
    _read_requirements(),
    _update_requirement(),
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
    _run_dfm(),
    _generate_drawing(),
    _generate_doc(),
)

TOOLS_BY_NAME: Final[dict[str, ToolDecl]] = {t.name: t for t in TOOLS}


def tool_names() -> tuple[str, ...]:
    return tuple(t.name for t in TOOLS)


def get_tool(name: str) -> ToolDecl:
    return TOOLS_BY_NAME[name]
