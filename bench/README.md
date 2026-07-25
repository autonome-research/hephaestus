# bench/ — Tier 3 benchmark results

The harness lives in `server/src/hephaestus/bench/` (`hephaestus.bench`); this
directory is where its output lands. The tasks and their reference solutions are
`corpus/tasks/` and `corpus/solutions/`.

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
