"""globals.py execution (§4): project params, derived constants, hc tracking."""

from __future__ import annotations

import pytest
from hephaestus.core.errors import ParamOutOfBoundsError, ValidationError
from hephaestus.core.executor.globals_exec import (
    ensure_no_shadowing,
    execute_globals,
    shadowed_params,
)
from hephaestus.core.hashing import consumed_hc_hash

GLOBALS = """\
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=12.0),
    "shelf_w": Param(80.0, min=40.0, max=160.0),
}
clearance = 0.3
hex_half_width = p.shelf_w / 2 + p.sheet_t
_private = 42
"""


class TestExecuteGlobals:
    def test_project_params_and_derived_constants(self) -> None:
        result = execute_globals(GLOBALS)
        assert result.effective_project_params == {"sheet_t": 6.0, "shelf_w": 80.0}
        assert result.hc_values["clearance"] == 0.3
        assert result.hc_values["hex_half_width"] == 46.0

    def test_private_names_excluded(self) -> None:
        result = execute_globals(GLOBALS)
        assert "_private" not in result.hc_values
        assert "PARAMS" not in result.hc_values

    def test_project_override_flows_into_derived(self) -> None:
        result = execute_globals(GLOBALS, overrides={"shelf_w": 100.0})
        assert result.effective_project_params["shelf_w"] == 100.0
        assert result.hc_values["hex_half_width"] == 56.0

    def test_project_override_out_of_bounds(self) -> None:
        with pytest.raises(ParamOutOfBoundsError) as excinfo:
            execute_globals(GLOBALS, overrides={"sheet_t": 100.0})
        assert excinfo.value.param == "sheet_t"

    def test_none_source_empty_namespace(self) -> None:
        result = execute_globals(None)
        assert dict(result.hc_values) == {}
        assert dict(result.project_params) == {}

    def test_overrides_without_globals_rejected(self) -> None:
        with pytest.raises(ValidationError):
            execute_globals(None, overrides={"sheet_t": 5.0})

    def test_math_available(self) -> None:
        result = execute_globals("angle = math.degrees(math.pi)\n")
        assert result.hc_values["angle"] == 180.0

    def test_part_absent_from_globals_namespace(self) -> None:
        with pytest.raises(NameError):
            execute_globals("part.geometry = 1\n")

    def test_hc_namespace_tracks_reads(self) -> None:
        result = execute_globals(GLOBALS)
        hc = result.hc_namespace()
        assert hc.sheet_t == 6.0
        assert hc.consumed_projection() == {"sheet_t": 6.0}


class TestConsumedProjection:
    """Changing an unconsumed global leaves the projection hash unchanged."""

    def test_unconsumed_change_projection_stable(self) -> None:
        before = execute_globals(GLOBALS)
        after = execute_globals(GLOBALS.replace("clearance = 0.3", "clearance = 0.9"))
        hc_before = before.hc_namespace()
        hc_after = after.hc_namespace()
        _ = hc_before.sheet_t
        _ = hc_after.sheet_t
        assert consumed_hc_hash(hc_before.consumed_projection()) == consumed_hc_hash(
            hc_after.consumed_projection()
        )

    def test_consumed_change_projection_moves(self) -> None:
        before = execute_globals(GLOBALS)
        after = execute_globals(GLOBALS, overrides={"sheet_t": 9.0})
        hc_before = before.hc_namespace()
        hc_after = after.hc_namespace()
        _ = hc_before.sheet_t
        _ = hc_after.sheet_t
        assert consumed_hc_hash(hc_before.consumed_projection()) != consumed_hc_hash(
            hc_after.consumed_projection()
        )


class TestShadowing:
    def test_shadowed_params_detects(self) -> None:
        assert shadowed_params(["sheet_t", "width"], ["sheet_t", "clearance"]) == ("sheet_t",)

    def test_no_shadowing_ok(self) -> None:
        ensure_no_shadowing(["width"], ["sheet_t"])

    def test_shadowing_is_contract_error(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ensure_no_shadowing(["sheet_t"], ["sheet_t"])
        assert excinfo.value.kind == "contract"
        assert "sheet_t" in excinfo.value.message
