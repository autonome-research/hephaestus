"""Typed declaration of the full Stage 2 tool surface (single source of truth).

This module is the *authoritative* description of every tool in ``tool_schema.md``
that is in Stage 2 scope. :mod:`hephaestus.contract.toolgen` renders it to the
committed canonical JSON Schema files (``schemas/tools/*.schema.json``), the Pi
TypeBox module (``agent/src/tools/schema.gen.ts``), and — from Stage 3 — the MCP
declarations. Those artifacts, this declaration, and the ``tool_schema.md``
headings are drift-tested against each other in CI.

Scope: the full ``tool_schema.md`` surface **except** the deferred ``run_fea`` /
``import_geometry``. ``run_dfm``, ``generate_drawing`` and ``generate_doc``
joined the surface with mission Stage 6; the ``ASSEMBLY.md`` §3 constraint
quartet (``declare_constraint`` / ``update_constraint`` / ``read_constraints`` /
``check_assembly``) joined with Stage 8C. ``export_part`` keeps
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
    "CONSTRAINT_ANCHOR_PATTERN",
    "CONSTRAINT_ID_PATTERN",
    "CONSTRAINT_KINDS",
    "CONSTRAINT_PARAMS",
    "CONSTRAINT_STATES",
    "IDENT_PATTERN",
    "JOINT_ID_PATTERN",
    "JOINT_KINDS",
    "MOTION_OUTCOME_STATES",
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
#: ``list_references``/``read_reference`` joined with INGEST.md §2: an image
#: citation is lint-unverifiable, so the §5 reviewer is the only thing that can
#: verify it — and it can only do that by opening the drawing itself.
REVIEWER_TOOLS: Final[frozenset[str]] = frozenset(
    {"inspect_part", "measure", "read_artifact", "list_references", "read_reference"}
)

# Documented in tool_schema.md but explicitly out of Stage 2 scope; the drift
# test subtracts these from the heading set before comparing with TOOLS.
STAGE2_EXCLUDED_TOOLS: Final[frozenset[str]] = frozenset({"run_fea", "import_geometry"})

JsonSchema = dict[str, Any]


def _find_limits_file() -> Path:
    """Locate ``schemas/bridge_limits.json``: override, then packaged, then repo.

    The packaged branch is what makes an installed wheel work. This module reads
    the file at *import* time (the delegation deadline bounds below are module
    constants), and the repo walk-up climbs out of ``site-packages`` and finds
    nothing, so before Stage 7H a wheel failed on ``import hephaestus.contract``.
    ``hephaestus-contract`` declares no dependencies, so it carries its own
    staged copy (see ``contract/hatch_build.py``) rather than importing
    ``hephaestus.core`` for one.
    """
    import os
    from importlib import resources

    override = os.environ.get("HEPHAESTUS_BRIDGE_LIMITS")
    if override:
        return Path(override)

    packaged = (
        Path(str(resources.files(__package__ or "hephaestus.contract")))
        / "_data"
        / "bridge_limits.json"
    )
    if packaged.is_file():
        return packaged

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "schemas" / "bridge_limits.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"schemas/bridge_limits.json not found: no packaged copy at {packaged}, "
        f"and none above {here}"
    )


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


#: ``COMPARE.md`` §1 records, as the tool reports them. The nesting is the
#: record's own (``dataclasses.asdict(SolidDiff)``) so the wire shape cannot
#: drift from the geometry layer's definition; every leaf is a fact, and
#: ``align`` is repeated on the sub-records that it actually affects.
_VOLUME_DIFF: Final[JsonSchema] = _obj(
    {
        "common_mm3": _NUM,
        "a_only_mm3": _NUM,
        "b_only_mm3": _NUM,
        "iou": _NUM,
        "align": _STR,
    },
    ["common_mm3", "a_only_mm3", "b_only_mm3", "iou", "align"],
    additional=True,
)

_SURFACE_DISTANCE: Final[JsonSchema] = _obj(
    {
        "a_to_b_mean_mm": _NUM,
        "b_to_a_mean_mm": _NUM,
        "chamfer_mm": _NUM,
        "max_deviation_mm": _NUM,
        # Reported, never optional: a chamfer computed from four points is not
        # the same claim as one computed from four thousand (COMPARE.md §1).
        "a_samples": _INT,
        "b_samples": _INT,
        "align": _STR,
    },
    [
        "a_to_b_mean_mm",
        "b_to_a_mean_mm",
        "chamfer_mm",
        "max_deviation_mm",
        "a_samples",
        "b_samples",
        "align",
    ],
    additional=True,
)

_TOPOLOGY_CENSUS: Final[JsonSchema] = _obj(
    {
        "solids": _INT,
        "faces": _INT,
        "edges": _INT,
        "planar_faces": _INT,
        "cylindrical_faces": _INT,
        "other_faces": _INT,
        "genus": _INT,
        "sealed": _BOOL,
    },
    ["solids", "faces", "edges", "genus", "sealed"],
    additional=True,
)

_TOPOLOGY_DIFF: Final[JsonSchema] = _obj(
    {
        "a": _TOPOLOGY_CENSUS,
        "b": _TOPOLOGY_CENSUS,
        "solids_delta": _INT,
        "faces_delta": _INT,
        "edges_delta": _INT,
        "planar_faces_delta": _INT,
        "cylindrical_faces_delta": _INT,
        "other_faces_delta": _INT,
        "genus_delta": _INT,
        "sealed_changed": _BOOL,
    },
    ["a", "b", "solids_delta", "faces_delta", "edges_delta", "genus_delta", "sealed_changed"],
    additional=True,
)

_TRIPLE: Final[JsonSchema] = {
    "type": "array",
    "items": _NUM,
    "minItems": 3,
    "maxItems": 3,
}

_SOLID_DIFF: Final[JsonSchema] = _obj(
    {
        "align": _STR,
        "volume": _VOLUME_DIFF,
        "surface": _SURFACE_DISTANCE,
        "topology": _TOPOLOGY_DIFF,
        "a_bbox_mm": _TRIPLE,
        "b_bbox_mm": _TRIPLE,
        "a_volume_mm3": _NUM,
        "b_volume_mm3": _NUM,
    },
    ["align", "volume", "surface", "topology", "a_volume_mm3", "b_volume_mm3"],
    additional=True,
)


def _compare_solids() -> ToolDecl:
    return ToolDecl(
        name="compare_solids",
        summary="Solid diff between a part and a part:/import: target (volume, surface, topology).",
        params=_obj(
            {
                "part": _ident(),
                "target": _STR,
                # COMPARE.md §1: alignment is a declared choice, never a silent
                # normalization, so it has a default but no implicit meaning —
                # the answer always names the mode it was computed in.
                "align": _enum(["as_posed", "principal"], "as_posed"),
            },
            ["part", "target"],
        ),
        result=_ok(
            {
                "status": {"const": "ok"},
                "align": _STR,
                "a": _obj(
                    {"kind": {"const": "part"}, "name": _STR, "artifact_ref": _STR},
                    ["kind", "name", "artifact_ref"],
                    additional=True,
                ),
                # An import target is attributed to the content hash it was read
                # at, so a comparison can be re-run against the same bytes.
                "b": _obj(
                    {
                        "kind": _enum(["part", "import"]),
                        "name": _STR,
                        "path": _STR,
                        "artifact_ref": _STR,
                        "sha256": _STR,
                        "snapshot_ref": _STR,
                    },
                    ["kind"],
                    additional=True,
                ),
                "diff": _SOLID_DIFF,
                "resolved_artifact_refs": {"type": "array", "items": _STR},
            },
            ["status", "align", "a", "b", "diff"],
        ),
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


#: The ``MESH_INGEST.md`` §6.4 ``ScanDistance``, as the tool returns it. The
#: two fields it deliberately LACKS are the design: no ``iou`` (an IoU needs a
#: solid on both sides, and getting one from a scan means a sew whose validity
#: gate refuses most real scans) and no ``chamfer_mm`` (one direction may be an
#: upper bound, and the mean of an exact number and a bound has no defined
#: meaning). The two directions are reported separately, always, with the method
#: that produced each.
_SCAN_DISTANCE: Final[JsonSchema] = _obj(
    {
        "align": _enum(["as_posed", "declared"]),
        "declared_transform": {"anyOf": [{"type": "array", "items": _NUM}, {"type": "null"}]},
        "scan_to_part_mean_mm": _NUM,
        "scan_to_part_max_mm": _NUM,
        "scan_to_part_min_mm": _NUM,
        "scan_samples": _INT,
        "part_to_scan_mean_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "part_to_scan_max_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "part_to_scan_upper_bound_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "part_to_scan_method": _enum(["kdtree_bound_exact_triangle", "vertex_nn_upper_bound"]),
        "part_to_scan_bias": _enum(["exact", "over"]),
        "part_to_scan_refusal": {"anyOf": [_STR, {"type": "null"}]},
        "part_samples": _INT,
        "scan_canonical_hash": _STR,
        "part_artifact_ref": _STR,
    },
    [
        "align",
        "scan_to_part_mean_mm",
        "scan_to_part_max_mm",
        "scan_to_part_min_mm",
        "scan_samples",
        "part_to_scan_method",
        "part_samples",
    ],
    additional=True,
)


def _compare_to_scan() -> ToolDecl:
    return ToolDecl(
        name="compare_to_scan",
        summary="Scan-distance between a part and a scan: mesh under imports/ (both directions).",
        params=_obj(
            {
                "part": _ident(),
                "scan": _STR,
                # MESH_INGEST.md §1.3: STL/PLY/OBJ/OFF/XYZ carry no unit and the
                # engine is millimetres throughout, so the unit is DECLARED or
                # the file is refused. It is required here — a default would be
                # the harness guessing a scale on the operator's behalf at
                # exactly the size where the guess is plausible and wrong.
                "units": _enum(["mm", "cm", "m", "in"]),
                # §6.5: 'principal' is absent from the enum because it is
                # refused, not defaulted away — principal_alignment needs a
                # shape with volume, and a limb scan is always partial.
                "align": _enum(["as_posed", "declared"], "as_posed"),
                "declared_transform": {
                    "anyOf": [
                        {"type": "array", "items": _NUM, "minItems": 16, "maxItems": 16},
                        {"type": "null"},
                    ],
                    "default": None,
                },
            },
            ["part", "scan", "units"],
        ),
        result=_ok(
            {
                "status": {"const": "ok"},
                "align": _STR,
                "part": _obj(
                    {"kind": {"const": "part"}, "name": _STR, "artifact_ref": _STR},
                    ["kind", "name"],
                    additional=True,
                ),
                # Two hashes, because they answer different questions (§1.4):
                # ``sha256`` is the file's identity, ``canonical_hash`` is the
                # geometry's, and two runs can say "the file changed, the
                # geometry did not".
                "scan": _obj(
                    {
                        "kind": {"const": "scan"},
                        "path": _STR,
                        "units": _STR,
                        "sha256": _STR,
                        "canonical_hash": _STR,
                        "snapshot_ref": _STR,
                    },
                    ["kind", "path", "units", "sha256", "canonical_hash"],
                    additional=True,
                ),
                "distance": _SCAN_DISTANCE,
                "quality": _dict(),
                "resolved_artifact_refs": {"type": "array", "items": _STR},
            },
            ["status", "align", "part", "scan", "distance", "quality"],
        ),
        profiles=("part", "orchestrator"),
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


#: One registered reference as ``list_references`` reports it (INGEST.md §2).
_REFERENCE_LISTING: Final[JsonSchema] = _obj(
    {
        "name": _STR,
        "kind": _enum(["document", "image"]),
        "mime_type": _STR,
        "sha256": _STR,
        "bytes": _INT,
        "pages": _INT,
        "artifact_ref": _STR,
    },
    ["name", "kind", "sha256"],
    additional=True,
)


def _list_references() -> ToolDecl:
    return ToolDecl(
        name="list_references",
        summary="List operator-supplied reference documents and images (read-only).",
        params=_obj({}, []),
        result={"type": "array", "items": _REFERENCE_LISTING},
        profiles=("part", "orchestrator", "reviewer"),
        sequential=False,
        idempotent=False,
    )


def _read_reference() -> ToolDecl:
    return ToolDecl(
        name="read_reference",
        summary="Read one reference: delimited document text (paged) or an inline image.",
        params=_obj(
            {
                "name": _STR,
                "page": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
                "offset_bytes": {"type": "integer", "minimum": 0, "default": 0},
            },
            ["name"],
        ),
        result=_result(
            _ok(
                {
                    "status": {"const": "ok"},
                    "name": _STR,
                    "kind": {"const": "document"},
                    "mime_type": _STR,
                    "artifact_ref": _STR,
                    "content": _STR,
                    "page": _INT,
                    "pages": _INT,
                    "offset_bytes": _INT,
                    "total_bytes": _INT,
                    **_PAGING_FIELDS,
                },
                ["status", "name", "kind", "content", "artifact_ref", "truncated"],
            ),
            _ok(
                {
                    "status": {"const": "ok"},
                    "name": _STR,
                    "kind": {"const": "image"},
                    "mime_type": _STR,
                    "artifact_ref": _STR,
                    "images": {
                        "type": "array",
                        "items": _obj(
                            {"data": _STR, "mime_type": _STR},
                            ["data", "mime_type"],
                            additional=True,
                        ),
                        "maxItems": MAX_IMAGES_PER_RESULT,
                    },
                },
                ["status", "name", "kind", "images", "artifact_ref"],
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
        profiles=("part", "orchestrator", "reviewer"),
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
                {
                    "id": _STR,
                    "name": _STR,
                    "params": _dict(),
                    "preview": _STR,
                    # PARTS_STORE.md §3: present for a *component* record only,
                    # absent for a legacy store part — which is why none of them
                    # is required. Interface names are as declared, unprefixed:
                    # the instance prefix is not known until instantiation.
                    "component_class": _STR,
                    "series": _dict(),
                    "interfaces": {
                        "type": "array",
                        "items": _obj(
                            {"name": _STR, "class": _STR, "role": _STR},
                            ["name", "class", "role"],
                        ),
                    },
                    "mass_g": _NUM,
                    "has_datasheet": _BOOL,
                },
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
                # PARTS_STORE.md §2.2: the scope of this instance's emitted
                # interface tags. Absent means the deterministic
                # `instance_prefix(id, params, pos)`, so two instances differing
                # in any of those three are already distinct; `instance` is the
                # escape hatch for pasting the SAME instance twice, which is
                # otherwise a `duplicate_tag` build failure.
                "instance": {"anyOf": [_ident(), {"type": "null"}], "default": None},
            },
            ["id", "params"],
        ),
        result=_result(
            # `mass` and `datasheet` are the declared blocks verbatim
            # (PARTS_STORE.md §3, §5, §7.3), present only for a component
            # record. Neither is a measurement and neither is required.
            # `interfaces` carries the EMITTED names — `<instance>__<name>` —
            # because those, not the declared ones, are what an 8C anchor or a
            # Stage 9 joint spells.
            #
            # `claims` is a STRING, not an array, and that is the point
            # (PARTS_STORE.md §6.3): no part of Hephaestus can evaluate a
            # torque-speed curve, so a datasheet claim reaches the model wrapped
            # in the same provenance delimiters registry text uses, whose footer
            # restates that it is reference material and not instructions.
            # Handing back a bare JSON array beside `metrics` would give a vendor
            # assertion the shape, and so the standing, of a measurement.
            _ok(
                {
                    "script_fragment": _STR,
                    "interfaces": {"type": "array", "items": _STR},
                    "mass": _dict(),
                    "datasheet": _dict(),
                    "claims": _STR,
                },
                ["script_fragment"],
            ),
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


#: ``INGEST.md`` §2: a ``specified`` entry may cite an operator-supplied
#: reference instead of a phrase of the request. ``reference`` names a registered
#: reference, ``page`` is 1-based (documents only) and ``quote`` is the cited
#: text — verified against the extracted text by ``heph lint`` for a document,
#: and routed to the §5 vision reviewer for an image.
#:
#: ``PARTS_STORE.md`` §7.4 adds ``component`` and ``claim``, naming *what the
#: quote transcribes*: a component record's claim id. Both are present or both
#: absent (``incomplete_component_cite``), and an unknown component id or claim
#: id is ``invalid_requirement`` with nothing written — the existing refusal on
#: the existing path. They are what makes the store⇄project provenance join
#: **operator-declared** rather than inferred from digest co-incidence, and so
#: what makes ``datasheet_digest_mismatch`` a rule that can both fire and stay
#: silent.
_REQUIREMENT_CITE: Final[JsonSchema] = _obj(
    {
        "reference": _STR,
        "page": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}], "default": None},
        "quote": _STR,
        "component": {"anyOf": [_STR, {"type": "null"}], "default": None},
        "claim": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    ["reference", "quote"],
)

#: One requirement-ledger entry (``VALIDATION.md`` §2). The per-source
#: obligations (``specified`` needs ``quote`` **or** an ``INGEST.md`` §2
#: ``cite``; ``derived`` needs ``from``; ``assumed`` needs ``rationale`` +
#: ``material``) are enforced structurally by the ledger op, which refuses the
#: whole batch — they are not prompt advice.
_REQUIREMENT_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": {"type": "string", "pattern": REQUIREMENT_ID_PATTERN},
        "text": _STR,
        "source": _enum(list(REQUIREMENT_SOURCES)),
        "quote": {"anyOf": [_STR, {"type": "null"}], "default": None},
        "cite": {"anyOf": [_REQUIREMENT_CITE, {"type": "null"}], "default": None},
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

#: One **binding** §4 dimension finding (``VALIDATION.md`` §4, "Dimension findings
#: are BINDING"). ``id`` is what an ``ask_user(requirement_ids=[…])`` question must
#: name for a user to dismiss one; ``status`` is ``open`` while it blocks
#: termination and ``cleared``/``dismissed`` once a matching rebuild or a
#: runtime-recorded dismissal closed it. Written by the runtime only — no tool
#: writes this, which is why its presence is evidence rather than a claim.
_DIMENSION_FINDING: Final[JsonSchema] = _ok(
    {
        "id": _STR,
        "part": _STR,
        "kind": _STR,
        "request_value_mm": _NUM,
        "request_text": _STR,
        "message": _STR,
        "axis": {"anyOf": [_STR, {"type": "null"}]},
        "dimension": {"anyOf": [_STR, {"type": "null"}]},
        "dimension_value_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "status": _enum(["open", "cleared", "dismissed"]),
        "asked": _BOOL,
        "dismissal": {"anyOf": [_STR, {"type": "null"}]},
        "closed_by": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "part", "kind", "request_value_mm", "status"],
)

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
        # Present when this build could bind its number diff: a published (non-
        # preview) build with request text in hand. Absent means "nothing was
        # bound here", never "clean" — the same rule as prompt_number_diff.
        "dimension_findings": _ok(
            {
                "generation": _INT,
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
                "open": {"type": "array", "items": _DIMENSION_FINDING},
                "cleared": {"type": "array", "items": _DIMENSION_FINDING},
                "warnings": _CRITIQUE_WARNINGS,
            },
            ["open", "cleared", "warnings"],
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
                "cite": {"anyOf": [_REQUIREMENT_CITE, {"type": "null"}], "default": None},
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


# --------------------------------------------------------------------------
# ASSEMBLY.md §3 — the constraint quartet
#
# The vocabulary below is RESTATED here, not invented: the authority is
# ``hephaestus.geom.constraints`` (``CONSTRAINT_KINDS`` / ``REQUIRED_PARAMS`` /
# ``OPTIONAL_PARAMS``) and ``hephaestus.core.project_store.constraints`` (the id
# and anchor grammars). This module may not import either — the contract package
# is pure declaration and geom binds the CAD kernel at import time — so the
# equality is asserted by a drift test instead
# (``server/tests/test_assembly_tools.py::test_declared_constraint_vocabulary_matches_geom``).

#: The 8C kinds (``ASSEMBLY.md`` §1). Each later kind is a contract amendment.
CONSTRAINT_KINDS: Final[tuple[str, ...]] = (
    "no_interference",
    "clearance_min",
    "distance",
    "coincident",
    "concentric",
    "parallel",
    "perpendicular",
    "fit",
)

#: Every declared parameter name any kind takes, name-sorted. Which ones a given
#: kind *requires* is enforced structurally by the constraint set, which refuses
#: a wrong set with ``invalid_constraint`` and writes nothing — the same division
#: the requirement ledger's per-source obligations already use, and for the same
#: reason: one authority (the evaluator's own tables), not a JSON Schema restating
#: it in a second place where it could drift.
CONSTRAINT_PARAMS: Final[tuple[str, ...]] = (
    "axis_eps_deg",
    "max_mm",
    "min_mm",
    "normal_eps_deg",
    "tol_deg",
    "tol_mm",
    "tol_mm3",
    "value_mm",
)

#: Constraint ids: a stable handle a requirement, a tool call, a reviewer finding
#: and a bench reason all name — so, like a ledger id, plain and pattern-checked.
CONSTRAINT_ID_PATTERN: Final[str] = r"^[A-Za-z][A-Za-z0-9._-]{0,63}$"

#: An anchor is ``part[:selector]`` (``ASSEMBLY.md`` §1): a §5.3 tag, a geometry
#: label or a binding name in the part's existing §7 namespace, or a bare part
#: meaning the whole compound. The separator is a colon, never the ``part/selector``
#: slash of a §7 cross-part measurement selector — an anchor already names its part.
CONSTRAINT_ANCHOR_PATTERN: Final[str] = r"^[A-Za-z_][A-Za-z0-9_]*(:[^\s:]+)?$"

#: The three per-constraint states (``ASSEMBLY.md`` §2). ``unresolvable`` is its
#: own state on purpose: a constraint that could not be checked is neither a pass
#: nor a violation, and collapsing it into either would be a lie about evidence.
CONSTRAINT_STATES: Final[tuple[str, ...]] = ("satisfied", "violated", "unresolvable")

_CONSTRAINT_ID: Final[JsonSchema] = {"type": "string", "pattern": CONSTRAINT_ID_PATTERN}
_CONSTRAINT_ANCHOR: Final[JsonSchema] = {
    "type": "string",
    "pattern": CONSTRAINT_ANCHOR_PATTERN,
}

#: Why this constraint is claimed to hold (``ASSEMBLY.md`` §1: provenance is
#: MANDATORY). Either it cites a requirement-ledger id, or it is an assumption
#: with a reason — a constraint IS an interpretation of intent, so it says whose.
#: Neither present is refused ``invalid_constraint`` with nothing written.
_CONSTRAINT_PROVENANCE: Final[JsonSchema] = _obj(
    {
        "requirement": {
            "anyOf": [{"type": "string", "pattern": REQUIREMENT_ID_PATTERN}, {"type": "null"}],
            "default": None,
        },
        "assumed": {"anyOf": [_BOOL, {"type": "null"}], "default": None},
        "reason": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    [],
)

#: Declared numbers ride at the entry's top level, exactly as ``ASSEMBLY.md`` §1
#: writes an entry (``value_mm`` next to ``id``), so the wire shape and the stored
#: shape are one shape.
_CONSTRAINT_NUMBERS: Final[dict[str, JsonSchema]] = {
    name: {"anyOf": [_NUM, {"type": "null"}], "default": None} for name in CONSTRAINT_PARAMS
}

_CONSTRAINT_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": _CONSTRAINT_ID,
        "kind": _enum(list(CONSTRAINT_KINDS)),
        "a": _CONSTRAINT_ANCHOR,
        "b": _CONSTRAINT_ANCHOR,
        "provenance": _CONSTRAINT_PROVENANCE,
        "note": {"anyOf": [_STR, {"type": "null"}], "default": None},
        # KINEMATICS.md §3 (Stage 9A): an entry may bind named poses for
        # per-pose evaluation. Absent (or null), evaluation and the outcome
        # wire shape are byte-for-byte the 8C ones; which ids are real poses
        # is the store's and the evaluator's own judgement, not this schema's.
        "poses": {
            "anyOf": [{"type": "array", "items": _STR}, {"type": "null"}],
            "default": None,
        },
        **_CONSTRAINT_NUMBERS,
    },
    ["id", "kind", "a", "b", "provenance"],
)

#: The same entry as it is *reported*: lenient, and carrying what a withdrawal
#: recorded. A withdrawn entry is never evaluated and never erased (``ASSEMBLY.md``
#: §3), so what a project stopped claiming — and why — stays readable.
_CONSTRAINT_ENTRY_OUT: Final[JsonSchema] = _ok(
    {
        **cast("dict[str, JsonSchema]", _CONSTRAINT_ENTRY["properties"]),
        "withdrawn": _BOOL,
        "withdrawn_reason": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "kind", "a", "b"],
)

#: What the geometry measured, next to what was declared (``ASSEMBLY.md`` §2).
#: ``satisfied`` here is arithmetic — the declared numbers restated against the
#: measurement — never a verdict about the design.
_CONSTRAINT_RESIDUAL: Final[JsonSchema] = _ok(
    {
        "kind": _STR,
        "measured": _NUM,
        "unit": _enum(["mm", "mm3", "deg"]),
        "slack": _NUM,
        "satisfied": _BOOL,
        "declared": {"type": "array"},
        "values": {"type": "array"},
        "worst_points": {"type": "array"},
    },
    ["kind", "measured", "unit", "slack", "satisfied"],
)

#: How one anchor resolved: the §7 rule that matched and the artifact it was read
#: from. Present even when resolution failed (``rule``/``artifact_ref`` null), so
#: an unresolvable constraint still says how far it got.
_CONSTRAINT_ANCHOR_REF: Final[JsonSchema] = _ok(
    {
        "anchor": _STR,
        "part": _STR,
        "selector": _STR,
        "rule": {"anyOf": [_STR, {"type": "null"}]},
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["anchor", "part", "selector"],
)

_CONSTRAINT_OUTCOME: Final[JsonSchema] = _ok(
    {
        "id": _STR,
        "kind": _STR,
        "a": _CONSTRAINT_ANCHOR_REF,
        "b": _CONSTRAINT_ANCHOR_REF,
        "state": _enum(list(CONSTRAINT_STATES)),
        # A violated outcome always carries the residual; an unresolvable one
        # always carries a named reason and a detail. Never both, which is what
        # keeps "not checked" from reading like a measurement.
        "residual": {"anyOf": [_CONSTRAINT_RESIDUAL, {"type": "null"}]},
        "reason": {"anyOf": [_STR, {"type": "null"}]},
        "detail": {"anyOf": [_STR, {"type": "null"}]},
        "provenance": _dict(),
        "note": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "kind", "a", "b", "state"],
)

#: One whole evaluation (``ASSEMBLY.md`` §2). ``blocking`` is the ids the
#: ``VALIDATION.md`` §5 never-green rule fires on — violated AND unresolvable,
#: because an unchecked constraint is not a passing one. ``stale`` names parts
#: rebuilt since this status was computed.
_ASSEMBLY_STATUS: Final[JsonSchema] = _ok(
    {
        "generation": _INT,
        "constraints": {"type": "array", "items": _CONSTRAINT_OUTCOME},
        "artifact_refs": _dict(_STR),
        "stale": {"type": "array", "items": _STR},
        "counts": _dict(_INT),
        "blocking": {"type": "array", "items": _STR},
    },
    ["generation", "constraints", "counts", "blocking"],
)

#: The result the three constraint-set tools share: the generation that is now
#: current, its immutable ref, what changed, every entry (withdrawn ones included)
#: and the LAST evaluation — ``assembly: null`` meaning *never evaluated*, which
#: is not a pass. Re-measuring is ``check_assembly``, never a side effect of a read.
_CONSTRAINT_SET_RESULT: Final[JsonSchema] = _ok(
    {
        "status": {"const": "ok"},
        "generation": _INT,
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
        "change": {"anyOf": [_dict(), {"type": "null"}]},
        "entries": {"type": "array", "items": _CONSTRAINT_ENTRY_OUT},
        "assembly": {"anyOf": [_ASSEMBLY_STATUS, {"type": "null"}]},
        "assembly_ref": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["status", "generation", "artifact_ref", "entries", "assembly"],
)


def _declare_constraint() -> ToolDecl:
    return ToolDecl(
        name="declare_constraint",
        summary="Declare one cross-part constraint (ASSEMBLY.md §1); advances one generation.",
        params=_CONSTRAINT_ENTRY,
        result=_CONSTRAINT_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _update_constraint() -> ToolDecl:
    return ToolDecl(
        name="update_constraint",
        summary="Revise or withdraw one constraint with a recorded reason; one generation.",
        params=_obj(
            {
                "id": _CONSTRAINT_ID,
                # Merged onto the stored entry and revalidated as a whole, so a
                # patch cannot produce an entry that could not have been declared.
                # `withdrawn: true` is the withdrawal path (ASSEMBLY.md §3): a new
                # generation that stops claiming the constraint, never an erasure.
                "patch": _obj(
                    {
                        "kind": {"anyOf": [_enum(list(CONSTRAINT_KINDS)), {"type": "null"}]},
                        "a": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "b": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "provenance": {"anyOf": [_CONSTRAINT_PROVENANCE, {"type": "null"}]},
                        "note": {"anyOf": [_STR, {"type": "null"}]},
                        # KINEMATICS.md §3 (Stage 9A): pose bindings are entry
                        # fields, so a patch may revise them; the merged entry
                        # is revalidated as a whole by the store.
                        "poses": {"anyOf": [{"type": "array", "items": _STR}, {"type": "null"}]},
                        "withdrawn": {"anyOf": [_BOOL, {"type": "null"}]},
                        **_CONSTRAINT_NUMBERS,
                    },
                    [],
                ),
                # Compulsory and recorded ON THE GENERATION: a silently revised
                # tolerance is exactly what ASSEMBLY.md §3 forbids.
                "reason": _STR,
            },
            ["id", "patch", "reason"],
        ),
        result=_CONSTRAINT_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _read_constraints() -> ToolDecl:
    return ToolDecl(
        name="read_constraints",
        summary="Read the constraint set and the latest assembly evaluation (no re-measure).",
        params=_obj({}, []),
        result=_CONSTRAINT_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


def _check_assembly() -> ToolDecl:
    return ToolDecl(
        name="check_assembly",
        summary="Evaluate declared constraints against the current builds; return AssemblyStatus.",
        params=_obj(
            {
                # Omitted: every active constraint, and the result is projected as
                # the project's assembly status. A named subset is deliberately NOT
                # projected — a projection covering some constraints would report a
                # set the project does not have.
                "ids": {
                    "anyOf": [{"type": "array", "items": _CONSTRAINT_ID}, {"type": "null"}],
                    "default": None,
                },
            },
            [],
        ),
        result=_ok(
            {
                "status": {"const": "ok"},
                "assembly": _ASSEMBLY_STATUS,
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
                "partial": _BOOL,
            },
            ["status", "assembly", "partial"],
        ),
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


# --------------------------------------------------------------------------
# KINEMATICS.md §6 — the Stage 9A/9B kinematics tools
#
# The vocabulary below is RESTATED here, not invented, on exactly the 8C
# constraint-quartet rule above: the authority is
# ``hephaestus.core.project_store.kinematics`` (``JOINT_KINDS`` /
# ``JOINT_ID_PATTERN`` / ``MOTION_CHECK_KINDS`` / the sample-cap constants /
# the shared 8C anchor grammar) and ``hephaestus.core.motion``
# (``MOTION_OUTCOME_STATES`` / ``SWEEP_VERDICTS``). This module may not
# import either, so the equality is asserted by a drift test instead
# (``server/tests/test_motion_tools.py::test_declared_joint_vocabulary_matches_engine``).

#: The Stage 9 joint kinds (``KINEMATICS.md`` §1); each later kind is a
#: contract amendment, so the set is closed here rather than extensible.
JOINT_KINDS: Final[tuple[str, ...]] = ("fixed", "revolute", "prismatic", "cylindrical")

#: Joint and pose ids: stable handles a requirement, a tool call and a reviewer
#: finding all name — pattern-checked exactly like constraint ids.
JOINT_ID_PATTERN: Final[str] = r"^[A-Za-z][A-Za-z0-9._-]{0,63}$"

#: The two per-joint and per-pose states (``KINEMATICS.md`` §2). Closed on
#: purpose: a joint set has nothing to satisfy or violate — those are the
#: constraint vocabulary — so "could not be evaluated" has exactly one spelling
#: here, and it is not a pass.
MOTION_OUTCOME_STATES: Final[tuple[str, ...]] = ("resolved", "unresolvable")

_JOINT_ID: Final[JsonSchema] = {"type": "string", "pattern": JOINT_ID_PATTERN}

#: One declared travel range (``min < max``, in the kind's own unit).
_JOINT_LIMIT_PAIR: Final[JsonSchema] = _obj({"min": _NUM, "max": _NUM}, ["min", "max"])

#: Which limit shape a kind requires (one pair for revolute/prismatic, the two
#: named pairs for cylindrical, none for fixed) is enforced structurally by the
#: joint set, which refuses a wrong shape with ``invalid_joint`` and writes
#: nothing — one authority (the store's own tables), the CONSTRAINT_PARAMS rule.
_JOINT_LIMITS: Final[JsonSchema] = {
    "anyOf": [
        _JOINT_LIMIT_PAIR,
        _obj(
            {"rotation": _JOINT_LIMIT_PAIR, "translation": _JOINT_LIMIT_PAIR},
            ["rotation", "translation"],
        ),
        {"type": "null"},
    ],
    "default": None,
}

#: A joint entry, exactly the ``KINEMATICS.md`` §1 shape. Anchors are the 8C
#: anchor grammar verbatim (§1: "no new naming scheme"); provenance carries the
#: same compulsion as a constraint's, under this set's own refusal token.
_JOINT_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": _JOINT_ID,
        "kind": _enum(list(JOINT_KINDS)),
        "parent": _CONSTRAINT_ANCHOR,
        "child": _CONSTRAINT_ANCHOR,
        "limits": _JOINT_LIMITS,
        # §1: the authored positions ARE parameter zero — the only value in the
        # 9A contract; a numeric zero offset is a 9C amendment candidate.
        "zero": _enum(["as_built"], "as_built"),
        "provenance": _CONSTRAINT_PROVENANCE,
        "note": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    ["id", "kind", "parent", "child", "provenance"],
)

#: The same entry as it is *reported*: lenient, and carrying what a withdrawal
#: recorded — a withdrawn joint is never evaluated and never erased (the 8C
#: read-tool shape: generational state is honest only if every generation stays
#: readable).
_JOINT_ENTRY_OUT: Final[JsonSchema] = _ok(
    {
        **cast("dict[str, JsonSchema]", _JOINT_ENTRY["properties"]),
        "withdrawn": _BOOL,
        "withdrawn_reason": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "kind", "parent", "child"],
)

#: A named pose, exactly the ``KINEMATICS.md`` §3 shape: parameter values by
#: joint id. Joints omitted take their zero value, so ``{}`` is legal and means
#: "everything as built".
_POSE_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": _JOINT_ID,
        "joints": _dict(_NUM),
        "provenance": _CONSTRAINT_PROVENANCE,
        "note": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    ["id", "joints", "provenance"],
)

_POSE_ENTRY_OUT: Final[JsonSchema] = _ok(
    {
        **cast("dict[str, JsonSchema]", _POSE_ENTRY["properties"]),
        "withdrawn": _BOOL,
        "withdrawn_reason": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "joints"],
)

#: One joint's state at one evaluation (``KINEMATICS.md`` §2). The anchor refs
#: reuse the 8C shape: how far resolution got, even on failure.
_JOINT_OUTCOME: Final[JsonSchema] = _ok(
    {
        "id": _STR,
        "kind": _STR,
        "parent": _CONSTRAINT_ANCHOR_REF,
        "child": _CONSTRAINT_ANCHOR_REF,
        "state": _enum(list(MOTION_OUTCOME_STATES)),
        "reason": {"anyOf": [_STR, {"type": "null"}]},
        "detail": {"anyOf": [_STR, {"type": "null"}]},
        "provenance": _dict(),
        "note": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "kind", "parent", "child", "state"],
)

#: One pose's state at one evaluation, with its binding restated. This is where
#: ``orphaned_pose`` lives (§2/§3): a per-POSE unresolvable state naming the
#: withdrawn joint in its detail, never a joint failure and never erased.
_POSE_OUTCOME: Final[JsonSchema] = _ok(
    {
        "id": _STR,
        "joints": _dict(_NUM),
        "state": _enum(list(MOTION_OUTCOME_STATES)),
        "reason": {"anyOf": [_STR, {"type": "null"}]},
        "detail": {"anyOf": [_STR, {"type": "null"}]},
        "provenance": _dict(),
        "note": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "joints", "state"],
)

#: One whole motion evaluation (``KINEMATICS.md`` §2): the TWO sections, the
#: artifact refs actually read for the joint forest, ``stale`` naming forest
#: parts rebuilt since, and ``blocking`` — the ids the (9B-amended) never-green
#: rule would fire on, because an unresolvable joint or pose is not a passing one.
_MOTION_STATUS: Final[JsonSchema] = _ok(
    {
        "joint_generation": _INT,
        "pose_generation": _INT,
        "joints": {"type": "array", "items": _JOINT_OUTCOME},
        "poses": {"type": "array", "items": _POSE_OUTCOME},
        "artifact_refs": _dict(_STR),
        "stale": {"type": "array", "items": _STR},
        "counts": _dict(_dict(_INT)),
        "blocking": {"type": "array", "items": _STR},
    },
    ["joint_generation", "pose_generation", "joints", "poses", "counts", "blocking"],
)

#: The result the three joint-set tools share (the 8C constraint-set shape):
#: the generation now current, its immutable ref, what changed, every entry
#: (withdrawn ones included) and the LAST evaluation — ``motion: null`` meaning
#: *never evaluated*, which is not a pass. Re-measuring is ``check_motion``,
#: never a side effect of a read.
_JOINT_SET_RESULT: Final[JsonSchema] = _ok(
    {
        "status": {"const": "ok"},
        "generation": _INT,
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
        "change": {"anyOf": [_dict(), {"type": "null"}]},
        "entries": {"type": "array", "items": _JOINT_ENTRY_OUT},
        "motion": {"anyOf": [_MOTION_STATUS, {"type": "null"}]},
        "motion_ref": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["status", "generation", "artifact_ref", "entries", "motion"],
)

_POSE_SET_RESULT: Final[JsonSchema] = _ok(
    {
        "status": {"const": "ok"},
        "generation": _INT,
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
        "change": {"anyOf": [_dict(), {"type": "null"}]},
        "entries": {"type": "array", "items": _POSE_ENTRY_OUT},
        "motion": {"anyOf": [_MOTION_STATUS, {"type": "null"}]},
        "motion_ref": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["status", "generation", "artifact_ref", "entries", "motion"],
)


def _declare_joint() -> ToolDecl:
    return ToolDecl(
        name="declare_joint",
        summary="Declare one joint between two parts (KINEMATICS.md §1); advances one generation.",
        params=_JOINT_ENTRY,
        result=_JOINT_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _update_joint() -> ToolDecl:
    return ToolDecl(
        name="update_joint",
        summary="Revise or withdraw one joint with a recorded reason; one generation.",
        params=_obj(
            {
                "id": _JOINT_ID,
                # Merged onto the stored entry and revalidated as a whole
                # (including the forest check — a re-parented joint can close a
                # cycle a declaration could not). `withdrawn: true` is the
                # withdrawal path: a new generation that stops claiming the
                # joint, never an erasure. A pose that binds it is deliberately
                # untouched — it becomes `orphaned_pose` at evaluation (§2/§3).
                "patch": _obj(
                    {
                        "kind": {"anyOf": [_enum(list(JOINT_KINDS)), {"type": "null"}]},
                        "parent": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "child": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "limits": _JOINT_LIMITS,
                        "provenance": {"anyOf": [_CONSTRAINT_PROVENANCE, {"type": "null"}]},
                        "note": {"anyOf": [_STR, {"type": "null"}]},
                        "withdrawn": {"anyOf": [_BOOL, {"type": "null"}]},
                    },
                    [],
                ),
                # Compulsory and recorded ON THE GENERATION, the 8C rule: a
                # silently revised travel limit is a silently revised claim.
                "reason": _STR,
            },
            ["id", "patch", "reason"],
        ),
        result=_JOINT_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _read_joints() -> ToolDecl:
    return ToolDecl(
        name="read_joints",
        summary="Read the joint set and the latest motion evaluation (no re-measure).",
        params=_obj({}, []),
        result=_JOINT_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


def _declare_pose() -> ToolDecl:
    return ToolDecl(
        name="declare_pose",
        summary="Declare one named pose binding joint values (KINEMATICS.md §3); one generation.",
        params=_POSE_ENTRY,
        result=_POSE_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _update_pose() -> ToolDecl:
    return ToolDecl(
        name="update_pose",
        summary="Revise or withdraw one pose with a recorded reason; one generation.",
        params=_obj(
            {
                "id": _JOINT_ID,
                "patch": _obj(
                    {
                        "joints": {"anyOf": [_dict(_NUM), {"type": "null"}]},
                        "provenance": {"anyOf": [_CONSTRAINT_PROVENANCE, {"type": "null"}]},
                        "note": {"anyOf": [_STR, {"type": "null"}]},
                        "withdrawn": {"anyOf": [_BOOL, {"type": "null"}]},
                    },
                    [],
                ),
                "reason": _STR,
            },
            ["id", "patch", "reason"],
        ),
        result=_POSE_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _read_poses() -> ToolDecl:
    return ToolDecl(
        name="read_poses",
        summary="Read the pose set and the latest motion evaluation (no re-measure).",
        params=_obj({}, []),
        result=_POSE_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


# -- motion checks (KINEMATICS.md §4, Stage 9B) ----------------------------

#: The Stage 9 motion-check kinds (§4); closed, like ``JOINT_KINDS`` — a
#: swept-volume envelope is a fact ``check_motion`` publishes, not a kind.
MOTION_CHECK_KINDS: Final[tuple[str, ...]] = (
    "sweep_clearance",
    "sweep_no_interference",
    "reach",
)

#: THE §4 result vocabulary, one closed set, restated verbatim. The asymmetry
#: is the honesty: universal kinds succeed as ``holds_at_samples`` (all-good
#: samples only evidence) and fail as ``violated`` (one bad sample IS proof);
#: the existence kind (``reach``) inverts — success is ``satisfied`` (one
#: achieving sample IS proof), failure is ``not_reached_at_samples`` (samples
#: not reaching is evidence, never proof of unreachability).
SWEEP_VERDICTS: Final[tuple[str, ...]] = (
    "holds_at_samples",
    "satisfied",
    "not_reached_at_samples",
    "violated",
    "unresolvable",
)

#: The per-axis sample default and the grid-total cap (§4: the cap binds the
#: computed product ``samples ** n_joints``, refused at declaration naming it).
SWEEP_SAMPLES_DEFAULT: Final[int] = 64
SWEEP_SAMPLES_MAX: Final[int] = 4096

#: One joint's declared sweep interval (``from < to``, in the kind's own unit).
_SWEEP_RANGE: Final[JsonSchema] = _obj({"from": _NUM, "to": _NUM}, ["from", "to"])

#: A motion-check entry, exactly the ``KINEMATICS.md`` §4 shape. Which anchor
#: and threshold fields a kind requires (``a``/``b`` for the universal kinds
#: plus ``min_mm`` for ``sweep_clearance``; ``anchor``/``target_point_mm``/
#: ``tol_mm`` for ``reach``) is enforced structurally by the motion-check set,
#: which refuses a wrong shape with ``invalid_motion_check`` and writes
#: nothing — one authority (the store's own tables), the ``_JOINT_LIMITS``
#: rule. Ditto the grid-total sample cap: the set computes and refuses on the
#: product, naming it, which a per-field JSON bound cannot express.
_MOTION_CHECK_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": _JOINT_ID,
        "kind": _enum(list(MOTION_CHECK_KINDS)),
        "a": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}], "default": None},
        "b": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}], "default": None},
        "anchor": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}], "default": None},
        "sweep": _dict(_SWEEP_RANGE),
        "samples": {"type": "integer", "default": SWEEP_SAMPLES_DEFAULT},
        "min_mm": {"anyOf": [_NUM, {"type": "null"}], "default": None},
        "target_point_mm": {
            "anyOf": [
                {"type": "array", "items": _NUM, "minItems": 3, "maxItems": 3},
                {"type": "null"},
            ],
            "default": None,
        },
        "tol_mm": {"anyOf": [_NUM, {"type": "null"}], "default": None},
        "provenance": _CONSTRAINT_PROVENANCE,
        "note": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    ["id", "kind", "sweep", "provenance"],
)

_MOTION_CHECK_ENTRY_OUT: Final[JsonSchema] = _ok(
    {
        **cast("dict[str, JsonSchema]", _MOTION_CHECK_ENTRY["properties"]),
        "withdrawn": _BOOL,
        "withdrawn_reason": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "kind", "sweep"],
)

#: One evaluated grid sample: the parameter assignment and what it measured
#: (mm for ``sweep_clearance``/``reach``, mm³ for ``sweep_no_interference``).
_SWEEP_SAMPLE: Final[JsonSchema] = _ok(
    {"values": _dict(_NUM), "measured": _NUM},
    ["values", "measured"],
)

#: One motion check's §4 result record. Every result restates the declared
#: quantities (``sweep``, ``samples_per_axis``, the thresholds) so the number
#: can never be read without the claim it was measured against, and carries
#: ``samples_evaluated`` plus the worst (for ``reach``: closest) sample's
#: parameter values and measured value whenever at least one sample landed.
_SWEEP_RESULT: Final[JsonSchema] = _ok(
    {
        "id": _STR,
        "kind": _STR,
        "verdict": _enum(list(SWEEP_VERDICTS)),
        "samples_evaluated": _INT,
        "grid_total": _INT,
        "samples_per_axis": _INT,
        "sweep": _dict(_SWEEP_RANGE),
        "unit": _STR,
        "anchors": _dict(_CONSTRAINT_ANCHOR_REF),
        "worst": {"anyOf": [_SWEEP_SAMPLE, {"type": "null"}]},
        "min_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "tol_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "target_point_mm": {"anyOf": [{"type": "array", "items": _NUM}, {"type": "null"}]},
        "miss_mm": {"anyOf": [_NUM, {"type": "null"}]},
        "reason": {"anyOf": [_STR, {"type": "null"}]},
        "detail": {"anyOf": [_STR, {"type": "null"}]},
        "provenance": _dict(),
        "note": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "kind", "verdict", "samples_evaluated", "grid_total", "sweep", "unit"],
)

#: The result the three motion-check tools share (the joint-set shape, with
#: the LAST full evaluation's results in place of the ``MotionStatus``):
#: ``results: null`` means *checks never evaluated*, which is not a pass.
#: Re-measuring is ``check_motion``, never a side effect of a read.
_MOTION_CHECK_SET_RESULT: Final[JsonSchema] = _ok(
    {
        "status": {"const": "ok"},
        "generation": _INT,
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
        "change": {"anyOf": [_dict(), {"type": "null"}]},
        "entries": {"type": "array", "items": _MOTION_CHECK_ENTRY_OUT},
        "results": {"anyOf": [{"type": "array", "items": _SWEEP_RESULT}, {"type": "null"}]},
        "results_ref": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["status", "generation", "artifact_ref", "entries", "results"],
)


def _declare_motion_check() -> ToolDecl:
    return ToolDecl(
        name="declare_motion_check",
        summary="Declare one sampled motion check (KINEMATICS.md §4); advances one generation.",
        params=_MOTION_CHECK_ENTRY,
        result=_MOTION_CHECK_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _update_motion_check() -> ToolDecl:
    return ToolDecl(
        name="update_motion_check",
        summary="Revise or withdraw one motion check with a recorded reason; one generation.",
        params=_obj(
            {
                "id": _JOINT_ID,
                # Merged onto the stored entry and revalidated as a whole,
                # including the grid-total cap — an update cannot smuggle a
                # grid past what a declaration would refuse. `withdrawn: true`
                # is the withdrawal path: a new generation that stops claiming
                # the check, never an erasure; a withdrawn check is never
                # evaluated again, and its last recorded result stays readable
                # exactly as measured.
                "patch": _obj(
                    {
                        "kind": {"anyOf": [_enum(list(MOTION_CHECK_KINDS)), {"type": "null"}]},
                        "a": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "b": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "anchor": {"anyOf": [_CONSTRAINT_ANCHOR, {"type": "null"}]},
                        "sweep": {"anyOf": [_dict(_SWEEP_RANGE), {"type": "null"}]},
                        "samples": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                        "min_mm": {"anyOf": [_NUM, {"type": "null"}]},
                        "target_point_mm": {
                            "anyOf": [
                                {"type": "array", "items": _NUM, "minItems": 3, "maxItems": 3},
                                {"type": "null"},
                            ]
                        },
                        "tol_mm": {"anyOf": [_NUM, {"type": "null"}]},
                        "provenance": {"anyOf": [_CONSTRAINT_PROVENANCE, {"type": "null"}]},
                        "note": {"anyOf": [_STR, {"type": "null"}]},
                        "withdrawn": {"anyOf": [_BOOL, {"type": "null"}]},
                    },
                    [],
                ),
                # Compulsory and recorded ON THE GENERATION, the 8C rule: a
                # silently revised threshold is a silently revised claim.
                "reason": _STR,
            },
            ["id", "patch", "reason"],
        ),
        result=_MOTION_CHECK_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _read_motion_checks() -> ToolDecl:
    return ToolDecl(
        name="read_motion_checks",
        summary="Read the motion-check set and the latest sweep results (no re-measure).",
        params=_obj({}, []),
        result=_MOTION_CHECK_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


def _check_motion() -> ToolDecl:
    # KINEMATICS.md §6 `check_motion(ids?)`, completed by Stage 9B exactly as
    # the 9A declaration said it would be: the result gains the per-check
    # sweep results, and `ids` narrows which motion CHECKS run (the joint and
    # pose sections are always evaluated in full — a MotionStatus covering
    # some joints would report a forest the project does not have). A named
    # subset is evaluated but deliberately not projected, and says so with
    # `partial: true` (the check_assembly rule); a full run records both the
    # status and the results so a later read — and the reviewer — sees them.
    return ToolDecl(
        name="check_motion",
        summary="Evaluate joints, poses and motion checks now; MotionStatus + sweep results.",
        params=_obj(
            {
                "ids": {
                    "anyOf": [{"type": "array", "items": _JOINT_ID}, {"type": "null"}],
                    "default": None,
                },
            },
            [],
        ),
        result=_ok(
            {
                "status": {"const": "ok"},
                "motion": _MOTION_STATUS,
                "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
                "results": {"type": "array", "items": _SWEEP_RESULT},
                "results_ref": {"anyOf": [_STR, {"type": "null"}]},
                "partial": _BOOL,
            },
            ["status", "motion", "results", "partial"],
        ),
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
    )


# -- couplings (KINEMATICS.md §5, Stage 9C) --------------------------------

#: A coupling entry, exactly the ``KINEMATICS.md`` §5 shape: the linear
#: relationship ``child = ratio * parent + offset`` between two joint
#: parameters — the transmission vocabulary (gear pairs, lead screws, belt
#: reductions) without gear-tooth geometry. ``parent``/``child`` are JOINT
#: ids, not anchors: a coupling relates parameters, and the joint forest
#: already relates the parts. That both joints exist unwithdrawn with a
#: scalar DOF, that the ratio is nonzero, that a child has ONE driver, and
#: that no cycle closes (``cyclic_coupling``, the cycle named) is the
#: coupling set's own table — refused with ``invalid_coupling`` /
#: ``cyclic_coupling`` and nothing written, the ``_JOINT_LIMITS`` rule.
_COUPLING_ENTRY: Final[JsonSchema] = _obj(
    {
        "id": _JOINT_ID,
        "parent": _JOINT_ID,
        "child": _JOINT_ID,
        "ratio": _NUM,
        "offset": {"type": "number", "default": 0.0},
        "provenance": _CONSTRAINT_PROVENANCE,
        "note": {"anyOf": [_STR, {"type": "null"}], "default": None},
    },
    ["id", "parent", "child", "ratio", "provenance"],
)

_COUPLING_ENTRY_OUT: Final[JsonSchema] = _ok(
    {
        **cast("dict[str, JsonSchema]", _COUPLING_ENTRY["properties"]),
        "withdrawn": _BOOL,
        "withdrawn_reason": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["id", "parent", "child", "ratio"],
)

#: The result the three coupling tools share (the pose-set shape: the latest
#: motion evaluation rides along as evidence already taken, because coupled
#: values are derived wherever poses and sweeps evaluate — ``motion: null``
#: meaning *never evaluated*, which is not a pass). Withdrawn entries are
#: returned with their reasons: generational state is honest only if every
#: generation stays readable (``KINEMATICS.md`` §6).
_COUPLING_SET_RESULT: Final[JsonSchema] = _ok(
    {
        "status": {"const": "ok"},
        "generation": _INT,
        "artifact_ref": {"anyOf": [_STR, {"type": "null"}]},
        "change": {"anyOf": [_dict(), {"type": "null"}]},
        "entries": {"type": "array", "items": _COUPLING_ENTRY_OUT},
        "motion": {"anyOf": [_MOTION_STATUS, {"type": "null"}]},
        "motion_ref": {"anyOf": [_STR, {"type": "null"}]},
    },
    ["status", "generation", "artifact_ref", "entries", "motion"],
)


def _declare_coupling() -> ToolDecl:
    return ToolDecl(
        name="declare_coupling",
        summary="Declare one coupling: child = ratio*parent + offset (KINEMATICS.md §5).",
        params=_COUPLING_ENTRY,
        result=_COUPLING_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _update_coupling() -> ToolDecl:
    return ToolDecl(
        name="update_coupling",
        summary="Revise or withdraw one coupling with a recorded reason; one generation.",
        params=_obj(
            {
                "id": _JOINT_ID,
                # Merged onto the stored entry and revalidated as a whole,
                # including the one-driver and cycle checks — a re-childed
                # coupling can close a cycle a declaration could not.
                # `withdrawn: true` is the withdrawal path: a new generation
                # that stops claiming the coupling, never an erasure; the
                # child joint becomes a FREE parameter again from the next
                # evaluation on.
                "patch": _obj(
                    {
                        "parent": {"anyOf": [_JOINT_ID, {"type": "null"}]},
                        "child": {"anyOf": [_JOINT_ID, {"type": "null"}]},
                        "ratio": {"anyOf": [_NUM, {"type": "null"}]},
                        "offset": {"anyOf": [_NUM, {"type": "null"}]},
                        "provenance": {"anyOf": [_CONSTRAINT_PROVENANCE, {"type": "null"}]},
                        "note": {"anyOf": [_STR, {"type": "null"}]},
                        "withdrawn": {"anyOf": [_BOOL, {"type": "null"}]},
                    },
                    [],
                ),
                # Compulsory and recorded ON THE GENERATION, the 8C rule: a
                # silently revised gear ratio is a silently revised claim.
                "reason": _STR,
            },
            ["id", "patch", "reason"],
        ),
        result=_COUPLING_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=True,
        idempotent=True,
    )


def _read_couplings() -> ToolDecl:
    return ToolDecl(
        name="read_couplings",
        summary="Read the coupling set — withdrawn entries included with reasons (no re-measure).",
        params=_obj({}, []),
        result=_COUPLING_SET_RESULT,
        profiles=("part", "orchestrator"),
        sequential=False,
        idempotent=False,
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

#: What a DXF/SVG export reports about kerf compensation. ``applied_mm`` is null
#: exactly when the emitted path is the nominal boundary, and ``source`` says
#: whether that was the caller's choice, the process pack's number, or nothing
#: at all — a kerf is never invented, so ``note: "kerf_uncompensated"`` is how an
#: uncompensated cut file announces itself instead of passing for a compensated
#: one.
_KERF: Final[JsonSchema] = _obj(
    {
        "applied_mm": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]},
        "source": _enum(["explicit", "dfm", "none"]),
        "process": {"anyOf": [_STR, {"type": "null"}]},
        "note": {"const": "kerf_uncompensated"},
        "reason": _STR,
    },
    ["applied_mm", "source"],
    additional=True,
)


def _export_part() -> ToolDecl:
    conditional = [
        {
            "if": {"properties": {"layout": {"const": "nested_sheet"}}, "required": ["layout"]},
            "then": {"properties": {"format": {"enum": ["dxf", "svg"]}}},
        },
        # Kerf compensates a *cut path*; a STEP/STL/GLTF/3MF model stays nominal.
        {
            "if": {
                "properties": {"kerf_mm": {"type": "number"}},
                "required": ["kerf_mm"],
            },
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
                "kerf_mm": {
                    "anyOf": [{"type": "number", "minimum": 0.0}, {"type": "null"}],
                    "default": None,
                },
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
                    "kerf": _KERF,
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
    _compare_solids(),
    # MESH_INGEST.md §7.2: exactly ONE new tool for the whole of Stage 12 —
    # mesh FACTS ride the build record and ``heph scan``, because each tool
    # costs five drift-tested generated artifacts and a per-profile decision.
    _compare_to_scan(),
    _run_checks(),
    _record_requirements(),
    _read_requirements(),
    _update_requirement(),
    # ASSEMBLY.md §3: declaring is cheap and reversible, so unlike the reference
    # registry the constraint set IS model-writable — the ledger's compelled-
    # honesty pattern rather than the registry's operator-only one.
    _declare_constraint(),
    _update_constraint(),
    _read_constraints(),
    _check_assembly(),
    # KINEMATICS.md §6 (Stage 9A): the joint and pose quartets ride the 8C
    # quartet decision unchanged — declaring is cheap, reversible, and measured
    # against geometry the model didn't choose, so compelled honesty beats
    # gatekeeping. Motion checks and couplings are 9B/9C amendments.
    _declare_joint(),
    _update_joint(),
    _read_joints(),
    _declare_pose(),
    _update_pose(),
    _read_poses(),
    _declare_motion_check(),
    _update_motion_check(),
    _read_motion_checks(),
    _check_motion(),
    _declare_coupling(),
    _update_coupling(),
    _read_couplings(),
    _load_skill(),
    _list_skills(),
    _list_references(),
    _read_reference(),
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
