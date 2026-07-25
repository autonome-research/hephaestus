# Reference solution for bench task knob-loft.
#
# A turned control knob, built the way a turned part is described: a revolved
# base flange, a lofted transition from the flange diameter to the grip
# diameter, a cylindrical grip, and a filleted crown. Everything is a body of
# revolution about Z, so the grip's radius is constant at every angle.
_flange_d = hc.flange_d
_flange_h = hc.flange_h
_grip_d = hc.grip_d
_taper_top = hc.taper_top_z
_top = hc.knob_h

# Base flange: revolve its half-section about the knob axis.
_section = Plane.XZ * Pos(_flange_d / 4.0, _flange_h / 2.0) * Rectangle(_flange_d / 2.0, _flange_h)
flange = revolve(_section, Axis.Z)
flange.label = "flange"

# Lofted transition from the flange rim up to the grip.
taper = loft(
    [
        Plane.XY.offset(_flange_h) * Circle(_flange_d / 2.0),
        Plane.XY.offset(_taper_top) * Circle(_grip_d / 2.0),
    ]
)
taper.label = "taper"

# Cylindrical grip up to the crown.
grip = Pos(0, 0, _taper_top) * Cylinder(
    radius=_grip_d / 2.0,
    height=_top - _taper_top,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
grip.label = "grip"

body = flange + taper + grip

# Crown: round the top rim over.
_rim = body.edges().filter_by(GeomType.CIRCLE).sort_by(Axis.Z)[-1]
body = fillet(_rim, radius=hc.crown_r)
body.label = "knob_body"

tag(body.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0], "seat_face")

part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") == approx((_flange_d, _flange_d, _top), abs=0.05),
    "solid": lambda m: m.sealed("part") and m.genus("part") == 0,
    "round_in_plan": lambda m: m.bbox("part")[0] == approx(m.bbox("part")[1], abs=0.01),
}

part.description = "Control knob: revolved flange, lofted transition, filleted crown"
part.material_spec = "PETG, 100% infill"
part.process = "fdm"
part.finish = "As printed; crown sanded"
part.feature("seat_face").surface_finish = "Flat; seats on the panel"
