# print-bracket acceptance checks (project scope: whole-part measurements).
#
# The printability verdict is graded separately: the grader re-runs the fdm rule
# pack against the built artifact on a sandboxed backend and requires the wall,
# bore and overhang rules to find nothing. These checks pin the geometry those
# rules are being run against.
#
# - envelope: 30 wide, 30 of reach, 40 tall;
# - topology: one sealed solid with exactly one through bore (genus 1) — a
#   bracket that answered the overhang rule by splitting into two pieces, or that
#   deleted the bore, fails here;
# - material: exact volume. The upright is 30 x 6 x 40 = 7200 mm^3; the arm is
#   the 24 x 36 mm section over the remaining reach less the ramp triangle
#   (0.5 x 24 x 30), i.e. (864 - 360) x 30 = 15120; the 4 mm bore removes
#   pi r^2 h over the 9.75 mm of material above the ramp at its centre = 122.52.
#   A flat-bottomed arm (33120 mm^3) or a ramp at another angle lands far outside
#   the window, so the ramp is measured and not assumed.
_ENVELOPE = (30.0, 30.0, 40.0)
_UPRIGHT = 30.0 * 6.0 * 40.0
_ARM = (24.0 * 36.0 - 0.5 * 24.0 * 30.0) * 30.0
_BORE = 3.14159265 * 4.0 * 9.75
_VOLUME_MM3 = _UPRIGHT + _ARM - _BORE

CHECKS = {
    "one_solid_one_bore": lambda m: m.sealed("bracket/part") and m.genus("bracket/part") == 1,
    "bracket_envelope": lambda m: m.bbox("bracket/part") == approx(_ENVELOPE, abs=0.05),
    "ramped_arm_material": lambda m: m.volume("bracket/part")
    == approx(_VOLUME_MM3, abs=20.0),
}
