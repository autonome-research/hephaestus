"""Scan-to-part CLI glue: ``heph import add --part`` then Stage 12.

#36 already copies a mesh into ``imports/`` and seeds ``import_mesh`` +
``mesh_to_solid``. This module asserts the operator path that closes #29:
the seeded part builds (or refuses by name), and ``heph scan`` /
``heph scan check`` work against the admitted file. Reconstruction is not
under test because it is not in the product.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import main

UNSAFE = "--unsafe-local-executor"

# 10 mm cube at the origin, 12 outward triangles — the Stage 12B cube that
# sews to a VALID solid. Written by hand so this file does not import the
# gate fixtures.
_CUBE_V = (
    (0.0, 0.0, 0.0),
    (10.0, 0.0, 0.0),
    (10.0, 10.0, 0.0),
    (0.0, 10.0, 0.0),
    (0.0, 0.0, 10.0),
    (10.0, 0.0, 10.0),
    (10.0, 10.0, 10.0),
    (0.0, 10.0, 10.0),
)
_CUBE_F = (
    (0, 3, 2),
    (0, 2, 1),
    (4, 5, 6),
    (4, 6, 7),
    (0, 1, 5),
    (0, 5, 4),
    (2, 3, 7),
    (2, 7, 6),
    (1, 2, 6),
    (1, 6, 5),
    (3, 0, 4),
    (3, 4, 7),
)


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cube_stl(*, drop_first: bool = False) -> bytes:
    """Binary STL for the 10 mm cube; ``drop_first`` opens a hole (refused sew)."""
    faces = _CUBE_F[1:] if drop_first else _CUBE_F
    out = bytearray(b"\x00" * 80)
    out += struct.pack("<I", len(faces))
    for tri in faces:
        a, b, c = _CUBE_V[tri[0]], _CUBE_V[tri[1]], _CUBE_V[tri[2]]
        normal = _cross(_sub(b, a), _sub(c, a))
        length = (normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) ** 0.5
        if length:
            normal = (normal[0] / length, normal[1] / length, normal[2] / length)
        out += struct.pack("<3f", *normal)
        for corner in (a, b, c):
            out += struct.pack("<3f", *corner)
        out += struct.pack("<H", 0)
    return bytes(out)


def project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "scan-to-part"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    return root


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


def test_import_add_part_mesh_builds_and_scan_check_measures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The #29 operator path: admit → seed → build → scan facts → scan check."""
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(cube_stl())

    assert (
        run(
            root,
            monkeypatch,
            "import",
            "add",
            str(source),
            "--units",
            "mm",
            "--part",
            "socket",
        )
        == 0
    )
    admitted = capsys.readouterr()
    assert "created parts/socket.py" in admitted.out
    assert "scan-to-part:" in admitted.out
    assert "no reconstruction" in admitted.out
    script = (root / "parts" / "socket.py").read_text(encoding="utf-8")
    assert script == (
        'scan = import_mesh("scan.stl", units="mm")\n'
        'part.geometry = mesh_to_solid(scan, intent="measurement_target")\n'
    )

    assert run(root, monkeypatch, "build", "socket", "--json", UNSAFE) == 0
    built = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert built["status"] == "ok"
    assert built["part"] == "socket"
    assert built["current"] is True

    assert run(root, monkeypatch, "scan", "scan.stl", "--units", "mm", "--json") == 0
    facts = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert facts["triangle_count"] == 12
    assert facts["watertight_at_weld_tol"] is True
    assert facts["units_declared"] == "mm"

    assert (
        run(root, monkeypatch, "scan", "check", "socket", "scan.stl", "--units", "mm", "--json")
        == 0
    )
    checked = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert checked["status"] == "ok"
    assert checked["part"]["name"] == "socket"
    assert checked["scan"]["path"] == "scan.stl"
    assert checked["scan"]["units"] == "mm"
    distance = cast("dict[str, Any]", checked["distance"])
    assert distance["scan_to_part_max_mm"] == pytest.approx(0.0, abs=1e-6)
    assert distance["part_to_scan_max_mm"] == pytest.approx(0.0, abs=1e-6)
    assert "iou" not in distance
    assert "chamfer_mm" not in distance


def test_import_add_part_open_mesh_builds_to_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ingress still seeds; the Stage 12 gate refuses the hole by name."""
    root = project(tmp_path / "proj")
    source = tmp_path / "holed.stl"
    source.write_bytes(cube_stl(drop_first=True))

    assert (
        run(
            root,
            monkeypatch,
            "import",
            "add",
            str(source),
            "--units",
            "mm",
            "--part",
            "socket",
        )
        == 0
    )
    capsys.readouterr()
    assert (root / "imports" / "holed.stl").is_file()
    assert (root / "parts" / "socket.py").is_file()

    assert run(root, monkeypatch, "build", "socket", "--json", UNSAFE) == 1
    captured = capsys.readouterr()
    payload = captured.out.strip()
    assert payload, captured.err
    built = cast("dict[str, Any]", json.loads(payload.splitlines()[-1]))
    assert built["status"] == "failed"
    message = str(cast("dict[str, Any]", built["error"])["message"])
    assert "mesh_solid_invalid" in message


def test_import_add_part_still_requires_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(cube_stl())

    assert run(root, monkeypatch, "import", "add", str(source), "--part", "socket") == 1
    assert "mesh_units_undeclared" in capsys.readouterr().err
    assert not (root / "parts" / "socket.py").exists()
    assert not (root / "imports" / "scan.stl").exists()
