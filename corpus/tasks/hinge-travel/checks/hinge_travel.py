# hinge-travel acceptance checks (project scope: whole-part measurements only).
#
# The hinge's MOTION — the travel window, the swept wire-channel clearance,
# the stand-clear at the open limit — is NOT measured here: it is the task's
# declared mechanism (KINEMATICS.md §6, Stage 9C), graded through the engine
# motion path (joint `j-lid`, pose `p-open`, motion check `mc-lid-swing`,
# pose-bound constraint `c-open-access`), and the coaxial pin bores are the
# declared 8C constraint `c-hinge-concentric`. What CHECKS owns is the
# single-part facts:
#
# - envelope: each part's overall extents (base: the 60 x 68 deck under the
#   Ø12 boss whose crown tops out at z = 21; lid: the 50 x 30 plate plus the
#   straps and the Ø12 lugs around the axis at z = 15);
# - the closed lid rests on the deck without biting into it;
# - topology: the base is one sealed solid with the pin bore through its boss
#   (genus 1); the lid is one sealed solid with the bore through BOTH lug
#   barrels (genus 2 — two tunnels, which is what makes the lugs real lugs).
_BASE_ENV = (60.0, 68.0, 21.0)
_LID_ENV = (50.0, 44.0, 13.0)

CHECKS = {
    "envelope_base": lambda m: m.bbox("base/part") == approx(_BASE_ENV, abs=0.05),
    "envelope_lid": lambda m: m.bbox("lid/part") == approx(_LID_ENV, abs=0.05),
    "lid_rests_without_bite": lambda m: m.interference("base/part", "lid/part")
    == approx(0.0, abs=1e-6),
    "sealed_base": lambda m: m.sealed("base/part") and m.genus("base/part") == 1,
    "sealed_lid": lambda m: m.sealed("lid/part") and m.genus("lid/part") == 2,
}
