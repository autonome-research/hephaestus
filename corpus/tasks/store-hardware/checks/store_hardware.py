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
#
# Both windows are budgets, re-authored 2026-07-26 (corpus audit) from +/-40 and
# +/-15. Each is set ~3x below the smallest re-detailing error it must reject:
# counterboring without opening the holes out is 285 mm^3 (bracket), and omitting
# the hex socket is 83 mm^3 over the two screws. The wider screw window also stops
# the check caring whether the socket is modelled hexagonal or as its inscribed
# circle (8 mm^3 over two screws) — a modelling choice, not an engineering one.
_BRACKET_VOLUME = 26013.12
_BRACKET_WINDOW = 100.0
_SCREWS_VOLUME = 1112.64
_SCREWS_WINDOW = 30.0

CHECKS = {
    "bracket_envelope": lambda m: m.bbox("bracket/part") == approx((60.0, 40.0, 40.0), abs=0.05),
    "bracket_counterbored": lambda m: m.volume("bracket/part")
    == approx(_BRACKET_VOLUME, abs=_BRACKET_WINDOW),
    "bracket_sealed": lambda m: m.sealed("bracket/part") and m.genus("bracket/part") == 2,
    "screw_instances_present": lambda m: m.volume("screws/part")
    == approx(_SCREWS_VOLUME, abs=_SCREWS_WINDOW),
    "screw_envelope": lambda m: m.bbox("screws/part") == approx((44.5, 8.5, 21.0), abs=0.1),
    "screws_do_not_interfere": lambda m: m.interference("bracket/part", "screws/part")
    == approx(0.0, abs=1e-6),
    "screws_seated_on_counterbore": lambda m: m.clearance("bracket/part", "screws/part")
    == approx(0.0, abs=1e-6),
    "heads_below_surface": lambda m: m.interference("screws/part", "head_gauge/part")
    == approx(0.0, abs=1e-6),
}
