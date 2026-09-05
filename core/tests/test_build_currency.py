# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``Publisher.freshness`` — the read-time recomputation audit-2026-09-04 B-5 adds.

``current`` (``core/project_store/publication.py``) is set exactly once, by the
pointer flip, and stays publication state (``architecture.md`` §3.5): it is
never recomputed by a reader. Freshness is a SEPARATE fact, computed on a
lock-free read from the same comparison ``Publisher._revalidate`` performs
under locks at publish time — extracted here as a module-level
``input_mismatches`` so publication behaviour stays byte-identical (covered,
unmodified, by the existing raced-publication tests in
``test_project_store_publication.py``).

``Publisher.freshness(part)`` is the public surface these tests pin: ``None``
when there is no current bundle to compare against; otherwise an object naming
whether the current build is still fresh and, if not, WHICH recorded inputs the
live project has moved past — the same closed vocabulary ``_revalidate``'s
mismatch messages already use as a prefix (``script``, ``hc_dependencies``,
``part_params``, ``toolchain``, ``imports[...]``).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher
from test_project_store_helpers import DEFAULT_SCRIPT, make_project, make_unpublished

from opstore import OpStore

GLOBALS_SOURCE = "T = 6\n"


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj", globals_source=GLOBALS_SOURCE)


@pytest.fixture
def opstore(layout: ProjectLayout) -> Iterator[OpStore]:
    store = open_store(layout)
    yield store
    store.close()


@pytest.fixture
def publisher(layout: ProjectLayout, opstore: OpStore) -> Publisher:
    return Publisher(layout, opstore)


def test_freshness_is_none_with_no_current_build(publisher: Publisher) -> None:
    """A part that has never published a current build has nothing to compare."""
    assert publisher.freshness("widget") is None


def test_freshness_is_fresh_immediately_after_publish(
    layout: ProjectLayout, publisher: Publisher, tmp_path: Path
) -> None:
    build = make_unpublished("widget", layout.part_path("widget").read_text(), tmp_path / "out")
    outcome = publisher.publish_build(build, op_id="pub-1")
    assert outcome.kind == "current"

    freshness = publisher.freshness("widget")
    assert freshness is not None
    assert freshness.fresh is True
    assert freshness.changed_inputs == ()


def test_freshness_names_script_after_a_live_edit_with_no_rebuild(
    layout: ProjectLayout, publisher: Publisher, tmp_path: Path
) -> None:
    """The B-5 reproduction, at the engine layer: an edit with no rebuild."""
    build = make_unpublished("widget", layout.part_path("widget").read_text(), tmp_path / "out")
    publisher.publish_build(build, op_id="pub-2")

    layout.part_path("widget").write_text(DEFAULT_SCRIPT + "# edited\n", encoding="utf-8")

    freshness = publisher.freshness("widget")
    assert freshness is not None
    assert freshness.fresh is False
    assert freshness.changed_inputs == ("script",)


def test_freshness_stays_fresh_when_the_script_is_rewritten_identically(
    layout: ProjectLayout, publisher: Publisher, tmp_path: Path
) -> None:
    """The negative half: identical bytes rewritten to disk are not a drift."""
    build = make_unpublished("widget", layout.part_path("widget").read_text(), tmp_path / "out")
    publisher.publish_build(build, op_id="pub-3")

    layout.part_path("widget").write_text(DEFAULT_SCRIPT, encoding="utf-8")

    freshness = publisher.freshness("widget")
    assert freshness is not None
    assert freshness.fresh is True
    assert freshness.changed_inputs == ()


def test_freshness_names_hc_dependencies_after_a_project_param_change(
    layout: ProjectLayout, publisher: Publisher, tmp_path: Path
) -> None:
    """The ``hc`` leg: a consumed project value moving is a changed input too,
    even though the part's own script text never moved — the same distinction
    ``test_raced_hc_change_never_current_and_keeps_stale`` exercises at publish
    time.
    """
    publisher.projections.apply_hc_state({"T": 6})
    build = make_unpublished(
        "widget",
        layout.part_path("widget").read_text(),
        tmp_path / "out",
        consumed={"T": 6},
    )
    publisher.publish_build(build, op_id="pub-4")

    publisher.projections.apply_hc_state({"T": 8})

    freshness = publisher.freshness("widget")
    assert freshness is not None
    assert freshness.fresh is False
    assert freshness.changed_inputs == ("hc_dependencies",)


def test_freshness_is_recomputed_lock_free_and_never_rebuilds(
    layout: ProjectLayout, publisher: Publisher, tmp_path: Path
) -> None:
    """A read: no lock is taken and the current pointer is untouched by the call."""
    build = make_unpublished("widget", layout.part_path("widget").read_text(), tmp_path / "out")
    outcome = publisher.publish_build(build, op_id="pub-5")

    layout.part_path("widget").write_text(DEFAULT_SCRIPT + "# edited\n", encoding="utf-8")
    publisher.freshness("widget")

    assert publisher.locks.held() == ()
    stored = publisher.current_result("widget")
    assert stored is not None
    assert stored.artifact_ref == outcome.artifact_ref  # unchanged: no rebuild happened
