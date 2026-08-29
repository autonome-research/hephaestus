# M3 heat-set (thermal) insert — brass envelope with its knurl band, thread-free.
#
# Coordinate convention: the ORIGIN sits on the boss top face. The insert body
# runs 0 .. -5.8 mm in Z, i.e. straight down into the boss. Instance it at the
# boss top and subtract it, or keep it as a visual body in the assembly.
#
# Deliberately simplified: the knurl is one cylindrical band at the flange end
# rather than a diamond pattern, and the internal thread is a plain 3 mm bore.
# The envelope is what matters for wall thickness, boss height and interference
# checks; the melt-flow relief the real insert needs is a process allowance, not
# geometry.
#
# Design rules this envelope is for:
#   boss pilot hole      4 mm dia, >= 6.8 mm deep (insert length + melt relief)
#   min boss wall        >= 1.6 mm around the pilot hole
#   `clearance` param    inflates the envelope radially for pocket subtraction

# --- hephaestus-store: params ---
PARAMS = {
    "clearance": Param(
        0.0, min=0.0, max=0.3, doc="radial envelope inflation for pocket subtraction, mm"
    ),
}
# --- hephaestus-store: bind ---
_clearance = p.clearance
# --- hephaestus-store: body ---
_length = 5.8
_body_d = 4.0 + 2 * _clearance
_knurl_d = 4.6 + 2 * _clearance
_knurl_h = 1.6
_bore_d = 3.0
_body = Cylinder(_body_d / 2, _length, align=(Align.CENTER, Align.CENTER, Align.MAX))
# The knurl band sits just below the flange end, where the insert grips.
_knurl = Pos(0, 0, -_knurl_h / 2 - 0.4) * Cylinder(
    _knurl_d / 2, _knurl_h, align=(Align.CENTER, Align.CENTER, Align.CENTER)
)
_bore = Cylinder(_bore_d / 2, _length + 2.0, align=(Align.CENTER, Align.CENTER, Align.MAX))
_insert = (_body + _knurl) - _bore
_insert.color = Color(0.72, 0.58, 0.3)
_insert.label = "heatset_insert_m3"
part.geometry = _insert

# --- hephaestus-store: interface ---
# PARTS_STORE.md §2.1: every selector is rooted at the published shape and is
# ordered by a MEASURE — area, radius, distance between shapes — never by a
# world axis. A measure is invariant under the placement the consumer applies;
# `sort_by(Axis.Z)[-1]` is not, and would silently pick a different face once
# the insert is instanced under a rotation.
#
# The bore and the knurl are the unique smallest- and largest-radius cylinders,
# so radius alone names them. The top and bottom annuli are CONGRUENT — equal
# area, equal geometry — so area alone cannot tell them apart. The knurl band
# sits near the top by construction, so the nearer of the two large annuli to
# the knurl face is the top face, and that distance is measured between two
# pieces of the same placed shape.
tag(
    _insert.faces()
    .filter_by(GeomType.PLANE)
    .sort_by(SortBy.AREA)[-2:]
    .sort_by_distance(
        _insert.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1]
    )[0],
    "top_face",
)
tag(_insert.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "bore")
tag(_insert.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "knurl")
