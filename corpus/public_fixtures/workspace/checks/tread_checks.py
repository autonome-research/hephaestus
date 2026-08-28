# Persistent project checks (script contract §6) for the workspace fixture.
#
# One check per REACHABLE badge state (INTERFACE.md §6.3): a predicate that
# holds, one that does not, and one that cannot be evaluated at all because it
# names a part this project does not have — which `run_checks` records as
# `measured.error` and `badge()` maps to `error`, never to `fail`.
#
# The fourth badge, `not_run`, has NO engine producer: `run_bundle` loads every
# check in the frozen bundle and runs all of them, so declared == run always.
# See README.md beside this file; it is a projection-level state, exercised
# through `checks_projection(report, declared=...)`, not something a check file
# can bring about.
CHECKS = {
    "tread_is_one_sheet_thick": lambda m: m.bbox("tread/part")[2] <= 6.0,
    "tread_fits_a_100_mm_sheet": lambda m: m.bbox("tread/part")[0] <= 100.0,
    "tread_clears_the_absent_stringer": lambda m: m.bbox("stringer/part")[0] > 0.0,
}
