# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8B: the editing loop closing on a target (``COMPARE.md`` §2, premise).

Gate clause, in the form the spec states its design premise: *"This closes the
editing loop: ``import_step`` -> modify -> ``compare_solids`` -> converge, with
the harness measuring convergence rather than the model asserting it."*

So this is the whole loop as a product scenario, not a unit: a real bench task
whose ``seed/imports/`` carries a vendor blank and the target it must become, a
scripted model that imports the blank, makes a **wrong** edit, is told by
``compare_solids`` how far off it is, corrects it, and is told it arrived — and
a ``CHECKS`` predicate over ``m.diff`` in the part's own script that fails on
the first build and passes on the second. Everything runs through the real
harness: the real bridge runtime against the packaged Node sidecar, real tool
dispatch, real grading, real archiving.

Two things are deliberately asserted about *who* measured convergence:

* the two ``iou`` figures come off the tool results the model was handed, and
  the first is below the task's threshold while the second is at 1.0 — the
  harness's numbers, not the model's closing sentence;
* the graded build's ``input_hashes.imports`` names **both** ``imports/``
  files — the blank it was built from and the target its check compared
  against — so the comparison is a frozen build input like any other
  (``INGEST.md`` §1) and the convergence claim is reproducible.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g8b import HOLE_MM3, PLATE_MM3, StepFixtures
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.bench import harness
from hephaestus.bench.harness import ARCHIVE_EVENTS_FILENAME, BenchTask, ProviderConfig
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai

#: A scripted turn never needs the 1800 s default.
PROMPT_TIMEOUT = 300.0

#: The threshold the task owns. COMPARE.md §1 is explicit that a number like
#: this is a *claim*, so it lives here and in the part's CHECKS — never in geom.
IOU_MIN = 0.995

PROMPT = (
    "The supplier's blank is in the project as vendor_plate.step and the part we "
    "actually need is target.step. Start from the blank rather than remodelling "
    "it, edit it until it matches the target, and use compare_solids against "
    "import:target.step to confirm you got there instead of guessing. Call the "
    "part `bracket` and build it."
)

#: The task's own acceptance, project scope: the material left after the bore.
CHECKS_SRC = """# The blank's envelope and the material left after the correct bore.
# The window is two orders below the bore itself, so a wrongly sized hole fails.
CHECKS = {{
    "envelope": lambda m: m.bbox("bracket/part") == approx((40.0, 20.0, 5.0), abs=0.05),
    "material_budget": lambda m: m.volume("bracket/part") == approx({volume!r}, abs=5.0),
}}
"""

#: First attempt: Ø4 where the target has Ø6. Buildable, plausible, wrong.
WRONG_SRC = """# The vendor's blank, bored -- first attempt.
base = import_step("vendor_plate.step")
part.geometry = base - Cylinder(2.0, 20.0)
part.description = "vendor blank, bored (first attempt)"

CHECKS = {
    "matches_target": lambda m: m.diff("part", "import:target.step").iou >= 0.995,
}
"""

#: The correction: the bore the target actually has.
RIGHT_SRC = """# The vendor's blank, bored to the target.
base = import_step("vendor_plate.step")
part.geometry = base - Cylinder(3.0, 20.0)
part.description = "vendor blank, bored to target.step"

CHECKS = {
    "matches_target": lambda m: m.diff("part", "import:target.step").iou >= 0.995,
}
"""


# --------------------------------------------------------------------------
# the task and the loop


@pytest.fixture
def converge_task(tmp_path: Path, steps: StepFixtures) -> BenchTask:
    """One bench task: a vendor blank to edit and the target to reach."""
    directory = tmp_path / "tasks" / "converge-plate"
    seed = directory / "seed"
    (seed / "imports").mkdir(parents=True, exist_ok=True)
    (seed / "hephaestus.toml").write_text('[project]\nname = "converge_plate"\n', encoding="utf-8")
    (seed / "globals.py").write_text(
        "# Project-shared namespace (script contract §4).\nPARAMS = {}\n", encoding="utf-8"
    )
    (seed / "imports" / "vendor_plate.step").write_bytes(steps.plate)
    (seed / "imports" / "target.step").write_bytes(steps.plate_holed)
    (directory / "checks").mkdir(exist_ok=True)
    (directory / "checks" / "converge_plate.py").write_text(
        CHECKS_SRC.format(volume=PLATE_MM3 - HOLE_MM3), encoding="utf-8"
    )
    (directory / "task.json").write_text(
        json.dumps(
            {
                "id": "converge-plate",
                "prompt": PROMPT,
                "budget_tool_calls": 20,
                "required_checks": ["converge_plate"],
                "export_requirements": [],
            }
        ),
        encoding="utf-8",
    )
    return BenchTask.load(directory)


@pytest.fixture
def fake_model() -> Iterator[FakeOpenAI]:
    fake = start_fake_openai([])
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def provider(fake_model: FakeOpenAI) -> ProviderConfig:
    return ProviderConfig(providers=(fake_model.provider_spec(),), model_id=fake_model.model_id)


@pytest.fixture
def runtime_factory(sidecar_dist: Path) -> harness.RuntimeFactory:
    def factory(project_root: Path, config: ProviderConfig) -> BridgeRuntime:
        return BridgeRuntime(
            project_root=project_root, providers=config.providers, dist_main=sidecar_dist
        )

    return factory


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def last_tool_result(info: RequestInfo) -> dict[str, Any]:
    """The JSON object of the most recent tool result in the transcript."""
    body = cast("dict[str, Any]", json.loads(info.body_text))
    for message in reversed(cast("list[Any]", body.get("messages", []))):
        if not isinstance(message, dict):
            continue
        entry = cast("dict[str, Any]", message)
        if entry.get("role") != "tool":
            continue
        content = entry.get("content")
        chunks: list[str] = []
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in cast("list[Any]", content):
                if isinstance(part, dict):
                    text = cast("dict[str, Any]", part).get("text")
                    if isinstance(text, str):
                        chunks.append(text)
                elif isinstance(part, str):
                    chunks.append(part)
        for chunk in chunks:
            try:
                parsed, _end = json.JSONDecoder().raw_decode(chunk.lstrip())
            except json.JSONDecodeError:
                continue
            assert isinstance(parsed, dict), parsed
            return cast("dict[str, Any]", parsed)
        break
    raise AssertionError("no tool result in the transcript")


def archived_events(run_dir: Path) -> list[dict[str, Any]]:
    return [
        cast("dict[str, Any]", json.loads(line))
        for line in (run_dir / ARCHIVE_EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def tool_names(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.get("kind") != "tool_call":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            names.append(str(cast("dict[str, Any]", payload).get("name", "")))
    return names


def converge_script(fake: FakeOpenAI, seen: list[float]) -> None:
    """import_step -> wrong edit -> compare -> correct edit -> compare -> checks.

    Every step reads the previous tool result, so the script cannot pass by
    accident: if ``compare_solids`` stopped reporting an ``iou``, or the first
    attempt were silently already correct, the run fails inside the model.
    """

    def create(info: RequestInfo) -> dict[str, Any]:
        recorded = last_tool_result(info)
        assert recorded.get("status") == "ok", recorded
        return tool_call("create_part", {"name": "bracket", "template": "blank"}, "c1")

    def write_wrong(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": "bracket", "expected_hash": created["content_hash"], "script": WRONG_SRC},
            "c2",
        )

    def build_first(info: RequestInfo) -> dict[str, Any]:
        written = last_tool_result(info)
        assert written.get("applied") is True, written
        return tool_call("build_part", {"name": "bracket"}, "c3")

    def compare_first(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        assert built.get("status") == "ok", built
        return tool_call(
            "compare_solids", {"part": "bracket", "target": "import:target.step"}, "c4"
        )

    def reread(info: RequestInfo) -> dict[str, Any]:
        # The measurement the model acts on: it is NOT there yet, and it knows
        # by how much because the harness told it.
        comparison = last_tool_result(info)
        seen.append(float(cast("dict[str, Any]", comparison["diff"])["volume"]["iou"]))
        assert seen[-1] < IOU_MIN, comparison
        return tool_call("read_part", {"name": "bracket"}, "c5")

    def write_right(info: RequestInfo) -> dict[str, Any]:
        current = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": "bracket", "expected_hash": current["content_hash"], "script": RIGHT_SRC},
            "c6",
        )

    def build_second(info: RequestInfo) -> dict[str, Any]:
        written = last_tool_result(info)
        assert written.get("applied") is True, written
        return tool_call("build_part", {"name": "bracket"}, "c7")

    def compare_second(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        assert built.get("status") == "ok", built
        return tool_call(
            "compare_solids", {"part": "bracket", "target": "import:target.step"}, "c8"
        )

    def check(info: RequestInfo) -> dict[str, Any]:
        comparison = last_tool_result(info)
        seen.append(float(cast("dict[str, Any]", comparison["diff"])["volume"]["iou"]))
        assert seen[-1] >= IOU_MIN, comparison
        return tool_call("run_checks", {"name": "bracket"}, "c9")

    def finish(info: RequestInfo) -> dict[str, Any]:
        report = last_tool_result(info)
        assert report.get("status") == "ok", report
        matched = cast("dict[str, Any]", cast("dict[str, Any]", report["checks"])["matches_target"])
        assert matched["pass"] is True, matched
        return {"kind": "text", "chunks": ["bored the blank to the target; iou 1.0 at as_posed"]}

    fake.set_script(
        [
            tool_call(
                "record_requirements",
                {
                    "entries": [
                        {
                            "id": "R1",
                            "text": "the geometry starts from the supplied vendor_plate.step",
                            "source": "specified",
                            "quote": "Start from the blank rather than remodelling it",
                        },
                        {
                            "id": "R2",
                            "text": "the built part matches target.step to iou >= 0.995",
                            "source": "specified",
                            "quote": "edit it until it matches the target",
                        },
                    ]
                },
                "c0",
            ),
            create,
            write_wrong,
            build_first,
            compare_first,
            reread,
            write_right,
            build_second,
            compare_second,
            check,
            finish,
        ]
    )


# ==========================================================================


def test_the_editing_loop_converges_on_a_seeded_target(
    tmp_path: Path,
    converge_task: BenchTask,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    seen: list[float] = []
    converge_script(fake_model, seen)
    archive = tmp_path / "results" / provider.model_slug / "2026-07-27"

    run = harness.run_task(
        converge_task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-27",
    )

    assert run.error is None, run.error
    assert run.passed, run.reasons
    grade = cast("dict[str, Any]", run.grade)
    for name, value in cast("dict[str, Any]", grade["checks"]).items():
        assert cast("dict[str, Any]", value)["pass"] is True, name

    # Convergence was MEASURED, and it moved: the first attempt sat below the
    # task's threshold, the corrected one is the target to numerical noise.
    first, second = seen
    assert first < IOU_MIN < second
    assert second == pytest.approx(1.0, abs=1e-6)
    # The wrong bore was wrong by exactly the ring of material it left behind:
    # the Ø4 part contains the Ø6 target, so iou is (V - hole6)/(V - hole4).
    hole_4 = HOLE_MM3 * 4.0 / 9.0  # the same cylinder at radius 2 instead of 3
    assert first == pytest.approx((PLATE_MM3 - HOLE_MM3) / (PLATE_MM3 - hole_4), rel=1e-3)

    # The loop really is import -> edit -> compare -> edit -> compare.
    names = tool_names(archived_events(archive / "converge-plate-s1"))
    assert names.count("compare_solids") == 2
    assert names.index("compare_solids") < names.index("read_part")
    assert names[-1] == "run_checks"

    # …and the target is a build input, frozen beside the blank the part was
    # built from: a convergence claim someone else can reproduce.
    project = Path(cast("str", run.project_dir))
    layout = load_project(project)
    store = open_store(layout)
    try:
        from hephaestus.agent_bridge.cad_ops import CadOps

        current = CadOps(layout, store).current_build("bracket")
        assert current is not None
        imports = dict(current.input_hashes.imports)
    finally:
        store.close()
    assert sorted(imports) == ["target.step", "vendor_plate.step"], imports
    assert all(digest.startswith("sha256:") for digest in imports.values()), imports


def test_a_part_that_never_converged_fails_its_own_check(
    tmp_path: Path,
    converge_task: BenchTask,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    """The same task, a model that stops at the wrong bore: the loop says no.

    This is the half that makes the convergence evidence worth anything. The
    model builds something plausible, asserts nothing, and both the task's own
    acceptance and the part's ``m.diff`` predicate report the gap.
    """

    def create(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return tool_call("create_part", {"name": "bracket", "template": "blank"}, "c1")

    def write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": "bracket", "expected_hash": created["content_hash"], "script": WRONG_SRC},
            "c2",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("applied") is True
        return tool_call("build_part", {"name": "bracket"}, "c3")

    def checks(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return tool_call("run_checks", {"name": "bracket"}, "c4")

    captured: dict[str, Any] = {}

    def finish(info: RequestInfo) -> dict[str, Any]:
        captured.update(last_tool_result(info))
        return {"kind": "text", "chunks": ["bored the blank; looks right to me"]}

    fake_model.set_script(
        [
            tool_call(
                "record_requirements",
                {
                    "entries": [
                        {
                            "id": "R1",
                            "text": "the built part matches target.step",
                            "source": "specified",
                            "quote": "edit it until it matches the target",
                        }
                    ]
                },
                "c0",
            ),
            create,
            write,
            build,
            checks,
            finish,
        ]
    )
    archive = tmp_path / "results" / provider.model_slug / "2026-07-27"

    run = harness.run_task(
        converge_task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-27",
    )

    assert run.error is None, run.error
    assert not run.passed
    # The part's own m.diff predicate is the one that names the gap, with the
    # whole measured record kept beside the verdict.
    matched = cast("dict[str, Any]", cast("dict[str, Any]", captured["checks"])["matches_target"])
    assert matched["pass"] is False, matched
    measured = cast("dict[str, Any]", matched["measured"])
    assert cast("dict[str, Any]", measured["volume"])["iou"] < IOU_MIN
    assert measured["align"] == "as_posed"
