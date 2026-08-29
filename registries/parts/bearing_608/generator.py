# 608 deep-groove ball bearing — ISO 15 boundary-dimension envelope.
#
# Coordinate convention: the ORIGIN sits on the back face, on the bore axis.
# The bearing spans 0 .. +7 mm in Z. Instance it at the shoulder a shaft
# steps down to and the seated bearing lands where the geometry says it does.
#
# Deliberately simplified: this is the BOUNDARY envelope — bore, outside
# diameter, width — modelled as a plain annular ring. There are no raceways,
# no balls, no cage, no shields and no chamfers, because none of them is
# reachable from the outside of an installed bearing and none of them is what
# a housing bore or a shaft seat has to fit. Do not use it to reason about
# load paths, preload or internal clearance.
#
# Every number here is a nominal boundary dimension of ISO 15's 608
# designation (8 x 22 x 7). Those are the dimensions of a public interface
# standard, which PARTS_STORE.md §7.1 admits by name; no vendor drawing was
# consulted and none is redistributed.
#
# Suggested mating features:
#   shaft seat        8 mm dia, k5/j5 for a rotating inner ring
#   housing bore     22 mm dia, H7 for a stationary outer ring

# --- hephaestus-store: params ---
PARAMS = {}
# --- hephaestus-store: bind ---
# --- hephaestus-store: body ---
_bore_d = 8.0
_outer_d = 22.0
_width = 7.0
_ring = Cylinder(_outer_d / 2, _width, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(
    _bore_d / 2, _width, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_ring.color = Color(0.55, 0.57, 0.6)
_ring.label = "bearing_608"
part.geometry = _ring

# --- hephaestus-store: interface ---
# PARTS_STORE.md §2.1: every selector is rooted at the published shape and is
# ordered by a MEASURE, never by a world axis — a measure survives the Pos/Rot
# the consumer applies, and `sort_by(Axis.Z)` does not.
#
# A plain annulus has exactly two cylindrical faces and their radii differ by
# construction at the one and only size this part ships, so radius alone names
# both. The two end annuli are CONGRUENT and no measure distinguishes them, so
# neither is declared: a bearing's axial datum is the housing shoulder it is
# pressed against, not a face of the bearing.
tag(_ring.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "bore")
tag(_ring.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "outer")
