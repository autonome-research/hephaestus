# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""G12A clauses 3-4: the confinement walk and the declaration grammar.

Clause 3's whole point is that the new terms bought no new reach. The walk is
one ``O_NOFOLLOW`` directory descriptor per component with ``S_ISREG`` on the
open descriptor; ``MESH_INGEST.md`` §9 says this document "does not claim the
function is untouched — it claims the confinement property is", because
``read_import`` genuinely gained the §1.6 size refusal. So the property is
re-proved here for the new kinds rather than inherited from G8A's proof for
STEP.

Clause 4's point is narrower and sharper: the grammar widened by exactly one
keyword and not one inch more. A computed path is still refused, a computed
*unit* is refused for the same reason (a value the freeze cannot read cannot be
frozen), and ``import_step`` with any keyword is refused exactly as it was
before this stage touched the function.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from _g12a import MeshFixtures, build_error, install_import
from hephaestus.core.executor.imports import (
    DynamicImportPathError,
    ImportResolutionError,
    declared_imports,
    read_import,
    static_import_declarations,
)
from hephaestus.geom.mesh import mesh_max_bytes
from hephaestus.testing.tools_fixture import Project

# ==========================================================================
# clause 3: confinement, unchanged, for the new kinds


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("../secret.txt", "secret"),
        ("/etc/passwd", "passwd"),
        ("nested/../../secret.txt", "secret"),
    ],
)
def test_traversal_and_absolute_paths_are_refused_for_a_mesh(
    project: Project, path: str, needle: str
) -> None:
    """A mesh term reaches exactly as far as a STEP term: nowhere outside."""
    secret = project.root / "secret.txt"
    secret.write_text("SECRET-CONTENT-42\n", encoding="utf-8")

    error = build_error(
        project,
        "escaping_" + needle,
        f'scan = import_mesh("{path}", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )

    assert error["line"] == 1
    assert "SECRET-CONTENT-42" not in error["message"]
    assert path in error["message"]


def test_a_symlinked_leaf_out_of_imports_is_refused(
    project: Project, meshes: MeshFixtures, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.ply").write_bytes(meshes.cube_ply_binary)
    (project.root / "imports").mkdir(exist_ok=True)
    (project.root / "imports" / "link.ply").symlink_to(outside / "real.ply")

    error = build_error(
        project,
        "symlinked_leaf",
        'scan = import_mesh("link.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )

    assert error["line"] == 1
    assert "link.ply" in error["message"]
    assert project.cad.current_build("symlinked_leaf") is None


def test_a_symlinked_parent_component_is_refused(
    project: Project, meshes: MeshFixtures, tmp_path: Path
) -> None:
    """The walk refuses a symlinked *directory* component, not only a leaf."""
    outside = tmp_path / "vendor"
    outside.mkdir()
    (outside / "real.ply").write_bytes(meshes.cube_ply_binary)
    (project.root / "imports").mkdir(exist_ok=True)
    (project.root / "imports" / "linked").symlink_to(outside, target_is_directory=True)

    error = build_error(
        project,
        "symlinked_parent",
        'scan = import_mesh("linked/real.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )

    assert error["line"] == 1
    assert "linked/real.ply" in error["message"]


def test_the_script_cannot_open_an_import_path_itself(
    project: Project, meshes: MeshFixtures
) -> None:
    """``open`` is absent from the namespace, so the script has no second route.

    The registry reads the staged files; the script never does. That is the
    property the two new terms had to preserve, and it is the reason a mesh
    import is a lookup rather than a file open even though it now reads *two*
    staged files instead of one.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    error = build_error(
        project,
        "peeking",
        'scan = import_mesh("limb.ply", units="mm")\n'
        'data = open("imports/limb.ply", "rb").read()\n'
        "part.geometry = Box(1, 1, 1)\n",
    )
    assert error["line"] == 2
    assert "open" in error["message"]


@pytest.mark.skipif(sys.platform != "linux", reason="the OS sandbox clause needs Linux")
def test_the_secure_sandbox_builds_a_mesh_import_without_reaching_the_project(
    tmp_path: Path, meshes: MeshFixtures
) -> None:
    """The OS-level half, "exactly as G8A proves it for STEP" (clause 3).

    The namespace denial above is the *contract-level* refusal: ``open`` does not
    exist in a part script, so it fails as a ``NameError``. That proof is worth
    having and it is not this one. A namespace is a thing the harness composes,
    and "the name is missing" is a statement about the vocabulary, not about the
    kernel — a worker that grew a route to the filesystem by some other means
    (a library that opens files, a leaked handle) would pass it unchanged.

    This is the OS-level refusal, and it is asserted on a build that really ran
    under the probed bubblewrap sandbox: the same job that produced geometry
    from ``limb.ply`` had **no mount through which it could have read
    ``limb.ply``**. The mesh case needs its own proof rather than G8A's because
    a mesh import stages *two* files (blob + sidecar) where STEP stages one, and
    "two files under the out dir" is a different mount question from "one".
    """
    from hephaestus.core.executor.imports import ImportPayload
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

    project_root = tmp_path / "project"
    imports_dir = project_root / "imports"
    imports_dir.mkdir(parents=True)
    (imports_dir / "limb.ply").write_bytes(meshes.cube_ply_binary)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    built = run_build(
        BuildRequest(
            part="secure_scan",
            script=(
                'scan = import_mesh("limb.ply", units="mm")\n'
                "part.geometry = Box(scan.bbox_mm[0], 2.0, 2.0)\n"
            ),
            imports={"limb.ply": ImportPayload(meshes.cube_ply_binary, "mesh", ("mm",))},
        ),
        backend=BwrapBackend(),
        out_dir=out_dir,
    )

    # The build really ran, and it really read the scan: the box it authored is
    # as wide as the cube fixture's bounding box.
    assert built.result.status == "ok", built.result.error
    assert built.result.metrics is not None
    assert built.result.metrics.bbox_mm[0] == pytest.approx(10.0, abs=1e-6)

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


def test_a_directory_named_as_a_mesh_is_not_a_regular_file(project: Project) -> None:
    (project.root / "imports" / "folder.ply").mkdir(parents=True)
    error = build_error(
        project,
        "directory_import",
        'scan = import_mesh("folder.ply", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    assert error["line"] == 1
    assert "folder.ply" in error["message"]


def test_read_import_requires_its_ceiling_at_every_call_site(
    project: Project, meshes: MeshFixtures
) -> None:
    """``max_bytes`` has no default, so a third caller is a TYPE error.

    §1.6 asks for exactly this: a caller that forgets to state a ceiling must
    fail to compile rather than silently inherit an unbounded read. The runtime
    check below is the executable half of that — the static half is pyright.
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    imports_dir = project.root / "imports"

    with pytest.raises(TypeError):
        read_import(imports_dir, "limb.ply")  # pyright: ignore[reportCallIssue]

    assert read_import(imports_dir, "limb.ply", max_bytes=None) == meshes.cube_ply_binary
    assert (
        read_import(imports_dir, "limb.ply", max_bytes=mesh_max_bytes()) == meshes.cube_ply_binary
    )
    with pytest.raises(ImportResolutionError) as excinfo:
        read_import(imports_dir, "limb.ply", max_bytes=1)
    assert excinfo.value.reason == "mesh_import_too_large"


# ==========================================================================
# clause 4: the grammar widened by one keyword, and by nothing else


@pytest.mark.parametrize(
    "expression",
    [
        'import_mesh(name, units="mm")',
        'import_mesh("limb" + ".ply", units="mm")',
        'import_mesh(f"{name}", units="mm")',
        'import_point_cloud(name, units="mm")',
    ],
)
def test_a_computed_path_is_still_refused_at_its_line(expression: str) -> None:
    script = f"name = 'limb.ply'\nscan = {expression}\n"
    with pytest.raises(DynamicImportPathError) as excinfo:
        declared_imports(ast.parse(script), source=script)
    assert excinfo.value.lineno == 2
    assert excinfo.value.col == 7
    assert expression.split("(")[0] in excinfo.value.statement


@pytest.mark.parametrize(
    "expression",
    [
        'import_mesh("limb.ply", units=unit)',
        'import_mesh("limb.ply", units="m" + "m")',
        'import_mesh("limb.ply", units=f"{unit}")',
        'import_mesh("limb.ply", scale="mm")',
        'import_mesh("limb.ply", **kwargs)',
    ],
)
def test_a_computed_or_unknown_keyword_is_refused_for_the_same_reason(
    expression: str,
) -> None:
    """The static-literal rule is not relaxed — it is extended to the unit.

    The declared unit is baked into the staged geometry before the build runs
    (§1.5 step 3), so a unit the freeze cannot read is a unit the geometry
    cannot be staged at. That is the same argument as the path's, and it gets
    the same refusal.
    """
    script = f"unit = 'mm'\nkwargs = {{}}\nscan = {expression}\n"
    with pytest.raises(DynamicImportPathError) as excinfo:
        declared_imports(ast.parse(script), source=script)
    assert excinfo.value.lineno == 3


def test_a_positional_only_mesh_import_parses_and_refuses_at_the_statement(
    project: Project, meshes: MeshFixtures
) -> None:
    """No ``units=`` is a REFUSAL, not a grammar error, and the distinction is real.

    The declaration is perfectly readable — the freeze can name and hash the
    file — so it is the *file* that cannot be admitted without a unit. Making it
    a grammar error would have reported it as an unfrozen declaration, which is
    a different and untrue diagnosis.
    """
    script = 'scan = import_mesh("limb.ply")\npart.geometry = Box(1, 1, 1)\n'
    declarations = declared_imports(ast.parse(script), source=script)
    assert [(d.path, d.kind, d.units) for d in declarations] == [("limb.ply", "mesh", None)]

    install_import(project.root, "limb.ply", meshes.cube_ply_binary)
    error = build_error(project, "unitless", script)
    assert error["line"] == 1
    assert "units" in error["message"]


def test_import_step_with_a_keyword_is_still_refused_no_regression() -> None:
    """The Stage 8A grammar for ``import_step`` did not move a character."""
    script = 'base = import_step(name="plate.step")\n'
    with pytest.raises(DynamicImportPathError):
        declared_imports(ast.parse(script), source=script)
    script = 'base = import_step("plate.step", units="mm")\n'
    with pytest.raises(DynamicImportPathError):
        declared_imports(ast.parse(script), source=script)


def test_declarations_carry_kind_and_units_to_the_freeze() -> None:
    """The freeze threads declarations, because a path string carries neither."""
    script = (
        'a = import_step("plate.step")\n'
        'b = import_mesh("limb.ply", units="in")\n'
        'c = import_point_cloud("marks.xyz", units="m")\n'
    )
    declarations = static_import_declarations(script)
    assert [(d.path, d.kind, d.units) for d in declarations] == [
        ("plate.step", "step", None),
        ("limb.ply", "mesh", "in"),
        ("marks.xyz", "points", "m"),
    ]
