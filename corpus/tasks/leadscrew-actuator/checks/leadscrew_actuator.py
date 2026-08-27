# leadscrew-actuator acceptance checks (project scope: whole-part facts only).
#
# The actuator's *mechanism* — the screw-to-carriage transmission, the travel
# window, the reach to the top-of-stroke handoff point, non-interference over
# the stroke — is NOT measured here: it is the task's declared kinematics
# (KINEMATICS.md §5/§6), graded through the engine motion path against the
# run's built geometry and its own declared coupling. What CHECKS owns is the
# single-part facts at the as-built zero configuration:
#
# - envelope: each part's overall extents (frame 60 x 60 x 8; screw Ø9.8 x 30;
#   carriage 12 x 12 x 6);
# - the screw really rides IN the bore: zero interference with the frame and
#   the 0.1 mm radial air of a Ø9.8 pilot in a Ø10 bore;
# - the carriage floats on its declared 0.5 mm gap above the plate top and
#   never touches the screw;
# - topology: the frame is one sealed solid whose bore runs through (genus 1);
#   screw and carriage are sealed genus-0 solids.
_FRAME_ENV = (60.0, 60.0, 8.0)
_SCREW_ENV = (9.8, 9.8, 30.0)
_CARRIAGE_ENV = (12.0, 12.0, 6.0)

CHECKS = {
    "envelope_frame": lambda m: m.bbox("frame/part") == approx(_FRAME_ENV, abs=0.05),
    "envelope_screw": lambda m: m.bbox("screw/part") == approx(_SCREW_ENV, abs=0.05),
    "envelope_carriage": lambda m: m.bbox("carriage/part") == approx(_CARRIAGE_ENV, abs=0.05),
    "screw_rides_free": lambda m: m.interference("screw/part", "frame/part")
    == approx(0.0, abs=1e-6),
    "screw_pilot_air": lambda m: m.clearance("screw/part", "frame/part")
    == approx(0.1, abs=0.02),
    "carriage_floats_on_gap": lambda m: m.interference("carriage/part", "frame/part")
    == approx(0.0, abs=1e-6)
    and m.clearance("carriage/part", "frame/part") == approx(0.5, abs=0.02),
    "carriage_clears_screw": lambda m: m.interference("carriage/part", "screw/part")
    == approx(0.0, abs=1e-6),
    "sealed_frame": lambda m: m.sealed("frame/part") and m.genus("frame/part") == 1,
    "sealed_screw": lambda m: m.sealed("screw/part") and m.genus("screw/part") == 0,
    "sealed_carriage": lambda m: m.sealed("carriage/part") and m.genus("carriage/part") == 0,
}
