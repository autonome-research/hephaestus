# Variant solution for drawing-shelf — deliberately NOT the reference.
#
# Same shelf, built in the opposite order (sides first, from a mirrored pair
# rather than two independent placements, deck last and bored with a Hole-style
# subtraction), and — the point of this fixture — its manufacturing metadata is
# worded differently in every field. The material is the same stock in the same
# registry; only the sentence is not the reference's.
#
# Until the 2026-07-26 corpus audit the drawing requirement matched the material
# line as a verbatim string, so this file would have failed the task while
# building a shelf identical to within a thousandth of a cubic millimetre.
_t = hc.panel_t
_half = hc.width / 2.0

sides = []
for _sx in (-1.0, 1.0):
    _side = Pos(_sx * (_half - _t / 2.0), hc.depth / 2.0, -hc.side_height / 2.0) * Box(
        _t, hc.depth, hc.side_height
    )
    _side.label = "side_left" if _sx < 0.0 else "side_right"
    sides.append(_side)

_blank = Box(hc.width, hc.depth, _t)
_bore = Cylinder(radius=hc.cable_bore_dia / 2.0, height=_t * 3.0)
deck = Pos(0.0, hc.depth / 2.0, _t / 2.0) * (_blank - _bore)
deck.label = "deck"

part.geometry = Compound(children=[*sides, deck])

part.description = "Shelf for the hallway: 600 mm deck carried on two full-depth end panels"
part.material_spec = "Baltic birch plywood, 18 mm, BB/BB grade"
part.process = "laser_cut"
part.stock_form = "sheet stock, 18 mm"
part.general_tolerance = "ISO 2768-m unless dimensioned"
part.finish = "edges sanded to 180 grit, left unfinished"
