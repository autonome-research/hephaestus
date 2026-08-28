<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# `workspace` — the public clean-room fixture for Gate G4

`INTERFACE.md` §14 and §19 item 16: neither `assembly`, `failure_fillet` nor
`fingerprint` is a project with the shape the Stage 4/5 browser gates need, and
the graded corpus under `corpus/tasks/` is Tier 3 bench evidence, not UI fixture
material. This project is the dedicated fixture `pnpm --dir web test:e2e` opens.

It is clean-room: a flat-pack stair-tread kit, nested for laser cutting. No
reference product's copy, geometry, naming or screens appear in it.

## Layout

| Path | What it is |
|---|---|
| `hephaestus.toml` | project manifest; `[dfm] auto_run = false` so the §6.4 setting has a known starting state |
| `globals.py` | one project parameter (`sheet_t`) and the sheet's derived constants |
| `parts/tread.py` | the subject part: three labeled solids, the `tread_top` tag, `groove_count`, all nine `part.*` metadata names, three DFM violations |
| `parts/riser.py` | a second part, so the tree, the part switcher and `GET /parts` are never one row |
| `parts/kerf_card.py` | the oversized-legend operand (G5.8). **Not built by the G4 harness** |
| `checks/tread_checks.py` | one check per reachable badge state |
| `requirements.json` | the ledger `VALIDATION.md` §2 requires before any build; replayed through the production writer at materialization, because a ledger lives in the opstore and cannot be committed |
| `transcript/` | the committed session history and its `tp_session_edges` row (see `transcript/README.md`) |

Materialize it with
`hephaestus.testing.workspace_fixture.materialize_workspace_fixture(dest)`,
which copies the tree, commits it to a fresh git repository (the git panel needs
a real history), replays the recorded transcript into `.heph/sessions/`, and
records the transcript's session edges through the same `SessionEdgeStore` the
two production writers use.

## The §14 requirement ledger

Every requirement §14 lists, and where it is met — including the one that is
not, stated rather than quietly dropped.

| §14 requirement | Met by | Value |
|---|---|---|
| ≥3 solids (G4.6 not vacuous) | `tread.py` | `tread`, `cleat_left`, `cleat_right` — three entries, one solid each, so a visibility toggle addresses exactly one solid |
| tagged `tread_top` face with a known creating line (G5.4) | `tread.py` | `tag(...)` on the walking surface; the source map records `{kind: face, solid: 0, line: 39}` |
| `groove_count = Param(5, min=2, max=10)` (G5.2, G5.3) | `tread.py` `PARAMS` | part-scope, drives the groove pitch, so moving it changes geometry |
| the full enumerated `part.*` metadata set (G4.3) | `tread.py` | all nine of `METADATA_FIELDS`. `blank_size` is an **f-string**, so a static AST parse cannot recover it and the properties projection must read the build record |
| checks producing each badge state | `checks/tread_checks.py` | `pass` / `fail` / `error` — see the refusal below for `not_run` |
| a selection legend over `INLINE_LEGEND_CAP_BYTES` (G5.8) | `kerf_card.py` | 366 faces + 1092 edges; `mask_mode="selection"` returns `mask_legend_truncated: true` with a `mask_legend_ref` |
| a >250-event normalized transcript with a quick-edit child (G4.9-G4.11) | `transcript/` | 281 normalized events over 2 history pages, plus a 3-event quick-edit child; recorded by `scripts/record_workspace_transcript.py` (see `transcript/README.md`) |
| a DFM-violating feature (§6.4) | `tread.py` | all three shipped `laser_cut` rules are violated — see below |

### The DFM violations, one per shipped rule

`registries/dfm/laser_cut/pack.toml` ships three rules and the tread violates
each exactly once, so a `run_dfm` on this fixture exercises the whole pack:

- **`laser_cut.min_feature_vs_kerf`** — the drainage bore is 0.5 mm across,
  below the 0.8 mm minimum cut feature.
- **`laser_cut.min_internal_radius`** — the service notch's two internal corners
  are rounded 0.3 mm, tighter than the 0.5 mm beam radius (two findings).
- **`laser_cut.sheet_thickness_match`** — `sheet_t` is 5.5 mm and Baltic birch
  plywood is stocked at 3/6/12/18 mm.

The thickness violation is a **parameter**, not a literal, so it can be cleared
by moving a slider. That is deliberate: a DFM demonstration whose only remedy is
a script edit demonstrates less.

### Refusal: `not_run` has no producer, and this fixture does not fake one

§14 asks for "checks producing at least one of each badge state **including
`not_run`**". Three of the four are here. The fourth is not, and the reason is a
fact about the engine rather than about this fixture:

> `hephaestus.core.checks.engine` loads every check in the frozen bundle and runs
> all of them, so *declared* and *run* are the same set by construction. A
> predicate that cannot be evaluated raises into `measured.error` and badges
> `error`; a bundle that cannot be loaded fails the whole generation closed with
> `invalid_check_generation`. There is no path by which a run reports a check it
> did not reach.

`not_run` is therefore a **projection-level** state:
`hephaestus.http.projections.checks_projection(report, declared=…)` badges any
declared name the report does not carry, and that is where it is exercised
(`server/tests/test_http_reads.py`, `web/test/inspector.test.tsx`). Writing a
check file that somehow "does not run" would mean writing a broken bundle and
calling its breakage a fourth badge. G4.4's own subject — browser badges versus
`heph check --json` — is unaffected: neither side can produce `not_run`, so the
comparison is total over the three states that exist.

## What this fixture is not

It is not graded bench material and it is not scored. It carries no task
manifest, no solution, and nothing under `corpus/tasks/` or `bench/` refers to
it. Changing it changes a UI gate and nothing else.
