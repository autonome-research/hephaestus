# solve-boss-fit acceptance checks (project scope: whole-part measurements).
#
# The graded engineering is the FIT, and the fit is declared rather than
# retyped: the task's `proposal_requirements` entry measures the radial
# clearance between the boss's tagged bore and the cap's tagged spigot through
# the engine constraint path, on the geometry the run actually rebuilt. A
# `propose_placement` result applies nothing, so a run that computes the right
# spigot radius and never authors it delivers nothing and fails there.
#
# What CHECKS pins is what a fit cannot see - a fit is invariant under any
# rigid motion and says nothing about whether the cap is still a cap. The
# flange window is a material budget: it rejects a cap built without its
# flange (3079 mm^3) while admitting the whole legal spigot range, whose own
# volume spans only 336 mm^3 across min..max.
_CAP_VOLUME = 4867.0
_CAP_WINDOW = 400.0

CHECKS = {
    "boss_envelope": lambda m: m.bbox("boss/part") == approx((30.0, 30.0, 12.0), abs=0.05),
    "boss_is_bored_through": lambda m: m.sealed("boss/part") and m.genus("boss/part") == 1,
    "cap_flange_diameter": lambda m: m.bbox("cap/part")[:2] == approx((28.0, 28.0), abs=0.05),
    "cap_is_one_sealed_solid": lambda m: m.sealed("cap/part") and m.genus("cap/part") == 0,
    "cap_carries_its_flange": lambda m: m.volume("cap/part")
    == approx(_CAP_VOLUME, abs=_CAP_WINDOW),
}
