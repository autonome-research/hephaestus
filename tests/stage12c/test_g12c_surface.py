# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12C: the engine surface — one tool, one facade call, one CLI verb (§7).

Gate clauses covered here:

* **41** ``compare_to_scan`` through dispatch on **both** profiles, with the
  scan's ``canonical_hash`` and the part's ``artifact_ref`` attributed in the
  response, and the confinement refusals intact on the tool path;
* **42** tool-surface drift, asserted both relatively (the pin increments by
  exactly one from the value standing when this stage opened) and absolutely
  (that recorded pre-stage value is 53, so the post-stage pin is 54), with all
  five generated artifacts regenerating deterministically;
* **43** ``m.scan_diff`` in a part-scope ``CHECKS`` predicate passing and
  failing either side of its named threshold, the cross-part facade refusing a
  ``scan:`` target by name, and the scan appearing in the build's frozen inputs;
* **49** ``heph scan check``, human and ``--json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from _g12c import Fixtures, build_ok, install_import, rewrite_script, scan_check
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.contract import toolgen, tools_decl
from hephaestus.testing.tools_fixture import Project

REPO = Path(__file__).resolve().parents[2]

#: The 44 x 34 x 24 shroud the 40 x 30 x 20 scan sits inside: every scanned
#: corner is exactly 2 mm from it, which is what makes every threshold below
#: hand-checkable rather than a number copied out of a run.
SHROUD_SRC = "part.geometry = Box(44.0, 34.0, 24.0)\n"

#: The value the tool-count pin stood at when Stage 12 opened. Recorded here as
#: a NAMED CONSTANT at gate-authoring time rather than re-derived from git
#: history at test time, which would make the gate depend on the checkout's
#: depth and shape (G12C.42's own words).
PRE_STAGE_TOOL_PIN: int = 53


@pytest.fixture
def scanned(project: Project, meshes: Fixtures) -> Project:
    """A project with the box scan under ``imports/`` and a built shroud."""
    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "shroud", SHROUD_SRC)
    return project


# ==========================================================================
# clause 41 — the tool, on both profiles


PART_SHROUD = Principal(session_id="ps", profile="part", part="shroud")


@pytest.mark.parametrize(
    "principal",
    [None, PART_SHROUD],
    ids=["orchestrator", "part"],
)
def test_compare_to_scan_answers_on_both_profiles(
    scanned: Project, principal: Principal | None
) -> None:
    """Both declared profiles, and the numbers are the hand-computed 2.0 mm."""
    arguments: dict[str, Any] = {"part": "shroud", "scan": "limb.stl", "units": "mm"}
    result = cast(
        "dict[str, Any]",
        scanned.call("compare_to_scan", arguments)
        if principal is None
        else scanned.call("compare_to_scan", arguments, principal=principal),
    )
    assert result["status"] == "ok"
    distance = cast("dict[str, Any]", result["distance"])
    assert distance["scan_to_part_min_mm"] == pytest.approx(2.0, abs=1e-9)
    assert distance["part_to_scan_method"] == "kdtree_bound_exact_triangle"


def test_the_declared_profiles_are_part_and_orchestrator() -> None:
    """The same two ``compare_solids`` carries (§7.2), asserted as a set."""
    assert set(tools_decl.get_tool("compare_to_scan").profiles) == {"part", "orchestrator"}


def test_the_response_attributes_both_operands(scanned: Project) -> None:
    """A comparison names its evidence: the artifact ref AND both scan hashes.

    Two hashes, because they answer different questions (§1.4): ``sha256`` is
    the file's identity — what a build freezes — and ``canonical_hash`` is the
    geometry's, so two runs can say "the file changed, the geometry did not".
    """
    import hashlib

    result = scan_check(scanned, "shroud", "limb.stl")
    scan = cast("dict[str, Any]", result["scan"])
    part = cast("dict[str, Any]", result["part"])
    raw = (scanned.root / "imports" / "limb.stl").read_bytes()

    assert scan["sha256"] == f"sha256:{hashlib.sha256(raw).hexdigest()}"
    assert scan["canonical_hash"].startswith("sha256:")
    assert scan["canonical_hash"] != scan["sha256"]
    assert scan["units"] == "mm"
    assert part["artifact_ref"], "the part side names the artifact it was read from"
    assert part["artifact_ref"] in cast("list[str]", result["resolved_artifact_refs"])
    assert cast("dict[str, Any]", result["distance"])["part_artifact_ref"] == part["artifact_ref"]


def test_the_quality_record_rides_the_response(scanned: Project) -> None:
    """§7.2: the ``ScanDistance`` **plus the MeshQuality of the target**."""
    result = scan_check(scanned, "shroud", "limb.stl")
    quality = cast("dict[str, Any]", result["quality"])
    assert quality["weld_tol_mm"] == pytest.approx(1e-6)
    assert quality["boundary_edge_count"] == 0
    assert quality["connected_component_count"] == 1


def test_the_scan_prefixed_spelling_is_accepted_too(scanned: Project) -> None:
    """A model reading a failing ``m.scan_diff`` can paste its target straight in."""
    bare = scan_check(scanned, "shroud", "limb.stl")
    prefixed = scan_check(scanned, "shroud", "scan:limb.stl")
    assert cast("dict[str, Any]", bare["scan"])["path"] == "limb.stl"
    assert cast("dict[str, Any]", prefixed["scan"])["path"] == "limb.stl"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../outside.stl", "path_confinement"),
        ("/etc/passwd", "invalid_import_path"),
        ("nope.stl", "unknown_import"),
    ],
)
def test_the_confinement_refusals_are_intact_on_the_tool_path(
    scanned: Project, path: str, reason: str
) -> None:
    """The Stage 8A walk, unchanged, and its vocabulary is not flattened."""
    with pytest.raises(DispatchError) as caught:
        scanned.call("compare_to_scan", {"part": "shroud", "scan": path, "units": "mm"})
    assert caught.value.reason == reason


def test_a_units_declaration_is_required_by_the_schema() -> None:
    """§1.3 at the tool boundary: a default here would guess a scale."""
    decl = tools_decl.get_tool("compare_to_scan")
    params = cast("dict[str, Any]", decl.params)
    assert "units" in cast("list[str]", params["required"])
    units = cast("dict[str, Any]", cast("dict[str, Any]", params["properties"])["units"])
    assert units["enum"] == ["mm", "cm", "m", "in"]
    assert "default" not in units


def test_a_declared_unit_changes_the_measurement(scanned: Project) -> None:
    """The unit is not decoration: the same bytes at ``cm`` are ten times larger."""
    mm = scan_check(scanned, "shroud", "limb.stl", units="mm")
    cm = scan_check(scanned, "shroud", "limb.stl", units="cm")
    assert (
        cast("dict[str, Any]", mm["scan"])["canonical_hash"]
        != cast("dict[str, Any]", cm["scan"])["canonical_hash"]
    )
    assert (
        cast("dict[str, Any]", mm["scan"])["sha256"] == cast("dict[str, Any]", cm["scan"])["sha256"]
    ), "same file, different declared unit: one input, two geometries (§1.4)"


def test_principal_is_refused_through_the_tool(scanned: Project) -> None:
    """The enum refuses it at the schema, and the engine refuses it by name."""
    decl = tools_decl.get_tool("compare_to_scan")
    align = cast(
        "dict[str, Any]",
        cast("dict[str, Any]", cast("dict[str, Any]", decl.params)["properties"])["align"],
    )
    assert align["enum"] == ["as_posed", "declared"]

    from hephaestus.core.scan_compare import ProjectScanComparer
    from hephaestus.geom.compare import ScanCompareError

    comparer = ProjectScanComparer(scanned.layout, scanned.store)
    with pytest.raises(ScanCompareError) as caught:
        comparer.compare("shroud", "scan:limb.stl", units="mm", align="principal")
    assert caught.value.reason == "scan_principal_unavailable"


# ==========================================================================
# clause 42 — tool-surface drift, relatively AND absolutely


def test_the_tool_pin_increments_by_exactly_one_from_the_recorded_pre_stage_value() -> None:
    """Both halves of G12C.42, so a silently moved pin cannot hide in the rule.

    (a) the relative half — the pin is the pre-stage value plus one, and this
    stage adds exactly one tool; (b) the absolute half — that recorded
    pre-stage value **is 53**, the value Stage 11 left (``PARTS_STORE.md`` adds
    no tool). A future reorder that changes the pre-stage value updates the
    constant *and* cites the amendment that moved it; changing it without a
    citation fails review, and changing the increment fails here.
    """
    assert PRE_STAGE_TOOL_PIN == 53
    assert len(tools_decl.tool_names()) == PRE_STAGE_TOOL_PIN + 1
    assert len(set(tools_decl.tool_names())) == PRE_STAGE_TOOL_PIN + 1
    assert "compare_to_scan" in tools_decl.tool_names()


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("contract/tests/test_toolgen.py", "assert len(tools_decl.tool_names()) == 54"),
        ("tests/stage2/test_g2_contract_drift.py", "assert len(TOOL_NAMES) == 54"),
    ],
)
def test_both_pins_moved_together_and_cite_this_stage(path: str, needle: str) -> None:
    """The two places §7.1 names, and neither may move without the citation."""
    source = (REPO / path).read_text(encoding="utf-8")
    assert needle in source, f"{path}: pin not repointed"
    window = source[max(0, source.index(needle) - 1600) : source.index(needle) + 400]
    assert "MESH_INGEST.md" in window, f"{path}: the repointed pin does not cite the amendment"


def test_the_generated_artifact_set_is_the_declared_tool_set() -> None:
    """A tool declared and never generated would otherwise pass every equality."""
    generated = toolgen.generate_json_schemas()
    assert {Path(rel).name.removesuffix(".schema.json") for rel in generated} == set(
        tools_decl.tool_names()
    )
    assert len(generated) == PRE_STAGE_TOOL_PIN + 1


def test_all_five_generated_artifacts_regenerate_deterministically() -> None:
    """Declaration, JSON schemas, TypeBox, MCP — and the committed bytes match."""
    assert toolgen.generate_json_schemas() == toolgen.generate_json_schemas()
    assert toolgen.generate_typebox_module() == toolgen.generate_typebox_module()
    assert toolgen.generate_mcp_document() == toolgen.generate_mcp_document()
    for rel, text in toolgen.generate_json_schemas().items():
        assert (REPO / rel).read_text(encoding="utf-8") == text, f"{rel} is stale"
    assert (REPO / "agent" / "src" / "tools" / "schema.gen.ts").read_text(
        encoding="utf-8"
    ) == toolgen.generate_typebox_module()
    assert (REPO / "schemas" / "mcp" / "tools.json").read_text(
        encoding="utf-8"
    ) == toolgen.generate_mcp_document()


def test_the_tool_has_a_heading_and_a_signature_in_the_document() -> None:
    """The fifth artifact: ``tool_schema.md``, which the drift gate reads both ways."""
    doc = (REPO / "tool_schema.md").read_text(encoding="utf-8")
    assert "### compare_to_scan" in doc
    assert "compare_to_scan(part: str, scan: str" in doc
    assert "MESH_INGEST.md" in doc


# ==========================================================================
# clause 43 — m.scan_diff in a part-scope CHECKS predicate


def _script_with_check(threshold: float) -> str:
    """A part script that imports the scan and asserts a clearance on it."""
    return (
        'scan = import_mesh("limb.stl", units="mm")\n'
        "part.geometry = Box(44.0, 34.0, 24.0)\n"
        "CHECKS = {\n"
        '    "clears_the_scan": lambda m: m.scan_diff("part", "scan:limb.stl")'
        f".scan_to_part_min_mm >= {threshold},\n"
        "}\n"
    )


def _check_result(project: Project, part: str, name: str) -> dict[str, Any]:
    """One part CHECK's outcome, through the model's own ``run_checks`` tool."""
    report = cast("dict[str, Any]", project.call("run_checks", {"name": part}))
    assert report["status"] == "ok", report
    return cast("dict[str, Any]", cast("dict[str, Any]", report["checks"])[name])


def _frozen_imports(project: Project, part: str) -> dict[str, str]:
    """``input_hashes.imports`` of the part's current build (§8 build record)."""
    current = project.cad.current_build(part)
    assert current is not None
    return dict(current.input_hashes.imports)


def test_a_scan_predicate_passes_and_fails_either_side_of_its_threshold(
    project: Project, meshes: Fixtures
) -> None:
    """The clearance is 2.0 mm by construction, so 1.5 passes and 2.5 does not."""
    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "shroud", _script_with_check(1.5))
    assert _check_result(project, "shroud", "clears_the_scan")["pass"] is True

    rewrite_script(project, "shroud", _script_with_check(2.5))
    failing = cast("dict[str, Any]", project.call("build_part", {"name": "shroud"}))
    assert failing["status"] == "ok", "a failing check fails the report, never the build"
    assert _check_result(project, "shroud", "clears_the_scan")["pass"] is False


def test_the_predicates_measured_value_is_the_whole_record(
    project: Project, meshes: Fixtures
) -> None:
    """The evidence behind a check is every number, not the one that was read."""
    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "shroud", _script_with_check(1.5))
    outcome = _check_result(project, "shroud", "clears_the_scan")
    measured = cast("dict[str, Any]", outcome["measured"])
    assert measured["part_to_scan_method"] == "kdtree_bound_exact_triangle"
    assert measured["scan_to_part_min_mm"] == pytest.approx(2.0, abs=1e-9)
    assert "iou" not in measured
    assert "chamfer_mm" not in measured
    # §7.4's other half, on the predicate's own path: the quality record travels
    # WITH the distance, so a check reading a clearance can also see the defects
    # the canonicalizer measured in the scan it cleared.
    quality = cast("dict[str, Any]", measured["quality"])
    assert quality["connected_component_count"] == 1
    assert quality["self_intersection_method"]


def test_the_scan_target_is_a_frozen_build_input(project: Project, meshes: Fixtures) -> None:
    """``input_hashes.imports`` carries it, and changed bytes are a changed build."""
    import hashlib

    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "shroud", _script_with_check(1.5))
    hashes = _frozen_imports(project, "shroud")
    raw = (project.root / "imports" / "limb.stl").read_bytes()
    assert hashes["limb.stl"] == f"sha256:{hashlib.sha256(raw).hexdigest()}"


def test_a_changed_scan_file_changes_the_build(project: Project, meshes: Fixtures) -> None:
    """The freeze argument in one assertion: the check's verdict rides the bytes."""
    from _g12c import export_mesh

    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "shroud", _script_with_check(1.5))
    first_hashes = _frozen_imports(project, "shroud")

    # A scan 5% larger in every axis: its corners move from 2.0 mm inside the
    # shroud's wall to 1.0 mm (22 - 21 in x), so the SAME predicate over the
    # SAME script must now fail. The scale is small on purpose — grow the scan
    # far enough and its corners poke OUT of the shroud, where the unsigned
    # distance rises again and the check would pass for the wrong reason.
    bigger = export_mesh(meshes.box_vertices * 1.05, meshes.box_faces)
    install_import(project.root, "limb.stl", bigger)
    rebuilt = cast("dict[str, Any]", project.call("build_part", {"name": "shroud"}))
    assert rebuilt["status"] == "ok", rebuilt

    assert first_hashes["limb.stl"] != _frozen_imports(project, "shroud")["limb.stl"]
    assert _check_result(project, "shroud", "clears_the_scan")["pass"] is False


def test_a_scan_target_the_script_never_imported_is_refused_by_name(
    project: Project, meshes: Fixtures
) -> None:
    """§1.3 has no exception here: a ``scan:`` string carries no unit.

    The file is still frozen — it is a build input — but the unit comes from the
    script's own ``import_mesh``, and without one the check refuses
    ``mesh_units_undeclared`` rather than measuring against a scale nobody
    declared.
    """
    install_import(project.root, "limb.stl", meshes.box_stl)
    script = (
        "part.geometry = Box(44.0, 34.0, 24.0)\n"
        "CHECKS = {\n"
        '    "clears_the_scan": lambda m: m.scan_diff("part", "scan:limb.stl")'
        ".scan_to_part_min_mm >= 1.5,\n"
        "}\n"
    )
    build_ok(project, "shroud", script)
    outcome = _check_result(project, "shroud", "clears_the_scan")
    assert outcome["pass"] is False
    # The DERIVED form, repointed with the amendment that produced it: the raise
    # site behind this message used to hand-write ``mesh_units_undeclared:`` into
    # a bare ``ValidationError`` with no ``reason=`` behind it, so this
    # substring could have kept passing while the vocabulary moved. It now goes
    # through ``ImportResolutionError``, which appends ``[code]`` from
    # ``reason`` (``imports.py``, the G12A.2 derivation rule), and the assertion
    # binds that form — the one a search for the code actually finds.
    assert "[mesh_units_undeclared]" in json.dumps(outcome["measured"])
    # …and the file was frozen anyway, which is what makes the refusal a
    # statement about the unit rather than about the file being missing.
    assert "limb.stl" in _frozen_imports(project, "shroud")


def test_a_scan_target_declared_at_two_units_is_refused_by_name(
    project: Project, meshes: Fixtures
) -> None:
    """§1.5.1's ambiguity, NAMED — the other end of the same rule.

    One path declared at two units is two staged geometries that differ by the
    whole factor the declaration exists to fix, so a check naming the path
    without saying which one it means is refused. Until the third repair pass
    this branch raised a bare ``ValidationError`` with no code at all — the one
    unnamed refusal left in the stage, which its own house rule (refusals NAMED,
    vocabularies CLOSED) forbids. It is now
    ``scan_target_ambiguous_units``: its own term rather than a reuse of
    ``mesh_units_conflict``, which §1.3 spends on a different fact.
    """
    install_import(project.root, "limb.stl", meshes.box_stl)
    script = (
        'mm = import_mesh("limb.stl", units="mm")\n'
        'inch = import_mesh("limb.stl", units="in")\n'
        "part.geometry = Box(44.0, 34.0, 24.0)\n"
        "CHECKS = {\n"
        '    "clears_the_scan": lambda m: m.scan_diff("part", "scan:limb.stl")'
        ".scan_to_part_min_mm >= 1.5,\n"
        "}\n"
    )
    build_ok(project, "shroud", script)
    outcome = _check_result(project, "shroud", "clears_the_scan")
    assert outcome["pass"] is False
    measured = json.dumps(outcome["measured"])
    assert "[scan_target_ambiguous_units]" in measured
    assert "mm" in measured and "in" in measured


def test_the_cross_part_facade_refuses_a_scan_target_by_name() -> None:
    """Project scope has no scan resolver — that absence IS the enforcement."""
    import inspect

    from hephaestus.core.addressing import GeometryIndex
    from hephaestus.core.checks.facade import GeometrySource, project_measurement
    from hephaestus.core.errors import ValidationError

    source = cast(
        "GeometrySource",
        type(
            "Src",
            (),
            {
                "index": GeometryIndex(labels=("part",), bindings={}, tags=frozenset()),
                "shape": lambda self, resolution: object(),
            },
        )(),
    )
    facade = project_measurement({"widget": source}, current_part="widget")
    with pytest.raises(ValidationError) as caught:
        facade.scan_diff("widget/part", "scan:limb.stl")
    assert "part-scope" in caught.value.message

    # Structural, not incidental: the cross-part constructor has no parameter to
    # pass one through, the same way it has no `at_pose` on the part side.
    assert "scan" not in inspect.signature(project_measurement).parameters


# ==========================================================================
# clause 49 — heph scan check


def _heph(project: Project, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *args],
        cwd=str(project.root),
        capture_output=True,
        text=True,
        check=False,
    )


def test_heph_scan_check_prints_the_distance_for_a_human(scanned: Project) -> None:
    completed = _heph(scanned, "scan", "check", "shroud", "limb.stl", "--units", "mm")
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "scan check shroud against limb.stl" in out
    assert "scan -> part" in out
    assert "part -> scan" in out
    assert "kdtree_bound_exact_triangle" in out
    # §11.3 rides the human output, because the human is who might read a
    # distance as a fit.
    assert "NOT a fit" in out or "not a fit" in out.lower()


def test_heph_scan_check_json_is_the_record_the_tool_returns(scanned: Project) -> None:
    completed = _heph(scanned, "scan", "check", "shroud", "limb.stl", "--units", "mm", "--json")
    assert completed.returncode == 0, completed.stderr
    payload = cast("dict[str, Any]", json.loads(completed.stdout))
    assert payload["status"] == "ok"
    distance = cast("dict[str, Any]", payload["distance"])
    assert distance["scan_to_part_min_mm"] == pytest.approx(2.0, abs=1e-9)
    assert distance["part_to_scan_method"] == "kdtree_bound_exact_triangle"
    assert "iou" not in distance and "chamfer_mm" not in distance


def test_heph_scan_still_prints_the_facts_form(scanned: Project) -> None:
    """The 12A subcommand is unchanged by the check verb sharing its parser."""
    completed = _heph(scanned, "scan", "limb.stl", "--units", "mm", "--json")
    assert completed.returncode == 0, completed.stderr
    payload = cast("dict[str, Any]", json.loads(completed.stdout))
    assert payload["triangle_count"] == 12
    assert payload["vertex_count"] == 8


def test_heph_scan_check_takes_a_declared_transform_or_refuses(scanned: Project) -> None:
    """The declared mode is reachable from the CLI, and only with its transform.

    ``--align declared`` without ``--transform`` is a usage error rather than a
    silent fall back to ``as_posed``: an alignment the record does not name
    would be exactly the normalization COMPARE.md §1 forbids.
    """
    identity = ",".join(str(v) for v in (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1))
    ok = _heph(
        scanned,
        *("scan", "check", "shroud", "limb.stl", "--units", "mm"),
        *("--align", "declared", "--transform", identity, "--json"),
    )
    assert ok.returncode == 0, ok.stderr
    payload = cast("dict[str, Any]", json.loads(ok.stdout))
    assert payload["align"] == "declared"
    assert cast("dict[str, Any]", payload["distance"])["declared_transform"][0] == 1.0

    missing = _heph(
        scanned, "scan", "check", "shroud", "limb.stl", "--units", "mm", "--align", "declared"
    )
    assert missing.returncode == 2
    assert "--transform" in missing.stderr


def test_heph_scan_check_with_the_wrong_shape_is_a_usage_error(scanned: Project) -> None:
    """Exit 2, and a message naming both forms — never a file called 'check'."""
    completed = _heph(scanned, "scan", "check", "shroud", "--units", "mm")
    assert completed.returncode == 2
    assert "heph scan check <part>" in completed.stderr
