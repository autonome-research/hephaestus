"""Gate G0B — parameter-bounds enforcement and stale-part propagation.

Two clauses of mission_plan G0B:

- **Bounds at part and project scope.** An out-of-range ``--param`` (part) or
  ``--global-param`` (project) override is refused with a structured error
  that *names the offending parameter*; an in-bounds override is applied; an
  unknown name is rejected. Enforcement is checked both end-to-end (through a
  real sandboxed/worker build) and at the unit boundary (``merge_overrides``).
- **Stale propagation.** Editing a project parameter or ``globals.py`` derived
  constant marks *exactly* the parts that consumed the changed name/value
  stale — an unconsumed change invalidates nobody (architecture §3.5).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _gate import ASSEMBLY, build_part
from hephaestus.core.errors import ParamOutOfBoundsError, ValidationError
from hephaestus.core.params import Param, merge_overrides
from hephaestus.core.project_store.layout import ProjectLayout, ProjectManifest, open_store
from hephaestus.core.project_store.locks import (
    PROJECT_CONFIG_LOCK,
    LockManager,
    part_lock,
)
from hephaestus.core.project_store.projections import Projections


class TestPartScopeBounds:
    """§3 bounds on a part-level ``--param`` override, end to end."""

    def test_out_of_bounds_names_parameter(self, tmp_path: Path) -> None:
        built = build_part(
            "primary",
            ASSEMBLY / "parts" / "primary.py",
            tmp_path,
            globals_path=ASSEMBLY / "globals.py",
            part_overrides={"post_inset": 100},  # declared max is 30
        )
        assert built.result.status == "failed"
        error = built.result.error
        assert error is not None
        assert error.type == "ParamOutOfBoundsError"
        assert "post_inset" in error.message

    def test_in_bounds_override_applied(self, tmp_path: Path) -> None:
        built = build_part(
            "primary",
            ASSEMBLY / "parts" / "primary.py",
            tmp_path,
            globals_path=ASSEMBLY / "globals.py",
            part_overrides={"post_inset": 20},
        )
        assert built.result.status == "ok"
        assert built.result.params["post_inset"] == pytest.approx(20.0)

    def test_unknown_part_param_rejected(self, tmp_path: Path) -> None:
        built = build_part(
            "primary",
            ASSEMBLY / "parts" / "primary.py",
            tmp_path,
            globals_path=ASSEMBLY / "globals.py",
            part_overrides={"not_a_param": 1},
        )
        assert built.result.status == "failed"
        assert built.result.error is not None
        assert built.result.error.type == "ValidationError"


class TestProjectScopeBounds:
    """§3/§4 bounds on a project-level ``--global-param`` override, end to end."""

    def test_out_of_bounds_names_parameter(self, tmp_path: Path) -> None:
        built = build_part(
            "primary",
            ASSEMBLY / "parts" / "primary.py",
            tmp_path,
            globals_path=ASSEMBLY / "globals.py",
            project_overrides={"sheet_t": 100},  # declared max is 12
        )
        assert built.result.status == "failed"
        error = built.result.error
        assert error is not None
        assert error.type == "ParamOutOfBoundsError"
        assert "sheet_t" in error.message

    def test_in_bounds_project_override_flows_to_hc(self, tmp_path: Path) -> None:
        # sheet_t drives post_side = 3*sheet_t and frame_h; a valid override
        # rebuilds coherently (proves the project param reached the part via hc).
        built = build_part(
            "primary",
            ASSEMBLY / "parts" / "primary.py",
            tmp_path,
            globals_path=ASSEMBLY / "globals.py",
            project_overrides={"sheet_t": 9},
        )
        assert built.result.status == "ok"
        metrics = built.result.metrics
        assert metrics is not None
        # bbox Z = sheet_t + post_h(90) + sheet_t = 90 + 2*9 = 108
        assert metrics.bbox_mm[2] == pytest.approx(108.0, abs=1e-6)

    def test_unknown_project_param_rejected(self, tmp_path: Path) -> None:
        built = build_part(
            "primary",
            ASSEMBLY / "parts" / "primary.py",
            tmp_path,
            globals_path=ASSEMBLY / "globals.py",
            project_overrides={"not_a_global": 1},
        )
        assert built.result.status == "failed"
        assert built.result.error is not None


class TestMergeOverridesUnit:
    """The all-or-nothing bounds merge (§3), exercised at the unit boundary."""

    def _params(self) -> dict[str, Param]:
        return {
            "a": Param(5, min=2, max=10),
            "b": Param(3.0, min=2.0, max=6.0),
        }

    def test_valid_merge(self) -> None:
        effective = merge_overrides(self._params(), {"a": 8})
        assert effective == {"a": 8, "b": 3.0}

    def test_out_of_bounds_names_every_offender(self) -> None:
        with pytest.raises(ParamOutOfBoundsError) as exc:
            merge_overrides(self._params(), {"a": 99, "b": 99.0})
        assert set(exc.value.params) == {"a", "b"}

    def test_all_or_nothing_on_partial_failure(self) -> None:
        # Even one bad value applies nothing (the valid one is not silently kept).
        with pytest.raises(ParamOutOfBoundsError) as exc:
            merge_overrides(self._params(), {"a": 8, "b": 99.0})
        assert exc.value.params == ("b",)

    def test_unknown_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            merge_overrides(self._params(), {"z": 1})

    def test_int_param_rejects_non_integer_override(self) -> None:
        with pytest.raises(ValidationError):
            merge_overrides(self._params(), {"a": 3.5})

    def test_boundary_values_are_inclusive(self) -> None:
        assert merge_overrides(self._params(), {"a": 2})["a"] == 2
        assert merge_overrides(self._params(), {"a": 10})["a"] == 10


class TestStalePropagation:
    """§3.5 selective staleness from project-param and globals.py edits.

    Modelled directly over :class:`Projections` (the mechanism the CLI drives
    on every build/--stale): a recorded consumer goes stale iff a name/value it
    actually consumed changes.
    """

    def _projections(self, tmp_path: Path) -> tuple[Projections, LockManager]:
        root = tmp_path / "proj"
        root.mkdir()
        (root / "hephaestus.toml").write_text('name = "stale"\n', encoding="utf-8")
        layout = ProjectLayout(root=root, manifest=ProjectManifest(name="stale"))
        store = open_store(layout)
        locks = LockManager(store)
        return Projections(store, locks=locks), locks

    def _record(
        self,
        projections: Projections,
        locks: LockManager,
        part: str,
        consumed: dict[str, float],
    ) -> None:
        locks.acquire(PROJECT_CONFIG_LOCK)
        locks.acquire(part_lock(part))
        try:
            projections.record_current(
                part,
                consumed=dict(consumed),
                artifact_ref=f"artifact:build:sha256:{part}",
            )
        finally:
            locks.release(part_lock(part))
            locks.release(PROJECT_CONFIG_LOCK)

    def test_project_param_change_marks_only_consumers(self, tmp_path: Path) -> None:
        projections, locks = self._projections(tmp_path)
        projections.apply_hc_state({"sheet_t": 6.0, "shelf_w": 180.0, "joint_clear": 0.3})
        self._record(projections, locks, "bracket", {"sheet_t": 6.0, "joint_clear": 0.3})
        self._record(projections, locks, "primary", {"sheet_t": 6.0, "shelf_w": 180.0})
        assert dict(projections.state().stale) == {}

        # sheet_t (a project PARAM) changes: both parts consume it.
        report = projections.apply_hc_state({"sheet_t": 9.0, "shelf_w": 180.0, "joint_clear": 0.3})
        assert report.stale == ("bracket", "primary")
        assert report.changed["bracket"] == ("sheet_t",)
        assert report.changed["primary"] == ("sheet_t",)

    def test_globals_derived_constant_change_marks_one_consumer(self, tmp_path: Path) -> None:
        projections, locks = self._projections(tmp_path)
        projections.apply_hc_state({"sheet_t": 6.0, "shelf_w": 180.0, "joint_clear": 0.3})
        self._record(projections, locks, "bracket", {"sheet_t": 6.0, "joint_clear": 0.3})
        self._record(projections, locks, "primary", {"sheet_t": 6.0, "shelf_w": 180.0})

        # shelf_w is a derived constant in globals.py; only primary consumes it.
        report = projections.apply_hc_state({"sheet_t": 6.0, "shelf_w": 200.0, "joint_clear": 0.3})
        assert report.stale == ("primary",)
        assert "bracket" not in report.changed

    def test_unconsumed_change_invalidates_nobody(self, tmp_path: Path) -> None:
        projections, locks = self._projections(tmp_path)
        projections.apply_hc_state({"sheet_t": 6.0, "shelf_w": 180.0})
        self._record(projections, locks, "primary", {"sheet_t": 6.0, "shelf_w": 180.0})

        # A brand-new name nobody consumed appears: no consumer changes.
        report = projections.apply_hc_state({"sheet_t": 6.0, "shelf_w": 180.0, "brand_new": 1.0})
        assert report.stale == ()
        assert report.changed == {}

    def test_recording_current_clears_stale(self, tmp_path: Path) -> None:
        projections, locks = self._projections(tmp_path)
        projections.apply_hc_state({"sheet_t": 6.0, "shelf_w": 180.0})
        self._record(projections, locks, "primary", {"sheet_t": 6.0, "shelf_w": 180.0})
        report = projections.apply_hc_state({"sheet_t": 9.0, "shelf_w": 180.0})
        assert report.stale == ("primary",)
        assert "primary" in projections.state().stale

        # Rebuilding primary against the new state clears its stale marker.
        self._record(projections, locks, "primary", {"sheet_t": 9.0, "shelf_w": 180.0})
        assert "primary" not in projections.state().stale
