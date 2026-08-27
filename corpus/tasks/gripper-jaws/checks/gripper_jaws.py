# gripper-jaws acceptance checks (project scope: whole-part measurements only).
#
# The gripper's *mechanism* — jaw travel, the open and closed gripping gaps,
# no interference anywhere along the stroke — is NOT measured here: it is the
# task's declared joint, named poses, pose-bound constraints and motion check
# (KINEMATICS.md §6), graded through the engine motion path against the run's
# built geometry. What CHECKS owns is the single-part facts:
#
# - envelope: the body's overall extents (60 x 30 base plus the fixed jaw
#   rising to z = 30) and the sliding jaw's block (10 x 30 x 20);
# - the sliding pair really is a pair: as built the jaw rides the base top
#   touching but never overlapping;
# - topology: each part is one sealed genus-0 solid.
_BODY_ENV = (60.0, 30.0, 30.0)
_JAW_ENV = (10.0, 30.0, 20.0)

CHECKS = {
    "envelope_body": lambda m: m.bbox("body/part") == approx(_BODY_ENV, abs=0.05),
    "envelope_jaw": lambda m: m.bbox("jaw/part") == approx(_JAW_ENV, abs=0.05),
    "jaw_rides_the_base_without_overlap": lambda m: m.interference("jaw/part", "body/part")
    == approx(0.0, abs=1e-6),
    "sealed_body": lambda m: m.sealed("body/part") and m.genus("body/part") == 0,
    "sealed_jaw": lambda m: m.sealed("jaw/part") and m.genus("jaw/part") == 0,
}
