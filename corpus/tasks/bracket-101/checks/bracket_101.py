# bracket-101 acceptance checks (project scope: whole-part measurements only —
# a reloaded build artifact resolves the "<part>/part" selector, so feature-level
# facts are measured by fitting the task's own inspection gauge).
#
# - envelope: the bracket's overall extents;
# - material: a budget on the intended solid (60x40x6 plate + 60x6x34 wall +
#   R4 inner fillet - two 6 mm through-holes). The envelope and the gauge already
#   pin the extents and the hole diameters, so what this window is really
#   measuring is the inner blend;
# - hole pattern: the 5.9 mm go-pins on the specified centres must pass through
#   with a 0.05 mm radial gap and never bite into the bracket;
# - topology: one sealed solid with two tunnels (genus 2).
_ENV_MAX = (60.05, 40.05, 40.05)
_ENV_MIN = (59.95, 39.95, 39.95)

# Material budget, not an identity (re-authored 2026-07-26, corpus audit). The
# window is +/-100 mm^3 (0.38%): the smallest spec deviation it has to catch is a
# missing R4 blend, which is r^2 (1 - pi/4) t = 206 mm^3 away, so the window sits
# a factor of 2 below what it must reject and comfortably above the cosmetic
# variation a correct bracket may legitimately carry (a 0.5 mm edge break round
# the plate is ~50 mm^3).
_VOLUME_MM3 = 26506.73
_VOLUME_WINDOW = 100.0

CHECKS = {
    "envelope": lambda m: m.bbox("bracket/part") <= _ENV_MAX
    and m.bbox("bracket/part") >= _ENV_MIN,
    "material_budget": lambda m: m.volume("bracket/part")
    == approx(_VOLUME_MM3, abs=_VOLUME_WINDOW),
    "gauge_pins_pass": lambda m: m.interference("bracket/part", "hole_gauge/part")
    == approx(0.0, abs=1e-6),
    "hole_pattern_clearance": lambda m: m.clearance("bracket/part", "hole_gauge/part")
    == approx(0.05, abs=0.02),
    "sealed": lambda m: m.sealed("bracket/part") and m.genus("bracket/part") == 2,
}
