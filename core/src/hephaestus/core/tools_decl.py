"""Compatibility facade: the tool declaration moved to :mod:`hephaestus.contract`.

The typed tool surface now lives in ``contract/src/hephaestus/contract/tools_decl.py``
so the CAD engine stays engine-first — :mod:`hephaestus.core` knows nothing about
agents or the tool contract. Import ``hephaestus.contract.tools_decl`` in new
code; this module only re-exports it for out-of-tree consumers and is not part of
``hephaestus.core``'s own surface. Nothing inside :mod:`hephaestus.core` may
import it.
"""

from __future__ import annotations

from hephaestus.contract.tools_decl import (
    DEADLINE_DEFAULT,
    DEADLINE_MAX,
    DEADLINE_MIN,
    IDENT_PATTERN,
    MAX_IMAGES_PER_RESULT,
    PROFILES,
    PROMPT_MAX_UTF8_BYTES,
    READ_ARTIFACT_PAGE_MAX,
    REQUIREMENT_ID_PATTERN,
    REQUIREMENT_SOURCES,
    REVIEWER_TOOLS,
    STAGE2_EXCLUDED_TOOLS,
    TOOLS,
    TOOLS_BY_NAME,
    JsonSchema,
    Profile,
    ToolDecl,
    get_tool,
    limits_document,
    tool_names,
)

__all__ = [
    "DEADLINE_DEFAULT",
    "DEADLINE_MAX",
    "DEADLINE_MIN",
    "IDENT_PATTERN",
    "MAX_IMAGES_PER_RESULT",
    "PROFILES",
    "PROMPT_MAX_UTF8_BYTES",
    "READ_ARTIFACT_PAGE_MAX",
    "REQUIREMENT_ID_PATTERN",
    "REQUIREMENT_SOURCES",
    "REVIEWER_TOOLS",
    "STAGE2_EXCLUDED_TOOLS",
    "TOOLS",
    "TOOLS_BY_NAME",
    "JsonSchema",
    "Profile",
    "ToolDecl",
    "get_tool",
    "limits_document",
    "tool_names",
]
