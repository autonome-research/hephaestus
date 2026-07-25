# store-hardware acceptance checks (project scope: whole-part measurements only).
#
# - the bracket keeps its bracket-101 envelope and topology (two through holes);
# - its exact volume pins BOTH re-cut features at once: a 5.5 mm clearance hole
#   through the plate and a 10 mm counterbore 5 mm deep (leaving the holes alone
#   is 548 mm^3 of extra material, counterboring without opening the holes out is
#   285 mm^3 — both far outside the window);
# - the screw instances are present with the store envelope's exact material
#   volume (head + shank - hex socket, twice) and its overall extents;
# - the hardware seats: zero interference with the bracket, and contact (the head
#   bearing face on the counterbore floor);
# - the heads are below the mounting surface: the seeded clearance gauge stands
#   on the plate's top face over both holes, and nothing may reach into it.
_BRACKET_VOLUME = 26013.12
_SCREWS_VOLUME = 1112.64

CHECKS = {
    "bracket_envelope": lambda m: m.bbox("bracket/part") == approx((60.0, 40.0, 40.0), abs=0.05),
    "bracket_counterbored": lambda m: m.volume("bracket/part")
    == approx(_BRACKET_VOLUME, abs=40.0),
    "bracket_sealed": lambda m: m.sealed("bracket/part") and m.genus("bracket/part") == 2,
    "screw_instances_present": lambda m: m.volume("screws/part")
    == approx(_SCREWS_VOLUME, abs=15.0),
    "screw_envelope": lambda m: m.bbox("screws/part") == approx((44.5, 8.5, 21.0), abs=0.1),
    "screws_do_not_interfere": lambda m: m.interference("bracket/part", "screws/part")
    == approx(0.0, abs=1e-6),
    "screws_seated_on_counterbore": lambda m: m.clearance("bracket/part", "screws/part")
    == approx(0.0, abs=1e-6),
    "heads_below_surface": lambda m: m.interference("screws/part", "head_gauge/part")
    == approx(0.0, abs=1e-6),
}
