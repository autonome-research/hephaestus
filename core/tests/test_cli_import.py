"""``heph import add|list`` — project ingress into ``imports/``.

Kernel import (``import_step`` / ``import_mesh``) is not under test here; this
is the operator-side copy that puts a vendor file where those terms can name
it. Confinement matches Stage 8A/12A: destination is a regular file beneath
``imports/``, ``O_NOFOLLOW``, original untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import main
from opstore.types import JSONValue

from opstore import sha256_bytes

ASCII_STL = b"""solid box
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0 1 0
    endloop
  endfacet
endsolid box
"""


def project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "imports"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    return root


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


def box_step(path: Path) -> bytes:
    from build123d import Box
    from hephaestus.geom.step_io import write_step

    write_step(Box(10, 10, 10), path)
    return path.read_bytes()


def test_add_copies_a_step_and_reports_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "box.step"
    payload = box_step(source)

    assert run(root, monkeypatch, "import", "add", str(source), "--json") == 0

    reported = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert reported == {
        "kind": "step",
        "name": "box.step",
        "path": "imports/box.step",
        "sha256": sha256_bytes(payload),
    }
    dest = root / "imports" / "box.step"
    assert dest.read_bytes() == payload
    assert not dest.is_symlink()
    assert source.read_bytes() == payload, "original must be untouched"


def test_add_mesh_requires_units_and_records_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(ASCII_STL)

    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm", "--json") == 0

    reported = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert reported == {
        "kind": "mesh",
        "name": "scan.stl",
        "path": "imports/scan.stl",
        "sha256": sha256_bytes(ASCII_STL),
        "units": "mm",
    }
    assert (root / "imports" / "scan.stl").read_bytes() == ASCII_STL
    assert source.read_bytes() == ASCII_STL


def test_add_refuses_a_missing_file_as_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path / "proj")
    assert run(root, monkeypatch, "import", "add", str(tmp_path / "nope.step")) == 2


def test_add_refuses_traversal_and_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "box.step"
    payload = box_step(source)

    assert run(root, monkeypatch, "import", "add", str(source), "--name", "../escape.step") == 1
    err = capsys.readouterr().err
    assert "path_confinement" in err
    assert not (tmp_path / "escape.step").exists()
    assert not (root / "escape.step").exists()

    link = tmp_path / "alias.step"
    link.symlink_to(source)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "imports").mkdir()
    planted = root / "imports" / "planted.step"
    planted.symlink_to(outside / "leaked.step")

    assert (
        run(root, monkeypatch, "import", "add", str(link), "--name", "planted.step", "--json") == 1
    )
    assert "path_confinement" in capsys.readouterr().err
    assert planted.is_symlink()
    assert not (outside / "leaked.step").exists()

    assert run(root, monkeypatch, "import", "add", str(link), "--name", "from_link.step") == 0
    dest = root / "imports" / "from_link.step"
    assert dest.is_file() and not dest.is_symlink()
    assert dest.read_bytes() == payload
    assert link.is_symlink()
    assert source.read_bytes() == payload


def test_add_does_not_write_through_a_planted_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dest hardlink is a regular file; O_TRUNC would clobber the outside inode.

    Rename replaces the imports/ directory entry. The outside name keeps its
    bytes whether add succeeds or refuses.
    """
    root = project(tmp_path / "proj")
    source = tmp_path / "vendor.step"
    payload = box_step(source)

    outside = tmp_path / "outside" / "secret.step"
    outside.parent.mkdir()
    original = b"OUTSIDE-ORIGINAL-BYTES\n"
    outside.write_bytes(original)
    (root / "imports").mkdir()
    planted = root / "imports" / "planted.step"
    os.link(outside, planted)
    assert planted.stat().st_ino == outside.stat().st_ino

    rc = run(root, monkeypatch, "import", "add", str(source), "--name", "planted.step")

    assert rc in (0, 1)
    assert outside.read_bytes() == original
    if rc == 0:
        dest = root / "imports" / "planted.step"
        assert dest.is_file() and not dest.is_symlink()
        assert dest.read_bytes() == payload
        assert dest.stat().st_ino != outside.stat().st_ino


def test_add_refuses_mesh_without_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(ASCII_STL)

    assert run(root, monkeypatch, "import", "add", str(source)) == 1
    err = capsys.readouterr().err
    assert "mesh_units_undeclared" in err
    assert not (root / "imports" / "scan.stl").exists()


def test_add_part_refuses_an_existing_name_without_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    existing = "part.geometry = Box(1, 1, 1)\n"
    (root / "parts" / "plate.py").write_text(existing, encoding="utf-8")
    source = tmp_path / "box.step"
    box_step(source)

    assert run(root, monkeypatch, "import", "add", str(source), "--part", "plate", "--json") == 1
    reported = cast("dict[str, JSONValue]", json.loads(capsys.readouterr().out))
    assert reported == {"part": "plate", "status": "already_exists"}
    assert (root / "parts" / "plate.py").read_text(encoding="utf-8") == existing
    assert not (root / "imports" / "box.step").exists()


def test_add_part_seeds_import_step_term(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "vendor_plate.step"
    box_step(source)

    assert (
        run(
            root,
            monkeypatch,
            "import",
            "add",
            str(source),
            "--part",
            "ingested",
            "--json",
        )
        == 0
    )
    reported = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert reported["name"] == "vendor_plate.step"
    assert reported["kind"] == "step"
    script = (root / "parts" / "ingested.py").read_text(encoding="utf-8")
    assert script == 'part.geometry = import_step("vendor_plate.step")\n'


def test_add_part_seeds_import_mesh_and_mesh_to_solid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "limb.stl"
    source.write_bytes(ASCII_STL)

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
    script = (root / "parts" / "socket.py").read_text(encoding="utf-8")
    assert script == (
        'scan = import_mesh("limb.stl", units="mm")\n'
        'part.geometry = mesh_to_solid(scan, intent="measurement_target")\n'
    )


def test_add_refuses_unknown_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "notes.txt"
    source.write_text("not geometry\n", encoding="utf-8")

    assert run(root, monkeypatch, "import", "add", str(source)) == 1
    assert "unsupported_import_suffix" in capsys.readouterr().err
    assert not (root / "imports").exists() or not any((root / "imports").iterdir())


def test_add_refuses_units_on_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "box.step"
    box_step(source)

    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm") == 1
    assert "step_units_not_applicable" in capsys.readouterr().err
    assert not (root / "imports" / "box.step").exists()


def test_list_reports_admitted_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    step = tmp_path / "box.step"
    box_step(step)
    mesh = tmp_path / "scan.stl"
    mesh.write_bytes(ASCII_STL)
    run(root, monkeypatch, "import", "add", str(step))
    run(root, monkeypatch, "import", "add", str(mesh), "--units", "in")
    capsys.readouterr()

    assert run(root, monkeypatch, "import", "list", "--json") == 0
    listed = cast("list[dict[str, Any]]", json.loads(capsys.readouterr().out))
    assert [entry["name"] for entry in listed] == ["box.step", "scan.stl"]
    assert [entry["kind"] for entry in listed] == ["step", "mesh"]
    assert "units" not in listed[0]
    assert "units" not in listed[1]


def test_list_on_an_empty_project_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    assert run(root, monkeypatch, "import", "list") == 0
    assert "no imports" in capsys.readouterr().out
