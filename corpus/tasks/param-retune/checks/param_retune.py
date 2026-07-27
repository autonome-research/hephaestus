# param-retune acceptance checks (project scope: whole-part measurements only).
#
# The retuned shelf must hit the NEW envelope (420 x 260 tread, gusset reaching
# 190 out and dropping 220) while every invariant of the original design still
# holds: the R25 front corners (pinned by the tread's exact volume), the
# triangular gusset profile (pinned by its volume), sealed single solids, the
# gusset carrying the tread, and both parts flush against the wall face. Editing
# geometry to hit the envelope therefore cannot pass by itself — the shape facts
# are measured too, and the part scripts are restored before grading.
#
# The windows track ``cat-step``'s (re-authored 2026-07-26, corpus audit) and are
# budgets rather than identities, even though this task has the least legitimate
# variation in the corpus: every geometry script is a protected path, so the only
# lever is ``set_params`` and there is nothing for a run to model differently.
# They are stated the same way anyway, so a future edit to either task cannot
# leave one of them demanding an identity.
_TREAD_VOLUME = 1960771.46
_TREAD_WINDOW = 600.0
_GUSSET_VOLUME = 376200.0
_GUSSET_WINDOW = 1500.0

CHECKS = {
    "tread_new_envelope": lambda m: m.bbox("shelf/part") == approx((420.0, 260.0, 18.0), abs=0.05),
    "gusset_new_envelope": lambda m: m.bbox("gusset/part")
    == approx((18.0, 190.0, 220.0), abs=0.05),
    "tread_material_pins_r25_corners": lambda m: m.volume("shelf/part")
    == approx(_TREAD_VOLUME, abs=_TREAD_WINDOW),
    "gusset_material_pins_triangular_profile": lambda m: m.volume("gusset/part")
    == approx(_GUSSET_VOLUME, abs=_GUSSET_WINDOW),
    "tread_sealed": lambda m: m.sealed("shelf/part") and m.genus("shelf/part") == 0,
    "gusset_sealed": lambda m: m.sealed("gusset/part") and m.genus("gusset/part") == 0,
    "gusset_carries_tread": lambda m: m.interference("shelf/part", "gusset/part")
    == approx(0.0, abs=1e-6)
    and m.clearance("shelf/part", "gusset/part") == approx(0.0, abs=1e-6),
    "tread_against_wall": lambda m: m.interference("shelf/part", "wall_plane/part")
    == approx(0.0, abs=1e-6)
    and m.clearance("shelf/part", "wall_plane/part") == approx(0.0, abs=1e-6),
    "gusset_against_wall": lambda m: m.interference("gusset/part", "wall_plane/part")
    == approx(0.0, abs=1e-6)
    and m.clearance("gusset/part", "wall_plane/part") == approx(0.0, abs=1e-6),
}
