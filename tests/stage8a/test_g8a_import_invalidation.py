# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8A: an imported file is a build input — staleness, revalidation, replay.

Gate clause: *input-hash invalidation (replaced file ⇒ stale, revalidation
refuses current-flip, retry replays original bytes)*.

``INGEST.md`` §1: "a changed file is a changed input". The evidence is taken at
the level the change is felt — the project's own state and the tools the model
calls next:

* an operator who replaces a file under ``imports/`` makes its importers stale,
  and a stale part refuses to export until it is rebuilt;
* a file replaced *while a build is in flight* loses the current-pointer flip
  (the same revalidation scripts and params get), so a build is never published
  as current against inputs that are no longer there;
* a retried publication of that same build replays the recorded record — and a
  build run from frozen inputs uses the ORIGINAL bytes, not whatever is on disk
  now.

The publisher is driven directly for the two revalidation clauses because "the
file changed between freeze and publish" has no tool call that expresses it: it
is a race, and the gate has to be able to lose it deliberately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from _g8a import StepFixtures, build_ok, install_import, write_script
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.publication import FrozenBuildInputs, Publisher
from hephaestus.testing.tools_fixture import Project

PART = "vendor_plate"
SRC = 'part.geometry = import_step("plate.step")\n'


@pytest.fixture
def built(project: Project, steps: StepFixtures) -> Project:
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, PART, SRC)
    build_ok(project, PART)
    return project


def publisher(project: Project) -> Publisher:
    return Publisher(project.layout, project.store)


def run(inputs: FrozenBuildInputs, out_dir: Path) -> UnpublishedBuild:
    """One build straight from frozen inputs — the CLI's own request shape."""
    request = BuildRequest(
        part=inputs.part,
        script=inputs.script,
        globals_source=inputs.globals_source,
        imports=dict(inputs.imports),
        import_errors=dict(inputs.import_errors),
    )
    return run_build(request, backend=UnsafeLocalBackend(), out_dir=out_dir)


# ==========================================================================
# a replaced file marks its importers stale


def test_a_replaced_import_makes_its_importer_stale_and_unexportable(
    built: Project, steps: StepFixtures
) -> None:
    exported = cast("dict[str, Any]", built.call("export_part", {"name": PART, "format": "step"}))
    assert exported["paths"]

    install_import(built.root, "plate.step", steps.plate_taller)
    # The next build in the project refreshes the live imports/ state (build_part
    # does it before it freezes anything), which is what notices the change.
    build_ok(built, "widget")

    stale = publisher(built).projections.state().stale
    assert PART in stale
    assert "plate.step" in stale[PART]

    with pytest.raises(DispatchError) as excinfo:
        built.call("export_part", {"name": PART, "format": "step", "target": "stale.step"})
    assert excinfo.value.reason == "stale_source"
    assert "plate.step" in str(excinfo.value)


def test_rebuilding_against_the_new_file_clears_the_staleness(
    built: Project, steps: StepFixtures
) -> None:
    install_import(built.root, "plate.step", steps.plate_taller)
    build_ok(built, "widget")

    build_ok(built, PART)

    assert publisher(built).projections.state().stale == {}
    exported = cast(
        "dict[str, Any]",
        built.call("export_part", {"name": PART, "format": "step", "target": "fresh.step"}),
    )
    current = built.cad.current_build(PART)
    assert current is not None
    assert exported["source_input_hashes"]["imports"] == dict(current.input_hashes.imports)
    assert current.metrics is not None
    assert current.metrics.bbox_mm[2] == pytest.approx(8.0, abs=1e-6)


def test_an_unimported_file_invalidates_nobody(built: Project, steps: StepFixtures) -> None:
    install_import(built.root, "unused.step", steps.boss)

    build_ok(built, "widget")

    assert publisher(built).projections.state().stale == {}
    assert built.call("export_part", {"name": PART, "format": "step", "target": "ok.step"})["paths"]


# ==========================================================================
# revalidation and replay


def test_a_file_replaced_mid_build_loses_the_current_flip(
    project: Project, steps: StepFixtures, tmp_path: Path
) -> None:
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, PART, SRC)
    pub = publisher(project)
    frozen = pub.freeze_inputs(PART)
    build = run(frozen, tmp_path / "out")
    assert build.result.status == "ok", build.result.error

    install_import(project.root, "plate.step", steps.plate_taller)
    outcome = pub.publish_build(build, op_id="g8a-raced")

    assert outcome.kind == "raced"
    assert any(detail.startswith("imports[plate.step]") for detail in outcome.details)
    # Nothing became current, so the model has nothing to export either.
    assert project.cad.current_build(PART) is None
    with pytest.raises(DispatchError) as excinfo:
        project.call("export_part", {"name": PART, "format": "step"})
    assert excinfo.value.reason == "invalid_part"
    assert "no current successful build" in str(excinfo.value)


def test_a_retried_publication_replays_the_original_bytes(
    project: Project, steps: StepFixtures, tmp_path: Path
) -> None:
    """The §8 retry contract, with the imported file in the frozen input set."""
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, PART, SRC)
    pub = publisher(project)
    frozen = pub.freeze_inputs(PART)
    # The operator swaps the file after the freeze: a retry must still replay
    # the geometry that was frozen, exactly as it does for the script text.
    install_import(project.root, "plate.step", steps.plate_taller)

    build = run(frozen, tmp_path / "out")

    assert build.result.status == "ok", build.result.error
    metrics = build.result.metrics
    assert metrics is not None
    assert metrics.bbox_mm[2] == pytest.approx(5.0, abs=1e-6), "the frozen plate, not the new one"

    # Put the frozen file back so revalidation passes, then publish twice on the
    # same op id: the second call replays the first record rather than re-flipping.
    install_import(project.root, "plate.step", steps.plate)
    first = pub.publish_build(build, op_id="g8a-retry")
    again = pub.publish_build(build, op_id="g8a-retry")

    assert first.kind == "current"
    assert again.replayed
    assert again.record_blob == first.record_blob
    current = project.cad.current_build(PART)
    assert current is not None
    assert current.input_hashes.imports == build.result.input_hashes.imports
