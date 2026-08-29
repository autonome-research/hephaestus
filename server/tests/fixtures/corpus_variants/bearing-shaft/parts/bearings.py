# INDEPENDENT SECOND IMPLEMENTATION (VALIDATION.md §1) — and a deliberate
# exception, stated rather than hidden. The store fragment below is
# `instance_store_part`'s OUTPUT, not this author's geometry: a second
# author instancing the same component at the same pos gets the same bytes
# by construction (PARTS_STORE.md §9), so varying it would be varying the
# store rather than the solution. The independence this task needs lives in
# the part the run actually authors, which really is built differently.
#
# Variant solution for bench task bearing-shaft — the two support bearings.
#
# Both are `bearing_608` instances from the pinned parts store, pasted exactly as
# `instance_store_part` rendered them: the store's own body, its placement, and
# its interface region, which is what emits the `brg_a__bore` / `brg_b__bore`
# tags the task's two `fit` constraints anchor on. The store's convention puts
# the origin on the back face on the bore axis, so an instance placed at the
# journal's near end lands where the geometry says it does.
#
# The two calls differ only in `pos` and in `instance`; `instance` is what scopes
# the emitted tag names, so pasting the same component twice does not collide
# (PARTS_STORE.md §2.2).

# 608 deep-groove ball bearing (ISO 15 boundary envelope) — parts-store instance at (0, 0, 6) mm, rotated (0, 0, 0)deg.
# registry: hephaestus-parts @ sha256:ff9e43925bfcf7a868e630fa322018664e416e48726cdd28d077a60e5f0ed780   id: bearing_608
# Reference geometry from a pinned registry: review it, then compose
#   _brg_a into part.geometry (e.g. Compound(children=[..., _brg_a])).

_brg_a_bore_d = 8.0
_brg_a_outer_d = 22.0
_brg_a_width = 7.0
_brg_a_ring = Cylinder(_brg_a_outer_d / 2, _brg_a_width, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(
    _brg_a_bore_d / 2, _brg_a_width, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_brg_a_ring.color = Color(0.55, 0.57, 0.6)
_brg_a_ring.label = "bearing_608"
_brg_a = Pos(0.0, 0.0, 6.0) * _brg_a_ring
_brg_a.label = "bearing_608"
# PARTS_STORE.md §2.1: every selector is rooted at the published shape and is
# ordered by a MEASURE, never by a world axis — a measure survives the Pos/Rot
# the consumer applies, and `sort_by(Axis.Z)` does not.
#
# A plain annulus has exactly two cylindrical faces and their radii differ by
# construction at the one and only size this part ships, so radius alone names
# both. The two end annuli are CONGRUENT and no measure distinguishes them, so
# neither is declared: a bearing's axial datum is the housing shoulder it is
# pressed against, not a face of the bearing.
tag(_brg_a.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "brg_a__bore")
tag(_brg_a.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "brg_a__outer")

# 608 deep-groove ball bearing (ISO 15 boundary envelope) — parts-store instance at (0, 0, 47) mm, rotated (0, 0, 0)deg.
# registry: hephaestus-parts @ sha256:ff9e43925bfcf7a868e630fa322018664e416e48726cdd28d077a60e5f0ed780   id: bearing_608
# Reference geometry from a pinned registry: review it, then compose
#   _brg_b into part.geometry (e.g. Compound(children=[..., _brg_b])).

_brg_b_bore_d = 8.0
_brg_b_outer_d = 22.0
_brg_b_width = 7.0
_brg_b_ring = Cylinder(_brg_b_outer_d / 2, _brg_b_width, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(
    _brg_b_bore_d / 2, _brg_b_width, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_brg_b_ring.color = Color(0.55, 0.57, 0.6)
_brg_b_ring.label = "bearing_608"
_brg_b = Pos(0.0, 0.0, 47.0) * _brg_b_ring
_brg_b.label = "bearing_608"
# PARTS_STORE.md §2.1: every selector is rooted at the published shape and is
# ordered by a MEASURE, never by a world axis — a measure survives the Pos/Rot
# the consumer applies, and `sort_by(Axis.Z)` does not.
#
# A plain annulus has exactly two cylindrical faces and their radii differ by
# construction at the one and only size this part ships, so radius alone names
# both. The two end annuli are CONGRUENT and no measure distinguishes them, so
# neither is declared: a bearing's axial datum is the housing shoulder it is
# pressed against, not a face of the bearing.
tag(_brg_b.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "brg_b__bore")
tag(_brg_b.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "brg_b__outer")

part.geometry = Compound(children=[_brg_a, _brg_b])

CHECKS = {
    "two_bearings": lambda m: m.volume("part") == approx(2.0 * 2309.0706, abs=0.5),
}

part.description = "Two 608 deep-groove ball bearings supporting the shaft"
part.material_spec = "Store part bearing_608 (ISO 15 boundary envelope, bearing steel)"
part.process = "purchased"
part.assembly_method = "Slip fit onto the shaft journals, retained by the housing"
