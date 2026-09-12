# Refusal vocabulary

> **Verified against** `3c3847c` on 2026-09-12.
> Counts printed from the code: `len(REASON_STATUS)` = 87; solver verdicts 12 distinct
> spellings, solver refusals 34, intersection empty.

Hephaestus refuses by name. An operation that cannot produce evidence returns a
named reason rather than a plausible answer, and callers dispatch on the name.
This page is the map of those names: where each family lives, what it means, and
the rules that keep the families apart.

## The one rule that shapes all of it

**A refusal is never a verdict, and a verdict is never a refusal.**

The clearest case is the solver. It has 12 distinct verdict spellings and 34
refusal names, and the two sets are disjoint — verified by intersecting them:

```console
$ uv run python -c "
from hephaestus.core import placement as P
V=set(P.POSE_SOLVE_VERDICTS)|set(P.TRANSFORM_SOLVE_VERDICTS)
R=set(P.SOLVE_REQUEST_REFUSALS)|set(P.SOLVE_RESOLUTION_REFUSALS)|set(P.SOLVE_RUNTIME_REFUSALS)
print(len(V), len(R), sorted(V & R))"
12 34 []
```

A killed solve decided nothing. Giving a ceiling a verdict spelling would let it
be read as an outcome, so `solver_timeout` cannot be mistaken for
`no_placement_found_from_starts`. The engine applies the same discipline to
checks, to comparisons and to motion.

## Base machinery

Every engine error carries a stable `code`; message text is informational only
(`core/src/hephaestus/core/errors.py`).

| Code | Meaning |
| --- | --- |
| `addressing_error` | a selector did not resolve, or resolved ambiguously; carries `candidates` and a `reason` of `unresolved` or `ambiguous` |
| `param_out_of_bounds` | one or more parameters outside declared bounds; names **every** offender, and nothing is applied |
| `sandbox_denied` | no proven OS sandbox; the build did not run |
| `unsafe_refused` | the unsafe executor was asked to run something it must not |
| `validation_error` | with a `kind` of `syntax`, `contract`, `sandbox` or `evaluation` |
| `conflict` | a compare-and-swap lost, or recorded evidence disagrees with itself |
| `check_set_drift` | the project's checks changed mid-capture |
| `invalid_check_generation` | the persisted check generation is marked invalid; execution fails closed |

## Addressing: three cases that must not merge

This is the family most often collapsed by accident, and the collapse is a real
defect: reporting "the part is invalid" about a part that is fine.

| Condition | HTTP route | Tool surface |
| --- | --- | --- |
| the name is not a legal part name | 400 `invalid_part` | `invalid_part` |
| a legal name the project does not have | 404 `unknown_part` | `addressing_error` with candidates |
| a selector *inside* a part that resolves to nothing or ambiguously | 400 `addressing_error` | `addressing_error` with candidates |

The surfaces differ because an HTTP route resolves the part before any engine
call runs, while a tool call reaches the store directly and the store's own
answer for a missing part is an addressing miss. The dispatcher re-raises the
engine's own code rather than flattening it.

## Bounded operations: a ceiling is not a death

Five operations run a child process under a wall clock through one shared
supervision helper (`core/src/hephaestus/core/executor/bounded_pass.py`). Each
must distinguish two facts, because the remedies differ: more time cures a slow
pass and cures nothing about a crashed one.

| Operation | Ceiling | Child died |
| --- | --- | --- |
| solid diff | `compare_timeout` | `compare_child_died` (carries the exit code) |
| motion sweep | `motion_timeout` | `motion_child_died` (carries the exit code) |
| solver verification | `solver_timeout` | `verification_process_died` |
| scan distance | `scan_timeout` | `scan_timeout` — **still conflated** |
| mesh sew | `mesh_sew_timeout` | `mesh_sew_timeout` — **still conflated** |

The last two rows are a known open item, recorded in the repository's audit
ledger and in [known open issues](../06-operations/known-open-issues.md). They
compute a differentiated message but raise the same reason, so a machine reading
`reason` cannot tell a crash from a ceiling there.

Every bounded refusal carries what was already measured — the partial facts and
a list naming which halves were lost. `lost` and `completed` partition the same
vocabulary: a direction that reported is in one and absent from the other, never
in both and never in neither.

## Checks: pass, fail, error, not run

A check result is two fields, `passed` and `measured`. There is no three-way
status enum. A measurement that could not be taken writes `unverifiable` (or
`error`) *inside* `measured`, and the report layer computes a closed badge set:

```
BADGES = ("pass", "fail", "error", "not_run")
```

A check whose measurement was cut short badges `error`, never `fail`. Neither
may read as a pass, and a check that never ran is `not_run`, not a failure.

Do not write "a check result is pass, measured or unverifiable" — that sentence
is wrong on all three counts.

## HTTP: the envelope

Every refusal on the HTTP surface has the same shape, and `reason` and `message`
always win over any data spread into the body:

```json
{"status": "error", "reason": "unknown_route", "message": "GET /api/v1/nope is not a route this server serves"}
```

87 reasons map to a status. The families:

| Status | Reasons include |
| --- | --- |
| 400 | `invalid_params`, `invalid_part`, `invalid_cursor`, `invalid_ref`, `idempotency_key_required`, `idempotency_key_malformed`, `addressing_error`, `prompt_too_large`, the four `json_*` structural limits |
| 401 | `unauthorized` |
| 403 | `scope_denied`, `not_loopback`, `git_verb_refused` |
| 404 | `unknown_part`, `unknown_artifact`, `unknown_session`, `unknown_run`, `unknown_route`, `not_a_git_repository` |
| 405 | `method_not_allowed` (the `Allow` header is preserved) |
| 409 | `conflict`, `part_busy`, `run_in_flight`, `target_exists`, the four idempotency-key faults |
| 410 | `artifact_expired` |
| 413 | `request_too_large`, `export_too_large` |
| 428 | `model_revision_required` |
| 429 | `busy`, `provider_rate_limited` |
| 500 | `internal_error` |
| 503 | `agent_unavailable`, `git_unavailable`, `process_down` |
| 504 | `git_timeout`, `timeout` |
| 507 | `protected_quota_exceeded` |

An unknown reason falls back by shape: one starting `unknown_` or `no_such_` is
404, anything else 400.

**Two conditions are 200, not errors.** A compare-and-swap conflict rides back as
the tool's own discriminated result, and a capability that is not available
(`capability_not_available`, `image_model_required`) returns
`{"status": "capability_error", …}` at 200. Both are answers, not failures.

**An unexpected exception** returns a fixed message and an incident id; the
traceback goes to the server log and nothing of the exception text reaches the
client.

## Agent tools

Three streams converge on the model's tool results, and all of them keep the
engine's own token:

- the dispatcher's own reasons, including `scope_denied`, `unknown_tool`,
  `already_exists`, `ambiguous_edit`, `build_failed`, `invalid_cursor`;
- the CAD operations' reasons, including `invalid_params`, `unknown_artifact`,
  `stale_selection`, `path_confinement`, `part_busy`, `mass_density_unbound`,
  `too_many_images`;
- the **registry's** reasons — 13, and this one is a closed enumerable set:
  `ambiguous_component_id`, `capability_not_available`,
  `computed_mass_disagreement`, `interface_class_mismatch`,
  `interface_not_placed`, `interface_placement_drift`, `invalid_instance_name`,
  `invalid_params`, `unknown_dfm_pack`, `unknown_dfm_rule`, `unknown_skill`,
  `unknown_store_part`, `unsourced_component_datum`.

The token is prefixed onto the message the model sees, so the model
discriminates on a name rather than on prose.

Both direct streams are now declared data: `DISPATCH_REFUSAL_REASONS` contains
the 10 reasons originated by `dispatch.py`, and `CAD_OP_REFUSAL_REASONS`
contains the 41 reasons originated by the CAD-operation modules. A source-walking
test compares each frozenset with every literal constructor call, so adding or
removing a direct reason requires changing the declaration. Reasons translated
from lower-layer exceptions remain owned by those layers rather than being
copied into either set.

## Delegation

`RejectionReason` declares exactly the five producible pre-admission reasons.

| Reason | Producer |
| --- | --- |
| `invalid_part` | the pre-admission gate |
| `scope_denied` | the pre-admission gate |
| `part_busy` | the pre-admission gate |
| `no_run_slot` | admission |
| `prompt_too_large` | the byte check |

The old `queue_full` token named a queue that no longer exists, and delegation
could not observe the foreign ownership needed to produce `session_busy`; both
were removed from the delegation result schema. Session ownership can still
refuse separately with `session_busy` before a delegation reaches this state
machine.

## Sandbox

`sandbox_denied` is the code; `sandbox_unavailable:` is a message prefix, not a
code. Several documents in the repository use the prefix as though it were the
code. Verified:

```console
$ PATH=/no/bwrap heph build example --json
{"code": "sandbox_denied", "message": "sandbox_unavailable: secure sandbox probe failed: bwrap not on PATH", "status": "refused"}
```

## CLI exit codes

| Exit | Meaning |
| --- | --- |
| 0 | the operation ran and succeeded |
| 1 | the operation ran and the answer was no: a failed build, failing checks, a named engine refusal, an unavailable sandbox |
| 2 | the request was malformed: usage, a bad selector with candidates, an unreadable path |

A refusal always goes to stderr, so stdout stays a result document. With
`--json` the shape is `{"status": "refused", "code": …, "message": …}` plus
`candidates` where the refusal has them.
