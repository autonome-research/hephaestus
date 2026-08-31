"""BuildResult/CheckReport record tests: §8 field mirror, round-trip, schema."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.types import (
    AuditHashes,
    BuildResult,
    BuiltThrough,
    CheckReport,
    CheckResult,
    ErrorRecord,
    GeometryEntry,
    InputHashes,
    LastGood,
    Metrics,
    StatementCheckpoint,
    Warning,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

Mutator = Callable[[dict[str, Any]], object]

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "build_result.schema.json"

_H = "sha256:" + "ab" * 32
_REF_BUILD = "artifact:build:" + _H
_REF_CHECKPOINT = "artifact:build-checkpoint:" + _H
_REF_SNAPSHOT = "artifact:project-snapshot:" + _H
_REF_SOURCE_MAP = "artifact:source-map:" + _H


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate(validator: Draft202012Validator, data: object) -> None:
    """Typed shim over the partially-typed jsonschema validate surface."""
    validator.validate(data)  # pyright: ignore[reportUnknownMemberType]


def _input_hashes() -> InputHashes:
    return InputHashes(
        script=_H,
        hc_dependencies=_H,
        part_params=_H,
        effective_params=_H,
        toolchain=_H,
    )


def _audit_hashes() -> AuditHashes:
    return AuditHashes(globals_source=_H, project_param_state=_H)


def ok_result() -> BuildResult:
    return BuildResult(
        part="cat_step_shelf",
        status="ok",
        current=True,
        artifact_ref=_REF_BUILD,
        project_snapshot_ref=_REF_SNAPSHOT,
        input_hashes=_input_hashes(),
        audit_hashes=_audit_hashes(),
        metrics=Metrics(
            solids=25,
            faces=438,
            bbox_mm=(380.0, 280.0, 250.0),
            volume_mm3=868892.28,
            sealed=True,
            genus=0,
        ),
        checks={
            "splines_clear_middle_panels": CheckResult(passed=True, measured=0.0),
            "manifold": CheckResult(passed=True, measured=True),
        },
        geometries=(
            GeometryEntry(label="outer_top_panel", solids=1),
            GeometryEntry(label="corner_splines", solids=1),
            GeometryEntry(label="corner_splines#2", solids=1),
        ),
        params={"groove_count": 5, "groove_width": 3.0},
        source_map_ref=_REF_SOURCE_MAP,
        warnings=(
            Warning(
                kind="tag_descriptor_changed",
                tag="tread_top",
                detail="centroid moved 1.4mm (threshold 1.0mm)",
                evidence={"baseline_ref": _REF_BUILD, "centroid_delta_mm": 1.4},
            ),
        ),
        error=None,
    )


def failed_result() -> BuildResult:
    return BuildResult(
        part="cat_step_shelf",
        status="failed",
        current=False,
        artifact_ref=None,
        project_snapshot_ref=None,
        input_hashes=_input_hashes(),
        audit_hashes=_audit_hashes(),
        metrics=None,
        checks={},
        geometries=(),
        params={"groove_count": 5},
        source_map_ref=None,
        warnings=(),
        error=ErrorRecord(
            line=46,
            col=14,
            type="ValueError",
            message="Failed creating a fillet with radius of 6, try a smaller value",
            frame=(
                "44 | tread_shelf = slotted_shelf - groove_cutter",
                "45 |",
                "> 46 | tread_shelf = fillet(...)",
            ),
            built_through=BuiltThrough(
                line=44, statement="tread_shelf = slotted_shelf - groove_cutter"
            ),
            last_good=LastGood(
                bodies=1,
                solids=1,
                size_mm=(250.0, 200.0, 18.0),
                volume_mm3=868892.28,
                sealed=True,
                genus=0,
            ),
            last_good_artifact_ref=_REF_CHECKPOINT,
            hint="inspect_part(name, artifact_ref=last_good_artifact_ref) renders this snapshot",
        ),
        checkpoints=(
            StatementCheckpoint(
                index=0,
                line=44,
                statement="tread_shelf = slotted_shelf - groove_cutter",
                span=(44, 0, 44, 48),
                bound=("tread_shelf",),
                shapes=("tread_shelf",),
                artifact_ref=_REF_CHECKPOINT,
            ),
        ),
    )


RESULT_MUTATIONS: list[Mutator] = [
    lambda d: d.update(status="partial"),
    lambda d: d.pop("part"),
    lambda d: d.pop("input_hashes"),
    lambda d: d.pop("audit_hashes"),
    lambda d: d.pop("error"),
    lambda d: d.update(artifact_ref="not-a-ref"),
    lambda d: d["input_hashes"].update(script="sha256:zz"),
    lambda d: d["input_hashes"].pop("toolchain"),
    lambda d: d.update(params={"groove_count": "five"}),
    lambda d: d.update(extra_field=1),
]

ERROR_MUTATIONS: list[Mutator] = [
    lambda e: e.pop("line"),
    lambda e: e.pop("built_through"),
    lambda e: e.pop("last_good"),
    lambda e: e.pop("last_good_artifact_ref"),
    lambda e: e.pop("hint"),
    lambda e: e.update(frame="not-a-list"),
    lambda e: e["last_good"].pop("volume_mm3"),
    lambda e: e["built_through"].pop("statement"),
]


class TestSchemaValidation:
    def test_ok_result_validates(self, validator: Draft202012Validator) -> None:
        _validate(validator, ok_result().to_json())

    def test_failed_result_validates(self, validator: Draft202012Validator) -> None:
        _validate(validator, failed_result().to_json())

    def test_json_is_serializable_and_stable(self) -> None:
        first = json.dumps(ok_result().to_json(), sort_keys=True)
        second = json.dumps(ok_result().to_json(), sort_keys=True)
        assert first == second

    @pytest.mark.parametrize("mutate", RESULT_MUTATIONS)
    def test_schema_rejects_mutations(
        self, validator: Draft202012Validator, mutate: Mutator
    ) -> None:
        data: dict[str, Any] = ok_result().to_json()
        mutate(data)
        with pytest.raises(SchemaValidationError):
            _validate(validator, data)

    @pytest.mark.parametrize("mutate", ERROR_MUTATIONS)
    def test_schema_rejects_error_mutations(
        self, validator: Draft202012Validator, mutate: Mutator
    ) -> None:
        data: dict[str, Any] = failed_result().to_json()
        mutate(data["error"])
        with pytest.raises(SchemaValidationError):
            _validate(validator, data)

    def test_metrics_null_only_alongside_error(self, validator: Draft202012Validator) -> None:
        data = failed_result().to_json()
        assert data["metrics"] is None
        _validate(validator, data)


class TestRoundTrip:
    def test_ok_round_trip(self) -> None:
        original = ok_result()
        rebuilt = BuildResult.from_json(original.to_json())
        assert rebuilt == original
        assert rebuilt.to_json() == original.to_json()

    def test_failed_round_trip_full_error_object(self) -> None:
        original = failed_result()
        rebuilt = BuildResult.from_json(original.to_json())
        assert rebuilt == original
        error = rebuilt.error
        assert error is not None
        assert error.line == 46
        assert error.col == 14
        assert error.type == "ValueError"
        assert error.built_through is not None
        assert error.built_through.line == 44
        assert error.last_good is not None
        assert error.last_good.size_mm == (250.0, 200.0, 18.0)
        assert error.last_good.volume_mm3 == pytest.approx(868892.28, abs=1e-6)
        assert error.last_good_artifact_ref == _REF_CHECKPOINT
        assert error.hint.startswith("inspect_part")
        assert len(rebuilt.checkpoints) == 1
        assert rebuilt.checkpoints[0].artifact_ref == _REF_CHECKPOINT
        assert rebuilt.checkpoints[0].statement.startswith("tread_shelf")

    def test_round_trip_through_json_text(self) -> None:
        original = failed_result()
        text = json.dumps(original.to_json())
        rebuilt = BuildResult.from_json(json.loads(text))
        assert rebuilt == original

    def test_error_nullable_members_round_trip(self) -> None:
        record = failed_result().error
        assert record is not None
        bare = ErrorRecord(
            line=1,
            col=0,
            type="SyntaxError",
            message="invalid syntax",
            frame=("> 1 | def:",),
            built_through=None,
            last_good=None,
            last_good_artifact_ref=None,
            hint="fix the syntax error",
        )
        assert ErrorRecord.from_json(bare.to_json()) == bare

    def test_check_measured_preserves_json_values(self) -> None:
        result = CheckResult(passed=False, measured=[380.0, 280.5, 250.0])
        assert CheckResult.from_json(result.to_json()) == result

    def test_from_json_rejects_missing_field(self) -> None:
        data = ok_result().to_json()
        del data["checks"]
        with pytest.raises(ValidationError) as exc_info:
            BuildResult.from_json(data)
        assert exc_info.value.code == "validation_error"
        assert exc_info.value.kind == "contract"

    def test_from_json_rejects_bool_param(self) -> None:
        data = ok_result().to_json()
        data["params"] = {"groove_count": True}
        with pytest.raises(ValidationError):
            BuildResult.from_json(data)

    def test_from_json_rejects_bad_status(self) -> None:
        data = ok_result().to_json()
        data["status"] = "partial"
        with pytest.raises(ValidationError):
            BuildResult.from_json(data)

    def test_absent_checkpoints_read_as_empty(self) -> None:
        data = ok_result().to_json()
        del data["checkpoints"]
        rebuilt = BuildResult.from_json(data)
        assert rebuilt.checkpoints == ()


class TestStatementCheckpoint:
    def test_round_trip(self) -> None:
        checkpoint = StatementCheckpoint(
            index=3,
            line=44,
            statement="tread_shelf = slotted_shelf - groove_cutter",
            span=(44, 0, 44, 48),
            bound=("tread_shelf",),
            shapes=("tread_shelf",),
            artifact_ref=_REF_CHECKPOINT,
        )
        assert StatementCheckpoint.from_json(checkpoint.to_json()) == checkpoint

    def test_null_artifact_ref_round_trips(self) -> None:
        checkpoint = StatementCheckpoint(
            index=0,
            line=1,
            statement="x = 1",
            span=(1, 0, 1, 5),
            bound=("x",),
            shapes=(),
        )
        rebuilt = StatementCheckpoint.from_json(checkpoint.to_json())
        assert rebuilt.artifact_ref is None


class TestInvariants:
    def test_failed_requires_error(self) -> None:
        with pytest.raises(ValidationError):
            BuildResult(
                part="p",
                status="failed",
                current=False,
                artifact_ref=None,
                project_snapshot_ref=None,
                input_hashes=_input_hashes(),
                audit_hashes=_audit_hashes(),
                metrics=None,
                checks={},
                geometries=(),
                params={},
                source_map_ref=None,
                warnings=(),
                error=None,
            )

    def test_ok_refuses_error(self) -> None:
        template = failed_result()
        with pytest.raises(ValidationError):
            BuildResult(
                part="p",
                status="ok",
                current=False,
                artifact_ref=_REF_BUILD,
                project_snapshot_ref=None,
                input_hashes=_input_hashes(),
                audit_hashes=_audit_hashes(),
                metrics=None,
                checks={},
                geometries=(),
                params={},
                source_map_ref=None,
                warnings=(),
                error=template.error,
            )

    def test_current_requires_ok(self) -> None:
        template = failed_result()
        with pytest.raises(ValidationError):
            BuildResult(
                part="p",
                status="failed",
                current=True,
                artifact_ref=None,
                project_snapshot_ref=None,
                input_hashes=_input_hashes(),
                audit_hashes=_audit_hashes(),
                metrics=None,
                checks={},
                geometries=(),
                params={},
                source_map_ref=None,
                warnings=(),
                error=template.error,
            )


class TestCheckReport:
    def _report(self) -> CheckReport:
        return CheckReport(
            part="cat_step_shelf",
            check_set_generation=7,
            check_bundle_ref="artifact:check-bundle:" + _H,
            file_hashes={"checks/clearance.py": _H, "checks/envelope.py": _H},
            project_snapshot_ref=_REF_SNAPSHOT,
            checks={
                "envelope": CheckResult(passed=True, measured=[380.0, 280.0, 250.0]),
                "one_cat_static": CheckResult(passed=False, measured=6250.0),
            },
        )

    def test_round_trip(self) -> None:
        report = self._report()
        assert CheckReport.from_json(report.to_json()) == report

    def test_fields_per_architecture(self) -> None:
        data = self._report().to_json()
        assert data["check_set_generation"] == 7
        assert isinstance(data["check_bundle_ref"], str)
        assert data["file_hashes"] == {
            "checks/clearance.py": _H,
            "checks/envelope.py": _H,
        }
        assert data["project_snapshot_ref"] == _REF_SNAPSHOT
        checks = data["checks"]
        assert isinstance(checks, dict)
        assert checks["envelope"] == {"pass": True, "measured": [380.0, 280.0, 250.0]}

    def test_from_json_rejects_missing_generation(self) -> None:
        data = self._report().to_json()
        del data["check_set_generation"]
        with pytest.raises(ValidationError):
            CheckReport.from_json(data)


class TestWarning:
    def test_optional_fields_omitted(self) -> None:
        warning = Warning(kind="lint", detail="params never read")
        data = warning.to_json()
        assert "tag" not in data
        assert "evidence" not in data
        assert Warning.from_json(data) == warning
