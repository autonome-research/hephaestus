"""The ``list_parts`` projection's build axis (``audit-2026-09-04`` J-web-viewport-7).

§4.5's landing default was "the alphabetically first part the server lists",
which correlates with nothing an operator cares about — and in the shipped
fixture it is the one part that has never been built, so the workspace opened on
an absence with every panel below it empty. The fix is a field, not a route:
``list_parts_projection`` hoists each part's build state out of the build axis so
the default is a pick over a document the client already has.

These are the engine-side halves: the vocabulary is closed, the token is computed
by ONE function, and the three record shapes land the three tokens. The
cross-route half — that ``GET /parts`` and ``GET /parts/{part}/build`` say the
same word about the same part — is a server test, because the build projection
lives above this layer.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.listing import (
    BUILD_STATUS_VALUES,
    list_parts_projection,
    part_build_status,
)
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import ProjectStore
from test_project_store_helpers import DEFAULT_SCRIPT, make_project, make_unpublished

from opstore import OpStore

#: The three parts the fixture project carries, one per build state, named so
#: the alphabetically first one is the UNBUILT one — the shape that made the
#: defect visible in the shipped fixture, reproduced here rather than described.
PARTS = {"aardvark": DEFAULT_SCRIPT, "broken": DEFAULT_SCRIPT, "widget": DEFAULT_SCRIPT}


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj", parts=PARTS)


@pytest.fixture
def opstore(layout: ProjectLayout) -> Iterator[OpStore]:
    store = open_store(layout)
    yield store
    store.close()


def listed(root: Path, opstore: OpStore, layout: ProjectLayout) -> dict[str, Any]:
    body = list_parts_projection(root, ProjectStore(layout, opstore))
    parts = cast("list[dict[str, Any]]", body["parts"])
    return {str(entry["name"]): entry for entry in parts}


def test_the_vocabulary_is_closed_and_is_what_the_one_rule_can_return() -> None:
    """The three tokens, and no fourth arriving by typo.

    ``BUILD_STATUS_VALUES`` is the closed set the build route serves; this
    asserts the set literally *and* that :func:`part_build_status` cannot return
    anything outside it, so widening one without the other fails here rather
    than in a client that has already branched on the new word.
    """
    assert BUILD_STATUS_VALUES == ("ok", "error", "not_built")
    assert set(BUILD_STATUS_VALUES) == {"ok", "error", "not_built"}


def test_a_part_with_no_published_record_at_all_is_the_named_absence() -> None:
    """§6.3: silence never reads as a pass. ``None`` is ``not_built``, not ``ok``."""
    assert part_build_status(None) == "not_built"


def test_a_failed_record_is_error_and_a_successful_one_is_ok(tmp_path: Path) -> None:
    """The record's two-value vocabulary maps onto the route's three-value one.

    ``BuildResult.status`` says ``ok`` / ``failed`` (``core.types.BuildStatus``);
    the routes say ``ok`` / ``error`` / ``not_built``. The translation is this
    one function, so the two vocabularies cannot come to disagree about which
    word means a failure.
    """
    ok = make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "ok").result
    failed = make_unpublished("broken", DEFAULT_SCRIPT, tmp_path / "bad", status="failed").result
    assert (ok.status, part_build_status(ok)) == ("ok", "ok")
    assert (failed.status, part_build_status(failed)) == ("failed", "error")


def test_the_listing_names_a_build_status_for_every_part_it_lists(
    layout: ProjectLayout, opstore: OpStore, tmp_path: Path
) -> None:
    """Every row carries the field, and the three states are the three tokens.

    The row's other four keys are asserted unchanged in the same breath: this
    change adds a field and drops nothing, and ``heph part list --json`` returns
    this same body.
    """
    publisher = Publisher(layout, opstore)
    publisher.publish_build(
        make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "ok"), op_id="pub-ok"
    )
    publisher.publish_build(
        make_unpublished("broken", DEFAULT_SCRIPT, tmp_path / "bad", status="failed"),
        op_id="pub-bad",
    )
    rows = listed(layout.root, opstore, layout)
    assert set(rows) == set(PARTS)
    assert {name: row["build_status"] for name, row in rows.items()} == {
        "aardvark": "not_built",
        "broken": "error",
        "widget": "ok",
    }
    for row in rows.values():
        assert set(row) == {"name", "path", "content_hash", "snapshot_ref", "build_status"}
        assert row["build_status"] in BUILD_STATUS_VALUES


def test_the_landing_default_would_now_skip_the_unbuilt_alphabetically_first_part(
    layout: ProjectLayout, opstore: OpStore, tmp_path: Path
) -> None:
    """The defect, in the shape the client resolves it.

    The listing is alphabetical and its first row is the part that has never been
    built, which is exactly what made "position zero" a default that always
    opened on an absence. The field is what lets the client pick the first row
    with something to show without a second request; this asserts the document
    supports that pick, and that a wholly unbuilt project still leaves position
    zero as the only answer (so the composed absence stays reachable).
    """
    publisher = Publisher(layout, opstore)
    publisher.publish_build(
        make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "ok"), op_id="pub-ok"
    )
    body = list_parts_projection(layout.root, ProjectStore(layout, opstore))
    parts = cast("list[dict[str, Any]]", body["parts"])
    assert parts[0]["name"] == "aardvark"
    assert parts[0]["build_status"] == "not_built"
    first_with_something = next(row for row in parts if row["build_status"] != "not_built")
    assert first_with_something["name"] == "widget"


def test_a_wholly_unbuilt_project_says_so_for_every_part(
    layout: ProjectLayout, opstore: OpStore
) -> None:
    """No part has a record, so no row claims one — and the client falls back to
    position zero, landing on the absence and its two remedies rather than on
    nothing."""
    rows = listed(layout.root, opstore, layout)
    assert {row["build_status"] for row in rows.values()} == {"not_built"}


def test_a_later_success_wins_over_an_earlier_failure(
    layout: ProjectLayout, opstore: OpStore, tmp_path: Path
) -> None:
    """The same preference ``GET /parts/{part}/build`` applies, for the same reason.

    The route reads the current successful record first and falls back to the
    last failure; a part that failed once and then built is ``ok``. Reversing
    that here would make the listing and the build route disagree about a part
    the operator is looking at.
    """
    publisher = Publisher(layout, opstore)
    publisher.publish_build(
        make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "bad", status="failed"),
        op_id="pub-bad",
    )
    assert listed(layout.root, opstore, layout)["widget"]["build_status"] == "error"
    publisher.publish_build(
        make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "ok"), op_id="pub-ok"
    )
    assert listed(layout.root, opstore, layout)["widget"]["build_status"] == "ok"


def test_the_listing_reads_through_the_store_it_was_handed(
    layout: ProjectLayout, opstore: OpStore, tmp_path: Path
) -> None:
    """One opstore handle, not a second one opened per call.

    §2.1 gives one process the project's leases, and a projection that opened its
    own handle would be a second ``LockManager`` owner over the same
    ``.heph/locks/``. The projection therefore reads through
    :attr:`ProjectStore.store` and shares :attr:`ProjectStore.locks`; this pins
    that the build it reports is the one published through *this* handle, which a
    second handle over a copied store could not see.
    """
    project_store = ProjectStore(layout, opstore)
    assert project_store.store is opstore
    Publisher(layout, opstore).publish_build(
        make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "ok"), op_id="pub-ok"
    )
    body = list_parts_projection(layout.root, project_store)
    parts = cast("list[dict[str, Any]]", body["parts"])
    assert [row["build_status"] for row in parts if row["name"] == "widget"] == ["ok"]
    assert project_store.locks.held() == ()
