"""Evaluating declared constraints against current builds (``ASSEMBLY.md`` §2).

Real published artifacts throughout: a bored plate and the shaft that sits in
it, built and published through the ordinary pipeline, then addressed the way a
constraint addresses them — through the §7 selector grammar against a *reloaded*
BRep. The clauses under test are the ones that distinguish an assembly status
from a loop over ``m.clearance``:

* every anchor form resolves (whole part, tag, label, binding);
* every way of failing to resolve is NAMED, and none is reported as a
  violation — ``unresolvable`` is its own state;
* a rebuild that breaks a formerly satisfied fit marks the projection stale and
  re-evaluation flips it;
* two processes reading the same artifacts measure the same numbers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import cast

import pytest
from _assembly_project import (
    NOMINAL_CLEARANCE_MM,
    assumed,
    build_part,
    fit_entry,
    open_project,
    pin_script,
)
from hephaestus.core.addressing import GeometryIndex, resolve
from hephaestus.core.assembly import (
    UNRESOLVABLE_REASONS,
    AssemblyEvaluator,
    AssemblyStatus,
    ConstraintOutcome,
    addressing_refusal,
)
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.constraints import ConstraintSet
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import STATE_POINTER, ProjectionState
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore


@pytest.fixture
def project(tmp_path: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    layout, store = open_project(tmp_path / "proj")
    yield layout, store
    store.close()


def _declare(store: OpStore, layout: ProjectLayout, *entries: Mapping[str, JSONValue]) -> None:
    constraints = ConstraintSet(layout, store)
    for entry in entries:
        constraints.declare(entry)


def _outcome(status: AssemblyStatus, constraint_id: str) -> ConstraintOutcome:
    return next(item for item in status.constraints if item.id == constraint_id)


class TestResolutionAndVerdicts:
    def test_a_tag_anchored_fit_measures_the_declared_clearance(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        status = AssemblyEvaluator(layout, store).evaluate()
        outcome = _outcome(status, "c-pin-fit")
        assert outcome.state == "satisfied"
        assert outcome.measured == pytest.approx(NOMINAL_CLEARANCE_MM, abs=1e-9)
        assert outcome.a.rule == "tag"
        assert outcome.a.artifact_ref is not None
        assert status.blocking() == ()

    def test_a_violated_constraint_carries_its_residual_and_blocks(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        # The same pair against a window the geometry misses: 0.1 mm is not in
        # [0.2, 0.4]. Nothing about the geometry changed — only the claim.
        _declare(store, layout, fit_entry(min_mm=0.2, max_mm=0.4))
        status = AssemblyEvaluator(layout, store).evaluate()
        outcome = _outcome(status, "c-pin-fit")
        assert outcome.state == "violated"
        assert outcome.residual is not None
        assert outcome.residual["satisfied"] is False
        assert outcome.reason is None
        assert status.violated == ("c-pin-fit",)
        assert status.blocking() == ("c-pin-fit",)

    def test_every_anchor_form_resolves(self, project: tuple[ProjectLayout, OpStore]) -> None:
        layout, store = project
        _declare(
            store,
            layout,
            {
                "id": "c-whole",  # rule 1: the whole compound
                "kind": "clearance_min",
                "a": "base",
                "b": "pin",
                "value_mm": 0.0,
                "provenance": assumed(),
            },
            fit_entry(id="c-tag"),  # rule 2: tags on both sides
            {
                "id": "c-label",  # rule 3: the geometry-tree label
                "kind": "no_interference",
                "a": "base",
                "b": "pin:shaft_body",
                "provenance": assumed(),
            },
        )
        status = AssemblyEvaluator(layout, store).evaluate()
        rules = {item.id: (item.a.rule, item.b.rule) for item in status.constraints}
        assert rules["c-whole"] == ("part", "part")
        assert rules["c-tag"] == ("tag", "tag")
        assert rules["c-label"] == ("part", "label")
        assert status.unresolvable == ()

    def test_the_status_names_the_artifacts_it_read(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        status = AssemblyEvaluator(layout, store).evaluate()
        publisher = Publisher(layout, store)
        for part in ("base", "pin"):
            current = publisher.current_result(part)
            assert current is not None
            assert status.artifact_refs[part] == current.artifact_ref

    def test_withdrawn_constraints_are_not_evaluated(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        constraints = ConstraintSet(layout, store)
        constraints.declare(fit_entry(min_mm=0.2, max_mm=0.4))
        constraints.withdraw("c-pin-fit", "the interface was redesigned")
        status = AssemblyEvaluator(layout, store).evaluate()
        assert status.constraints == ()
        assert status.blocking() == ()

    def test_evaluating_a_named_subset(self, project: tuple[ProjectLayout, OpStore]) -> None:
        layout, store = project
        _declare(store, layout, fit_entry(), fit_entry(id="c-two"))
        status = AssemblyEvaluator(layout, store).evaluate(["c-two"])
        assert [item.id for item in status.constraints] == ["c-two"]

    def test_an_unknown_id_is_an_addressing_error_not_an_empty_status(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        with pytest.raises(AddressingError) as err:
            AssemblyEvaluator(layout, store).evaluate(["c-nope"])
        assert err.value.candidates == ("c-pin-fit",)


class TestUnresolvableTaxonomy:
    """Each way of not being checkable is named, and none of them is a violation."""

    def test_each_reason_is_reported_under_its_own_name(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(
            store,
            layout,
            {
                "id": "c-missing-part",
                "kind": "no_interference",
                "a": "ghost",
                "b": "pin",
                "provenance": assumed(),
            },
            {
                "id": "c-no-build",
                "kind": "no_interference",
                "a": "never_built",
                "b": "pin",
                "provenance": assumed(),
            },
            {
                "id": "c-dangling",
                "kind": "no_interference",
                "a": "pin:no_such_tag",
                "b": "base",
                "provenance": assumed(),
            },
            {
                "id": "c-unaddressable",
                "kind": "no_interference",
                "a": "pin:spare",  # bound in the script, absent from the geometry
                "b": "base",
                "provenance": assumed(),
            },
        )
        status = AssemblyEvaluator(layout, store).evaluate()
        reasons = {item.id: item.reason for item in status.constraints}
        assert reasons["c-missing-part"] == "missing_part"
        assert reasons["c-no-build"] == "no_current_build"
        assert reasons["c-dangling"] == "dangling_selector"
        assert reasons["c-unaddressable"] == "unaddressable_anchor"
        # ``shape_refused`` and ``ambiguous_selector`` complete the taxonomy and
        # are asserted below; every reason here is one of the named set.
        assert set(reasons.values()) <= {None, *UNRESOLVABLE_REASONS}

        for item in status.constraints:
            if item.reason is not None:
                assert item.state == "unresolvable"
                assert item.residual is None  # never dressed as a measurement
                assert item.detail
        assert set(status.unresolvable) == {
            "c-missing-part",
            "c-no-build",
            "c-dangling",
            "c-unaddressable",
        }
        # Not checked is not passed, and not checked is not violated either.
        assert status.violated == ()
        assert set(status.blocking()) == set(status.unresolvable)

    def test_the_wrong_class_of_shape_is_a_named_refusal_not_a_number(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(
            store,
            layout,
            {
                "id": "c-boxes",
                "kind": "fit",  # a plate and a shaft: one bore, one shaft, fine
                "a": "base",
                "b": "pin",
                "min_mm": 0.05,
                "max_mm": 0.2,
                "provenance": assumed(),
            },
            {
                "id": "c-two-shafts",
                "kind": "fit",  # a shaft against itself: no hole anywhere
                "a": "pin",
                "b": "pin:shaft_face",
                "min_mm": 0.0,
                "max_mm": 1.0,
                "provenance": assumed(),
            },
        )
        status = AssemblyEvaluator(layout, store).evaluate()
        assert _outcome(status, "c-boxes").state == "satisfied"
        refused = _outcome(status, "c-two-shafts")
        assert refused.state == "unresolvable"
        assert refused.reason == "shape_refused"
        assert "fit_needs_hole_and_shaft" in (refused.detail or "")

    def test_ambiguity_and_absence_are_different_reasons(self) -> None:
        """§7 forbids guessing between two interpretations; so does the status.

        Both failures come out of the real addressing layer over a real index —
        a label set where ``wall#2`` is both a literal label and the display name
        of the second ``wall``. What is pinned is that the engine keeps the two
        apart, which it can only do because the addressing error names its own
        reason (message text is informational, never dispatched on).
        """
        index = GeometryIndex(labels=("wall", "wall", "wall#2"))
        with pytest.raises(AddressingError) as ambiguous:
            resolve("wall#2", index)
        with pytest.raises(AddressingError) as absent:
            resolve("roof", index)

        assert addressing_refusal(ambiguous.value)[0] == "ambiguous_selector"
        assert addressing_refusal(absent.value)[0] == "dangling_selector"
        for exc in (ambiguous.value, absent.value):
            reason, detail = addressing_refusal(exc)
            assert reason in UNRESOLVABLE_REASONS
            assert detail  # a refusal always says what it could not resolve


class TestStaleness:
    def test_an_edit_that_breaks_a_fit_marks_the_projection_stale_and_flips_it(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        evaluator = AssemblyEvaluator(layout, store)
        assert evaluator.evaluate().satisfied == ("c-pin-fit",)

        projected = evaluator.projected()
        assert projected is not None
        assert projected.stale == ()
        assert projected.satisfied == ("c-pin-fit",)

        # The edit: a fatter shaft leaves 0.01 mm, outside the declared window.
        layout.part_path("pin").write_text(pin_script(4.99), encoding="utf-8")
        build_part(Publisher(layout, store), layout, "pin")

        stale = evaluator.projected()
        assert stale is not None
        assert stale.stale == ("pin",)
        # The projection is stale, NOT quietly re-measured: it still reports the
        # last measurement, and says so.
        assert stale.satisfied == ("c-pin-fit",)

        rechecked = evaluator.evaluate()
        assert rechecked.violated == ("c-pin-fit",)
        assert rechecked.stale == ()
        outcome = _outcome(rechecked, "c-pin-fit")
        assert outcome.measured == pytest.approx(0.01, abs=1e-9)

    def test_a_stale_status_survives_gc_after_the_rebuild_that_staled_it(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        """Staleness is only honest if the stale status is still *there* to read.

        The status document hangs off the projection-state blob, which is the
        protected GC root — and the state pointer moves on every publication. If
        the reachability edge were recorded once, at evaluation time, the very
        rebuild that marks the status stale would orphan it, and a project that
        measured its mates would read back as one that never had.
        """
        layout, store = project
        _declare(store, layout, fit_entry())
        evaluator = AssemblyEvaluator(layout, store)
        evaluator.evaluate()
        blob = store.blobs.read_pointer(STATE_POINTER)
        assert blob is not None
        status_blob = ProjectionState.from_json(
            cast("Mapping[str, JSONValue]", json.loads(store.blobs.get(blob).decode("utf-8")))
        ).assembly
        assert status_blob is not None

        layout.part_path("pin").write_text(pin_script(4.99), encoding="utf-8")
        build_part(Publisher(layout, store), layout, "pin")

        assert status_blob.status_blob in store.gc.reachable()
        store.gc.collect()
        stale = evaluator.projected()
        assert stale is not None and stale.stale == ("pin",)

    def test_rebuilding_an_unanchored_part_does_not_invalidate_the_status(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(
            store,
            layout,
            {
                "id": "c-base-only",
                "kind": "no_interference",
                "a": "base",
                "b": "base:bore_face",
                "provenance": assumed(),
            },
        )
        evaluator = AssemblyEvaluator(layout, store)
        evaluator.evaluate()
        layout.part_path("pin").write_text(pin_script(4.5), encoding="utf-8")
        build_part(Publisher(layout, store), layout, "pin")
        projected = evaluator.projected()
        assert projected is not None
        assert projected.stale == ()

    def test_the_projected_status_has_an_immutable_ref(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        evaluator = AssemblyEvaluator(layout, store)
        assert evaluator.projected_ref() is None
        evaluator.evaluate()
        ref = evaluator.projected_ref()
        assert ref is not None
        assert ref.startswith("artifact:assembly-status:sha256:")
        assert store.blobs.has(blob_hash_of_ref(ref))

    def test_a_partial_evaluation_is_not_projected(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry(), fit_entry(id="c-two"))
        evaluator = AssemblyEvaluator(layout, store)
        assert evaluator.projected() is None
        evaluator.evaluate(["c-two"])
        assert evaluator.projected() is None
        evaluator.evaluate()
        projected = evaluator.projected()
        assert projected is not None
        assert len(projected.constraints) == 2


class TestDeterminism:
    def test_two_processes_measure_the_same_residuals(
        self, project: tuple[ProjectLayout, OpStore], tmp_path: Path
    ) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        here = AssemblyEvaluator(layout, store).evaluate(record=False)

        script = textwrap.dedent(
            """
            import json, sys
            from pathlib import Path
            from hephaestus.core.assembly import AssemblyEvaluator
            from hephaestus.core.project_store.layout import load_project, open_store

            layout = load_project(Path(sys.argv[1]))
            store = open_store(layout)
            try:
                status = AssemblyEvaluator(layout, store).evaluate(record=False)
            finally:
                store.close()
            print(json.dumps(status.to_json(), sort_keys=True))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(layout.root)],
            capture_output=True,
            text=True,
            check=True,
        )
        there = json.loads(completed.stdout.strip().splitlines()[-1])
        mine = json.loads(json.dumps(here.to_json(), sort_keys=True))
        assert there == mine
        residual = there["constraints"][0]["residual"]
        assert residual["measured"] == pytest.approx(here.constraints[0].measured, abs=1e-9)

    def test_re_evaluation_is_idempotent(self, project: tuple[ProjectLayout, OpStore]) -> None:
        layout, store = project
        _declare(store, layout, fit_entry())
        evaluator = AssemblyEvaluator(layout, store)
        first = evaluator.evaluate()
        second = evaluator.evaluate()
        assert first.to_json() == second.to_json()
