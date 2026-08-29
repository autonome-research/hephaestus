# M4 socket-head cap screw — DIN 912 head/shank envelope, thread-free.
#
# Coordinate convention: the ORIGIN sits on the head bearing face. The head
# occupies 0 .. +4 mm in Z; the shank hangs below into the workpiece. Place an
# instance at the counterbore floor (or at the panel face for a plain
# through-hole) and the seated screw lands where the geometry says it does.
#
# Deliberately simplified: no thread helix, no under-head fillet, no washer
# face. The solid is the DIN 912 *envelope*, which is what clearance,
# interference and head-below-surface checks actually need. Do not use it to
# reason about thread engagement or preload.
#
# Suggested mating features:
#   clearance hole  4.5 mm    counterbore  8 mm dia x >= 4 mm deep

# --- hephaestus-store: params ---
PARAMS = {
    "length": Param(16.0, min=6.0, max=40.0, doc="shank length below the head, mm"),
}
# --- hephaestus-store: bind ---
_length = p.length
# --- hephaestus-store: body ---
_head_d = 7.0
_head_h = 4.0
_shank_d = 4.0
_socket_af = 3.0
_socket_depth = 2.5
# A hexagon's across-flats distance AF gives circumradius AF / sqrt(3).
_socket_r = _socket_af / math.sqrt(3.0)
_head = Cylinder(_head_d / 2, _head_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_shank = Cylinder(_shank_d / 2, _length, align=(Align.CENTER, Align.CENTER, Align.MAX))
_socket = extrude(
    Plane.XY.offset(_head_h) * RegularPolygon(_socket_r, 6), amount=-_socket_depth
)
_screw = (_head + _shank) - _socket
_screw.color = Color(0.62, 0.64, 0.67)
_screw.label = "screw_socket_head_m4"
part.geometry = _screw

# --- hephaestus-store: interface ---
# PARTS_STORE.md §2.1: every selector is rooted at the published shape and is
# ordered by a MEASURE, never by a world axis — a measure survives the Pos/Rot
# the consumer applies, and `sort_by(Axis.Z)` does not.
#
# The head outer and the shank are the only two cylinders, and the head is the
# larger radius at every declared length. The head top (a disc with the hex
# socket cut out of it) is the largest planar face and the bearing face is the
# next largest, at every size and every length in the declared range; the hex
# flats, the socket floor and the shank end are all smaller.
tag(_screw.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-2], "head_bearing_face")
tag(_screw.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "head_outer")
tag(_screw.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "shank")
