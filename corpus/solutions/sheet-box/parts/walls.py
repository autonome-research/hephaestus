# Reference solution for bench task sheet-box — the four assembled walls.
#
# One flat panel generator is used for every wall: a length x wall_height plate
# with two tabs hanging one sheet thickness below its bottom edge. The panels are
# then stood up into the assembled tray, so the cut file and the assembly are the
# same geometry seen from two places.
_t = hc.sheet_t
_h = hc.wall_height
_long_len = hc.box_len
_short_len = hc.box_width - 2.0 * _t


def _wall_panel(length):
    """Flat wall panel: x in [-length/2, length/2], y in [-t, h], z in [0, t]."""
    _plate = Pos(0, _h / 2.0, _t / 2.0) * Box(length, _h, _t)
    _tab_a = Pos(-length / 4.0, -_t / 2.0, _t / 2.0) * Box(hc.tab_len, _t, _t)
    _tab_b = Pos(length / 4.0, -_t / 2.0, _t / 2.0) * Box(hc.tab_len, _t, _t)
    return _plate + _tab_a + _tab_b


# Long walls run along X; their outer faces are the tray's +/-Y faces.
_wall_y = hc.box_width / 2.0 - _t
front = Pos(0, -_wall_y, 0) * Rot(90, 0, 0) * _wall_panel(_long_len)
front.label = "wall_front"
back = Pos(0, _wall_y, 0) * Rot(0, 0, 180) * Rot(90, 0, 0) * _wall_panel(_long_len)
back.label = "wall_back"

# Short walls run along Y between the long walls' inner faces.
_wall_x = hc.box_len / 2.0 - _t
right = Pos(_wall_x, 0, 0) * Rot(0, 0, 90) * Rot(90, 0, 0) * _wall_panel(_short_len)
right.label = "wall_right"
left = Pos(-_wall_x, 0, 0) * Rot(0, 0, -90) * Rot(90, 0, 0) * _wall_panel(_short_len)
left.label = "wall_left"

part.geometry = Compound(children=[front, back, right, left])

CHECKS = {
    "assembled_envelope": lambda m: m.bbox("part")
    == approx((hc.box_len, hc.box_width, hc.wall_height + hc.sheet_t), abs=0.05),
    "corners_butt_without_overlap": lambda m: m.interference("wall_front", "wall_right")
    == approx(0.0, abs=1e-6),
}

part.description = "Four tabbed tray walls in their assembled positions"
part.material_spec = "6 mm Baltic birch plywood"
part.process = "cnc_router"
part.stock_form = "sheet"
part.joint = "Through tabs into the base panel; butt joints at the corners"
