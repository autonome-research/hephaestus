# bracket-101 acceptance checks (project scope: whole-part measurements only —
# a reloaded build artifact resolves the "<part>/part" selector, so feature-level
# facts are measured by fitting the task's own inspection gauge).
#
# - envelope: the bracket's overall extents;
# - material: the exact volume of the intended solid (60x40x6 plate + 60x6x34
#   wall + R4 inner fillet - two 6 mm through-holes), which pins the fillet and
#   the hole diameters together;
# - hole pattern: the 5.9 mm go-pins on the specified centres must pass through
#   with a 0.05 mm radial gap and never bite into the bracket;
# - topology: one sealed solid with two tunnels (genus 2).
_ENV_MAX = (60.05, 40.05, 40.05)
_ENV_MIN = (59.95, 39.95, 39.95)
_VOLUME_MM3 = 26506.73

CHECKS = {
    "envelope": lambda m: m.bbox("bracket/part") <= _ENV_MAX
    and m.bbox("bracket/part") >= _ENV_MIN,
    "material_volume": lambda m: m.volume("bracket/part") == approx(_VOLUME_MM3, abs=60.0),
    "gauge_pins_pass": lambda m: m.interference("bracket/part", "hole_gauge/part")
    == approx(0.0, abs=1e-6),
    "hole_pattern_clearance": lambda m: m.clearance("bracket/part", "hole_gauge/part")
    == approx(0.05, abs=0.02),
    "sealed": lambda m: m.sealed("bracket/part") and m.genus("bracket/part") == 2,
}
