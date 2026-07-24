"""Param declaration/inference, bounds validation, all-or-nothing merge tests."""

from __future__ import annotations

from typing import ClassVar

import pytest
from hephaestus.core.errors import ParamOutOfBoundsError, ValidationError
from hephaestus.core.params import (
    Param,
    extract_params,
    merge_overrides,
    params_declaration_json,
)


class TestInference:
    def test_int_default_declares_int(self) -> None:
        assert Param(5, min=2, max=10).type == "int"

    def test_float_default_declares_float(self) -> None:
        assert Param(3.0, min=2, max=6).type == "float"

    def test_smith_observed_forms(self) -> None:
        params = {
            "groove_count": Param(5, min=2, max=10),
            "groove_width": Param(3.0, min=2, max=6),
            "brace_slot_clear": Param(0.3, min=0.0, max=0.8),
        }
        assert params["groove_count"].type == "int"
        assert params["groove_width"].type == "float"
        assert params["brace_slot_clear"].type == "float"

    def test_doc_and_step_extensions(self) -> None:
        param = Param(3.0, min=1.0, max=6.0, doc="groove width", step=0.5)
        assert param.doc == "groove width"
        assert param.step == 0.5


class TestDeclarationValidation:
    def test_bool_default_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(True, min=0, max=1)  # type: ignore[arg-type]

    def test_non_numeric_default_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param("5", min=0, max=10)  # type: ignore[arg-type]

    def test_default_outside_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(11, min=2, max=10)

    def test_inverted_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(5, min=10, max=2)

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(float("nan"), min=0.0, max=1.0)

    def test_nonpositive_step_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(5.0, min=0.0, max=10.0, step=0)

    def test_declaration_json(self) -> None:
        assert Param(5, min=2, max=10).to_json() == {
            "default": 5,
            "min": 2,
            "max": 10,
            "type": "int",
        }
        assert Param(3.0, min=2, max=6, doc="d", step=0.5).to_json() == {
            "default": 3.0,
            "min": 2,
            "max": 6,
            "type": "float",
            "doc": "d",
            "step": 0.5,
        }


class TestCoercion:
    def test_int_param_accepts_int(self) -> None:
        assert Param(5, min=2, max=10).coerce(7, name="n") == 7

    def test_int_param_accepts_integral_float(self) -> None:
        value = Param(5, min=2, max=10).coerce(7.0, name="n")
        assert value == 7
        assert isinstance(value, int)

    def test_int_param_rejects_fractional(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Param(5, min=2, max=10).coerce(7.5, name="groove_count")
        assert "groove_count" in exc_info.value.message

    def test_int_param_parses_string(self) -> None:
        assert Param(5, min=2, max=10).coerce("7", name="n") == 7

    def test_float_param_parses_string(self) -> None:
        assert Param(3.0, min=2, max=6).coerce("4.5", name="n") == 4.5

    def test_float_param_coerces_int_to_float(self) -> None:
        value = Param(3.0, min=2, max=6).coerce(4, name="n")
        assert isinstance(value, float)

    def test_unparseable_string_names_param(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Param(3.0, min=2, max=6).coerce("wide", name="groove_width")
        assert "groove_width" in exc_info.value.message

    def test_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(5, min=0, max=10).coerce(True, name="n")

    def test_non_finite_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Param(3.0, min=2, max=6).coerce(float("inf"), name="n")


class TestMerge:
    PARAMS: ClassVar[dict[str, Param]] = {
        "groove_count": Param(5, min=2, max=10),
        "groove_width": Param(3.0, min=2, max=6),
        "brace_slot_clear": Param(0.3, min=0.0, max=0.8),
    }

    def test_no_overrides_yields_defaults(self) -> None:
        assert merge_overrides(self.PARAMS, {}) == {
            "groove_count": 5,
            "groove_width": 3.0,
            "brace_slot_clear": 0.3,
        }

    def test_valid_override_applies(self) -> None:
        effective = merge_overrides(self.PARAMS, {"groove_count": 8, "groove_width": "4.5"})
        assert effective == {"groove_count": 8, "groove_width": 4.5, "brace_slot_clear": 0.3}

    def test_out_of_bounds_names_parameter(self) -> None:
        with pytest.raises(ParamOutOfBoundsError) as exc_info:
            merge_overrides(self.PARAMS, {"groove_count": 11})
        error = exc_info.value
        assert error.code == "param_out_of_bounds"
        assert error.param == "groove_count"
        assert "groove_count" in error.message

    def test_bounds_are_inclusive(self) -> None:
        effective = merge_overrides(self.PARAMS, {"groove_count": 10, "brace_slot_clear": 0.0})
        assert effective["groove_count"] == 10
        assert effective["brace_slot_clear"] == 0.0

    def test_all_or_nothing_reports_every_violation(self) -> None:
        with pytest.raises(ParamOutOfBoundsError) as exc_info:
            merge_overrides(
                self.PARAMS,
                {"groove_count": 11, "groove_width": 4.0, "brace_slot_clear": 0.9},
            )
        assert exc_info.value.params == ("brace_slot_clear", "groove_count")

    def test_unknown_parameter_rejected_with_known_listed(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            merge_overrides(self.PARAMS, {"groove_widht": 4.0})
        message = exc_info.value.message
        assert "groove_widht" in message
        assert "groove_width" in message

    def test_mixed_unknown_and_valid_applies_nothing(self) -> None:
        # All-or-nothing: the valid override must not leak out via the raise.
        with pytest.raises(ValidationError):
            merge_overrides(self.PARAMS, {"groove_count": 8, "bogus": 1})

    def test_declaration_order_preserved(self) -> None:
        assert list(merge_overrides(self.PARAMS, {})) == list(self.PARAMS)


class TestExtractParams:
    def test_absent_params_is_empty(self) -> None:
        assert extract_params({"other": 1}) == {}

    def test_extracts_declared_dict(self) -> None:
        params = {"n": Param(5, min=2, max=10)}
        assert extract_params({"PARAMS": params}) == params

    def test_non_dict_params_rejected(self) -> None:
        with pytest.raises(ValidationError):
            extract_params({"PARAMS": [Param(5, min=2, max=10)]})

    def test_non_param_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            extract_params({"PARAMS": {"n": 5}})

    def test_non_str_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            extract_params({"PARAMS": {1: Param(5, min=2, max=10)}})


class TestDeclarationJson:
    def test_name_sorted(self) -> None:
        params = {
            "z_last": Param(1, min=0, max=2),
            "a_first": Param(1.0, min=0.0, max=2.0),
        }
        assert list(params_declaration_json(params)) == ["a_first", "z_last"]
