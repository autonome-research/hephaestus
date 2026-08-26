# Independent second implementation of flange-edit (corpus meta-test).
#
# Same specification, different construction: instead of importing the vendor
# file and cutting (the reference), the flange is remodelled from the vendor's
# published dimensions with the enlarged Ø30 bore designed in from the start.
# The acceptance diff against imports/flange.step must still read this as
# exactly the requested edit - which is what proves the checks grade the
# function (a Ø30-bored vendor flange, in the vendor's pose) rather than the
# reference solution's construction.
_od = 80.0
_t = 8.0
_bore_d = 30.0
_bolt_d = 9.0
_bolt_r = 30.0

body = Pos(0, 0, _t / 2.0) * Cylinder(radius=_od / 2.0, height=_t)
body = body - Pos(0, 0, _t / 2.0) * Cylinder(radius=_bore_d / 2.0, height=5.0 * _t)
for _x, _y in ((_bolt_r, 0.0), (-_bolt_r, 0.0), (0.0, _bolt_r), (0.0, -_bolt_r)):
    body = body - Pos(_x, _y, _t / 2.0) * Cylinder(radius=_bolt_d / 2.0, height=5.0 * _t)
body.label = "flange_body"

part.geometry = body

CHECKS = {
    "matches_the_edited_vendor_flange": lambda m: m.diff("part", "import:flange.step").a_only_mm3
    <= 1.0,
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 5,
}

part.description = "Vendor flange remodelled with the centre bore at 30 mm"
part.material_spec = "Steel flange to the vendor drawing"
part.process = "cnc_mill"
