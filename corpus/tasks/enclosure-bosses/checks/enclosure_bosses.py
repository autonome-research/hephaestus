# enclosure-bosses acceptance checks (project scope: whole-part measurements
# only — a reloaded build artifact resolves the "<part>/part" selector, so the
# internal features are measured by fitting the task's own gauges).
#
# Everything here is a FIT or a TOPOLOGY fact, measured against seeded gauges.
# No check pins a part's volume to the reference solution's own value: the one
# volume window left is a material budget wide enough for legitimate design
# variation, and it is named as one.
#
# - min wall: the seeded 1.6 mm shell gauge must be entirely inside the box's
#   material. The overlap volume equals the shell's own volume when no wall,
#   floor or corner is thinner than the process minimum;
# - bosses: the four go-pins must enter the pilot holes with a 0.05 mm radial gap
#   and no interference — that measures the boss pattern, the boss height and the
#   bore depth at once;
# - lid: zero interference with the box while seating on its rim (contact); the
#   register clearance measured per side against the cavity-opening gauge; and
#   the lid go-gauge (full-thickness cover slab + register engagement band)
#   contained completely, which says the lid closes the box and its lip really
#   registers in the opening — whatever shape that lip is;
# - material: a box material budget, not an identity;
# - topology + envelopes: one sealed box (genus 0), a lid with four through holes
#   (genus 4).

# Minimum-wall containment. The window is 40 mm^3 (0.2% of the shell) so that an
# edge break or elephant-foot chamfer around the base is still a pass, while the
# thing it must catch is enormous beside it: opening the cavity out by 0.2 mm on
# one side eats 330 mm^3 of the shell, and 0.2 mm off the floor eats 851.
_SHELL_VOLUME = 20112.384

# Box material budget. The intended solid (80 x 60 x 30 outer, 2 mm walls, 2.5 mm
# floor, four Ø8 bosses to z = 24 bored 3.2 x 15) is 30800.4 mm^3. The window is
# ±200 mm^3 (0.65%): wide enough for the fillets and chamfers an FDM part
# legitimately carries at the boss roots and around the base (a 1.5 mm boss-root
# fillet is ~50 mm^3), and still far tighter than what it has to catch — a
# missing boss set is 3838 mm^3 and an unhollowed box is 113000.
_ENCLOSURE_VOLUME = 30800.4
_ENCLOSURE_WINDOW = 200.0

# The lid go-gauge's own volume: a 79 x 59 x 2.8 cover slab less four Ø5.2 bores,
# plus a (75 x 55) − (73 x 53) register band 1.2 mm deep. The check is
# containment of that gauge, so it measures what the lid must DO — close the box
# at full thickness and register in the opening all the way round — and stays
# silent about how the lip is modelled (solid block, peripheral rib, stepped).
_PI = 3.141592653589793
_COVER_SLAB = 79.0 * 59.0 * 2.8 - 4.0 * _PI * 2.6 * 2.6 * 2.8
_REGISTER_BAND = (75.0 * 55.0 - 73.0 * 53.0) * 1.2
_LID_GO_VOLUME = _COVER_SLAB + _REGISTER_BAND

# Declared register fit: the lip is inset 0.2 mm from the cavity wall on every
# side. The window is 0.05–0.35 mm per side: under 0.05 the lid is a press fit on
# an FDM box (the task says it must drop in), over 0.35 the register stops
# locating the lid. 0.2 sits in the middle, and a lip modelled anywhere in that
# band is a correct lid rather than a copy of this one.
_REGISTER_CLEARANCE = 0.2

CHECKS = {
    "box_envelope": lambda m: m.bbox("enclosure/part") == approx((80.0, 60.0, 30.0), abs=0.05),
    "lid_envelope": lambda m: m.bbox("lid/part") == approx((80.0, 60.0, 5.0), abs=0.05),
    "min_wall_1p6": lambda m: m.interference("enclosure/part", "wall_gauge/part")
    == approx(_SHELL_VOLUME, abs=40.0),
    "box_material_budget": lambda m: m.volume("enclosure/part")
    == approx(_ENCLOSURE_VOLUME, abs=_ENCLOSURE_WINDOW),
    "boss_pins_enter": lambda m: m.interference("enclosure/part", "boss_gauge/part")
    == approx(0.0, abs=1e-6),
    "boss_pattern_clearance": lambda m: m.clearance("enclosure/part", "boss_gauge/part")
    == approx(0.05, abs=0.02),
    "lid_no_interference": lambda m: m.interference("lid/part", "enclosure/part")
    == approx(0.0, abs=1e-6),
    "lid_seats_on_rim": lambda m: m.clearance("lid/part", "enclosure/part")
    == approx(0.0, abs=1e-6),
    "lid_register_clears_the_opening": lambda m: m.clearance("lid/part", "register_gauge/part")
    == approx(_REGISTER_CLEARANCE, abs=0.15)
    and m.interference("lid/part", "register_gauge/part") == approx(0.0, abs=1e-6),
    "lid_closes_and_registers": lambda m: m.interference("lid/part", "lid_go_gauge/part")
    == approx(_LID_GO_VOLUME, abs=2.0),
    "box_sealed": lambda m: m.sealed("enclosure/part") and m.genus("enclosure/part") == 0,
    "lid_sealed": lambda m: m.sealed("lid/part") and m.genus("lid/part") == 4,
}
