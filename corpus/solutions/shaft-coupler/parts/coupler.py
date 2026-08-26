# Reference solution for bench task shaft-coupler — the sleeve coupler.
#
# A Ø22 sleeve, 30 long, bored 0.04 mm radial over the spindle (inside the
# task's 0.02-0.08 sliding window), seated 12 mm above the hub shoulder, with
# one Ø4 set-screw hole radially through the +Y wall at mid-length.
_bore_r = hc.spindle_d / 2.0 + 0.04

_outer = Cylinder(radius=hc.coupler_od / 2.0, height=hc.coupler_len)
_bore = Cylinder(radius=_bore_r, height=hc.coupler_len + 2.0)
# The set-screw hole: along +Y from inside the bore cavity out past the OD,
# through one wall only.
_screw = Rot(-90.0, 0.0, 0.0) * Cylinder(
    radius=hc.setscrew_d / 2.0,
    height=hc.coupler_od / 2.0 + 1.0,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
body = _outer - _bore - _screw
body = Pos(0.0, 0.0, hc.coupler_seat_z + hc.coupler_len / 2.0) * body
body.label = "coupler_body"

# Radius sorts the three cylindrical faces: set-screw hole, bore, OD wall.
tag(body.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[1], "bore")
tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "seat_end")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part")
    == approx((hc.coupler_od, hc.coupler_od, hc.coupler_len), abs=0.05),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 2,
}

part.description = "Sleeve coupler, sliding fit on the Ø12 spindle, one M4 set-screw hole"
part.material_spec = "22 mm 6061-T6 aluminium bar"
part.process = "cnc_router"
