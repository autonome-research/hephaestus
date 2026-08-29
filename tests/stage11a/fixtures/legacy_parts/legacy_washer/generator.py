# Flat washer — a plain annulus, DIN 125 nominal envelope.
#
# Coordinate convention: the ORIGIN sits on the lower face; the washer runs
# 0 .. +thickness in Z.
#
# FROZEN FIXTURE (tests/stage11a). No interface region, no `component` block:
# a legacy store part, kept unedited so clause 1 has evidence that is not the
# shipped six.

# --- hephaestus-store: params ---
PARAMS = {
    "thickness": Param(0.8, min=0.4, max=4.0, doc="washer thickness, mm"),
}
# --- hephaestus-store: bind ---
_thickness = p.thickness
# --- hephaestus-store: body ---
_outer_d = 9.0
_bore_d = 3.2
_disc = Cylinder(_outer_d / 2, _thickness, align=(Align.CENTER, Align.CENTER, Align.MIN))
_hole = Cylinder(_bore_d / 2, _thickness + 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_washer = _disc - _hole
_washer.label = "legacy_washer"
part.geometry = _washer
