# Reference solution for bench task nest-gusset.
#
# Three flat laminations of one sheet thickness, each a separate solid so the
# nested cut file sees three profiles. `part.blank_size` is the declaration the
# nested export nests onto — without it there is no blank to nest on.
_t = hc.sheet_t

_web = extrude(
    make_face(Polyline((0.0, 0.0), (hc.web_leg_x, 0.0), (0.0, hc.web_leg_y), close=True)),
    amount=_t,
)
_web.label = "web"

_spacer = Pos(150.0, 0.0, 0.0) * Box(
    hc.spacer_len, hc.spacer_width, _t, align=(Align.MIN, Align.MIN, Align.MIN)
)
_spacer.label = "spacer"

_cleat = Pos(0.0, 100.0, 0.0) * Box(
    hc.cleat_len, hc.cleat_width, _t, align=(Align.MIN, Align.MIN, Align.MIN)
)
_cleat.label = "cleat"

part.geometry = Compound(children=[_web, _spacer, _cleat])

part.description = "Shelf gusset laminations: triangular web, spacer and cleat"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
part.blank_size = "210 x 125 mm blank, one set per blank"
