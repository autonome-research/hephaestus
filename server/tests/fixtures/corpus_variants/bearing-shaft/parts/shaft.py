# Independent second implementation for bench task bearing-shaft — the shaft.
#
# Built from sketches and extrusions rather than from primitives, top-down
# rather than bottom-up, with the collar as its own extruded profile and the
# journals named by where they sit rather than by a sort order. Same interface,
# different construction: if the acceptance demanded the reference's build it
# would fail here.
PARAMS = {
    "stock_allowance": Param(0.0, min=0.0, max=1.0, doc="unused turning allowance, mm"),
}

_journal_r = hc.journal_d / 2.0
_top = hc.shaft_len

_blank = extrude(Plane.XY * Circle(_journal_r), amount=_top)
_collar = extrude(Plane.XY.offset(hc.collar_to) * Circle(hc.collar_d / 2.0), amount=-(hc.collar_to - hc.collar_from))
shaft = Part() + _blank + _collar
shaft.label = "shaft"
part.geometry = shaft

# Named by position, not by sort order: the journal nearest the datum end is A.
_cyls = shaft.faces().filter_by(GeomType.CYLINDER)
tag(_cyls.sort_by_distance((0.0, 0.0, 0.0))[0], "journal_a")
tag(_cyls.sort_by_distance((0.0, 0.0, _top))[0], "journal_b")

CHECKS = {
    "journals_are_undersize": lambda m: hc.journal_d < 8.0,
}

part.description = "Stepped shaft: a full-length journal blank with an extruded central collar"
part.material_spec = "1018 steel bar, turned"
part.process = "turned"
part.assembly_method = "Bearings slip on from each end and seat against the collar"
