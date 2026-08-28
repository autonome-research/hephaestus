# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G4.9 to G4.11: the reopened transcript, its threading, and its archived identities.

``INTERFACE.md`` §2.8 commits "the first *archive*" of a guarantee
``history.ts`` already makes — identical entries yield identical events and seq
numbers — and names the property the archive exists to defend:

    The e2e asserts the reopened transcript's IDs equal the archive **across a
    sidecar restart**, because restart-stability is the property the archive
    exists to defend.

A browser cannot restart the sidecar; the serving process owns it (§2.1). So the
restart half lives here, where a test can start a sidecar, tear it down, and
start another over the same committed transcript. The browser half — that the
reopened panel *renders* those identities into ``data-event-id`` — is
``web/e2e/stream.spec.ts``. Neither is the other's substitute: this one proves
the identities are stable, that one proves they reach the DOM.

Every test in this module reads the transcript the fixture **commits**. Nothing
is recorded here; a mismatch means either the normalizer changed (re-baseline
with ``scripts/record_workspace_transcript.py``, as its own PR) or something is
wrong.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.testing.workspace_fixture import (
    EVENT_ARCHIVE,
    EVENT_ARCHIVE_PROVENANCE,
    ORCHESTRATOR_SESSION_ID,
    QUICK_EDIT_SESSION_ID,
    SUBJECT_PART,
    stage4_goldens,
)

#: ``agent/src/session/history.ts``. Not a knob: §2.8 refuses a page-size
#: parameter, so "multi-page" is a property of the transcript's length.
HISTORY_PAGE_SIZE = 250


def archive() -> list[dict[str, Any]]:
    path = stage4_goldens() / EVENT_ARCHIVE
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def archived_for(session_id: str) -> list[dict[str, Any]]:
    return [row for row in archive() if row["session_id"] == session_id]


class Sidecar:
    """One bridge runtime over the fixture, resuming the committed sessions."""

    def __init__(self, project_root: Path, dist_main: Path) -> None:
        from hephaestus.agent_bridge.app import BridgeRuntime
        from hephaestus.testing.fake_openai import start_fake_openai

        self.fake = start_fake_openai([])
        self.runtime = BridgeRuntime(
            project_root=project_root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
        )
        self.runtime.start()

    def resume(self, session_id: str, profile: str, part: str | None = None) -> str:
        return self.runtime.create_session(profile, part=part, session_id=session_id, resume=True)

    def pages(self, session_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.runtime.history_page(session_id, cursor)
            out.append(page)
            if page.get("done") or page.get("cursor") is None:
                return out
            cursor = str(page["cursor"])

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()


def rows_from(pages: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    """The archive's own row shape, rebuilt from a live history read."""
    from hephaestus.http.event_identity import historical_event_id

    out: list[dict[str, Any]] = []
    for index, page in enumerate(pages):
        for event in page["events"]:
            row: dict[str, Any] = {
                "event_id": historical_event_id(session_id, int(event["seq"])),
                "session_id": session_id,
                "page": index,
                "seq": int(event["seq"]),
                "kind": event["kind"],
            }
            if "tool_call_id" in event:
                row["tool_call_id"] = event["tool_call_id"]
            if "payload" in event:
                row["payload"] = event["payload"]
            out.append(row)
    return out


@pytest.fixture
def sidecar(fixture_project: Path, sidecar_dist: Path) -> Iterator[Sidecar]:
    started = Sidecar(fixture_project, sidecar_dist)
    try:
        yield started
    finally:
        started.close()


# --------------------------------------------------------------------------


def test_the_committed_transcript_is_installed_and_resumable(
    fixture_project: Path, sidecar: Sidecar
) -> None:
    """The fixture's transcript reaches the sidecar as a resumable session.

    Materialization replays ``transcript/sessions/`` into ``.heph/sessions/``;
    without that, ``history.page`` has nothing to serve, because it reads the
    sessions the sidecar has **open** (``agent/src/main.ts``) and a session is
    opened by name only through ``resume``.
    """
    installed = sorted(p.name for p in (fixture_project / ".heph" / "sessions").iterdir())
    assert installed == sorted([ORCHESTRATOR_SESSION_ID, QUICK_EDIT_SESSION_ID])
    assert sidecar.resume(ORCHESTRATOR_SESSION_ID, "orchestrator") == ORCHESTRATOR_SESSION_ID


def test_the_transcript_is_multi_page_without_a_page_size_knob(sidecar: Sidecar) -> None:
    """G4.9: "multi-page" is a fact about the transcript, not about a parameter.

    §2.8 exposes no page size, so the only way for a page boundary to exist is a
    transcript longer than ``HISTORY_PAGE_SIZE``. The last page is the one that
    reports ``done``; every earlier page carries an opaque cursor.
    """
    sidecar.resume(ORCHESTRATOR_SESSION_ID, "orchestrator")
    pages = sidecar.pages(ORCHESTRATOR_SESSION_ID)
    assert len(pages) > 1, "the fixture transcript no longer pages; §14 requires >250 events"
    assert len(pages[0]["events"]) == HISTORY_PAGE_SIZE
    assert sum(len(page["events"]) for page in pages) > HISTORY_PAGE_SIZE
    assert pages[-1]["done"] is True
    assert all(page["done"] is False and page["cursor"] for page in pages[:-1])


def test_the_reopened_transcript_matches_the_archive_event_for_event(
    sidecar: Sidecar,
) -> None:
    """G4.11 over the **historical** namespace: ``<session_id>@<ordinal>``.

    Full normalized events, not only the identities: an archive of ids alone
    would pass while every payload changed underneath it.
    """
    for session_id, profile, part in (
        (ORCHESTRATOR_SESSION_ID, "orchestrator", None),
        (QUICK_EDIT_SESSION_ID, "quick_edit", SUBJECT_PART),
    ):
        sidecar.resume(session_id, profile, part)
        rebuilt = rows_from(sidecar.pages(session_id), session_id)
        assert rebuilt == archived_for(session_id), f"{session_id} drifted from the archive"


def test_the_archived_identities_survive_a_sidecar_restart(
    fixture_project: Path, sidecar_dist: Path
) -> None:
    """§2.8's stated reason for having an archive at all.

    Two sidecar processes, one after the other, over the same committed
    transcript. The identities are session-scoped and restart at 0, so a
    normalizer that started counting from anywhere else — or that skipped an
    entry kind on a cold read — would show up here and nowhere else.
    """
    reads: list[list[dict[str, Any]]] = []
    for _ in range(2):
        started = Sidecar(fixture_project, sidecar_dist)
        try:
            started.resume(ORCHESTRATOR_SESSION_ID, "orchestrator")
            reads.append(rows_from(started.pages(ORCHESTRATOR_SESSION_ID), ORCHESTRATOR_SESSION_ID))
        finally:
            started.close()
    assert reads[0] == reads[1]
    assert reads[0] == archived_for(ORCHESTRATOR_SESSION_ID)


def test_the_archive_is_only_the_historical_namespace(sidecar: Sidecar) -> None:
    """§2.8: the two identities are never merged, and this archive is one of them.

    Archiving ``(run_id, seq)`` would have archived identities a reopened panel
    never emits, so the assertion would have been vacuous or impossible depending
    on how it was written. Every archived id is historical, by its separator.
    """
    from hephaestus.http.event_identity import identity_surface

    assert {identity_surface(row["event_id"]) for row in archive()} == {"historical"}


def test_a_failed_tool_call_reopens_as_an_error_not_as_ok(sidecar: Sidecar) -> None:
    """§7.2 / §19 item 13: ``isError`` on a historical ``tool_result``.

    The recorded session contains an ``inspect_part`` on a part that had not been
    built. Before the normalizer carried ``isError``, a reopened chip for it read
    ``ok`` — the panel stating as fact that a failed call succeeded. The archive
    is baselined on the corrected shape, so this asserts the shape is still
    correct, in both directions: the failure is ``true`` and every other result is
    ``false``, never absent.

    The stale-hash ``edit_part`` in the same turn is deliberately **not** the
    failure: a CAS conflict is a discriminated *result* (§2.4 keeps it at 200,
    ``applied: false`` plus a conflict record), so the tool answered and
    ``isError`` is correctly ``false``. Asserting both in one test is what stops
    "any refusal is an error" from creeping into a chip.
    """
    results = [row for row in archive() if row["kind"] == "tool_result"]
    assert results, "the archive has no tool results at all"
    assert all("isError" in row["payload"] for row in results)
    failed = [row for row in results if row["payload"]["isError"] is True]
    assert len(failed) == 1
    assert "no current successful build" in failed[0]["payload"]["text"]
    conflicts = [row for row in results if '"applied":false' in row["payload"]["text"]]
    assert len(conflicts) == 1
    assert conflicts[0]["payload"]["isError"] is False


def test_the_archive_carries_an_image_as_metadata_only(sidecar: Sidecar) -> None:
    """§7.3: history retains ``{mimeType}``; the bytes are not recoverable.

    An honest limit, and the fixture exercises it rather than leaving the panel's
    placeholder branch untested.
    """
    images = [row for row in archive() if row["kind"] == "image"]
    assert len(images) == 1
    assert set(images[0]["payload"]) == {"mimeType"}


def test_the_provenance_sidecar_names_what_produced_the_archive() -> None:
    """The churn policy is written down beside the bytes, not only in a doc."""
    sidecar_path = stage4_goldens() / EVENT_ARCHIVE_PROVENANCE
    provenance = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert provenance["recorded_by"] == "scripts/record_workspace_transcript.py"
    assert "history.ts::normalizeEntries" in " ".join(provenance["normalizers"])
    assert provenance["sessions"][ORCHESTRATOR_SESSION_ID]["pages"] > 1
    counted = sum(len(archived_for(sid)) for sid in provenance["sessions"])
    assert counted == len(archive())


# --------------------------------------------------------------------------
# G4.10 — threading


def test_the_quick_edit_child_threads_to_its_parent(fixture_project: Path) -> None:
    """G4.10: the durable edge, read back through §2.8's projection.

    Deliberately **not** gated on an agent runtime: threading lives in
    ``state.db`` and is readable long after the runtime that wrote it, which is
    what makes a reopened project able to draw the tree at all.
    """
    from hephaestus.http.app import build_app
    from hephaestus.http.runtime import WorkspaceRuntime
    from starlette.testclient import TestClient

    runtime = WorkspaceRuntime.open(fixture_project, token="g4", serve_mode=True)
    client = TestClient(build_app(runtime))
    try:
        response = client.get(
            f"/api/v1/sessions/{ORCHESTRATOR_SESSION_ID}/thread",
            headers={"Authorization": "Bearer g4"},
        )
        assert response.status_code == 200, response.text
        document = response.json()
        # `linked` because the tree has a child, not because the root has a
        # parent: `thread_projection` reports `unlinked` only when a session has
        # neither, which is §2.8's honest state for a pre-edge-table transcript.
        assert document["thread_state"] == "linked"
        assert document["parent_session_id"] is None
        children = {node["session_id"]: node for node in document["nodes"]}
        assert set(children) == {ORCHESTRATOR_SESSION_ID, QUICK_EDIT_SESSION_ID}
        child = children[QUICK_EDIT_SESSION_ID]
        assert child["parent_session_id"] == ORCHESTRATOR_SESSION_ID
        assert child["kind"] == "quick_edit"
        assert child["depth"] == 1
        origin = child["origin"]
        assert origin["part"] == SUBJECT_PART
        assert origin["source_artifact_ref"].startswith("artifact:build:")
        assert isinstance(origin["selection_id"], int)
    finally:
        client.close()
        runtime.close()


def test_the_route_can_reopen_a_named_session(fixture_project: Path, sidecar_dist: Path) -> None:
    """The §2.3 deviation, asserted where it is used.

    ``POST /sessions`` accepts ``{session_id, resume}``. Without it a committed
    transcript is unreachable over HTTP and G4.11's session-scoped archive cannot
    be matched, because every session id would be a fresh UUID. ``resume``
    without a name is refused rather than silently ignored.
    """
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.http.app import build_app
    from hephaestus.http.runtime import WorkspaceRuntime
    from hephaestus.testing.fake_openai import start_fake_openai
    from starlette.testclient import TestClient

    runtime = WorkspaceRuntime.open(fixture_project, token="g4", serve_mode=True)
    fake = start_fake_openai([])
    bridge = BridgeRuntime(
        project_root=runtime.root,
        providers=[fake.provider_spec()],
        dist_main=sidecar_dist,
        store=runtime.store,
        project_store=runtime.project_store,
        cad=runtime.cad,
        dispatcher=runtime.dispatcher,
    )
    bridge.start()
    runtime.attach_sessions(bridge)
    client = TestClient(build_app(runtime))
    auth = {"Authorization": "Bearer g4"}
    try:
        opened = client.post(
            "/api/v1/sessions",
            json={
                "profile": "orchestrator",
                "session_id": ORCHESTRATOR_SESSION_ID,
                "resume": True,
            },
            headers=auth,
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["session_id"] == ORCHESTRATOR_SESSION_ID
        assert opened.json()["resumed"] is True

        history = client.get(f"/api/v1/sessions/{ORCHESTRATOR_SESSION_ID}/history", headers=auth)
        assert history.status_code == 200, history.text
        assert len(history.json()["events"]) == HISTORY_PAGE_SIZE

        refused = client.post(
            "/api/v1/sessions", json={"profile": "orchestrator", "resume": True}, headers=auth
        )
        assert refused.status_code == 400
        assert refused.json()["reason"] == "invalid_params"
    finally:
        client.close()
        if runtime.sessions is not None:
            runtime.sessions.close()
        bridge.close()
        runtime.close()
        fake.close()
