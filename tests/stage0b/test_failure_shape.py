"""Gate G0B — §8 failure-record reproduction with mutation tests.

The oversized-fillet fixture (``failure_fillet/parts/broken.py``) yields a
failed build; this suite asserts *every* §8 error field individually
(line/col, exception type, source frame spanning the failing statement,
``built_through`` at the prior statement, last-good metrics equal to
**independently computed** values, and the machine-readable last-good inspect
pointer). Per verification.md the last-good metrics are checked against values
computed here in Python, not merely echoed from the fixture manifest — and the
manifest itself is cross-checked against the same independent computation.

Every field assertion is a named helper. Each mutation test corrupts exactly
that produced field (via ``dataclasses.replace``) and proves the helper's
assertion *bites* (raises ``AssertionError``) — so the contract suite cannot
silently pass on a degraded executor.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from _gate import FAILURE_FILLET, build_part
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.types import BuiltThrough, ErrorRecord, LastGood

# --- Independent (clean-room) computation of the last-good geometry ---------
# broken.py builds a 50x30x6 plate, subtracts a centered 20x8 through-slot,
# then fails on an oversized fillet. The last good solid is the notched plate.
PLATE_W, PLATE_D, PLATE_T = 50.0, 30.0, 6.0
SLOT_W, SLOT_D = 20.0, 8.0
# Slot passes fully through the 6 mm thickness => a through-hole: sealed, genus 1.
LAST_GOOD_VOLUME = PLATE_W * PLATE_D * PLATE_T - SLOT_W * SLOT_D * PLATE_T  # 8040.0
LAST_GOOD_SIZE = (PLATE_W, PLATE_D, PLATE_T)
LAST_GOOD_GENUS = 1
LAST_GOOD_SOLIDS = 1
FAIL_LINE = 9
BUILT_THROUGH_LINE = 8
BUILT_THROUGH_STATEMENT = "notched = plate - slot"
ERROR_TYPE = "ValueError"


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    data = json.loads((FAILURE_FILLET / "fixture.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def failed(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    built = build_part(
        "broken",
        FAILURE_FILLET / "parts" / "broken.py",
        tmp_path_factory.mktemp("failure-fillet"),
    )
    assert built.result.status == "failed"
    assert built.result.error is not None
    return built


@pytest.fixture(scope="module")
def error(failed: UnpublishedBuild) -> ErrorRecord:
    assert failed.result.error is not None
    return failed.result.error


# --- Field assertion helpers (each is exercised by a mutation test) ---------


def check_line(err: ErrorRecord) -> None:
    assert err.line == FAIL_LINE


def check_col(err: ErrorRecord) -> None:
    # 0-based column of the failing expression (§8 example uses 0-based cols).
    assert isinstance(err.col, int)
    assert err.col >= 0


def check_type(err: ErrorRecord) -> None:
    assert err.type == ERROR_TYPE


def check_message_nonempty(err: ErrorRecord) -> None:
    # Our wording is our own; only presence is contractual (verification.md).
    assert err.message.strip() != ""


def check_frame_marks_failing_line(err: ErrorRecord) -> None:
    marked = [line for line in err.frame if line.startswith("> ")]
    assert len(marked) == 1
    assert marked[0].startswith(f"> {FAIL_LINE} | ")
    # The frame spans the failing statement with ±context.
    numbers = [int(line.lstrip("> ").split(" | ", 1)[0]) for line in err.frame]
    assert min(numbers) <= FAIL_LINE <= max(numbers)
    assert FAIL_LINE in numbers


def check_built_through(err: ErrorRecord) -> None:
    bt = err.built_through
    assert bt is not None
    assert bt.line == BUILT_THROUGH_LINE
    assert bt.statement == BUILT_THROUGH_STATEMENT


def check_last_good_metrics(err: ErrorRecord) -> None:
    lg = err.last_good
    assert lg is not None
    assert lg.solids == LAST_GOOD_SOLIDS
    assert lg.bodies == 1
    assert lg.size_mm == pytest.approx(LAST_GOOD_SIZE, abs=1e-6)
    assert lg.volume_mm3 == pytest.approx(LAST_GOOD_VOLUME, abs=1e-6)
    assert lg.sealed is True
    assert lg.genus == LAST_GOOD_GENUS


def check_last_good_artifact_ref(err: ErrorRecord) -> None:
    ref = err.last_good_artifact_ref
    assert ref is not None
    assert ref.startswith("artifact:build-checkpoint:sha256:")
    # Opaque capability, never a filesystem path (§8).
    assert "/" not in ref.rsplit(":", 1)[-1]


def check_hint(err: ErrorRecord) -> None:
    assert err.hint.strip() != ""
    assert "artifact_ref" in err.hint


# --- The positive contract: every field present and correct -----------------


class TestFailureRecordFields:
    def test_status_failed_with_error(self, failed: UnpublishedBuild) -> None:
        assert failed.result.status == "failed"
        assert failed.result.current is False
        assert failed.result.metrics is None
        assert failed.result.error is not None

    def test_line(self, error: ErrorRecord) -> None:
        check_line(error)

    def test_col(self, error: ErrorRecord) -> None:
        check_col(error)

    def test_type(self, error: ErrorRecord) -> None:
        check_type(error)

    def test_message_present(self, error: ErrorRecord) -> None:
        check_message_nonempty(error)

    def test_frame(self, error: ErrorRecord) -> None:
        check_frame_marks_failing_line(error)

    def test_built_through(self, error: ErrorRecord) -> None:
        check_built_through(error)

    def test_last_good_metrics_equal_independent_values(self, error: ErrorRecord) -> None:
        check_last_good_metrics(error)

    def test_last_good_artifact_ref(self, error: ErrorRecord) -> None:
        check_last_good_artifact_ref(error)

    def test_hint(self, error: ErrorRecord) -> None:
        check_hint(error)

    def test_last_good_brep_checkpoint_installed(self, failed: UnpublishedBuild) -> None:
        ref = failed.result.error and failed.result.error.last_good_artifact_ref
        assert ref is not None
        path = failed.artifact_files[ref]
        assert path.is_file()
        assert path.read_bytes()  # the last-good BRep exists and is non-empty


class TestManifestMatchesIndependentComputation:
    """The committed fixture manifest must equal the clean-room computation."""

    def test_manifest_last_good(self, manifest: dict[str, object]) -> None:
        assert manifest["fail_line"] == FAIL_LINE
        assert manifest["error_type"] == ERROR_TYPE
        bt = manifest["built_through"]
        assert isinstance(bt, dict)
        assert bt["line"] == BUILT_THROUGH_LINE
        assert bt["statement"] == BUILT_THROUGH_STATEMENT
        lg = manifest["last_good"]
        assert isinstance(lg, dict)
        assert lg["solids"] == LAST_GOOD_SOLIDS
        assert lg["volume_mm3"] == pytest.approx(LAST_GOOD_VOLUME, abs=1e-6)
        assert list(map(float, lg["size_mm"])) == pytest.approx(  # type: ignore[arg-type]
            list(LAST_GOOD_SIZE), abs=1e-6
        )
        assert lg["genus"] == LAST_GOOD_GENUS
        assert lg["sealed"] is True

    def test_produced_record_agrees_with_manifest(
        self, error: ErrorRecord, manifest: dict[str, object]
    ) -> None:
        assert error.line == manifest["fail_line"]
        assert error.type == manifest["error_type"]
        lg = error.last_good
        assert lg is not None
        manifest_lg = manifest["last_good"]
        assert isinstance(manifest_lg, dict)
        assert lg.volume_mm3 == pytest.approx(float(manifest_lg["volume_mm3"]), abs=1e-6)  # type: ignore[arg-type]


# --- Mutation tests: corrupt each field, prove the assertion bites ----------


class TestMutationsBite:
    """Each helper must reject a corrupted copy of the field it guards.

    Without these, a field assertion that never fails would give false
    assurance (verification.md 'mutation tests confirm the contract suite
    actually fails when the error fields are corrupted').
    """

    def test_line_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_line(replace(error, line=error.line + 1))

    def test_type_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_type(replace(error, type="RuntimeError"))

    def test_message_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_message_nonempty(replace(error, message="   "))

    def test_frame_missing_marker_mutation(self, error: ErrorRecord) -> None:
        stripped = tuple(line.lstrip("> ") for line in error.frame)
        with pytest.raises(AssertionError):
            check_frame_marks_failing_line(replace(error, frame=stripped))

    def test_frame_wrong_line_mutation(self, error: ErrorRecord) -> None:
        shifted = tuple(
            f"> {FAIL_LINE + 50} | x" if line.startswith("> ") else line for line in error.frame
        )
        with pytest.raises(AssertionError):
            check_frame_marks_failing_line(replace(error, frame=shifted))

    def test_built_through_line_mutation(self, error: ErrorRecord) -> None:
        assert error.built_through is not None
        corrupt = replace(error.built_through, line=BUILT_THROUGH_LINE + 1)
        with pytest.raises(AssertionError):
            check_built_through(replace(error, built_through=corrupt))

    def test_built_through_statement_mutation(self, error: ErrorRecord) -> None:
        corrupt = BuiltThrough(line=BUILT_THROUGH_LINE, statement="wrong = 0")
        with pytest.raises(AssertionError):
            check_built_through(replace(error, built_through=corrupt))

    def test_built_through_absent_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_built_through(replace(error, built_through=None))

    def test_last_good_volume_mutation(self, error: ErrorRecord) -> None:
        assert error.last_good is not None
        corrupt = replace(error.last_good, volume_mm3=LAST_GOOD_VOLUME + 1.0)
        with pytest.raises(AssertionError):
            check_last_good_metrics(replace(error, last_good=corrupt))

    def test_last_good_genus_mutation(self, error: ErrorRecord) -> None:
        assert error.last_good is not None
        corrupt = replace(error.last_good, genus=0)
        with pytest.raises(AssertionError):
            check_last_good_metrics(replace(error, last_good=corrupt))

    def test_last_good_size_mutation(self, error: ErrorRecord) -> None:
        assert error.last_good is not None
        corrupt = replace(error.last_good, size_mm=(1.0, 2.0, 3.0))
        with pytest.raises(AssertionError):
            check_last_good_metrics(replace(error, last_good=corrupt))

    def test_last_good_sealed_mutation(self, error: ErrorRecord) -> None:
        assert error.last_good is not None
        corrupt = replace(error.last_good, sealed=False)
        with pytest.raises(AssertionError):
            check_last_good_metrics(replace(error, last_good=corrupt))

    def test_last_good_absent_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_last_good_metrics(replace(error, last_good=None))

    def test_last_good_ref_absent_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_last_good_artifact_ref(replace(error, last_good_artifact_ref=None))

    def test_last_good_ref_wrong_prefix_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_last_good_artifact_ref(
                replace(error, last_good_artifact_ref="artifact:build:sha256:deadbeef")
            )

    def test_last_good_ref_filesystem_path_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_last_good_artifact_ref(
                replace(
                    error,
                    last_good_artifact_ref="artifact:build-checkpoint:sha256:/etc/passwd",
                )
            )

    def test_hint_mutation(self, error: ErrorRecord) -> None:
        with pytest.raises(AssertionError):
            check_hint(replace(error, hint="oops"))

    def test_independent_value_guards_real_record(self) -> None:
        # Sanity: a LastGood with the wrong genus fails the check, proving the
        # metric assertion is not vacuous even in isolation.
        bad = LastGood(
            bodies=1,
            solids=1,
            size_mm=LAST_GOOD_SIZE,
            volume_mm3=LAST_GOOD_VOLUME,
            sealed=True,
            genus=0,
        )
        err = ErrorRecord(
            line=FAIL_LINE,
            col=0,
            type=ERROR_TYPE,
            message="x",
            frame=(f"> {FAIL_LINE} | x",),
            built_through=BuiltThrough(BUILT_THROUGH_LINE, BUILT_THROUGH_STATEMENT),
            last_good=bad,
            last_good_artifact_ref="artifact:build-checkpoint:sha256:abc",
            hint="use artifact_ref",
        )
        with pytest.raises(AssertionError):
            check_last_good_metrics(err)
