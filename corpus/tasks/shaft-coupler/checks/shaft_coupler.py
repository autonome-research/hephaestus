# shaft-coupler acceptance checks (project scope: whole-part measurements only).
#
# The centrepiece of this task - the hole/shaft sliding fit - is NOT measured
# here: it is the task's declared `fit` constraint (ASSEMBLY.md §3), graded as
# a radial hole/shaft window through the engine constraint path, alongside a
# no_interference and the seat-height distance. What CHECKS owns is the
# single-part facts:
#
# - envelope: the stepped shaft's extents (Ø20 hub under a Ø12 spindle, 58
#   tall) and the sleeve's (Ø22 x 30);
# - the whole-assembly closest approach IS the sliding gap: the bore wall over
#   the spindle, inside the same 0.02-0.08 mm window the fit declares - so a
#   coupler parked beside the shaft (right radii, wrong place) fails here even
#   though a radius window alone cannot see position;
# - topology: the shaft is one plain sealed solid (genus 0); the coupler is a
#   sleeve whose set-screw hole really breaks into the bore (sealed, genus 2).
_GAP_MIN = 0.015
_GAP_MAX = 0.085

CHECKS = {
    "shaft_envelope": lambda m: m.bbox("shaft/part") == approx((20.0, 20.0, 58.0), abs=0.05),
    "coupler_envelope": lambda m: m.bbox("coupler/part") == approx((22.0, 22.0, 30.0), abs=0.05),
    "coupler_rides_the_spindle_with_sliding_gap": lambda m: _GAP_MIN
    <= m.clearance("shaft/part", "coupler/part")
    <= _GAP_MAX,
    "shaft_sealed": lambda m: m.sealed("shaft/part") and m.genus("shaft/part") == 0,
    "coupler_sealed_with_setscrew_path": lambda m: m.sealed("coupler/part")
    and m.genus("coupler/part") == 2,
}
