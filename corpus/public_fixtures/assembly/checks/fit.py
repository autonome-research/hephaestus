# Cross-part fit checks (script contract §6, cross-part form): the corner
# bracket must seat exactly one joint_clear (0.3 mm at defaults) off the
# frame's +X face and must never intersect the frame.
CHECKS = {
    "bracket_clears_frame": lambda m: m.interference("primary/part", "bracket/part")
    == approx(0.0, abs=1e-6),
    "bracket_seats_at_joint_clearance": lambda m: m.clearance(
        "primary/part", "bracket/part"
    )
    == approx(0.3, abs=0.01),
}
