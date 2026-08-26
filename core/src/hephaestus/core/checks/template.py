"""The safe cross-part check template.

One source of truth for the initial script both entry points install:
``create_project_check`` (the model-facing tool in the server's ``cad_ops``)
and ``heph init`` (the operator-facing scaffolding verb). It lives in core so
the engine-only wheel can scaffold a project without the server installed;
``hephaestus.agent_bridge.cad_ops`` re-exports it unchanged.
"""

from __future__ import annotations

from typing import Final

#: The safe cross-part check template. The sentinel is substituted, not
#: ``str.format``-ed, because the body itself contains braces.
CHECK_DESCRIPTION_SENTINEL: Final[str] = "__DESCRIPTION__"
CHECK_TEMPLATE_HEADER: Final[str] = (
    f"# Project check{CHECK_DESCRIPTION_SENTINEL}\n"
    "#\n"
    "# Checks receive the measurement facade `m` and the pure `approx` helper\n"
    '# only. Address another part as "<part>/<selector>".\n'
    "\n"
    "CHECKS = {\n"
    '    "placeholder": lambda m: True,\n'
    "}\n"
)


def check_template(description: str) -> str:
    """The initial script ``create_project_check`` installs (no-replace)."""
    suffix = f": {description}" if description else ""
    return CHECK_TEMPLATE_HEADER.replace(CHECK_DESCRIPTION_SENTINEL, suffix)
