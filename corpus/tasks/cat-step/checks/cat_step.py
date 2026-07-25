# cat-step acceptance checks (project scope: whole-part measurements only — a
# reloaded build artifact resolves the "<part>/part" selector, so the design's
# invariants are measured between parts and against the seeded wall gauge).
#
# - envelopes: tread 300 x 200 x 18, gusset 18 wide reaching 140 out and 160 down;
# - material: the tread's exact volume pins the R25 front corners (square corners
#   leave 4829 mm^3 more material, R20 leaves 1739 mm^3 more), the gusset's pins
#   the triangular profile (a rectangular bracket would be twice the volume);
# - fit: the gusset carries the tread (contact, no overlap) and both parts sit
#   flush against the wall face without cutting into it;
# - topology: both parts are single sealed solids.
_TREAD_VOLUME = 1075171.46
_GUSSET_VOLUME = 201600.0

CHECKS = {
    "tread_envelope": lambda m: m.bbox("shelf/part") == approx((300.0, 200.0, 18.0), abs=0.05),
    "tread_corner_radius": lambda m: m.volume("shelf/part") == approx(_TREAD_VOLUME, abs=400.0),
    "tread_sealed": lambda m: m.sealed("shelf/part") and m.genus("shelf/part") == 0,
    "gusset_envelope": lambda m: m.bbox("gusset/part") == approx((18.0, 140.0, 160.0), abs=0.05),
    "gusset_is_triangular": lambda m: m.volume("gusset/part")
    == approx(_GUSSET_VOLUME, abs=600.0),
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
