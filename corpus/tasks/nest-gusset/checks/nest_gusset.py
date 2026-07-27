# nest-gusset acceptance checks (project scope: whole-part measurements only, so
# the three laminations are pinned by the material they take together and the
# nested cut file is what proves they are three separate profiles that fit).
#
# - one sheet thick: every lamination lies flat in the same 6 mm sheet, so the
#   part's Z extent is exactly the stock thickness;
# - material: exact volume. Triangular web (100 x 60 legs) = 18000 mm^3, spacer
#   60 x 40 = 14400, cleat 90 x 25 = 13500. A rectangular web instead of a
#   triangular one (36000) is 18 mm^3 x 1000 outside the window;
# - topology: three plain sealed laminations, no holes (genus 0).
#
# The rest of the acceptance test is the nested DXF export the grader performs:
# three profiles on the CUT layer, a 210 x 125 blank drawn from the part's
# own declared blank size, and every profile inside it.
_WEB_VOLUME = 0.5 * 100.0 * 60.0 * 6.0
_SPACER_VOLUME = 60.0 * 40.0 * 6.0
_CLEAT_VOLUME = 90.0 * 25.0 * 6.0
_VOLUME_MM3 = _WEB_VOLUME + _SPACER_VOLUME + _CLEAT_VOLUME
# The window was +/-30 mm^3 and is +/-150 (re-authored 2026-07-26, corpus audit):
# what it must reject is a rectangular web instead of a triangular one, 18000 mm^3
# away, so 150 leaves two orders of magnitude of margin and stops the check
# demanding the author's arithmetic back to four significant figures.
_VOLUME_WINDOW = 150.0

CHECKS = {
    "one_sheet_thick": lambda m: m.bbox("gusset/part")[2] == approx(6.0, abs=0.02),
    "material": lambda m: m.volume("gusset/part") == approx(_VOLUME_MM3, abs=_VOLUME_WINDOW),
    "plain_sealed_laminations": lambda m: m.sealed("gusset/part")
    and m.genus("gusset/part") == 0,
}
