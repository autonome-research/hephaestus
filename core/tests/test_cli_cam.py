"""G6: `heph cam emit` writes a laser/waterjet DXF from a built part.

This is 2D CAM, not DFM-only. The CLI is the headless contract. It
is not an export: no WAL, no `.heph/exports/`. Kerf is taken from the
named pack parameter unless `--kerf-mm` overrides it. CNC router is
refused — Stage 14 milling is a different contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cam import emit_part
from hephaestus.core.cli import main as heph
from hephaestus.geom.kerf import KERF_UNCOMPENSATED

UNSAFE = "--unsafe-local-executor"

PLATE = """_plate = Box(60.0, 40.0, 6.0) - Cylinder(6.0, 20.0)
_plate.label = "plate"
part.geometry = _plate

part.description = "A bored plate whose cut path must be kerf compensated"
part.process = "{process}"
part.stock_form = "sheet"
part.blank_size = "One 120 x 90 x 6 mm blank"
"""


def _init_part(tmp_path: Path, name: str, process: str) -> Path:
    target = tmp_path / "proj"
    assert heph(["init", str(target)]) == 0
    (target / "parts" / f"{name}.py").write_text(PLATE.format(process=process), encoding="utf-8")
    return target


def test_cam_emit_writes_laser_dxf_with_pack_kerf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _init_part(tmp_path, "plate", "laser_cut")
    monkeypatch.chdir(target)
    assert heph(["build", "plate", UNSAFE]) == 0
    capsys.readouterr()

    out = target / "plate.dxf"
    code = heph(["cam", "emit", "plate", "--out", str(out), "--json"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert out.is_file()
    assert out.stat().st_size > 200
    assert not (target / ".heph" / "exports").exists()
    body = out.read_text()
    assert "ENTITIES" in body
    assert "CIRCLE" in body or "LWPOLYLINE" in body or "LINE" in body

    payload = cast("dict[str, Any]", json.loads(captured.out))
    assert payload["kind"] == "cut2d"
    assert payload["process"] == "laser_cut"
    assert payload["part"] == "plate"
    assert payload["kerf"] == {
        "applied_mm": 0.2,
        "source": "dfm",
        "process": "laser_cut",
    }
    assert str(payload["dxf_sha256"]).startswith("sha256:")
    assert payload["layers"]["CUT"] == 2
    assert payload["path"] == str(out)

    program = emit_part("plate", project_root=target)
    assert program.kerf.applied_mm == pytest.approx(0.2)
    assert program.kerf.source == "dfm"
    assert program.kerf.note != KERF_UNCOMPENSATED
    assert [contour.ring for contour in program.toolpath] == ["hole_1", "outer"]


def test_cam_emit_waterjet_uses_pack_kerf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _init_part(tmp_path, "jet", "waterjet")
    monkeypatch.chdir(target)
    assert heph(["build", "jet", UNSAFE]) == 0
    capsys.readouterr()

    out = target / "jet.dxf"
    code = heph(["cam", "emit", "jet", "--out", str(out), "--json"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert out.is_file()
    payload = cast("dict[str, Any]", json.loads(captured.out))
    assert payload["process"] == "waterjet"
    assert payload["kerf"] == {
        "applied_mm": 0.8,
        "source": "dfm",
        "process": "waterjet",
    }

    program = emit_part("jet", project_root=target)
    assert program.kerf.applied_mm == pytest.approx(0.8)
    assert program.process == "waterjet"


def test_cam_emit_explicit_kerf_overrides_the_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _init_part(tmp_path, "plate", "laser_cut")
    monkeypatch.chdir(target)
    assert heph(["build", "plate", UNSAFE]) == 0
    capsys.readouterr()

    out = target / "override.dxf"
    code = heph(["cam", "emit", "plate", "--out", str(out), "--kerf-mm", "1.0", "--json"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    payload = cast("dict[str, Any]", json.loads(captured.out))
    assert payload["kerf"] == {
        "applied_mm": 1.0,
        "source": "explicit",
        "process": "laser_cut",
    }


def test_cam_emit_refuses_cnc_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _init_part(tmp_path, "block", "cnc_router")
    monkeypatch.chdir(target)
    assert heph(["build", "block", UNSAFE]) == 0
    capsys.readouterr()

    code = heph(["cam", "emit", "block"])
    assert code == 1
    err = capsys.readouterr().err
    assert "cam_refused" in err
    assert "not_a_cut2d_process" in err


def test_cam_emit_refuses_unbuilt_part(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _init_part(tmp_path, "plate", "laser_cut")
    monkeypatch.chdir(target)
    code = heph(["cam", "emit", "plate"])
    assert code == 1
    err = capsys.readouterr().err
    assert "cam_refused" in err
    assert "not_built" in err


def test_cam_emit_requires_part_name() -> None:
    with pytest.raises(SystemExit) as ei:
        heph(["cam", "emit"])
    assert ei.value.code == 2


def test_cam_emit_outside_project_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code = heph(["cam", "emit", "plate"])
    assert code == 2
    assert "hephaestus.toml" in capsys.readouterr().err
