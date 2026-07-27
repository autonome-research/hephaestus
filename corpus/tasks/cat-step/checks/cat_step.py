# cat-step acceptance checks (project scope: whole-part measurements only — a
# reloaded build artifact resolves the "<part>/part" selector, so the design's
# invariants are measured between parts and against the seeded wall gauge).
#
# - envelopes: tread 300 x 200 x 18, gusset 18 wide reaching 140 out and 160 down;
# - material: budgets, not identities. Both envelopes are already pinned to
#   0.05 mm, so each volume window measures exactly one thing — the tread's, the
#   front-corner treatment; the gusset's, the profile;
# - fit: the gusset carries the tread (contact, no overlap) and both parts sit
#   flush against the wall face without cutting into it;
# - topology: both parts are single sealed solids.

# Tread material budget (re-authored 2026-07-26, corpus audit). +/-600 mm^3 is
# 0.06% of the tread and sits ~3x below the smallest corner error it must reject
# (R20 instead of R25 leaves 1739 mm^3 more material; square corners, 4829), while
# admitting the eased edges a ply tread legitimately carries.
_TREAD_VOLUME = 1075171.46
_TREAD_WINDOW = 600.0

# Gusset material budget. The envelope pins both legs, so this window only has to
# separate a triangular web from a rectangular one — a 201600 mm^3 difference —
# and +/-1500 mm^3 (0.7%) leaves two orders of magnitude of margin while letting
# a correct gusset carry a relieved corner or a broken edge.
_GUSSET_VOLUME = 201600.0
_GUSSET_WINDOW = 1500.0

CHECKS = {
    "tread_envelope": lambda m: m.bbox("shelf/part") == approx((300.0, 200.0, 18.0), abs=0.05),
    "tread_material_pins_r25_corners": lambda m: m.volume("shelf/part")
    == approx(_TREAD_VOLUME, abs=_TREAD_WINDOW),
    "tread_sealed": lambda m: m.sealed("shelf/part") and m.genus("shelf/part") == 0,
    "gusset_envelope": lambda m: m.bbox("gusset/part") == approx((18.0, 140.0, 160.0), abs=0.05),
    "gusset_material_pins_triangular_profile": lambda m: m.volume("gusset/part")
    == approx(_GUSSET_VOLUME, abs=_GUSSET_WINDOW),
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
