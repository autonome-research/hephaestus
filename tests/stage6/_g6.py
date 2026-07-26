# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G6 evidence suite.

Every G6 clause is asserted against a **real project driven through the real
tool dispatcher** — the surface a model actually calls — over a real opstore.
Two backends are used deliberately:

* :class:`~hephaestus.core.executor.sandbox.bwrap.BwrapBackend` wherever
  registry content executes (DFM rule predicates, store-part generators), because
  architecture §3.6/§7.2 give registry content no capability a part script does
  not have and no path that skips the sandbox;
* the unsafe local backend for the drawing/nesting/registry-integrity clauses,
  whose subject is the produced bytes rather than what executed.

The fixture geometry is authored here rather than imported from
``corpus/`` so a gate assertion cannot be satisfied by a change to a bench task.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.registry import RegistryOps, RegistrySet

from opstore import OpStore

REPO = Path(__file__).resolve().parents[2]

#: Registry content executes only under a probed OS sandbox; a machine without
#: one cannot produce the DFM half of the gate evidence (and must not fake it).
requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="registry content (DFM predicates, store generators) needs a probed bwrap sandbox",
)

ORCH = Principal(session_id="g6", profile="orchestrator", part=None)

# --------------------------------------------------------------------------
# fixture parts

#: A 5.5 mm laser-cut panel whose material is stocked at 3/6/12/18 mm, with a
#: 0.5 mm-diameter tagged bore and 0.3 mm internal corner radii: one known
#: violation of each of the three ``laser_cut`` rules, each on named topology.
VENT_PANEL_SRC = """PARAMS = {
    "thickness": Param(5.5, min=3.0, max=12.0),
}

panel = Box(80.0, 50.0, p.thickness)
panel = panel - Pos(12.0, 0.0, 0.0) * Cylinder(0.25, 20.0)
panel = panel - Pos(-26.0, 15.0, 0.0) * Box(16.0, 16.0, 20.0)
corners = [e for e in panel.edges().filter_by(Axis.Z) if abs(e.center().Y - 7.0) < 1e-6]
panel = fillet(corners, 0.3)
vent = [
    f
    for f in panel.faces()
    if f.geom_type == GeomType.CYLINDER
    and abs(f.center().X - 12.0) < 0.5
    and abs(f.center().Y) < 0.5
][0]
tag(vent, "vent_bore")
part.geometry = panel
part.description = "a laser-cut vent panel with a too-small bore"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
"""

#: A printed tray: 0.8 mm walls, a 1.0 mm tagged drain bore and a 63-degree
#: conical overhang — one known violation of each of the three ``fdm`` rules.
TRAY_SRC = """PARAMS = {
    "height": Param(15.0, min=8.0, max=40.0),
}

bottom = (Align.CENTER, Align.CENTER, Align.MIN)
tray = Box(30.0, 20.0, p.height, align=bottom) - Pos(0.0, 0.0, 0.8) * Box(
    28.4, 18.4, 40.0, align=bottom
)
tray = tray - Cylinder(0.5, 4.0, align=bottom)
drain = [f for f in tray.faces() if f.geom_type == GeomType.CYLINDER][0]
tag(drain, "drain_bore")
flare = Cone(bottom_radius=1.0, top_radius=9.0, height=4.0, align=bottom)
part.geometry = Compound(children=[tray, Pos(40.0, 0.0, 0.0) * flare])
part.description = "a printed tray with a drain and a flare"
part.process = "fdm"
part.material_spec = "PLA filament"
"""

#: A plain printed block: nothing either pack can complain about.
BLOCK_SRC = """block = Box(30.0, 20.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
part.geometry = block
part.description = "a solid printed block"
part.process = "fdm"
"""

#: The shelf-class drawing fixture: three labelled solids (a deck on two sides),
#: an 8 mm cable bore, and the §5.2 metadata a title block is read from. Its
#: five principal dimensions are 600 x 250 x 218 overall, 18.0 material
#: thickness and a Ø8.0 bore.
SHELF_SRC = """PARAMS = {
    "width": Param(600.0, min=200.0, max=1200.0),
}

t = 18.0
deck = Pos(0.0, 125.0, t / 2.0) * Box(p.width, 250.0, t)
deck = deck - Pos(0.0, 125.0, t / 2.0) * Cylinder(4.0, 4.0 * t)
deck.label = "deck"
left = Pos(-p.width / 2.0 + t / 2.0, 125.0, -100.0) * Box(t, 250.0, 200.0)
left.label = "side"
right = Pos(p.width / 2.0 - t / 2.0, 125.0, -100.0) * Box(t, 250.0, 200.0)
right.label = "side"
part.geometry = Compound(children=[deck, left, right])

part.description = "Wall shelf: deck on two side panels, cable pass-through"
part.material_spec = "18 mm Baltic birch plywood"
part.process = "laser_cut"
part.stock_form = "sheet"
part.general_tolerance = "+/-0.25 mm cut profile"
part.finish = "sanded, hardwax oiled"
"""

#: The gusset-class nesting fixture: three flat laminations of one 6 mm sheet,
#: declared to be cut from a 210 x 125 mm blank.
GUSSET_SRC = """PARAMS = {"t": Param(6.0, min=3.0, max=12.0)}

web = extrude(make_face(Polyline((0.0, 0.0), (100.0, 0.0), (0.0, 60.0), close=True)), amount=p.t)
web.label = "web"
spacer = Pos(150.0, 0.0, 0.0) * Box(60.0, 40.0, p.t, align=(Align.MIN, Align.MIN, Align.MIN))
spacer.label = "spacer"
cleat = Pos(0.0, 100.0, 0.0) * Box(90.0, 25.0, p.t, align=(Align.MIN, Align.MIN, Align.MIN))
cleat.label = "cleat"
part.geometry = Compound(children=[web, spacer, cleat])

part.description = "Shelf gusset laminations: triangular web, spacer and cleat"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
part.blank_size = "210 x 125 mm blank, one set per blank"
"""

#: Every fixture part, by name. Scaffolding writes the subset a case asks for.
FIXTURE_PARTS: dict[str, str] = {
    "vent_panel": VENT_PANEL_SRC,
    "tray": TRAY_SRC,
    "block": BLOCK_SRC,
    "shelf": SHELF_SRC,
    "gusset": GUSSET_SRC,
}

GLOBALS_SRC = 'PARAMS = {\n    "spare": Param(1.0, min=0.5, max=2.0),\n}\n'


# --------------------------------------------------------------------------
# the project under test


@dataclass
class G6Project:
    """One scaffolded project, its ops object and the dispatcher under test."""

    root: Path
    layout: ProjectLayout
    store: OpStore
    cad: CadOps
    dispatcher: ToolDispatcher
    _n: list[int]

    def call(self, tool: str, arguments: dict[str, Any], *, entry: str | None = None) -> Any:
        """Dispatch one tool call the way the agent sidecar does."""
        self._n[0] += 1
        return self.dispatcher.dispatch(
            ORCH,
            {
                "session_id": ORCH.session_id,
                "run_id": "run-g6",
                "tool": tool,
                "arguments": arguments,
                "invocation": {
                    "session_id": ORCH.session_id,
                    "entry_id": entry or f"g6-{self._n[0]}",
                    "ordinal": 1,
                    "provider_call_id": f"call_{self._n[0]}",
                },
            },
        )

    def build(self, name: str, params: dict[str, Any] | None = None) -> str:
        """Build one part through the tool surface; return its artifact ref."""
        arguments: dict[str, Any] = {"name": name}
        if params is not None:
            arguments["params"] = params
        result = dict(self.call("build_part", arguments))
        assert result["status"] == "ok", result.get("error")
        ref = result["artifact_ref"]
        assert isinstance(ref, str)
        return ref

    def read(self, rel_path: str) -> bytes:
        return (self.root / rel_path).read_bytes()

    def close(self) -> None:
        self.store.close()


def make_g6_project(
    root: Path,
    parts: tuple[str, ...],
    *,
    secure: bool,
    manifest_extra: str = "",
    wire_registry: bool = False,
) -> G6Project:
    """Scaffold a project holding ``parts`` and wire the real dispatcher to it.

    ``wire_registry`` additionally wires the registry tool family over the
    project's *pinned* registry set, so ``instance_store_part`` executes store
    generators under the same backend the parts do.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text(
        '[project]\nname = "g6"\n' + manifest_extra, encoding="utf-8"
    )
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    for name in parts:
        (root / "parts" / f"{name}.py").write_text(FIXTURE_PARTS[name], encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    backend: Any = BwrapBackend() if secure else UnsafeLocalBackend()
    cad = CadOps(layout, store, backend=backend)
    registry: RegistryOps | None = None
    if wire_registry:
        registry = RegistryOps(
            RegistrySet.open(root),
            store,
            backend=backend,
            scratch_root=root / ".heph" / "scratch",
        )
    dispatcher = ToolDispatcher(ProjectStore(layout, store), cad=cad, registry=registry)
    return G6Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])


# --------------------------------------------------------------------------
# reading the evidence


def artifact_topology(project: G6Project, part: str, artifact_ref: str) -> Any:
    """The build123d shape a finding's descriptors are supposed to address."""
    target = project.cad.dfm_target(part, artifact_ref=artifact_ref)
    return load_brep_shape(target.brep)


def resolve_descriptor(shape: Any, descriptor: dict[str, Any]) -> Any:
    """Resolve one ``{kind, solid_id, topology_index}`` against the artifact.

    Raises ``IndexError`` if the descriptor does not address anything in these
    bytes — which is exactly the failure a bare mask id would produce.
    """
    solid = shape.solids()[int(descriptor["solid_id"])]
    kind = str(descriptor["kind"])
    if kind == "solid":
        return solid
    entities = solid.faces() if kind == "face" else solid.edges()
    return list(entities)[int(descriptor["topology_index"])]
