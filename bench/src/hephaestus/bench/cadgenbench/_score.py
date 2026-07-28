"""The local pre-score — a floor, and labelled as one (``EXTERNAL_EVAL.md`` §2).

CADGenBench's ground truth is private to the leaderboard Space, so **no local
computation can produce a CAD Score**. What can be produced locally is:

1. the validity floor (:mod:`._validity`) — the gate that zeroes a sample, and
   the one thing whose failure is knowable without ground truth; and
2. for editing samples, ``bench.scoring.score_step_files`` facts against the
   *starting solid* — the only reference geometry the public dataset ships.
   Those facts measure **departure from the input**, not correctness: a large
   IoU against the start means the edit barely happened (the grader's
   ``b_shape`` no-op baseline caps such a sample at 0.4), and a small one means
   it changed a lot, rightly or wrongly. The reference is named in every row so
   the number can never be read as agreement with ground truth.

Every artifact this module produces carries :data:`LOCAL_FLOOR_LABEL`, in those
words, at the top level. A benchmark adapter that printed a bare number next to
a leaderboard's name would be inviting exactly the misreading the stage exists
to avoid.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._package import CANDIDATE_NAMES
from ._samples import EDITING, SampleError, load_sample
from ._validity import ValidityFacts, step_validity

__all__ = [
    "LOCAL_FLOOR_LABEL",
    "SampleFloor",
    "SubmissionFloor",
    "score_outputs",
]

#: The words every score artifact carries, literally.
LOCAL_FLOOR_LABEL = (
    "local floor: geom validity (sealed, positive volume, finite bbox) plus "
    "score_step_files facts where the public dataset ships reference geometry. "
    "This is NOT the CADGenBench cad_score — ground truth is private to the "
    "leaderboard, and no local computation can produce that number."
)


@dataclass(frozen=True)
class SampleFloor:
    """One sample's floor: its status, its validity facts, its diff facts."""

    sample_id: str
    #: ``valid`` | ``invalid`` | ``missing`` (the benchmark's own vocabulary).
    status: str
    validity: ValidityFacts | None = None
    #: What the ``step_score`` was measured against, when anything was.
    reference: str | None = None
    step_score: Mapping[str, Any] | None = None
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "status": self.status,
            "validity": None if self.validity is None else self.validity.to_json(),
            "reference": self.reference,
            "step_score": None if self.step_score is None else dict(self.step_score),
            "note": self.note,
        }


@dataclass(frozen=True)
class SubmissionFloor:
    """The whole pre-score, labelled."""

    entries: tuple[SampleFloor, ...] = ()
    label: str = LOCAL_FLOOR_LABEL

    @property
    def n_valid(self) -> int:
        return sum(1 for e in self.entries if e.status == "valid")

    @property
    def n_invalid(self) -> int:
        return sum(1 for e in self.entries if e.status == "invalid")

    @property
    def n_missing(self) -> int:
        return sum(1 for e in self.entries if e.status == "missing")

    def to_json(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n_samples": len(self.entries),
            "n_valid": self.n_valid,
            "n_invalid": self.n_invalid,
            "n_missing": self.n_missing,
            "entries": [entry.to_json() for entry in self.entries],
        }


def _candidate(directory: Path) -> Path | None:
    for name in CANDIDATE_NAMES:
        path = directory / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _editing_start(dataset_root: Path | None, sample_id: str) -> Path | None:
    """The editing sample's starting solid, when the dataset is at hand."""
    if dataset_root is None:
        return None
    try:
        sample = load_sample(dataset_root / sample_id)
    except (SampleError, FileNotFoundError):
        return None
    if sample.task_type != EDITING or not sample.step_inputs:
        return None
    return sample.input_path(sample.step_inputs[0])


def score_outputs(
    outputs_dir: Path,
    sample_ids: Sequence[str],
    *,
    dataset_root: Path | None = None,
    policy: Mapping[str, Any] | None = None,
) -> SubmissionFloor:
    """Apply the floor to every produced candidate under ``outputs_dir``."""
    from hephaestus.bench.scoring import score_step_files

    entries: list[SampleFloor] = []
    for sample_id in sample_ids:
        directory = outputs_dir / sample_id
        candidate = _candidate(directory) if directory.is_dir() else None
        if candidate is None:
            entries.append(SampleFloor(sample_id=sample_id, status="missing"))
            continue
        facts = step_validity(candidate)
        status = "valid" if facts.ok else "invalid"
        start = _editing_start(dataset_root, sample_id)
        if start is None:
            entries.append(SampleFloor(sample_id=sample_id, status=status, validity=facts))
            continue
        score = score_step_files(candidate, start, policy)
        entries.append(
            SampleFloor(
                sample_id=sample_id,
                status=status,
                validity=facts,
                reference="editing_start",
                step_score=score.to_json(),
                note=(
                    "measured against the sample's own starting solid, not ground "
                    "truth: this quantifies how much the edit changed, never whether "
                    "it changed the right thing"
                ),
            )
        )
    return SubmissionFloor(entries=tuple(entries))
