# Round standoff spacer — a plain bored cylinder, thread-free.
#
# Coordinate convention: the ORIGIN sits on the lower face; the body runs
# 0 .. +length in Z.
#
# FROZEN FIXTURE (tests/stage11a). This generator declares no interface region
# and its part.json carries no `component` block, which is exactly what it is
# for: it is the "legacy store part" G11A clause 1 pins byte-for-byte.

# --- hephaestus-store: params ---
PARAMS = {
    "length": Param(10.0, min=2.0, max=40.0, doc="spacer length, mm"),
}
# --- hephaestus-store: bind ---
_length = p.length
# --- hephaestus-store: body ---
_outer_d = 6.0
_bore_d = 3.2
_body = Cylinder(_outer_d / 2, _length, align=(Align.CENTER, Align.CENTER, Align.MIN))
_bore = Cylinder(_bore_d / 2, _length + 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_spacer = _body - _bore
_spacer.label = "legacy_spacer"
part.geometry = _spacer
