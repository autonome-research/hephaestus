<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0

GENERATED FILE — do not edit by hand.
Regenerate with: heph bench leaderboard --out docs/leaderboard.md
Source: bench/results/<model>/<date>.json (hephaestus.bench.leaderboard)
-->

# Model leaderboard

Which models can actually do CAD in this harness, measured the same way
every time. Each row is one scored corpus run archived under
`bench/results/<model>/<date>.json`; the page is generated from those
artifacts and never edits them.

| Model | Date | Runs | Prose pass rate | Seeded pass rate | Wilson lower-90 | Interpretation gap | Meets gate |
|---|---|---|---|---|---|---|---|
| `ThinkingCap-Qwen3.6-27B-NVFP4` | 2026-07-25 | 24 | 16.7% (4/24)† | n/a | 0.091 (aggregate) | n/a | no |
| `gpt-5.6-sol` | 2026-07-29 | 72 | 69.4% (25/36) | 80.6% (29/36) | 0.589 (prose) | +11.1 pp | no |
| `gpt-5.6-sol` | 2026-08-03 | 72 | 72.2% (26/36) | 91.7% (33/36) | 0.618 (prose) | +19.4 pp | no |
| `gpt-5.6-sol` | 2026-08-13 | 72 | 83.3% (30/36) | 97.2% (35/36) | 0.740 (prose) | +13.9 pp | yes |

## Reading the table

- **Runs** is every scored (task, seed, split) run behind the row. A split's
  own denominator is shown inside its cell.
- **Prose** and **seeded** pass rates are separate measurements with
  independently baselined thresholds, and are never averaged into one
  number (`VALIDATION.md` §1). Prose measures interpreting a request;
  seeded measures iterating to green against checks installed as an
  independent spec.
- **Wilson lower-90** is the one-sided lower 90% Wilson bound on the gated
  split's pass rate — the quantity a gate compares against, so that tiny-n
  luck cannot pass a stage (`verification.md`). The split it was taken over
  is named in the cell.
- **Interpretation gap** is seeded − prose: the interpretation tax. A large
  positive gap says the model can build what it is told precisely and
  struggles to work out what was meant.
- **Meets gate** is the verdict recorded in the artifact, not a judgment
  made here.
- **†** marks an unsplit corpus-v0 aggregate from before the
  2026-07-25 seeding amendment. It is shown in the prose column because
  that is the closest thing it measured, but it is **not** comparable to a
  post-amendment prose rate (`VALIDATION.md` §1) and has no gap to report.

Harness errors are measured and never charged to the model: a run whose
only failure reason is harness-attributable is excluded from the pass/fail
decision and reported separately as `harness_error_rate`
(`VALIDATION.md` §8). The full §8 metric set — error recovery, requirement
coverage, clarification rate, review catch rate split by channel, spec
tampering — is in each artifact's `metrics` object; this page carries the
columns a leaderboard is for.

## Reproducing a row

```console
$ heph bench run --provider providers.json --model <id> --seeds 3
$ heph bench score bench/results/<id>/<date>
$ heph bench leaderboard --out docs/leaderboard.md
```

The public corpus split is what ships in `corpus/`; the private gate split
lives in a separate restricted repository and is never published, so a
reproduced public number is a check on the harness, not the gate itself
(`verification.md`).
