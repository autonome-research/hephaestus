# M3 socket-head cap screw — DIN 912 head/shank envelope, thread-free.
#
# Coordinate convention: the ORIGIN sits on the head bearing face. The head
# occupies 0 .. +3 mm in Z; the shank hangs below into the workpiece. Place an
# instance at the counterbore floor (or at the panel face for a plain
# through-hole) and the seated screw lands where the geometry says it does.
#
# Deliberately simplified: no thread helix, no under-head fillet, no washer
# face. The solid is the DIN 912 *envelope*, which is what clearance,
# interference and head-below-surface checks actually need. Do not use it to
# reason about thread engagement or preload.
#
# Suggested mating features:
#   clearance hole  3.4 mm    counterbore  6.5 mm dia x >= 3 mm deep

# --- hephaestus-store: params ---
PARAMS = {
    "length": Param(12.0, min=6.0, max=30.0, doc="shank length below the head, mm"),
}
# --- hephaestus-store: bind ---
_length = p.length
# --- hephaestus-store: body ---
_head_d = 5.5
_head_h = 3.0
_shank_d = 3.0
_socket_af = 2.5
_socket_depth = 2.0
# A hexagon's across-flats distance AF gives circumradius AF / sqrt(3).
_socket_r = _socket_af / math.sqrt(3.0)
_head = Cylinder(_head_d / 2, _head_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_shank = Cylinder(_shank_d / 2, _length, align=(Align.CENTER, Align.CENTER, Align.MAX))
_socket = extrude(
    Plane.XY.offset(_head_h) * RegularPolygon(_socket_r, 6), amount=-_socket_depth
)
_screw = (_head + _shank) - _socket
_screw.color = Color(0.62, 0.64, 0.67)
_screw.label = "screw_socket_head_m3"
part.geometry = _screw
