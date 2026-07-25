# Reference solution for bench task sheet-box — the base panel.
#
# A 110 x 90 sheet blank with eight through slots, two for each wall. Every slot
# is the tab footprint grown by the kerf so the cut parts actually assemble:
# slot = (tab_len + kerf) x (sheet_t + kerf).
_t = hc.sheet_t
_kerf = hc.kerf

# Wall centrelines: outer faces flush with the wall box, so the centreline of a
# wall sits half a sheet thickness inside it.
_wall_y = hc.box_width / 2.0 - _t / 2.0
_wall_x = hc.box_len / 2.0 - _t / 2.0

# Tab centres: a quarter of each wall's length in from its ends.
_end_tab_x = hc.box_len / 4.0
_side_tab_y = (hc.box_width - 2.0 * _t) / 4.0

_blank = Pos(0, 0, -_t / 2.0) * Box(hc.base_len, hc.base_width, _t)

_slots = []
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        # Slots for the two long walls (they run along X).
        _slots.append(
            Pos(_sx * _end_tab_x, _sy * _wall_y, -_t / 2.0)
            * Box(hc.tab_len + _kerf, _t + _kerf, _t)
        )
        # Slots for the two short walls (they run along Y).
        _slots.append(
            Pos(_sx * _wall_x, _sy * _side_tab_y, -_t / 2.0)
            * Box(_t + _kerf, hc.tab_len + _kerf, _t)
        )

_panel = _blank
for _slot in _slots:
    _panel = _panel - _slot
_panel.label = "base_panel"

tag(_panel.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1], "base_top")

part.geometry = _panel

CHECKS = {
    "blank_envelope": lambda m: m.bbox("part")
    == approx((hc.base_len, hc.base_width, hc.sheet_t), abs=0.05),
    "eight_through_slots": lambda m: m.sealed("part") and m.genus("part") == 8,
}

part.description = "Tray base panel with eight kerf-compensated tab slots"
part.material_spec = "6 mm Baltic birch plywood"
part.process = "cnc_router"
part.stock_form = "sheet"
part.general_tolerance = "+/-0.2 mm cut profile"
