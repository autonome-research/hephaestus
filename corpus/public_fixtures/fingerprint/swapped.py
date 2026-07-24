# Selector-swap variant of base.py: the crest tag now selects the OTHER
# ridge — a symmetric, equal-descriptor neighbour only 0.8 mm away. Every
# measured delta (centroid 0.8 mm, normal 0 deg, area 0%) stays below the
# §5.3 thresholds, so no warning is emitted. This is the documented
# false-negative limit of the descriptor heuristic; the heuristic never
# claims topology identity, so silence here is by design.
_plate_w = 60.0
_plate_d = 40.0
_plate_t = 6.0
_rib_w = 0.4
_rib_h = 4.0
_rib_x = 0.4
tread = Pos(0, 0, _plate_t / 2.0) * Box(_plate_w, _plate_d, _plate_t)
tread.label = "tread"
ribs = []
for _x in [-_rib_x, _rib_x]:
    rib = Pos(_x, 0, _plate_t + _rib_h / 2.0) * Box(_rib_w, _plate_d, _rib_h)
    rib.label = "rib"
    ribs.append(rib)
tag(tread.faces().sort_by(Axis.Z)[-1], "tread_top")
tag(ribs[1].faces().sort_by(Axis.Z)[-1], "rib_crest")
part.geometry = Compound(children=[tread, *ribs])
part.description = "Fingerprint fixture: tread plate with twin ridges"
part.process = "cnc_router"
part.feature("tread_top").surface_finish = "as-milled"
part.feature("rib_crest").surface_finish = "as-milled"
