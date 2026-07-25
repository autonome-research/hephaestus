# Reference solution for bench task sheet-box — the flat cut layout.
#
# The same five panels as `base` and `walls`, laid flat on the sheet (all of them
# in z = 0 .. sheet_t, none of them overlapping) so the as_built DXF of this part
# is the cut file: five outermost profiles plus the base panel's interior slots.
_t = hc.sheet_t
_kerf = hc.kerf
_h = hc.wall_height
_long_len = hc.box_len
_short_len = hc.box_width - 2.0 * _t


def _wall_panel(length):
    """Flat wall panel: x in [-length/2, length/2], y in [-t, h], z in [0, t]."""
    _plate = Pos(0, _h / 2.0, _t / 2.0) * Box(length, _h, _t)
    _tab_a = Pos(-length / 4.0, -_t / 2.0, _t / 2.0) * Box(hc.tab_len, _t, _t)
    _tab_b = Pos(length / 4.0, -_t / 2.0, _t / 2.0) * Box(hc.tab_len, _t, _t)
    return _plate + _tab_a + _tab_b


def _base_panel():
    """Flat base panel with the eight kerf-compensated tab slots."""
    _wall_y = hc.box_width / 2.0 - _t / 2.0
    _wall_x = hc.box_len / 2.0 - _t / 2.0
    _end_tab_x = hc.box_len / 4.0
    _side_tab_y = _short_len / 4.0
    _panel = Pos(0, 0, _t / 2.0) * Box(hc.base_len, hc.base_width, _t)
    for _sx in (-1.0, 1.0):
        for _sy in (-1.0, 1.0):
            _panel = _panel - Pos(_sx * _end_tab_x, _sy * _wall_y, _t / 2.0) * Box(
                hc.tab_len + _kerf, _t + _kerf, _t
            )
            _panel = _panel - Pos(_sx * _wall_x, _sy * _side_tab_y, _t / 2.0) * Box(
                _t + _kerf, hc.tab_len + _kerf, _t
            )
    return _panel


# Nested up the sheet with a 14 mm gap between panels: every profile is separate,
# so a nesting or CAM step sees exactly five cut outlines.
_pitch = _h + _t + 14.0
base_blank = _base_panel()
base_blank.label = "layout_base"
wall_front = Pos(0, hc.base_width / 2.0 + 14.0 + _t, 0) * _wall_panel(_long_len)
wall_front.label = "layout_wall_front"
wall_back = Pos(0, hc.base_width / 2.0 + 14.0 + _t + _pitch, 0) * _wall_panel(_long_len)
wall_back.label = "layout_wall_back"
wall_left = Pos(0, hc.base_width / 2.0 + 14.0 + _t + 2.0 * _pitch, 0) * _wall_panel(_short_len)
wall_left.label = "layout_wall_left"
wall_right = Pos(0, hc.base_width / 2.0 + 14.0 + _t + 3.0 * _pitch, 0) * _wall_panel(_short_len)
wall_right.label = "layout_wall_right"

part.geometry = Compound(
    children=[base_blank, wall_front, wall_back, wall_left, wall_right]
)

CHECKS = {
    "everything_is_one_sheet_thick": lambda m: m.bbox("part")[2]
    == approx(hc.sheet_t, abs=0.01),
    "panels_do_not_overlap": lambda m: m.interference("layout_base", "layout_wall_front")
    == approx(0.0, abs=1e-6),
}

part.description = "Flat cut layout: the five tray panels nested on one sheet"
part.material_spec = "6 mm Baltic birch plywood"
part.process = "cnc_router"
part.stock_form = "sheet"
part.blank_size = "110 x 320 mm"
