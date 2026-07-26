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
- The ledger is the substrate for §3, §5 and §8: it makes interpretation an
  inspectable artifact rather than an implicit act.

## 3. Clarification gate (rule-enforced, blocking)

`build_part` is **refused** while any ledger entry has `source:"assumed"` and
`material:true` and no recorded resolution. Refusal is a discriminated result:

```
{status:"clarification_required", entries:[...], message:...}
```

Material classes (non-exhaustive, matched by `applies_to`/`kind` on the entry):
envelope dimension, datum/origin placement, wall or feature direction
(inside/outside a stated face), fit class or clearance value, joint mating
direction, material thickness when not stated.

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

## 5. Termination review (independent, blocking)

**The agent may not self-declare done.** Reaching a stop state (final assistant
turn with no pending tool call) triggers a reviewer child session that receives:

- the **original request verbatim**,
- the requirement ledger,
- multi-view renders: `rgb` at ≥2 standard views, plus a `section` render for
  every part whose geometry has internal features (cavity, boss, bore),
- the final part scripts and measured metrics,
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
unverified or assumed-without-confirmation.** A truthful "built, but wall
direction unconfirmed and Y envelope is 46 mm against a stated 40 mm" is a
better outcome than a confident pass — in the bench and in front of a user.

## 7. Bench answers non-committally, and asking is scored

The bench answerer must not do the disambiguation the production `ask_user`
exists to obtain. It answers every question with:

> "unspecified — use your engineering judgment and record it as an assumption."

and the run records `asked: true` for that requirement. Auto-answering
helpfully would delete the very mechanism under test. An agent that asks well
scores better than one that guesses right by luck (§8).

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
termination review (reviewer receives request/ledger/renders and NOT the
agent's CHECKS — asserted structurally; assumed ⇒ fail-unless-confirmed;
channel recorded); continuation ladder (findings re-enter, 3-cycle cap,
same-failure-twice escalation, `unresolved_requirements` terminal, and the
never-green-with-open-requirements invariant); bench answerer non-committal +
`asked` scored; seeded/prose split scored separately with no cross-baseline
comparison; protected seeded checks restored **before** the final build and
tampering scored. Existing G0A/G0B/G1/G2/G3 suites stay green.
