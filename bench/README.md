# bench/ — Tier 3 benchmark

This directory is the `hephaestus-bench` workspace member. The harness is its
source tree, `bench/src/hephaestus/bench/` (import path `hephaestus.bench`,
unchanged by the promotion out of `server/`); `bench/results/` is where its
output lands. The tasks and their reference solutions are `corpus/tasks/` and
`corpus/solutions/`.

## Running it

```sh
uv run heph bench run --dry-run                       # list the planned runs; no model calls
uv run heph bench run --provider providers.json --model <id> [--tasks a,b] [--seeds 3]
uv run heph bench score bench/results/<model>/<date>  # write the scoring artifact
```

`--provider` is a JSON file so no endpoint or credential is ever hard-coded:

```json
{
  "providers": [
    {
      "id": "reference",
      "kind": "openai_compatible",
      "baseUrl": "https://…/v1",
      "credential": "HEPH_BENCH_KEY",
      "models": [{"id": "…", "contextWindow": 200000, "maxTokens": 8192,
                  "input": ["text", "image"]}]
    }
  ],
  "credential_env": ["HEPH_BENCH_KEY"]
}
```

`credential_env` names are read from the ambient environment at load time; the
supervisor forwards only that allowlist to the sidecar. `--model` must name a
model the file declares (the harness reorders providers so the sidecar resolves
it).

## Layout

```
bench/results/<model>/<date>/                run archive for one `heph bench run`
  runs.jsonl                                 one RunRecord JSON per line (the index)
  <task>-s<seed>/
    prompt.txt                               the exact seeded prompt sent
    events.jsonl                             normalized Hephaestus events, in order
    grade.json                               GradeReport: builds, checks, exports, renders
    result.json                              the RunRecord for this (task, seed)
    project/                                 the seeded project the run authored into
bench/results/<model>/<date>.json            the scoring artifact / leaderboard row
```

## What gets committed

Two artifacts, and only those: `<model>/<date>.json` — the scoring artifact
`verification.md` names as the leaderboard row — and `<model>/<date>/runs.jsonl`,
the RunRecord index a score can be re-derived from. Everything else inside a run
directory (`prompt.txt`, `events.jsonl`, `grade.json`, `result.json`, `project/`)
is an ordinary CI artifact: large, per-machine, and ignored. `bench/results/.gitignore`
encodes exactly that split; do not commit a run directory's contents by force.

## What a pass means

Pass = **every required check passes AND every required export/render validates
AND the run stayed within its tool-call budget**. Grading is independent of how
the run got there: the task's protected files are restored, every part is
rebuilt, the task's CHECKS are installed over whatever the run authored, and the
exports are produced from the graded geometry.

## The gate statistic

The gate is the one-sided **lower 90% Wilson bound** of the aggregate pass rate
(z = 1.281552), never the raw fraction. Stage 2 (G2): `wilson_lower_90 >= 0.60`
over 8 tasks × ≥3 seeds (n ≥ 24), plus `repair-fillet` passing every seed.
`heph bench score` exits 0 only when both hold. Thresholds are mission-tunable
*upward* only.

The statistic covers the corpus it was baselined over and no more. A corpus
**family** (`PARTS_STORE.md` G11C clause 12, following `KINEMATICS.md:392-398`)
— currently `component`, the Stage 11 component-bearing mechanism tasks — is its
own split per spec, carries no threshold, and is carved out of the gated number
entirely, so adding tasks to the corpus can never dilute an existing bar by
arithmetic. A family is baselined on its own **first** measurement at ≥3 seeds
into `component_baseline.json`; a thinner first measurement is refused by name
(`insufficient_component_seeds`) rather than recorded. Re-baselining any
combined bar is its own explicit amendment.

Two consequences worth stating, because both are properties of the *archive*
rather than of the code that reads it. First, the carve-out never rewrites
history: a family split appears in `<date>.json` only when it has runs, and
`min_seeds_per_task` — the floor's one input — is serialised for family splits
only, so re-scoring an archive measured before Stage 11 reproduces its stored
artifact byte for byte. Second, the component family's baseline **has not been
measured yet**; taking it is a detached run with the epoch's reference model, and
`heph bench score` prints `component family: NOT MEASURED` on every archive that
ran no family task so that the gap is never inferred away.

## External evaluation: the CADGenBench adapter

`hephaestus.bench.cadgenbench` (`EXTERNAL_EVAL.md` §2) adapts the external
benchmark onto this harness. It lives entirely in `bench/` — the engine never
imports it — and rides Stage 8A ingest (generation = drawings seeded as
`references/`, editing = the starting solid seeded under `imports/`) and Stage
8B comparison, so it adds no engine capability. The facts it is written against
are recorded in `bench/CADGENBENCH_FACTS.md`.

```sh
uv run heph bench cadgenbench fetch                       # public inputs -> ~/.cache/hephaestus/cadgenbench
uv run heph bench cadgenbench convert --tasks-dir tasks   # samples -> bench tasks (refusals are named)
uv run heph bench cadgenbench run --provider providers.json --model <id> \
    --tasks-dir tasks --outputs outputs [--samples 101,201] [--parallel N]
uv run heph bench cadgenbench package --outputs outputs --out submission.zip \
    --submitter "…" --submission "…" --agree-to-publish
uv run heph bench cadgenbench score --outputs outputs
```

Four rules this surface enforces rather than documents:

- **No external data is ever committed.** The dataset is ODC-BY (geometry
  courtesy of Mecado) and is cached outside the repository; a `--dest` inside
  the working tree is refused. The committed fixtures under
  `tests/stage8d/fixtures/` are synthetic mini-samples in the same layout.
- **A malformed sample is refused by name, never skipped.** `convert` exits
  non-zero and names every refusal, and `run` will not proceed on a partial
  corpus.
- **`--agree-to-publish` is required.** `meta.json`'s `agree_to_publish` is the
  leaderboard's only consent gate; it is the operator's declaration to make.
- **`score` is a floor, and says so.** Ground truth is private to the
  leaderboard Space, so no local computation is a CAD Score. The artifact is
  labelled `local floor` and reports validity plus, for editing samples,
  `score_step_files` facts against the sample's *own starting solid*.

Uploading the ZIP is an operator act; the machine-checkable gate ends at the
packaged, sanity-checked submission.
