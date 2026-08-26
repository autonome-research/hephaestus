# Reference solution for bench task flange-edit.
#
# The vendor flange is a term in the expression (INGEST.md §1): import the file
# as-is and open the centre bore from Ø25 to the requested Ø30. Nothing else is
# touched, so everything the vendor ships - outer diameter, thickness, bolt
# holes, pose - survives the edit by construction.
PARAMS = {
    "new_bore_d": Param(30.0, min=25.0, max=36.0),
}

base = import_step("flange.step")

# Cut well past both faces so the enlarged bore is a clean through hole.
_cut_len = 5.0 * hc.flange_t
bore = Pos(0, 0, hc.flange_t / 2.0) * Cylinder(radius=p.new_bore_d / 2.0, height=_cut_len)
body = base - bore
body.label = "flange_body"

# The new bore wall is the cylindrical face nearest the axis.
_bore_wall = body.faces().filter_by(GeomType.CYLINDER).sort_by_distance((0, 0, hc.flange_t / 2.0))[0]
tag(_bore_wall, "bore_wall")

part.geometry = body

CHECKS = {
    # 1727.88 mm^3 is the Ø25 -> Ø30 annulus the request asks for ("grow from
    # 25 mm to 30 mm diameter"); the window matches the task's removal budget.
    "removed_the_bore_annulus_only": lambda m: m.diff("part", "import:flange.step").b_only_mm3
    == approx(1727.88, abs=120.0),
    "added_nothing": lambda m: m.diff("part", "import:flange.step").a_only_mm3 <= 1.0,
    "still_the_vendor_flange": lambda m: m.sealed("part") and m.genus("part") == 5,
}

part.description = "Vendor pipe flange with the centre bore opened to 30 mm"
part.material_spec = "Vendor-supplied steel flange, machined as received"
part.process = "cnc_mill"
part.general_tolerance = "+/-0.05 mm on the bore diameter"
part.feature("bore_wall").surface_finish = "Bored finish; seals on the nozzle O-ring"
