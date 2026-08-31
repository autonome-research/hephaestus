"""Create-part templates shared by the engine CLI and the tool dispatcher.

``create_part`` (``tool_schema.md``) and ``heph part create`` write the same
bytes for a given template name. The dispatcher used to own this table; it
lives here so a Node-free ``heph`` install can create a part without importing
the server package, and so the two callers cannot drift.
"""

from __future__ import annotations

from typing import Final

__all__ = ["BLANK_TEMPLATES", "PART_TEMPLATES", "TEMPLATE_NAMES"]

#: Minimal create-templates (Stage 1 owns richer scaffolds; blank is enough).
PART_TEMPLATES: Final[dict[str, str]] = {
    "blank": "from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n",
    "solid": "from build123d import *\n\n\nwith BuildPart() as part:\n    Box(10, 10, 10)\n",
    "sheet": "from build123d import *\n\n\nwith BuildSketch() as sk:\n    Rectangle(50, 50)\n",
    "from_store": "from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n",
}

#: Compatibility alias — the dispatcher exported this name first.
BLANK_TEMPLATES: Final[dict[str, str]] = PART_TEMPLATES

TEMPLATE_NAMES: Final[tuple[str, ...]] = ("blank", "sheet", "solid", "from_store")
