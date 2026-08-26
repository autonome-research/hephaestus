# flange-edit acceptance checks (project scope). The edit is measured against
# the seeded vendor file itself: m.diff("flange/part", "import:flange.step")
# compares the run's geometry with the import (COMPARE.md §2), as_posed, so a
# moved flange is a changed flange. The diff proves the edit happened AND that
# nothing else changed; the seeded go-pin gauge measures the new bore as a fit.
#
# - removal: material removed relative to the vendor solid equals the Ø25->Ø30
#   bore annulus;
# - nothing added: a pure removal edit leaves a_only at zero;
# - pose/topology: same bbox in the vendor's pose, same genus, still sealed;
# - new bore: the Ø29.9 go-pin passes with a 0.05 mm radial gap and no bite.

# The Ø25 -> Ø30 bore enlargement: pi * (15.0^2 - 12.5^2) * 8.0 = 1727.88 mm^3.
_BORE_GROWTH_MM3 = 1727.88
# Removal BUDGET, not an identity: the smallest wrong removal it must reject is
# an edit that also takes material somewhere else - opening one Ø9 bolt hole to
# Ø11 removes a further 251 mm^3 - so the window sits a factor of ~2 below that
# and two orders above kernel boolean noise (~1 mm^3 on this flange).
_BORE_GROWTH_WINDOW = 120.0
# A removal-only edit adds nothing; 1 mm^3 absorbs boolean noise only.
_ADDED_MAX_MM3 = 1.0
# The vendor envelope (Ø80 disc, 8 mm thick), which the edit may not move.
_ENVELOPE = (80.0, 80.0, 8.0)

CHECKS = {
    "bore_enlarged_by_the_specified_annulus": lambda m: m.diff(
        "flange/part", "import:flange.step"
    ).b_only_mm3
    == approx(_BORE_GROWTH_MM3, abs=_BORE_GROWTH_WINDOW),
    "no_material_added": lambda m: m.diff("flange/part", "import:flange.step").a_only_mm3
    <= _ADDED_MAX_MM3,
    "vendor_pose_and_topology_preserved": lambda m: (
        lambda d: d.genus_delta == 0
        and not d.sealed_changed
        and d.a_bbox_mm == approx(_ENVELOPE, abs=0.05)
    )(m.diff("flange/part", "import:flange.step")),
    "go_pin_passes_the_new_bore": lambda m: m.interference("flange/part", "bore_gauge/part")
    == approx(0.0, abs=1e-6),
    "go_pin_clearance": lambda m: m.clearance("flange/part", "bore_gauge/part")
    == approx(0.05, abs=0.02),
    "sealed": lambda m: m.sealed("flange/part") and m.genus("flange/part") == 5,
}
