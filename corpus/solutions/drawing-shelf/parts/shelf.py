# Reference solution for bench task drawing-shelf.
#
# Deck plus two side panels, all from one panel thickness, sitting against the
# seeded wall plane at y = 0. The §5.2 manufacturing metadata is part of the
# deliverable: the dimensioned sheet's title block is read from it, so the
# material spec has to be authored here or the drawing cannot state it.
_t = hc.panel_t

_deck = Pos(0.0, hc.depth / 2.0, _t / 2.0) * Box(hc.width, hc.depth, _t)
_deck = _deck - Pos(0.0, hc.depth / 2.0, _t / 2.0) * Cylinder(
    hc.cable_bore_dia / 2.0, 4.0 * _t
)
_deck.label = "deck"

_left = Pos(-hc.width / 2.0 + _t / 2.0, hc.depth / 2.0, -hc.side_height / 2.0) * Box(
    _t, hc.depth, hc.side_height
)
_left.label = "side_left"
_right = Pos(hc.width / 2.0 - _t / 2.0, hc.depth / 2.0, -hc.side_height / 2.0) * Box(
    _t, hc.depth, hc.side_height
)
_right.label = "side_right"

part.geometry = Compound(children=[_deck, _left, _right])

part.description = "Wall shelf: deck on two side panels, cable pass-through in the deck"
part.material_spec = "18 mm Baltic birch plywood"
part.process = "laser_cut"
part.stock_form = "sheet"
part.general_tolerance = "+/-0.25 mm cut profile"
part.finish = "sanded, hardwax oiled"
part.assembly_method = "glued and screwed"
