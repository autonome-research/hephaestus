# drawing-shelf acceptance checks (project scope: whole-part measurements).
#
# The drawing half is graded separately: the grader generates the dimensioned
# sheet from this geometry and requires the five principal dimensions — the
# drawing's engineering purpose — in the PDF's text layer, while the material and
# process are gated structurally through the task's metadata_requirements rather
# than as title-block prose. These checks are the geometry the sheet is a drawing
# OF — if the model is wrong the sheet is wrong, whatever it prints.
#
# - envelope: 600 wide, 250 deep, 218 tall (deck plus 200 mm of side panel);
# - material: a budget. Deck 600 x 250 x 18 = 2700000 mm^3 less the 8 mm
#   cable bore (pi r^2 t = 904.78), plus two 18 x 250 x 200 side panels
#   (900000 each). A missing bore, a bore at another diameter or a side panel of
#   another height all land outside the window;
# - the deck is one sheet thick where it matters: the thinnest wall in the
#   assembly is the panel stock;
# - mounting: the shelf sits against the seeded wall plane with zero
#   interference and zero clearance — touching it, never buried in it.
_ENVELOPE = (600.0, 250.0, 218.0)
_DECK_VOLUME = 600.0 * 250.0 * 18.0 - 904.78
_SIDE_VOLUME = 18.0 * 250.0 * 200.0
_VOLUME_MM3 = _DECK_VOLUME + 2.0 * _SIDE_VOLUME
# Material budget, not an identity (re-authored 2026-07-26, corpus audit). The
# window was +/-50 mm^3 on 4.5 million - one part in 90,000, which an unrequested
# 0.5 mm edge break on a single 600 mm edge (75 mm^3) already breaks. It is now
# +/-350: the smallest spec deviation it has to reject is a missing cable bore
# (905 mm^3), so the window sits 2.6x below that and no longer grades sanding.
_VOLUME_WINDOW = 350.0

CHECKS = {
    "shelf_envelope": lambda m: m.bbox("shelf/part") == approx(_ENVELOPE, abs=0.05),
    "shelf_material_budget": lambda m: m.volume("shelf/part")
    == approx(_VOLUME_MM3, abs=_VOLUME_WINDOW),
    "flush_against_the_wall": lambda m: m.interference("shelf/part", "rail/part")
    == approx(0.0, abs=1e-6),
    "touching_the_wall": lambda m: m.clearance("shelf/part", "rail/part")
    == approx(0.0, abs=1e-6),
}
