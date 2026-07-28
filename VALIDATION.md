# 06 — Validation Ladder (Stage 2V)

Normative. Amends `mission_plan.md` (new gated stage 2V), `verification.md`
(corpus split + reported metrics), `tool_schema.md` (ledger/critique/review
surfaces) and `architecture.md` §4 (validation layer above the session).

## The gap this closes

The harness has **verification** — did the built geometry match what the agent
intended? — through build metrics, `CHECKS`, `measure`, and renders. It has no
**validation** — was the intention correct? Measured evidence (`bracket-101`
seed 2, 2026-07-26): the agent authored

```python
CHECKS = {"envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1), ...}
```

built geometry measuring `[60.0, 46.0, 40.0]`, saw its own check pass, and
stopped at 9 of 20 calls. The request said 40 mm in Y. A self-authored spec
test cannot catch a misreading of the spec, because it encodes the misreading.
100% of model-authored scripts in the 2026-07-25/26 corpus runs contain a
`CHECKS` block, so the loop is closed and self-referential — the failure is
upstream of geometry and no measurement machinery reaches it.

**Design rule for everything below: every rung fires by RULE, never by model
choice.** An agent that must be asked to be careful is not validated.

## 1. Corpus: two specs, never collapsed

`task.json` gains `"spec": "prose" | "seeded"`.

- **prose** — the project seeds without `checks/`; the agent must infer the
  spec from the request. Measures *interpretation*.
- **seeded** — the task's acceptance checks are installed in `checks/` at seed
  time as an independent spec the agent must satisfy. Measures
  *iterate-to-green*.

Each public corpus task ships in both variants (`<id>` and `<id>@seeded`).
Pass rates are reported and gated **separately**, with independently baselined
thresholds; the corpus-v0 aggregate gate (Wilson ≥ 0.60) continues to name the
**prose** split so the historical baseline stays comparable. The seeded split
gets its own threshold, baselined on first measurement, and **post-seeding
numbers are never compared against the pre-2026-07-26 baseline**.

The prose-vs-seeded gap is a first-class leaderboard column: it is the
interpretation tax, and it is the number this project exists to reduce.

Seeded acceptance checks are **protected paths**: the grader restores them
before the final build (already the ordering in `_grade.grade` —
`restore_protected` precedes `_build_all`; pinned by a regression test) and
scores any attempt to modify them (§8 spec-tampering rate).

### Acceptance checks are functional, never reproductive (2026-07-26)

The corpus fell into the same self-referential trap this document describes for
model-authored `CHECKS`, one level up: every acceptance check was authored FROM
its reference solution and validated AGAINST that same solution, so the "a task
no reference solution passes is broken" meta-test could only ever prove a task
was *passable* — never that it graded correctness rather than the author's
geometry. `gpt-5.6-sol` exposed it by failing three tasks no model can pass.

The normative rules that follow are enforced by corpus-wide tests:

1. **An acceptance check asserts a functional property** — fits, clears, seals,
   holds this envelope, uses this material, has this count. Never "matches my
   numbers."
2. **A volume window is a material budget**, carrying in a named constant the
   smallest spec deviation it must reject and the margin it keeps. An inline
   `abs=20.0` justifies nothing and is rejected.
3. **A check named for a fit is measured as a fit** — against a seeded gauge
   part, not through a volume proxy.
4. **An acceptance check evaluates on every submission, and fails under its own
   name** (added 2026-07-26 from a live bench defect). A check may not be
   conditional on something the run itself had to author, and one requirement
   may not be another's silent precondition. `print-bracket`'s DFM requirement
   left its `process` unset, so the fdm rule pack — the subject of the task —
   ran only when the model happened to write `part.process`; `gpt-5.6-sol` wrote
   it in seed 1 and not in seed 2 and was graded on printability once and on an
   unresolvable-process refusal (`dfm_failed:bracket`) once, for the same
   correct geometry. A task therefore **declares** what its checks need — the
   DFM process is named on the requirement, and the parser rejects one that
   omits it — and where the declaration is *itself* asked for by the prompt it
   is gated as its own named requirement (`metadata_process:bracket:unstated`),
   never as a precondition. Corollary: **where a prompt asks for §5.2
   manufacturing metadata, a `metadata_requirements` entry gates it** — and
   gates only what the prompt states, since a requirement the request never
   made is a different task.

Every task additionally ships an independent second solution — different
construction, different dimensions within spec — that must also pass. A check
written from one implementation cannot detect that it demands that
implementation; only a second, deliberately different one can.

## 2. Requirement ledger (the substrate)

Before any geometry, the agent emits a ledger; one entry per constraint:

```json
{"id": "R1", "text": "base plate 60 mm in X",
 "source": "specified", "quote": "60 mm (X) by 40 mm (Y) base plate",
 "value": 60.0, "unit": "mm", "applies_to": "bracket"}
```

`source` ∈ `specified` (traceable to a phrase in the request — `quote`
required), `derived` (computed from other entries — `from` lists their ids),
`assumed` (the model supplied it — `rationale` required; `material: true|false`
declares whether it moves geometry).

- Tool surface: `record_requirements(entries)` / `read_requirements()` /
  `update_requirement(id, ...)`, stored as an immutable-per-generation project
  artifact (`artifact:requirements:sha256:…`) under the project-config lock.
- **Every `CHECKS` threshold must cite a ledger entry id** in a trailing
  comment or the check name map; `heph lint` emits `unsourced_constant` for a
  numeric literal in a `CHECKS` predicate with no citation, and
  `unsourced_requirement` for a ledger entry with `source:"specified"` whose
  `quote` is not a substring of the request.
- **A `specified` entry may cite a reference instead of the prompt
  (`INGEST.md` §2).** Real work starts from a drawing or a datasheet, and a
  spec that lives there is no less specified for it, so in place of `quote` an
  entry may carry `cite: {reference, page?, quote}` naming an operator-supplied
  reference. It is not a weaker claim and is not checked more weakly: the
  ledger op refuses a citation of a reference the project does not carry (or a
  page past its end) with `invalid_requirement` and nothing written, and
  `unsourced_requirement` verifies a **document** citation against that
  reference's extracted text exactly as it verifies a prompt quote against the
  request. A citation of an **image** reference has no text to decide against,
  so lint neither passes nor fails it: it is `unverifiable_citation`, and §5's
  reviewer verifies it through the vision channel with the cited references in
  its context — which is why §8's channel split now measures document-grounded
  work too.
- The ledger is the substrate for §3, §5 and §8: it makes interpretation an
  inspectable artifact rather than an implicit act.
- **"Before any geometry" is enforced, not advised (2026-07-26).** `build_part`
  is refused while the ledger is **empty**, with the §3 discriminated result
  carrying `reason: "no_ledger"` and a message naming `record_requirements` as
  the way out. Measured: a live bench run reported `compelled_tool_calls = 0` on
  every run — nothing compelled the substrate to exist, so §3 had nothing to
  gate, §5 nothing to verify and §8's `requirement_coverage` no denominator. A
  rung that fires only when the model chooses to build it is not a rung.

## 3. Clarification gate (rule-enforced, blocking)

`build_part` is **refused** while any ledger entry has `source:"assumed"` and
`material:true` and **no recorded clarification** — that is, neither `asked`
nor `resolution` set by the runtime. The gate compels the *question*, not a
particular answer: once the runtime has recorded that the user was asked, §5
carries the burden. This is forced by the rest of the document — §3's own
closing clause and §6's exemplar terminal ("built, but wall direction
unconfirmed…") both presuppose that a declined answer still reaches geometry
and review, and §7's bench answer instructs the agent to proceed and record an
assumption. Nothing is relaxed: `asked` alone never confirms, §5 remains
fail-unless-**confirmed** keyed on a runtime-recorded `resolution`, and the §6
never-green invariant still forbids terminating green with the assumption
open. Refusal is a discriminated result:

```
{status:"clarification_required", reason:"unresolved_material_assumption"|"no_ledger",
 entries:[...], message:...}
```

`reason` discriminates the two refusals that share this shape: §2's absent
ledger (`no_ledger`, `entries: []`) and §3's unasked material assumption.

Material classes (non-exhaustive, matched by `applies_to`/`kind` on the entry):
envelope dimension, datum/origin placement, wall or feature direction
(inside/outside a stated face), fit class or clearance value, joint mating
direction, material thickness when not stated.

Both `asked` and `resolution` are **runtime-only fields**: `record_requirements`
and `update_requirement` refuse them from the model (discriminated
`invalid_requirement` naming `ask_user` as the only route), so their presence on
a stored entry is itself the evidence that a user was asked. An agent cannot
self-resolve its way past the gate, nor self-report §8's clarification rate.

Resolution comes from `ask_user`, and the question must follow the
concrete-options pattern — 2–4 options, **each stating its geometric
consequence**, never an open "what did you mean?":

> Walls: (a) inside the stated footprint → 40 mm overall, 34 mm internal;
> (b) outside → 46 mm overall, 40 mm internal; (c) split the difference.

The gate is enforced in the dispatch layer over ledger tags — it is not a
prompt instruction. A declined/non-committal answer leaves the entry
`assumed` with `asked: true`; it then **must survive §5 review**, which treats
unconfirmed assumptions as failures.

In the s2 case the wall-direction entry is exactly what fires.

## 4. Automatic post-build critique (unrequested)

Every **successful** `build_part` returns, without being asked, alongside
existing metrics:

- `interference`: pairwise overlap volume across all solids; any non-zero
  overlap not declared intentional (`part.feature(...).intentional_overlap` or
  a ledger entry) is a warning with the pair and volume.
- `manifold`: sealed/genus (already present, now surfaced in the critique
  block).
- `prompt_number_diff`: numeric values with units extracted from the original
  request, compared against bbox extents, tagged dimensions, and `CHECKS`
  thresholds. Any request number with no corresponding dimension → warning
  `unmatched_request_number`; any dimension contradicting a matched number →
  `dimension_mismatch` with both values.

Matching is deliberately crude (regex + unit normalization + nearest-dimension
within tolerance). False positives are acceptable; silence on a real mismatch
is not. On s2 this fires immediately: request says 40, geometry says 46,
nothing references 40.

Rationale: the reference product volunteered interference unasked; waiting for
a confident model to choose to measure is waiting forever.

### Dimension findings are BINDING (2026-07-26)

Measured on `bracket-101`: all three seeds built a wall outside the stated
footprint, this rung **fired correctly and unrequested** — "bbox.y measures
46 mm" against a request that says 40 mm, plus "nothing in the built geometry
measures 40 mm on Y" — and every seed shipped anyway. §3 could not help, because
the model tagged its misreading `source: "specified"`, so there was no assumption
to gate on. The rung that works is the independent one, and it had no teeth: a
warning is advice, and an agent that must be asked to care is not validated.

So a `dimension_mismatch` / `unmatched_request_number` raised by a **successful**
build is recorded as an **open finding on the run**, and §6 may not terminate
green while one is open — exactly the never-green invariant an unconfirmed
material assumption already carries (§5/§6), from the other side: one says nobody
confirmed the interpretation, this says the geometry contradicts the request.

- **Harness-derived, so not self-clearable.** Findings are computed from the
  request text the runtime bound and the geometry the build published. There is
  no model-facing write: not through the ledger, not through `update_requirement`,
  not by the reviewer being talked into a `pass` (a verdict supplied for a finding
  id is filed as unknown and counts for nothing).
- **Judged against measured dimensions only** — bbox extents and tagged edge
  lengths, never the script's own `CHECKS` thresholds. §5 refuses to hand the
  reviewer the agent's acceptance tests for this reason and it holds one rung
  down: clearing a finding with the artifact that encodes the misreading is not
  clearing it. (The *advisory* block above still matches thresholds.)
- **Binding on axis-resolved numbers.** A number the request pins to an axis
  ("40 mm (Y)", "overall height is 40 mm") is measured by the bbox either way
  round, so a disagreement is evidence. An axis-less unmatched number ("no
  dimension corresponds to 12 mm") says the harness did not *find* it, not that
  the geometry contradicts it; it stays the advisory warning it was, because
  binding on the harness's blindness would make every terminal red and therefore
  meaningless.
- **It clears in exactly two ways.** (1) A **later successful build of the same
  part** whose binding diff no longer raises it — the geometry actually changed
  to match. A failed build publishes nothing and clears nothing; a *preview*
  build (transient overrides) is not what the run delivered and neither raises
  nor clears. (2) An **explicit dismissal by the user** through the `ask_user`
  path, recorded by the runtime from a committal answer exactly as §3 records a
  clarification `resolution` — a declined or non-committal answer (§7's bench
  answerer) records `asked` and dismisses nothing, so the bench can never answer
  its way past its own measurement. A dismissed finding is not reopened by a
  later build: a human judged that dimension.
- Findings live in an immutable generation store
  (`artifact:dimension-findings:sha256:…`) so the archive shows what was open
  when and how it closed, and every successful build's result carries the still-
  open findings — with the id an `ask_user` question must name — so the model
  reads the obligation in the same result as the measurement.

## 5. Termination review (independent, blocking)

**The agent may not self-declare done.** Reaching a stop state (final assistant
turn with no pending tool call) triggers a reviewer child session that receives:

- the **original request verbatim**,
- the requirement ledger,
- multi-view renders: `rgb` at ≥2 standard views, plus a `section` render for
  every part whose geometry has internal features (cavity, boss, bore),
- the final part scripts and measured metrics,
- every operator-supplied reference the ledger **cites** (`INGEST.md` §2), by
  name and artifact ref, which the reviewer opens with `read_reference`. An
  image citation is lint-*unverifiable* by construction, so this reviewer is the
  only thing that verifies it, and it does so by looking: such a finding is
  recorded on the `vision` channel by rule, from the entry rather than from the
  reviewer's claim about itself,
- **explicitly NOT** the agent's own `CHECKS` — so it cannot inherit the
  misreading.

It returns per requirement: `pass` | `fail` | `unverifiable`, each with the
supporting measurement or render observation, and **treats `assumed` entries
as fail-unless-confirmed**. It records `channel: "vision" | "numeric"` for each
finding — this is where vision earns its keep (feature on the wrong face, joint
that does not mate) versus the numeric channel (dimension errors).

The reviewer is a Pi child with the measurement/render tool subset, no
mutation tools, no delegation, and its own budget; it cannot edit the project.

## 6. Continuation ladder (bounded)

Review findings return **as an ordinary tool result the agent must resolve** —
a continuation, not an advisory. Bounds:

- ≤ **3** review cycles per task;
- a requirement failing **the same way twice** escalates to a mandatory
  `ask_user` with concrete options rather than another silent repair;
- exhausting cycles or budget terminates with an explicit
  `unresolved_requirements` report listing each open item.

**Invariant: an agent may never terminate green while any requirement is
unverified, assumed-without-confirmation, or contradicted by an open §4
dimension finding.** A truthful "built, but wall direction unconfirmed and Y
envelope is 46 mm against a stated 40 mm" is a better outcome than a confident
pass — in the bench and in front of a user. Note that the exemplar's second
clause is now enforced by machinery rather than hoped for in a report: §4's
findings enter this ladder as open items of the same kind as review findings.

Open dimension findings ride the machinery above unchanged, because they are the
same kind of obligation:

- they re-enter as part of the same continuation payload the agent must resolve,
  each naming its finding id and the number it failed;
- the same failure twice escalates to the same mandatory `ask_user`, whose
  concrete options must include the dismissal — that is the only route the run
  has short of geometry that matches, so an escalation that hid it would demand
  a resolution nobody could give;
- the escalation is satisfied by the *runtime's* record that the question was put
  (`asked` on the finding, as on a ledger entry), never by a silent repair;
- the 3-cycle cap applies, and the terminal's `unresolved_requirements` lists
  each open dimension alongside each open requirement, carrying
  `source: "critique"` so a reader can tell what was stated from what was
  measured.

Their clearing rules — a rebuild that matches, or a runtime-recorded dismissal,
and nothing else — are §4's, above.

## 7. Bench answers non-committally, and asking is scored

The bench answerer must not do the disambiguation the production `ask_user`
exists to obtain. It answers every question with:

> "unspecified — use your engineering judgment and record it as an assumption."

and the run records `asked: true` for that requirement. Auto-answering
helpfully would delete the very mechanism under test. An agent that asks well
scores better than one that guesses right by luck (§8).

### Budget enforcement vs measurement (2026-07-26)

Cancelling a run the moment it exceeds its budget **censors the measurement**:
every over-budget run records exactly `budget + 1`, so "needed one more call"
and "needed triple" are indistinguishable — and the pass rate cannot tell a
calibration problem from a capability one. Worse, a cancelled run never reaches
a stop state, so §5's termination reviewer and §6's continuation ladder never
fire; measured 2026-07-26, seven consecutive cancellations meant the reviewer
had never executed in a bench at all.

The bench therefore **observes** by default: a run continues past its budget to
a hard ceiling (`max(4 × budget, budget + 24)`) or the wall-clock timeout, and
records `tool_calls` to completion plus `budget_exceeded_at`. `--enforce-budget`
restores hard cancellation for cost-bounded runs. **Grading is identical in both
modes** — `within_budget` is computed from the recorded count and a run over its
budget still fails — so this changes what is learned, never what passes.

### Budget accounting for compelled calls (2026-07-26)

The tool-call budget measures the **agent's own** design efficiency. The
ladder's rungs are not the agent's choices — §2 requires a ledger before
geometry, §3 blocks `build_part` until a material assumption has been asked
about, §6 returns findings the agent must resolve — so `record_requirements`,
`read_requirements`, `update_requirement` and `ask_user` are **counted but not
charged**. Charging them would silently tighten every task by several calls
against budgets calibrated before the ladder existed, making the bench measure
harness ceremony rather than agent competence. They cannot be gamed precisely
because they are compelled: the rules decide when they fire. Every run record
reports `compelled_tool_calls` alongside `tool_calls`, so the exemption is
visible per run rather than hidden.

## 8. Reported metrics (leaderboard + gate evidence)

Per model, per corpus version:

| metric | definition |
|---|---|
| `pass_rate_prose` / `pass_rate_seeded` | separate, separately baselined |
| `interpretation_gap` | seeded − prose |
| `error_recovery_rate` | failed build → **next build succeeds** (not error uniqueness: a model that abandons approaches also shows few repeats) |
| `requirement_coverage` | ledger entries with a reviewer verdict ≠ `unverifiable` |
| `clarification_rate` | material `assumed` entries that produced a question |
| `review_catch_rate` | reviewer-caught failures ÷ total, **split by channel** (vision vs numeric) |
| `spec_tampering_rate` | attempts to modify protected/seeded checks (restored, and scored) |
| `harness_error_rate` | runs carrying a harness-attributable reason (`review_error:`, `harness_error:`) ÷ all runs |

**Harness errors are measured, never charged to the model.** When the §5
reviewer cannot be run — a sidecar respawned without its `runtime.configure`, a
reviewer child that raised — that is our bug, and it is no evidence at all about
the agent. Such a reason stays in the archived run record and is reported here as
`harness_error_rate`, a reliability number about the harness; it is excluded from
the pass/fail decision, so a run whose only reason is `review_error` passes. A run
that also failed a real check still fails on that check, and a grading crash
(`harness_error:`) still fails, because it leaves no verdict to trust.

## 9. Model-selection discipline

`bracket-101` is prismatic with numeric criteria — the case where vision
contributes least. **No conclusion about the vision path** (and no downgrade to
a text-only reference model) until `knob-loft`, `enclosure-bosses`, and an
assembly-mating task have reported with §8's channel split. The harness is
model-agnostic; the bench decides and the leaderboard publishes the split.

## Gate G2V

`uv run pytest tests/stage2v -q` exits 0, covering: ledger CRUD + generations +
lint rules (unsourced constant, unquoted `specified`); the clarification gate
(material assumption blocks `build_part` with the discriminated result;
resolution unblocks; non-committal answer keeps `assumed` + `asked`);
post-build critique (interference pair detection, `unmatched_request_number`
and `dimension_mismatch` on the recorded s2 fixture — it MUST fire there);
**binding dimension findings** (the recorded s2 build MUST be blocked from
terminating green; it clears when a rebuild matches; an explicit
runtime-recorded dismissal clears it; a non-committal answer, a ledger write, a
`CHECKS` assertion and a reviewer `pass` all fail to clear it; the 3-cycle cap,
the escalation-with-dismissal-option and the `unresolved_requirements` terminal
hold);
termination review (reviewer receives request/ledger/renders and NOT the
agent's CHECKS — asserted structurally; assumed ⇒ fail-unless-confirmed;
channel recorded); continuation ladder (findings re-enter, 3-cycle cap,
same-failure-twice escalation, `unresolved_requirements` terminal, and the
never-green-with-open-requirements invariant); bench answerer non-committal +
`asked` scored; seeded/prose split scored separately with no cross-baseline
comparison; protected seeded checks restored **before** the final build and
tampering scored. Existing G0A/G0B/G1/G2/G3 suites stay green.
