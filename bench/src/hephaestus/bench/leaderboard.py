# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Generate the model-leaderboard page from archived bench artifacts.

`mission_plan.md` §"Stage 7H" names "the model-leaderboard page generated from
bench artifacts" as a release deliverable, and `verification.md` says the bench
"doubles as the model leaderboard deliverable", with the scoring artifact at
``bench/results/<model>/<date>.json``. Those files are the rows; this module is
the only thing that turns them into `docs/leaderboard.md`.

Three properties the generator is held to:

**It reads, it never scores.** Every number on the page is copied out of an
artifact `heph bench score` already wrote. The generator computes nothing that
could disagree with the archived evidence — not a pass rate, not a Wilson bound,
not the gate verdict. A leaderboard that re-derives statistics is a second
scorer, and a second scorer eventually differs from the first.

**It is deterministic.** Same artifacts in, byte-identical page out: rows sort by
model then date, and nothing about the wall clock, the filesystem order, or the
host reaches the output. `--check` therefore means something in CI.

**It reports the interpretation tax as a first-class column.** `VALIDATION.md`
§8 lists ``interpretation_gap`` (seeded − prose) as a reported metric and
`verification.md` calls the prose-vs-seeded gap "a published leaderboard
column". The two pass rates are shown side by side and never averaged.

Artifacts predating the 2026-07-25 seeding amendment carry no ``splits`` table:
they measured one unsplit corpus-v0 aggregate. Those rows render their number in
the prose column marked ``†`` and their gap as ``n/a``, because `VALIDATION.md`
§1 is explicit that "post-seeding numbers are never compared against
pre-amendment results" — the marker is what stops the table from implying the
comparison its own layout invites.

Only ``<date>.json`` files are rows. Sibling artifacts in the same directory —
``seeded_baseline.json``, ``cadgenbench-local-floor-<date>.json`` — are
different measurements with different meanings, and a leaderboard that swept up
every JSON beside a result would silently publish them as corpus runs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

__all__ = [
    "DATE_FILE_RE",
    "LeaderboardRow",
    "generate",
    "load_rows",
    "render",
    "row_from_artifact",
]

#: Result artifacts are named for the date they scored; nothing else is a row.
DATE_FILE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")

#: Marks a row whose numbers predate the prose/seeded split amendment.
PRE_SPLIT_MARK: Final[str] = "†"

_HEADER: Final[tuple[str, ...]] = (
    "Model",
    "Date",
    "Runs",
    "Prose pass rate",
    "Seeded pass rate",
    "Wilson lower-90",
    "Interpretation gap",
    "Meets gate",
)


@dataclass(frozen=True)
class LeaderboardRow:
    """One scored corpus run, as the page shows it.

    Every field is transcribed from the artifact. ``split_measured`` is False for
    pre-amendment artifacts, which is what earns the row its ``†``.
    """

    model: str
    date: str
    runs: int
    split_measured: bool
    prose_passes: int
    prose_n: int
    prose_rate: float
    seeded_passes: int | None
    seeded_n: int | None
    seeded_rate: float | None
    wilson_lower_90: float
    gated_split: str
    interpretation_gap: float | None
    meets_gate: bool
    threshold: float | None

    @property
    def sort_key(self) -> tuple[str, str]:
        """Model then date — the total order the page is written in."""
        return (self.model, self.date)


def _require(payload: Mapping[str, Any], key: str, *, source: str) -> Any:
    if key not in payload:
        raise ValueError(f"{source}: result artifact is missing required key {key!r}")
    return payload[key]


def _split(payload: Mapping[str, Any], name: str, *, source: str) -> Mapping[str, Any] | None:
    splits: object = payload.get("splits")
    if not isinstance(splits, Mapping):
        return None
    entry: object = cast("Mapping[str, Any]", splits).get(name)
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise ValueError(f"{source}: splits.{name} must be an object")
    return cast("Mapping[str, Any]", entry)


def row_from_artifact(payload: Mapping[str, Any], *, source: str) -> LeaderboardRow:
    """Build one row from a parsed ``bench/results/<model>/<date>.json`` document.

    ``source`` names the file in any error, because the first thing anyone asks
    about a malformed leaderboard is which artifact produced it.
    """
    model = str(_require(payload, "model", source=source))
    date = str(_require(payload, "date", source=source))

    prose = _split(payload, "prose", source=source)
    seeded = _split(payload, "seeded", source=source)
    split_measured = prose is not None

    if prose is not None:
        prose_n = int(prose["n"])
        prose_passes = int(prose["passes"])
        prose_rate = float(prose["pass_rate"])
    else:
        # Pre-amendment: one unsplit aggregate over the whole corpus.
        prose_n = int(_require(payload, "n", source=source))
        prose_passes = int(_require(payload, "passes", source=source))
        prose_rate = float(_require(payload, "aggregate", source=source))

    if seeded is not None:
        seeded_n: int | None = int(seeded["n"])
        seeded_passes: int | None = int(seeded["passes"])
        seeded_rate: float | None = float(seeded["pass_rate"])
    else:
        seeded_n = seeded_passes = None
        seeded_rate = None

    runs = int(payload.get("n_total", prose_n + (seeded_n or 0)))
    gap_raw = payload.get("interpretation_gap")
    gap = float(gap_raw) if isinstance(gap_raw, int | float) else None
    threshold_raw = payload.get("threshold")
    threshold = float(threshold_raw) if isinstance(threshold_raw, int | float) else None

    return LeaderboardRow(
        model=model,
        date=date,
        runs=runs,
        split_measured=split_measured,
        prose_passes=prose_passes,
        prose_n=prose_n,
        prose_rate=prose_rate,
        seeded_passes=seeded_passes,
        seeded_n=seeded_n,
        seeded_rate=seeded_rate,
        wilson_lower_90=float(_require(payload, "wilson_lower_90", source=source)),
        gated_split=str(payload.get("gated_split", "aggregate")),
        interpretation_gap=gap,
        meets_gate=bool(_require(payload, "meets_gate", source=source)),
        threshold=threshold,
    )


def load_rows(results_dir: Path) -> list[LeaderboardRow]:
    """Read every ``<model>/<date>.json`` under ``results_dir``, sorted for output.

    A missing directory yields no rows rather than raising: a checkout that has
    not run the bench still builds its docs.
    """
    rows: list[LeaderboardRow] = []
    if not results_dir.is_dir():
        return rows
    for model_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        for artifact in sorted(p for p in model_dir.iterdir() if DATE_FILE_RE.match(p.name)):
            payload: object = json.loads(artifact.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError(f"{artifact}: result artifact must be a JSON object")
            rows.append(row_from_artifact(cast("Mapping[str, Any]", payload), source=str(artifact)))
    rows.sort(key=lambda row: row.sort_key)
    return rows


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _rate_cell(passes: int | None, n: int | None, rate: float | None, *, mark: str = "") -> str:
    if rate is None or passes is None or n is None:
        return "n/a"
    return f"{_pct(rate)} ({passes}/{n}){mark}"


def _gap_cell(gap: float | None) -> str:
    if gap is None:
        return "n/a"
    return f"{gap * 100:+.1f} pp"


def _table(rows: Sequence[LeaderboardRow]) -> list[str]:
    lines = [
        "| " + " | ".join(_HEADER) + " |",
        "|" + "|".join(["---"] * len(_HEADER)) + "|",
    ]
    for row in rows:
        mark = "" if row.split_measured else PRE_SPLIT_MARK
        cells = (
            f"`{row.model}`",
            row.date,
            str(row.runs),
            _rate_cell(row.prose_passes, row.prose_n, row.prose_rate, mark=mark),
            _rate_cell(row.seeded_passes, row.seeded_n, row.seeded_rate),
            f"{row.wilson_lower_90:.3f} ({row.gated_split})",
            _gap_cell(row.interpretation_gap),
            "yes" if row.meets_gate else "no",
        )
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render(rows: Sequence[LeaderboardRow]) -> str:
    """Render the full `docs/leaderboard.md` page. Pure function of ``rows``."""
    out: list[str] = [
        "<!--",
        "Copyright 2026 The Hephaestus Authors",
        "SPDX-License-Identifier: Apache-2.0",
        "",
        "GENERATED FILE — do not edit by hand.",
        "Regenerate with: heph bench leaderboard --out docs/leaderboard.md",
        "Source: bench/results/<model>/<date>.json (hephaestus.bench.leaderboard)",
        "-->",
        "",
        "# Model leaderboard",
        "",
        "Which models can actually do CAD in this harness, measured the same way",
        "every time. Each row is one scored corpus run archived under",
        "`bench/results/<model>/<date>.json`; the page is generated from those",
        "artifacts and never edits them.",
        "",
    ]
    if not rows:
        out += [
            "No scored runs are archived in this checkout.",
            "",
        ]
    else:
        out += _table(rows)
        out += [""]
    out += [
        "## Reading the table",
        "",
        "- **Runs** is every scored (task, seed, split) run behind the row. A split's",
        "  own denominator is shown inside its cell.",
        "- **Prose** and **seeded** pass rates are separate measurements with",
        "  independently baselined thresholds, and are never averaged into one",
        "  number (`VALIDATION.md` §1). Prose measures interpreting a request;",
        "  seeded measures iterating to green against checks installed as an",
        "  independent spec.",
        "- **Wilson lower-90** is the one-sided lower 90% Wilson bound on the gated",
        "  split's pass rate — the quantity a gate compares against, so that tiny-n",
        "  luck cannot pass a stage (`verification.md`). The split it was taken over",
        "  is named in the cell.",
        "- **Interpretation gap** is seeded − prose: the interpretation tax. A large",
        "  positive gap says the model can build what it is told precisely and",
        "  struggles to work out what was meant.",
        "- **Meets gate** is the verdict recorded in the artifact, not a judgment",
        "  made here.",
        f"- **{PRE_SPLIT_MARK}** marks an unsplit corpus-v0 aggregate from before the",
        "  2026-07-25 seeding amendment. It is shown in the prose column because",
        "  that is the closest thing it measured, but it is **not** comparable to a",
        "  post-amendment prose rate (`VALIDATION.md` §1) and has no gap to report.",
        "",
        "Harness errors are measured and never charged to the model: a run whose",
        "only failure reason is harness-attributable is excluded from the pass/fail",
        "decision and reported separately as `harness_error_rate`",
        "(`VALIDATION.md` §8). The full §8 metric set — error recovery, requirement",
        "coverage, clarification rate, review catch rate split by channel, spec",
        "tampering — is in each artifact's `metrics` object; this page carries the",
        "columns a leaderboard is for.",
        "",
        "## Reproducing a row",
        "",
        "```console",
        "$ heph bench run --provider providers.json --model <id> --seeds 3",
        "$ heph bench score bench/results/<id>/<date>",
        "$ heph bench leaderboard --out docs/leaderboard.md",
        "```",
        "",
        "The public corpus split is what ships in `corpus/`; the private gate split",
        "lives in a separate restricted repository and is never published, so a",
        "reproduced public number is a check on the harness, not the gate itself",
        "(`verification.md`).",
        "",
    ]
    return "\n".join(out)


def generate(results_dir: Path, out_path: Path) -> str:
    """Render the page from ``results_dir`` and write it to ``out_path``."""
    text = render(load_rows(results_dir))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text
