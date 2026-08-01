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

import multiprocessing
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ._package import CANDIDATE_NAMES
from ._samples import EDITING, SampleError, load_sample
from ._validity import ValidityFacts, step_validity

__all__ = [
    "LOCAL_FLOOR_LABEL",
    "SAMPLE_TIMEOUT_S",
    "SampleFloor",
    "SubmissionFloor",
    "score_outputs",
]

#: Wall-clock ceiling for ONE sample's floor computation, process-killed with
#: no retry — CADGenBench's own MESH_TIMEOUT_S policy, applied to ours. OCCT
#: booleans on pathological candidates can grind for hours (one CADGenBench
#: editing candidate held a single core for ~19 h on 2026-07-30), so unbounded
#: per-sample work turns an 81-sample report into a hang. Env-overridable via
#: ``HEPHAESTUS_CGB_SAMPLE_TIMEOUT_S``, exactly as the benchmark's ceilings are.
SAMPLE_TIMEOUT_S: Final[float] = 300.0

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


def _floor_child(
    conn: Any,
    candidate: str,
    start: str | None,
    policy: dict[str, Any] | None,
) -> None:  # pragma: no cover - runs in a spawned child process
    """One sample's floor, computed where a kill cannot take the report down."""
    from hephaestus.bench.scoring import score_step_files

    # Validity ships the moment it is known: it is the load-bearing local fact
    # (the leaderboard zeroes invalid samples), and the diff half below can be
    # orders of magnitude more expensive — a ceiling kill after this send
    # still leaves a validity row behind.
    facts = step_validity(Path(candidate))
    conn.send(("validity", facts))
    if start is not None:
        score_json = score_step_files(Path(candidate), Path(start), policy).to_json()
        conn.send(("score", score_json))
    conn.close()


def _bounded_floor(
    candidate: Path,
    start: Path | None,
    policy: Mapping[str, Any] | None,
    timeout_s: float,
) -> tuple[ValidityFacts | None, dict[str, Any] | None, str | None]:
    """Run one sample's floor under the wall-clock ceiling.

    Returns ``(validity, score_json, refusal)``. The child streams validity
    the moment it is known, so a ceiling kill in the (far more expensive)
    diff half still returns the validity facts; ``refusal`` is ``None`` on a
    complete run, else ``timeout`` or ``crashed:<exitcode>`` naming what cut
    the computation short.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_floor_child,
        args=(child, str(candidate), None if start is None else str(start),
              None if policy is None else dict(policy)),
    )
    proc.start()
    child.close()
    validity: ValidityFacts | None = None
    score_json: dict[str, Any] | None = None
    refusal: str | None = "timeout"
    expect_score = start is not None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if parent.poll(0.25):
            kind, payload = parent.recv()
            if kind == "validity":
                validity = payload
                if not expect_score:
                    refusal = None
                    break
            else:
                score_json = payload
                refusal = None
                break
        elif not proc.is_alive():
            refusal = None if (validity is not None and not expect_score) else (
                f"crashed:{proc.exitcode}"
            )
            break
    if proc.is_alive():
        proc.kill()
    proc.join()
    parent.close()
    return validity, score_json, refusal


def score_outputs(
    outputs_dir: Path,
    sample_ids: Sequence[str],
    *,
    dataset_root: Path | None = None,
    policy: Mapping[str, Any] | None = None,
    sample_timeout_s: float | None = None,
) -> SubmissionFloor:
    """Apply the floor to every produced candidate under ``outputs_dir``.

    Each sample computes in its own spawned process under
    ``sample_timeout_s`` (default :data:`SAMPLE_TIMEOUT_S`, env-overridable
    via ``HEPHAESTUS_CGB_SAMPLE_TIMEOUT_S``): a sample that exceeds it or
    crashes the kernel is ``invalid`` with the reason in its note, and the
    other 80 still report — one pathological candidate is one row, never a
    hung report.
    """
    if sample_timeout_s is None:
        sample_timeout_s = float(
            os.environ.get("HEPHAESTUS_CGB_SAMPLE_TIMEOUT_S", SAMPLE_TIMEOUT_S)
        )

    entries: list[SampleFloor] = []
    for sample_id in sample_ids:
        directory = outputs_dir / sample_id
        candidate = _candidate(directory) if directory.is_dir() else None
        if candidate is None:
            entries.append(SampleFloor(sample_id=sample_id, status="missing"))
            continue
        start = _editing_start(dataset_root, sample_id)
        validity, score_json, refusal = _bounded_floor(
            candidate, start, policy, sample_timeout_s
        )
        if refusal is not None:
            cut_short = (
                f"floor computation exceeded {sample_timeout_s:g}s and was "
                "process-killed (CADGenBench MESH_TIMEOUT_S policy applied locally)"
                if refusal == "timeout"
                else f"floor computation died in the kernel ({refusal})"
            )
            if validity is None:
                entries.append(
                    SampleFloor(sample_id=sample_id, status="invalid", note=cut_short)
                )
            else:
                # Validity landed before the kill; only the diff facts are lost.
                entries.append(
                    SampleFloor(
                        sample_id=sample_id,
                        status="valid" if validity.ok else "invalid",
                        validity=validity,
                        note=f"step_score facts unavailable: {cut_short}",
                    )
                )
            continue
        assert validity is not None  # refusal is None only after a validity send
        status = "valid" if validity.ok else "invalid"
        if score_json is None:
            entries.append(SampleFloor(sample_id=sample_id, status=status, validity=validity))
            continue
        entries.append(
            SampleFloor(
                sample_id=sample_id,
                status=status,
                validity=validity,
                reference="editing_start",
                step_score=score_json,
                note=(
                    "measured against the sample's own starting solid, not ground "
                    "truth: this quantifies how much the edit changed, never whether "
                    "it changed the right thing"
                ),
            )
        )
    return SubmissionFloor(entries=tuple(entries))
