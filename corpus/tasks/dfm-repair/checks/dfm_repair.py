# dfm-repair acceptance checks (project scope: whole-part measurements).
#
# The DFM verdict itself is not asserted here — the grader re-runs the laser_cut
# pack against the built artifact on a sandboxed backend and requires the
# minimum-feature and internal-radius rules to find nothing. These checks are the
# other half: the repair must fix the two feature SIZES without redesigning the
# panel around the rules.
#
# - envelope: the 80 x 50 blank, one sheet thick, is unchanged;
# - topology: still one sealed panel with exactly one through bore (genus 1) — a
#   panel that answered the DFM findings by deleting the vent fails here;
# - material: exact volume. An 80 x 50 x 6 blank is 24000 mm^3; the 16 x 10 notch
#   removes 960; two concave R3 corners add r^2 (1 - pi/4) t = 11.59 each; the
#   6 mm bore removes pi r^2 t = 169.65. A 0.5 mm bore (23039.05), a bore at any
#   other diameter (5 mm: 22945.4) and any other corner radius (R2: 22880.6) all
#   land outside the window, so both repaired sizes are measured, not assumed.
_ENVELOPE = (80.0, 50.0, 6.0)
_VOLUME_MM3 = 22893.53

CHECKS = {
    "builds_sealed_with_one_bore": lambda m: m.sealed("vent_panel/part")
    and m.genus("vent_panel/part") == 1,
    "blank_envelope_unchanged": lambda m: m.bbox("vent_panel/part")
    == approx(_ENVELOPE, abs=0.05),
    "vent_and_corners_at_size": lambda m: m.volume("vent_panel/part")
    == approx(_VOLUME_MM3, abs=1.0),
}
