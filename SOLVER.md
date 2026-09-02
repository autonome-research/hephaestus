<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 15 — Placement proposal and pose solving (Stage 13)

Number 15 is the next free slot in the repo's document sequence: `00`
`architecture.md`, `01` `script_contract.md`, `02` `tool_schema.md`, `03`
`verification.md`, `04` `mission_plan.md`, `05` `repo_conventions.md`, `06`
`VALIDATION.md`, `07` `INGEST.md`, `08` `COMPARE.md`, `09` `ASSEMBLY.md`, `10`
`EXTERNAL_EVAL.md`, `11` `KINEMATICS.md`, `12` `INTERFACE.md`, `13`
`PARTS_STORE.md` (Stage 11, landed), `14` `MESH_INGEST.md` (Stage 12, landed).
`16` `CAM.md` and `17` `PHYSICS.md` are drafts already holding their numbers,
so 15 is the free slot and taking it renumbers nothing.

**Normative** (promoted 2026-08-30 with the `mission_plan.md` Stage 13
amendment — a dated Stage 13 heading naming 13A/13B/13C, carrying the
G13A–G13C gate summaries and citing this spec, on the
`ASSEMBLY.md` / `COMPARE.md` / `KINEMATICS.md` pattern exactly
(`KINEMATICS.md:8-11`; `mission_plan.md:984-1000` is the worked example), and
written **after** an adversarial pass against the codebase). What that review
was, stated so no later reader rounds it up: a six-finding adversarial pass —
three blocking, three major — followed by an independent clause-by-clause
closure audit against the repository, which found seven further defects inside
the closures and closed them with them. That is smaller than the 40-agent,
31-finding pass `KINEMATICS.md` records, and the plan's Stage 13 block says so
too. All six findings were closed by **tightening**; no clause was deleted or
weakened, and the count stands at 56 (G13A 17, G13B 26, G13C 13). A further
adversarial pass remains available and would land as tightenings under mission
rule 1, never as waivers.

The no-solver rule quoted in §1 was the only binding text on this subject until
that amendment landed. It is now **scoped, not deleted**: `ASSEMBLY.md` §1's
first two sentences stay normative verbatim, `mission_plan.md`'s Stage 13 block
carries the writeback refusal in its own words, and this document is binding on
the machinery the three sub-gates ship.

This document is unusual among its siblings: every other normative spec in
this repo *adds* a capability the plan already anticipated. This one
**reverses a rule five documents and four modules state in the imperative**.
Mission rule 5 (`mission_plan.md:1957-1959`) is the only door — deferred items
enter by amending the plan with a new gated stage — and `ASSEMBLY.md:68`
pre-authorised exactly this route in the same breath as the refusal: "(A
placement solver, if ever, is a separate stage.)" §1 is therefore not
preamble. It is the load-bearing section, and a reviewer who rejects §1
should reject the rest unread.

**The reversal is scoped, and the scope is the whole of it.** Three of those
five document sentences were scoped on 2026-08-30 (Amendment manifest); two
more are scoped at 13B; **all four module contracts stand unamended and the
new modules restate them**. What the reversal buys is proposing, and nothing
else: writeback is refused, in `mission_plan.md`'s own words as well as here,
and no code path in Stage 13 writes a script, a parameter, or an artifact.

## Amendment manifest

Each amendment lands with the sub-stage whose machinery ships it; amending a
document before its machinery exists is doc drift (`KINEMATICS.md:25-29`).

**Three of them landed early, with the plan amendment itself (2026-08-30), and
the manifest rows below record it.** The `ASSEMBLY.md` §1, `KINEMATICS.md` §0
and `tool_schema.md` rows were drafted as "lands with 13A". They landed one
step earlier, in the same change as the `mission_plan.md` Stage 13 block and
ahead of any 13A code, because the reason those three rows were pulled forward
from 13B to 13A applies once more at the boundary: an amendment that reverses a
rule cannot trail the plan block that authorises the reversal, and a rule
sentence left standing *false* between the two changes is the drift
`KINEMATICS.md:25-29` names. This is not the doc-drift failure that rule
guards against, which is a document describing machinery that does not exist:
none of the three claims any Stage 13 tool exists, each **scopes** a sentence
rather than deleting it, and `tool_schema.md` says in the same breath that no
Stage 13 tool has a heading yet. G13A clause 14 is unchanged and still asserts
all three as landed text — a clause asserting a state, not an edit, passes
whether the edit landed at 13A or before it.

**Citation audit, as a precondition on every sub-stage (2026-08-30).** This
document was drafted at `ab0cf66`, *before* Stage 11 (`d9d845f`) and Stage 12
(`668064f`) landed, and those stages amended five of the documents it cites
by line: `mission_plan.md` (+649 lines), `script_contract.md` (+146),
`tool_schema.md` (+140), `COMPARE.md` (+51), `VALIDATION.md` (+50), plus
`bench/scoring.py` (+352) and both tool-count pins. Roughly thirty citations
had drifted by up to 550 lines, and the surface count had moved 53 → 54 under
`compare_to_scan`. All of them were re-resolved against `HEAD` on 2026-08-30
and are correct as written *now*. Two of them were load-bearing rather than
cosmetic — G13A clause 14 greps the `check_assembly` occurrence of "There is
no solver." (`tool_schema.md:911`, which the 2026-08-30 amendment rewrote in
place, so the clause now reads the amended wording at the same line), and
G13B clause 40 repoints the two literal `assert len(...) == N` pins — so a
stale line number here is not a typo but a gate clause nobody can write.
**The audit ran a second time on 2026-08-30**, after this stage's own
amendments moved `ASSEMBLY.md`, `KINEMATICS.md`, `tool_schema.md` and
`mission_plan.md` underneath it: sixteen further citations were re-resolved,
including four whose *anchors* had drifted before this stage touched anything
(`KINEMATICS.md`'s no-clamping rule and its "exports are never posed"
sentence were each cited a line or two past the text they name, which a
range-resolves check cannot catch and an anchor check does). **Each sub-stage
therefore re-runs
this audit as part of its own gate**, in two halves: every `file:line`
citation in this document resolves **by range** inside the file it names, and
every citation in the **anchor register** below resolves to text containing
the anchor it is registered for. Both halves are asserted mechanically, at
13A, 13B and 13C alike. Documents drift under other stages; a spec that cites
them by line has to be re-measured, not trusted.

**The audit ran a third time at 13C, and this time it caught drift that no
Stage 13 edit caused — which is the case it was actually built for.** Five
anchors had slid: `docs/cli.md`'s scoped "no solver **in this surface**"
sentence moved 255 → 390, because 13A's, 13B's and 13C's own `heph solve`
sections all land above the `heph joints` section that carries it (drift this
stage caused, and the sub-stage-local half of the audit's job); and the four
**mission rules** moved +8 lines each — 1850 → 1858, 1864 → 1872, 1867 → 1875,
1872 → 1880 — under an unrelated `mission_plan.md` insertion made while this
sub-stage's suite was running. Both halves were re-resolved and both are now
correct as written. The second is the argument for the per-sub-stage rule
stated as strongly as it can be stated: the citation that broke was to mission
rule 1, the rule that says a gate is a command, and nothing in Stage 13 touched
the file it points at.

**This sentence was tightened on 2026-09-01, loudly, under mission rule 1
(`mission_plan.md:1943-1946`), after an independent verifier found it
asserting more than any gate could.** It read "every `file:line` citation in
this document resolves to text containing the anchor it is cited for" — a
universal anchor claim over ~160 citations. No parser can derive a
per-citation anchor from a line number, so the universal form was not a
clause a gate could be written for, and the machinery that shipped under it
did a range check everywhere and an anchor check over a list curated inside
two test files. That is the defect this document warns about one level up: a
clause asserting more than the machinery does. The fix is **tightening, never
waiving** — the anchor half is now scoped to an enumerated register, the
register lives **here, in the normative document**, not in a test file, and
each sub-stage asserts that its own list of anchors *is* the register (a row
added here and nowhere else fails the gate, and a test that quietly dropped a
row fails it too). Scoping the claim to a register is strictly more than the
old sentence bought in practice, because the old one bought nothing that was
assertable; and the range half stays universal.

**The anchor register.** Each row is a citation this document's own clauses
lean on — a gate greps the cited text, or a rule's whole force depends on the
sentence being the one cited — and each is re-resolved by anchor at every
sub-stage. A citation whose range still resolves but whose text has slid
fails *silently*, and a reader following it lands on a sentence that says
something else; four of these were wrong that way once, before this stage
touched anything.

- `mission_plan.md:1943-1946` — "Gates are commands"
- `mission_plan.md:1957-1959` — "Scope discipline"
- `mission_plan.md:1960-1964` — "Framework boundaries are contractual"
- `mission_plan.md:1965-1969` — "Pinned, isolated agent dependencies"
- `mission_plan.md:984-1000` — "Stage 12 — Mesh and scan ingest"
- `ASSEMBLY.md:56-57` — "A constraint that requires motion to satisfy is"
- `ASSEMBLY.md:55-75` — "NO SOLVER MOVES GEOMETRY"
- `ASSEMBLY.md:68` — "is a separate stage.)"
- `ASSEMBLY.md:126` — "No placement solver **in 8C**"
- `KINEMATICS.md:333` — "No placement/assembly solver **in Stage 9**"
- `KINEMATICS.md:25-29` — "Each amendment lands with the sub-stage whose machinery ships it"
- `KINEMATICS.md:8-11` — "Stage 9 amendment"
- `KINEMATICS.md:394-406` — "FakeModel harness"
- `VALIDATION.md:320-331` — "It clears in exactly two ways"
- `VALIDATION.md:392-396` — "blocking finding by rule"
- `VALIDATION.md:67-77` — "insufficient_scan_seeds"
- `VALIDATION.md:163-167` — "independent second solution"
- `VALIDATION.md:510-516` — "budget = ceil"
- `tool_schema.md:911` — "No solver moves geometry"
- `tool_schema.md:126-132` — "orchestrator-only"
- `script_contract.md:119-140` — "PARAMS"
- `script_contract.md:141-149` — "globals.py"
- `script_contract.md:164-172` — "a part MUST NOT shadow an `hc` name"
- `docs/cli.md:390-393` — "no solver **in"
- `bench/src/hephaestus/bench/scoring.py:282-304` — "def split_name"
- `contract/tests/test_toolgen.py:98-115` — "declared additions, not drift"
- `tests/stage2/test_g2_contract_drift.py:357` — "solve_pose"
- `tests/stage2/test_g2_contract_drift.py:270-305` — "def test_documented_signature_matches_declared_parameters"

A row may be added here at any time and costs nothing but the anchor holding;
a row may be **removed** only with the clause that stopped leaning on it.

**The audit ran a fourth time on 2026-09-01, against the repair itself, and
the four mission rules moved a second time.** Recording the tightening in
`mission_plan.md`'s Stage 13 block inserted sixteen lines above the rules, so
rule 1 moved 1885 → 1899, rule 5 1899 → 1913, rule 6 1902 → 1916 and rule 7
1907 → 1921; all four were re-resolved by anchor, here and in the register
above, and eleven citations in this document were repointed. The register
caught its own author, which is the strongest thing that can be said for a
mechanical audit: the change that *scoped* the anchor check was the change
that broke four anchors, and nothing but the check would have noticed.

**And a fifth time, later the same day, for the same reason.** Recording the
second 2026-09-01 repair (the `kappa` recording below, and clause 17's
tightening) inserted twenty-seven lines above the mission rules, so rule 1
moved 1899 → 1926, rule 5 1913 → 1940, rule 6 1916 → 1943 and rule 7 1921 →
1948; all four were re-resolved by anchor, here and in the register above, and
the twelve citations in this document were repointed. Twice in one day, from
two unrelated edits to a paragraph neither of them was about, is the argument
for running the audit per sub-stage rather than once: *the rule that keeps
being broken is mission rule 1, and nothing in Stage 13 touches the file that
holds it.*

- **`ASSEMBLY.md` §1, the `NO SOLVER` bullet** — **LANDED 2026-08-30 with the
  plan amendment** (the amended bullet is `ASSEMBLY.md:55-75`), one step ahead
  of the **13A** the row was drafted for, and the ordering is not a
  preference in either version. 13A's second target
  form (§2A) drives joint motion to satisfy *declared 8C constraint ids*,
  which is exactly the act `ASSEMBLY.md:56-57` forbids as written: "A
  constraint that requires motion to satisfy is simply unsatisfied." An 13A
  that shipped before this amendment would be a sub-stage of machinery its
  own binding rule prohibits, so the amendment is 13A's machinery, not 13B's.
  The first two sentences are unchanged and stay normative
  verbatim: *"Scripts position geometry; constraints verify, they never move
  anything. A constraint that requires motion to satisfy is simply
  unsatisfied."* The parenthesis `(A placement solver, if ever, is a separate
  stage.)` is replaced by: *"A placement solver PROPOSES: Stage 13
  (`SOLVER.md`) computes candidate placements as a measured, provenance-
  carrying artifact that no tool applies. A constraint's verdict is still
  produced only by measuring delivered geometry; a proposal is never a
  verdict, never clears a violated row, and nothing in Stage 13 writes a
  script, a parameter, or an artifact."* The heading of the bullet changes
  from `NO SOLVER` to `NO SOLVER MOVES GEOMETRY`.
- **`ASSEMBLY.md` §4 (`ASSEMBLY.md:126`)** — **LANDED 2026-08-30 with 13B**.
  "No placement solver." is scoped to 8C the way its neighbouring sentence was
  already scoped to 8C by the Stage 9 amendment: "No placement solver **in
  8C** (amendment: proposal-only placement solving is Stage 13 per
  `SOLVER.md`; nothing in Stage 13 moves what a script authored)", and the
  landed bullet adds what the proposal is and is not — a measured,
  provenance-carrying artifact no tool applies, with the `AssemblyStatus` row
  still saying `violated` until a rebuilt script measures otherwise, and
  writeback refused.
- **`KINEMATICS.md` §0, first bullet** — **LANDED 2026-08-30 with the plan
  amendment** (the amended bullet is `KINEMATICS.md:45-56`), one step ahead of
  the **13A** the row was drafted for. The sentence *"nothing in Stage 9
  moves what a script authored or
  republishes transformed artifacts. A pose exists only inside an
  evaluation."* is unchanged and remains true of Stage 9 and of Stage 13. The
  bullet gains: *"Stage 13 (`SOLVER.md`) adds the inverse direction —
  **solving for joint parameter values** (§2A below) and **proposing** part
  placements (§2B) — under the same rule: a solved pose is a parameter
  assignment, which is exactly what a declared pose already is
  (`KINEMATICS.md` §3), and a proposed placement is an artifact nobody
  applies."* The bullet title changes from "A solver that positions authored
  geometry" to "A solver that MOVES authored geometry".
- **`KINEMATICS.md` §7 (`KINEMATICS.md:333`)** — **LANDED 2026-08-30 with
  13B**. "No placement/assembly solver — authored positions stay authored."
  became "No placement/assembly solver **in Stage 9** — authored positions stay
  authored, in Stage 9 and in Stage 13 alike (`SOLVER.md` §1)."
- **`tool_schema.md`** — **§`check_assembly`'s "There is no solver."**
  was rewritten to the amended `ASSEMBLY.md` §1 wording and **LANDED
  2026-08-30 with the plan amendment** (`tool_schema.md:911-926`), rather than
  at the **13A** the row was drafted for. The row said "at 13A, in the same
  change that adds the `solve_pose` heading"; the sentence went one step
  earlier and the heading did not move with it, because the two halves are
  not symmetric. Scoping a false sentence early leaves the document *more*
  accurate, while adding a heading for a tool that does not exist would break
  `tests/stage2/test_g2_contract_drift.py`'s declaration ⇄ heading equality —
  so the sentence is scoped now and says in its own text that no Stage 13 tool
  has a heading yet. What the row was protecting is untouched: a normative
  tool document that carries a `solve_pose` signature block and the un-scoped
  sentence "There is no solver." would contradict itself for the whole
  duration of a *passing* G13A, and doc drift that a gate does not catch is
  the failure `KINEMATICS.md:25-29` names. G13A greps for exactly this pair
  (Gates, G13A) and is unchanged — it asserts a state, which now holds on
  the sentence half already. Three new tool headings are added — `solve_pose`
  (13A),
  `propose_placement` (13B, with its `space` enum extended and its
  `space: "parameters"` subsection **LANDED 2026-08-30 with 13C**),
  `read_proposals` (13B) — with their profile rows (§11). The 13B pair
  **LANDED 2026-08-30**, and the sentence that named them absent moved with
  them, so the declared surface in that document is again exactly the surface
  that exists.
- **`docs/cli.md` §`heph joints`** — lands with **13A**, and this row was
  missing from the manifest until the plan amendment landed (2026-08-30);
  finding it then rather than at 13A is the citation audit paying for itself.
  The sentence "there is no per-script joint syntax and no solver: scripts
  position geometry, poses exist only inside an evaluation"
  (`docs/cli.md:390-393`, re-resolved at 13C: 13A's, 13B's and 13C's own
  `heph solve` sections land above this one, so the anchor moved 255 → 390 and
  the audit is what noticed) is **true today** — no `heph solve` verb exists — and
  becomes false the moment 13A ships `heph solve pose` (§11). It is scoped, not
  deleted, on the same pattern as the three sentences above: "no solver **in
  this surface** — `heph solve` (Stage 13, `SOLVER.md`) proposes and writes
  nothing; scripts position geometry, poses exist only inside an evaluation."
  Deliberately **not** landed with the plan amendment, because unlike the other
  three it names a CLI surface rather than a rule, and scoping it before the
  verb exists would describe machinery that does not — which is the drift
  `KINEMATICS.md:25-29` actually names. `docs/cli.md` is inside
  `scripts/docs_check.py`'s checked set, so the reference it gains is
  mechanically resolved.
- **`VALIDATION.md` §5** — **LANDED 2026-08-30 with 13B**. The reviewer context
  gains placement proposals, **explicitly as non-evidence**: the never-green rule at
  `VALIDATION.md:392-401` is unchanged, and one sentence is added — "A
  placement proposal (`SOLVER.md` §8) is delivered to the reviewer as a fact
  about a computation, never as a constraint verdict; it clears nothing, and
  no verdict is solicited or accepted for a proposal id." **`VALIDATION.md`
  §1** gains the Stage 13 corpus split — **LANDED 2026-08-30 with 13C**, on
  the G9C wording verbatim and on the terms Stages 11 and 12C took: the
  `solve-*` family's two splits, its own first measurement at >= 3 seeds, its
  own `solve_baseline.json`, `insufficient_solve_seeds` for a thinner one, and
  neither compared against nor averaged into the v1/v2/v3 baselines. The
  section also states the `proposal_requirements` acceptance vocabulary and why
  it is graded on the rebuilt part and never on the proposal.
- **`script_contract.md`** — **nothing changes.** Named here because silence
  in an amendment manifest is a claim: part scripts declare no solve, `PARAMS`
  and `hc` are untouched, the `CHECKS` facade gains no solver surface (§12),
  and no build path changes. The 13C parameter solve rides `build_part`'s
  existing transient-override preview contract (`script_contract.md:476-481`,
  `tool_schema.md:238-243`) without amending it.
- **`COMPARE.md`, `INGEST.md`, `EXTERNAL_EVAL.md`, `architecture.md`,
  `verification.md`, `repo_conventions.md`, `INTERFACE.md`** — unchanged.
  `COMPARE.md` §5's bounded-execution pattern is *reused* (§10), not amended.

Design premise: Stage 8C made a mate a declared, machine-checked fact, and
its honesty rests on a single mechanism — nothing between declaration and
measurement can move the geometry, so `violated` means the delivered design
misses the mate (`VALIDATION.md:397-399`). What 8C cannot do is tell an
author *how far off, and in what direction*. A `violated` row today carries a
signed scalar (`ConstraintResidual.slack`,
`core/src/hephaestus/geom/constraints.py:295-333`) and a worst-point pair;
turning that into an edit is unaided human or model arithmetic over a coupled
system, and coupled systems are where hand arithmetic fails. Stage 13 computes
the answer and **hands it back as a measurement**, leaving the authoring act —
and therefore the authorship, the diff, the provenance and the git history —
exactly where they are.

## 0. What this capability is, and what it is not

Stage 13 is a **numerical proposal service**: given declared constraints, the
current published artifacts, and a declared set of free variables, it computes
values that would reduce declared residuals, re-measures its own answer
through the *existing* evaluator in a separate process, and stores the result
as a content-addressed artifact. It is:

- **13A — pose solving.** Free variables are declared joint parameters
  (`KINEMATICS.md` §1). The output is an assignment `{joint_id: value}`,
  which is precisely the shape a named pose already has
  (`KINEMATICS.md:166-175`) and precisely what `declare_pose` already writes.
  **This half moves nothing authored** — but its legality under the *unamended*
  rule splits, and the earlier draft of this bullet overclaimed it. An
  **anchor-to-point target** (the inverse of `reach`) touches no constraint
  set and needs no rule change: it is arithmetic over declared joint
  parameters, and a solved assignment is a pose. A **constraint-id target**
  (§2A) drives motion in order to satisfy a declared 8C constraint, which
  `ASSEMBLY.md:56-57` forbids in those words; it is legal only under the §1
  amendment, which was scheduled at 13A for that reason and landed one step
  earlier still, on 2026-08-30 with the plan amendment (Amendment
  manifest) — so 13A's code ships into a rule that already permits it. 13A is
  staged before 13B because it shares every piece of machinery with it and
  scheduling it elsewhere would duplicate that machinery — not because it
  needs no amendment.
- **13B — placement proposal.** Free variables are a rigid transform per
  declared-free part. The output is a **proposal artifact**, not a placement.
- **13C — parameter proposal.** Free variables are declared `Param`s
  (`script_contract.md:119-140`), evaluated by transient-override preview
  builds, which are `current=false` by contract and publish nothing
  (`script_contract.md:476-481`).

It is **not**:

- **A solver that moves geometry.** No tool, CLI verb, or code path in Stage
  13 writes a part script, writes a parameter, republishes a transformed
  artifact, or makes any build current. The four module-level contracts that
  say so today (`geom/constraints.py:17-18`, `geom/kinematics.py:17-21`,
  `core/assembly.py:27-34`, `core/motion.py:106-110`) are **not weakened**;
  the new modules restate them.
- **A writeback engine.** There is no inverse from a `RigidTransform` to a
  script expression. A +0.42 mm X delta on
  `corpus/public_fixtures/assembly/parts/bracket.py:19-20` can be authored as
  a change to `hc.joint_clear`, `hc.shelf_w`, `p.wing`, or a new literal —
  four different design intents, three of which change other parts
  (`script_contract.md:164-172`). Stage 13 **refuses to guess which**, and the
  refusal is structural rather than a promise or a runtime check: the
  proposal document schema (§8) is `additionalProperties: false`, so a
  `suggested_edit` field cannot be emitted, and every tool input schema in
  this repo already is (57 of 57 `schemas/tools/*.schema.json`, re-measured
  2026-08-30 with 13B's two additions; it was 54 of 54 at 13A, the surface
  having been 54 since Stage 12C's `compare_to_scan` and not the 53 an earlier
  draft counted; e.g. `set_params.schema.json:6`), so
  one cannot be requested either. There is
  no refusal *name* here because there is no reachable request to refuse —
  see §8.
- **A constraint-driven parametric modeller.** Constraints do not acquire
  authority over geometry; they acquire a *gradient*. The authority stays in
  the script.
- **A global optimiser.** Every method here is local, started from declared
  starts, and its verdicts say so by name (§6). No branch-and-bound, no
  simulated annealing, no random restarts (an RNG would also break §9).
- **Dynamics, loads, FEA, or contact resolution.** Unchanged from
  `KINEMATICS.md:57-62`; FEA is named deferred by `mission_plan.md:1957-1959`.
- **A verdict.** §7 and §8 are the sections that make this true, and they are
  the sections a hostile review should read first.

## 1. The reversal, confronted

### 1.1 The rule, verbatim

**Three of the five sentences below were scoped on 2026-08-30** by the
`mission_plan.md` Stage 13 amendment and the Amendment manifest's first three
rows. They are quoted here **as they stood before it**, because a reversal
argued against a paraphrase of what it reverses is not an argument; each is
followed by where its scoped form now lives. None was deleted, and none lost
its no-writeback force.

`ASSEMBLY.md` §1's last bullet, **as it stood** (now `ASSEMBLY.md:55-75`,
titled `NO SOLVER MOVES GEOMETRY`, whose first two sentences are the two
below, unchanged):

> **NO SOLVER.** Scripts position geometry; constraints verify, they never
> move anything. A constraint that requires motion to satisfy is simply
> unsatisfied. (A placement solver, if ever, is a separate stage.)

The parenthesis is the route this stage took and is now spent; it survives in
the bullet's dated amendment note (`ASSEMBLY.md:68`) as the record of what was
replaced.

`ASSEMBLY.md:126`, §4: "No placement solver." — **unamended**, scoped at 13B.

`KINEMATICS.md` §0's first bullet, **as it stood** (now
`KINEMATICS.md:45-56`, titled "A solver that MOVES authored geometry", whose
first sentence is the one below, unchanged):

> - **A solver that positions authored geometry.** The 8C rule stands
>   verbatim: scripts position geometry; nothing in Stage 9 moves what a
>   script authored or republishes transformed artifacts. A pose exists only
>   inside an evaluation.

`KINEMATICS.md:333`, §7: "No placement/assembly solver — authored positions
stay authored." — **unamended**, scoped at 13B.

`tool_schema.md`'s `check_assembly` section, **as it stood** (now
`tool_schema.md:911-926`, opening "**No solver moves geometry.**" and carrying
the amended `ASSEMBLY.md` §1 wording):

> **There is no solver.** Scripts position geometry; constraints verify, they
> never move anything, and a constraint that would need motion to satisfy is
> simply unsatisfied.

And in code, as module contract, four times — **all four unamended and not
weakened by this stage; the new modules restate them** (§0):
`core/src/hephaestus/geom/constraints.py:17-18`
("**NO SOLVER** … Nothing here moves geometry. A constraint that would need
motion to hold simply measures as unsatisfied.");
`core/src/hephaestus/geom/kinematics.py:17-21`;
`core/src/hephaestus/core/assembly.py:27-34`;
`core/src/hephaestus/core/motion.py:106-110`.

### 1.2 What the rule protects

The rule is a short sentence guarding seven properties. Each is named here
with the machinery that implements it, because a design that preserves "the
spirit" of an unenumerated rule preserves nothing.

- **P1 — reproducibility is defined off the script.** A build's identity is
  `input_hashes = {script, hc_dependencies, part_params, effective_params,
  toolchain, imports}` (`script_contract.md:469-479`, rules at `:475-484`). A
  position originating anywhere else is not named by that hash set, so the
  artifact stops being a function of its recorded inputs.
- **P2 — git owns authored design state (mission rule 6,
  `mission_plan.md:1960-1964`).** Per-part placement stored in `.heph/` or a
  ledger would be a second source of geometric truth, which rule 6 forbids
  independently of `ASSEMBLY.md`.
- **P3 — one home per number.** `hc` is how mating parts agree without
  duplicating numbers; a part may not shadow an `hc` name (lint error) "so
  every tunable has exactly one home", and the executor marks exactly the
  consuming parts dirty when an `hc` name changes
  (`script_contract.md:164-172`). A solved literal transform is a second home
  for a number `hc` already owns, and it desynchronises every part reading it.
- **P4 — the diff carries intent.** Real placements are symbolic:
  `corpus/public_fixtures/assembly/parts/bracket.py:19-20` reads
  `body = Pos(hc.shelf_w / 2.0 + hc.joint_clear + p.wing / 2.0, 0, 0) * body`
  under the comment "Seat the bracket one joint_clear off the frame's +X
  face." A reviewer reads that. Nobody reads a 3×4 matrix.
- **P5 — the verdict vocabulary means something.** "`violated` says the
  delivered geometry does not meet a declared mate, `unresolvable` says the
  mate was never checked — and an unchecked constraint is not a passing one"
  (`VALIDATION.md:397-399`), stamped from the engine's status, with "no
  verdict … solicited for a constraint id and none … accepted"
  (`VALIDATION.md:392-396`).
- **P6 — the closed loop stays broken.** "A self-authored spec test cannot
  catch a misreading of the spec, because it encodes the misreading"
  (`VALIDATION.md:24-26`); "Acceptance checks are functional, never
  reproductive" (`VALIDATION.md:127-134`). A harness that satisfies its own
  declared constraints by moving geometry is that loop with one extra step.
- **P7 — every geometry decision cites a requirement.** Constraint provenance
  is compulsory — a requirement id or `assumed` with a reason — "because a
  constraint IS an interpretation of intent" (`ASSEMBLY.md:52-54`;
  enforced at
  `core/src/hephaestus/core/project_store/constraints.py:26-31`).

### 1.3 The design that preserves them

One structural decision does most of the work, and it is the decision the
operator's framing already points at:

> **DECISION (the reversal's whole content): the solver PROPOSES.** Its
> output is a content-addressed, provenance-carrying measurement artifact.
> No tool, no CLI verb, and no agent path in Stage 13 applies it. Applying is
> an authoring act performed by an agent or operator through the *existing*
> `edit_part` / `write_part` / `set_params` surface, with the existing
> optimistic-hash, journal-backed, no-force-overwrite contract
> (`tool_schema.md:190-227`), and it shows up in git as a normal diff.
>
> **The alternative that lost: mutating published artifacts** — republishing
> transformed geometry so a constraint measures satisfied. It fails P1
> (provenance stops being a function of `input_hashes`), P2 (git no longer
> holds design state), P5 and P6 (the constraint becomes self-satisfied), and
> it exports geometry no script produces. Stage 9 already refused a strictly
> weaker version of it — "or republishes transformed artifacts"
> (`KINEMATICS.md:46`), "exports are never posed" (`KINEMATICS.md:343-344`).
> A third alternative, **the solver driving `edit_part` itself**, is refused
> in Stage 13 for a narrower reason: it resolves the writeback ambiguity of
> §0 by model interpretation, which `VALIDATION.md` gates rather than trusts,
> and it collides with the tag-drift soft failure
> (`script_contract.md:236-241`) where a resolved selector "may select a
> *different* face, and nothing in the resolution itself detects the drift".
> It is a candidate for a later amendment that would need the
> dimension-findings discipline verbatim; it is not in Stage 13.

Property by property, under that decision:

| Property | How it survives |
|---|---|
| P1 | No artifact is produced by anything but a script build. A proposal is not an input to a build and is not in `input_hashes`. The 13C preview builds are `current=false` by existing contract (`script_contract.md:476-481`). |
| P2 | A proposal is a *measurement*, in the same category as an `AssemblyStatus` or a `SolidDiff` — not design state. Design state after Stage 13 is exactly what it is today: scripts, `globals.py`, and persisted params, in git. |
| P3 | Nothing is written, so no second home is created. The 13C parameter space is the strongest case: its free variables are `Param`s, which already have exactly one home and already ride `effective_params` in the input hash. |
| P4 | The author writes the diff. A proposal deliberately ships **no** suggested source text (§8). |
| P5 | §7: the proposal's residuals are re-measured by `core.assembly` through `evaluate_residual` in a separate process, and the `AssemblyStatus` row is untouched — it keeps saying `violated` until a rebuilt script measures otherwise. |
| P6 | The loop is broken at the same seam `VALIDATION.md` already uses for binding-dimension findings: a finding "clears in exactly two ways — a later successful build of the same part whose binding diff no longer raises it … or an explicit dismissal by the user", and "there is no model-facing write" (`VALIDATION.md:320-331`). Stage 13 adopts that clearing rule verbatim for proposals. |
| P7 | A solve request carries compulsory provenance on the 8C/ledger taxonomy (§8): a requirement id, or `assumed` with a reason. A proposal without it is refused `invalid_solve_request`, nothing written. |

## 2. Three solve spaces, one discipline

Every space obeys the same five-step pipeline; only the variables differ.
**Resolve → assemble residuals → iterate → re-measure independently → record
as a proposal.**

### 2A. Pose space (13A) — free joint parameters

Variables: a declared subset of the joint set's parameters, each inside its
declared limits (`JointFrame.limits` / `travel_limits`,
`core/src/hephaestus/geom/kinematics.py:268-298`). Targets: an anchor-to-point
target (the inverse of `reach`, `KINEMATICS.md:203-208`), and/or a set of
constraint ids evaluated at the solved assignment.

Nothing here moves authored geometry: a solved assignment is a *pose*, poses
are already declared, model-writable project state (`KINEMATICS.md:166-175`,
`declare_pose` at `KINEMATICS.md:279-282`), and `forward_kinematics` already
places parts transiently without mutation
(`core/src/hephaestus/geom/kinematics.py:711-763`). Stage 13A adds the
inverse direction and nothing else. **13A does not auto-declare a pose**: the
solved assignment is returned, and `declare_pose` remains an explicit act.

**The two target forms were not equally legal before the amendment, and the
difference is scheduling, not rhetoric.** The anchor-to-point form needs no
amendment: it never reads the constraint set. The constraint-id form does —
it moves joint parameters *in order to make a declared 8C constraint measure
satisfied*, and `ASSEMBLY.md:56-57` said in the imperative that such a
constraint "is simply unsatisfied". That is the `ASSEMBLY.md` §1 amendment's
whole job, and it is why the manifest scheduled that amendment at **13A** —
and why it in fact landed with the plan block on 2026-08-30, ahead of any 13A
code. An implementer who wanted 13A to ship without touching `ASSEMBLY.md`
had exactly one legal option: ship anchor-to-point targets only and defer
constraint-id targets to 13B. This spec does not take that option — it amends
first — but records it so the choice is a decision rather than an oversight,
and G13A clause 2(b) exercises the constraint-id form so the amendment is not
bought on credit.

### 2B. Transform space (13B) — a rigid transform per free part

Variables: `SE(3)` per part named in the request's `free` set; every other
part is ground. At least one part must be ground
(`no_ground_part`) — a system with no ground has a six-dimensional trivial
null space and every reported solution would be an arbitrary member of it.

**A part that rides a joint may not be free** (`free_part_is_jointed`): its
position is owned by forward kinematics from its parent, and letting a
transform and a joint both claim it would create the second-home failure P3
describes, inside one evaluation. Jointed parts are solved in pose space. **13B refuses both joint
roles, not only the child**, and the widening is recorded rather than silent:
moving a joint's PARENT freely while its subtree stays where forward
kinematics put it would propose a placement no kinematic chain can realise,
which is the same failure seen from the other end. Stricter than the sentence,
named the same way.

**A pose-bound constraint (`ASSEMBLY.md:41-44`) may not be an objective term
in transform space** (`pose_bound_constraint_in_transform_space`): its
residual is already a function of a pose assignment, and composing a free
transform with an FK transform makes the returned number attributable to
neither. Solve it in pose space, or unbind it.

### 2C. Parameter space (13C) — declared `Param`s

Variables: named `Param`s of parts or of `globals.py`
(`script_contract.md:119-140`, `script_contract.md:141-149`), each strictly
inside its declared
`min`/`max`. This is the space that costs nothing from §1.2: the variables
are bounded, named, one-home-each, already inputs to `input_hashes`, and
already settable without touching source through transient overrides — a
build with transient params "create[s] a preview artifact and therefore
always return[s] `current=false`" (`tool_schema.md:238-240`). The solver can
therefore *evaluate* candidates while writing nothing at all.

**How a variable is spelled (13C).** `<part>.<param>` for a part's own
`PARAMS` and `hc.<param>` for `globals.py`'s — the two spellings a script
already uses to *read* them, so a request names a knob the way the author's
own code does. A `hc.` name in a project that also has a part called `hc` is
refused `unknown_param` rather than guessed into a scope nobody chose.

**`unbounded_param` names a case that really exists**, and it is worth saying
which one: `globals.py` holds two kinds of public name (`script_contract.md`
§4) — declared `Param`s, which carry `min`/`max`, and derived constants, which
do not. A derived constant is a real, readable `hc` name with no declared box,
so a request naming one asks this space to solve over bounds the author never
wrote. Refused by name, never given a default range. (Every `Param` proper is
bounded by construction — `Param(default, min=, max=)` requires both — so
`unbounded_param` would otherwise be a name nothing could reach, which is the
`no_writeback_grammar` defect §6.3 corrects elsewhere.)

Its cost, stated as a limitation rather than routed around: **it can only
reach placements the author parameterised.** A mate nobody made a knob for is
unreachable, and that unreachability is reported by name
(`no_free_variable_affects(constraint_id)` — a constraint whose residual is
insensitive to every free parameter, detected as an all-zero Jacobian column
block beyond `SENSITIVITY_EPS`), never worked around by inventing a
transform.

**And the test has a second conjunct, added at 13C because the first alone is
wrong.** A constraint that is *already satisfied* and moves for nothing is not
unreachable — it is reached, and the honest report of it is the satisfied row
a converged solve already carries. A `fit` sitting inside its declared window
contributes an identically flat residual by construction (§3.3's deadband), so
the one-conjunct reading would refuse a whole solve over a constraint that
holds. The refusal therefore fires only when a source is flat in every free
variable **and** at least one of its components is outside its own declared
bound: nothing can move it, and it is not where it needs to be.

## 3. The residual system

### 3.1 The verdict is `satisfied`; the objective is a residual VECTOR

Two different numbers do two different jobs here, and an earlier draft of
this section conflated them. Conflating them is how a solver comes to emit
`converged_at_tolerance` for a placement the engine measures `violated`.

**What the verdict is decided on: `ConstraintResidual.satisfied`
(`geom/constraints.py:326`), never `slack`.** The record's own docstring is
the reason, and it is the sharpest sentence in the module: "Kinds with an
additional class predicate (`coincident`'s opposed normals, `concentric`'s
axis alignment) can be unsatisfied with positive slack, which is why
`satisfied` is stored rather than derived by the reader"
(`geom/constraints.py:304-311`). Read the code: `coincident`'s `slack` is
`tol_mm - gap` (`:664`) while its `satisfied` is `gap <= tol_mm and opposed`
(`:665`); `concentric`'s are `tol_mm - offset` (`:697`) and
`offset <= tol_mm and angle <= axis_eps_deg` (`:698`). A bracket lying flush
in the right plane and facing the *wrong way* measures `gap == 0.0`,
`slack == tol_mm`, `satisfied == False` — and `AssemblyStatus` keeps saying
`violated`. A solver graded on `slack` would report that placement as
converged, which is precisely the overclaim P5 (§1.2) exists to prevent and
precisely what §11's bench acceptance already refuses by grading on
constraint ids that "must measure `satisfied` through the ordinary engine
path". §6.1 and §7 are therefore written on `satisfied`.

**What the iteration is driven on: a residual vector per constraint**, whose
components are quantities `ConstraintResidual` already carries — in
`measured`, or by name in `values`. Each component has its own declared
bound and its own weight (§3.4):

| Kind | Primary component | Its bound | Class-predicate component | Its bound |
|---|---|---|---|---|
| `coincident` | plane gap, mm (`:657`, `measured`) | `tol_mm` | `normal_deviation_deg`, distance from a true 180° (`:658`, `values`) | `normal_eps_deg`, default `COINCIDENT_NORMAL_EPS_DEG = 1e-3` (`:209`) |
| `concentric` | radial offset, mm (`:691`) | `tol_mm` | `axis_angle_deg`, folded angle between the axis *lines* (`:692`, `:701`) | `axis_eps_deg`, default `CONCENTRIC_AXIS_EPS_DEG = 1e-3` (`:215`) |
| `parallel` | folded angle, deg (`:719`) | `tol_deg` | none — `satisfied` is the primary bound alone (`:725`) | — |
| `perpendicular` | deviation from square, deg (`:742`) | `tol_deg` | none (`:748`) | — |
| `fit` (2C only) | `hole_radius − shaft_radius`, mm (`:790-800`) | `min_mm`/`max_mm` window | none — `axis_angle_deg` / `axis_offset_mm` ride along as facts and do **not** gate `satisfied` | — |

Both class-predicate bounds are *tight*: 1e-3 deg, documented as "kernel
round-off, not a design allowance" (`geom/constraints.py:206-215`). Both are
read out of the entry's `declared` tuple (`:666`, `:699`), never assumed — a
constraint that overrode `normal_eps_deg` is solved against the number it
declared, exactly as `ConstraintResidual.declared` echoes bounds
(`:318-320`).

**The alternative that lost: keep the class predicates out of the objective
and catch them at §7.** A solver blind to the normals has no gradient that
would ever flip the bracket, so every same-facing fixture would burn its
whole iteration budget, converge on the primary component, and be refused at
verification. A refusal produced *unconditionally* for a whole fixture class
is a design error wearing a safety net's clothes.

Nothing new is invented to define "how far off": the numbers the solver
drives are the numbers the reviewer already reads.

### 3.2 Not every kind is an objective term, and the refusals say why

This is the finding most likely to be skipped by an implementer and is
therefore normative. The eight 8C kinds do not form one class:

| Kind | Objective term in 2B? | In 2C? | Class predicate (§3.1) | Why |
|---|---|---|---|---|
| `coincident` | yes | yes | opposed normals | Plane gap `dot(c_b − c_a, n_a)` (`geom/constraints.py:638-671`) — closed-form in the transform through `PlanarFaceRecord` (`geom/topology.py:86-93`). |
| `concentric` | yes | yes | axis alignment | Radial offset of one axis from the other (`geom/constraints.py:672-708`) via `CylinderRecord` (`geom/topology.py:96-108`). |
| `parallel` | yes | yes | none | Folded angle between directions (`geom/constraints.py:709-731`). |
| `perpendicular` | yes | yes | none | `abs(90 − angle)` (`geom/constraints.py:732-754`). |
| `fit` | **no** — `not_an_objective_kind(pose_invariant)` | **yes** | none | `measured = hole_radius − shaft_radius` (`geom/constraints.py:790-800`) is invariant under a rigid transform, so it carries no gradient in 2B. It is not invariant under a `Param` change, so it is a legitimate term in 2C. |
| `distance` | **no** — `not_an_objective_kind(kernel_extremum)` | **yes**, disclosed | none | `measure.distance` is `a.distance_to(b)` (`geom/measure.py:87-89`): piecewise smooth with a witness pair (`_closest_points`, `geom/constraints.py:505-513`) that switches discontinuously as surfaces slide, and the kink sits exactly where mates live. Excluded from 2B structurally (§4.1: `geom.solve` holds frames, not shapes); admitted in 2C, where every derivative is a finite difference anyway, and every result naming one lists it in `nonsmooth_terms`. |
| `clearance_min` | **no** — `not_an_objective_kind(plateau)` | **no** | none | `measure.clearance` returns exactly `0.0` whenever the solids overlap (`geom/measure.py:92-101`): a flat plateau over the whole infeasible region. A solver started in penetration has no descent information at all, and a solver that "optimises" it silently does not work. |
| `no_interference` | **no** — `not_an_objective_kind(plateau)` | **no** | none | Overlap volume is identically `0` over the whole feasible set (`geom/measure.py:62-71`). |

The two plateau kinds are **feasibility filters, never objective terms**.
They are evaluated at the returned solution as verification predicates (§7)
and their outcome is reported; they never steer the iteration. Declaring one
as an objective term is refused at request time, by name, with the reason.

### 3.3 The solver's residual is a REFORMULATION, and the identity is gated

The table above admits four kinds because their `measured` is closed-form in
the transform. That is true and it is not sufficient. **As implemented, all
four of those `measured` expressions are non-smooth or singular at exactly
their own solutions** — the same pathology §3.2 uses to *exclude* `distance`,
whose "kink sits exactly where mates live". Naming the defect in the excluded
kind and not in the admitted ones would be the review this document is
supposed to survive, failed:

- `coincident`: `gap = abs(_dot(...))` (`:657`). An absolute value whose kink
  is at `gap == 0` — the mate.
- `concentric`: `_radial_offset` is a Euclidean norm to a line
  (`:378-386`). Non-differentiable at offset `0` — the mate.
- `parallel`: `_folded_angle_deg` (`:372-375`) over
  `_angle_deg = degrees(acos(clamp(dot)))` (`:367-369`). The derivative of
  `acos` is `-1/sqrt(1 - u²)` and is **unbounded** as `u → ±1` — the
  Jacobian blows up precisely at a parallel mate.
- `perpendicular`: `abs(90 - folded_angle)` (`:742`), where the fold
  `min(θ, 180-θ)` kinks at θ = 90° and the outer `abs` kinks at the same
  point — the perpendicular solution.

So `geom.solve` does **not** iterate on `measured`. It iterates on a signed
or vector reformulation per component, chosen so the residual is zero exactly
where `measured` is zero, smooth in a neighbourhood of that zero, and of
bounded derivative there. `measured` remains the reported number; the
reformulation is an implementation of the same measurement, and the gate
proves it is the same rather than asserting it.

| Component | Solver residual | Dim | Identity that recovers the engine's number |
|---|---|---|---|
| `coincident` gap | signed plane gap `dot(c_b − c_a, n_a)` — **no `abs`** | 1 | `abs(r) == measured` |
| `coincident` normals | `n_a + n_b` (zero exactly when opposed) | 3 | `2·degrees(asin(clamp(‖r‖/2)))  ==  normal_deviation_deg` |
| `concentric` offset | the radial-offset **vector** `p_b − foot`, expressed in the two axes of `a`'s perpendicular frame | 2 | `‖r‖ == measured` |
| `concentric` axes | `cross(axis_a, axis_b)` | 3 | `degrees(asin(clamp(‖r‖))) == axis_angle_deg` |
| `parallel` | `cross(d_a, d_b)` (zero for parallel *and* anti-parallel, which is what folding means) | 3 | `degrees(asin(clamp(‖r‖))) == measured` |
| `perpendicular` | `dot(d_a, d_b)` — signed, smooth everywhere, zero exactly at square | 1 | `degrees(asin(clamp(abs(r)))) == measured` |

**Two more, admitted in parameter space only (13C).** `fit` and `distance`
are objective terms in 2C and nowhere else (§3.2), and each needs the same
treatment for the same reason — the engine's own number is non-smooth at
exactly its own solution:

| Component | Solver residual | Dim | Identity that recovers the engine's number |
|---|---|---|---|
| `distance` | `measured − value_mm` — signed, no `abs` | 1 | `abs(r) == deviation_mm` |
| `fit` | the signed excess outside the window: `measured − max_mm` above it, `measured − min_mm` below it, exactly `0.0` inside | 1 | `abs(r) == max(0, −slack)` |

`distance`'s engine form is `deviation_mm = abs(measured − value_mm)`
(`geom/constraints.py:650-653`), whose kink sits at the declared separation —
the solution — which is the same pathology this section exists to name.
`fit`'s bound is a **window** rather than a tolerance (`satisfied` is
`min_mm <= measured <= max_mm`, `:790-800`), so its residual is a deadband:
that is the shape the constraint actually claims, and driving to one
particular clearance inside the window would be the solver inventing an intent
the declaration does not carry. Its component bound is therefore `0.0`, and
`|excess| <= 0` is exactly the kernel's own `satisfied` — the window is not
flattened into a one-sided tolerance anywhere. The deadband's flat interior is
also why §2C's sensitivity test asks about satisfaction as well as about the
derivative.

Each identity holds for unit-normalised directions (`_unit`, `:360-365`,
already applied by `_plane_of` / `_cylinder_of` / `_direction_of`); `clamp`
is `max(-1, min(1, ·))`, the same guard `_angle_deg` applies at `:368`. Each
is a **gate clause**, asserted to 1e-9 on every fixture (Gates, G13B): if the
reformulation and the measurement ever disagree, the solver is optimising
something other than the constraint, and no amount of convergence would make
its answer evidence.

Two consequences, both normative:

- **The reformulated components are dimensionless where the engine's are
  degrees.** They are scaled into their measurement domain by the identity's
  leading factor before §3.4's weights apply, so a weight declared in `deg`
  means what it says. That factor is `180/π` for **every** angular
  component — including the coincident normal pair, where an earlier draft of
  this bullet wrote `2·180/π`. **That number was wrong** and 13A corrected it
  in the arithmetic rather than propagating it: the leading factor is the
  derivative of the identity at zero, and
  `2·degrees(asin(‖r‖/2))` differentiates to `2 · (180/π) · (1/2) = 180/π` —
  the outer `2` and the `/2` inside the `asin` cancel. Using `2·180/π` would
  make a `coincident` normal residual weigh twice its own degrees, which is
  exactly the silent normalization `COMPARE.md:34-36` forbids. G13A pins the
  corrected factor (`component_scale`, asserted against a measured
  derivative) so the prose cannot quietly pull the code back. The tolerance test is **never** applied to a reformulated component:
  tolerance is decided on the re-measured engine numbers by §7, which is the
  whole point of §7.
- **Analytic Jacobians (NW4) are Jacobians of the reformulation**, and are
  gated where the old formulation would have failed: finite-difference
  agreement is asserted at a point *within one declared tolerance of the
  solution*, not at a comfortable distance from it.

### 3.4 Weighting across units is a declared choice, never a default

A residual vector mixing mm and deg has no canonical norm. The precedent is
`COMPARE.md:34-36`: "Alignment is a declared choice, NEVER a silent
normalization." So:

- `weighting: "unit_scaled_v1" | "declared"` is **required** on every solve
  request; absent, `invalid_solve_request(undeclared_weighting)`.
- `unit_scaled_v1`: length residuals weight 1.0 per mm; angular residuals are
  multiplied by `characteristic_radius_mm * π / 180`, where
  `characteristic_radius_mm` is the maximum over free parts of the distance
  from the part's bounding-box centre to its bounding-box corner — so one
  degree of tilt costs what that tilt moves at the part's extremity. The
  computed radius is recorded in the result.
- `declared`: explicit `{"mm": w, "deg": w}` from the caller.
- **Class-predicate components carry their own weight**, not a share of the
  primary's. A `coincident` term contributes two weighted rows (one `mm`, one
  `deg`), a `concentric` term likewise; `parallel`, `perpendicular` and `fit`
  contribute one. Both class-predicate bounds are 1e-3 deg (§3.1), three
  orders tighter than a typical `tol_mm`, so folding them into one weight
  would let the tight bound dominate every step or vanish entirely depending
  on the declared numbers — which is exactly the silent normalization
  `COMPARE.md:34-36` forbids.
- Either way the applied weights are echoed in the proposal record, next to
  the residuals and per component, exactly as `ConstraintResidual.declared`
  echoes bounds (`geom/constraints.py:318-320`).

### 3.5 Regularisation is a declared choice too

`regularization: "min_norm_from_start"` is the only member in Stage 13 and is
still **required and echoed**, because §6 shows the Jacobian is rank-deficient
by construction and the choice of which null-space member to return is a
design decision, not a numerical detail. `min_norm_from_start` means: among
solutions within tolerance, return the one nearest the start iterate in the
weighted norm — "nearest to what the author already wrote", which is the only
choice that respects P4.

## 4. Solution method

### 4.1 Where it lives

- **`hephaestus.geom.solve`** — a **tenth pure geom service**, under the
  standing contract: pure functions over frames and numbers the caller
  already holds, no executor, store, project, or verdicts
  (`geom/constraints.py:6-18` states the contract; the boundary is
  mechanically enforced by the AST allowlist and import-closure test at
  `core/tests/test_geom_import_boundary.py:43-78`). It takes **extracted
  frames** — `PlanarFaceRecord` / `CylinderRecord` (`geom/topology.py:86-108`)
  — and declared bounds, and returns transforms, residuals, rank and
  null-space facts. It never sees a shape, which is why kernel-extremum kinds
  are structurally excluded from 2B (§3.2) rather than excluded by taste.
- **`hephaestus.core.placement`** — the engine half, mirroring the
  `constraints.py` ↔ `assembly.py` and `kinematics.py` ↔ `motion.py` split
  (`core/assembly.py:1-19`): anchor resolution through the shared
  `AnchorResolver` / `PartGeometry` pair (`core/assembly.py:476-573`, already
  reused by motion per `core/assembly.py:42-47`), the outcome vocabulary, the
  independent verification pass, and the proposal record.
- **`hephaestus.core.project_store.proposals`** — generational proposal
  state on the ledger pattern (`project_store/constraints.py:1-37`).

### 4.2 The iteration

Weighted Levenberg–Marquardt with a trust region, over the weighted residual
vector `r(x)` of §3:

1. **Frames once.** Anchors resolve once against current artifacts; the
   analytic kinds' records are transported under the candidate transform in
   closed form. No kernel call occurs inside a 2B iteration.
2. **Analytic Jacobian** of the §3.3 reformulation per objective component
   (NW3, NW4), assembled column-blocked by
   free variable.
3. **Rank and null space** by fixed-order Householder QR with column pivoting
   against a declared relative tolerance `RANK_TOL_REL`. If the smallest
   retained and largest discarded singular-value surrogates straddle the
   tolerance by less than `RANK_MARGIN_REL`, the solve is refused
   `rank_undecidable` — a guessed rank silently decides whether the answer is
   unique, which is the one thing §6 exists to prevent.
4. **Damped step**, clipped to the variable box (joint limits in 2A, `Param`
   bounds in 2C; 2B is unbounded unless the request declares a box).
   **Bounds are never clamped silently** — the refusal-never-clamp rule of
   `geom/kinematics.py:217-245` and `KINEMATICS.md:129-131` — a step that would
   leave the box is shortened to the boundary and the affected variables are
   reported in `bounds_active` / `limits_active` on the result, because a
   solution sitting on a bound is a boundary solution and not a stationary
   point.
5. **SO(3) validity.** Every accepted 2B iterate's rotation block is checked
   for orthonormality to `SO3_EPS` and re-projected; an iterate that cannot
   be re-projected within `SO3_REPROJECT_EPS` is the named refusal
   `non_rigid_iterate`, carrying the deviation. Nothing in the codebase
   checks this today (NW2), and a drifted iterate would produce a "transform"
   that is not a placement.
6. **Termination** on `‖weighted r‖∞ <= tol` **and** every objective
   constraint's reformulated class-predicate component inside its own
   declared bound (§3.1/§3.3) — the candidate-convergence test, which §7 then
   re-decides on the engine's `satisfied` — on `‖J^T W r‖ <=
   STATIONARITY_EPS` with residual above tolerance (over-constrained, §6), on
   the iteration ceiling, or on the wall clock (§10). The solver's
   termination test is a *candidate* test only: it never emits a verdict, and
   `‖weighted r‖∞ <= tol` alone was the earlier draft's mistake.

**No new dependency.** The linear algebra is fixed-order plain-float
arithmetic implemented in `geom.solve`. `numpy` is already a core dependency
(`core/pyproject.toml:7-17`) but its BLAS backend is threaded and
dispatch-dependent, which §9 shows would forfeit the one determinism tier
worth having; `scipy` is not a dependency and adding one is mission rule 7
territory (`mission_plan.md:1965-1969`). **The alternative that lost:
`scipy.optimize.least_squares`** — fewer lines, no reproducible digits, and a
new pinned dependency.

## 5. Initial guess, and its sensitivity

`zero: "as_built"` (`KINEMATICS.md:110-114`) makes the authored configuration
a genuinely good start: authored positions are near-solutions by discipline,
which is what makes a local method defensible and a global one unnecessary.
So `starts` defaults to the single start `as_built`.

But the interesting failures are exactly where that is false — a mate 20 mm
out because the author misread the spec puts the true solution outside the
local basin. Therefore:

- **Starts are declared and reported.** `starts` is a list; each entry is
  `as_built` or an explicit assignment. Every result names which start
  produced it (`from_start: "<id>"`), and non-convergence names **every**
  start tried.
- **No random restarts.** An RNG would break §9 and would let a rerun quietly
  change the answer. A caller who wants coverage declares more starts.
- **Sensitivity is reported, not assumed away.** When two or more declared
  starts converge to solutions differing by more than
  `SOLUTION_DISTINCT_EPS` (weighted norm), the verdict is
  `multiple_solutions_from_starts` (§6) and **all** of them are returned. The
  solver does not pick.
- **A local method's silence is never infeasibility.** The verdict name for
  failure is `no_placement_found_from_starts` — the
  `not_reached_at_samples` construction (`KINEMATICS.md:215-219`,
  `core/motion.py:1359-1378`) — and the spec forbids the spellings
  "infeasible", "impossible", and "no solution exists" anywhere in the
  result.

## 6. Convergence, non-convergence, multiplicity, and constraint count

### 6.1 The closed verdict set, stated once

Six spellings, and no others. For 2B and 2C:

1. **`converged_at_tolerance`** — never "solved". Three conjuncts, all
   required, all machine-checked:
   1. **every objective constraint re-measures `satisfied is True`** through
      the ordinary engine path (§7) — the class predicates of §3.1 included,
      which residual-within-tolerance does **not** imply for `coincident` or
      `concentric`;
   2. every weighted residual is within the declared tolerance as re-measured
      by §7;
   3. the Jacobian at the solution has full column rank at `RANK_TOL_REL`.

   Conjunct (i) is not redundant with (ii) and the spec is explicit about it
   because the earlier draft got this wrong: a zero-gap, same-facing
   `coincident` pair passes (ii) with room to spare and fails (i), and
   emitting a success verdict for it would contradict the `AssemblyStatus`
   row that still reads `violated` — P5 (§1.2), and the bench acceptance of
   §11 which grades on `satisfied` through the engine path. A solve meeting
   (ii) and (iii) but not (i) is **not** a success: it terminates
   `no_placement_found_from_starts` (verdict 4) carrying the unsatisfied
   constraint ids and their class-predicate values, because from that start
   the iteration genuinely did not reach a satisfying configuration.

   It is evidence about *this iterate from this start*, and it claims nothing
   about uniqueness beyond the local basin.
2. **`underdetermined_at_tolerance`** — conjuncts (i) and (ii) of verdict 1
   hold (every objective constraint re-measures `satisfied`, residuals within
   tolerance) but (iii) does not: the null space is non-trivial, the solution
   set is a positive-dimensional manifold, and one member is being shown.
   **This, not verdict 1, is where a single-kind 2B system lands** — a lone
   `coincident`, `concentric`, `parallel` or `perpendicular` pair is
   rank-deficient by construction, so no gate clause may demand a unique
   transform from one. Carries `dof_remaining` and a
   named basis of the free directions (translation along an axis, rotation
   about an axis, with the axis in world mm). **This is a distinct verdict,
   not a footnote on success**, because reporting one point of a continuum as
   *the* answer is a claim the mathematics does not support. Multiplicity is
   the norm here, not the exception: `concentric` leaves axial rotation *and*
   axial translation free, `coincident` leaves the whole in-plane `SE(2)`
   free, `parallel`/`perpendicular` fix two of three rotational DOF, `fit` is
   pose-invariant. A realistic 2B system is under-determined by construction.
3. **`multiple_solutions_from_starts`** — two or more declared starts
   converged to solutions separated by more than `SOLUTION_DISTINCT_EPS`.
   All are returned, ranked by weighted distance from `as_built`, none
   chosen. This is how *discrete* multiplicity surfaces — a bracket flipped
   180° about a bore satisfies `concentric` + `coincident` identically, and
   rank tells you nothing about it.
4. **`no_placement_found_from_starts`** — no declared start produced a
   configuration meeting verdict 1's conjuncts (i) and (ii), and no start
   reached stationarity. Two routes land here and the record says which: no
   start reached tolerance, or a start reached tolerance on the primary
   components while an objective constraint still re-measures
   `satisfied is False` — the class-predicate case of §3.1, whose unsatisfied
   ids and class-predicate values are carried explicitly, because "the gap is
   zero and it is still not a mate" is exactly the fact an author needs and
   the fact a residual number hides. Carries every start, the best iterate
   per start, and its independently re-measured per-constraint residuals.
   **Never "infeasible"** (§5).
5. **`overconstrained_at_residual_floor`** — a start reached a stationary
   point (`‖J^T W r‖ <= STATIONARITY_EPS`) whose weighted residual exceeds
   tolerance, with full column rank: the declared constraints disagree with
   each other over the declared free variables. Carries the per-constraint
   residuals at the floor and the floor value. It names **no culprit
   constraint**: identifying a minimal inconsistent subset is a different
   computation nobody has run, and naming one on a whim would be a verdict
   about the author's intent. It also does not claim global infeasibility —
   only that this start's basin has none.
6. **`unresolvable(reason)`** — reuse of
   `core/assembly.py:120-171`'s `UNRESOLVABLE_REASONS` verbatim, same
   failure/same fix/same name, exactly as `core/motion.py:225-249` already
   does, plus the Stage 13 additions named in §6.3.

**For 2A, six pose spellings and no others — enumerated here, not left as
"the same six with pose spellings".** An earlier draft said only that, and a
vocabulary named nowhere is not closed: G13A clauses 2, 3, 4, 5, 6 and 12
assert these by name and clauses 3 and 12 assert a *literal verdict tuple*,
which cannot be written against a set the spec never wrote down. That is the same
defect §6.3 corrects for `no_writeback_grammar`, in the verdict vocabulary
instead of the refusal one, so it is corrected the same way:

1. **`pose_converged_at_tolerance`** — the constraint-id target form. All
   three conjuncts of verdict 1 above, unchanged and in particular including
   conjunct (i): every objective constraint re-measures `satisfied is True`
   through the ordinary engine path. A 2A constraint-id solve is a solve
   against 8C constraints and gets no weaker success test than a 2B one.
2. **`pose_underdetermined_at_tolerance`** — conjuncts (i) and (ii), not
   (iii); `dof_remaining` and the named direction basis, in joint-parameter
   coordinates.
3. **`multiple_poses_from_starts`** — verdict 3's construction; all
   assignments returned, ranked by distance from `as_built`, none chosen.
4. **`no_pose_found_from_starts`** — verdict 4's construction, including its
   two routes and the class-predicate carry-out. **Never "infeasible"** (§5).
5. **`pose_overconstrained_at_residual_floor`** — verdict 5's construction,
   no culprit joint or constraint named.
6. **`unresolvable(reason)`** — verdict 6, unchanged.

Plus one asymmetry taken straight from `KINEMATICS.md:209-222`, and it is an
addition to the six rather than a member of them: an **anchor-to-point**
target is an **existence** claim, so a verified achieving assignment is
proof. Its success spelling is **`pose_found`** and its failure is
`no_pose_found_from_starts` (shared with 4). `pose_found` is emitted **only**
for anchor-to-point targets and `pose_converged_at_tolerance` **only** for
constraint-id targets; a request carrying both target forms is scored on
both and returns the constraint-id spelling, because the weaker claim may
not stand in for the stronger one. The pose verdict tuple is therefore
seven spellings — the six above plus `pose_found` — and that tuple is the
literal object G13A clause 12 asserts against.

### 6.2 Over- and under-constrained, each named

- **Under-constrained** → verdict 2 (`underdetermined_at_tolerance`), always
  with `dof_remaining` and the direction basis. Never reported as
  `converged_at_tolerance`.
- **Over-constrained but consistent** (more equations than DOF, residuals
  still within tolerance) → verdict 1. Full rank; nothing to report beyond
  the residuals.
- **Over-constrained and inconsistent** → verdict 5
  (`overconstrained_at_residual_floor`).
- **Rank not decidable** → refusal `rank_undecidable` (§4.2, step 3), which
  is not a verdict.

### 6.3 Refusals are not verdicts

`MotionTimeout` is "deliberately NOT a `SWEEP_VERDICTS` member: a killed
sweep decided nothing, and giving the kill a verdict spelling would let a
timeout be read as an outcome" (`core/motion.py:1489-1498`). Stage 13 copies
that rule exactly. The refusal set, closed, none of them a verdict:

**Request-time** (`invalid_solve_request(reason)`, nothing written):
`no_free_variables`, `no_ground_part`, `free_part_is_jointed`,
`free_part_in_no_constraint`, `undeclared_weighting`,
`undeclared_regularization`, `not_an_objective_kind(plateau|kernel_extremum|
pose_invariant)`, `pose_bound_constraint_in_transform_space`,
`unknown_constraint`, `withdrawn_constraint`, `unknown_param`,
`unbounded_param`, `unknown_joint`, `missing_provenance`,
`tolerance_below_determinism_floor` (a declared tolerance tighter than 1e-9,
the number G8C's determinism clause asserts two processes agree to —
`ASSEMBLY.md:152-153`).

**Resolution-time** (`unresolvable(reason)`): the nine
`UNRESOLVABLE_REASONS` of `core/assembly.py:161-171`, plus
`stale_proposal_inputs` (§8) and `no_free_variable_affects` (§2C).

**Run-time** (named refusals carrying the best iterate and its independently
re-measured residuals): `solver_timeout`, `iteration_ceiling`,
`build_budget_exhausted` (2C), `unbuildable_parameter_iterate` (2C — a
candidate whose preview build failed, carrying the build error),
`non_rigid_iterate`, `rank_undecidable`, and — the one that matters most —
`solver_residual_disagreement` (§7).

**Three notes on closure, because a closed vocabulary that omits a member it
elsewhere asserts is not closed.**

- **`insufficient_solve_seeds` (§11, G13C clause 55) is deliberately NOT in
  these three lists, and its absence is scoped rather than sloppy.** It is a
  *bench-harness* refusal — the `insufficient_scan_seeds` construction
  (`VALIDATION.md:67-77`) refusing to write a Tier 3 baseline from fewer than
  three seeds — raised by `bench`, never by a solve. No solve request can
  produce it, no proposal record carries it, and nothing in
  `core.placement` or `geom.solve` may emit it. The three lists above are the
  closed vocabulary of **Stage 13 solve refusals**; the bench's own
  vocabulary is closed by `VALIDATION.md`, and conflating them would make
  either set unfalsifiable. G13C clause 55 asserts the name in the bench
  payload; G13B clause 36's fourth assertion asserts it absent from every
  solve refusal tuple and every solve payload.

- `tolerance_below_determinism_floor` was spelled
  `tolerance_below_measurement_floor` in the earlier draft, and the rename is
  deliberate. 1e-9 is a *determinism* floor: it is what two processes in the
  pinned image are gated to agree to (`ASSEMBLY.md:152-153`), and nothing in
  this repo has ever measured the kernel's accuracy against ground truth.
  Calling it a measurement floor would claim a number nobody computed, and
  attach that claim to the one epsilon a reader is most likely to trust. A
  genuine measurement floor — an accuracy bound on `evaluate_residual`
  against analytically known geometry — does not exist here and Stage 13 does
  not add one (§12); if one is ever wanted it enters by mission rule 5, as
  its own gated stage with its own measurements, never by renaming this
  constant back.
- **`no_writeback_grammar` is not in any of the three lists, and that is the
  correction, not the omission.** The earlier draft asserted it as a refusal
  name in §0, §8 and a gate clause while never listing it here. It is also
  unreachable as written: `propose_placement`'s declared inputs (§11) have no
  field through which a `suggested_edit` could be requested, and every tool
  input schema in this repo is `additionalProperties: false` (57 of 57,
  re-measured 2026-08-30 with 13B's two additions —
  `set_params.schema.json:6`, `read_part.schema.json:6`,
  `compare_solids.schema.json:6`), so an extra field is rejected by JSON
  Schema validation before dispatch and produces a schema error, never a
  named Stage 13 refusal. The guarantee is kept and made *stronger* by moving
  it from a runtime name to a schema fact: §8 asserts structurally that no
  proposal record carries source text or a `suggested_edit` field, and the
  gate asserts the proposal document schema is `additionalProperties: false`
  and the tool input schemas are too. A refusal nobody can trigger is not a
  safeguard; a schema that cannot express the field is.

## 7. Independent verification: why the answer is believed

**A solved placement is never trusted because the solver said so.** This
section is the mechanical reason §1's amendment is safe, and every clause of
it is a gate clause.

0. **What is verified is a SOLVE RECORD, and 13A has one without a proposal
   store.** The two-block shape of §9 (`solver_core` + `verification`) is a
   property of every **solve record**, in all three spaces. The *proposal
   document* of §8 is the persisted, content-addressed form of a solve record
   and it lands with **13B**; 13A's `solve_pose` writes nothing at all (§0,
   §2A, §11) and carries its solve record inline in the tool result. Stating
   it the other way round — the blocks as a property of the proposal document
   — would make G13A clauses 10, 11 and 13 depend on 13B's store, which is a
   sub-gate reaching forward for machinery a later sub-stage ships, and
   `KINEMATICS.md:25-29` is the rule against exactly that. Everything below
   reads "solve record"; in 13B and 13C that record is also serialised as the
   proposal document.
1. **A separate process.** Verification runs in a fresh subprocess whose only
   input is the serialised solve record — transforms, joint assignments or
   parameter values, the bound artifact refs, the constraint generation — and
   the project store. It does not import `geom.solve`, proven by an
   import-closure assertion in the same style as
   `core/tests/test_geom_import_boundary.py:64-78`. A solver bug therefore
   cannot reach the number that is reported.

   **This has a structural consequence 13A discovered and every later
   sub-stage inherits: `hephaestus.geom.__init__` must NOT re-export
   `solve`.** The verification pass imports `hephaestus.geom` — it needs
   `evaluate_residual` and `transformed_shape` — so a package `__init__` that
   eagerly re-exported the solver would pull it into the very closure this
   clause excludes, and the exclusion would be false while every other test
   still passed. `solve` is therefore the one geom service the package does
   not re-export, and the omission IS the guarantee. A gate clause asserts
   both halves: the closure is checked inside the verification process, and
   importing the package alone is checked not to load the solver.
2. **The existing evaluator, unmodified.** Verification calls
   `hephaestus.core.assembly`'s evaluator over shapes placed by
   `geom.kinematics.transformed_shape` (`geom/kinematics.py:763-782` — a
   placed copy, never a mutation), which dispatches to
   `geom.constraints.evaluate_residual` (`geom/constraints.py:822`). It is
   the same code path that produces a real `AssemblyStatus`, and in 2C it is
   literally a preview build followed by the ordinary evaluation.
3. **All eight kinds, not the four that steered.** The plateau and
   pose-invariant kinds excluded from the objective (§3.2) are *evaluated*
   here. A proposal that satisfies four mates and drives two parts into each
   other is reported with `no_interference` violated at the solution — which
   is the honest answer and the reason those kinds are not silently dropped.
4. **`satisfied` is what the verdict is read from — not the residual
   number.** For each objective constraint the pass reads the whole
   re-measured `ConstraintResidual`: `measured`, `slack`, every entry of
   `values`, and `satisfied` (`geom/constraints.py:320-329`). Verdict 1
   requires `satisfied is True` on every one of them (§6.1). This is the
   clause that closes the gap §7.6 alone cannot: a same-facing `coincident`
   pair has a genuinely zero gap, so the solver's number and the kernel's
   number **agree perfectly** and the disagreement check below passes — the
   only thing that catches it is reading the predicate the kernel already
   evaluated. Every class-predicate value (`normal_deviation_deg`,
   `axis_angle_deg`) is recorded in the proposal beside its declared bound,
   so a reader can see which conjunct failed rather than inferring it.
5. **The solver's own numbers are discarded.** The proposal record carries the
   re-measured residuals. The solver's internal residuals are retained only
   for the disagreement check and are never the reported figure.
6. **Disagreement is fatal, not a warning.** If any re-measured residual
   differs from the solver's internal value by more than `VERIFY_EPS`, the
   whole result is refused `solver_residual_disagreement`, naming the
   constraint id and both numbers. No verdict is emitted. A solver whose
   model of the geometry has drifted from the kernel's is not producing
   evidence, and reporting its answer with a caveat would be exactly the
   overclaim this project's vocabulary exists to prevent. The comparison is
   per *component*, over the identities of §3.3: the reformulated residual is
   mapped back into the measurement domain and compared against `measured`
   and against each class-predicate value, so a reformulation bug is caught
   here and not absorbed.
7. **The `AssemblyStatus` row is untouched.** Verification produces facts
   about a *hypothetical* configuration. It does not write, project, or
   invalidate assembly status. The row keeps saying `violated`.

## 8. The proposal record: provenance, staleness, and what it may never do

A proposal is an immutable content-addressed document,
`artifact:placement-proposal:sha256:…`, in generational state on the ledger
pattern (`project_store/constraints.py:1-37`). It binds, compulsorily:

- every source part's `artifact_ref` at solve time;
- the constraint-set generation, and the joint/pose/coupling generations for
  2A;
- the full request: space, free set, ground set, starts, weighting (with the
  computed `characteristic_radius_mm`), regularisation, tolerance, iteration
  ceiling, budgets;
- the toolchain hash and the `geom.solve` version;
- **provenance on the 8C taxonomy** — a requirement id, or `assumed` with a
  reason (`ASSEMBLY.md:52-54`). A solve is an interpretation of intent for
  the same reason a constraint is;
- the verdict, the independently re-measured per-constraint residuals (§7) —
  `measured`, `slack`, `satisfied`, and every `values` entry, each beside the
  bound it was tested against, so a reader never has to re-derive
  satisfaction from a number — `dof_remaining` and the null-space basis where
  applicable, `bounds_active` / `limits_active`, `nonsmooth_terms`,
  iterations used, and `from_start`;
- the `solver_core` and `verification` blocks with their per-block
  `determinism_tier` (§9).

**The document schema is `additionalProperties: false`.** This is not a
stylistic choice: it is the mechanism by which "carries no source text" below
is a structural fact rather than a promise, and it is asserted as a gate
clause. Note that this deviates from the repo's *tool result* convention,
where no result schema closes its shape: re-measured 2026-08-30 over the 57
`schemas/tools/*.schema.json`, 35 `result` blocks state
`additionalProperties: true` and the remaining 22 omit the keyword, which
JSON Schema reads as open — so **zero of 57 results are closed**, and an
earlier draft's "all 53 result schemas are `additionalProperties: true`"
overstated a uniformity the files do not have. The direction of the deviation
is what matters and it survives the correction intact: results are open,
this artifact is closed. The proposal is a content-addressed artifact
document, not a tool result, and an artifact whose shape is open cannot be a
closed vocabulary. The gate asserts the proposal schema's own
`additionalProperties: false` and the **input** schemas', never a property of
result schemas.

**Staleness has two faces, and only one of them is a refusal.** §6.3 lists
`stale_proposal_inputs` in the resolution-time set citing this section, and an
earlier draft left it listed here but never defined — a member of a closed
vocabulary that the document names once and explains nowhere is the same
defect as a name asserted but not listed, so it is defined here.

- **`stale_proposal_inputs` (a refusal, at solve time).** A part's
  `artifact_ref` changed *between* frame extraction and the §7 verification
  pass — a concurrent build republished geometry underneath the solve. The
  run is refused by name, nothing is written, and no verdict is emitted,
  because the iterate was computed against frames that no longer describe any
  current artifact and re-measuring it would silently mix two generations.
  This is resolution-time, not run-time, for the reason `unresolvable` is:
  the fix is to rerun, not to read a number.
- **`stale: true` (a read-time fact, never a refusal).** A proposal that was
  valid when written and whose bound refs have since moved. It is reported,
  the proposal stays readable, and no verdict changes.

A proposal whose bound artifact refs no longer match the parts'
current refs is reported `stale: true` at read, naming which refs changed —
the `AssemblyProjection` staleness rule (`core/assembly.py:988-1000`) applied
by comparison at read time rather than by a stored projection.
**DECISION**: no new `ProjectionState` field. Proposals are immutable and
their inputs are already bound, so freshness is a pure function of the
current refs; adding a projection field would be a second, cache-shaped copy
of a fact that can be recomputed exactly. *The alternative that lost:* a
`SolveProjection` on the Stage 9 motion-projection precedent
(`KINEMATICS.md:148-155`) — better when status is expensive to recompute,
which this is not.

**What a proposal may never do**, each a gate clause:

- **It is never a verdict.** No tool accepts a proposal id where a constraint
  verdict is expected; the reviewer receives proposals labeled as
  computations, and `VALIDATION.md:392-396`'s rule — verdicts stamped from
  the engine, none solicited, none accepted — is unchanged.
- **It never clears anything.** The dimension-findings clearing rule verbatim
  (`VALIDATION.md:320-331`): a violated constraint clears in exactly two ways
  — a later successful build of the same part that measures otherwise, or an
  explicit operator dismissal — and there is **no model-facing write** that
  clears one.
- **It carries no source text.** The record names the part and the transform,
  decomposed into translation (mm) plus axis-angle (axis, degrees) for human
  legibility, and says nothing about which statement to edit. §0 gives the
  reason. The absence is **structural, not a refusal**: the proposal document
  schema is `additionalProperties: false` above, so no `suggested_edit` field
  can be emitted, and every tool input schema is `additionalProperties: false`
  (57 of 57), so none can be requested — an extra field is a JSON Schema
  rejection before dispatch. The earlier draft named a refusal
  (`no_writeback_grammar`) for a request the tool grammar cannot express;
  §6.3 records why that name was removed rather than kept as decoration.
- **It is never an input to a build.** Not in `input_hashes`, not readable
  from a part script, not readable from `CHECKS` (§12).

## 9. Determinism, honestly tiered

The gates already demand cross-process identity to 1e-9
(`ASSEMBLY.md:152-153`), and this repo has already been bitten by
environment-dependent float output — goldens had to be re-baselined *inside
the pinned CI image* (commits `148075f`, `f3a4d42`; the pinned-image policy
is `verification.md:76-97`). Iterative solving makes that harder, so the
claim is split.

**The tier is a property of a BLOCK, not of a solve.** The earlier draft
tiered whole solves and immediately contradicted itself: it defined D1 for
transform-space solves only, put every 2A solve in D2, and then gated a pose
solve at D1 — a byte-identity claim about digits that come out of kernel
anchor resolution, which is the one thing this section exists to refuse. The
correct seam is not 2A-versus-2B; it is **kernel-touched versus not**, and
that seam runs *through* every solve, so the **solve record** (§7.0 — the
`solve_pose` result in 13A, the proposal document in 13B/13C) carries two
blocks and each states its own tier.

- **`solver_core`** — the extracted frames the iteration consumed, the
  request, the returned iterate (joint assignment in 2A, transform rows in
  2B, parameter values in 2C), rank, `dof_remaining`, the null-space basis,
  `from_start`, iterations used.
- **`verification`** — everything §7 measured: the re-measured
  `ConstraintResidual` per constraint, `satisfied`, the class-predicate
  values, the plateau kinds' outcomes.

**Tier D1 — bit-reproducible, gated on the digits, and available only to
`solver_core`.** A solve whose iteration is kernel-free — 2A, and 2B when
every objective term is analytic (§3.2) — extracts frames once and then does
nothing but fixed-order plain-float arithmetic in `geom.solve` (§4.2).
**Given identical extracted frames**, an identical request, and the pinned
image, `solver_core` is byte-identical across processes, and the gate asserts
byte equality of its canonical JSON minus timestamps. The frames are inside
the block, not upstream of it, precisely because the claim is conditional on
them: frame extraction is a kernel call and is *not* claimed bit-stable, so a
reader comparing two `solver_core` blocks can see whether the condition held
instead of taking it on faith. Two runs whose recorded frames differ are
D2-comparable only, and the gate asserts frame equality as an explicit
precondition rather than assuming it. This is why no BLAS and no RNG are
permitted anywhere in the iteration.

**Tier D2 — not bit-reproducible, and the spec says so.** Three cases, and
the first is unconditional: **every `verification` block is D2**, in every
space including 2A, because it is kernel measurement; a 2C `solver_core` is
D2 as well (each iterate is a preview build, and OCP boolean output is not
claimed bit-stable across environments); and any `solver_core` whose recorded
frames differ from the comparison run's is D2 by the condition above. For
these the spec claims **no** stability of the returned digits. What is
reproducible, and what the gate binds to:

1. the **verdict spelling** — identical across processes;
2. the **independently re-measured residuals** (§7) — identical to within the
   declared tolerance, on the same side of it, and with identical `satisfied`
   flags (a run that flips `satisfied` has flipped the answer, tolerance or
   no tolerance);
3. the **set of active bounds/limits** and `dof_remaining`;
4. the proposal's **bound input refs** — identical, so two runs are provably
   about the same geometry.

Iteration counts, step sizes, and the returned digits themselves are
explicitly **not** gated in D2. `determinism_tier` is recorded **per block** —
`solver_core.determinism_tier ∈ {D1, D2}`, `verification.determinism_tier`
always `"D2"` — so a reader never has to infer which claim applies to which
number, and the gates assert in both directions: no `verification` block ever
claims D1, and no 2C `solver_core` does either. A `solver_trace_ref`
(iterates, damping, residual norms) is stored for replay and is evidence
about a run, never about the design.

## 10. Bounded execution

`COMPARE.md:152-176` is the pattern, and its measurement is the warning: a
single boolean ground for ~19 h on a pathological B-rep, and five of six
live-run infrastructure deaths ended on an unanswered `compare_solids`. The
Stage 13 sharpening is that **the ceiling must be per iteration, not only per
solve**, because a solve is an unbounded number of kernel evaluations.

- 2B iterations touch no kernel, so a 2B solve is bounded by
  `SOLVE_ITER_MAX` plus `SOLVE_TIMEOUT_S` (named constants,
  env-overridable on the local-floor pattern, as
  `MOTION_TIMEOUT_S` / `motion_timeout_s()` at `core/motion.py:1434-1447`).
- Every §7 verification pass — which *does* touch the kernel — runs in the
  killable subprocess under `VERIFY_TIMEOUT_S`, per pass.
- 2C additionally carries `SOLVE_BUILD_BUDGET`, a cap on **total preview
  builds across the solve's ITERATION**, and each build runs under the
  executor's existing bounds. Budget exhaustion is `build_budget_exhausted`,
  carrying the best iterate and its verified residuals.

  Two corrections 13C made in the arithmetic rather than in the prose. **A
  finite-difference gradient costs `2n` evaluations, not `1 + n`**: the driver
  is the *central* difference `geom.solve` already owns and G13B clause 19
  holds the analytic Jacobians against, and writing a second forward-difference
  one for the budget's sake would be a second implementation (mission rule 6)
  that is also less accurate exactly at the solution §3.3's whole argument is
  about. What the real cost is below both numbers is the scoping: a part
  parameter cannot change another part's geometry, so a probe of `<part>.<p>`
  rebuilds that part alone, and an evaluation at inputs already built is
  returned from the solve's own cache rather than rebuilt. **And the §7
  verification pass's builds are NOT charged to this budget**: §7 gives that
  pass its own bound (`VERIFY_TIMEOUT_S`, per pass, in a killable subprocess),
  and charging one ceiling's budget against another's would let a solve that
  spent its iteration honestly be refused for the cost of checking it. The
  record reports both counts separately.
- Every ceiling returns a **named refusal carrying partial evidence** —
  never a hang, never a silent pass, never a verdict (`core/motion.py:
  1489-1498`).
- Inside a `CHECKS` predicate: nothing. There is no solver surface in
  `CHECKS` (§12), so this class of timeout cannot reach a check report.

## 11. Surface

**Model tools: +3 (54 → 57), in two steps: 54 → 55 at 13A, 55 → 57 at 13B.**
The base is 54, not the 53 an earlier draft carried: Stage 12C's
`compare_to_scan` landed one tool, and the pins now read 54
(`contract/tests/test_toolgen.py:98-115`,
`tests/stage2/test_g2_contract_drift.py:357`). Because the pins are
`assert len(...) == N` on an *existing* suite, **each sub-stage repoints them
as it lands** — 13A to 55, 13B to 57 — or "existing suites stay green" fails
on the sub-stage that adds the tool. Tool count is a design constraint at this
size: each tool costs five generated, drift-tested artifacts, a per-profile
decision, dispatch tests on both profiles, and a `tool_schema.md` heading
under one drift gate (`contract/tests/test_toolgen.py:98-115`,
`tests/stage2/test_g2_contract_drift.py:357`). The 8A/8B lever applies — put
the capability in the script or an existing enum, not on the surface — so
2C is an **enum value on an existing tool**, not a fourth tool.

- `solve_pose(targets, free_joints?, starts?, tol, weighting, regularization,
  provenance, ceiling?)` → pose verdict + solved assignment + verified
  residuals, carried as the inline **solve record** with its `solver_core` /
  `verification` blocks and their per-block `determinism_tier` (§7.0, §9).
  It writes nothing: no proposal artifact, no pose declaration (§2A), no
  generation. **Part and orchestrator profiles**, on the 8C quartet rationale
  (`ASSEMBLY.md:105-112`): cheap, reversible, and measured against geometry the
  model did not choose.
- `propose_placement(space: "transform"|"parameters", constraints, free,
  ground?, starts?, box?, weighting, regularization, tol, provenance,
  ceiling?, build_budget?)`
  → proposal ref + verdict + verified residuals. **Orchestrator profile
  only**: it reasons across parts and spends a project-scoped build budget,
  the same rationale that makes project-scoped `set_params` and `run_checks`
  orchestrator-only (`tool_schema.md:126-132`). `space: "parameters"` is the
  13C enum extension — the `layout="nested_sheet"` precedent
  (`tool_schema.md:1409-1433`), a schema amendment rather than a new tool, and
  it **landed at 13C with the tool count unchanged at 57**. `free` carries part
  names in transform space and `Param` names (`<part>.<param>` / `hc.<param>`)
  in parameter space; `box` and `ground` are transform space's alone (a
  `Param`'s own `min`/`max` IS its box, and parameter space holds no part
  still), and `build_budget` is parameter space's alone (a transform iteration
  issues no build at all) — each refused **by name** in the other space rather
  than ignored, because a declared limit nothing spends is a limit a reader
  would believe was enforced. `budgets?` was this slot's placeholder name in the
  draft; it is spelled `build_budget` because there is exactly one budget here
  and an unnamed plural would be a field nobody could assert against.
- `read_proposals(ids?, include_documents?)` → entries + verdicts + staleness,
  **withdrawn generations included with their reasons** (the 8C read-tool
  shape: generational state is honest only if every generation stays readable,
  `KINEMATICS.md:283-288`). Both profiles. `include_documents` landed with 13B
  and defaults to `false`: an index row is what a reader normally wants, a
  proposal document is large, and asking for the whole thing should be an
  explicit act rather than the price of listing. Reading never measures and
  never re-solves. An `ids` entry nobody recorded is **refused by name**
  (`unknown_proposal`) rather than filtered away: an empty answer for a typo
  is indistinguishable from an empty answer for a project with no proposals,
  and nothing here is silently skipped.

**Operator CLI**: `heph solve pose|placement|params` and `heph proposals`
(table + `--json`), on the `heph assembly` / `heph motion` shape.

**Ladder integration** (`VALIDATION.md` §5): the termination reviewer
receives open proposals as labeled non-evidence, alongside the unchanged
`AssemblyStatus`. A violated constraint with a `converged_at_tolerance`
proposal against it is **still a blocking finding** — the proposal is a
suggestion nobody has acted on. No new blocking rule is added: Stage 13
introduces no new failure the reviewer must judge.

**Bench** (13C): a new `solve-*` task family. Acceptance is graded on the
**rebuilt part**, never on the proposal: a `proposal_requirements` entry names
constraint ids that must measure `satisfied` through the ordinary engine path
after the agent has applied a proposal by authoring it. That is the
closed-loop break made mechanical — a run cannot pass by producing a good
proposal, only by delivering geometry. `solve-*` is a **corpus family** on the
mechanism `VALIDATION.md:67-77` now states in its own right — a mechanism
that did not exist when this section was first drafted against G9C's prose
(`KINEMATICS.md:394-406`) and that supersedes it as the citation, because
Stage 11's component family and Stage 12C's `scan-*` family have since
established it: **solve-prose and solve-seeded are each their own split, each
baselined on its own first measurement with the reference model at ≥ 3 seeds,
neither compared against nor averaged into the v1/v2/v3 baselines.**
`split_name` carves family runs out **before** the aggregate is formed and
`aggregate_threshold` keys on coverage
(`bench/src/hephaestus/bench/scoring.py:282-304`), so the new family is
invisible to existing bars until its own coverage constant and threshold
land — the dilution cannot arrive through the plumbing either — and
re-baselining any combined bar is its own future amendment. Taking the family
mechanism means taking its refusal too: a first measurement thinner than
three seeds per task is refused by name (`insufficient_solve_seeds`, the
`insufficient_scan_seeds` construction) rather than written as a baseline.
Each task ships prose + seeded variants (`VALIDATION.md:33-56`), dual
independent solutions (`VALIDATION.md:163-167`), and hand-counted budgets on
the calibration formula (`VALIDATION.md:510-516`).

## 12. What deliberately does NOT change

No script syntax: parts declare no solve, `PARAMS`/`hc` are untouched, no new
`part.*` field. **No `CHECKS` surface** — the measurement facade gains
nothing, in either scope; a predicate that could read a proposal would let an
acceptance check pass on a computation instead of on geometry, which is
`VALIDATION.md:127-134` inverted. No new persistence beyond the ledger-pattern
proposal set (no `ProjectionState` field, §8). No change to `AssemblyStatus`,
`MotionStatus`, or any wire shape either produces — 8C and Stage 9 evidence
stays byte-for-byte valid. No change to `check_assembly` or `check_motion`
semantics. No change to `edit_part` / `write_part` / `set_params`: no force
overwrite appears, and no tool applies a proposal. No change to export —
`as_built` is still what a script built, never a proposed placement. No
dynamics, loads, FEA, or motor sizing (`mission_plan.md:1957-1959`). No new
runtime dependency (§4.2). **No measurement floor**: Stage 13 does not
measure `evaluate_residual`'s accuracy against analytically known geometry
and does not claim one exists; the only 1e-9 **constant Stage 13 declares** is
the determinism floor G8C already asserts (§6.3), and every *other* 1e-9 in
this document is a gate clause naming a pure-function claim — the §3.3
identities and G13A's `forward_kinematics` clause — never a solved quantity.
An earlier draft of this sentence said "the only 1e-9 in this document",
which its own next clause contradicted. No new
sandbox profile: nothing here shells out to
an external binary, so the executor seam (`core/src/hephaestus/core/executor/`)
is untouched — a future external solver binary would re-engage mission rules
6 and 7 and is out of scope. No global optimisation, no random restarts, no
mesh path, no feature recognition. Ball, planar and gear joints remain absent
(`KINEMATICS.md:107-109`), so 2A's variable set is the Stage 9 kind set.

## 13. NAMED NEW WORK

Nothing in this list exists today. Anything not listed here is a claim that it
already exists.

**Mathematics and `geom.solve` (the tenth pure service)**

1. **Transform → parameters** — a log map / rigid decomposition
   (translation + axis-angle) for reporting and for `min_norm_from_start`.
   `geom/kinematics.py` is forward-only (`:491-556`); there is no inverse.
2. **`SO(3)` validity and re-projection** — orthonormality check to
   `SO3_EPS`, re-projection, and the `non_rigid_iterate` refusal. Nothing in
   the repo checks a `RigidTransform`'s rotation block today
   (`geom/kinematics.py:423-448` is a raw 3×4 dataclass).
3. **The residual reformulation of §3.3 and its identities** — the signed
   plane gap, the radial-offset vector in the axis's perpendicular frame, the
   normal-sum vector, and the two cross/dot angular forms, each with the
   closed-form map back into the engine's measurement domain. None of these
   exist: `geom/constraints.py` computes the `abs`/`acos`/norm forms and
   nothing else.
4. **Analytic Jacobians of the reformulation** (not of `measured`) for
   `coincident`, `concentric`, `parallel`, `perpendicular` with respect to
   `SE(3)` — including the class-predicate rows, which are new objective
   components, not existing ones — and the closed-form transport of
   `PlanarFaceRecord` / `CylinderRecord` under a candidate transform
   (`geom/topology.py:86-108` records exist; transporting them does not).
5. **Weighted residual assembly** across mm/mm³/deg, per *component* rather
   than per constraint (§3.4), with the `unit_scaled_v1` characteristic-radius
   computation and the `declared` mode.
6. **Fixed-order Householder QR with column pivoting**, rank determination
   against `RANK_TOL_REL`, and the `rank_undecidable` straddle refusal.
7. **Null-space basis extraction and naming** — turning basis vectors into
   human-readable free directions ("translation along [0,0,1] through
   (12.0, 0.0, 4.5)").
8. **Damped least squares with a trust region**, `min_norm_from_start`
   regularisation, and the box-clipping step with `bounds_active` /
   `limits_active` reporting (no clamping — `geom/kinematics.py:217-245`).
9. **Stationarity detection** (`‖J^T W r‖`) to distinguish verdict 5 from
   verdict 4.
10. **Solution-distinctness comparison** in the weighted norm
    (`SOLUTION_DISTINCT_EPS`) for `multiple_solutions_from_starts`.
11. **Finite-difference driver for 2C**, including the per-constraint
    sensitivity test that produces `no_free_variable_affects`.

**Engine (`hephaestus.core.placement`)**

12. **The solve-request grammar and its request-time refusal set** (§6.3),
    including `free_part_is_jointed`,
    `pose_bound_constraint_in_transform_space`,
    `not_an_objective_kind(reason)`, and
    `tolerance_below_determinism_floor`.
13. **Ground/free-set semantics** — parts partitioned into free and ground,
    `no_ground_part`.
14. **The frame-extraction-once pipeline** over the shared `AnchorResolver` /
    `PartGeometry` (`core/assembly.py:476-573`), producing the analytic
    records `geom.solve` consumes.
15. **The independent verification pass** (§7): separate process, its
    import-closure assertion, the all-eight-kinds evaluation, the
    **satisfaction read** (`ConstraintResidual.satisfied` plus every
    class-predicate `values` entry beside its declared bound, §7.4), the
    per-component disagreement comparison over the §3.3 identities, and the
    `solver_residual_disagreement` refusal.
16. **The verdict and refusal vocabularies** (§6): the six transform/parameter
    spellings, and the pose-space tuple of **seven** — the six pose spellings
    (`pose_converged_at_tolerance`, `pose_underdetermined_at_tolerance`,
    `multiple_poses_from_starts`, `no_pose_found_from_starts`,
    `pose_overconstrained_at_residual_floor`, `unresolvable`) plus
    `pose_found` for the anchor-to-point existence claim, each a literal
    tuple a gate can assert against.
17. **Bounded execution**: `SOLVE_ITER_MAX`, `SOLVE_TIMEOUT_S`,
    `VERIFY_TIMEOUT_S`, `SOLVE_BUILD_BUDGET`, each env-overridable on the
    local-floor pattern, with partial-evidence refusals.
18. **The 2C preview-build driver** — issuing transient-override builds,
    reading residuals through the ordinary evaluation, and
    `unbuildable_parameter_iterate`.
19. **Per-block determinism tiering** (§9): the `solver_core` /
    `verification` split of the **solve record** (§7.0 — inline in 13A's
    `solve_pose` result, serialised as the proposal document from 13B on,
    so no G13A clause reaches forward into 13B's store), the recorded extracted
    frames that make the D1 claim conditional and checkable, per-block
    `determinism_tier`, and the `solver_trace_ref` trace record.

**Store, surface, evidence**

20. **`project_store.proposals`** — generational proposal state, the
    `artifact:placement-proposal:sha256:…` document, its
    `additionalProperties: false` JSON Schema (§8 — a deviation from the tool
    result convention, deliberate and gated), canonical JSON serialisation,
    and GC edges keeping a stale proposal readable.
21. **Read-time staleness** by comparing bound refs to current refs (§8).
22. **Three tools** (`solve_pose`, `propose_placement`, `read_proposals`),
    their five generated artifacts each, profile rows, dispatch tests, and
    the pins repointed **per sub-stage** — 54 → 55 at 13A, 55 → 57 at 13B
    (`contract/tests/test_toolgen.py:98-115`,
    `tests/stage2/test_g2_contract_drift.py:357`).
23. **CLI**: `heph solve pose|placement|params`, `heph proposals`, human and
    `--json`.
24. **Reviewer context extension**: proposals delivered as labeled
    non-evidence, with the proof that they clear nothing.
25. **Geom boundary admission**: `solve` added to the AST allowlist and
    import-closure suites (`core/tests/test_geom_import_boundary.py:43-78`).
26. **Hand-computable fixtures** for every analytic Jacobian and for each
    verdict — including a deliberately under-determined system with a known
    null-space dimension, a flipped-bracket discrete-multiplicity fixture, a
    provably inconsistent over-constrained fixture, a **full-column-rank**
    fixture per analytic kind (a lone mate of any of the four kinds is
    rank-deficient by construction, §6.1 verdict 2, so a unique hand-computed
    transform does not exist for one), and a **zero-gap same-facing
    `coincident`** fixture for the class-predicate clause. With them, the
    three gate-only constants `TRANSFORM_MATCH_EPS`, `PARAM_MATCH_EPS` and
    `JACOBIAN_FD_EPS` (§ Gates), their two declared factors, and the recorded
    per-fixture conditioning number `kappa` the first two are derived from.
27. **The `tool_schema.md` / `ASSEMBLY.md` sub-stage drift gate** — asserting
    at the sub-stage that adds a heading, not one later, that no un-scoped
    "There is no solver." survives alongside a `solve_pose` heading and that
    every declared tool name has a normative heading (the
    `tests/stage2/test_g2_contract_drift.py:270-305` shape, re-run at 13A).
28. **Bench**: the `solve-*` family, its `proposal_requirements` acceptance
    vocabulary and grader half, its coverage constant and its own splits, and
    dual independent solutions per task.
29. **The `mission_plan.md` Stage 13 amendment itself**, and the six document
    amendments of the manifest. The plan amendment **carries the writeback
    refusal in its own words**, not by citing this document: the operator's
    2026-08-29 direction was explicitly that the refusal live in the plan's
    text, and a rule that exists only in the spec it constrains is a rule
    with one reader. The plan's Stage 13 heading therefore states, in the
    plan, that the solver proposes; that its output is a measurement artifact
    nothing applies; that applying a proposal stays an authoring act through
    the ordinary edit path; and that **writeback is refused** — no inverse
    from a transform to a script expression is computed, offered or guessed
    (§0, §8). G13A clause 14 asserts that text present.

## Gates

Stage 13 lands in three gated sub-stages, strictly ordered. Every clause below
is a pytest assertion; a clause that cannot be written as one is a defect in
this document to be fixed by tightening it, never by waiving it (mission rule
1, `mission_plan.md:1943-1946`).

**Four epsilons exist only for these gates (three from the start and a fourth
measured at 13B), and they exist because an earlier
draft demanded 1e-9 of quantities no part of this spec drives to 1e-9.** A
gate clause may assert 1e-9 of a **pure function evaluated at fixed given
inputs** — `forward_kinematics` at declared joint values, a §3.3 identity —
because that is arithmetic with no iteration in it, and it is the claim
`ASSEMBLY.md:152-153` and `KINEMATICS.md:353-355` already make. A gate clause may
**never** assert 1e-9 of a *solved* quantity: the solver terminates on the
declared tolerance (§4.2 step 6), a tolerance tighter than 1e-9 is refused
`tolerance_below_determinism_floor` (§6.3), and demanding accuracy a
termination rule cannot deliver is a clause nobody can write — the defect
mission rule 1 says to fix by tightening, which is what these two constants
do.

- **`TRANSFORM_MATCH_EPS`** — how far a returned transform may sit from a
  hand-computed one. Per fixture: `tol * TRANSFORM_MATCH_FACTOR * kappa`,
  where `kappa` is that fixture's condition number of the weighted Jacobian
  at the solution, recorded in the fixture beside its hand-computed answer,
  and `TRANSFORM_MATCH_FACTOR` is a declared constant. Residual accuracy and
  *solution* accuracy are different quantities related by the conditioning,
  and the gate says which one it is asserting.

  **"Recorded in the fixture" is load-bearing, and 2026-09-01 tightened it
  into the two assertions it always implied.** An independent verifier found
  both epsilons deriving `kappa` from the record — the solver's own reported
  conditioning — with nothing pinning it, so a solver reporting an inflated
  number would have widened the tolerance it was being graded against and the
  gate would have stayed green. It was ~700x from vacuous in the shipped tree
  and would have gone undetected if it moved, which is the definition of a
  gate that is not asserting what it says. So: the epsilon is derived from the
  **fixture's recorded** number, and the solver's reported number is
  separately **held to** that recording within a declared relative band
  (`KAPPA_MATCH_REL`). The band may not be 1e-9 and is not: `kappa` comes off
  a *solved* iterate, which this preamble's own rule forbids asserting to
  1e-9. Both recordings are arithmetic rather than transcribed decimals —
  13B's is `12/π` (three-mate fixtures) and `6√2/π` (the four-mate one), 13C's
  is exactly `2` — each derived in its fixture from the part dimensions and
  the `unit_scaled_v1` weights, so the recording is a hand-computation the
  same way the answer beside it is.
- **`PARAM_MATCH_EPS`** — `TRANSFORM_MATCH_EPS`'s parameter-space analogue,
  used only by G13C clause 44: `tol * PARAM_MATCH_FACTOR * kappa` over the
  same recorded per-fixture conditioning, in the declared units of each
  `Param`. It is named here rather than left as "the parameter-space
  analogue" because a gate clause cannot assert against an unnamed constant,
  and an unnamed third epsilon inside a section whose first word was "Two"
  is the vocabulary-closure defect §6.3 corrects elsewhere.
- **`JACOBIAN_FD_EPS`** — relative agreement between an analytic Jacobian
  column and a central finite difference of the same reformulated residual.
- **`ACOS_CONDITIONING_EPS_DEG`** — a fourth, added at 13B and confined to one
  clause: how far an ANGULAR §3.3 identity may sit from the engine's own
  number *at a solution*, where 1e-9 is unreachable because
  `degrees(acos(clamp(dot)))` has lost the digits (clause 19 records the
  measurement and the derivation). It is not a fifth epsilon by the back door:
  it applies to no other comparison, it is asserted to stay three orders below
  the tightest bound any design declares, and the length identities keep the
  1e-9 unchanged.

### Gate G13A — pose solving

`uv run pytest tests/stage13a -q` exits 0, covering:

1. **Forward kinematics, as a pure function.** `forward_kinematics` at
   *fixed given* joint values reproduces the hand-computed transform of a
   two-revolute chain to **1e-9**, with no solver anywhere in the call — the
   G9A clause shape (`KINEMATICS.md:353-355`) restated so this suite owns it.
   This is the only 1e-9 in G13A and it is a claim about arithmetic.
2. **Inverse kinematics, as a solve — BOTH target forms, because 13A ships
   both.** (a) *Anchor-to-point.* On that same chain: the verdict is
   `pose_found`, and the target error **re-measured by §7 through
   `core.motion`'s resolution path** is `<= tol` — the declared tolerance,
   which is the number the solver actually drove. The clause asserts `<=
   tol`, never 1e-9, and asserts that the record reports the re-measured
   error rather than the solver's internal one. (b) *Constraint-id.* A pose
   solve whose target is a declared 8C constraint id returns
   `pose_converged_at_tolerance`, and **conjunct (i) is asserted
   independently**: the constraint re-measures `satisfied is True` through
   the ordinary `core.assembly` engine path, class predicates included, with
   every `values` entry recorded beside its declared bound. The
   class-predicate negative is asserted here too, in pose space: a target
   `coincident` reachable to zero gap only with same-facing normals returns
   `no_pose_found_from_starts`, not a success, with `satisfied == False` and
   `normal_deviation_deg` near 180 in the record. **This clause is not
   optional and not deferrable to 13B.** The constraint-id form is the sole
   reason the `ASSEMBLY.md` §1 amendment lands at 13A rather than 13B (§0,
   §2A, Amendment manifest); a G13A that amends the no-solver rule for a
   capability no clause exercises would buy the amendment on credit. (c)
   `pose_overconstrained_at_residual_floor` on two pose-space constraint ids
   that a two-revolute chain cannot satisfy together, with stationarity
   asserted and no culprit named.
3. The pose verdict tuple of §6.1 asserted **verbatim and complete** — the
   six pose spellings plus `pose_found`, seven and no more — with
   `pose_found` emitted only for anchor-to-point targets and
   `pose_converged_at_tolerance` only for constraint-id ones; the strings
   "solved", "infeasible" and "holds" appear nowhere in any result payload.
4. `no_pose_found_from_starts` on an out-of-reach target, carrying every
   declared start and the closest miss distance — and **not** spelled
   `violated`.
5. A redundant chain (3 joints, 2-DOF target) returns
   `pose_underdetermined_at_tolerance` with `dof_remaining == 1` and a named
   direction basis.
6. Two declared starts converging to elbow-up and elbow-down return
   `multiple_poses_from_starts` with both assignments, ranked by distance
   from `as_built`, and neither marked chosen.
7. A target reachable only past a declared limit returns
   `no_pose_found_from_starts` with the limiting joint in `limits_active`;
   the returned assignment is inside limits and no value is clamped
   (`geom/kinematics.py:217-245`).
8. Every request-time refusal in §6.3 reachable from pose space fires by
   name with nothing written: `no_free_variables`, `unknown_joint`,
   `missing_provenance`, `undeclared_weighting`, `undeclared_regularization`,
   `tolerance_below_determinism_floor` — the last on a request declaring
   `tol` below 1e-9, with the superseded spelling
   `tolerance_below_measurement_floor` asserted absent from the source tree
   and from every payload.
9. `rank_undecidable` on a fixture constructed to straddle `RANK_TOL_REL`.
10. Independent verification: the solved assignment's target error is
    re-measured through `core.motion`'s resolution path in a separate
    process; an injected solver-side residual error produces
    `solver_residual_disagreement` and **no verdict**.
11. Import-closure assertion: the verification process's closure excludes
    `hephaestus.geom.solve`.
12. `solver_timeout` and `iteration_ceiling` are named refusals carrying the
    best iterate and its verified residuals, and are absent from the verdict
    set (asserted against the literal verdict tuple).
13. **Determinism, per block (§9), and the negative in both directions.** Two
    processes solve the same request. The recorded extracted frames are
    asserted **equal** first, as the explicit precondition of the D1 claim;
    then `solver_core` is byte-identical as canonical JSON minus timestamps,
    and `solver_core.determinism_tier == "D1"`. The `verification` block is
    **not** byte-compared: it is held to the four D2 bindings of §9 —
    identical verdict spelling, re-measured residuals within tolerance and on
    the same side of it with identical `satisfied` flags, identical
    `limits_active` and `dof_remaining`, identical bound input refs — and
    carries `determinism_tier == "D2"`. The test asserts that **no**
    `verification` block in any record claims `"D1"`, so the negative
    assertion lands with the first record that carries a tier rather than two
    sub-stages later.
14. **Amendment drift, asserted at the sub-stage that ships the heading.**
    With 13A's amendments landed: `tool_schema.md` contains a `solve_pose`
    heading **and** no un-scoped sentence "There is no solver." (the
    `check_assembly` occurrence at `tool_schema.md:911` now reads the amended
    `ASSEMBLY.md` §1 wording); every name in `TOOL_NAMES` has a matching
    normative heading with a parseable signature block (the
    `tests/stage2/test_g2_contract_drift.py:270-305` shape, re-run here);
    `ASSEMBLY.md` §1's last bullet is titled `NO SOLVER MOVES GEOMETRY` and
    carries the amended text verbatim; `KINEMATICS.md` §0's first bullet
    carries the Stage 13 sentence; and `docs/cli.md`'s `heph joints` section
    carries **no** un-scoped "no solver" beside a shipped `heph solve` verb
    (Amendment manifest) — the same pair-assertion as the `tool_schema.md` one,
    in the operator-facing document, since a CLI reference that denies a verb
    it documents is the same defect in a different file. The tool-count pins
    are repointed 54 → 55
    (`contract/tests/test_toolgen.py:98-115`,
    `tests/stage2/test_g2_contract_drift.py:357`) — 13A adds a tool, so the
    existing `assert len(...) == 54` fails here unless it moves, and clause
    17's "existing suites stay green" is what would otherwise catch it late.
    `mission_plan.md`'s Stage 13 heading carries the **writeback refusal in
    the plan's own words** (NAMED NEW WORK 29) — asserted as text present in
    `mission_plan.md`, not as a citation of this file, because that is what
    the operator directed on 2026-08-29 and a gate that accepted a pointer
    would let the plan say nothing. **And the plan's own G13A gate summary
    carries clause 17's delta, not the absolute it superseded** — the delta
    named (`tests/stage9a` and `tests/stage9b` untouched, `tests/stage9c`'s
    corpus-count pin repointed 23 → 25), and every occurrence of the string
    "`tests/stage9a`–`stage9c` unchanged" anywhere in `mission_plan.md`
    quoted, so it survives only as the dated record of what was replaced and
    never again as a live claim. *Added 2026-09-01 under mission rule 1, and
    it is the clause closing on itself:* clause 17's tightening landed in this
    file and in the plan's closure record while the plan's **own** gate
    summary still restated the false absolute hundreds of lines away, because clause
    14 asserted only the writeback refusal in `mission_plan.md` and the plan's
    gate summaries were asserted by nothing. That is precisely the shape the
    last sentence of this clause forbids, surviving in the one document the
    repair did not reach; the summaries are now inside the assertion. And the
    citation audit of the Amendment
    manifest runs, **both halves**: every `file:line` citation in `SOLVER.md`
    resolves by range inside the file it names, and every citation in the
    manifest's **anchor register** resolves to text containing its registered
    anchor — with the asserted list held equal to the register itself, so a
    register row this suite does not check is a red gate rather than a silent
    omission. (The anchor half was scoped to the register on 2026-09-01; the
    manifest records why, and 13B and 13C run the identical pair.) A passing
    G13A therefore cannot leave a normative document contradicting the
    machinery the same sub-stage shipped.
15. `solve_pose` through dispatch on both profiles; the solved assignment is
    returned and **no pose is declared** as a side effect (pose-set
    generation unchanged).
16. `heph solve pose` human and `--json`.
17. Existing suites stay green; **Stage 13 leaves `tests/stage9a` and
    `tests/stage9b` untouched, and its only edit anywhere under
    `tests/stage9c` is the corpus-count pin G13C clause 54 repoints, 23 → 25,
    carrying this stage's citation**; the geom boundary suites admit `solve`
    as a pure service.

    **Tightened 2026-09-01, under mission rule 1
    (`mission_plan.md:1943-1946`), and the tightening is the whole point.**
    This clause read "`tests/stage9a`–`stage9c` unchanged". The shipped tree
    contradicts it: 13C's corpus family adds two public tasks, so stage9c's
    count pin had to move with them or "existing suites stay green" — the
    conjunct immediately before it — would have failed on the sub-stage that
    added them. Worse, **no clause asserted the sentence at all**, so a
    passing G13A coexisted with a normative sentence its own tree denied,
    which is exactly the drift shape clause 14 exists to catch, arriving in
    the gate text instead of in a citation. The absolute was both false and
    unassertable; the delta is neither, and G13A now asserts it: nothing under
    `tests/stage9a` or `tests/stage9b` mentions this stage at all, and the one
    file under `tests/stage9c` that does mentions it only at the repointed
    pin, whose number is held equal to the public corpus on disk. Nothing was
    deleted and nothing was relaxed — the clause now says what the tree does,
    and a gate now says it too.

### Gate G13B — placement proposal, transform space

`uv run pytest tests/stage13b -q` exits 0, covering:

18. **Each analytic objective kind on a FULL-COLUMN-RANK fixture.** For
    `coincident`, `concentric`, `parallel`, `perpendicular`: a fixture built
    from the kind under test plus enough further analytic constraints to
    remove the null space entirely, so a unique answer exists to hand-compute
    at all. The clause asserts, in order: the rank at the solution is full
    (asserted explicitly, not inferred from the verdict); the verdict is
    `converged_at_tolerance`; **`satisfied is True` for every objective
    constraint** as re-measured by §7, class predicates included; the
    verified residual is `<= tol`; and the returned transform matches the
    hand-computed one to `TRANSFORM_MATCH_EPS`, with the fixture's recorded
    `kappa`. A lone mate of any of these four kinds is rank-deficient by
    construction (§6.1 verdict 2) and is asserted in clause 23 instead — no
    clause anywhere demands a unique transform from a positive-dimensional
    solution set.
19. **The reformulation is the same measurement, and its Jacobian is right
    where it matters (§3.3).** For every fixture and every objective
    component: the reformulated residual mapped back through its stated
    identity reproduces the engine's `measured` or class-predicate value to
    **1e-9** — a pure-function claim over fixed inputs, the only kind of 1e-9
    this gate permits. And: each analytic Jacobian column agrees with a
    central finite difference of the same reformulated residual to
    `JACOBIAN_FD_EPS`, evaluated at a point **within one declared tolerance
    of the solution** — the neighbourhood where the `abs` / `acos` / norm
    forms of `geom/constraints.py` are non-smooth or unbounded, and therefore
    the neighbourhood where a clause evaluated at a comfortable distance
    would have proved nothing.

    **Measured at 13B, and the clause is split rather than waived.** The 1e-9
    holds verbatim for every *length* component (`abs`, `norm`) both at the
    solution and away from it, and for every *angular* component at a
    well-conditioned configuration. It does **not** hold for an angular
    component *at* the solution, and the reason is the pathology this section
    exists to name, arriving from the other side: the engine's number comes
    from `degrees(acos(clamp(dot)))`, whose derivative is unbounded as
    `dot → ±1`, so one ulp of `dot` becomes `ulp / sin θ` of angle. G13B
    measured **1.2e-8 deg** at its tightest fixture (θ ≈ 3e-5 deg). What that
    measures is the ENGINE's remaining precision, not the identity's — the
    reformulation has no such amplification, which is exactly why §3.3
    replaces the `acos` form for the iteration. The gate therefore declares
    `ACOS_CONDITIONING_EPS_DEG = 1e-6` for that one case, two orders above the
    worst observation and asserted to stay three orders **below** the tightest
    class-predicate bound any design declares (1e-3 deg), so the comparison
    cannot go vacuous. Demanding 1e-9 there would be demanding of `acos` an
    accuracy nobody measured, which is the defect the
    `tolerance_below_determinism_floor` rename corrects elsewhere in this
    document.
20. **A class predicate is not a footnote: the negative fixture.** A
    `coincident` pair whose gap is exactly zero with **same-facing** normals
    does **not** return `converged_at_tolerance`. The record shows
    `satisfied == False`, `normal_deviation_deg` near 180, and the declared
    `normal_eps_deg` beside it; the verdict is `no_placement_found_from_starts`
    when no free DOF can flip the part. **"No free DOF can flip the part" is
    expressible in transform space only through the declared box** of §4.2
    step 4 ("2B is unbounded unless the request declares a box"), since every
    free part otherwise carries all six degrees of freedom; 13B therefore
    ships that box, the negative pins the three rotational variables, and the
    pinned variables come back in `bounds_active` rather than being clamped in
    silence. The mirror positive is asserted in the
    same test: given a free rotational DOF, the solver flips the part and
    returns `converged_at_tolerance` with `satisfied is True` — proving the
    class predicate steers the iteration (§3.1) rather than only failing it at
    verification. The `concentric` analogue is asserted alongside: zero radial
    offset with axes tilted beyond `axis_eps_deg` is not a success.
21. `not_an_objective_kind` fires with reason `plateau` for `clearance_min`
    and `no_interference`, `pose_invariant` for `fit`, and `kernel_extremum`
    for `distance` — each asserted with its reason string, nothing written.
22. Those excluded kinds are nevertheless **evaluated at the solution**: a
    fixture whose four analytic mates are satisfiable only by driving two
    solids into each other returns `converged_at_tolerance` — with all four
    objective constraints re-measuring `satisfied is True` — and
    `no_interference` violated in the verification block.
23. **`underdetermined_at_tolerance` is where the rank-deficient single-kind
    systems land.** A single `concentric` pair: `dof_remaining == 2`, and the
    basis names axial translation and axial rotation about the measured axis.
    A single `coincident` pair: `dof_remaining == 3`, the in-plane `SE(2)`
    basis named. Each asserts `satisfied is True` at the returned member and
    the verified residual `<= tol`, and neither asserts a unique transform.
24. `multiple_solutions_from_starts` on the 180°-flip bracket fixture; all
    solutions returned, none chosen.
25. `overconstrained_at_residual_floor` on a provably inconsistent pair, with
    stationarity asserted, per-constraint residuals at the floor attached,
    and **no culprit constraint named** (asserted as an absent field).
26. `no_placement_found_from_starts` from a deliberately distant start, with
    every start listed; the words "infeasible"/"no solution" absent from the
    payload.
27. `no_ground_part`, `free_part_is_jointed`,
    `pose_bound_constraint_in_transform_space`, `free_part_in_no_constraint`,
    `unknown_constraint`, `withdrawn_constraint` each fire by name with
    nothing written.
28. `non_rigid_iterate` under a fault-injected rotation-block perturbation
    beyond `SO3_REPROJECT_EPS`.
29. Weighting: the same system under `unit_scaled_v1` and under two different
    `declared` weight pairs returns different solutions, each echoing its
    applied weights **per component** — a `coincident` term echoes two, one
    `mm` and one `deg` (§3.4) — and (for `unit_scaled_v1`) the computed
    `characteristic_radius_mm`; a request omitting `weighting` is refused.
30. Regularisation is echoed; a request omitting it is refused
    `undeclared_regularization`.
31. Independent verification (§7): separate process, import-closure
    assertion, all-eight-kind evaluation, the satisfaction read (§7.4 — every
    `values` entry recorded beside its declared bound), and a fault-injected
    internal residual producing `solver_residual_disagreement` with both
    numbers and no verdict.
32. **The proposal is not a verdict**: after a `converged_at_tolerance`
    proposal against a violated constraint, `check_assembly` still reports
    that constraint `violated`, the assembly projection is unchanged, and no
    tool accepts the proposal id where a constraint id is expected.
33. **The proposal clears nothing**: the FakeModel reviewer harness produces
    the blocking finding for the violated constraint with the converged
    proposal present, and no model-facing write clears it
    (`VALIDATION.md:320-331`).
34. Proposal provenance: the record binds every source `artifact_ref`, the
    constraint generation, the toolchain hash and the request; a proposal
    with neither a requirement id nor `assumed` is refused
    `missing_provenance`.
35. Staleness: rebuilding a bound part makes `read_proposals` report
    `stale: true` naming the changed ref; the proposal stays readable.
36. **No writeback, asserted structurally rather than by a refusal name.**
    Three assertions, no runtime trigger among them: (i) the proposal record
    contains no source text and no `suggested_edit` field, asserted against
    the canonical proposal document schema; (ii) that schema is
    `additionalProperties: false`, so the field cannot appear whatever an
    implementer adds; (iii) all 57 tool input schemas are
    `additionalProperties: false` (`schemas/tools/*.schema.json`), so the
    field cannot be requested either — an extra key is a schema rejection
    before dispatch. A fourth clause keeps the vocabulary closed **in both
    directions**, asserted against the literal request-time / resolution-time
    / run-time tuples of §6.3: (a) every name those three tuples contain is
    reachable and is exercised by some clause of G13A–G13C, so the set has no
    decorative member — `stale_proposal_inputs` included, on the concurrent-
    rebuild fixture of §8; and (b) the strings `no_writeback_grammar` and
    `insufficient_solve_seeds` appear in no solve refusal tuple and in no
    solve payload, so the set has no member the document asserts but does not
    list, and no bench name leaks into the solve vocabulary.
37. Determinism for an all-analytic 2B solve, per block (§9): recorded frames
    asserted equal, `solver_core` byte-identical as canonical JSON minus
    timestamps with `determinism_tier == "D1"`, the `verification` block held
    to the four D2 bindings and carrying `determinism_tier == "D2"`, and no
    `verification` block claiming D1.
38. Bounded execution: `SOLVE_ITER_MAX` and `SOLVE_TIMEOUT_S` produce named
    refusals carrying the best iterate and its verified residuals; the
    verification subprocess is dead after `VERIFY_TIMEOUT_S`; neither
    spelling is in the verdict tuple.
39. `propose_placement` is refused on the part profile and dispatches on the
    orchestrator profile; `read_proposals` dispatches on both and returns
    withdrawn generations with their reasons.
40. Tool-count pins repointed **55 → 57** with this stage cited (13A already
    took 54 → 55, §11), and the five generated artifacts drift-clean
    (`contract/tests/test_toolgen.py:98-115`,
    `tests/stage2/test_g2_contract_drift.py:357`); the clause-14 heading gate
    re-runs over the 13B headings. `propose_placement`'s `space` enum at 13B
    admits **`"transform"` only** — `"parameters"` is 13C's extension
    (clause 51), so a 13B schema already listing it would make that clause
    vacuous, and this clause asserts the 13B enum is the one-member one.
41. `heph solve placement` and `heph proposals`, human and `--json`.
42. Reviewer context carries proposals labeled as non-evidence; no verdict is
    solicited or accepted for a proposal id.
43. Existing suites stay green; 8C and Stage 9 wire shapes byte-for-byte
    unchanged, asserted against recorded evidence.

### Gate G13C — parameter space, and the bench

`uv run pytest tests/stage13c -q` exits 0, covering:

44. A parameter solve over a two-`Param` fixture reaches a hand-computed
    optimum — the parameter values asserted to `PARAM_MATCH_EPS`
    (§ Gates), derived from the same declared tolerance and the fixture's
    recorded conditioning, never to 1e-9; `fit` and `distance` are admitted
    as objective terms here and `fit`'s admission is asserted against 13B's
    refusal of the same kind (the difference being pose- versus
    parameter-invariance).
45. `nonsmooth_terms` lists every `distance` term in the result, and the
    record states the local-model caveat.
46. Every candidate build is a preview: `current == false` on every build the
    solve issued, the parts' current artifact refs are unchanged afterwards,
    and no parameter override is persisted (project param state hash
    unchanged).
47. `no_free_variable_affects` on a constraint insensitive to every free
    parameter, naming the constraint id.
48. `unknown_param`, `unbounded_param` refused by name; a solve never
    proposes a value outside a declared `min`/`max`, and a solution on a
    bound reports it in `bounds_active`.
49. `unbuildable_parameter_iterate` carrying the build error when a candidate
    fails to build; `build_budget_exhausted` carrying the best iterate and
    its verified residuals.
50. Determinism D2 in **both** blocks across two processes: a 2C
    `solver_core` carries `determinism_tier == "D2"` (its iterates are
    preview builds), the `verification` block carries `"D2"`, and all four
    bindings of §9 are asserted — identical verdict spelling, verified
    residuals within tolerance and on the same side of it with identical
    `satisfied` flags, identical `bounds_active` and `dof_remaining`,
    identical bound input refs. The test explicitly does **not** assert digit
    equality anywhere, and asserts that no 2C block of either kind claims
    tier D1.
51. `space: "parameters"` accepted as an enum value on `propose_placement`
    with its schema constraint enforced in the canonical JSON Schema, and
    asserted to have been absent from the 13B enum (clause 40); no
    fourth tool is added (tool count still 57).
52. `heph solve params` human and `--json`.
53. The `solve-*` corpus family graded through the engine path: the reference
    solutions pass their own acceptance (Tier 1), and a run that produces a
    correct proposal **without rebuilding** fails the task — asserted
    directly, because it is the clause that keeps the loop broken.
54. Each new task ships prose + seeded variants and a second independent
    solution that also passes (`VALIDATION.md:163-167`); corpus-count pins
    repointed with this stage cited.
55. The Tier 3 bench clause, on the corpus-family mechanism
    (`VALIDATION.md:67-77`): **solve-prose and solve-seeded are each their own
    split, each baselined on its own first measurement with the reference
    model at ≥ 3 seeds, neither compared against nor averaged into the
    v1/v2/v3 baselines** — asserted through `split_name`, which must carve
    the family runs out *before* the aggregate is formed, so the existing
    0.70 prose bar keys on its own coverage
    (`bench/src/hephaestus/bench/scoring.py:282-304`) and is not diluted
    through the plumbing either; a first measurement thinner than three seeds
    per task is refused `insufficient_solve_seeds` and no baseline file is
    written (asserted directly, not by inspecting a written baseline);
    re-baselining any combined bar is its own explicit future amendment.
56. Existing suites stay green.
