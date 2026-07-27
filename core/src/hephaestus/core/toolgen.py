"""Compatibility facade: the code generator moved to :mod:`hephaestus.contract`.

The generator now lives in ``contract/src/hephaestus/contract/toolgen.py`` so the
CAD engine stays engine-first — :mod:`hephaestus.core` knows nothing about agents
or the tool contract. The canonical invocation is
``uv run python -m hephaestus.contract.toolgen all``; ``python -m
hephaestus.core.toolgen all`` keeps working through this module and writes
byte-identical artifacts.

This module re-exports :mod:`hephaestus.contract.toolgen` for out-of-tree
consumers and existing drift tests only; it is not part of
:mod:`hephaestus.core`'s own surface, and nothing inside :mod:`hephaestus.core`
may import it.
"""

from __future__ import annotations

from hephaestus.contract.toolgen import (
    MCP_META_RESULT_KEY,
    MCP_META_TOOL_KEY,
    generate_json_schemas,
    generate_mcp_document,
    generate_typebox_module,
    main,
    mcp_declaration,
    mcp_declarations,
    repo_root,
    schema_document,
    write_all,
)

__all__ = [
    "MCP_META_RESULT_KEY",
    "MCP_META_TOOL_KEY",
    "generate_json_schemas",
    "generate_mcp_document",
    "generate_typebox_module",
    "main",
    "mcp_declaration",
    "mcp_declarations",
    "repo_root",
    "schema_document",
    "write_all",
]


if __name__ == "__main__":
    raise SystemExit(main())
