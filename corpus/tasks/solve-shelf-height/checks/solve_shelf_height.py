# solve-shelf-height acceptance checks (project scope: whole-part measurements).
#
# The graded engineering is the HEIGHT, and the height is declared rather than
# retyped: the task's two `proposal_requirements` entries measure the seat and
# the stand-off through the engine constraint path, on the geometry the run
# actually rebuilt. That is the whole point of this family - a proposal is a
# measurement artifact nothing applies, so a run that computes the right
# numbers and never authors them delivers nothing and fails there.
#
# What CHECKS pins is what those two distances cannot see: that the shelf is
# still a shelf and the post still a post. Neither check constrains a solved
# height, deliberately - a check that pinned the answer would grade the
# author's arithmetic instead of the delivered geometry, and would pass a run
# that hard-coded 40 without ever seating anything.
CHECKS = {
    "shelf_footprint": lambda m: m.bbox("shelf/part")[:2] == approx((50.0, 50.0), abs=0.05),
    "shelf_is_one_sealed_plate": lambda m: m.sealed("shelf/part")
    and m.genus("shelf/part") == 0,
    "post_section": lambda m: m.bbox("post/part")[:2] == approx((12.0, 12.0), abs=0.05),
    "post_is_one_sealed_column": lambda m: m.sealed("post/part")
    and m.genus("post/part") == 0,
}
