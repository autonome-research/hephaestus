# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The leaderboard page is a pure, deterministic function of the bench artifacts.

`mission_plan.md` §"Stage 7H" ships "the model-leaderboard page generated from
bench artifacts", and G7H requires `bench.yml` to publish it. A generated release
artifact is only worth anything if two properties hold, and both are tested here
rather than asserted in prose:

**Deterministic.** The same artifacts produce a byte-identical page, whatever
order the filesystem hands the directories back in. Without that, `heph bench
leaderboard --check` is noise in CI and the page churns in every diff.

**Transcribing, not scoring.** Every number on the page is copied out of an
artifact `heph bench score` already wrote. The test proves this the only way it
can be proved — by feeding the generator an artifact whose archived
``wilson_lower_90`` and ``meets_gate`` do not follow from its own counts, and
requiring the page to publish the archived values. A generator that recomputed
would "fix" them, and the page would then disagree with the evidence it cites.

The fixture rows are synthetic on purpose: real artifacts change when the bench
is re-run, and a test that moved with them would assert nothing. The archived
rows are covered separately, by checking that the committed page is exactly what
the committed artifacts render to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hephaestus.bench import leaderboard

REPO = Path(__file__).resolve().parents[2]

#: A pre-amendment corpus-v0 artifact: one unsplit aggregate, no `splits` table.
PRE_SPLIT_ARTIFACT: dict[str, Any] = {
    "model": "fixture-old",
    "date": "2026-01-02",
    "n": 10,
    "passes": 3,
    "aggregate": 0.3,
    "wilson_lower_90": 0.123,
    "meets_gate": False,
}

#: A post-amendment artifact: prose and seeded measured separately, prose gated.
SPLIT_ARTIFACT: dict[str, Any] = {
    "model": "fixture-new",
    "date": "2026-03-04",
    "n_total": 24,
    "splits": {
        "prose": {"n": 12, "passes": 9, "pass_rate": 0.75},
        "seeded": {"n": 12, "passes": 11, "pass_rate": 0.9166666666666666},
    },
    "wilson_lower_90": 0.7010,
    "gated_split": "prose",
    "interpretation_gap": 0.16666666666666663,
    "meets_gate": True,
    "threshold": 0.7,
}

#: The exact table the two fixtures above must render to. Every cell is checked
#: by eye against the artifact it came from: rates are one decimal with the
#: split's own denominator beside them, the pre-amendment row wears the dagger
#: and has no gap, and the Wilson bound names the split it was taken over.
EXPECTED_TABLE = """\
| Model | Date | Runs | Prose pass rate | Seeded pass rate | Wilson lower-90 | \
Interpretation gap | Meets gate |
|---|---|---|---|---|---|---|---|
| `fixture-new` | 2026-03-04 | 24 | 75.0% (9/12) | 91.7% (11/12) | 0.701 (prose) \
| +16.7 pp | yes |
| `fixture-old` | 2026-01-02 | 10 | 30.0% (3/10)† | n/a | 0.123 (aggregate) | n/a | no |"""


def _write(results_dir: Path, artifact: dict[str, Any], *, name: str | None = None) -> Path:
    model_dir = results_dir / str(artifact["model"])
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / (name or f"{artifact['date']}.json")
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    """Both fixture artifacts, written in the *opposite* order to their sort."""
    directory = tmp_path / "results"
    _write(directory, PRE_SPLIT_ARTIFACT)
    _write(directory, SPLIT_ARTIFACT)
    return directory


def test_fixture_rows_render_the_exact_table(results_dir: Path) -> None:
    """The generated table is byte-exact, down to the dagger and the sign."""
    page = leaderboard.render(leaderboard.load_rows(results_dir))
    assert EXPECTED_TABLE in page, page


def test_rows_sort_by_model_then_date_not_by_filesystem_order(results_dir: Path) -> None:
    """`fixture-new` precedes `fixture-old` though it was written second."""
    rows = leaderboard.load_rows(results_dir)
    assert [row.sort_key for row in rows] == [
        ("fixture-new", "2026-03-04"),
        ("fixture-old", "2026-01-02"),
    ]


def test_the_page_is_byte_identical_across_regeneration(results_dir: Path, tmp_path: Path) -> None:
    """Same artifacts in, same bytes out — what makes `--check` meaningful."""
    first = leaderboard.generate(results_dir, tmp_path / "a" / "leaderboard.md")
    second = leaderboard.generate(results_dir, tmp_path / "b" / "leaderboard.md")
    assert first == second
    assert (tmp_path / "a" / "leaderboard.md").read_bytes() == (
        tmp_path / "b" / "leaderboard.md"
    ).read_bytes()


def test_archived_numbers_are_transcribed_never_recomputed(tmp_path: Path) -> None:
    """A bound that does not follow from the counts is still published verbatim.

    9/12 could not produce a lower-90 bound of 0.999, and a 0.75 rate does not
    clear a 0.9 threshold. The page must show what the scorer archived anyway:
    the leaderboard is a view over the evidence, not a second opinion on it.
    """
    artifact = dict(SPLIT_ARTIFACT, wilson_lower_90=0.999, threshold=0.9, meets_gate=True)
    directory = tmp_path / "results"
    _write(directory, artifact)

    page = leaderboard.render(leaderboard.load_rows(directory))
    assert "0.999 (prose)" in page
    assert "| 75.0% (9/12) |" in page
    assert page.count("| yes |") == 1


def test_only_dated_artifacts_are_rows(tmp_path: Path) -> None:
    """Siblings of a result are different measurements, not leaderboard rows."""
    directory = tmp_path / "results"
    _write(directory, SPLIT_ARTIFACT)
    _write(directory, dict(SPLIT_ARTIFACT, wilson_lower_90=0.0), name="seeded_baseline.json")
    _write(
        directory,
        dict(SPLIT_ARTIFACT, wilson_lower_90=0.0),
        name="cadgenbench-local-floor-2026-08-01.json",
    )

    rows = leaderboard.load_rows(directory)
    assert [row.wilson_lower_90 for row in rows] == [0.7010]


def test_a_checkout_with_no_bench_results_still_renders(tmp_path: Path) -> None:
    """Docs must build on a tree that has never run the bench."""
    page = leaderboard.render(leaderboard.load_rows(tmp_path / "absent"))
    assert "No scored runs are archived in this checkout." in page
    assert "| Model | Date |" not in page


def test_a_malformed_artifact_names_the_file_that_broke(tmp_path: Path) -> None:
    """The first question about a bad leaderboard is which artifact caused it."""
    directory = tmp_path / "results"
    broken = _write(directory, {"model": "fixture-new", "date": "2026-03-04"})

    with pytest.raises(ValueError) as excinfo:
        leaderboard.load_rows(directory)
    assert str(broken) in str(excinfo.value)


def test_the_committed_page_matches_the_committed_artifacts() -> None:
    """`docs/leaderboard.md` is not stale with respect to `bench/results/`.

    This is `heph bench leaderboard --check` as a test, so a re-scored run that
    lands without regenerating the page fails here rather than shipping a page
    that contradicts its own sources.
    """
    expected = leaderboard.render(leaderboard.load_rows(REPO / "bench" / "results"))
    published = (REPO / "docs" / "leaderboard.md").read_text(encoding="utf-8")
    assert published == expected, (
        "docs/leaderboard.md is stale; regenerate with "
        "`uv run heph bench leaderboard --out docs/leaderboard.md`"
    )


def test_the_published_page_carries_the_gap_column_and_both_split_rates() -> None:
    """VALIDATION.md §8's interpretation gap is a first-class column, not a note."""
    published = (REPO / "docs" / "leaderboard.md").read_text(encoding="utf-8")
    header = next(line for line in published.splitlines() if line.startswith("| Model |"))
    assert "Prose pass rate" in header
    assert "Seeded pass rate" in header
    assert "Interpretation gap" in header
    # The two rates are reported side by side and never collapsed into one.
    assert "aggregate pass rate" not in published.lower()
