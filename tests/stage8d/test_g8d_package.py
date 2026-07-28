"""G8D: submission packaging (``EXTERNAL_EVAL.md`` §2, "Packaging").

Gate clause: *packaging assembles the ZIP layout the benchmark demands
(``output.step`` per sample folder + ``meta.json``), runs the vendored-or-fetched
sanity check, and fails when a sample is missing, a STEP is invalid, or the
sanity check fails*.

The layout claims are asserted against ``CADGENBENCH_FACTS.md``'s reading of the
Space's own ``submit.py``, because every one of them is a *hard reject* rather
than a lost point: a wrapper directory, a missing folder, an extra folder, or a
``meta.json`` key that is absent (or an ``agree_to_publish`` that is the string
``"true"``) throws the whole upload away.

The sanity check is exercised with a stub script standing in for the
benchmark's, which needs the full ``cadgenbench`` OCC install and lives in the
dataset repo. What is under test here is *our* contract with it — that its exit
code decides, and that a checker which cannot run is an error and never a pass.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from _g8d import STEPS, outputs_with
from hephaestus.bench.cadgenbench import (
    SANITY_CHECK_FILENAME,
    PackagingError,
    SubmissionMeta,
    package_submission,
    resolve_sanity_check,
    step_validity,
)

SAMPLES = ("101", "102", "201")


def meta() -> SubmissionMeta:
    return SubmissionMeta(
        submitter_name="Hephaestus",
        submission_name="hephaestus stage 8d",
        agree_to_publish=True,
    )


def stub_checker(path: Path, *, exit_code: int, message: str = "stub") -> Path:
    """A stand-in for ``sanity_check_submission.py`` (which needs the OCC stack)."""
    path.write_text(
        f"import sys\nprint({message!r}, file=sys.stderr)\nraise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    return path


# ==========================================================================
# the layout the benchmark demands


def test_the_zip_has_no_wrapper_and_carries_every_sample_folder(tmp_path: Path) -> None:
    outputs = outputs_with(
        tmp_path / "outputs",
        {"101": STEPS / "plate.step", "102": None, "201": STEPS / "edited.step"},
    )
    target = tmp_path / "submission.zip"

    report = package_submission(outputs, SAMPLES, meta(), target)

    assert report.n_solved == 2
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        document = json.loads(archive.read("meta.json"))
    # meta.json at the root, sample folders at the top level, no wrapper.
    assert "meta.json" in names
    assert {"101/output.step", "201/output.step"} <= names
    assert all("/" not in name.rstrip("/") or name.split("/")[0] in SAMPLES for name in names)
    # The unsolved sample survives extraction as an explicit directory entry —
    # without it the Space reports "missing sample" instead of a scored zero.
    assert "102/" in names
    assert not any(name.startswith("102/output") for name in names)
    assert document == {
        "agent_url": None,
        "agree_to_publish": True,
        "notes": None,
        "submission_name": "hephaestus stage 8d",
        "submitter_name": "Hephaestus",
    }


def test_meta_agree_to_publish_must_be_the_literal_boolean(tmp_path: Path) -> None:
    """The Space checks ``is not True``; consent is never defaulted for the operator."""
    outputs = outputs_with(tmp_path / "outputs", {sample: None for sample in SAMPLES})

    with pytest.raises(PackagingError) as excinfo:
        package_submission(
            outputs,
            SAMPLES,
            SubmissionMeta(submitter_name="A", submission_name="B"),
            tmp_path / "submission.zip",
        )

    assert excinfo.value.reasons == ("meta_agree_to_publish_required",)
    assert not (tmp_path / "submission.zip").exists()


def test_notes_are_normalized_and_capped(tmp_path: Path) -> None:
    outputs = outputs_with(tmp_path / "outputs", {sample: None for sample in SAMPLES})
    long_notes = "x" * 501

    with pytest.raises(PackagingError) as excinfo:
        package_submission(
            outputs,
            SAMPLES,
            SubmissionMeta(
                submitter_name="A",
                submission_name="B",
                notes=long_notes,
                agree_to_publish=True,
            ),
            tmp_path / "submission.zip",
        )
    assert excinfo.value.reasons[0].startswith("meta_notes_too_long")

    report = package_submission(
        outputs,
        SAMPLES,
        SubmissionMeta(
            submitter_name="A",
            submission_name="B",
            notes="one\n\ttwo   three ",
            agree_to_publish=True,
        ),
        tmp_path / "ok.zip",
    )
    with zipfile.ZipFile(report.zip_path) as archive:
        assert json.loads(archive.read("meta.json"))["notes"] == "one two three"


# ==========================================================================
# the three ways packaging fails


def test_a_missing_sample_folder_fails_packaging(tmp_path: Path) -> None:
    outputs = outputs_with(tmp_path / "outputs", {"101": STEPS / "plate.step"})

    with pytest.raises(PackagingError) as excinfo:
        package_submission(outputs, SAMPLES, meta(), tmp_path / "submission.zip")

    assert set(excinfo.value.reasons) == {"missing_sample:102", "missing_sample:201"}
    assert not (tmp_path / "submission.zip").exists()


def test_an_unexpected_folder_fails_packaging(tmp_path: Path) -> None:
    """Extra folders are fatal server-side, so they are fatal here."""
    outputs = outputs_with(tmp_path / "outputs", dict.fromkeys([*SAMPLES, "999"], None))

    with pytest.raises(PackagingError) as excinfo:
        package_submission(outputs, SAMPLES, meta(), tmp_path / "submission.zip")

    assert "unexpected_folder:999" in excinfo.value.reasons


@pytest.mark.parametrize(
    ("candidate", "failure"),
    [("broken.step", "unreadable_step"), ("open_face.step", "unsealed,non_positive_volume")],
)
def test_an_invalid_step_fails_packaging(tmp_path: Path, candidate: str, failure: str) -> None:
    outputs = outputs_with(
        tmp_path / "outputs",
        {"101": STEPS / candidate, "102": None, "201": STEPS / "edited.step"},
    )

    with pytest.raises(PackagingError) as excinfo:
        package_submission(outputs, SAMPLES, meta(), tmp_path / "submission.zip")

    assert excinfo.value.reasons == (f"invalid_step:101:{failure}",)
    assert not (tmp_path / "submission.zip").exists()


def test_the_sanity_check_decides_by_exit_code(tmp_path: Path) -> None:
    outputs = outputs_with(
        tmp_path / "outputs",
        {"101": STEPS / "plate.step", "102": None, "201": STEPS / "edited.step"},
    )

    passing = stub_checker(tmp_path / "pass.py", exit_code=0)
    report = package_submission(outputs, SAMPLES, meta(), tmp_path / "ok.zip", sanity_check=passing)
    assert report.sanity_check == str(passing)
    assert [entry.sanity for entry in report.entries if entry.solved] == ["pass", "pass"]

    failing = stub_checker(tmp_path / "fail.py", exit_code=1, message="FAIL  is_valid=False")
    with pytest.raises(PackagingError) as excinfo:
        package_submission(outputs, SAMPLES, meta(), tmp_path / "bad.zip", sanity_check=failing)
    assert excinfo.value.reasons == ("sanity_check_failed:101", "sanity_check_failed:201")
    assert not (tmp_path / "bad.zip").exists()


def test_a_checker_that_cannot_run_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """The real checker hard-imports the whole ``cadgenbench`` OCC stack."""
    outputs = outputs_with(
        tmp_path / "outputs", {"101": STEPS / "plate.step", "102": None, "201": None}
    )
    crashing = tmp_path / "crash.py"
    crashing.write_text("import cadgenbench.common.validity\n", encoding="utf-8")

    with pytest.raises(PackagingError) as excinfo:
        package_submission(
            outputs, SAMPLES, meta(), tmp_path / "submission.zip", sanity_check=crashing
        )

    assert excinfo.value.reasons == ("sanity_check_error:101",)


# ==========================================================================
# where the checker comes from


def test_the_checker_is_found_in_the_snapshot_then_the_cache_never_the_repo(
    tmp_path: Path,
) -> None:
    """ "Vendored-or-fetched" resolves offline in both places, and never downloads here."""
    from hephaestus.agent_bridge.app import repo_root

    snapshot = tmp_path / "snapshot"
    cache = tmp_path / "cache"
    snapshot.mkdir()
    cache.mkdir()

    # Neither place has it and downloading is refused: a named error, no network.
    with pytest.raises(FileNotFoundError, match=SANITY_CHECK_FILENAME):
        resolve_sanity_check(dataset_root=snapshot, cache=cache, download=False)

    cached = cache / SANITY_CHECK_FILENAME
    cached.write_text("raise SystemExit(0)\n", encoding="utf-8")
    assert resolve_sanity_check(dataset_root=snapshot, cache=cache, download=False) == cached

    # The snapshot's own copy wins over the cached one.
    local = snapshot / SANITY_CHECK_FILENAME
    local.write_text("raise SystemExit(0)\n", encoding="utf-8")
    assert resolve_sanity_check(dataset_root=snapshot, cache=cache, download=False) == local

    # EXTERNAL_EVAL.md §4: the ODC-BY checker is never committed to this repo.
    assert not list(repo_root().rglob(SANITY_CHECK_FILENAME))


def test_an_empty_folder_is_a_legal_unsolved_submission(tmp_path: Path) -> None:
    """A folder with no candidate scores zero; that is not a packaging failure."""
    outputs = outputs_with(tmp_path / "outputs", dict.fromkeys(SAMPLES, None))

    report = package_submission(outputs, SAMPLES, meta(), tmp_path / "submission.zip")

    assert report.n_solved == 0
    with zipfile.ZipFile(report.zip_path) as archive:
        assert sorted(archive.namelist()) == ["101/", "102/", "201/", "meta.json"]


def test_allow_missing_records_the_sample_rather_than_inventing_one(tmp_path: Path) -> None:
    outputs = outputs_with(tmp_path / "outputs", {"101": STEPS / "plate.step"})

    report = package_submission(
        outputs, SAMPLES, meta(), tmp_path / "submission.zip", allow_missing=True
    )

    assert report.n_solved == 1
    with zipfile.ZipFile(report.zip_path) as archive:
        assert "102/" in archive.namelist()


# ==========================================================================
# the floor underneath packaging


def test_the_validity_floor_names_what_it_measured() -> None:
    good = step_validity(STEPS / "plate.step")
    assert good.ok and good.sealed
    assert good.volume_mm3 == pytest.approx(20.0 * 10.0 * 4.0, rel=1e-6)
    assert good.bbox_mm == pytest.approx((20.0, 10.0, 4.0), abs=1e-6)

    face = step_validity(STEPS / "open_face.step")
    assert face.failures == ("unsealed", "non_positive_volume")

    broken = step_validity(STEPS / "broken.step")
    assert broken.failures == ("unreadable_step",)
    assert broken.readable is False
    assert broken.error  # the reason is recorded, never swallowed
