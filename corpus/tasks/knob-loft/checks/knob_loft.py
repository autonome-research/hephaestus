# knob-loft acceptance checks (project scope: whole-part measurements only).
#
# - envelope + topology: Ø40 x 30 overall, one sealed solid with no through
#   features (genus 0);
# - round in plan: the X and Y extents of a body of revolution are equal;
# - form: the grip band must contain the seeded go-plug completely (never short)
#   and stay clear of the seeded no-go sleeve (never long), which holds the grip
#   surface inside a 0.05 mm radial band at every angle — the measured form of
#   "max radial deviation of the profile under a 180 deg rotation < 0.05 mm";
# - material: the volume window pins the flange, the lofted taper and the R6
#   crown together (a straight step instead of the loft is ~700 mm^3 more, a
#   square crown ~517 mm^3 more).
_PLUG_VOLUME = 3153.4435
_KNOB_VOLUME = 21699.9

CHECKS = {
    "envelope": lambda m: m.bbox("knob/part") == approx((40.0, 40.0, 30.0), abs=0.05),
    "sealed_solid": lambda m: m.sealed("knob/part") and m.genus("knob/part") == 0,
    "round_in_plan": lambda m: m.bbox("knob/part")[0]
    == approx(m.bbox("knob/part")[1], abs=0.05),
    "grip_fills_go_plug": lambda m: m.interference("knob/part", "core_gauge/part")
    == approx(_PLUG_VOLUME, abs=1.0),
    "grip_clears_no_go_sleeve": lambda m: m.interference("knob/part", "sleeve_gauge/part")
    == approx(0.0, abs=1e-6),
    "material_volume": lambda m: m.volume("knob/part") == approx(_KNOB_VOLUME, abs=220.0),
}
