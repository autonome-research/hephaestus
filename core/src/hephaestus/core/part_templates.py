"""Create-part templates shared by the engine CLI and the tool dispatcher.

``create_part`` (``tool_schema.md``) and ``heph part create`` write the same
bytes for a given template name. The dispatcher used to own this table; it
lives here so a Node-free ``heph`` install can create a part without importing
the server package, and so the two callers cannot drift.

**Every value in this table must build unmodified.** A scaffold that does not
build is worse than no scaffold: it teaches the wrong shape on the first line a
new author reads, and the documented quickstart (``heph part create`` then
``heph build``) is a lie. Two rules follow from ``script_contract.md``:

- **No imports.** §1: "There are no imports in part scripts; the injected
  namespace is the entire API surface"; §2 lists ``__import__`` among the
  builtins that are absent, so ``from build123d import *`` is a *build error*,
  not a redundancy. ``build123d`` is pre-injected whole.
- **Assign, do not shadow.** §5's output protocol is ``part.geometry = <shape>``
  against the injected ``part`` handle. The builder-context idiom
  ``with BuildPart() as part:`` rebinds that name to a build123d builder, so the
  script publishes nothing at all.

``core/tests/test_cli_authoring.py::test_every_template_builds`` enforces the
invariant by running ``heph part create`` + ``heph build`` for every name here;
``test_no_template_imports`` enforces the first rule textually, so the import
line cannot come back unnoticed.
"""

from __future__ import annotations

from typing import Final

__all__ = ["BLANK_TEMPLATES", "PART_TEMPLATES", "TEMPLATE_NAMES"]

_BLANK: Final[str] = """\
# Scaffolded by `heph part create --template blank`. Edit or replace it.
#
# Nothing is brought in from elsewhere: build123d, math, Param, p, hc, part and
# tag are already in scope — the injected namespace is the whole API surface
# (script contract §2). Declare tunables in PARAMS and read them back as
# `p.<name>`; publish by assigning to `part.geometry` (§5).
PARAMS = {}

part.geometry = Box(10.0, 10.0, 10.0)

# `heph lint` asks for these two (§5.2); fill them in when the shape is real.
# part.description = ""
# part.process = ""
"""

_SOLID: Final[str] = """\
# Scaffolded by `heph part create --template solid`. Edit or replace it.
#
# A bounded Param is a declared design range, not a default: the bounds are what
# a check, a sweep, or the model may move the value between (script contract §3).
# Labelled solids are addressable as "<part>/<label>" by checks and constraints.
PARAMS = {
    "width": Param(40.0, min=10.0, max=120.0),
    "depth": Param(30.0, min=10.0, max=120.0),
    "thickness": Param(8.0, min=2.0, max=40.0),
}

body = Box(p.width, p.depth, p.thickness)
body.label = "body"
part.geometry = body
part.description = "Solid block scaffolded by heph part create"
part.process = "cnc_router"
"""

_SHEET: Final[str] = """\
# Scaffolded by `heph part create --template sheet`. Edit or replace it.
#
# Sheet parts are solids too: a flat pattern is a profile extruded to the stock
# thickness, which is what `heph cam emit` flattens back out. Keep the thickness
# a Param so the stock form and the geometry cannot disagree.
PARAMS = {
    "length": Param(80.0, min=10.0, max=600.0),
    "width": Param(50.0, min=10.0, max=600.0),
    "thickness": Param(3.0, min=0.5, max=12.0),
}

profile = Rectangle(p.length, p.width)
blank = extrude(profile, amount=p.thickness)
blank.label = "sheet_blank"
part.geometry = blank
part.description = "Sheet-metal blank scaffolded by heph part create"
part.process = "laser_cut"
part.stock_form = "sheet"
"""

_FROM_STORE: Final[str] = """\
# Scaffolded by `heph part create --template from_store`. Edit or replace it.
#
# This is the carrier for a parts-store component (PARTS_STORE.md §2.4): the
# component lives *inside* this part's script, so its interfaces and this
# carrier's features anchor against each other without a cross-part constraint.
#
# To fill it in:
#   1. find the component  — the `search_parts_store` tool, by name or class;
#   2. instance it         — the `instance_store_part` tool returns a
#                            `script_fragment` already placed at your `pos`;
#   3. paste that fragment below this line, then add its instance name to the
#      Compound children — e.g. Compound(children=[carrier, nema17_a91f03]).
#
# Until a fragment is pasted this builds the carrier alone, so the part is
# buildable at every step rather than only at the end.
PARAMS = {
    "carrier_length": Param(60.0, min=10.0, max=400.0),
    "carrier_width": Param(60.0, min=10.0, max=400.0),
    "carrier_thickness": Param(6.0, min=2.0, max=40.0),
}

carrier = Box(p.carrier_length, p.carrier_width, p.carrier_thickness)
carrier.label = "carrier"

# --- paste the store fragment above this line ---

part.geometry = Compound(children=[carrier])
part.description = "Parts-store carrier scaffolded by heph part create"
part.process = "cnc_router"
"""

#: The create-part table. Every value builds under the part-script contract —
#: see the module docstring and ``test_every_template_builds``.
PART_TEMPLATES: Final[dict[str, str]] = {
    "blank": _BLANK,
    "solid": _SOLID,
    "sheet": _SHEET,
    "from_store": _FROM_STORE,
}

#: Compatibility alias — the dispatcher exported this name first.
BLANK_TEMPLATES: Final[dict[str, str]] = PART_TEMPLATES

TEMPLATE_NAMES: Final[tuple[str, ...]] = ("blank", "sheet", "solid", "from_store")
