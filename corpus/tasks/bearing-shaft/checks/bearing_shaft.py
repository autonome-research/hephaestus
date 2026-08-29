# bearing-shaft acceptance checks (project scope: whole-part measurements only).
#
# The graded engineering is the FIT, and the fit is declared, not retyped: the
# two `fit` constraints below (task-owned) measure the radial clearance between
# each store bearing's tagged bore and the shaft's tagged journal, through the
# engine constraint path. What CHECKS pins here is everything a fit cannot see:
# that the shaft is the shaft the fit was declared about, that the bearings are
# the store's envelope and not a hand-drawn ring, and that nothing overlaps.
#
# Windows are budgets. The shaft window is ~3x below the smallest modelling
# error it must reject: turning the journals at nominal 8 mm instead of 7.98
# removes nothing but adds 12.0 mm^3 of material over the two journals, which
# the fit catches; leaving the collar off entirely is 682 mm^3, which this
# catches. The bearings window rejects a single missing bearing (2309 mm^3).
_SHAFT_VOLUME = 5145.69
_SHAFT_WINDOW = 60.0
_BEARINGS_VOLUME = 4618.14
_BEARINGS_WINDOW = 40.0

CHECKS = {
    "shaft_envelope": lambda m: m.bbox("shaft/part") == approx((12.0, 12.0, 60.0), abs=0.05),
    "shaft_stepped": lambda m: m.volume("shaft/part") == approx(_SHAFT_VOLUME, abs=_SHAFT_WINDOW),
    "shaft_sealed": lambda m: m.sealed("shaft/part") and m.genus("shaft/part") == 0,
    "bearings_are_the_store_envelope": lambda m: m.volume("bearings/part")
    == approx(_BEARINGS_VOLUME, abs=_BEARINGS_WINDOW),
    "bearings_span_the_supports": lambda m: m.bbox("bearings/part")
    == approx((22.0, 22.0, 48.0), abs=0.05),
    "bearings_run_free": lambda m: m.interference("shaft/part", "bearings/part")
    == approx(0.0, abs=1e-6),
}
