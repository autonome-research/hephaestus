# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8A: import resolution, staging, refusals and determinism — at the tool surface.

Gate clauses covered here (``INGEST.md`` "Gate G8A"):

* *import resolution + staging (happy path; missing file, corrupt STEP,
  traversal/symlink escape all refused with named errors at the right layer)*;
* *the worker cannot open import paths directly (sandbox denial proven)*;
* *determinism (same bytes ⇒ identical metrics twice)*;
* *mixed imported+native geometry builds, measures, exports*.

The subject is what a model sees: it writes a part that names a file under
``imports/`` and calls ``build_part``. A refusal is therefore asserted as the §8
build error the model is handed at the offending statement — never as an
exception escaping the harness, and never as a message that leaked the content
of a file the script was not allowed to reach. The layer each refusal is named
at (``ImportResolutionError.reason`` /``DynamicImportPathError``) is unit
coverage; the gate's business is that the model is refused, at the right line,
with the file named.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from _g8a import PLATE_VOLUME_MM3, StepFixtures, build_ok, install_import, write_script
from hephaestus.testing.tools_fixture import Project

# A plate with a Ø6 through hole and a native boss stood on top of it: an
# imported solid used as a term in an ordinary expression (INGEST.md §1).
MIXED_SRC = """base = import_step("plate.step")
pocket = Cylinder(3, 20)
boss = Cylinder(4, 6).moved(Location((15, 0, 5.5)))
body = (base - pocket) + boss
part.geometry = body
part.description = "vendor plate, bored and bossed"
"""

PLAIN_SRC = 'part.geometry = import_step("plate.step")\n'

#: The Ø6 hole removed from the 40 x 20 x 5 plate, and the Ø8 x 6 boss stood on
#: top of it (they touch, they do not overlap), so the volumes simply add.
HOLE_MM3 = 3.0 * 3.0 * 3.14159265358979 * 5.0
BOSS_MM3 = 4.0 * 4.0 * 3.14159265358979 * 6.0


@pytest.fixture
def with_plate(project: Project, steps: StepFixtures) -> Project:
    install_import(project.root, "plate.step", steps.plate)
    return project


# ==========================================================================
# happy path: a declared import builds, measures and exports


def test_an_imported_solid_is_a_term_in_the_expression(with_plate: Project) -> None:
    """Build, measure and export a part whose geometry starts from a vendor file."""
    write_script(with_plate, "ingested", MIXED_SRC)

    built = build_ok(with_plate, "ingested")

    assert built["current"] is True
    volume = cast(
        "dict[str, Any]", with_plate.call("measure", {"kind": "volume", "a": "ingested/part"})
    )
    assert volume["value"] == pytest.approx(PLATE_VOLUME_MM3 - HOLE_MM3 + BOSS_MM3, abs=1e-2), (
        volume
    )
    bbox = cast(
        "dict[str, Any]", with_plate.call("measure", {"kind": "bbox", "a": "ingested/part"})
    )
    # The imported envelope, raised by the native boss: mixed geometry measured
    # as one body.
    assert bbox["value"][:2] == pytest.approx([40.0, 20.0], abs=1e-6)
    assert bbox["value"][2] == pytest.approx(11.0, abs=1e-6)

    exported = cast(
        "dict[str, Any]",
        with_plate.call("export_part", {"name": "ingested", "format": "step"}),
    )
    path = with_plate.layout.exports_dir / Path(exported["paths"][0]).name
    assert path.stat().st_size > 1024
    assert path.read_bytes().startswith(b"ISO-10303-21;")
    # §1 content-addressing reaches the export record: the file the geometry
    # came from is named in the same input hashes as the script.
    assert exported["source_input_hashes"]["imports"]["plate.step"].startswith("sha256:")


def test_imported_and_native_parts_measure_against_each_other(
    with_plate: Project, steps: StepFixtures
) -> None:
    """A whole-project measurement spanning an imported part and a native one."""
    install_import(with_plate.root, "boss.step", steps.boss)
    write_script(with_plate, "imported_plate", 'part.geometry = import_step("plate.step")\n')
    write_script(
        with_plate,
        "native_lid",
        "part.geometry = Box(40, 20, 3).moved(Location((0, 0, 6)))\n",
    )
    build_ok(with_plate, "imported_plate")
    build_ok(with_plate, "native_lid")
    # A cross-part measurement is taken over a coherent project snapshot, so the
    # fixture's own two parts have to be current too.
    with_plate.build("widget", "bracket")

    clearance = cast(
        "dict[str, Any]",
        with_plate.call(
            "measure",
            {"kind": "clearance", "a": "imported_plate/part", "b": "native_lid/part"},
        ),
    )
    interference = cast(
        "dict[str, Any]",
        with_plate.call(
            "measure",
            {"kind": "interference", "a": "imported_plate/part", "b": "native_lid/part"},
        ),
    )
    # The plate spans z ∈ [-2.5, 2.5]; the lid z ∈ [4.5, 7.5]. Two millimetres of
    # air between an imported solid and a native one, and no overlap.
    assert clearance["value"] == pytest.approx(2.0, abs=1e-6)
    assert interference["value"] == pytest.approx(0.0, abs=1e-9)


def test_two_declarations_of_the_same_file_are_one_staged_input(with_plate: Project) -> None:
    script = (
        'a = import_step("plate.step")\n'
        'b = import_step("plate.step").moved(Location((0, 40, 0)))\n'
        "part.geometry = a + b\n"
    )
    write_script(with_plate, "twinned", script)

    build_ok(with_plate, "twinned")

    current = with_plate.cad.current_build("twinned")
    assert current is not None
    assert list(current.input_hashes.imports) == ["plate.step"]
    metrics = current.metrics
    assert metrics is not None
    assert metrics.solids == 2


# ==========================================================================
# refusals: every one of them is a §8 build error at the naming statement


def build_error(project: Project, name: str, script: str) -> dict[str, Any]:
    write_script(project, name, script)
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "error", result
    return cast("dict[str, Any]", result["error"])


def test_a_missing_import_is_a_build_error_at_its_statement(project: Project) -> None:
    error = build_error(
        project,
        "absent_import",
        "shim = Box(1, 1, 1)\nbase = import_step('absent.step')\npart.geometry = base\n",
    )
    assert error["line"] == 2
    assert "absent.step" in error["message"]


def test_a_corrupt_step_is_a_build_error_at_its_statement(project: Project) -> None:
    install_import(project.root, "broken.step", b"ISO-10303-21;\nHEADER;\ntruncated")
    error = build_error(project, "corrupt_import", 'part.geometry = import_step("broken.step")\n')
    assert error["line"] == 1
    assert "broken.step" in error["message"]


def test_a_traversing_import_is_refused_without_reading_the_file(
    with_plate: Project, tmp_path: Path
) -> None:
    """Confinement holds and the refusal leaks nothing about what is outside."""
    secret = with_plate.root / "secret.txt"
    secret.write_text("SECRET-CONTENT-42\n", encoding="utf-8")

    error = build_error(with_plate, "traversing", 'part.geometry = import_step("../secret.txt")\n')

    assert error["line"] == 1
    assert "SECRET-CONTENT-42" not in error["message"]
    assert "../secret.txt" in error["message"]


def test_a_symlink_out_of_imports_is_refused(with_plate: Project, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "plate.step").write_bytes((with_plate.root / "imports" / "plate.step").read_bytes())
    (with_plate.root / "imports" / "escape.step").symlink_to(outside / "plate.step")

    error = build_error(with_plate, "escaped", 'part.geometry = import_step("escape.step")\n')

    assert error["line"] == 1
    assert "escape.step" in error["message"]
    assert with_plate.cad.current_build("escaped") is None


def test_a_dynamic_import_path_is_refused_at_its_statement(with_plate: Project) -> None:
    """A computed path cannot be frozen or hashed, so it is not a path at all."""
    error = build_error(
        with_plate,
        "dynamic",
        'name = "plate" + ".step"\npart.geometry = import_step(name)\n',
    )
    assert error["line"] == 2
    assert error["type"] == "DynamicImportPathError"
    assert "string literal" in error["message"]


def test_a_refused_import_publishes_nothing(project: Project) -> None:
    build_error(project, "never_built", 'part.geometry = import_step("absent.step")\n')
    assert project.cad.current_build("never_built") is None


# ==========================================================================
# the script itself never touches the filesystem


def test_the_script_cannot_open_the_import_it_declares(with_plate: Project) -> None:
    """``import_step`` is harness-resolved: the sandbox has no file access at all."""
    error = build_error(
        with_plate,
        "self_service",
        'base = import_step("plate.step")\n'
        'raw = open("imports/plate.step", "rb").read()\n'
        "part.geometry = base\n",
    )
    assert error["line"] == 2
    assert "not available in part scripts" in error["message"]


# ==========================================================================
# determinism


def test_the_same_bytes_produce_identical_metrics_twice(with_plate: Project) -> None:
    write_script(with_plate, "first_pass", PLAIN_SRC)
    write_script(with_plate, "second_pass", PLAIN_SRC)

    build_ok(with_plate, "first_pass")
    build_ok(with_plate, "second_pass")

    left = with_plate.cad.current_build("first_pass")
    right = with_plate.cad.current_build("second_pass")
    assert left is not None and right is not None
    assert left.input_hashes.imports == right.input_hashes.imports
    a, b = left.metrics, right.metrics
    assert a is not None and b is not None
    assert a.volume_mm3 == pytest.approx(b.volume_mm3, abs=1e-9)
    assert a.bbox_mm == pytest.approx(b.bbox_mm, abs=1e-9)
    assert (a.solids, a.faces, a.genus) == (b.solids, b.faces, b.genus)


def test_a_different_file_is_a_different_input(with_plate: Project, steps: StepFixtures) -> None:
    write_script(with_plate, "pinned", PLAIN_SRC)
    build_ok(with_plate, "pinned")
    before = with_plate.cad.current_build("pinned")

    install_import(with_plate.root, "plate.step", steps.plate_taller)
    build_ok(with_plate, "pinned")
    after = with_plate.cad.current_build("pinned")

    assert before is not None and after is not None
    assert before.input_hashes.script == after.input_hashes.script
    assert before.input_hashes.imports != after.input_hashes.imports
    assert after.metrics is not None
    assert after.metrics.bbox_mm[2] == pytest.approx(8.0, abs=1e-6)


# ==========================================================================
# the OS sandbox, not just the namespace


@pytest.mark.skipif(
    __import__("sys").platform != "linux",
    reason="the OS sandbox clause needs Linux",
)
def test_the_secure_sandbox_builds_an_import_without_reaching_the_project(
    tmp_path: Path, steps: StepFixtures
) -> None:
    """The staged BRep is reachable inside the sandbox; ``imports/`` is not.

    The namespace denial above is the contract-level refusal (``open`` does not
    exist in a part script). This is the OS-level one, and it is asserted on a
    build that really ran under the probed sandbox: the same job that produced
    geometry from ``plate.step`` had no mount through which it could have read
    ``plate.step``.
    """
    from hephaestus.core.executor.runner import (
        DEFAULT_RLIMITS,
        BuildRequest,
        run_build,
        worker_command,
        worker_ro_binds,
    )
    from hephaestus.core.executor.sandbox.base import SandboxSpec
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, build_bwrap_argv, find_bwrap

    bwrap = find_bwrap()
    if bwrap is None:
        pytest.skip("no bwrap on this machine: the OS-sandbox clause cannot be evidenced")

    project = tmp_path / "project"
    imports_dir = project / "imports"
    imports_dir.mkdir(parents=True)
    (imports_dir / "plate.step").write_bytes(steps.plate)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    built = run_build(
        BuildRequest(part="secure", script=PLAIN_SRC, imports={"plate.step": steps.plate}),
        backend=BwrapBackend(),
        out_dir=out_dir,
    )

    assert built.result.status == "ok", built.result.error
    assert built.result.metrics is not None
    assert built.result.metrics.volume_mm3 == pytest.approx(PLATE_VOLUME_MM3, abs=1e-6)

    spec = SandboxSpec(
        worker_cmd=worker_command(),
        ro_binds=worker_ro_binds(),
        rw_out_dir=out_dir,
        rlimits=DEFAULT_RLIMITS,
        wall_clock_s=5.0,
    )
    bound = [
        Path(argv[i + 1])
        for argv in [build_bwrap_argv(bwrap, spec)]
        for i, flag in enumerate(argv)
        if flag in ("--ro-bind", "--bind")
    ]
    assert not [p for p in bound if p == imports_dir or p in imports_dir.parents], (
        "the sandbox must not bind the project's imports/ directory"
    )
