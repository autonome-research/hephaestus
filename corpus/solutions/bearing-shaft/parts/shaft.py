# Reference solution for bench task bearing-shaft — the shaft itself.
#
# A plain stepped shaft: a 7.98 mm journal running the full length with a 12 mm
# collar in the middle, so the two 608 bearings slip on from either end and stop
# against the collar. The 0.02 mm undersize on the journal is the whole point of
# the task: it is what makes the declared fit a clearance fit rather than a
# nominal one, and the engine measures it rather than taking the prompt's word.
PARAMS = {
    "collar_len": Param(34.0, min=20.0, max=40.0),
}

_journal_d = hc.journal_d
_len = hc.shaft_len

_body = Cylinder(_journal_d / 2.0, _len, align=(Align.CENTER, Align.CENTER, Align.MIN))
_collar = Pos(0, 0, hc.collar_from) * Cylinder(
    hc.collar_d / 2.0, p.collar_len, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
shaft = _body + _collar
shaft.label = "shaft"
part.geometry = shaft

# The two journals are the only 7.98 mm cylinders; the collar splits them, so
# the lower-centred one is the A end.
_journals = shaft.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0:2].sort_by(Axis.Z)
tag(_journals[0], "journal_a")
tag(_journals[-1], "journal_b")

CHECKS = {
    "collar_stands_proud": lambda m: hc.collar_d > _journal_d,
}

part.description = "Stepped shaft with a central collar and a bearing journal at each end"
part.material_spec = "1018 steel, turned"
part.process = "turned"
part.assembly_method = "Bearings slip on from each end and seat against the collar"
