# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""G12A clauses 1-2: the admitted formats build, and every reachable refusal fires.

The subject is what a model sees: it writes a part that names a file under
``imports/`` and calls ``build_part``. A refusal is therefore asserted as the §8
build error the model is handed **at the offending statement** — never as an
exception escaping the harness, and never as a silently-honoured guess.

Clause 2's shape is worth stating, because it is the clause most easily written
dishonestly. The §1.7 vocabulary has eleven codes; ten are reachable in 12A and
fire here. The eleventh, ``mesh_units_conflict``, is **asserted unreachable**
rather than skipped: every unit-carrying format refuses at admission and the
five admitted extensions carry no unit at all, so the clause enumerates that
fact instead of enumerating ten codes and calling it "every". If a later
amendment admits a unit-carrying format without also making the code fire, this
test fails — which is exactly the drift the assertion exists to catch.
"""

from __future__ import annotations

import pytest
from _g12a import MeshFixtures, build_error, build_ok, install_import, scan_facts, write_script
from hephaestus.geom.mesh import (
    MESH_EXTENSIONS,
    MESH_REFUSALS,
    MESH_UNITS,
    MeshReadError,
    canonicalize_mesh,
    sniff_format,
    unit_factor,
)
from hephaestus.testing.tools_fixture import Project

CUBE_VOLUME_MM3 = 1000.0
CUBE_AREA_MM2 = 600.0

#: Every admitted mesh fixture, by the extension the file must carry.
ADMITTED_MESHES = (
    ("cube_bin.stl", "cube_stl_binary"),
    ("cube_ascii.stl", "cube_stl_ascii"),
    ("cube_bin.ply", "cube_ply_binary"),
    ("cube_ascii.ply", "cube_ply_ascii"),
    ("cube.obj", "cube_obj"),
    ("cube.off", "cube_off"),
)


# ==========================================================================
# clause 1: every admitted format imports, with independently computed counts


@pytest.mark.parametrize(("name", "attribute"), ADMITTED_MESHES)
def test_each_admitted_mesh_format_imports_with_hand_computed_facts(
    project: Project, meshes: MeshFixtures, name: str, attribute: str
) -> None:
    """A cube is a cube in all six encodings: 8 vertices, 12 triangles, χ = 2.

    The counts are arithmetic, not a golden: an axis-aligned cube triangulated
    two-per-face has 8 welded vertices, 18 edges and 12 triangles, so
    ``V - E + F`` is 2, its area is ``6 x 10^2`` and its polyhedron volume is
    exactly ``10^3`` because a cube's facets are its faces — the only shape where
    the inscribed-facet bias of §2.2 is zero.
    """
    data: bytes = getattr(meshes, attribute)
    install_import(project.root, name, data)
    write_script(
        project,
        "scanned",
        f'scan = import_mesh("{name}", units="mm")\n'
        "part.geometry = Box(scan.bbox_mm[0], scan.bbox_mm[1], scan.bbox_mm[2])\n"
        "print(scan.vertex_count, scan.triangle_count, scan.euler_characteristic)\n",
    )

    build_ok(project, "scanned")

    asset = scan_facts(name, data, "mm")
    assert asset.vertex_count == 8
    assert asset.triangle_count == 12
    assert asset.euler_characteristic == 2
    assert asset.watertight_at_weld_tol is True
    assert asset.bbox_mm == pytest.approx((10.0, 10.0, 10.0), abs=1e-9)
    assert asset.tessellated_area_mm2 == pytest.approx(CUBE_AREA_MM2, abs=1e-9)
    assert asset.tessellated_volume_mm3 == pytest.approx(CUBE_VOLUME_MM3, abs=1e-9)


def test_a_point_cloud_imports_as_its_own_kind(project: Project, meshes: MeshFixtures) -> None:
    """``.xyz`` is a point cloud: three points, a bbox, and nothing borrowed."""
    from hephaestus.geom.mesh import canonicalize_points, point_cloud_asset_from_staged

    install_import(project.root, "landmarks.xyz", meshes.points_xyz)
    write_script(
        project,
        "clouded",
        'cloud = import_point_cloud("landmarks.xyz", units="mm")\n'
        "part.geometry = Box(cloud.bbox_mm[0] + 1, cloud.bbox_mm[1] + 1, cloud.bbox_mm[2] + 1)\n",
    )

    build_ok(project, "clouded")

    canonical = canonicalize_points("landmarks.xyz", meshes.points_xyz, "mm")
    cloud = point_cloud_asset_from_staged(canonical.blob, source_path="l.xyz", units="mm")
    assert cloud.point_count == 3
    assert cloud.bbox_mm == pytest.approx((4.0, 5.0, 6.5), abs=1e-9)


# ==========================================================================
# clause 2: every §1.7 refusal reachable in 12A, at the right layer
#
# "With its exact code" is the half of this clause that is easy to fake. A
# message-substring assertion ("empty", "units", "finite") does not bind the
# code at all: a raise site could keep its prose and change its ``reason=``
# underneath, the vocabulary would drift, and every assertion here would stay
# green. So each reachable code is asserted TWICE, at the two layers the clause
# names — ``MeshReadError.reason`` where the refusal is decided, and the exact
# code string inside the §8 build error the model is handed. The two cannot
# disagree, because ``MeshReadError`` derives the message suffix from ``reason``
# (``geom/mesh.py``) rather than letting a raise site write it by hand.


#: Every §1.7 code reachable in 12A, with the fixture that reaches it and the
#: layer it is decided at. The table is asserted COMPLETE against
#: ``MESH_REFUSALS`` below, so a code added to the vocabulary without a fixture
#: fails the gate here rather than being quietly untested.
REACHABLE_CODES: tuple[str, ...] = (
    "mesh_format_unsupported",
    "mesh_format_mismatch",
    "mesh_unreadable",
    "mesh_empty",
    "mesh_multi_object",
    "mesh_not_finite",
    "mesh_degenerate_only",
    "mesh_units_undeclared",
    "mesh_units_unsupported",
    "mesh_import_too_large",
)


def test_the_ten_reachable_codes_are_the_vocabulary_minus_the_unreachable_one() -> None:
    """The table above is the clause's own completeness check.

    Ten reachable plus the one asserted unreachable IS the closed eleven. A
    twelfth code, or a rename, breaks this line before it can reach a fixture
    that was never written for it.
    """
    assert set(REACHABLE_CODES) | {"mesh_units_conflict"} == set(MESH_REFUSALS)
    assert len(REACHABLE_CODES) == 10


#: Where a §1.7 code could be written by hand into a message. Product source
#: only: a test may name a code in a string because asserting one is its job.
_PRODUCT_ROOTS: tuple[str, ...] = ("core/src", "server/src", "bench/src", "contract/src")


def _mesh_ingest_vocabulary() -> tuple[str, ...]:
    """Every ``MESH_INGEST.md`` §10 code, read from the code's own declarations.

    Assembled from the four closed vocabularies plus the one lint code rather
    than re-typed here, so a code added to any of them is policed the moment it
    exists. That is the difference the third repair pass turned up: the detector
    below iterated ``MESH_REFUSALS`` alone, so it covered the admission third of
    §10 and was blind to the other two thirds — twenty-six raise sites across
    ``core/src`` and ``bench/src`` were hand-writing a ``code: `` prefix, and two
    of them (``point_cloud_not_a_shape``, ``mesh_topology_not_taggable``, the two
    codes G12A.14 and G12A.15 bind by message substring) had no ``reason=``
    behind the prose at all. A detector that cannot see two thirds of the
    vocabulary it exists to police is a detector that reads as coverage.
    """
    from hephaestus.core.project_compare import MESH_INGEST_REFUSAL_REASONS
    from hephaestus.geom.compare import SCAN_REFUSALS
    from hephaestus.geom.mesh import (
        MESH_OPERATION_REFUSALS,
        MESH_TYPE_REFUSALS,
    )

    codes = (
        set(MESH_REFUSALS)
        | set(MESH_TYPE_REFUSALS)
        | set(MESH_OPERATION_REFUSALS)
        | set(SCAN_REFUSALS)
        | set(MESH_INGEST_REFUSAL_REASONS)
        # §10's lint bullet: warning-class, syntactic, and a code all the same.
        | {"mesh_derived_offset"}
    )
    return tuple(sorted(codes))


def test_the_detector_sees_every_third_of_the_section_10_vocabulary() -> None:
    """The detector's own coverage, asserted before it is trusted.

    §10 names four groups — admission, type and topology, conversion and
    operations, comparison — plus a lint code. All five are in the table the walk
    below iterates, and this line is what fails if a group is dropped from it.
    """
    from hephaestus.geom.mesh import MESH_OPERATION_REFUSALS, MESH_TYPE_REFUSALS

    vocabulary = set(_mesh_ingest_vocabulary())
    assert set(MESH_REFUSALS) <= vocabulary
    assert set(MESH_TYPE_REFUSALS) <= vocabulary
    assert set(MESH_OPERATION_REFUSALS) <= vocabulary
    assert {"scan_unmeasurable", "scan_iou_unavailable", "scan_timeout"} <= vocabulary
    assert "mesh_derived_offset" in vocabulary
    # Not a token count for its own sake: the four groups are disjoint by §10's
    # construction, so the union's size is the sum and a code that slipped into
    # two vocabularies would show up here as a shortfall.
    assert len(vocabulary) >= 11 + 2 + 5 + 7 + 1


def test_no_raise_site_writes_a_section_10_code_into_its_own_prose() -> None:
    """The derivation rule, enforced over the repository rather than per site.

    ``MeshReadError``, ``ImportResolutionError``, ``MeshOperationError``,
    ``MeshTypeError``, ``ScanCompareError``, ``ScanRefusal``, ``MeshSewTimeout``
    and (for its one §10 reason) ``CompareRefusal`` derive the ``[code]`` suffix
    from ``reason=``, so a message and its code cannot disagree. That only holds
    while no raise site *also* writes one by hand — and after the second repair
    pass twenty-six still did, because the derivation had been added to two
    classes and the detector iterated one vocabulary.

    Asserting the *class* rather than one site is the difference between fixing a
    bug and closing a drift. A code may appear in product prose only in the
    derived suffix form, in a ``reason=``/``Literal`` declaration, or in a
    comment or docstring explaining the vocabulary — never as the ``code: ``
    prefix that reads like a derivation and is not one.
    """
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    vocabulary = _mesh_ingest_vocabulary()
    offenders: list[str] = []
    for root in _PRODUCT_ROOTS:
        for source in sorted((repo / root).rglob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                text = node.value.lstrip()
                for code in vocabulary:
                    if text.startswith(f"{code}:"):
                        offenders.append(
                            f"{source.relative_to(repo)}:{node.lineno} writes {code!r} "
                            "into its own prose"
                        )
    assert offenders == [], (
        "a §10 code is hand-written into a message instead of being derived from "
        "reason= (MESH_INGEST.md §10, G12A.2):\n  " + "\n  ".join(offenders)
    )


def test_every_refusal_class_derives_its_code_from_its_reason() -> None:
    """The other half of the rule: the classes actually derive it.

    The detector above proves no site writes a code by hand; this proves the
    codes are in the messages at all. Without it, "no raise site writes the code"
    would be satisfiable by a repository whose refusal messages never name their
    codes anywhere — which is the drift in its other direction, and which is what
    ``MeshOperationError`` and ``ScanCompareError`` were doing (they carried
    ``reason`` and derived nothing, so every one of their sites hand-wrote it).
    """
    from hephaestus.core.executor.imports import ImportResolutionError
    from hephaestus.core.mesh_solid import MeshSewTimeout
    from hephaestus.core.project_compare import CompareRefusal
    from hephaestus.core.scan_compare import ScanRefusal
    from hephaestus.geom.compare import ScanCompareError
    from hephaestus.geom.mesh import MeshOperationError, MeshTypeError

    built: list[tuple[str, str, str]] = [
        ("MeshReadError", "mesh_empty", MeshReadError("x", reason="mesh_empty").message),
        (
            "ImportResolutionError",
            "mesh_units_undeclared",
            ImportResolutionError("x", reason="mesh_units_undeclared", path="p").message,
        ),
        (
            "MeshOperationError",
            "mesh_solid_invalid",
            MeshOperationError("x", reason="mesh_solid_invalid").message,
        ),
        (
            "MeshTypeError",
            "point_cloud_not_a_shape",
            MeshTypeError("x", reason="point_cloud_not_a_shape").message,
        ),
        (
            "ScanCompareError",
            "scan_unmeasurable",
            ScanCompareError("x", reason="scan_unmeasurable").message,
        ),
        (
            "ScanRefusal",
            "scan_target_unsupported",
            ScanRefusal("x", reason="scan_target_unsupported").message,
        ),
        (
            "CompareRefusal",
            "scan_target_unsupported",
            CompareRefusal("x", reason="scan_target_unsupported").message,
        ),
        (
            "MeshSewTimeout",
            "mesh_sew_timeout",
            MeshSewTimeout("x", timeout_s=1.0, partial={}, lost=()).message,
        ),
    ]
    for name, code, message in built:
        assert message.endswith(f"[{code}]"), f"{name} does not derive its code: {message!r}"

    # Idempotent where a refusal crosses a process boundary and is re-raised: it
    # keeps its identity and states it once.
    crossed = ScanRefusal(
        ScanCompareError("x", reason="scan_unmeasurable").message, reason="scan_unmeasurable"
    ).message
    assert crossed.count("[scan_unmeasurable]") == 1

    # And the earlier stages' own vocabularies are left alone: Stage 8A's five
    # import reasons and Stage 8B's six compare reasons keep their pinned text,
    # which is why the derivation is scoped rather than applied to every class.
    assert ImportResolutionError("x", reason="not_found", path="p").message == "x"
    assert CompareRefusal("x", reason="invalid_target").message == "x"


def test_glb_and_3mf_refuse_at_admission_naming_the_amendment(
    project: Project, meshes: MeshFixtures
) -> None:
    """The two format refusals are refusals of SUBSTANCE, and say which.

    glTF is a scene, so flattening one is a normalization with semantic content;
    3MF costs an ``lxml`` dependency under mission rule 7. Neither message is
    "unsupported" alone — each names the amendment it would take, because a
    refusal a reader cannot act on is a dead end rather than a boundary.
    """
    for name, needle in (("scene.glb", "scene"), ("box.3mf", "lxml")):
        install_import(project.root, name, meshes.cube_ply_binary)
        error = build_error(
            project,
            name.replace(".", "_"),
            f'scan = import_mesh("{name}", units="mm")\npart.geometry = Box(1, 1, 1)\n',
        )
        assert error["line"] == 1
        assert name in error["message"]
        assert needle in error["message"]
        assert "amendment" in error["message"] or "rule 7" in error["message"]
        # The code itself, in the record the model reads — not a paraphrase.
        assert "[mesh_format_unsupported]" in error["message"]
        # …and the layer that decided it says the same thing.
        with pytest.raises(MeshReadError) as raised:
            sniff_format(name, meshes.cube_ply_binary)
        assert raised.value.reason == "mesh_format_unsupported"


def test_extension_magic_mismatch_is_never_a_silently_honoured_sniff(
    project: Project, meshes: MeshFixtures
) -> None:
    """A ``.stl`` whose bytes are a PLY header is refused, not read as PLY."""
    install_import(project.root, "liar.stl", meshes.cube_ply_binary)
    error = build_error(
        project,
        "mismatched",
        'scan = import_mesh("liar.stl", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    assert error["line"] == 1
    assert "stl" in error["message"] and "ply" in error["message"]
    assert "[mesh_format_mismatch]" in error["message"]
    with pytest.raises(MeshReadError) as raised:
        sniff_format("liar.stl", meshes.cube_ply_binary)
    assert raised.value.reason == "mesh_format_mismatch"


@pytest.mark.parametrize(
    ("name", "attribute", "needle", "code"),
    [
        ("empty.stl", None, "empty", "mesh_empty"),
        ("garbage.off", None, "readable", "mesh_unreadable"),
        ("both.obj", "multi_object_obj", "objects", "mesh_multi_object"),
        ("both.ply", "multi_element_ply", "element", "mesh_multi_object"),
        ("nan.ply", "nan_ply", "finite", "mesh_not_finite"),
        ("flat.ply", "all_degenerate_ply", "degenerate", "mesh_degenerate_only"),
    ],
)
def test_each_payload_refusal_lands_at_its_own_statement(
    project: Project, meshes: MeshFixtures, name: str, attribute: str | None, needle: str, code: str
) -> None:
    """Empty, unreadable, multi-object, NaN and all-degenerate, each by name.

    "By name" is asserted as the code, at both layers: ``canonicalize_mesh``
    raises ``MeshReadError`` carrying it, and the §8 build error the model is
    handed carries the same string. Asserting only the prose would leave the
    ``reason=`` free to say something else.

    Note what is NOT here: a mesh with holes, non-manifold edges or inverted
    normals. Those are **admitted** with everything recorded (§3) — refusal is
    reserved for what makes the file unreadable, because every real limb scan is
    imperfect and a harness that refuses them all has not opened the door.
    """
    if attribute is None:
        data = b"" if name.startswith("empty") else b"OFF\nnot actually an off file\n"
    else:
        data = getattr(meshes, attribute)
    install_import(project.root, name, data)

    # The geom layer, where the refusal is decided.
    with pytest.raises(MeshReadError) as raised:
        canonicalize_mesh(name, data, "mm")
    assert raised.value.reason == code

    error = build_error(
        project,
        name.replace(".", "_"),
        f'shim = Box(1, 1, 1)\nscan = import_mesh("{name}", units="mm")\npart.geometry = shim\n',
    )

    assert error["line"] == 2, error
    assert name in error["message"]
    assert needle in error["message"].lower()
    assert f"[{code}]" in error["message"], error["message"]


def test_missing_and_unsupported_units_are_two_different_refusals(
    project: Project, meshes: MeshFixtures
) -> None:
    """Omitting the unit and naming a bad one are different mistakes.

    Telling them apart matters: the first is an author who did not know the
    declaration was required, the second is one who thought ``"inches"`` was a
    unit token. One message for both would leave the second author reading
    advice for a problem they do not have — so the two codes are asserted, not
    the shared word "units".
    """
    install_import(project.root, "limb.ply", meshes.cube_ply_binary)

    undeclared = build_error(
        project,
        "no_units",
        'scan = import_mesh("limb.ply")\npart.geometry = Box(1, 1, 1)\n',
    )
    assert undeclared["line"] == 1
    assert "units" in undeclared["message"]
    assert "[mesh_units_undeclared]" in undeclared["message"]

    unsupported = build_error(
        project,
        "bad_units",
        'scan = import_mesh("limb.ply", units="furlong")\npart.geometry = Box(1, 1, 1)\n',
    )
    assert unsupported["line"] == 1
    assert "furlong" in unsupported["message"]
    assert ", ".join(MESH_UNITS) in unsupported["message"]
    assert "[mesh_units_unsupported]" in unsupported["message"]

    # Both codes again at the layer that decides them, so a raise site that kept
    # its prose and changed its ``reason=`` fails here even if the message
    # assertions above were somehow satisfied.
    for units, code in ((None, "mesh_units_undeclared"), ("furlong", "mesh_units_unsupported")):
        with pytest.raises(MeshReadError) as raised:
            unit_factor(units)
        assert raised.value.reason == code


def test_the_byte_and_count_ceilings_carry_their_code_into_the_build_error(
    project: Project,
) -> None:
    """The tenth reachable code, at the statement that named the file.

    The byte ceiling's own three consequences (no blob, no snapshot, nothing
    read) are clause 20's subject and live in the ceilings module; what is
    asserted here is the half clause 2 owns — that the refusal the model is
    handed carries ``mesh_import_too_large`` itself. The count ceiling is used
    because it needs no multi-gigabyte fixture: a binary STL header claiming
    10⁸ triangles is 84 bytes.
    """
    import struct

    claim = bytes(80) + struct.pack("<I", 100_000_000)
    install_import(project.root, "liar_count.stl", claim)
    error = build_error(
        project,
        "over_count",
        'scan = import_mesh("liar_count.stl", units="mm")\npart.geometry = Box(1, 1, 1)\n',
    )
    assert error["line"] == 1
    assert "[mesh_import_too_large]" in error["message"], error["message"]
    assert "HEPHAESTUS_MESH_MAX_TRIANGLES" in error["message"]


def test_the_declared_refusal_vocabulary_is_the_closed_eleven() -> None:
    """The §1.7 set is CLOSED, and the executor's ``Literal`` agrees with it.

    Two definitions of one vocabulary is how they come to disagree (mission
    rule 6), so the executor's ``ImportResolutionReason`` is asserted to contain
    every geom-side code rather than being transcribed a second time.
    """
    import typing

    from hephaestus.core.executor.imports import ImportResolutionReason

    reasons = set(typing.get_args(ImportResolutionReason))
    assert len(MESH_REFUSALS) == 11
    assert set(MESH_REFUSALS) <= reasons
    # The Stage 8A five are still there: this stage EXTENDS the vocabulary and
    # retires nothing.
    assert {"invalid_import_path", "import_not_found", "path_confinement"} <= reasons


def test_mesh_units_conflict_is_declared_and_asserted_unreachable(
    meshes: MeshFixtures,
) -> None:
    """The eleventh code cannot fire in 12A, and this asserts WHY, as a fact.

    A clause that claimed "every refusal fires" while testing ten would have
    been the defect. So: enumerate the admitted extensions, assert that none of
    them carries an in-file unit, and assert that the two unit-carrying formats
    refuse at admission. A later amendment that admits a unit-carrying format
    without making this code fire fails right here.
    """
    assert "mesh_units_conflict" in MESH_REFUSALS
    assert set(MESH_EXTENSIONS) == {".stl", ".ply", ".obj", ".off", ".xyz"}

    # No admitted extension carries a unit: the same bytes canonicalize to
    # exactly the declared scale in all four units, which is only possible if
    # the file itself said nothing about scale.
    for units, factor in (("mm", 1.0), ("cm", 10.0), ("m", 1000.0), ("in", 25.4)):
        canonical = canonicalize_mesh("cube.ply", meshes.cube_ply_binary, units)
        assert canonical.bbox_mm[0] == pytest.approx(10.0 * factor, rel=1e-12)

    # And the two formats that DO carry one refuse before any unit is read.
    for name in ("scene.glb", "box.3mf"):
        with pytest.raises(MeshReadError) as excinfo:
            sniff_format(name, meshes.cube_ply_binary)
        assert excinfo.value.reason == "mesh_format_unsupported"
