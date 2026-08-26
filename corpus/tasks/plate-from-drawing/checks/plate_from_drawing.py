# plate-from-drawing acceptance checks (project scope: whole-part measurements
# only - feature-level facts are measured by fitting the task's own inspection
# gauge). The numbers below are the drawing's (references/plate-drawing.png):
# 90 x 60 x 6 plate, four Ø5.5 mounting holes with centres 8 mm in from each
# adjacent edge, one Ø22 central bore.
#
# - envelope: the plate's overall extents;
# - material: a BUDGET on the drawn solid (90*60*6 - 4 small holes - the bore);
# - hole pattern: the gauge's five go-pins must pass on the drawn centres with a
#   0.05 mm radial gap and never bite into the plate (which pins both position
#   and diameter: an oversized hole moves the clearance out of its window);
# - topology: one sealed solid with five tunnels (genus 5).
_ENV_MAX = (90.05, 60.05, 6.05)
_ENV_MIN = (89.95, 59.95, 5.95)

# Material budget, not an identity. 90*60*6 - 4*pi*2.75^2*6 - pi*11^2*6
# = 29548.98 mm^3. The envelope and the gauge already pin the extents and the
# hole pattern, so what this window really rejects is unrequested stock moved
# elsewhere - the smallest deviation it must catch is a pocket or boss of about
# 20 x 20 x 2 (800 mm^3), and the window sits a factor ~2.3 below that while
# staying ~4x above the cosmetic variation a correct plate may carry (a 0.5 mm
# edge break around both faces is ~75 mm^3).
_VOLUME_MM3 = 29548.98
_VOLUME_WINDOW = 350.0

CHECKS = {
    "envelope": lambda m: m.bbox("plate/part") <= _ENV_MAX and m.bbox("plate/part") >= _ENV_MIN,
    "material_budget": lambda m: m.volume("plate/part")
    == approx(_VOLUME_MM3, abs=_VOLUME_WINDOW),
    "gauge_pins_pass": lambda m: m.interference("plate/part", "hole_gauge/part")
    == approx(0.0, abs=1e-6),
    "hole_pattern_clearance": lambda m: m.clearance("plate/part", "hole_gauge/part")
    == approx(0.05, abs=0.02),
    "sealed": lambda m: m.sealed("plate/part") and m.genus("plate/part") == 5,
}
