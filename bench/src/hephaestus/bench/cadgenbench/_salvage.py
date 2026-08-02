"""``package --from-archive``: export a run's STEP from its archived artifact.

``EXTERNAL_EVAL.md`` §5 (salvage export): the 2026-07-29 autopsy found runs
that had *built* a correct-status candidate and then died — infra deaths, budget
kills — before the grader's export produced ``output.step``. The geometry
exists, published and content-addressed, inside the archived project's blob
store; refusing to submit it would be throwing away finished work over our own
harness failure.

So the salvage is exactly what the normal export path does with an artifact,
minus the ops ceremony that would write into the archive: the deliverable's
**current, successful** build is looked up in the archived grade record, its
BRep blob is read straight out of the archived project's content-addressed
store (read-only — ``bench/results/`` is evidence and is never written), the
shape is rebuilt (:func:`hephaestus.geom.step_io.shape_from_brep`) and written
as STEP into the submission outputs tree. Same geometry, same provenance chain:
the artifact ref travels into the packaging notes.

It never resurrects a failed build. A sample whose archived run has no current
successful deliverable build is refused **by name** — ``no_archived_run``,
``no_deliverable_build``, ``deliverable_build_failed``,
``deliverable_build_not_current``, ``artifact_blob_missing`` — never silently
skipped and never "helpfully" exported anyway.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ._convert import PART_NAME, TASK_ID_PREFIX, sample_id_for_task
from ._package import SUBMISSION_CANDIDATE, _candidate  # pyright: ignore[reportPrivateUsage]
from ._validity import step_validity

__all__ = [
    "SALVAGE_REPORT_FILENAME",
    "SalvageEntry",
    "SalvageReport",
    "salvage_from_archive",
]

#: Written into the outputs root (never into a sample folder, so the ZIP layout
#: is untouched): the packaging notes' record of what was salvaged from where.
SALVAGE_REPORT_FILENAME = "salvage.json"

#: Refusal precedence, weakest first: when several archived runs exist for one
#: sample, the reported refusal is the most specific thing the archive proved.
_REFUSAL_ORDER: tuple[str, ...] = (
    "no_archived_run",
    "no_deliverable_build",
    "deliverable_build_failed",
    "deliverable_build_not_current",
    "artifact_blob_missing",
    "unreadable_artifact",
    "invalid_salvaged_step",
)


@dataclass(frozen=True)
class SalvageEntry:
    """One sample's salvage outcome: exported, already present, or refused."""

    sample_id: str
    #: ``exported`` / ``already_present`` / a named refusal (see module doc).
    status: str
    artifact_ref: str | None = None
    run_dir: str | None = None
    output: str | None = None
    detail: str | None = None

    @property
    def exported(self) -> bool:
        return self.status == "exported"

    @property
    def refused(self) -> bool:
        return self.status not in ("exported", "already_present")

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "status": self.status,
            "artifact_ref": self.artifact_ref,
            "run_dir": self.run_dir,
            "output": self.output,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SalvageReport:
    """What one ``--from-archive`` pass exported, and what it refused, by name."""

    archive_dir: Path
    outputs_dir: Path
    entries: tuple[SalvageEntry, ...] = ()

    @property
    def exported(self) -> tuple[SalvageEntry, ...]:
        return tuple(e for e in self.entries if e.exported)

    @property
    def refusals(self) -> tuple[SalvageEntry, ...]:
        return tuple(e for e in self.entries if e.refused)

    def to_json(self) -> dict[str, Any]:
        return {
            "archive_dir": str(self.archive_dir),
            "outputs_dir": str(self.outputs_dir),
            "n_exported": len(self.exported),
            "n_refused": len(self.refusals),
            "entries": [entry.to_json() for entry in self.entries],
        }


def _load_records(archive_dir: Path) -> dict[str, list[tuple[Path, Mapping[str, Any]]]]:
    """Archived CADGenBench run records, grouped by sample id, in run order."""
    by_sample: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {}
    if not archive_dir.is_dir():
        return by_sample
    for run_dir in sorted(p for p in archive_dir.iterdir() if p.is_dir()):
        result = run_dir / "result.json"
        if not result.is_file():
            continue
        raw = json.loads(result.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        record = cast("Mapping[str, Any]", raw)
        task_id = str(record.get("task_id", ""))
        if not task_id.startswith(TASK_ID_PREFIX):
            continue
        by_sample.setdefault(sample_id_for_task(task_id), []).append((run_dir, record))
    return by_sample


def _deliverable_build(record: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str | None]:
    """``(build result, refusal)`` for the record's deliverable part."""
    grade = record.get("grade")
    builds = cast("Mapping[str, Any]", grade).get("builds") if isinstance(grade, dict) else None
    build = cast("Mapping[str, Any]", builds).get(PART_NAME) if isinstance(builds, dict) else None
    if not isinstance(build, dict):
        return None, "no_deliverable_build"
    entry = cast("Mapping[str, Any]", build)
    if entry.get("status") != "ok":
        return None, "deliverable_build_failed"
    if not bool(entry.get("current")):
        # A preview or superseded publication is not the run's final geometry;
        # §5 is explicit that salvage never resurrects anything but CURRENT.
        return None, "deliverable_build_not_current"
    if not isinstance(entry.get("artifact_ref"), str) or not entry["artifact_ref"]:
        return None, "no_deliverable_build"
    return entry, None


def _artifact_blob_path(record: Mapping[str, Any], artifact_ref: str) -> tuple[Path | None, str]:
    """The archived project's content-addressed blob file for the artifact.

    The path is derived, not opened through the opstore: opening the store
    would take locks and write WAL state inside ``bench/results/``, which is
    read-only evidence. The CAS layout is stable (``.heph/blobs/sha256/…``) and
    the read is a plain file read.
    """
    from hephaestus.core.project_store.store import blob_hash_of_ref

    project_dir = record.get("project_dir")
    if not isinstance(project_dir, str) or not project_dir:
        return None, "artifact_blob_missing"
    try:
        digest = blob_hash_of_ref(artifact_ref).split(":", 1)[1]
    except Exception:
        return None, "artifact_blob_missing"
    return Path(project_dir) / ".heph" / "blobs" / "sha256" / digest[:2] / digest, digest


def _salvage_one(
    sample_id: str, runs: Sequence[tuple[Path, Mapping[str, Any]]], target: Path
) -> SalvageEntry:
    """Export the first salvageable run's artifact, or the best-named refusal."""
    from hephaestus.geom.step_io import shape_from_brep, write_step

    refusal = "no_archived_run"
    refusal_run: str | None = None
    for run_dir, record in runs:
        build, reason = _deliverable_build(record)
        if build is None:
            assert reason is not None
            if _REFUSAL_ORDER.index(reason) > _REFUSAL_ORDER.index(refusal):
                refusal, refusal_run = reason, str(run_dir)
            continue
        artifact_ref = str(build["artifact_ref"])
        blob_path, _digest = _artifact_blob_path(record, artifact_ref)
        if blob_path is None or not blob_path.is_file():
            if _REFUSAL_ORDER.index("artifact_blob_missing") > _REFUSAL_ORDER.index(refusal):
                refusal, refusal_run = "artifact_blob_missing", str(run_dir)
            continue
        try:
            shape = shape_from_brep(blob_path.read_bytes(), source=artifact_ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_step(shape, target)
        except Exception as exc:
            return SalvageEntry(
                sample_id=sample_id,
                status="unreadable_artifact",
                artifact_ref=artifact_ref,
                run_dir=str(run_dir),
                detail=f"{type(exc).__name__}: {exc}",
            )
        facts = step_validity(target)
        if not facts.ok:
            # A salvaged candidate that would fail the local floor is worse
            # than an honest refusal: delete it and say why.
            target.unlink(missing_ok=True)
            return SalvageEntry(
                sample_id=sample_id,
                status="invalid_salvaged_step",
                artifact_ref=artifact_ref,
                run_dir=str(run_dir),
                detail=",".join(facts.failures),
            )
        return SalvageEntry(
            sample_id=sample_id,
            status="exported",
            artifact_ref=artifact_ref,
            run_dir=str(run_dir),
            output=str(target),
        )
    return SalvageEntry(sample_id=sample_id, status=refusal, run_dir=refusal_run)


def salvage_from_archive(
    archive_dir: Path,
    outputs_dir: Path,
    *,
    sample_ids: Sequence[str] | None = None,
) -> SalvageReport:
    """Fill missing submission candidates from the archived runs' artifacts.

    A sample that already has a candidate in ``outputs_dir`` is left exactly as
    it is (``already_present``): the grader's own export always wins over a
    salvage. Everything else is exported from the archive when — and only when
    — a run holds a current, successful deliverable build; otherwise the entry
    is a named refusal. The report is also written to
    ``outputs_dir/salvage.json`` so the packaging notes carry the artifact refs.
    """
    by_sample = _load_records(archive_dir)
    wanted = tuple(sample_ids) if sample_ids is not None else tuple(sorted(by_sample))
    entries: list[SalvageEntry] = []
    for sample_id in wanted:
        directory = outputs_dir / sample_id
        if directory.is_dir() and _candidate(directory) is not None:
            entries.append(SalvageEntry(sample_id=sample_id, status="already_present"))
            continue
        target = directory / SUBMISSION_CANDIDATE
        entries.append(_salvage_one(sample_id, by_sample.get(sample_id, ()), target))
    report = SalvageReport(
        archive_dir=archive_dir, outputs_dir=outputs_dir, entries=tuple(entries)
    )
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / SALVAGE_REPORT_FILENAME).write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
