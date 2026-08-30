# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12C: the validation ladder and the corpus family (§7.4, §7.5).

Gate clauses covered here:

* **48** the reviewer context carries ``MeshQuality``, ``geometry_source`` and
  the ``ScanDistance`` **with its method fields intact**, and a mesh-derived
  ``geometry_source`` is surfaced and asserted **not** to produce a blocking
  finding;
* **50** the ``scan-*`` corpus family: each task's two independent reference
  solutions pass its own acceptance through the engine path, the
  ``scan_requirements`` parser rejects a requirement that omits what its check
  needs, and the corpus-count pins are repointed with this stage cited;
* **51** the Tier 3 bench clause: scan-prose and scan-seeded are each their own
  split, baselined on their own first measurement at >= 3 seeds, neither
  compared against nor averaged into the v1/v2 baselines, and the existing 0.70
  prose bar is not diluted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _g12c import Fixtures, build_ok, install_import
from hephaestus.bench.harness import BenchTask, GradeReport, grade_reference_solution, load_tasks
from hephaestus.bench.harness._tasks import SCAN_CHECK_KINDS, ScanRequirement
from hephaestus.testing.tools_fixture import Project

REPO = Path(__file__).resolve().parents[2]

#: The independently authored second implementations (one home, not a copy —
#: the same tree the Stage 11 meta-suite grades its own family from).
CORPUS_VARIANTS: Path = REPO / "server" / "tests" / "fixtures" / "corpus_variants"

#: The Stage 12C corpus-v5 additions, stated here so the gate suite owns its own
#: count clause rather than trusting another suite's constant.
SCAN_PAIR: frozenset[str] = frozenset({"scan-socket-cuff", "scan-boss-relief"})

#: The public corpus after this stage: twenty-one (v4) plus the scan pair.
CORPUS_SIZE_V5: int = 23


def _mapping(value: Any) -> Mapping[str, Any]:
    assert isinstance(value, dict), f"expected a mapping record, got {value!r}"
    return cast("Mapping[str, Any]", value)


@pytest.fixture(scope="module")
def scan_tasks() -> dict[str, BenchTask]:
    return {task.id: task for task in load_tasks(sorted(SCAN_PAIR))}


# ==========================================================================
# clause 48 — the reviewer context (VALIDATION.md §5, MESH_INGEST.md §7.4)


SCRIPT_WITH_SCAN = (
    'scan = import_mesh("limb.stl", units="mm")\n'
    "part.geometry = Box(44.0, 34.0, 24.0)\n"
    'part.description = f"shroud around a scan of {scan.triangle_count} triangles"\n'
)

SCRIPT_WITHOUT_SCAN = "part.geometry = Box(10.0, 10.0, 10.0)\n"

#: The third part the reviewer must see: geometry that IS the scan, sewn. This
#: is the only script in the stage whose build carries
#: ``geometry_source == "mesh_derived"``, and clause 48's second half is about
#: what a reviewer is told when one exists.
SCRIPT_MESH_DERIVED = (
    'scan = import_mesh("limb.stl", units="mm")\n'
    'part.geometry = mesh_to_solid(scan, intent="measurement_target")\n'
    'part.description = "the limb scan itself, sewn"\n'
)


@pytest.fixture
def reviewed(project: Project, meshes: Fixtures) -> Project:
    """A project with a scan-measuring part, a plain part, and a mesh-derived one.

    The third is what makes clause 48's second half evidence rather than
    inference: without a part whose ``geometry_source`` is actually
    ``"mesh_derived"``, "surfaced and not blocking" can only be asserted about
    the rules, never about a context a reviewer would receive.
    """
    install_import(project.root, "limb.stl", meshes.box_stl)
    build_ok(project, "shroud", SCRIPT_WITH_SCAN)
    build_ok(project, "plain", SCRIPT_WITHOUT_SCAN)
    build_ok(project, "sewn", SCRIPT_MESH_DERIVED)
    return project


class _PassingReviewer:
    """A reviewer child that passes everything it is shown, confidently.

    Deliberately credulous, for the reason ``tests/stage9b`` uses the same
    shape: if a blocking finding appears in the report anyway, it came from a
    RULE and not from the reviewer's judgement — which is the only way to tell
    "geometry_source does not block" from "the reviewer happened not to mind".
    """

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def call(self, request: Any) -> Any:
        from hephaestus.agent_bridge.review import ReviewerResponse

        self.requests.append(request)
        return ReviewerResponse(
            findings=tuple(
                {
                    "id": str(cast("Mapping[str, Any]", entry)["id"]),
                    "verdict": "pass",
                    "evidence": "measured it, looks right",
                    "channel": "numeric",
                }
                for entry in request.context.requirements
            )
        )


def test_the_reviewer_receives_the_quality_record_and_the_distance(
    reviewed: Project,
) -> None:
    """§7.4: for every part whose script imports a mesh, and by RULE.

    Measured at review time from the delivered geometry, exactly as the assembly
    and motion statuses are — never copied from the agent's ``CHECKS``, which §5
    excludes and which a reviewer inheriting would inherit the misreading with.
    """
    from hephaestus.agent_bridge.review import build_review_context

    context = build_review_context(reviewed.cad, request="shroud the scan")

    # Every part whose script imports a mesh, by rule — which is both the part
    # that MEASURES against the scan and the part that was SEWN from it. The
    # plain part is absent because it declares none, not because it is fine.
    assert [scan.part for scan in context.scans] == ["sewn", "shroud"]
    scan = next(entry for entry in context.scans if entry.part == "shroud")
    assert scan.path == "limb.stl"
    assert scan.units == "mm"
    assert scan.canonical_hash.startswith("sha256:")
    assert scan.refusal is None

    quality = _mapping(scan.quality)
    assert quality["boundary_edge_count"] == 0
    assert quality["connected_component_count"] == 1
    assert "self_intersection_method" in quality, "the sampled fact names its method"

    distance = _mapping(scan.distance)
    assert distance["scan_to_part_min_mm"] == pytest.approx(2.0, abs=1e-9)
    assert distance["part_to_scan_method"] == "kdtree_bound_exact_triangle"
    assert distance["part_to_scan_bias"] == "exact"
    assert "iou" not in distance and "chamfer_mm" not in distance


def test_a_part_that_imports_no_mesh_contributes_no_scan_entry(reviewed: Project) -> None:
    """Empty means "no part declares a scan", never "the scans are fine"."""
    from hephaestus.agent_bridge.review import build_review_context, scan_evidence

    context = build_review_context(reviewed.cad, request="shroud the scan")
    assert "plain" not in {scan.part for scan in context.scans}
    assert scan_evidence(reviewed.cad, ["plain"]) == ()


def test_every_part_carries_geometry_source_from_the_closed_set(reviewed: Project) -> None:
    """§4.3: ``{"authored", "mesh_derived"}``, on every part, from the bundle.

    A part that MEASURED against a scan is ``"authored"`` — the scan was
    measurement data, and §5.2 exists precisely so that distinction stays true.
    """
    from hephaestus.agent_bridge.review import build_review_context
    from hephaestus.core.project_store.publication import GEOMETRY_SOURCES

    context = build_review_context(reviewed.cad, request="shroud the scan")
    sources = {part.name: part.geometry_source for part in context.parts}
    assert set(sources) == {"shroud", "plain", "sewn", "widget", "bracket"}
    for name, source in sources.items():
        assert source in GEOMETRY_SOURCES, name
    assert sources["shroud"] == "authored", (
        "importing a mesh and MEASURING against it leaves a build authored (§4.3)"
    )
    assert sources["sewn"] == "mesh_derived", (
        "a SUCCESSFUL mesh_to_solid is the one thing that flips it (§4.3)"
    )


def test_the_context_json_carries_all_three_facts(reviewed: Project) -> None:
    """The reviewer is handed JSON, so the fields must survive serialization."""
    from hephaestus.agent_bridge.review import build_review_context

    payload = json.loads(json.dumps(build_review_context(reviewed.cad, request="r").to_json()))
    assert payload["scans"], "the scan section is present"
    entry = _mapping(cast("list[Any]", payload["scans"])[0])
    assert entry["quality"] and entry["distance"]
    assert _mapping(entry["distance"])["part_to_scan_method"]
    for part in cast("list[Any]", payload["parts"]):
        assert "geometry_source" in _mapping(part)


def test_the_prompt_names_the_facts_and_refuses_the_clinical_reading(
    reviewed: Project,
) -> None:
    """§11.3 rides the prompt: a distance is never evidence of fit."""
    from hephaestus.agent_bridge.review import build_review_context

    prompt = build_review_context(reviewed.cad, request="shroud the scan").prompt()
    assert "geometry_source" in prompt
    assert "vertex_nn_upper_bound" in prompt, "the method vocabulary is named, not implied"
    assert "not blocking by rule" in prompt
    assert "fitting a limb" in prompt


def test_a_mesh_derived_geometry_source_is_surfaced_to_the_reviewer(
    reviewed: Project,
) -> None:
    """SURFACED (§4.3, §7.4): the reviewer is TOLD, in the context and in the prompt.

    "Surfaced" is a claim about a context a reviewer actually receives, so it is
    asserted against one — a real project carrying a real part whose geometry
    came out of ``mesh_to_solid``. The previous shape of this clause read
    ``review.py``'s source text for the *absence* of the word, which is evidence
    about the rules and no evidence at all that anybody is told.
    """
    from hephaestus.agent_bridge.review import build_review_context

    context = build_review_context(reviewed.cad, request="sew the scan")
    derived = [part for part in context.parts if part.geometry_source == "mesh_derived"]
    assert [part.name for part in derived] == ["sewn"]

    # It survives the crossing to JSON, which is what the reviewer is handed…
    payload = json.loads(json.dumps(context.to_json()))
    by_name = {
        _mapping(part)["name"]: _mapping(part) for part in cast("list[Any]", payload["parts"])
    }
    assert by_name["sewn"]["geometry_source"] == "mesh_derived"
    # …and the prompt names the vocabulary, so the word is not a field a
    # reviewer has to already know to look for.
    prompt = context.prompt()
    assert "geometry_source" in prompt
    assert "mesh_derived" in prompt


def test_a_mesh_derived_geometry_source_raises_no_blocking_finding(
    reviewed: Project,
) -> None:
    """NOT BLOCKING (§7.4): this stage adds no never-green rule, and it is measured.

    Two independent bindings, because either alone is weaker than the clause:

    * **through the harness.** A real review runs over the project that contains
      the mesh-derived part, under a FakeModel reviewer that passes everything.
      A blocking finding in the resulting report could then only have come from
      a rule — and none appears. The credulous reviewer is the point: it is what
      separates "no rule blocks on it" from "the reviewer did not mind".
    * **over the rules.** Every function that manufactures a blocking finding by
      rule is enumerated, and none of them reads ``geometry_source`` or a scan
      distance. A rule added later that blocked on it fails here even if a
      future fixture stopped containing a mesh-derived part.
    """
    from hephaestus.agent_bridge import review
    from hephaestus.agent_bridge.review import TerminationReviewService, build_review_context

    context = build_review_context(reviewed.cad, request="sew the scan")
    assert any(part.geometry_source == "mesh_derived" for part in context.parts), (
        "the clause is about a context that HAS one"
    )

    reviewer = _PassingReviewer()
    report = TerminationReviewService(reviewed.cad, reviewer).review(
        request="sew the scan", run_id="g12c-48"
    )
    assert reviewer.requests, "the reviewer really ran"
    blocking = [finding for finding in report.findings if finding.verdict == "fail"]
    assert blocking == [], [f"{f.id}: {f.evidence}" for f in blocking]
    assert report.green is True

    source = (REPO / "server" / "src" / "hephaestus" / "agent_bridge" / "review.py").read_text(
        encoding="utf-8"
    )
    # Every rule that manufactures a blocking finding by rule is named here;
    # none of them reads geometry_source or a scan distance.
    for maker in (
        review.dimension_review_findings,
        review.assembly_review_findings,
        review.motion_review_findings,
    ):
        assert callable(maker)
    assert "geometry_source" not in source.split("def dimension_review_findings")[1]
    assert "scan" not in source.split("def assembly_review_findings")[1].split("def ")[0]


def test_a_refused_scan_rides_the_context_instead_of_vanishing(
    project: Project, meshes: Fixtures
) -> None:
    """A scan that could not be measured is not a scan that matched.

    The part declares a unit the file cannot be admitted at — here the file is
    not a mesh at all — so the evidence carries the named refusal in place of a
    distance rather than being dropped, which would read to a reviewer as "no
    scan".
    """
    from hephaestus.agent_bridge.review import scan_evidence

    install_import(project.root, "broken.stl", b"this is not a mesh")
    script = 'scan = import_mesh("broken.stl", units="mm")\npart.geometry = Box(10.0, 10.0, 10.0)\n'
    project.call("create_part", {"name": "broken_scan"})
    read = cast("dict[str, Any]", project.call("read_part", {"name": "broken_scan"}))
    project.call(
        "write_part",
        {"name": "broken_scan", "expected_hash": read["content_hash"], "script": script},
    )
    project.call("build_part", {"name": "broken_scan"})

    evidence = scan_evidence(project.cad, ["broken_scan"])
    assert len(evidence) == 1
    assert evidence[0].distance is None
    assert evidence[0].refusal is not None
    assert _mapping(evidence[0].refusal)["reason"]


# ==========================================================================
# clause 50 — the scan-* corpus family, graded through the engine path


def _assert_acceptance(label: str, task: BenchTask, report: GradeReport) -> None:
    """The whole acceptance, judged on one grade report."""
    assert report.passed, f"{label} solution failed: {report.reasons}"
    for name, value in report.checks.items():
        assert _mapping(value).get("pass") is True, f"{label}: check {name} did not pass: {value}"
    assert len(report.scans) == len(task.scans)
    for record in report.scans:
        entry = _mapping(record)
        assert "error" not in entry, entry
        distance = _mapping(entry["distance"])
        # Measured through the engine path, so the record carries the method it
        # was measured with — a bound compared against a tolerance is not a
        # measurement, and the archive must be able to show which it was.
        assert distance["part_to_scan_method"] == "kdtree_bound_exact_triangle"
        assert _mapping(entry["quality"])["weld_tol_mm"] == pytest.approx(1e-6)
    assert report.restored_protected == ()


@pytest.mark.parametrize("task_id", sorted(SCAN_PAIR))
def test_the_reference_solution_passes_its_own_acceptance(
    scan_tasks: dict[str, BenchTask], task_id: str, tmp_path: Path
) -> None:
    task = scan_tasks[task_id]
    _assert_acceptance("reference", task, grade_reference_solution(task, tmp_path / "project"))


@pytest.mark.parametrize("task_id", sorted(SCAN_PAIR))
def test_the_independent_second_solution_passes_the_same_acceptance(
    scan_tasks: dict[str, BenchTask], task_id: str, tmp_path: Path
) -> None:
    """A different build of the same interface — a sketch extrusion rather than a
    boolean of primitives — with the same clearance. The acceptance grades the
    distance to the scan, not the reference geometry back (``VALIDATION.md`` §1).
    """
    task = scan_tasks[task_id]
    _assert_acceptance(
        "variant",
        task,
        grade_reference_solution(task, tmp_path / "project", solutions_dir=CORPUS_VARIANTS),
    )


def test_the_acceptance_measures_a_clearance_and_names_its_tolerance(
    scan_tasks: dict[str, BenchTask],
) -> None:
    """Functional, never reproductive: a fit measured as a fit (``VALIDATION.md`` §1)."""
    cuff = scan_tasks["scan-socket-cuff"]
    assert [req.kind for req in cuff.scans] == ["clearance_min"]
    assert cuff.scans[0].min_mm == pytest.approx(1.5)
    assert cuff.scans[0].units == "mm"

    relief = scan_tasks["scan-boss-relief"]
    assert {req.kind for req in relief.scans} == set(SCAN_CHECK_KINDS)
    assert relief.scans[0].min_mm == pytest.approx(1.5)
    assert relief.scans[1].max_mm == pytest.approx(4.0)


# ------------------------------------------------------------------------
# the grader's own honesty: an absent measurement is not a pass, and a bound
# is not a measurement (§6.4). Both are pure functions of the record, so both
# are asserted without a kernel — the grader is where a false pass would be
# least visible, so it is where the assertion has to be cheapest to run.


def test_a_missing_scan_measurement_is_refused_by_name_and_never_reads_as_zero() -> None:
    """The regression this guard exists for: absence must not read as success.

    ``distance.get(field, 0.0)`` — the shape this replaced — made a
    ``deviation_max`` requirement PASS on a record that measured nothing at all,
    because ``0.0 > max_mm`` is False. The ``clearance_min`` branch happened to
    fail safe under the same default, which is exactly what made the other one
    easy to miss: one of the two was wrong and neither looked it.
    """
    from hephaestus.bench.harness._grade import scan_measurement

    for kind in ("clearance_min", "deviation_max"):
        value, refusal = scan_measurement({}, kind)
        assert value is None
        assert refusal is not None
        token, detail = refusal
        assert token == "scan_unmeasurable"
        assert detail.startswith("missing:")

    # …and a record that DID measure comes back as the number, unchanged.
    value, refusal = scan_measurement({"scan_to_part_min_mm": 1.25}, "clearance_min")
    assert refusal is None
    assert value == pytest.approx(1.25)


def test_a_direction_that_came_back_as_a_bound_is_refused_scan_method() -> None:
    """The ``scan_method`` guard is CODE, not a sentence in a docstring.

    Both of today's requirement kinds read direction A, which has no bounded
    mode at all — so the guard is latent, and a guard that is latent and
    undefended is a guard that will not exist when it is first needed. It is
    exercised here by pointing a kind at the part→scan direction, which is
    precisely the amendment that would otherwise make it reachable without
    anybody noticing: a ``vertex_nn_upper_bound`` result compared against a
    tolerance is not a measurement (§6.4), and the requirement must fail rather
    than be judged on a ceiling.
    """
    from hephaestus.bench.harness import _grade

    bounded = {
        "part_to_scan_mean_mm": None,
        "part_to_scan_max_mm": None,
        "part_to_scan_upper_bound_mm": 3.5,
        "part_to_scan_method": "vertex_nn_upper_bound",
    }
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(
            cast("dict[str, Any]", _grade.SCAN_REQUIREMENT_FIELDS),
            "deviation_max",
            ("part_to_scan_max_mm", "part_to_scan"),
        )
        value, refusal = _grade.scan_measurement(bounded, "deviation_max")
    finally:
        monkey.undo()

    assert value is None
    assert refusal is not None
    token, detail = refusal
    assert token == "scan_method"
    assert "vertex_nn_upper_bound" in detail

    # The map is back where it was, and direction A still declares no bound
    # field — which is the statement that direction A has no bounded mode, not
    # an omission.
    assert _grade.SCAN_REQUIREMENT_FIELDS["deviation_max"] == (
        "scan_to_part_max_mm",
        "scan_to_part",
    )
    assert _grade.SCAN_DIRECTION_BOUND_FIELD["scan_to_part"] is None
    assert _grade.SCAN_DIRECTION_BOUND_FIELD["part_to_scan"] == "part_to_scan_upper_bound_mm"


def test_every_scan_requirement_kind_has_a_field_the_grader_knows_how_to_read() -> None:
    """The closed kind vocabulary and the grader's map cannot drift apart.

    A kind added to ``SCAN_CHECK_KINDS`` without a row here would reach
    ``scan_measurement`` as a ``KeyError`` at grading time — a harness crash in
    place of a verdict, discovered during a sweep rather than here.
    """
    from hephaestus.bench.harness._grade import SCAN_DIRECTION_BOUND_FIELD, SCAN_REQUIREMENT_FIELDS

    assert set(SCAN_REQUIREMENT_FIELDS) == set(SCAN_CHECK_KINDS)
    for _field, direction in SCAN_REQUIREMENT_FIELDS.values():
        assert direction in SCAN_DIRECTION_BOUND_FIELD


def test_a_scan_task_declares_its_part_as_a_deliverable(
    scan_tasks: dict[str, BenchTask],
) -> None:
    """A scan requirement names a part, so the grader must build it."""
    assert scan_tasks["scan-socket-cuff"].declared_parts() == frozenset({"cuff"})
    assert scan_tasks["scan-boss-relief"].declared_parts() == frozenset({"frame"})


@pytest.mark.parametrize(
    ("payload", "missing"),
    [
        ({"part": "cuff", "scan": "limb.stl", "units": "mm", "kind": "clearance_min"}, "min_mm"),
        ({"part": "cuff", "scan": "limb.stl", "units": "mm", "kind": "deviation_max"}, "max_mm"),
    ],
)
def test_the_parser_rejects_a_requirement_that_omits_what_its_check_needs(
    payload: dict[str, Any], missing: str
) -> None:
    """``VALIDATION.md`` §1: a check without its named tolerance cannot fail.

    And a check that cannot fail is worse than no check — it reads as evidence
    while proving nothing.
    """
    with pytest.raises(ValueError) as caught:
        ScanRequirement.from_json(payload)
    assert missing in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"scan": "limb.stl", "units": "mm", "kind": "clearance_min", "min_mm": 1.0},
        {"part": "cuff", "units": "mm", "kind": "clearance_min", "min_mm": 1.0},
        {"part": "cuff", "scan": "limb.stl", "kind": "clearance_min", "min_mm": 1.0},
        {
            "part": "cuff",
            "scan": "limb.stl",
            "units": "furlongs",
            "kind": "clearance_min",
            "min_mm": 1.0,
        },
        {"part": "cuff", "scan": "limb.stl", "units": "mm", "kind": "vibes", "min_mm": 1.0},
        {
            "part": "cuff",
            "scan": "limb.stl",
            "units": "mm",
            "kind": "clearance_min",
            "min_mm": 1.0,
            "align": "principal",
        },
    ],
    ids=["no-part", "no-scan", "no-units", "bad-units", "bad-kind", "principal"],
)
def test_the_parser_refuses_every_incomplete_or_out_of_vocabulary_requirement(
    payload: dict[str, Any],
) -> None:
    """The vocabulary is CLOSED, and the unit is never defaulted (§1.3, §6.5)."""
    with pytest.raises(ValueError):
        ScanRequirement.from_json(payload)


def test_a_scan_requirement_round_trips_through_its_json_form() -> None:
    entry = {
        "part": "cuff",
        "scan": "limb.stl",
        "units": "mm",
        "kind": "clearance_min",
        "min_mm": 1.5,
        "align": "as_posed",
        "note": "the cuff clears the scan",
    }
    assert ScanRequirement.from_json(entry).to_json() == entry


def test_the_fixture_scan_is_synthesized_from_an_analytic_solid() -> None:
    """§7.5: ground truth exists because the scan was MADE from a known solid.

    A real scan has none — nobody knows where the limb's surface actually was —
    so a corpus task seeded with one could only ever grade a part against
    another measurement. The generator is committed, and ``--check``
    re-synthesizes and compares bytes rather than trusting the committed file.
    """
    generator = REPO / "scripts" / "synthesize_scan_fixture.py"
    assert generator.is_file()
    source = generator.read_text(encoding="utf-8")
    assert "--check" in source and "--write" in source
    assert "does not add noise" in source, "a fabricated defect would grade the fabrication"
    for task_id, name in (("scan-socket-cuff", "limb.stl"), ("scan-boss-relief", "boss.stl")):
        assert (REPO / "corpus" / "tasks" / task_id / "seed" / "imports" / name).is_file()


def test_the_public_corpus_is_twenty_three_with_the_scan_pair() -> None:
    prose = {task.id for task in load_tasks(specs=("prose",))}
    assert len(prose) == CORPUS_SIZE_V5
    assert prose >= SCAN_PAIR
    seeded = {task.id for task in load_tasks(specs=("seeded",))}
    assert {f"{task_id}@seeded" for task_id in SCAN_PAIR} <= seeded
    assert len(seeded) == CORPUS_SIZE_V5


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("tests/stage6/test_g6_corpus_v1.py", "CORPUS_SIZE = 23"),
        ("server/tests/test_bench_corpus.py", "CORPUS_V5_ADDITIONS"),
        ("tests/stage9c/test_corpus_mechanisms.py", "corpus v5 is twenty-three public tasks"),
        ("tests/stage11c/test_g11c_corpus.py", "CORPUS_SIZE_NOW: int = 23"),
    ],
)
def test_every_repointed_count_pin_cites_this_stage(path: str, needle: str) -> None:
    """ "Repointed **with this stage cited**" — the citation is the clause.

    A count silently edited from 21 to 23 is indistinguishable from a count that
    drifted. Each pin must carry the amendment that moved it, so a reader who
    finds the number surprising can find out why.
    """
    source = (REPO / path).read_text(encoding="utf-8")
    assert needle in source, f"{path}: pin not repointed"
    window = source[max(0, source.index(needle) - 1600) : source.index(needle) + 600]
    assert "MESH_INGEST.md" in window and "2026-08-29" in window, (
        f"{path}: the repointed pin does not cite the Stage 12C amendment that moved it"
    )


def test_each_new_task_carries_a_dated_hand_count_budget_derivation() -> None:
    """``VALIDATION.md`` §7: a new task may not ship a bare guess."""
    for task_id in sorted(SCAN_PAIR):
        notes = json.loads(
            (REPO / "corpus" / "tasks" / task_id / "task.json").read_text(encoding="utf-8")
        )["notes"]
        assert "hand-count" in notes
        assert "2026-08-25" in notes, "the measured-budget policy's own date"
        assert "MESH_INGEST.md" in notes, "and the amendment that added the task"


def test_each_new_task_refuses_the_clinical_reading_in_its_own_notes() -> None:
    """§11.3 is not only in the spec: the corpus says it where a task is read."""
    for task_id in sorted(SCAN_PAIR):
        notes = json.loads(
            (REPO / "corpus" / "tasks" / task_id / "task.json").read_text(encoding="utf-8")
        )["notes"]
        assert "clinical claim" in notes


# ==========================================================================
# clause 51 — the Tier 3 bench clause, following the split rule verbatim


def test_the_scan_family_is_the_corpus_pair_and_the_vocabulary_is_closed() -> None:
    """The split cannot drift away from the corpus it claims to measure."""
    from hephaestus.bench.scoring import CORPUS_FAMILIES, FAMILY_SCAN, SCAN_FAMILY_TASKS

    assert set(SCAN_FAMILY_TASKS) == set(SCAN_PAIR)
    assert FAMILY_SCAN in CORPUS_FAMILIES
    assert CORPUS_FAMILIES[FAMILY_SCAN] == SCAN_FAMILY_TASKS


@pytest.mark.parametrize("spec", ["prose", "seeded"])
def test_a_scan_run_lands_in_its_own_split_in_both_specs(spec: str) -> None:
    """Its own split — and one per spec, never merged (the G9C precedent)."""
    from hephaestus.bench.scoring import FAMILY_SCAN, SCAN_FAMILY_TASKS, split_name

    for task_id in SCAN_FAMILY_TASKS:
        assert split_name(task_id, spec) == f"{FAMILY_SCAN}-{spec}"
    assert split_name("bracket-101", spec) == spec


def _run(task_id: str, seed: int, *, passed: bool = True, spec: str = "prose") -> dict[str, Any]:
    return {
        "task_id": task_id if spec == "prose" else f"{task_id}@seeded",
        "spec": spec,
        "seed": seed,
        "passed": passed,
        "model": "reference-model",
        "date": "2026-08-29",
    }


def test_the_scan_family_is_neither_compared_against_nor_averaged_into_the_prose_bar() -> None:
    """The 0.70 bar keys on its own coverage constant and is not diluted.

    The carve-out is mechanical: ``split_name`` moves these runs out before the
    aggregate is formed, so a sweep over the whole corpus cannot fold them in
    through the plumbing either — which is the dilution arriving by accident
    rather than by decision.
    """
    from hephaestus.bench.scoring import FAMILY_SCAN, score_records

    records = [_run("bracket-101", seed) for seed in (1, 2, 3)]
    records += [_run("scan-socket-cuff", seed, passed=False) for seed in (1, 2, 3)]
    score = score_records(records)

    assert score.prose.n == 3, "only the non-family runs are in the gated split"
    assert score.prose.pass_rate == pytest.approx(1.0)
    family = score.family_split(FAMILY_SCAN, "prose")
    assert family.n == 3
    assert family.pass_rate == pytest.approx(0.0)
    assert family.threshold is None and family.meets_threshold is None
    assert score.n_total == 6, "carved out, never dropped"


def test_the_family_is_baselined_on_its_first_measurement_and_never_again(
    tmp_path: Path,
) -> None:
    """Its own first measurement, at >= 3 seeds, and never re-taken."""
    from hephaestus.bench.scoring import (
        SCAN_BASELINE_MIN_SEEDS,
        record_scan_baseline,
        score_records,
    )

    records = [
        _run(task_id, seed, spec=spec)
        for task_id in sorted(SCAN_PAIR)
        for seed in (1, 2, 3)
        for spec in ("prose", "seeded")
    ]
    path = tmp_path / "scan_baseline.json"
    baseline = record_scan_baseline(score_records(records), path)
    assert baseline is not None
    assert baseline["family"] == "scan"
    assert baseline["min_seeds"] == SCAN_BASELINE_MIN_SEEDS
    assert baseline["threshold"] is None, "a baseline is a record, never a gate"
    splits = cast("dict[str, Any]", baseline["splits"])
    assert set(splits) == {"scan-prose", "scan-seeded"}
    for row in splits.values():
        assert cast("dict[str, Any]", row)["threshold"] is None

    # Never re-baselined: a second call over DIFFERENT numbers returns the
    # stored file unchanged. A baseline that could be re-taken is not a baseline.
    again = record_scan_baseline(
        score_records([_run(task_id, 1, passed=False) for task_id in sorted(SCAN_PAIR)]), path
    )
    assert again == baseline


def test_a_first_measurement_thinner_than_three_seeds_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """Named, not silent: the alternative is a file that looks like evidence."""
    from hephaestus.bench.scoring import (
        INSUFFICIENT_SCAN_SEEDS,
        record_scan_baseline,
        score_records,
    )

    thin = [_run(task_id, seed) for task_id in sorted(SCAN_PAIR) for seed in (1, 2)]
    path = tmp_path / "scan_baseline.json"
    with pytest.raises(ValueError) as caught:
        record_scan_baseline(score_records(thin), path)
    assert INSUFFICIENT_SCAN_SEEDS in str(caught.value)
    assert not path.exists(), "nothing is written when the measurement is refused"


def test_an_unmeasured_scan_family_is_said_out_loud_by_the_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Absence of measurement is a fact about the evidence, so the tool says it.

    The live reference-model sweep is a detached run this repository cannot take
    and does not fake, so the honest statement of clause 51's status is
    *machinery closed, measurement outstanding* — and ``heph bench score`` prints
    exactly that on any archive that ran no scan task.
    """
    from hephaestus.bench import cli_bench
    from hephaestus.bench.scoring import SCAN_BASELINE_FILENAME

    archive = tmp_path / "reference-model" / "2026-08-29"
    archive.mkdir(parents=True)
    (archive / "runs.jsonl").write_text(
        "".join(json.dumps(_run("bracket-101", seed)) + "\n" for seed in (1, 2, 3)),
        encoding="utf-8",
    )
    cli_bench.main(["bench", "score", str(archive)])
    out = capsys.readouterr().out

    assert "scan family: NOT MEASURED" in out
    for task_id in sorted(SCAN_PAIR):
        assert task_id in out
    assert "outstanding" in out
    assert not (archive.parent / SCAN_BASELINE_FILENAME).exists()
