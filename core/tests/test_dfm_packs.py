# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""DFM rule packs: the format, the evaluation primitives, and the sandbox boundary.

Three things are asserted here, in the order they have to hold:

* the *format* — a pack is loadable and self-consistent, and every way of
  writing an incoherent one (a rule reading a parameter the pack never declared,
  a rule id that does not belong to its process, a missing predicate file) is a
  typed contract error at load rather than a surprise inside the sandbox;
* the *rules* — each shipped rule evaluates against a fixture part with a known
  violation and produces a finding with the right rule id, the offending tags,
  artifact-bound topology descriptors, and the resolved source artifact ref;
* the *boundary* — a predicate reaching for the filesystem is denied, the unsafe
  local backend refuses DFM jobs outright, and no backend at all is a typed
  refusal rather than a quiet unsandboxed evaluation.

The bwrap cases skip where bubblewrap is unavailable. The in-process cases
exercise the same worker entry point without a sandbox, which is how the
namespace half of the denial is asserted everywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hephaestus.core.dfm import (
    TopologyDescriptor,
    descriptors_from_source_map,
    findings_by_severity,
)
from hephaestus.core.dfm.runner import DfmRequest, evaluate_pack
from hephaestus.core.dfm.types import DfmRuleOutcome
from hephaestus.core.dfm.worker import evaluate_job
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.registry import (
    DfmIndex,
    DfmPack,
    MaterialsIndex,
    RegistryError,
    RegistrySet,
    load_pack,
    load_registry,
)
from opstore.types import JSONValue

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"
DFM_ROOT = REGISTRIES / "dfm"

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="DFM predicates execute only under a probed secure sandbox (bubblewrap)",
)


# -- fixtures ---------------------------------------------------------------


def _brep(shape: object) -> bytes:
    """Serialize a build123d shape the way a published build artifact is stored."""
    import tempfile

    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.brep"
        assert BRepTools.Write_s(shape.wrapped, str(path))  # pyright: ignore[reportAttributeAccessIssue]
        return path.read_bytes()


def laser_fixture() -> bytes:
    """A 5.5 mm panel: not a stock thickness, a 0.5 mm bore, 0.3 mm inner corners.

    Three known violations, one per laser rule.
    """
    from build123d import Align, Axis, Box, Cylinder, Pos, fillet

    panel = Box(60, 40, 5.5)
    panel = panel - Pos(10, 0, 0) * Cylinder(0.25, 20)
    panel = panel - Pos(-20, 12, 0) * Box(
        16, 16, 20, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    concave = [e for e in panel.edges().filter_by(Axis.Z) if abs(e.center().Y - 4.0) < 1e-6]
    assert len(concave) == 2, "fixture must have two concave notch corners"
    return _brep(fillet(concave, 0.3))


def fdm_fixture() -> bytes:
    """A 0.8 mm-walled tray with a 1.0 mm bore and a 63 deg conical overhang."""
    from build123d import Align, Box, Cone, Cylinder, Pos

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    tray = Box(30, 20, 15, align=bottom) - Pos(0, 0, 0.8) * Box(28.4, 18.4, 20, align=bottom)
    tray = tray - Cylinder(0.5, 4, align=bottom)
    flare = Cone(bottom_radius=1, top_radius=9, height=4, align=bottom)
    return _brep(tray + Pos(40, 0, 0) * flare)


def materials_index() -> MaterialsIndex:
    return MaterialsIndex(load_registry(REGISTRIES / "materials"))


def plywood_record() -> dict[str, JSONValue]:
    material = materials_index().get("plywood-baltic-birch")
    assert material is not None
    record: dict[str, JSONValue] = dict(material.to_json())
    record["thicknesses"] = [float(t) for t in material.thicknesses]
    return record


def laser_pack() -> DfmPack:
    return DfmIndex(load_registry(DFM_ROOT)).get("laser_cut")


def fdm_pack() -> DfmPack:
    return DfmIndex(load_registry(DFM_ROOT)).get("fdm")


def _run_in_process(
    pack: DfmPack,
    brep: bytes,
    tmp_path: Path,
    *,
    part: str = "fixture",
    artifact_ref: str = "artifact:build:sha256:fixture",
    metadata: dict[str, str] | None = None,
    material: dict[str, JSONValue] | None = None,
    tags: dict[str, TopologyDescriptor] | None = None,
) -> dict[str, DfmRuleOutcome]:
    """Evaluate a pack through the worker entry point without a sandbox."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source.brep").write_bytes(brep)
    job: dict[str, JSONValue] = {
        "mode": "dfm",
        "origin": "registry",
        "part": part,
        "process": pack.process,
        "source_artifact_ref": artifact_ref,
        "brep": "source.brep",
        "out_dir": str(out_dir),
        "metadata": dict(metadata or {}),
        "material": material,
        "tags": {name: d.to_json() for name, d in (tags or {}).items()},
        "rules": [
            {
                "rule_id": rule.rule_id,
                "title": rule.title,
                "severity": rule.severity,
                "params": dict(rule.values),
                "source": rule.read_predicate(),
            }
            for rule in pack.rules
        ],
    }
    result = evaluate_job(job)
    assert result["status"] == "ok", result["error"]
    rules = result["rules"]
    assert isinstance(rules, list)
    outcomes = [DfmRuleOutcome.from_json(item) for item in rules if isinstance(item, dict)]
    return {outcome.rule_id: outcome for outcome in outcomes}


# -- the pack format --------------------------------------------------------


def test_the_bundled_dfm_registry_loads_with_both_packs() -> None:
    registry = load_registry(DFM_ROOT)
    assert registry.kind == "dfm"
    assert registry.manifest.license
    index = DfmIndex(registry)
    assert index.processes() == ("fdm", "laser_cut")
    assert index.has("laser_cut") and not index.has("cnc_router")


def test_every_rule_declares_an_id_a_title_a_severity_and_its_parameters() -> None:
    for pack in (laser_pack(), fdm_pack()):
        assert pack.rule_ids() == tuple(dict.fromkeys(pack.rule_ids())), "ids must be unique"
        for rule in pack.rules:
            assert rule.rule_id.startswith(f"{pack.process}.")
            assert rule.title and rule.description
            assert rule.severity in ("error", "warning", "info")
            assert rule.params, f"{rule.rule_id} declares no parameters"
            # A rule sees exactly the parameters it declared — no more.
            assert set(rule.values) == set(rule.params)
            assert set(rule.params) <= set(pack.params)
            assert rule.predicate_path.is_file()


def test_the_shipped_packs_cover_the_stage6_rules() -> None:
    assert laser_pack().rule_ids() == (
        "laser_cut.min_feature_vs_kerf",
        "laser_cut.min_internal_radius",
        "laser_cut.sheet_thickness_match",
    )
    assert fdm_pack().rule_ids() == (
        "fdm.min_wall_thickness",
        "fdm.overhang_angle",
        "fdm.min_hole_diameter",
    )


def test_an_unknown_process_or_rule_lists_the_candidates() -> None:
    index = DfmIndex(load_registry(DFM_ROOT))
    with pytest.raises(RegistryError) as unknown_process:
        index.get("waterjet")
    assert unknown_process.value.reason == "unknown_dfm_pack"
    assert "laser_cut" in unknown_process.value.message
    with pytest.raises(RegistryError) as unknown_rule:
        laser_pack().rule("laser_cut.nope")
    assert unknown_rule.value.reason == "unknown_dfm_rule"


def _write_pack(
    directory: Path, manifest: str, *, predicate: str = "def evaluate(ctx):\n    pass\n"
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pack.toml").write_text(manifest, encoding="utf-8")
    (directory / "rule.py").write_text(predicate, encoding="utf-8")
    return directory


PACK_HEADER = """\
[pack]
process = "demo"
version = "0.0.1"

[params]
limit_mm = 1.0
"""


def test_a_rule_reading_an_undeclared_parameter_is_refused_at_load(tmp_path: Path) -> None:
    directory = _write_pack(
        tmp_path / "demo",
        PACK_HEADER
        + '\n[[rules]]\nid = "demo.thing"\ntitle = "T"\npredicate = "rule.py"\n'
        + 'reads = ["limit_mm", "kerf_mm"]\n',
    )
    with pytest.raises(ValidationError) as error:
        load_pack(directory)
    assert "kerf_mm" in error.value.message
    assert "limit_mm" in error.value.message


def test_a_rule_id_outside_its_process_is_refused_at_load(tmp_path: Path) -> None:
    directory = _write_pack(
        tmp_path / "demo",
        PACK_HEADER + '\n[[rules]]\nid = "fdm.thing"\ntitle = "T"\npredicate = "rule.py"\n',
    )
    with pytest.raises(ValidationError, match="prefixed with the pack process"):
        load_pack(directory)


def test_a_duplicate_rule_id_is_refused_at_load(tmp_path: Path) -> None:
    rule = '\n[[rules]]\nid = "demo.thing"\ntitle = "T"\npredicate = "rule.py"\n'
    directory = _write_pack(tmp_path / "demo", PACK_HEADER + rule + rule)
    with pytest.raises(ValidationError, match="duplicate rule id"):
        load_pack(directory)


def test_a_missing_predicate_file_is_refused_at_load(tmp_path: Path) -> None:
    directory = _write_pack(
        tmp_path / "demo",
        PACK_HEADER + '\n[[rules]]\nid = "demo.thing"\ntitle = "T"\npredicate = "gone.py"\n',
    )
    with pytest.raises(ValidationError, match="is missing"):
        load_pack(directory)


def test_an_invalid_severity_is_refused_at_load(tmp_path: Path) -> None:
    directory = _write_pack(
        tmp_path / "demo",
        PACK_HEADER
        + '\n[[rules]]\nid = "demo.thing"\ntitle = "T"\npredicate = "rule.py"\n'
        + 'severity = "catastrophic"\n',
    )
    with pytest.raises(ValidationError, match="severity"):
        load_pack(directory)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("Three laminations of 6 mm Baltic birch plywood, BB/BB grade", "plywood-baltic-birch"),
        # Identity beats prose: the PETG record's notes mention PLA.
        ("PLA filament", "pla"),
        ("PETG sheet", "petg"),
        ("6061 aluminium plate", "al-6061"),
        ("unobtainium", None),
        ("", None),
    ],
)
def test_material_spec_resolves_to_the_registry_record_a_rule_measures_against(
    spec: str, expected: str | None
) -> None:
    match = materials_index().match(spec)
    assert (match.id if match is not None else None) == expected


def test_the_dfm_registry_resolves_through_the_project_registry_set(tmp_path: Path) -> None:
    (tmp_path / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    registries = RegistrySet.open(tmp_path)
    assert registries.dfm.processes() == ("fdm", "laser_cut")
    listing = registries.dfm.listing()
    assert [entry["process"] for entry in listing] == ["fdm", "laser_cut"]
    assert all(entry["registry_digest"] for entry in listing)


# -- the rules, against fixture parts with known violations -----------------


def test_every_laser_rule_fires_on_the_laser_fixture(tmp_path: Path) -> None:
    outcomes = _run_in_process(
        laser_pack(),
        laser_fixture(),
        tmp_path,
        part="panel",
        metadata={"material_spec": "6 mm Baltic birch plywood", "stock_form": "sheet"},
        material=plywood_record(),
    )
    assert set(outcomes) == set(laser_pack().rule_ids())
    assert all(outcome.status == "violations" for outcome in outcomes.values()), {
        rule_id: (outcome.status, outcome.error) for rule_id, outcome in outcomes.items()
    }

    bore = outcomes["laser_cut.min_feature_vs_kerf"].findings[0]
    assert bore.severity == "error"
    assert bore.suggested_bound == pytest.approx(0.8)
    assert bore.topology[0].kind == "face"

    corner = outcomes["laser_cut.min_internal_radius"].findings[0]
    assert corner.suggested_bound == pytest.approx(0.5)
    assert "0.300 mm" in corner.message

    stock = outcomes["laser_cut.sheet_thickness_match"].findings[0]
    assert stock.suggested_bound == pytest.approx(6.0)
    assert "5.500" in stock.message and "Baltic birch" in stock.message


def test_the_sheet_thickness_rule_reports_an_unresolved_material(tmp_path: Path) -> None:
    outcomes = _run_in_process(
        laser_pack(),
        laser_fixture(),
        tmp_path,
        metadata={"material_spec": "unobtainium"},
        material=None,
    )
    finding = outcomes["laser_cut.sheet_thickness_match"].findings[0]
    assert "does not resolve to any materials-registry record" in finding.message


def test_every_fdm_rule_fires_on_the_fdm_fixture(tmp_path: Path) -> None:
    outcomes = _run_in_process(fdm_pack(), fdm_fixture(), tmp_path, part="tray")
    assert set(outcomes) == set(fdm_pack().rule_ids())
    assert all(outcome.status == "violations" for outcome in outcomes.values()), {
        rule_id: (outcome.status, outcome.error) for rule_id, outcome in outcomes.items()
    }

    wall = outcomes["fdm.min_wall_thickness"].findings[0]
    assert wall.measured is not None
    assert wall.suggested_bound == pytest.approx(1.2)
    assert len(wall.topology) == 2, "a wall names both of its faces"

    overhang = outcomes["fdm.overhang_angle"].findings[0]
    assert overhang.severity == "warning"
    assert overhang.suggested_bound == pytest.approx(45.0)

    hole = outcomes["fdm.min_hole_diameter"].findings[0]
    assert hole.suggested_bound == pytest.approx(2.0)


def test_a_clean_part_produces_no_findings(tmp_path: Path) -> None:
    from build123d import Align, Box

    block = Box(30, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    outcomes = _run_in_process(fdm_pack(), _brep(block), tmp_path)
    assert all(outcome.status == "ok" for outcome in outcomes.values())
    assert all(not outcome.findings for outcome in outcomes.values())


def test_findings_carry_the_offending_tag_and_the_resolved_source_artifact(
    tmp_path: Path,
) -> None:
    """A tagged bore is reported by name *and* by artifact-bound descriptor."""
    brep = fdm_fixture()
    pack = fdm_pack()
    # Locate the bore's face the way the source map's tag placement does.
    untagged = _run_in_process(pack, brep, tmp_path / "a")
    descriptor = untagged["fdm.min_hole_diameter"].findings[0].topology[0]
    assert descriptor.tag is None

    tagged = _run_in_process(
        pack,
        brep,
        tmp_path / "b",
        artifact_ref="artifact:build:sha256:deadbeef",
        tags={
            "drain_bore": TopologyDescriptor(
                kind="face",
                solid_id=descriptor.solid_id,
                topology_index=descriptor.topology_index,
                tag="drain_bore",
            )
        },
    )
    finding = tagged["fdm.min_hole_diameter"].findings[0]
    assert finding.tags == ("drain_bore",)
    assert finding.topology[0].tag == "drain_bore"
    assert finding.topology[0].solid_id == descriptor.solid_id
    assert finding.source_artifact_ref == "artifact:build:sha256:deadbeef"
    # Never a bare mask id: the descriptor is (kind, solid_id, topology_index).
    assert set(finding.topology[0].to_json()) == {"kind", "solid_id", "topology_index", "tag"}


def test_tag_descriptors_come_from_a_build_source_map() -> None:
    source_map: dict[str, JSONValue] = {
        "tags": {
            "tread_top": {"kind": "face", "solid": 0, "topo_index": 4, "statement": 3, "line": 9},
            "unresolved": {"kind": "face", "solid": None, "topo_index": None},
        }
    }
    descriptors = descriptors_from_source_map(source_map)
    assert set(descriptors) == {"tread_top"}
    assert descriptors["tread_top"] == TopologyDescriptor(
        kind="face", solid_id=0, topology_index=4, tag="tread_top"
    )


def test_findings_sort_most_severe_first(tmp_path: Path) -> None:
    outcomes = _run_in_process(fdm_pack(), fdm_fixture(), tmp_path)
    findings = [f for outcome in outcomes.values() for f in outcome.findings]
    ordered = findings_by_severity(findings)
    severities = [finding.severity for finding in ordered]
    assert severities == sorted(severities, key=lambda s: 0 if s == "error" else 1)


# -- the sandbox boundary ---------------------------------------------------


HOSTILE_PACK = """\
[pack]
process = "hostile"
version = "0.0.1"

[params]
limit_mm = 1.0
"""

HOSTILE_PREDICATES: dict[str, str] = {
    # `open` is not in the injected namespace at all, and the sandbox has no
    # bind to read from even if it were.
    "reads_a_file": 'def evaluate(ctx):\n    ctx.report(open("/etc/passwd").read()[:20])\n',
    # The classic namespace escape.
    "imports_os": 'def evaluate(ctx):\n    __import__("os").listdir("/")\n',
    # A predicate cannot invent a parameter it never declared.
    "undeclared_param": 'def evaluate(ctx):\n    ctx.param("kerf_mm")\n',
}


def hostile_pack(tmp_path: Path) -> DfmPack:
    directory = tmp_path / "hostile"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = HOSTILE_PACK
    for name, source in HOSTILE_PREDICATES.items():
        (directory / f"{name}.py").write_text(source, encoding="utf-8")
        manifest += (
            f'\n[[rules]]\nid = "hostile.{name}"\ntitle = "{name}"\n'
            f'predicate = "{name}.py"\nreads = ["limit_mm"]\n'
        )
    (directory / "pack.toml").write_text(manifest, encoding="utf-8")
    return load_pack(directory)


def test_a_predicate_reaching_for_the_filesystem_is_denied(tmp_path: Path) -> None:
    from build123d import Box

    outcomes = _run_in_process(hostile_pack(tmp_path / "pack"), _brep(Box(10, 10, 10)), tmp_path)
    denied = outcomes["hostile.reads_a_file"]
    assert denied.status == "error"
    assert denied.error is not None
    assert "SandboxDeniedError" in denied.error
    assert "'open'" in denied.error
    assert not denied.findings


def test_a_predicate_importing_a_module_is_denied(tmp_path: Path) -> None:
    from build123d import Box

    outcomes = _run_in_process(hostile_pack(tmp_path / "pack"), _brep(Box(10, 10, 10)), tmp_path)
    denied = outcomes["hostile.imports_os"]
    assert denied.status == "error"
    assert denied.error is not None and "SandboxDeniedError" in denied.error


def test_a_predicate_reading_an_undeclared_parameter_fails_only_its_own_rule(
    tmp_path: Path,
) -> None:
    from build123d import Box

    outcomes = _run_in_process(hostile_pack(tmp_path / "pack"), _brep(Box(10, 10, 10)), tmp_path)
    assert outcomes["hostile.undeclared_param"].status == "error"
    assert "undeclared parameter" in (outcomes["hostile.undeclared_param"].error or "")
    # Every rule still ran: one broken predicate never hides the others.
    assert set(outcomes) == {f"hostile.{name}" for name in HOSTILE_PREDICATES}


def test_no_backend_is_a_typed_refusal_not_an_unsandboxed_run() -> None:
    request = DfmRequest(
        part="panel",
        process="laser_cut",
        brep=b"not-really-a-brep",
        source_artifact_ref="artifact:build:sha256:x",
    )
    with pytest.raises(RegistryError) as error:
        evaluate_pack(request, laser_pack(), backend=None)
    assert error.value.reason == "capability_not_available"


def test_the_unsafe_local_backend_refuses_dfm_jobs(tmp_path: Path) -> None:
    from hephaestus.core.errors import UnsafeRefusedError

    request = DfmRequest(
        part="panel",
        process="laser_cut",
        brep=laser_fixture(),
        source_artifact_ref="artifact:build:sha256:x",
    )
    with pytest.raises((UnsafeRefusedError, RegistryError)) as error:
        evaluate_pack(request, laser_pack(), backend=UnsafeLocalBackend(), scratch_root=tmp_path)
    message = str(error.value)
    assert "unsafe" in message.lower() or "registry" in message.lower()


def test_a_request_must_name_the_artifact_it_measured() -> None:
    with pytest.raises(ValidationError, match="source_artifact_ref"):
        DfmRequest(part="p", process="fdm", brep=b"x", source_artifact_ref="")


def test_a_pack_cannot_evaluate_another_process_request() -> None:
    request = DfmRequest(
        part="p", process="fdm", brep=b"x", source_artifact_ref="artifact:build:sha256:x"
    )
    with pytest.raises(RegistryError, match="cannot evaluate"):
        evaluate_pack(request, laser_pack(), backend=UnsafeLocalBackend())


@requires_bwrap
def test_the_laser_pack_runs_under_the_secure_sandbox(tmp_path: Path) -> None:
    request = DfmRequest(
        part="panel",
        process="laser_cut",
        brep=laser_fixture(),
        source_artifact_ref="artifact:build:sha256:panel",
        metadata={"material_spec": "6 mm Baltic birch plywood", "stock_form": "sheet"},
        material=plywood_record(),
    )
    evaluation = evaluate_pack(request, laser_pack(), backend=BwrapBackend(), scratch_root=tmp_path)
    assert evaluation.process == "laser_cut"
    assert evaluation.source_artifact_ref == "artifact:build:sha256:panel"
    assert evaluation.registry_digest.startswith("sha256:")
    assert not evaluation.errored_rules()
    assert {finding.rule_id for finding in evaluation.findings} == set(laser_pack().rule_ids())
    for finding in evaluation.findings:
        assert finding.source_artifact_ref == request.source_artifact_ref
        assert finding.topology, "every finding points at topology"


@requires_bwrap
def test_the_fdm_pack_runs_under_the_secure_sandbox(tmp_path: Path) -> None:
    request = DfmRequest(
        part="tray",
        process="fdm",
        brep=fdm_fixture(),
        source_artifact_ref="artifact:build:sha256:tray",
    )
    evaluation = evaluate_pack(request, fdm_pack(), backend=BwrapBackend(), scratch_root=tmp_path)
    assert not evaluation.errored_rules()
    counts = evaluation.severity_counts()
    assert counts.get("error", 0) >= 2 and counts.get("warning", 0) >= 1
    assert evaluation.to_json()["source_artifact_ref"] == "artifact:build:sha256:tray"


@requires_bwrap
def test_a_filesystem_predicate_is_denied_under_the_secure_sandbox(tmp_path: Path) -> None:
    from build123d import Box

    request = DfmRequest(
        part="block",
        process="hostile",
        brep=_brep(Box(10, 10, 10)),
        source_artifact_ref="artifact:build:sha256:block",
    )
    evaluation = evaluate_pack(
        request,
        hostile_pack(tmp_path / "pack"),
        backend=BwrapBackend(),
        scratch_root=tmp_path,
    )
    assert not evaluation.findings
    assert set(evaluation.errored_rules()) == {f"hostile.{name}" for name in HOSTILE_PREDICATES}
    denied = next(o for o in evaluation.outcomes if o.rule_id == "hostile.reads_a_file")
    assert denied.error is not None and "SandboxDeniedError" in denied.error
