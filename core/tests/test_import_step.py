"""STEP ingest: conversion, resolution, staging, and the worker's ``import_step``.

Covers ``INGEST.md`` §1 from the bottom up:

* :mod:`hephaestus.geom.step_io` — bytes in, shape out, every OCCT failure
  mode named rather than silently empty;
* :mod:`hephaestus.core.executor.imports` — the declaration scan (string
  literals only) and the confined read beneath ``imports/`` (traversal,
  absolute paths and symlink escapes refused with named reasons);
* the build: an imported solid is a term in the expression — it booleans with
  native geometry, measures, and exports — while an unresolvable import is a §8
  build error at the ``import_step`` statement that named it, not an exception
  out of the harness.

Provenance is asserted the way ``INGEST.md`` demands it: imported solids
attribute to their ``import_step`` statement at BINDING scope, and there is no
per-face statement anywhere in the source map (the same honesty rule booleans
already obey).
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
from hephaestus.core.executor.imports import (
    STAGE_DIRNAME,
    DynamicImportPathError,
    ImportPayload,
    ImportResolutionError,
    declared_imports,
    read_import,
    stage_import,
    static_import_paths,
)
from hephaestus.core.executor.runner import (
    DEFAULT_RLIMITS,
    BuildRequest,
    UnpublishedBuild,
    run_build,
    worker_command,
    worker_ro_binds,
)
from hephaestus.core.executor.sandbox.base import SandboxSpec
from hephaestus.core.executor.sandbox.bwrap import build_bwrap_argv
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.geom import shape_volume
from hephaestus.geom.step_io import (
    StepReadError,
    read_step,
    read_step_bytes,
    shape_from_brep,
    shape_to_brep,
    write_step,
)

from opstore import sha256_bytes

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "step"
PLATE = FIXTURES / "plate.step"
PLATE_TALLER = FIXTURES / "plate_taller.step"
BOSS = FIXTURES / "boss.step"

#: A 40 x 20 x 5 plate: the fixture's exact volume, to 1e-6.
PLATE_VOLUME_MM3 = 40 * 20 * 5


def build(
    script: str,
    out_dir: Path,
    *,
    imports: dict[str, bytes] | None = None,
    import_errors: dict[str, str] | None = None,
) -> UnpublishedBuild:
    # Stage 12 amendment (``MESH_INGEST.md`` §1.1, §12 item 6a):
    # ``BuildRequest.imports`` carries an ``ImportPayload`` per path rather than
    # bare bytes, because the declared kind and unit have to reach the staging
    # code. STEP declares neither, so every payload here is the default kind
    # with no units and the staged bytes are what they always were.
    request = BuildRequest(
        part="ingested",
        script=script,
        imports={path: ImportPayload(data) for path, data in (imports or {}).items()},
        import_errors=import_errors or {},
    )
    return run_build(request, backend=UnsafeLocalBackend(), out_dir=out_dir)


def plate_bytes() -> bytes:
    return PLATE.read_bytes()


class TestStepIo:
    """Pure conversion: the geometry layer's half of ingest."""

    def test_reads_a_step_part_into_a_shape(self) -> None:
        shape = read_step_bytes(plate_bytes(), source="plate.step")
        assert shape_volume(shape) == pytest.approx(PLATE_VOLUME_MM3, abs=1e-6)
        assert len(shape.faces()) == 6

    def test_read_step_path_matches_read_step_bytes(self) -> None:
        assert shape_volume(read_step(PLATE)) == pytest.approx(
            shape_volume(read_step_bytes(plate_bytes())), abs=1e-9
        )

    def test_corrupt_payload_is_named_never_silent(self) -> None:
        with pytest.raises(StepReadError) as excinfo:
            read_step_bytes(b"ISO-10303-21;\nthis is not a STEP file\n", source="bad.step")
        assert "bad.step" in str(excinfo.value)

    def test_empty_payload_is_refused(self) -> None:
        with pytest.raises(StepReadError):
            read_step_bytes(b"", source="empty.step")

    def test_step_file_without_a_root_entity_is_refused(self) -> None:
        empty = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
        with pytest.raises(StepReadError) as excinfo:
            read_step_bytes(empty.encode(), source="hollow.step")
        assert "root entity" in str(excinfo.value)

    def test_brep_round_trip_preserves_the_solid(self) -> None:
        shape = read_step_bytes(plate_bytes())
        restored = shape_from_brep(shape_to_brep(shape))
        assert shape_volume(restored) == pytest.approx(shape_volume(shape), abs=1e-9)
        assert len(restored.faces()) == len(shape.faces())

    def test_unreadable_brep_is_refused(self) -> None:
        with pytest.raises(StepReadError):
            shape_from_brep(b"definitely not a brep")

    def test_write_step_round_trips_through_the_reader(self, tmp_path: Path) -> None:
        target = tmp_path / "out.step"
        write_step(read_step_bytes(plate_bytes()), target)
        assert shape_volume(read_step(target)) == pytest.approx(PLATE_VOLUME_MM3, abs=1e-6)


class TestDeclarationScan:
    """``import_step`` arguments are read statically; a computed one is refused."""

    def test_collects_literal_declarations_in_source_order(self) -> None:
        script = 'a = import_step("plate.step")\nb = import_step("boss.step")\n'
        declarations = declared_imports(ast.parse(script), source=script)
        assert [d.path for d in declarations] == ["plate.step", "boss.step"]
        assert [d.lineno for d in declarations] == [1, 2]
        assert [d.statement_index for d in declarations] == [0, 1]

    def test_finds_declarations_nested_in_loops(self) -> None:
        script = 'for n in ["a.step"]:\n    s = import_step("plate.step")\n'
        declarations = declared_imports(ast.parse(script), source=script)
        assert [d.path for d in declarations] == ["plate.step"]
        assert declarations[0].statement_index == 0

    @pytest.mark.parametrize(
        "expression",
        [
            "import_step(name)",
            'import_step("plate" + ".step")',
            'import_step(f"{name}.step")',
            'import_step(name="plate.step")',
            'import_step("a.step", "b.step")',
        ],
    )
    def test_dynamic_paths_are_refused_with_the_statement(self, expression: str) -> None:
        script = f"name = 'plate.step'\nshape = {expression}\n"
        with pytest.raises(DynamicImportPathError) as excinfo:
            declared_imports(ast.parse(script), source=script)
        assert excinfo.value.lineno == 2
        assert expression.split("(")[0] in excinfo.value.statement

    def test_static_paths_deduplicate_and_tolerate_bad_scripts(self) -> None:
        assert static_import_paths('a = import_step("p.step")\nb = import_step("p.step")\n') == (
            "p.step",
        )
        assert static_import_paths("this is not python(") == ()
        assert static_import_paths("s = import_step(name)") == ()


class TestConfinedResolution:
    """``imports/`` is the only reachable directory, rechecked at read time."""

    @pytest.fixture
    def imports_dir(self, tmp_path: Path) -> Path:
        root = tmp_path / "project" / "imports"
        (root / "vendor").mkdir(parents=True)
        shutil.copy(PLATE, root / "plate.step")
        shutil.copy(BOSS, root / "vendor" / "boss.step")
        (tmp_path / "project" / "secret.txt").write_text("not yours", encoding="utf-8")
        return root

    def test_reads_a_confined_file(self, imports_dir: Path) -> None:
        assert read_import(imports_dir, "plate.step", max_bytes=None) == plate_bytes()

    def test_reads_a_nested_file(self, imports_dir: Path) -> None:
        assert read_import(imports_dir, "vendor/boss.step", max_bytes=None) == BOSS.read_bytes()

    def test_missing_file_is_import_not_found(self, imports_dir: Path) -> None:
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(imports_dir, "absent.step", max_bytes=None)
        assert excinfo.value.reason == "import_not_found"
        assert excinfo.value.path == "absent.step"

    def test_missing_imports_dir_is_import_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(tmp_path / "nowhere", "plate.step", max_bytes=None)
        assert excinfo.value.reason == "import_not_found"

    def test_traversal_is_refused(self, imports_dir: Path) -> None:
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(imports_dir, "../secret.txt", max_bytes=None)
        assert excinfo.value.reason == "path_confinement"

    def test_absolute_paths_are_refused(self, imports_dir: Path) -> None:
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(imports_dir, "/etc/passwd", max_bytes=None)
        assert excinfo.value.reason == "invalid_import_path"

    def test_backslash_and_nul_are_refused(self, imports_dir: Path) -> None:
        for path in ("vendor\\boss.step", "plate.step\x00"):
            with pytest.raises(ImportResolutionError) as excinfo:
                read_import(imports_dir, path, max_bytes=None)
            assert excinfo.value.reason == "invalid_import_path"

    def test_symlinked_leaf_escape_is_refused(self, imports_dir: Path, tmp_path: Path) -> None:
        (imports_dir / "escape.step").symlink_to(tmp_path / "project" / "secret.txt")
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(imports_dir, "escape.step", max_bytes=None)
        assert excinfo.value.reason == "path_confinement"

    def test_symlinked_directory_escape_is_refused(self, imports_dir: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        shutil.copy(PLATE, outside / "plate.step")
        (imports_dir / "linked").symlink_to(outside)
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(imports_dir, "linked/plate.step", max_bytes=None)
        assert excinfo.value.reason == "path_confinement"

    def test_a_directory_is_not_an_import(self, imports_dir: Path) -> None:
        with pytest.raises(ImportResolutionError) as excinfo:
            read_import(imports_dir, "vendor", max_bytes=None)
        assert excinfo.value.reason == "path_confinement"


class TestStaging:
    """Conversion happens once, parent-side, into a read-only input area."""

    def test_stages_read_only_brep(self, tmp_path: Path) -> None:
        data = plate_bytes()
        staged = stage_import(
            data, path="plate.step", content_hash=sha256_bytes(data), out_dir=tmp_path
        )
        assert staged.parent == tmp_path / STAGE_DIRNAME
        assert not staged.stat().st_mode & 0o222, "staged BRep must be read-only"
        assert shape_volume(shape_from_brep(staged.read_bytes())) == pytest.approx(
            PLATE_VOLUME_MM3, abs=1e-6
        )

    def test_identical_bytes_stage_to_one_file(self, tmp_path: Path) -> None:
        data = plate_bytes()
        first = stage_import(data, path="a.step", content_hash=sha256_bytes(data), out_dir=tmp_path)
        second = stage_import(
            data, path="b.step", content_hash=sha256_bytes(data), out_dir=tmp_path
        )
        assert first == second

    def test_corrupt_step_is_named_at_the_resolver_layer(self, tmp_path: Path) -> None:
        data = b"ISO-10303-21;\ntruncated"
        with pytest.raises(ImportResolutionError) as excinfo:
            stage_import(
                data, path="broken.step", content_hash=sha256_bytes(data), out_dir=tmp_path
            )
        assert excinfo.value.reason == "unreadable_step"
        assert excinfo.value.path == "broken.step"


class TestImportedBuilds:
    """An imported solid is a term in the expression, not a mode."""

    def test_imported_geometry_booleans_with_native_geometry(self, tmp_path: Path) -> None:
        script = (
            'base = import_step("plate.step")\n'
            "pocket = Cylinder(3, 20)\n"
            "body = base - pocket\n"
            "part.geometry = body\n"
            'part.description = "plate with a through hole"\n'
        )
        built = build(script, tmp_path / "out", imports={"plate.step": plate_bytes()})
        assert built.result.status == "ok", built.result.error
        metrics = built.result.metrics
        assert metrics is not None
        assert metrics.solids == 1
        assert metrics.bbox_mm == pytest.approx((40.0, 20.0, 5.0), abs=1e-6)
        # A Ø6 through hole removed from the plate: measurably less material.
        assert metrics.volume_mm3 < PLATE_VOLUME_MM3
        assert metrics.volume_mm3 == pytest.approx(PLATE_VOLUME_MM3 - 9 * 3.14159265 * 5, abs=1e-3)

    def test_multiple_imports_measure_and_export(self, tmp_path: Path) -> None:
        script = (
            'plate = import_step("plate.step")\n'
            'boss = import_step("boss.step")\n'
            "part.geometry = plate + boss\n"
        )
        built = build(
            script,
            tmp_path / "out",
            imports={"plate.step": plate_bytes(), "boss.step": BOSS.read_bytes()},
        )
        assert built.result.status == "ok", built.result.error
        assert sorted(built.result.input_hashes.imports) == ["boss.step", "plate.step"]
        # The build artifact is a real shape: it measures and exports.
        final = shape_from_brep((tmp_path / "out" / "final.brep").read_bytes())
        assert shape_volume(final) > PLATE_VOLUME_MM3
        exported = tmp_path / "fused.step"
        write_step(final, exported)
        assert shape_volume(read_step(exported)) == pytest.approx(shape_volume(final), abs=1e-6)

    def test_input_hashes_record_the_imported_bytes(self, tmp_path: Path) -> None:
        data = plate_bytes()
        script = 'part.geometry = import_step("plate.step")\n'
        built = build(script, tmp_path / "out", imports={"plate.step": data})
        assert built.result.input_hashes.imports == {"plate.step": sha256_bytes(data)}

    def test_missing_file_fails_at_the_import_statement(self, tmp_path: Path) -> None:
        script = 'x = Box(1, 1, 1)\nbase = import_step("absent.step")\npart.geometry = base\n'
        built = build(
            script,
            tmp_path / "out",
            import_errors={"absent.step": "import 'absent.step' does not exist under imports/"},
        )
        error = built.result.error
        assert built.result.status == "failed"
        assert error is not None
        assert error.line == 2
        assert "absent.step" in error.message
        assert error.built_through is not None
        assert error.built_through.line == 1

    def test_corrupt_step_fails_at_the_import_statement(self, tmp_path: Path) -> None:
        script = 'base = import_step("broken.step")\npart.geometry = base\n'
        built = build(script, tmp_path / "out", imports={"broken.step": b"ISO-10303-21;\nnope"})
        error = built.result.error
        assert built.result.status == "failed"
        assert error is not None
        assert error.line == 1
        assert "broken.step" in error.message

    def test_undeclared_name_is_a_build_error(self, tmp_path: Path) -> None:
        script = 'base = import_step("never_staged.step")\npart.geometry = base\n'
        built = build(script, tmp_path / "out")
        error = built.result.error
        assert built.result.status == "failed"
        assert error is not None
        assert error.line == 1
        assert "never_staged.step" in error.message

    def test_dynamic_path_is_a_build_error_naming_the_statement(self, tmp_path: Path) -> None:
        script = 'name = "plate.step"\nbase = import_step(name)\npart.geometry = base\n'
        built = build(script, tmp_path / "out", imports={"plate.step": plate_bytes()})
        error = built.result.error
        assert built.result.status == "failed"
        assert error is not None
        assert error.line == 2
        assert error.type == "DynamicImportPathError"
        assert "string literal" in error.message
        assert any("> 2 |" in line for line in error.frame)

    def test_the_sandbox_never_binds_the_projects_imports_directory(self, tmp_path: Path) -> None:
        """Defense in depth: the secure mount plan cannot reach ``imports/`` at all.

        The namespace denial above is the contract-level refusal; this is the
        OS-level one. Only the staged input area (inside the one writable out
        dir) is reachable, which is exactly what makes ``import_step`` a lookup
        rather than a file open.
        """
        project = tmp_path / "project"
        imports_dir = project / "imports"
        imports_dir.mkdir(parents=True)
        shutil.copy(PLATE, imports_dir / "plate.step")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        staged = stage_import(
            plate_bytes(),
            path="plate.step",
            content_hash=sha256_bytes(plate_bytes()),
            out_dir=out_dir,
        )
        spec = SandboxSpec(
            worker_cmd=worker_command(),
            ro_binds=worker_ro_binds(),
            rw_out_dir=out_dir,
            rlimits=DEFAULT_RLIMITS,
            wall_clock_s=5.0,
        )
        argv = build_bwrap_argv("/usr/bin/bwrap", spec)
        bound = [
            Path(argv[i + 1]) for i, flag in enumerate(argv) if flag in ("--ro-bind", "--bind")
        ]
        assert not [path for path in bound if path == imports_dir or path in imports_dir.parents], (
            "the sandbox must not bind the project's imports/ directory"
        )
        assert any(path == out_dir or path in staged.parents for path in bound)

    def test_script_cannot_open_an_import_path_itself(self, tmp_path: Path) -> None:
        script = 'data = open("imports/plate.step", "rb").read()\npart.geometry = Box(1, 1, 1)\n'
        built = build(script, tmp_path / "out", imports={"plate.step": plate_bytes()})
        error = built.result.error
        assert built.result.status == "failed"
        assert error is not None
        assert error.line == 1
        assert "not available in part scripts" in error.message


class TestImportProvenance:
    """Binding scope attributes imported solids; faces get no statement."""

    def test_imported_solid_attributes_to_its_import_statement(self, tmp_path: Path) -> None:
        script = '# a comment line\nbase = import_step("plate.step")\npart.geometry = base\n'
        built = build(script, tmp_path / "out", imports={"plate.step": plate_bytes()})
        assert built.result.status == "ok", built.result.error
        source_map = built.source_map
        assert source_map is not None
        bindings = source_map["bindings"]
        assert isinstance(bindings, dict)
        events = bindings["base"]
        assert isinstance(events, list)
        assert events[0] == {"line": 2, "statement": 0, "iteration": 1, "call_site": None}

    def test_no_per_face_statement_is_recorded_for_imported_topology(self, tmp_path: Path) -> None:
        """Imported faces have NO creating statement — the boolean honesty rule."""
        script = (
            'base = import_step("plate.step")\n'
            "body = base - Cylinder(3, 20)\n"
            "part.geometry = body\n"
        )
        built = build(script, tmp_path / "out", imports={"plate.step": plate_bytes()})
        assert built.result.status == "ok", built.result.error
        source_map = built.source_map
        assert source_map is not None
        # The three recorded scopes are exactly bindings/booleans/tags; nothing
        # in the serialized map addresses a face.
        assert set(source_map) == {"version", "bindings", "booleans", "tags"}
        assert "face" not in json.dumps(source_map)

    def test_tag_on_imported_topology_resolves(self, tmp_path: Path) -> None:
        script = (
            'base = import_step("plate.step")\n'
            'tag(base.faces().sort_by(Axis.Z)[-1], "plate_top")\n'
            "part.geometry = base\n"
        )
        built = build(script, tmp_path / "out", imports={"plate.step": plate_bytes()})
        assert built.result.status == "ok", built.result.error
        assert "plate_top" in built.tag_fingerprints
        assert built.result.warnings == ()


class TestImportDeterminism:
    """Identical bytes ⇒ identical geometry (pinned OCCT), across processes."""

    def test_two_separate_process_builds_agree(self, tmp_path: Path) -> None:
        script = 'base = import_step("plate.step")\npart.geometry = base - Cylinder(2, 20)\n'
        data = plate_bytes()
        first = build(script, tmp_path / "a", imports={"plate.step": data})
        second = build(script, tmp_path / "b", imports={"plate.step": data})
        assert first.result.status == "ok"
        assert second.result.status == "ok"
        assert first.result.input_hashes.to_json() == second.result.input_hashes.to_json()
        left, right = first.result.metrics, second.result.metrics
        assert left is not None and right is not None
        assert left.volume_mm3 == pytest.approx(right.volume_mm3, abs=1e-6)
        assert left.bbox_mm == pytest.approx(right.bbox_mm, abs=1e-6)
        assert (left.solids, left.faces, left.genus) == (right.solids, right.faces, right.genus)

    def test_a_different_file_changes_the_input_hashes(self, tmp_path: Path) -> None:
        script = 'part.geometry = import_step("plate.step")\n'
        first = build(script, tmp_path / "a", imports={"plate.step": plate_bytes()})
        second = build(script, tmp_path / "b", imports={"plate.step": PLATE_TALLER.read_bytes()})
        assert first.result.input_hashes.script == second.result.input_hashes.script
        assert first.result.input_hashes.imports != second.result.input_hashes.imports
