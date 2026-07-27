# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). The lid GO gauge: the material a closing lid must
# have, wherever it must have it. Two solids, both of which the lid must contain
# completely — the acceptance check compares the overlap volume against the
# gauge's own volume.
#
# `cover_slab`: the seating plate. A slab across the footprint (inset 0.5 mm all
#   round so an edge break is still a pass) spanning 0.1 mm inside the plate's
#   z band, bored 5.2 mm at the four screw positions so any sane clearance hole
#   passes through it. Containment says the lid really is a full-thickness
#   closed cover over the box, not a thin sheet or a frame with a hole in it.
# `register_band`: the lip's engagement. A frame 0.5-1.5 mm inside the cavity
#   opening, over 1.2 mm of the lip's 2 mm depth. Containment says a register
#   lip runs the whole way round and drops far enough into the cavity to locate
#   the lid — and it says nothing about whether the lip is a solid block or a
#   peripheral rib, because either one registers.
#
# Together with `register_gauge` (which measures how much clearance that lip
# leaves) this is the register fit as two measurements: it engages, and it is
# not a press fit. Neither one reproduces a particular lid.
_cav_x = hc.box_len - 2.0 * hc.wall_t
_cav_y = hc.box_width - 2.0 * hc.wall_t
_edge_break = 0.5
_bore_r = (hc.lid_hole_d + 1.8) / 2.0

_slab = Pos(0, 0, hc.box_height + 0.1) * Box(
    hc.box_len - 2.0 * _edge_break,
    hc.box_width - 2.0 * _edge_break,
    hc.lid_t - 0.2,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        _slab = _slab - Pos(_sx * hc.boss_x, _sy * hc.boss_y, hc.box_height - 1.0) * Cylinder(
            radius=_bore_r,
            height=hc.lid_t + 2.0,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
_slab.label = "cover_slab"

_band_z0 = hc.box_height - hc.lid_lip_h + 0.2
_band_z1 = hc.box_height - 0.6
_band_outer = Pos(0, 0, _band_z0) * Box(
    _cav_x - 1.0,
    _cav_y - 1.0,
    _band_z1 - _band_z0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
_band_inner = Pos(0, 0, _band_z0 - 1.0) * Box(
    _cav_x - 3.0,
    _cav_y - 3.0,
    (_band_z1 - _band_z0) + 2.0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
_band = _band_outer - _band_inner
_band.label = "register_band"

part.geometry = Compound(children=[_slab, _band])

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part")
    == approx(
        (
            hc.box_len - 2.0 * _edge_break,
            hc.box_width - 2.0 * _edge_break,
            (hc.box_height + 0.1 + hc.lid_t - 0.2) - _band_z0,
        ),
        abs=0.01,
    ),
}

part.description = "Lid go-gauge: full-thickness cover slab plus register engagement band"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
