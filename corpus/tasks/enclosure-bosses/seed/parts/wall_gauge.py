# Inspection gauge (task-owned: the bench restores this file before grading, so
# editing it changes nothing). The minimum-wall shell: the outer envelope with a
# block one min_wall (1.6 mm) inside every closed face removed, and open at the
# top where the lid goes.
#
# Every point of this shell is material the enclosure MUST have if no wall is
# thinner than 1.6 mm. The acceptance check compares the overlap volume against
# the shell's own volume: a cavity cut too big, a floor left too thin, or a wall
# opened out anywhere eats into the shell and the overlap drops below it. That is
# a DFM min-wall check expressed with measured geometry rather than a promise.
_inner = Pos(0, 0, hc.min_wall) * Box(
    hc.box_len - 2.0 * hc.min_wall,
    hc.box_width - 2.0 * hc.min_wall,
    hc.box_height,  # deliberately overshoots the top: the box is open there
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)
_outer = Box(
    hc.box_len, hc.box_width, hc.box_height, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
shell = _outer - _inner
shell.label = "min_wall_shell"

part.geometry = shell

CHECKS = {
    "gauge_intact": lambda m: m.bbox("part")
    == approx((hc.box_len, hc.box_width, hc.box_height), abs=0.01),
}

part.description = "Minimum-wall shell gauge: 1.6 mm inside every closed face"
part.material_spec = "Reference geometry, not a manufactured part"
part.process = "reference"
