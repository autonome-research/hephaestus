# Notched L-plate: a rectangular blank with a square notch cut out of its
# +X/+Y corner, and the resulting inner corner blended so the part does not
# crack in service. The blend radius currently asks for more material than the
# 20 mm notch can give, so the build fails on the fillet statement; every
# statement above it builds cleanly.
_w = hc.plate_len
_d = hc.plate_depth
_t = hc.plate_t
_notch = hc.notch

plate = Box(_w, _d, _t)
cut = Pos(_w / 2.0 - _notch / 2.0, _d / 2.0 - _notch / 2.0, 0) * Box(_notch, _notch, _t)
notched = plate - cut
_corner = notched.edges().filter_by(Axis.Z).sort_by_distance(
    (_w / 2.0 - _notch, _d / 2.0 - _notch, 0)
)[0]
blended = fillet(_corner, radius=40.0)
tag(blended.faces().filter_by(GeomType.CYLINDER)[0], "inner_fillet")

part.geometry = blended

part.description = "Notched L-plate with a blended inner corner"
part.material_spec = "6 mm 6061-T6 aluminium plate"
part.process = "cnc_router"
part.general_tolerance = "+/-0.15 mm cut profile"
