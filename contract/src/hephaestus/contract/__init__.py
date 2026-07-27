"""hephaestus.contract: the canonical tool surface — typed declarations and codegen.

This package owns what the agent side of Hephaestus may call and what those
calls look like on the wire: :mod:`hephaestus.contract.tools_decl` declares every
tool once, and :mod:`hephaestus.contract.toolgen` renders that declaration to the
committed artifacts (per-tool JSON Schema, the TypeBox module the TypeScript
agent imports, and the MCP ``tools/list`` document).

It lives outside :mod:`hephaestus.core` on purpose: the CAD engine is
engine-first and knows nothing about agents, so the dependency runs
``server``/agent codegen -> ``contract``, never ``core`` -> ``contract``.
"""
