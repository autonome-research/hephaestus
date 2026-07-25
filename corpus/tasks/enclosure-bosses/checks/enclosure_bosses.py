# enclosure-bosses acceptance checks (project scope: whole-part measurements
# only — a reloaded build artifact resolves the "<part>/part" selector, so the
# internal features are measured by fitting the task's own gauges).
#
# - min wall: the seeded 1.6 mm shell gauge must be entirely inside the box's
#   material. The overlap volume equals the shell's own volume exactly when no
#   wall, floor or corner is thinner than the process minimum;
# - bosses: the four go-pins must enter the pilot holes with a 0.05 mm radial gap
#   and no interference — that measures the boss pattern, the boss height and the
#   bore depth at once;
# - lid: zero interference with the box while seating on its rim (contact), and a
#   lid volume that pins the 0.2 mm-per-side register clearance (a lip cut to the
#   nominal cavity is 105 mm^3 more material);
# - material: the box's volume pins the cavity, the four Ø8 bosses and their
#   bores;
# - topology + envelopes: one sealed box (genus 0), a lid with four through holes
#   (genus 4).
_SHELL_VOLUME = 20112.384
_ENCLOSURE_VOLUME = 30800.4
_LID_VOLUME = 22625.26

CHECKS = {
    "box_envelope": lambda m: m.bbox("enclosure/part") == approx((80.0, 60.0, 30.0), abs=0.05),
    "lid_envelope": lambda m: m.bbox("lid/part") == approx((80.0, 60.0, 5.0), abs=0.05),
    "min_wall_1p6": lambda m: m.interference("enclosure/part", "wall_gauge/part")
    == approx(_SHELL_VOLUME, abs=5.0),
    "box_material": lambda m: m.volume("enclosure/part") == approx(_ENCLOSURE_VOLUME, abs=60.0),
    "boss_pins_enter": lambda m: m.interference("enclosure/part", "boss_gauge/part")
    == approx(0.0, abs=1e-6),
    "boss_pattern_clearance": lambda m: m.clearance("enclosure/part", "boss_gauge/part")
    == approx(0.05, abs=0.02),
    "lid_no_interference": lambda m: m.interference("lid/part", "enclosure/part")
    == approx(0.0, abs=1e-6),
    "lid_seats_on_rim": lambda m: m.clearance("lid/part", "enclosure/part")
    == approx(0.0, abs=1e-6),
    "lid_register_clearance": lambda m: m.volume("lid/part") == approx(_LID_VOLUME, abs=20.0),
    "box_sealed": lambda m: m.sealed("enclosure/part") and m.genus("enclosure/part") == 0,
    "lid_sealed": lambda m: m.sealed("lid/part") and m.genus("lid/part") == 4,
}
