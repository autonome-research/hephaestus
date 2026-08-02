# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8D addendum (``EXTERNAL_EVAL.md`` §5): ``package --from-archive`` salvage.

A sample whose run built a CURRENT successful deliverable but never exported it
is exported from the archived build artifact — the BRep blob is read straight
out of the archived project's content-addressed store, re-shaped, and written
as ``output.step`` with the artifact ref recorded in the packaging notes
(``salvage.json``). It never resurrects a failed build: a failed, non-current
or absent build is refused by name, and nothing is written for it.

The archives here are authored fixtures in the real archive shape
(``<task>-s<seed>/result.json`` + the project's ``.heph/blobs`` CAS), with the
geometry produced by the product's own STEP reader/BRep writer over the suite's
committed plate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _g8d import STEPS
from hephaestus.bench.cadgenbench import (
    SALVAGE_REPORT_FILENAME,
    salvage_from_archive,
    step_validity,
)


@pytest.fixture(scope="module")
def plate_brep() -> tuple[bytes, str]:
    """The sealed plate as a published build artifact: BRep bytes + blob hash."""
    from hephaestus.geom.step_io import read_step, shape_to_brep

    from opstore import sha256_bytes

    data = shape_to_brep(read_step(STEPS / "plate.step"))
    return data, sha256_bytes(data)


def _archive_run(
    archive: Path,
    sample_id: str,
    plate_brep: tuple[bytes, str],
    *,
    seed: int = 1,
    status: str = "ok",
    current: bool = True,
    with_blob: bool = True,
    part: str = "candidate",
) -> str:
    """Author one archived run in the real shape; returns its artifact ref."""
    data, blob_hash = plate_brep
    digest = blob_hash.split(":", 1)[1]
    run_dir = archive / f"cadgenbench-{sample_id}-s{seed}"
    project = run_dir / "project"
    if with_blob:
        blob = project / ".heph" / "blobs" / "sha256" / digest[:2] / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
    artifact_ref = f"artifact:build:{blob_hash}"
    record: dict[str, Any] = {
        "task_id": f"cadgenbench-{sample_id}",
        "seed": seed,
        "project_dir": str(project),
        "grade": {
            "builds": {part: {"status": status, "current": current, "artifact_ref": artifact_ref}}
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return artifact_ref


def test_a_current_successful_build_is_exported_from_the_archive(
    tmp_path: Path, plate_brep: tuple[bytes, str]
) -> None:
    archive = tmp_path / "archive"
    outputs = tmp_path / "outputs"
    ref = _archive_run(archive, "101", plate_brep)

    report = salvage_from_archive(archive, outputs, sample_ids=["101"])

    (entry,) = report.entries
    assert entry.status == "exported"
    assert entry.artifact_ref == ref
    candidate = outputs / "101" / "output.step"
    assert Path(str(entry.output)) == candidate
    facts = step_validity(candidate)
    assert facts.ok, facts.to_json()
    # Same geometry: the archived plate's volume survives the round trip.
    assert facts.volume_mm3 == pytest.approx(800.0, rel=1e-6)
    # The packaging notes carry the provenance: sample -> artifact ref -> run.
    notes = json.loads((outputs / SALVAGE_REPORT_FILENAME).read_text(encoding="utf-8"))
    assert notes["entries"][0]["artifact_ref"] == ref
    assert notes["n_exported"] == 1


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"status": "error"}, "deliverable_build_failed"),
        ({"current": False}, "deliverable_build_not_current"),
        ({"part": "scratch"}, "no_deliverable_build"),
        ({"with_blob": False}, "artifact_blob_missing"),
    ],
)
def test_a_failed_or_absent_build_is_refused_by_name(
    tmp_path: Path, plate_brep: tuple[bytes, str], kwargs: dict[str, Any], refusal: str
) -> None:
    """§5: salvage never resurrects a failed build — it refuses, and says why."""
    archive = tmp_path / "archive"
    outputs = tmp_path / "outputs"
    _archive_run(archive, "101", plate_brep, **kwargs)

    report = salvage_from_archive(archive, outputs, sample_ids=["101"])

    (entry,) = report.entries
    assert entry.status == refusal
    assert entry.refused
    assert not (outputs / "101" / "output.step").exists()


def test_a_sample_with_no_archived_run_is_refused_by_name(tmp_path: Path) -> None:
    report = salvage_from_archive(tmp_path / "archive", tmp_path / "outputs", sample_ids=["999"])

    (entry,) = report.entries
    assert entry.status == "no_archived_run"


def test_the_graders_own_export_always_wins_over_a_salvage(
    tmp_path: Path, plate_brep: tuple[bytes, str]
) -> None:
    archive = tmp_path / "archive"
    outputs = tmp_path / "outputs"
    _archive_run(archive, "101", plate_brep)
    existing = outputs / "101" / "output.step"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"ISO-10303-21; the run's own export")

    report = salvage_from_archive(archive, outputs, sample_ids=["101"])

    (entry,) = report.entries
    assert entry.status == "already_present"
    assert existing.read_bytes() == b"ISO-10303-21; the run's own export"


def test_a_corpus_run_in_the_archive_is_never_read_as_a_sample(
    tmp_path: Path, plate_brep: tuple[bytes, str]
) -> None:
    archive = tmp_path / "archive"
    run_dir = archive / "bracket-101-s1"
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(
        json.dumps({"task_id": "bracket-101", "grade": {}}), encoding="utf-8"
    )
    _archive_run(archive, "101", plate_brep)

    report = salvage_from_archive(archive, tmp_path / "outputs")

    assert [entry.sample_id for entry in report.entries] == ["101"]
    assert report.entries[0].status == "exported"


# ==========================================================================
# `heph bench cadgenbench package --from-archive`: the operator's surface


def _package_argv(tmp_path: Path, *, json_output: bool = False) -> list[str]:
    argv = [
        "bench",
        "cadgenbench",
        "package",
        "--outputs",
        str(tmp_path / "outputs"),
        "--out",
        str(tmp_path / "submission.zip"),
        "--submitter",
        "Hephaestus",
        "--submission",
        "salvage round trip",
        "--agree-to-publish",
        "--skip-sanity-check",
        "--samples",
        "101",
        "--from-archive",
        str(tmp_path / "archive"),
    ]
    if json_output:
        argv.append("--json")
    return argv


def test_package_from_archive_round_trips_the_salvage_into_the_zip(
    tmp_path: Path, plate_brep: tuple[bytes, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """§5 gate clause: the flag itself. A sample with no exported candidate but
    a current successful archived build is salvaged, packaged into the ZIP, and
    the packaging report carries the salvage (artifact ref included) under
    ``salvage`` — the provenance chain rides with the submission."""
    import zipfile

    from hephaestus.core.cli import main as heph_main

    ref = _archive_run(tmp_path / "archive", "101", plate_brep)

    code = heph_main(_package_argv(tmp_path, json_output=True))

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    salvage = document["salvage"]
    assert salvage["entries"][0]["status"] == "exported"
    assert salvage["entries"][0]["artifact_ref"] == ref
    with zipfile.ZipFile(tmp_path / "submission.zip") as archive_file:
        names = archive_file.namelist()
    assert "101/output.step" in names and "meta.json" in names
    # The salvaged candidate in the zip is the archived geometry, revalidated.
    facts = step_validity(tmp_path / "outputs" / "101" / "output.step")
    assert facts.ok and facts.volume_mm3 == pytest.approx(800.0, rel=1e-6)
    assert (tmp_path / "outputs" / SALVAGE_REPORT_FILENAME).is_file()


def test_package_from_archive_refuses_a_failed_build_and_packages_nothing(
    tmp_path: Path, plate_brep: tuple[bytes, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """§5: salvage never resurrects a failed build — the refusal is named on the
    operator's console, no candidate is written, and packaging still fails on
    the missing sample instead of quietly shipping an empty folder."""
    from hephaestus.core.cli import main as heph_main

    _archive_run(tmp_path / "archive", "101", plate_brep, status="error")

    code = heph_main(_package_argv(tmp_path))

    assert code == 1
    err = capsys.readouterr().err
    assert "salvage refused 101: deliverable_build_failed" in err
    assert "missing_sample:101" in err
    assert not (tmp_path / "outputs" / "101" / "output.step").exists()
    assert not (tmp_path / "submission.zip").exists()
