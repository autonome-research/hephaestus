# Reference solution for bench task store-hardware — the mounting hardware.
#
# Two M5 socket-head cap screws (the parts store's `screw_socket_head_m5`
# envelope: 8.5 x 5 mm head, 5 mm shank, 4 mm hex socket 3 mm deep, thread-free)
# seated in the bracket's counterbores. The store's convention puts the origin on
# the head bearing face with the head above it and the shank hanging below, so an
# instance placed on the counterbore floor lands where the geometry says it does.
PARAMS = {
    "length": Param(16.0, min=8.0, max=50.0, doc="shank length below the head, mm"),
}

_head_d = 8.5
_head_h = 5.0
_shank_d = 5.0
_socket_af = 4.0
_socket_depth = 3.0
_socket_r = _socket_af / math.sqrt(3.0)

# Counterbore floor: 5 mm below the plate's top face.
_seat_z = hc.plate_t - 5.0
_hx = hc.bracket_len / 2.0 - 12.0
_hy = hc.bracket_width / 2.0 - 14.0


def _screw():
    _head = Cylinder(_head_d / 2.0, _head_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    _shank = Cylinder(_shank_d / 2.0, p.length, align=(Align.CENTER, Align.CENTER, Align.MAX))
    _socket = extrude(Plane.XY.offset(_head_h) * RegularPolygon(_socket_r, 6), amount=-_socket_depth)
    return (_head + _shank) - _socket


screw_a = Pos(-_hx, _hy, _seat_z) * _screw()
screw_a.label = "screw_a"
screw_b = Pos(_hx, _hy, _seat_z) * _screw()
screw_b.label = "screw_b"

part.geometry = Compound(children=[screw_a, screw_b])

CHECKS = {
    "two_screws": lambda m: m.volume("screw_a") == approx(m.volume("screw_b"), abs=1e-6),
    "head_buried": lambda m: m.bbox("part")[2] == approx(_head_h + p.length, abs=0.05),
}

part.description = "Two M5 socket-head cap screws seated in the bracket counterbores"
part.material_spec = "Store part screw_socket_head_m5 (DIN 912 envelope, class 12.9)"
part.process = "purchased"
part.assembly_method = "Screwed; heads fully below the mounting face"
