# Stair tread kit, nested flat for laser cutting: one grooved tread plate and
# two cleat blanks, all in one sheet. Three labeled solids, so the workspace's
# Results list, its per-entry visibility toggles and the explode transform all
# have something to be about (INTERFACE.md §14: ">=3 solids, so G4.6's all-pairs
# centroid clause is not vacuous").
PARAMS = {
    "groove_count": Param(5, min=2, max=10),
}

tread = Box(hc.tread_w, hc.tread_d, hc.sheet_t)

# Anti-slip grooves across the walking surface, evenly pitched in Y and inset
# from both long edges so the top face is never divided.
_pitch = hc.tread_d / (p.groove_count + 1)
for _i in range(p.groove_count):
    _y = -hc.tread_d / 2.0 + _pitch * (_i + 1)
    tread = tread - Pos(0.0, _y, hc.sheet_t / 2.0) * Box(
        hc.tread_w - 2.0 * hc.groove_margin, hc.groove_w, hc.groove_depth * 2.0
    )

# One drainage bore. 0.5 mm across is below what the beam can cut cleanly:
# the fixture's `laser_cut.min_feature_vs_kerf` violation.
tread = tread - Pos(hc.tread_w / 2.0 - 14.0, 0.0, 0.0) * Cylinder(hc.drain_r, hc.sheet_t * 3.0)

# A service notch in the +Y edge. Its two internal corners are rounded tighter
# than the beam radius: the `laser_cut.min_internal_radius` violation.
tread = tread - Pos(-hc.tread_w / 2.0 + 18.0, hc.tread_d / 2.0, 0.0) * Box(
    hc.notch_w, hc.notch_d, hc.sheet_t * 3.0
)
_notch_y = hc.tread_d / 2.0 - hc.notch_d / 2.0
_corners = [
    e for e in tread.edges().filter_by(Axis.Z) if abs(e.center().Y - _notch_y) < 1e-6
]
tread = fillet(_corners, hc.notch_radius)
tread.label = "tread"

# The walking surface. `tread_top` is the fixture's tagged face and THIS is its
# creating line: G5.4 joins the tag back to it through the source map.
tag(tread.faces().sort_by(Axis.Z)[-1], "tread_top")

# Two cleat blanks nested beside the tread, flat in the same sheet. Separately
# labeled — one solid each — so a visibility toggle addresses exactly one solid
# (INTERFACE.md §5.4 keys visibility by geometry-entry label).
_cleat_y = hc.tread_d / 2.0 + hc.sheet_gap + hc.cleat_d / 2.0
cleat_left = Pos(-60.0, -_cleat_y, 0.0) * Box(hc.cleat_w, hc.cleat_d, hc.sheet_t)
cleat_left.label = "cleat_left"
cleat_right = Pos(60.0, _cleat_y, 0.0) * Box(hc.cleat_w, hc.cleat_d, hc.sheet_t)
cleat_right.label = "cleat_right"

part.geometry = Compound(children=[tread, cleat_left, cleat_right])

# The whole assignable metadata surface (script_contract.md §5.2, nine names).
# `blank_size` is an f-string ON PURPOSE: a static AST parse of this script
# cannot recover it, so the properties projection has to read the build record's
# runtime metadata to serve all nine (INTERFACE.md §6.2, G4.3).
part.description = "Flat-pack stair tread: a grooved tread plate and two cleats, nested in one sheet"
part.material_spec = "Baltic birch plywood (BB/BB) sheet"
part.process = "laser_cut"
part.stock_form = "sheet"
part.blank_size = f"{hc.tread_w:.0f} x {hc.tread_d + 2.0 * (hc.sheet_gap + hc.cleat_d):.0f} x {hc.sheet_t:.1f} mm"
part.general_tolerance = "+/-0.25 mm cut profile"
part.finish = "Sand the laser char off every edge; clear water-based poly on the tread"
part.assembly_method = "PVA the two cleats to the tread underside, flush with the short edges; clamp 30 min"
part.joint = "Glued lap; the cleats register on the tread's long edges and take the riser screws"
part.feature("tread_top").surface_finish = "Leave the grooves unsanded; they are the anti-slip feature"
