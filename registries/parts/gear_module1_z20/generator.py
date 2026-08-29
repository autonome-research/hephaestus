# Module 1, 20-tooth spur gear — ISO 53 pitch-cylinder blank, 5 mm bore.
#
# Coordinate convention: the ORIGIN sits on the back face, on the bore axis.
# The blank spans 0 .. +6 mm in Z.
#
# Deliberately simplified: the toothed rim is represented by its PITCH
# cylinder (d = m*z = 20 mm), not by tooth flanks. That is the standard
# equivalent-blank simplification, and it is the one that makes the declared
# mass reproducible: PARTS_STORE.md §5 admits a computed mass only when the
# value follows from the built envelope, and a tooth form the envelope does
# not carry is a number nothing could check. Do not use this to reason about
# contact ratio, backlash, undercut or tooth bending — none of them is here.
#
# Every number is derived from ISO 53's module-1 basic rack applied to z = 20:
# pitch d = 20.0, tip d = 22.0, root d = 17.5. Only the pitch cylinder is
# built. A public standard's nominal dimensions are what §7.1 admits; no
# vendor table was transcribed.
#
# Suggested mating features:
#   shaft            5 mm dia, with a grub screw or a press fit
#   centre distance  to a mating module-1 gear: (20 + z2) / 2 mm

# --- hephaestus-store: params ---
PARAMS = {}
# --- hephaestus-store: bind ---
# --- hephaestus-store: body ---
_module = 1.0
_teeth = 20
_pitch_d = _module * _teeth
_face_width = 6.0
_bore_d = 5.0
_blank = Cylinder(
    _pitch_d / 2, _face_width, align=(Align.CENTER, Align.CENTER, Align.MIN)
) - Cylinder(_bore_d / 2, _face_width, align=(Align.CENTER, Align.CENTER, Align.MIN))
_blank.color = Color(0.68, 0.7, 0.72)
_blank.label = "gear_module1_z20"
part.geometry = _blank

# --- hephaestus-store: interface ---
# PARTS_STORE.md §2.1: rooted at the published shape, ordered by a MEASURE.
# The blank has exactly two cylindrical faces; the bore is the smaller and the
# pitch cylinder the larger at the one size this part ships. The two end faces
# are congruent annuli and no measure separates them, so neither is declared.
tag(_blank.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "bore")
tag(_blank.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1], "pitch_cylinder")
