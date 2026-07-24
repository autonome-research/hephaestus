# No-op refactor of base.py: a helper function, renamed bindings, and a
# list literal instead of an append loop. Geometry is numerically identical,
# so every tag descriptor is identical and no drift warning may be emitted.
_deck_w = 60.0
_deck_d = 40.0
_deck_t = 6.0
_fin_w = 0.4
_fin_h = 4.0
_fin_x = 0.4


def _make_fin(x):
    fin = Pos(x, 0, _deck_t + _fin_h / 2.0) * Box(_fin_w, _deck_d, _fin_h)
    fin.label = "rib"
    return fin


deck = Pos(0, 0, _deck_t / 2.0) * Box(_deck_w, _deck_d, _deck_t)
deck.label = "tread"
fins = [_make_fin(-_fin_x), _make_fin(_fin_x)]
tag(deck.faces().sort_by(Axis.Z)[-1], "tread_top")
tag(fins[0].faces().sort_by(Axis.Z)[-1], "rib_crest")
part.geometry = Compound(children=[deck, *fins])
part.description = "Fingerprint fixture: tread plate with twin ridges"
part.process = "cnc_router"
part.feature("tread_top").surface_finish = "as-milled"
part.feature("rib_crest").surface_finish = "as-milled"
