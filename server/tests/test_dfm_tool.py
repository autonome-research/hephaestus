"""``run_dfm`` end to end: resolution, findings, and the DFM-mode auto-run.

Gate G6 asks four things of this tool, and each is asserted here against real
built geometry rather than a stub evaluation:

* fixtures with **known** violations — one part per shipped pack — produce
  findings with the right rule ids, the offending tag names, and the artifact
  ref they were measured against;
* a clean part produces none, so a finding means something;
* a *transient preview* artifact is checkable explicitly while the default
  resolution still names the current artifact — the two refs differ and both
  are reported, which is the deferred G0B "preview DFM targeting" clause;
* with the project's DFM mode on, a successful ``build_part`` carries the
  findings in its ``VALIDATION.md`` §4 critique block unrequested, and with the
  mode off the section is absent entirely.

Rule predicates are registry content and run only under a probed secure
sandbox, so the evaluating cases skip where bubblewrap is unavailable. The
resolution and mode-off cases need no sandbox and always run.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOpError, CadOps, script_metadata
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.registry import RegistryError

from opstore import OpStore

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="DFM predicates execute only under a probed secure sandbox (bubblewrap)",
)

# -- fixture parts ----------------------------------------------------------

#: A 5.5 mm panel in a material stocked at 3/6/12/18 mm, with a 0.5 mm bore and
#: 0.3 mm notch corners: one known violation for each laser_cut rule.
PANEL_SRC = """PARAMS = {
    "thickness": Param(5.5, min=3.0, max=12.0),
}

panel = Box(60.0, 40.0, p.thickness)
panel = panel - Pos(10.0, 0.0, 0.0) * Cylinder(0.25, 20.0)
panel = panel - Pos(-20.0, 12.0, 0.0) * Box(16.0, 16.0, 20.0)
corners = [e for e in panel.edges().filter_by(Axis.Z) if abs(e.center().Y - 4.0) < 1e-6]
panel = fillet(corners, 0.3)
vent = [
    f
    for f in panel.faces()
    if f.geom_type == GeomType.CYLINDER
    and abs(f.center().X - 10.0) < 0.5
    and abs(f.center().Y) < 0.5
][0]
tag(vent, "vent_bore")
part.geometry = panel
part.description = "a laser-cut vent panel"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
"""

#: A 0.8 mm-walled tray with a 1.0 mm bore and a 63 deg conical overhang: one
#: known violation for each fdm rule.
TRAY_SRC = """PARAMS = {
    "height": Param(15.0, min=8.0, max=40.0),
}

bottom = (Align.CENTER, Align.CENTER, Align.MIN)
tray = Box(30.0, 20.0, p.height, align=bottom) - Pos(0.0, 0.0, 0.8) * Box(
    28.4, 18.4, 40.0, align=bottom
)
tray = tray - Cylinder(0.5, 4.0, align=bottom)
drain = [f for f in tray.faces() if f.geom_type == GeomType.CYLINDER][0]
tag(drain, "drain_bore")
flare = Cone(bottom_radius=1.0, top_radius=9.0, height=4.0, align=bottom)
part.geometry = Compound(children=[tray, Pos(40.0, 0.0, 0.0) * flare])
part.description = "a printed tray with a drain and a flare"
part.process = "fdm"
part.material_spec = "PLA filament"
"""

#: A plain block: nothing an fdm pack can complain about.
BLOCK_SRC = """block = Box(30.0, 20.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
part.geometry = block
part.description = "a solid printed block"
part.process = "fdm"
"""

#: The same block with no ``part.process``: a process is never guessed.
UNDECLARED_SRC = """part.geometry = Box(30.0, 20.0, 10.0)
part.description = "a block that never says how it is made"
"""

GLOBALS_SRC = 'PARAMS = {\n    "spare": Param(1.0, min=0.5, max=2.0),\n}\n'

PARTS: dict[str, str] = {
    "panel": PANEL_SRC,
    "tray": TRAY_SRC,
    "block": BLOCK_SRC,
    "undeclared": UNDECLARED_SRC,
}


def _project(root: Path, *, auto_run: bool, backend: object) -> tuple[CadOps, OpStore]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    manifest = '[project]\nname = "dfm"\n'
    if auto_run:
        manifest += "\n[dfm]\nauto_run = true\n"
    (root / "hephaestus.toml").write_text(manifest, encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    for name, source in PARTS.items():
        (root / "parts" / f"{name}.py").write_text(source, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    return CadOps(layout, store, backend=cast("Any", backend)), store


@pytest.fixture
def sandboxed(tmp_path: Path) -> Iterator[CadOps]:
    """A project whose builds and DFM runs both go through bubblewrap."""
    cad, store = _project(tmp_path / "secure", auto_run=False, backend=BwrapBackend())
    try:
        yield cad
    finally:
        store.close()


@pytest.fixture
def unsandboxed(tmp_path: Path) -> Iterator[CadOps]:
    """A project on the unsafe local backend: builds run, DFM refuses."""
    cad, store = _project(tmp_path / "local", auto_run=False, backend=UnsafeLocalBackend())
    try:
        yield cad
    finally:
        store.close()


def _build(cad: CadOps, name: str, params: dict[str, Any] | None = None) -> str:
    result = cad.build_part(name, params)
    assert result["status"] == "ok", result.get("error")
    ref = result["artifact_ref"]
    assert isinstance(ref, str)
    return ref


def _findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = report["findings"]
    assert isinstance(findings, list)
    return cast("list[dict[str, Any]]", findings)


def _by_rule(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(finding["rule_id"]): finding for finding in _findings(report)}


# -- metadata resolution ----------------------------------------------------


def test_part_metadata_is_read_from_the_script_without_running_it() -> None:
    metadata = script_metadata(PANEL_SRC)
    assert metadata["process"] == "laser_cut"
    assert metadata["material_spec"] == "6 mm Baltic birch plywood"
    assert metadata["stock_form"] == "sheet"
    # A computed metadata expression has no literal value and is not invented.
    assert "process" not in script_metadata('part.process = "laser" + "_cut"\n')


def test_a_part_without_a_process_is_refused_rather_than_guessed(unsandboxed: CadOps) -> None:
    _build(unsandboxed, "undeclared")
    with pytest.raises(CadOpError) as refusal:
        unsandboxed.run_dfm("undeclared")
    assert refusal.value.reason == "invalid_params"
    assert "laser_cut" in str(refusal.value.data["candidates"])


def test_an_unknown_process_override_lists_the_packs_that_exist(unsandboxed: CadOps) -> None:
    _build(unsandboxed, "block")
    with pytest.raises(RegistryError) as unknown:
        unsandboxed.run_dfm("block", process="waterjet")
    assert unknown.value.reason == "unknown_dfm_pack"


def test_dfm_without_a_secure_sandbox_is_a_typed_capability_refusal(unsandboxed: CadOps) -> None:
    """The unsafe local backend refuses registry content; it never evaluates it."""
    _build(unsandboxed, "block")
    with pytest.raises(RegistryError) as refusal:
        unsandboxed.run_dfm("block")
    assert refusal.value.reason in {"capability_not_available", "unsafe_refused", "sandbox_denied"}


# -- the findings -----------------------------------------------------------


@requires_bwrap
def test_the_laser_panel_reports_every_laser_rule_against_the_current_artifact(
    sandboxed: CadOps,
) -> None:
    artifact = _build(sandboxed, "panel")
    report = sandboxed.run_dfm("panel")

    assert report["status"] == "ok"
    assert report["process"] == "laser_cut"
    assert report["resolved_from"] == "current"
    assert report["source_artifact_ref"] == artifact
    assert not report["errored_rules"], report["errored_rules"]

    findings = _by_rule(report)
    assert set(findings) == {
        "laser_cut.min_feature_vs_kerf",
        "laser_cut.min_internal_radius",
        "laser_cut.sheet_thickness_match",
    }
    for finding in findings.values():
        assert finding["source_artifact_ref"] == artifact
        assert finding["severity"] == "error"

    bore = findings["laser_cut.min_feature_vs_kerf"]
    assert bore["suggested_bound"] == pytest.approx(0.8)
    # The offending topology is named by tag AND addressed inside the artifact.
    assert bore["tags"] == ["vent_bore"]
    descriptor = cast("list[dict[str, Any]]", bore["topology"])[0]
    assert set(descriptor) == {"kind", "solid_id", "topology_index", "tag"}
    assert descriptor["tag"] == "vent_bore"
    assert descriptor["kind"] == "face"

    stock = findings["laser_cut.sheet_thickness_match"]
    assert stock["suggested_bound"] == pytest.approx(6.0)
    assert "Baltic birch" in str(stock["message"])


@requires_bwrap
def test_the_printed_tray_reports_every_fdm_rule_with_its_offending_tag(
    sandboxed: CadOps,
) -> None:
    artifact = _build(sandboxed, "tray")
    report = sandboxed.run_dfm("tray")

    assert report["process"] == "fdm"
    assert report["source_artifact_ref"] == artifact
    findings = _by_rule(report)
    assert set(findings) == {
        "fdm.min_wall_thickness",
        "fdm.overhang_angle",
        "fdm.min_hole_diameter",
    }
    assert findings["fdm.min_hole_diameter"]["tags"] == ["drain_bore"]
    assert findings["fdm.min_hole_diameter"]["suggested_bound"] == pytest.approx(2.0)
    assert findings["fdm.overhang_angle"]["severity"] == "warning"
    counts = cast("dict[str, int]", report["severity_counts"])
    assert counts["error"] >= 2 and counts["warning"] >= 1
    # Pack provenance travels with the report: which registry said so, at what digest.
    pack = cast("dict[str, Any]", report["pack"])
    assert pack["version"] and str(pack["registry_digest"]).startswith("sha256:")


@requires_bwrap
def test_a_clean_part_yields_no_findings(sandboxed: CadOps) -> None:
    _build(sandboxed, "block")
    report = sandboxed.run_dfm("block")
    assert _findings(report) == []
    assert report["severity_counts"] == {}
    assert not report["errored_rules"]
    assert all(rule["status"] == "ok" for rule in cast("list[Any]", report["rules"]))


@requires_bwrap
def test_the_process_override_checks_a_part_against_another_process(sandboxed: CadOps) -> None:
    """The same block is fine printed and fine cut — but it is *checked* twice."""
    _build(sandboxed, "block")
    report = sandboxed.run_dfm("block", process="laser_cut")
    assert report["process"] == "laser_cut"
    assert {str(rule["rule_id"]) for rule in cast("list[Any]", report["rules"])} == {
        "laser_cut.min_feature_vs_kerf",
        "laser_cut.min_internal_radius",
        "laser_cut.sheet_thickness_match",
    }


# -- preview targeting (the deferred G0B clause) ----------------------------


@requires_bwrap
def test_an_explicit_preview_artifact_is_checked_while_the_default_stays_current(
    sandboxed: CadOps,
) -> None:
    current = _build(sandboxed, "tray")
    # A transient parameter makes the build a preview: published, never current.
    preview = _build(sandboxed, "tray", {"height": 30.0})
    assert preview != current
    assert sandboxed.current_build("tray") is not None
    assert cast("Any", sandboxed.current_build("tray")).artifact_ref == current

    default_report = sandboxed.run_dfm("tray")
    preview_report = sandboxed.run_dfm("tray", artifact_ref=preview)

    assert default_report["source_artifact_ref"] == current
    assert default_report["resolved_from"] == "current"
    assert preview_report["source_artifact_ref"] == preview
    assert preview_report["resolved_from"] == "artifact_ref"
    # Every finding names the bytes it was measured against, not "the part".
    for report, ref in ((default_report, current), (preview_report, preview)):
        assert _findings(report), "both artifacts violate the fdm pack"
        assert {finding["source_artifact_ref"] for finding in _findings(report)} == {ref}
    # A preview keeps its own tags: the source map of the build that made it.
    assert _by_rule(preview_report)["fdm.min_hole_diameter"]["tags"] == ["drain_bore"]


def test_an_artifact_ref_and_a_project_snapshot_ref_are_mutually_exclusive(
    unsandboxed: CadOps,
) -> None:
    artifact = _build(unsandboxed, "block")
    with pytest.raises(CadOpError, match="mutually exclusive"):
        unsandboxed.run_dfm(
            "block", artifact_ref=artifact, project_snapshot_ref="artifact:project-snapshot:x"
        )


def test_an_artifact_ref_that_is_not_geometry_is_refused(unsandboxed: CadOps) -> None:
    """A render or a source map is not something a DFM rule can measure."""
    _build(unsandboxed, "block")
    with pytest.raises(CadOpError, match="does not name build geometry"):
        unsandboxed.run_dfm("block", artifact_ref="artifact:render:sha256:" + "0" * 64)


def test_an_artifact_that_is_not_stored_is_refused(unsandboxed: CadOps) -> None:
    _build(unsandboxed, "block")
    with pytest.raises(CadOpError, match="not durably stored"):
        unsandboxed.run_dfm("block", artifact_ref="artifact:build:sha256:" + "0" * 64)


@requires_bwrap
def test_a_project_snapshot_resolves_the_parts_own_artifact(tmp_path: Path) -> None:
    cad, store = _project(tmp_path / "snapshot", auto_run=False, backend=BwrapBackend())
    try:
        current = _build(cad, "tray")
        for name in ("block", "panel", "undeclared"):
            _build(cad, name)
        snapshot = Publisher(cad.layout, store).projections.assemble_snapshot(sorted(PARTS))
        report = cad.run_dfm("tray", project_snapshot_ref=snapshot.ref)
        assert report["resolved_from"] == "project_snapshot"
        assert report["source_artifact_ref"] == current
    finally:
        store.close()


# -- DFM mode: the auto-run critique rung -----------------------------------


def test_the_critique_has_no_dfm_section_when_the_mode_is_off(unsandboxed: CadOps) -> None:
    result = unsandboxed.build_part("tray")
    assert result["status"] == "ok", result.get("error")
    critique = cast("dict[str, Any]", result["critique"])
    assert "dfm" not in critique
    assert all(
        str(warning.get("kind", "")).startswith("dfm") is False
        for warning in cast("list[dict[str, Any]]", critique["warnings"])
    )


def test_dfm_mode_reports_that_it_could_not_run_rather_than_a_clean_sheet(
    tmp_path: Path,
) -> None:
    """Mode on, no secure sandbox: the block says so instead of staying silent."""
    cad, store = _project(tmp_path / "modeless", auto_run=True, backend=UnsafeLocalBackend())
    try:
        result = cad.build_part("tray")
        assert result["status"] == "ok", result.get("error")
        critique = cast("dict[str, Any]", result["critique"])
        block = cast("dict[str, Any]", critique["dfm"])
        assert block["available"] is False
        assert block["findings"] == []
        kinds = [w.get("kind") for w in cast("list[dict[str, Any]]", critique["warnings"])]
        assert "dfm_unavailable" in kinds
    finally:
        store.close()


@requires_bwrap
def test_dfm_mode_appends_findings_to_the_post_build_critique_unrequested(
    tmp_path: Path,
) -> None:
    cad, store = _project(tmp_path / "mode", auto_run=True, backend=BwrapBackend())
    try:
        result = cad.build_part("tray")
        assert result["status"] == "ok", result.get("error")
        artifact = result["artifact_ref"]
        critique = cast("dict[str, Any]", result["critique"])
        block = cast("dict[str, Any]", critique["dfm"])

        assert block["available"] is True
        assert block["process"] == "fdm"
        # The auto-run measures the artifact this build published, not "current".
        assert block["source_artifact_ref"] == artifact
        rule_ids = {str(f["rule_id"]) for f in cast("list[dict[str, Any]]", block["findings"])}
        assert rule_ids == {
            "fdm.min_wall_thickness",
            "fdm.overhang_angle",
            "fdm.min_hole_diameter",
        }
        # Findings are flattened into the §4 warning list like every other rung.
        warnings = cast("list[dict[str, Any]]", critique["warnings"])
        dfm_warnings = [w for w in warnings if w.get("kind") == "dfm_finding"]
        assert {str(w["rule_id"]) for w in dfm_warnings} == rule_ids
        assert all(w["source_artifact_ref"] == artifact for w in dfm_warnings)

        # A clean part still gets the section — and it is empty, not absent.
        clean = cad.build_part("block")
        clean_block = cast("dict[str, Any]", cast("dict[str, Any]", clean["critique"])["dfm"])
        assert clean_block["available"] is True and clean_block["findings"] == []
    finally:
        store.close()
