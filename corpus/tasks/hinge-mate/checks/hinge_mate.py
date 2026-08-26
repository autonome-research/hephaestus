# hinge-mate acceptance checks (project scope: whole-part measurements only).
#
# The hinge's *fits* — concentric pin bores, flush knuckle mate, the swing gap
# between the plates — are NOT measured here: they are the task's declared
# constraints (ASSEMBLY.md §3), graded through the engine constraint path
# against the run's built geometry. What CHECKS owns is the single-part facts:
#
# - envelope: each leaf's overall extents (plate 20 x 30 x 4 plus the Ø10
#   knuckle barrel around the axis at z = 7: 20 x 38.5 x 12);
# - the bores are real Ø6 bores: the seeded 5.9 mm go-pin passes through both
#   knuckles with a 0.05 mm radial gap and never bites into either leaf;
# - the leaves may touch at the knuckle mate but never overlap;
# - topology: each leaf is one sealed solid whose bore runs through (genus 1).
_LEAF_ENV = (20.0, 38.5, 12.0)

CHECKS = {
    "envelope_leaf_a": lambda m: m.bbox("leaf_a/part") == approx(_LEAF_ENV, abs=0.05),
    "envelope_leaf_b": lambda m: m.bbox("leaf_b/part") == approx(_LEAF_ENV, abs=0.05),
    "gauge_pin_passes_leaf_a": lambda m: m.interference("leaf_a/part", "pin_gauge/part")
    == approx(0.0, abs=1e-6),
    "gauge_pin_passes_leaf_b": lambda m: m.interference("leaf_b/part", "pin_gauge/part")
    == approx(0.0, abs=1e-6),
    "bore_clearance_leaf_a": lambda m: m.clearance("leaf_a/part", "pin_gauge/part")
    == approx(0.05, abs=0.02),
    "bore_clearance_leaf_b": lambda m: m.clearance("leaf_b/part", "pin_gauge/part")
    == approx(0.05, abs=0.02),
    "leaves_do_not_overlap": lambda m: m.interference("leaf_a/part", "leaf_b/part")
    == approx(0.0, abs=1e-6),
    "sealed_leaf_a": lambda m: m.sealed("leaf_a/part") and m.genus("leaf_a/part") == 1,
    "sealed_leaf_b": lambda m: m.sealed("leaf_b/part") and m.genus("leaf_b/part") == 1,
}
