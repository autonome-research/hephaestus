"""Engine part-scope behavior: CHECKS collection, execution, restricted modules."""

from __future__ import annotations

import textwrap
from collections.abc import Callable

import pytest
from hephaestus.core.checks.approx import approx
from hephaestus.core.checks.engine import (
    CheckPredicate,
    collect_checks,
    load_check_module,
    run_checks,
)
from hephaestus.core.checks.facade import Measurement, part_measurement
from hephaestus.core.errors import ValidationError
from test_checks_helpers import PLATE, PRIMARY_PART, RIB, FakeOps, primary_source


def factory_with(ops: FakeOps) -> Callable[[], Measurement]:
    def _make() -> Measurement:
        return part_measurement("primary", primary_source(), ops=ops)

    return _make


def _always_true(_m: Measurement) -> bool:
    return True


class TestCollectChecks:
    def test_absent_is_empty(self) -> None:
        assert collect_checks({}) == {}

    def test_collects_predicates(self) -> None:
        def pred(m: Measurement) -> bool:
            _ = m
            return True

        checks = collect_checks({"CHECKS": {"a": pred}})
        assert list(checks) == ["a"]

    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            collect_checks({"CHECKS": ["nope"]})
        assert excinfo.value.kind == "contract"

    def test_rejects_non_string_key(self) -> None:
        with pytest.raises(ValidationError):
            collect_checks({"CHECKS": {1: _always_true}})

    def test_rejects_non_callable(self) -> None:
        with pytest.raises(ValidationError):
            collect_checks({"CHECKS": {"a": 42}})


class TestRunChecks:
    def test_pass_and_fail_with_measured_values(self) -> None:
        ops = FakeOps(
            interferences={frozenset({PLATE, RIB}): 4.2},
            bboxes={PRIMARY_PART: (380.0, 280.0, 250.0)},
        )
        checks: dict[str, CheckPredicate] = {
            "clear": lambda m: m.interference("plate", "rib") == approx(0, abs=1e-6),
            "envelope": lambda m: m.bbox("part") <= (380.5, 280.5, 250.5),
        }
        results = run_checks(checks, factory_with(ops))
        assert results["clear"].passed is False
        assert results["clear"].measured == 4.2
        assert results["envelope"].passed is True
        assert results["envelope"].measured == [380.0, 280.0, 250.0]
        assert results["clear"].to_json() == {"pass": False, "measured": 4.2}

    def test_predicate_exception_fails_check_not_build(self) -> None:
        def broken(m: Measurement) -> bool:
            _ = m
            raise RuntimeError("kaboom")

        results = run_checks({"boom": broken}, factory_with(FakeOps()))
        assert results["boom"].passed is False
        measured = results["boom"].measured
        assert isinstance(measured, dict)
        error = measured["error"]
        assert isinstance(error, dict)
        assert error["type"] == "RuntimeError"

    def test_addressing_error_fails_check_with_code(self) -> None:
        results = run_checks({"missing": lambda m: m.volume("nope") > 0}, factory_with(FakeOps()))
        assert results["missing"].passed is False
        measured = results["missing"].measured
        assert isinstance(measured, dict)
        error = measured["error"]
        assert isinstance(error, dict)
        assert error["code"] == "addressing_error"

    def test_fresh_facade_per_check(self) -> None:
        ops = FakeOps(volumes={PRIMARY_PART: 5.0})
        checks: dict[str, CheckPredicate] = {
            "a": lambda m: m.volume("part") == 5.0,
            "b": lambda m: m.volume("part") == 5.0,
        }
        results = run_checks(checks, factory_with(ops))
        assert results["a"].measured == 5.0
        assert results["b"].measured == 5.0  # not a two-entry mixed trace


class TestLoadCheckModule:
    def test_valid_module(self) -> None:
        source = textwrap.dedent(
            """
            LIMIT = 380.5
            CHECKS = {
                "envelope": lambda m: m.bbox("part") <= (LIMIT, 280.5, 250.5),
                "clear": lambda m: m.interference("plate", "rib") == approx(0, abs=1e-6),
            }
            """
        )
        checks = load_check_module(source, filename="envelope.py")
        assert sorted(checks) == ["clear", "envelope"]

    def test_syntax_error(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            load_check_module("CHECKS = {", filename="broken.py")
        assert excinfo.value.kind == "syntax"

    def test_missing_checks_is_contract_error(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            load_check_module("x = 1", filename="empty.py")
        assert excinfo.value.kind == "contract"

    def test_malformed_checks_is_contract_error(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            load_check_module("CHECKS = [1, 2]", filename="bad.py")
        assert excinfo.value.kind == "contract"

    def test_module_level_crash_is_evaluation_error(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            load_check_module("x = 1 / 0\nCHECKS = {}", filename="crash.py")
        assert excinfo.value.kind == "evaluation"

    def test_filesystem_denied(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            load_check_module("data = open('/etc/passwd').read()\nCHECKS = {}", filename="fs.py")
        assert excinfo.value.kind == "sandbox"

    def test_import_denied(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            load_check_module("import os\nCHECKS = {}", filename="imp.py")
        assert excinfo.value.kind == "sandbox"

    def test_eval_and_introspection_denied(self) -> None:
        for stmt in ("eval('1')", "exec('x=1')", "globals()", "getattr(int, 'mro')"):
            with pytest.raises(ValidationError) as excinfo:
                load_check_module(f"{stmt}\nCHECKS = {{}}", filename="deny.py")
            assert excinfo.value.kind == "sandbox"

    def test_approx_available_in_namespace(self) -> None:
        checks = load_check_module(
            "CHECKS = {'t': lambda m: 0.0 == approx(0, abs=1e-6)}", filename="a.py"
        )
        results = run_checks(checks, factory_with(FakeOps()))
        assert results["t"].passed is True

    def test_runtime_denial_fails_check_only(self) -> None:
        source = "CHECKS = {'sneaky': lambda m: open('/etc/passwd')}"
        checks = load_check_module(source, filename="sneaky.py")
        results = run_checks(checks, factory_with(FakeOps()))
        assert results["sneaky"].passed is False
        measured = results["sneaky"].measured
        assert isinstance(measured, dict)
        error = measured["error"]
        assert isinstance(error, dict)
        assert error["code"] == "validation_error"
