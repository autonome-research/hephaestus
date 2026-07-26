# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G6: DFM findings, artifact resolution, and artifact-bound topology.

Three sentences of the gate live here, asserted through ``run_dfm`` on the real
tool surface over fixtures whose violations are known by construction:

* *"DFM fixtures with known violations yield findings with correct rule ids,
  offending tags, and resolved source artifact"* — both shipped packs, every
  rule id, the design's own tag names, and the artifact ref every finding was
  measured against;
* *"a transient preview is checked explicitly while default DFM still resolves
  the current artifact"* — the two resolved refs are asserted to **differ**, and
  each report's findings name its own ref;
* *"findings report source artifact and artifact-bound topology descriptors
  rather than bare mask IDs"* — the structural claim is enforced by resolving
  every descriptor against the very bytes the report names, so an unresolvable
  index (which is all a bare mask id is) fails the gate.

Rule predicates are registry content, so these cases need a probed secure
sandbox. The unit-level coverage of resolution refusals lives in
``server/tests/test_dfm_tool.py``; this module is the gate evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from _g6 import G6Project, artifact_topology, make_g6_project, requires_bwrap, resolve_descriptor
from hephaestus.core.dfm import TOPOLOGY_KINDS

pytestmark = requires_bwrap

#: What each shipped pack is expected to say about its fixture, by rule id.
LASER_RULES: frozenset[str] = frozenset(
    {
        "laser_cut.min_feature_vs_kerf",
        "laser_cut.min_internal_radius",
        "laser_cut.sheet_thickness_match",
    }
)
FDM_RULES: frozenset[str] = frozenset(
    {"fdm.min_wall_thickness", "fdm.overhang_angle", "fdm.min_hole_diameter"}
)


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Iterator[G6Project]:
    """One secure project holding the two violating fixtures and a clean one."""
    scaffolded = make_g6_project(
        tmp_path_factory.mktemp("g6-dfm") / "proj",
        ("vent_panel", "tray", "block"),
        secure=True,
    )
    try:
        yield scaffolded
    finally:
        scaffolded.close()


@pytest.fixture(scope="module")
def panel_ref(project: G6Project) -> str:
    return project.build("vent_panel")


@pytest.fixture(scope="module")
def tray_ref(project: G6Project) -> str:
    return project.build("tray")


def _report(project: G6Project, name: str, **arguments: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    payload.update(arguments)
    return dict(project.call("run_dfm", payload))


def _findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", report["findings"])


def _by_rule(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(finding["rule_id"]): finding for finding in _findings(report)}


# ==========================================================================
# known violations -> rule ids, tags, resolved artifact


def test_the_laser_fixture_reports_every_laser_rule_against_its_built_artifact(
    project: G6Project, panel_ref: str
) -> None:
    report = _report(project, "vent_panel")

    assert report["status"] == "ok"
    assert report["process"] == "laser_cut"
    # The artifact the findings were measured against is the one just built.
    assert report["resolved_from"] == "current"
    assert report["source_artifact_ref"] == panel_ref
    assert not report["errored_rules"], report["errored_rules"]

    findings = _by_rule(report)
    assert set(findings) == set(LASER_RULES), "each laser rule has exactly one finding"
    assert {f["source_artifact_ref"] for f in findings.values()} == {panel_ref}

    # The 0.5 mm bore violates the kerf rule and is named by the design's tag.
    bore = findings["laser_cut.min_feature_vs_kerf"]
    assert bore["tags"] == ["vent_bore"]
    assert bore["severity"] == "error"
    assert float(cast("float", bore["suggested_bound"])) > 0.5

    # The 5.5 mm panel is not a stocked thickness of its own declared material.
    stock = findings["laser_cut.sheet_thickness_match"]
    assert "Baltic birch" in str(stock["message"])
    assert stock["suggested_bound"] == pytest.approx(6.0)

    # Provenance: which registry said so, at what digest.
    pack = cast("dict[str, Any]", report["pack"])
    assert pack["name"] and pack["version"]
    assert str(pack["registry_digest"]).startswith("sha256:")


def test_the_printed_fixture_reports_every_fdm_rule_with_its_offending_tag(
    project: G6Project, tray_ref: str
) -> None:
    report = _report(project, "tray")

    assert report["process"] == "fdm"
    assert report["source_artifact_ref"] == tray_ref
    findings = _by_rule(report)
    assert set(findings) == set(FDM_RULES)
    assert findings["fdm.min_hole_diameter"]["tags"] == ["drain_bore"]
    counts = cast("dict[str, int]", report["severity_counts"])
    assert sum(counts.values()) == len(_findings(report))
    assert counts["error"] >= 2


def test_a_clean_fixture_yields_no_findings_so_a_finding_means_something(
    project: G6Project,
) -> None:
    project.build("block")
    report = _report(project, "block")
    assert _findings(report) == []
    assert report["severity_counts"] == {}
    assert not report["errored_rules"]
    assert {str(rule["rule_id"]) for rule in cast("list[Any]", report["rules"])} == set(FDM_RULES)
    assert all(rule["status"] == "ok" for rule in cast("list[Any]", report["rules"]))


# ==========================================================================
# preview vs current resolution


def test_an_explicit_preview_is_checked_while_the_default_stays_on_current(
    project: G6Project, tray_ref: str
) -> None:
    """The G6 clause: two different artifacts of one part, both addressable."""
    preview_ref = project.build("tray", {"height": 30.0})
    # A transient-parameter build is published but never becomes current.
    assert preview_ref != tray_ref
    current = project.cad.current_build("tray")
    assert current is not None
    assert cast("Any", current).artifact_ref == tray_ref

    default_report = _report(project, "tray")
    preview_report = _report(project, "tray", artifact_ref=preview_ref)

    assert default_report["source_artifact_ref"] == tray_ref
    assert default_report["resolved_from"] == "current"
    assert preview_report["source_artifact_ref"] == preview_ref
    assert preview_report["resolved_from"] == "artifact_ref"
    # The whole point of the clause: checking a preview did not move the default.
    assert default_report["source_artifact_ref"] != preview_report["source_artifact_ref"]

    # Each report's findings name the bytes they were measured against — and the
    # preview keeps the tags of the build that produced it.
    for report, ref in ((default_report, tray_ref), (preview_report, preview_ref)):
        assert _findings(report), "both artifacts violate the fdm pack"
        assert {f["source_artifact_ref"] for f in _findings(report)} == {ref}
    assert _by_rule(preview_report)["fdm.min_hole_diameter"]["tags"] == ["drain_bore"]


# ==========================================================================
# artifact-bound topology descriptors, not bare mask ids


@pytest.mark.parametrize("part", ["vent_panel", "tray"])
def test_every_finding_addresses_topology_inside_the_artifact_it_names(
    project: G6Project, part: str, panel_ref: str, tray_ref: str
) -> None:
    report = _report(project, part)
    ref = str(report["source_artifact_ref"])
    assert ref == (panel_ref if part == "vent_panel" else tray_ref)
    shape = artifact_topology(project, part, ref)

    seen = 0
    for finding in _findings(report):
        descriptors = cast("list[dict[str, Any]]", finding["topology"])
        assert descriptors, f"{finding['rule_id']} points at no topology at all"
        for descriptor in descriptors:
            # Shape: an addressed entity, never an opaque identifier.
            assert set(descriptor) == {"kind", "solid_id", "topology_index", "tag"}
            assert descriptor["kind"] in TOPOLOGY_KINDS
            assert isinstance(descriptor["solid_id"], int)
            assert isinstance(descriptor["topology_index"], int)
            assert descriptor["solid_id"] >= 0 and descriptor["topology_index"] >= 0
            assert descriptor["tag"] is None or isinstance(descriptor["tag"], str)
            # Binding: it resolves in the very bytes the finding names.
            assert resolve_descriptor(shape, descriptor) is not None
            seen += 1
    assert seen >= 3, "the fixtures violate three rules each"


def test_a_tagged_descriptor_resolves_to_the_face_the_script_tagged(
    project: G6Project, panel_ref: str
) -> None:
    """Tag *and* address agree: the descriptor is the bore, not just labelled one."""
    report = _report(project, "vent_panel")
    bore = _by_rule(report)["laser_cut.min_feature_vs_kerf"]
    descriptor = cast("list[dict[str, Any]]", bore["topology"])[0]
    assert descriptor["tag"] == "vent_bore"
    assert descriptor["kind"] == "face"

    shape = artifact_topology(project, "vent_panel", panel_ref)
    face = resolve_descriptor(shape, descriptor)
    # The tagged vent bore is the 0.5 mm cylinder at x = 12 in the fixture.
    assert str(face.geom_type) == "GeomType.CYLINDER"
    assert pytest.approx(12.0, abs=0.5) == face.center().X


def test_the_same_rule_on_two_artifacts_addresses_each_artifacts_own_topology(
    project: G6Project, tray_ref: str
) -> None:
    """A descriptor is only meaningful next to the ref it travels with."""
    preview_ref = project.build("tray", {"height": 30.0})
    for ref in (tray_ref, preview_ref):
        report = _report(project, "tray", artifact_ref=ref)
        shape = artifact_topology(project, "tray", ref)
        for finding in _findings(report):
            assert finding["source_artifact_ref"] == ref
            for descriptor in cast("list[dict[str, Any]]", finding["topology"]):
                assert resolve_descriptor(shape, descriptor) is not None
