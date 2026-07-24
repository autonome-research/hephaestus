"""In-process worker protocol tests (no subprocess): §8 records, checks, main().

The integration suite exercises the worker through the sandbox subprocess;
these tests drive :func:`hephaestus.core.executor.worker.execute_job` and
:func:`main` directly so the failure paths (§8 error records, last-good
snapshots, globals failures), the in-worker §6 check evaluation, and the
stdin/stdout protocol shell are pinned in-process.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.executor import worker
from opstore.types import JSONValue


def run_job(
    script: str,
    out_dir: Path,
    *,
    globals_source: str | None = None,
    part: str = "unit",
) -> dict[str, JSONValue]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return worker.execute_job(
        {
            "part": part,
            "script": script,
            "globals_source": globals_source,
            "part_overrides": {},
            "project_overrides": {},
            "out_dir": str(out_dir),
        }
    )


def error_of(result: dict[str, JSONValue]) -> dict[str, JSONValue]:
    assert result["status"] == "failed"
    error = result["error"]
    assert isinstance(error, dict)
    return error


FAIL_AFTER_PROGRESS = (
    "plate = Box(30, 20, 6)\n"
    "posts = [Box(4, 4, 8), Box(4, 4, 8)]\n"
    "bad = fillet(plate.edges().filter_by(Axis.Z), radius=99.0)\n"
    "part.geometry = plate\n"
)

SINGLE_SHAPE = "plate = Box(10, 10, 2)\npart.geometry = plate\n"


class TestFailureRecords:
    def test_syntax_error_carries_frame_and_no_snapshot_hint(self, tmp_path: Path) -> None:
        result = run_job("def broken(:\n", tmp_path)
        error = error_of(result)
        assert error["type"] == "SyntaxError"
        assert error["line"] == 1
        frame = error["frame"]
        assert isinstance(frame, list) and any(
            isinstance(line, str) and line.startswith("> ") for line in frame
        )
        assert error["built_through"] is None
        assert error["last_good"] is None
        assert error["hint"] == worker.NO_SNAPSHOT_HINT
        assert result["checkpoints"] == []

    def test_statement_failure_writes_last_good_snapshot(self, tmp_path: Path) -> None:
        result = run_job(FAIL_AFTER_PROGRESS, tmp_path)
        error = error_of(result)
        assert error["line"] == 3
        built_through = error["built_through"]
        assert isinstance(built_through, dict) and built_through["line"] == 2
        last_good = error["last_good"]
        assert isinstance(last_good, dict)
        # The last shape-binding statement bound the two posts.
        assert last_good["solids"] == 2
        assert last_good["sealed"] is True
        assert error["hint"] == worker.INSPECT_HINT
        assert result["artifacts"] == {"last_good": worker.LAST_GOOD_BREP}
        assert (tmp_path / worker.LAST_GOOD_BREP).is_file()
        checkpoints = result["checkpoints"]
        assert isinstance(checkpoints, list) and len(checkpoints) == 2

    def test_missing_geometry_is_a_contract_failure(self, tmp_path: Path) -> None:
        result = run_job("x = 1\n", tmp_path)
        error = error_of(result)
        assert error["type"] == "ValidationError"
        message = error["message"]
        assert isinstance(message, str) and "part.geometry" in message
        assert error["last_good"] is None

    def test_non_shape_geometry_is_rejected(self, tmp_path: Path) -> None:
        result = run_job("part.geometry = 42\n", tmp_path)
        error = error_of(result)
        message = error["message"]
        assert isinstance(message, str) and "build123d shape" in message

    def test_globals_failure_attributes_to_globals(self, tmp_path: Path) -> None:
        result = run_job(SINGLE_SHAPE, tmp_path, globals_source="raise RuntimeError('boom')\n")
        error = error_of(result)
        message = error["message"]
        assert isinstance(message, str) and message.startswith("globals.py:")
        hint = error["hint"]
        assert isinstance(hint, str) and "globals.py" in hint


class TestSuccessPaths:
    def test_single_shape_root_labels_from_binding(self, tmp_path: Path) -> None:
        result = run_job(SINGLE_SHAPE, tmp_path)
        assert result["status"] == "ok", result["error"]
        assert result["geometries"] == [{"label": "plate", "solids": 1}]
        index = result["geometry_index"]
        assert isinstance(index, dict)
        assert index["labels"] == ["plate"]
        assert index["bindings"] == {"plate": 1}
        assert (tmp_path / worker.FINAL_BREP).is_file()

    def test_orphan_tag_yields_unresolved_warning(self, tmp_path: Path) -> None:
        script = (
            "plate = Box(10, 10, 2)\n"
            "scrap = Box(5, 5, 5)\n"
            'tag(scrap.faces().sort_by(Axis.Z)[-1], "orphan")\n'
            "part.geometry = plate\n"
        )
        result = run_job(script, tmp_path)
        assert result["status"] == "ok", result["error"]
        warnings = result["warnings"]
        assert isinstance(warnings, list)
        kinds = [w["kind"] for w in warnings if isinstance(w, dict)]
        assert "tag_unresolved" in kinds

    def test_part_checks_run_in_worker_over_all_selector_kinds(self, tmp_path: Path) -> None:
        script = (
            'PARAMS = {"width": Param(20.0, min=10, max=40)}\n'
            "plate = Box(p.width, 10, 4)\n"
            'plate.label = "plate"\n'
            "cap = Pos(0, 0, 4) * Box(4, 4, 2)\n"
            "hidden = Box(2, 2, 2)\n"
            'tag(plate.faces().sort_by(Axis.Z)[-1], "top")\n'
            "part.geometry = Compound(children=[plate, cap])\n"
            "CHECKS = {\n"
            '    "sealed": lambda m: m.sealed("part"),\n'
            '    "plate_volume": lambda m: m.volume("plate") == approx(800.0, abs=1e-6),\n'
            '    "cap_volume": lambda m: m.volume("cap") == approx(32.0, abs=1e-6),\n'
            '    "hidden_volume": lambda m: m.volume("hidden") == approx(8.0, abs=1e-6),\n'
            '    "top_is_flat": lambda m: m.bbox("top")[2] == approx(0.0, abs=1e-6),\n'
            "}\n"
        )
        result = run_job(script, tmp_path)
        assert result["status"] == "ok", result["error"]
        assert result["check_names"] == sorted(
            ["sealed", "plate_volume", "cap_volume", "hidden_volume", "top_is_flat"]
        )
        checks = result["checks"]
        assert isinstance(checks, dict) and set(checks) == set(
            cast("list[str]", result["check_names"])
        )
        for name, outcome in checks.items():
            assert isinstance(outcome, dict)
            assert outcome["pass"] is True, (name, outcome)


class TestMainProtocol:
    def job_json(self, tmp_path: Path, script: str = SINGLE_SHAPE) -> str:
        return json.dumps(
            {
                "part": "unit",
                "script": script,
                "globals_source": None,
                "part_overrides": {},
                "project_overrides": {},
                "out_dir": str(tmp_path),
            }
        )

    def test_ok_job_round_trips_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(self.job_json(tmp_path)))
        assert worker.main() == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert isinstance(parsed, dict) and parsed["status"] == "ok"

    def test_invalid_json_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        assert worker.main() == 2
        assert "invalid job JSON" in capsys.readouterr().err

    def test_non_object_job_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
        assert worker.main() == 2
        assert "must be a JSON object" in capsys.readouterr().err

    def test_internal_error_exits_3(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        job = json.dumps({"part_overrides": [1], "out_dir": str(tmp_path)})
        monkeypatch.setattr("sys.stdin", io.StringIO(job))
        assert worker.main() == 3
        assert "internal error" in capsys.readouterr().err
