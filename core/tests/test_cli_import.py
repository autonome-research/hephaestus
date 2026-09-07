"""``heph import add|list`` — project ingress into ``imports/``.

Kernel import (``import_step`` / ``import_mesh``) is not under test here; this
is the operator-side copy that puts a vendor file where those terms can name
it. Confinement matches Stage 8A/12A: destination is a regular file beneath
``imports/``, ``O_NOFOLLOW``, original untouched.
"""

from __future__ import annotations

import json
import os
import struct
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

# An axis-aligned cube, 12 outward triangles, that sews to a VALID solid —
# needed wherever a test must actually *build* the seeded part rather than
# merely admit the file (``ASCII_STL`` above is one open triangle: real for
# admission tests, refused by the sewer for anything that tries to build it).
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


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cube_stl(*, scale: float = 1.0) -> bytes:
    """Binary STL for a cube; a different ``scale`` yields different bytes
    while remaining a valid, buildable solid."""
    verts = tuple((x * scale, y * scale, z * scale) for x, y, z in _CUBE_V)
    out = bytearray(b"\x00" * 80)
    out += struct.pack("<I", len(_CUBE_F))
    for tri in _CUBE_F:
        a, b, c = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        normal = _cross(_sub(b, a), _sub(c, a))
        length = sum(component**2 for component in normal) ** 0.5
        if length:
            normal = tuple(component / length for component in normal)
        out += struct.pack("<3f", *normal)
        for corner in (a, b, c):
            out += struct.pack("<3f", *corner)
        out += struct.pack("<H", 0)
    return bytes(out)


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
        "recorded": True,
        "sha256": sha256_bytes(payload),
        "units": None,
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
        "recorded": True,
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


def test_add_refuses_a_directory_as_a_directory_not_no_such_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``heph import add <dir>`` must not assert that the directory does not
    exist — one of the six sites ``require_input_file`` unifies
    (ledger J-cli-robustness-12)."""
    root = project(tmp_path / "proj")
    a_dir = tmp_path / "adir"
    a_dir.mkdir()
    assert run(root, monkeypatch, "import", "add", str(a_dir)) == 2
    err = capsys.readouterr().err
    assert "is a directory" in err
    assert "no such" not in err


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


def test_add_part_refuses_a_point_cloud_without_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A cloud has no solid conversion; reconstruction is out of scope."""
    from hephaestus.core.cli_import import ImportIngressError, seed_part_script

    with pytest.raises(ImportIngressError) as caught:
        seed_part_script("marks.xyz", kind="points", units="mm")
    assert caught.value.reason == "point_cloud_has_no_solid"

    root = project(tmp_path / "proj")
    source = tmp_path / "marks.xyz"
    source.write_text("0 0 0\n1 0 0\n0 1 0\n", encoding="utf-8")

    assert (
        run(root, monkeypatch, "import", "add", str(source), "--units", "mm", "--part", "cloud")
        == 1
    )
    err = capsys.readouterr().err
    assert "point_cloud_has_no_solid" in err
    assert not (root / "parts" / "cloud.py").exists()
    assert not (root / "imports" / "marks.xyz").exists()


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
    """``heph import list`` must recover the declared unit (ledger
    J-cli-robustness-8): ``--units`` is compulsory on a mesh import precisely
    because it is not recoverable from the file, so discarding it after
    admission is the exact failure the flag guards against. A STEP import
    reports no unit at all (the flag is forbidden there) — ``units`` is
    present and ``null``, not simply absent, so a caller can tell "no unit"
    from "field not implemented"."""
    root = project(tmp_path / "proj")
    step = tmp_path / "box.step"
    box_step(step)
    mesh = tmp_path / "scan.stl"
    mesh.write_bytes(ASCII_STL)
    run(root, monkeypatch, "import", "add", str(step))
    run(root, monkeypatch, "import", "add", str(mesh), "--units", "in")
    capsys.readouterr()

    assert run(root, monkeypatch, "import", "list", "--json") == 0
    # One listing envelope, not a bare array (ledger J-cli-robustness-7).
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert payload["status"] == "ok", payload
    listed = cast("list[dict[str, Any]]", payload["imports"])
    assert [entry["name"] for entry in listed] == ["box.step", "scan.stl"]
    assert [entry["kind"] for entry in listed] == ["step", "mesh"]
    assert listed[0]["units"] is None  # STEP: the flag is forbidden, not merely absent
    assert listed[1]["units"] == "in"  # the declared unit, recovered
    assert listed[0]["recorded"] is True
    assert listed[1]["recorded"] is True


def test_list_reports_a_hand_copied_file_with_a_null_unit_and_unrecorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file dropped into ``imports/`` by hand (never through ``import add``)
    has no admission to recover a unit from; the listing must say so plainly —
    ``units: null`` and ``recorded: false`` — rather than hide the file or
    guess."""
    root = project(tmp_path / "proj")
    (root / "imports").mkdir()
    (root / "imports" / "hand.stl").write_bytes(ASCII_STL)

    assert run(root, monkeypatch, "import", "list", "--json") == 0
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    listed = cast("list[dict[str, Any]]", payload["imports"])
    assert [entry["name"] for entry in listed] == ["hand.stl"]
    assert listed[0]["units"] is None
    assert listed[0]["recorded"] is False


def test_list_on_an_empty_project_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    assert run(root, monkeypatch, "import", "list") == 0
    assert "no imports" in capsys.readouterr().out


# -- J-cli-robustness-9: re-admitting a name under a contradictory unit -----


def test_readmitting_the_same_bytes_and_unit_is_an_idempotent_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(ASCII_STL)
    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm") == 0
    capsys.readouterr()

    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm") == 0
    capsys.readouterr()
    assert run(root, monkeypatch, "import", "list", "--json") == 0
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    listed = cast("list[dict[str, Any]]", payload["imports"])
    assert len(listed) == 1, listed  # one index entry, not a duplicate


def test_readmitting_under_a_contradictory_unit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Any part script or scan already written against the first declaration
    describes a different physical object once the unit silently changes —
    the re-admission must refuse, naming both declared units, and must not
    touch the admitted file."""
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(ASCII_STL)
    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm") == 0
    capsys.readouterr()

    code = run(root, monkeypatch, "import", "add", str(source), "--units", "in")
    err = capsys.readouterr().err
    assert code == 1, err
    assert "import_unit_conflict" in err
    assert "'mm'" in err
    assert "'in'" in err
    assert "--redeclare" in err

    assert run(root, monkeypatch, "import", "list", "--json") == 0
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    listed = cast("list[dict[str, Any]]", payload["imports"])
    assert len(listed) == 1
    assert listed[0]["units"] == "mm"  # unchanged: the contradiction never wrote


def test_readmitting_different_bytes_under_the_same_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(ASCII_STL)
    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm") == 0
    capsys.readouterr()

    other = tmp_path / "other.stl"
    other.write_bytes(
        ASCII_STL.replace(b"box", b"cube")  # different bytes, same admitted name
    )
    code = run(
        root, monkeypatch, "import", "add", str(other), "--name", "scan.stl", "--units", "mm"
    )
    err = capsys.readouterr().err
    assert code == 1, err
    assert "import_bytes_conflict" in err
    assert "--redeclare" in err


def test_redeclare_replaces_a_contradictory_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The explicit escape hatch: with ``--redeclare`` the new declaration
    replaces the old one instead of being refused."""
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(ASCII_STL)
    assert run(root, monkeypatch, "import", "add", str(source), "--units", "mm") == 0
    capsys.readouterr()

    code = run(
        root, monkeypatch, "import", "add", str(source), "--units", "in", "--redeclare", "--json"
    )
    out = capsys.readouterr().out
    assert code == 0, out

    assert run(root, monkeypatch, "import", "list", "--json") == 0
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    listed = cast("list[dict[str, Any]]", payload["imports"])
    assert listed[0]["units"] == "in"


def test_redeclare_with_different_bytes_marks_importing_parts_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A replaced import's bytes changed the build input; the part that
    imports it must go stale immediately, not at the next build (INGEST.md
    §1)."""
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.stl"
    source.write_bytes(cube_stl())
    assert (
        run(root, monkeypatch, "import", "add", str(source), "--units", "mm", "--part", "socket")
        == 0
    )
    capsys.readouterr()
    build_code = run(root, monkeypatch, "build", "socket", "--unsafe-local-executor")
    build_err = capsys.readouterr().err
    assert build_code == 0, build_err

    replacement = tmp_path / "scan2.stl"
    replacement.write_bytes(cube_stl(scale=2.0))
    code = run(
        root,
        monkeypatch,
        "import",
        "add",
        str(replacement),
        "--name",
        "scan.stl",
        "--units",
        "mm",
        "--redeclare",
    )
    out = capsys.readouterr().out
    assert code == 0, out
    capsys.readouterr()

    assert run(root, monkeypatch, "part", "show", "socket", "--json") == 0
    shown = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert shown.get("stale") is True, shown
