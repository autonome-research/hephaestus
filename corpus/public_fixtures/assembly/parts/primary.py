# Open-frame shelf: two full-footprint decks tied together by four square
# corner posts. Post positions are inset from the deck edges so the frame
# can be picked up by the decks without racking.
PARAMS = {
    "post_inset": Param(15.0, min=6.0, max=30.0),
}

# Deck plates span the full shelf footprint; posts sit between them.
bottom_deck = Pos(0, 0, hc.sheet_t / 2.0) * Box(hc.shelf_w, hc.shelf_d, hc.sheet_t)
bottom_deck.label = "bottom_deck"
top_deck = Pos(0, 0, hc.sheet_t + hc.post_h + hc.sheet_t / 2.0) * Box(
    hc.shelf_w, hc.shelf_d, hc.sheet_t
)
top_deck.label = "top_deck"

# Four congruent corner posts, inset from the deck edges.
_px = hc.shelf_w / 2.0 - p.post_inset
_py = hc.shelf_d / 2.0 - p.post_inset
posts = []
for _sx, _sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
    post = Pos(_sx * _px, _sy * _py, hc.sheet_t + hc.post_h / 2.0) * Box(
        hc.post_side, hc.post_side, hc.post_h
    )
    post.label = "post"
    posts.append(post)

tag(top_deck.faces().sort_by(Axis.Z)[-1], "deck_top")
tag(bottom_deck.faces().sort_by(Axis.Z)[0], "base_bottom")

part.geometry = Compound(children=[bottom_deck, top_deck, *posts])

# Persistent checks (§6): envelope, exact deck volume, post/deck fit, topology.
_env = (hc.shelf_w + 0.5, hc.shelf_d + 0.5, hc.frame_h + 0.5)
_deck_volume = hc.shelf_w * hc.shelf_d * hc.sheet_t
CHECKS = {
    "envelope": lambda m: m.bbox("part") <= _env,
    "deck_volume": lambda m: m.volume("top_deck") == approx(_deck_volume, abs=1e-6),
    "posts_clear_top_deck": lambda m: m.interference("post#*", "top_deck")
    == approx(0.0, abs=1e-6),
    "sealed_frame": lambda m: m.sealed("part") and m.genus("part") == 0,
}

part.description = "Open-frame shelf: two sheet decks tied by four corner posts"
part.material_spec = "Baltic birch plywood decks; hardwood posts, three sheet widths square"
part.process = "cnc_router"
part.general_tolerance = "+/-0.25 mm cut profile"
part.feature("deck_top").surface_finish = "Sand top deck to 180 grit; ease exposed edges"
part.feature("base_bottom").surface_finish = "Leave as-machined; glides attach here"
