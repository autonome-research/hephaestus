# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The context envelope on the wire (``INTERFACE.md`` §7A.3, §7A.4; §19.20/§19.22/§19.26).

Three subjects, and each is here because it is decided on the **server**:

* **the envelope is validated, not believed** (§7A.3) — an unknown part, a
  malformed section plane, a member outside the closed set and a selection that
  does not resolve are all named refusals, and none of them degrades into a
  block that quietly says something else;
* **the request text is exactly what the operator typed** (§7A.4) — the block
  travels beside ``text`` and is never bound, so ``VALIDATION.md`` §4's
  ``prompt_number_diff`` still diffs the operator's own words. §7A.12's case 3
  is the second test in that section and it is pytest by the spec's own
  instruction: "it asserts on the ops layer, not the DOM";
* **``POST /sessions`` accepts two profiles, not three** (§7A.2, §19.26).

§7A.12's case 4 — two concurrent prompts, each critique seeing its own request —
lives in ``test_request_binding.py``, which is where §19.23's per-run binding is
tested and where the two-thread harness already exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import (
    bind_run_request_text,
    release_run_request_text,
    run_request_text,
)
from hephaestus.agent_bridge.dispatch import Principal
from hephaestus.http.context import (
    BLOCK_MAX_LINES,
    CONTEXT_SOURCE_ROUTES,
    ENVELOPE_MEMBERS,
    TRUNCATION_MARKER,
    ComposedContext,
    compose_context,
    parse_envelope,
)
from hephaestus.http.errors import HttpRefusal
from hephaestus.testing.tools_fixture import Project, make_project
from hephaestus.testing.workspace import Workspace, workspace

#: A number-rich envelope's worth of workspace state, and a prompt with **no**
#: numbers in it. §7A.12's case 3: "a prompt with no numbers plus a number-rich
#: envelope yields ``prompt_number_diff.numbers == []``".
NUMBERLESS_REQUEST = "make the widget wider than a hand span"


@pytest.fixture
def app(tmp_path: Path) -> Iterator[Workspace]:
    with workspace(tmp_path / "ws", agent=True) as ws:
        yield ws


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


def _built(app: Workspace) -> str:
    """Build the fixture's widget and return its artifact ref."""
    response = app.post("/parts/widget/build", json={}, key=_key())
    assert response.status_code == 200, response.text
    body = cast("dict[str, Any]", response.json())
    assert body["status"] == "ok", body
    return str(body["artifact_ref"])


def _key() -> str:
    from hephaestus.testing.workspace import uuid7

    return uuid7()


# --------------------------------------------------------------------------
# §7A.3 — the closed member set, and refusals that name themselves


def test_the_member_set_is_closed_and_an_extra_member_is_named(app: Workspace) -> None:
    """An unexpected member is refused, never silently dropped.

    A dropped member is the worse failure: the operator saw the chip row, took
    nothing out of it, and the model was told less than the workspace showed.
    The refusal names the offender **and** the admitted set, because a client
    cannot correct a vocabulary it is not shown.
    """
    response = app.post("/context/preview", json={"context": {"bbox_mm": [1, 2, 3]}})
    assert response.status_code == 400
    body = cast("dict[str, Any]", response.json())
    assert body["reason"] == "invalid_params"
    assert body["unexpected"] == ["bbox_mm"]
    assert set(body["admitted"]) == ENVELOPE_MEMBERS


def test_every_admitted_member_is_accepted(app: Workspace) -> None:
    """The closed set is a *contract*, so every name in it must be sendable.

    Asserted as a loop over :data:`ENVELOPE_MEMBERS` rather than as a
    hand-written body, so a member added to the constant without a parser branch
    fails here instead of at a browser.
    """
    ref = _built(app)
    envelope: dict[str, Any] = {
        "part": "widget",
        "artifact_ref": ref,
        "pin_mode": "pinned",
        "stage_tab": "viewport",
        "inspector_tab": "checks",
        "view": "iso",
        "explode_t": 0.5,
        "section_plane": "+Z@10",
        "hidden_labels": ["body"],
        "selection": None,
        "focus": "geometry:body",
    }
    assert set(envelope) == ENVELOPE_MEMBERS
    response = app.post("/context/preview", json={"context": envelope})
    assert response.status_code == 200, response.text


def test_an_unknown_part_is_refused_rather_than_repeated_into_the_block(app: Workspace) -> None:
    """§7A.3's "a lying client is caught, not believed"."""
    response = app.post("/context/preview", json={"context": {"part": "no_such_part"}})
    assert response.status_code == 404
    assert cast("dict[str, Any]", response.json())["reason"] == "unknown_part"


def test_a_ref_outside_this_project_is_refused_by_the_store(app: Workspace) -> None:
    """§2.2's project-scoped check, reached through the artifact projection.

    The block never names an artifact the open project does not hold: the
    refusal comes from the same ``artifact_meta`` the ``/meta`` route serves,
    not from a second reachability check written for this path.
    """
    foreign = "artifact:build:sha256:" + "0" * 64
    response = app.post("/context/preview", json={"context": {"artifact_ref": foreign}})
    assert response.status_code == 404
    assert cast("dict[str, Any]", response.json())["reason"] == "unknown_artifact"


def test_a_malformed_section_plane_is_invalid_params(app: Workspace) -> None:
    response = app.post("/context/preview", json={"context": {"section_plane": "sideways"}})
    assert response.status_code == 400
    assert cast("dict[str, Any]", response.json())["reason"] == "invalid_params"


def test_a_selection_that_does_not_resolve_is_stale_never_a_fallback(app: Workspace) -> None:
    """§15.3, applied to the prompt path.

    §7A.3: a selection that does not resolve is ``stale_selection`` — "**never**
    a fallback to current geometry, and never a prompt that quietly drops the
    selection it claimed to carry". The refusal is the assertion; a ``200`` with
    a block that simply omitted the selection would be the failure.
    """
    ref = _built(app)
    response = app.post(
        "/context/preview",
        json={
            "context": {
                "part": "widget",
                "artifact_ref": ref,
                "selection": {"selection_id": "7", "bundle_ref": ref},
            }
        },
    )
    assert response.status_code in (404, 409), response.text
    body = cast("dict[str, Any]", response.json())
    assert body["reason"] in {"stale_selection", "unknown_artifact"}


def test_the_route_takes_a_context_and_nothing_else(app: Workspace) -> None:
    response = app.post("/context/preview", json={"context": None, "text": "hello"})
    assert response.status_code == 400
    body = cast("dict[str, Any]", response.json())
    assert body["reason"] == "invalid_params"
    assert body["unexpected"] == ["text"]


def test_the_blank_canvas_composes_nothing(app: Workspace) -> None:
    for envelope in (None, {"stage_tab": "viewport"}):
        response = app.post("/context/preview", json={"context": envelope})
        assert response.status_code == 200, response.text
        body = cast("dict[str, Any]", response.json())
        assert body["block"] == ""
        assert body["truncated"] is False
        assert body["sources"] == []


def test_composition_is_deterministic_in_the_envelope_and_the_project(app: Workspace) -> None:
    """§7A.3: "deterministic in ``(references, project state)``".

    The golden family in ``tests/stage4`` is only meaningful if this holds; a
    block that differed between two calls on one unchanged project would make
    every golden a coin toss.
    """
    envelope = {"part": "widget", "inspector_tab": "checks", "hidden_labels": ["body"]}
    first = app.post("/context/preview", json={"context": envelope}).json()
    second = app.post("/context/preview", json={"context": envelope}).json()
    assert first == second


def test_sources_are_drawn_from_the_closed_route_list(app: Workspace) -> None:
    response = app.post("/context/preview", json={"context": {"part": "widget"}})
    body = cast("dict[str, Any]", response.json())
    for source in cast("list[str]", body["sources"]):
        # Each is one of the five templates with `{part}`/`{ref}` resolved.
        assert any(
            source == template.replace("{part}", "widget") or source == template
            for template in CONTEXT_SOURCE_ROUTES
        ), source


def test_truncation_is_marked_in_the_block_as_well_as_in_the_field() -> None:
    """§2.9's precedent, and the reason the marker is in the text.

    The model reads the block and cannot read the ``truncated`` field. A model
    told a partial workspace state is complete would reason from an absence it
    had no way to detect, so the cut says so where the model will see it.
    """
    from hephaestus.http.context import _bounded  # pyright: ignore[reportPrivateUsage]

    long_block = "".join(f"line {n}\n" for n in range(BLOCK_MAX_LINES + 50))
    composed: ComposedContext = _bounded(long_block, ())
    assert composed.truncated is True
    assert composed.block.endswith(TRUNCATION_MARKER + "\n")
    assert len(composed.block.splitlines()) == BLOCK_MAX_LINES + 1


def test_the_preview_is_not_gated_on_the_agent_runtime(tmp_path: Path) -> None:
    """A serve with no runtime can still say what the agent *would* be told.

    §7A.8 puts the disabled composer's explanation on the composer itself, and a
    disclosure that went dark exactly when the composer is disabled would be
    missing at the one moment the operator needs it. The ``503`` on the session
    route is what proves this serve has no runtime.
    """
    with workspace(tmp_path / "ws") as ws:  # note: no `agent=True`
        assert ws.get("/sessions").status_code == 503
        response = ws.post("/context/preview", json={"context": {"part": "widget"}})
        assert response.status_code == 200, response.text
        assert cast("dict[str, Any]", response.json())["block"] != ""


# --------------------------------------------------------------------------
# §7A.4 — the request text is exactly what the operator typed


def test_the_block_travels_beside_the_text_and_never_inside_it(app: Workspace) -> None:
    """§7A.4's invariant, asserted on the split rather than on the joined string.

    ``FakeAgent`` records ``(text, context)`` as the route passed them, so a
    caller that prepended the block would show up here as a ``text`` that is not
    byte-for-byte the operator's. That is the only shape of this assertion that
    can fail on the defect it is about.
    """
    _built(app)
    agent = app.agent
    assert agent is not None
    created = cast("dict[str, Any]", app.post("/sessions", json={"profile": "orchestrator"}).json())
    session_id = str(created["session_id"])

    response = app.post(
        f"/sessions/{session_id}/prompt",
        json={
            "text": NUMBERLESS_REQUEST,
            "context": {"part": "widget", "inspector_tab": "checks"},
        },
    )
    assert response.status_code == 200, response.text
    text, context = agent.prompts[-1]
    assert text == NUMBERLESS_REQUEST
    assert context is not None
    assert "## Part: widget" in context
    # And the block is echoed, so a client knows what was actually sent (§7A.3).
    body = cast("dict[str, Any]", response.json())
    assert cast("dict[str, Any]", body["context"])["block"] == context


def test_a_prompt_with_no_context_sends_none(app: Workspace) -> None:
    """The wire is byte-identical to a pre-§19.22 turn when there is no block."""
    agent = app.agent
    assert agent is not None
    created = cast("dict[str, Any]", app.post("/sessions", json={"profile": "orchestrator"}).json())
    session_id = str(created["session_id"])
    response = app.post(f"/sessions/{session_id}/prompt", json={"text": "hello"})
    assert response.status_code == 200, response.text
    assert agent.prompts[-1] == ("hello", None)
    assert cast("dict[str, Any]", response.json())["context"] is None


def test_an_envelopes_numbers_never_reach_the_request_diff(project: Project) -> None:
    """§7A.12 case 3, on the ops layer where §7A.4's argument actually lands.

    The failure this pins is specific and was argued rather than assumed: a
    context block carrying ``bbox 40 x 20 x 2 mm`` prepended to the prompt would
    put the build's **own extents** into "the request", and every one of them
    would come back ``matched: true`` against itself —
    ``prompt_number_diff``, the rung that exists to catch a design that does not
    meet its brief, would be measuring the workspace's own context block.

    So: bind a numberless request the way ``BridgeRuntime.prompt`` binds one,
    build, and assert the critique found no request numbers. A block full of
    numbers is composed alongside and is deliberately *not* bound — which is the
    whole of the invariant, stated as the difference between the two calls.
    """
    principal = Principal(session_id="sess-purity", profile="orchestrator", part=None)
    bind_run_request_text("run-purity", NUMBERLESS_REQUEST)
    try:
        # The binding is the request, and it is the operator's text alone.
        assert run_request_text("run-purity") == NUMBERLESS_REQUEST
        result = cast(
            "dict[str, Any]",
            project.call(
                "build_part", {"name": "widget"}, principal=principal, run_id="run-purity"
            ),
        )
        assert result["status"] == "ok", result.get("error")
        critique = cast("dict[str, Any]", result["critique"])
        diff = cast("dict[str, Any]", critique["prompt_number_diff"])
        assert diff["numbers"] == [], (
            "a number reached prompt_number_diff from something other than the "
            "operator's own words; §7A.4's invariant is broken"
        )
    finally:
        release_run_request_text("run-purity")


# --------------------------------------------------------------------------
# §7A.2 / §19.26 — POST /sessions accepts two profiles, not three


def test_quick_edit_is_refused_by_name_pointing_at_the_route_that_seeds_one(
    app: Workspace,
) -> None:
    """§7A.2's TIGHTENING.

    A bare create produces the profile's **restrictions** and none of its
    context: a scope the operator can feel but cannot see, and a
    ``parent_session_id`` that is nothing, so §2.8's edge is never written and
    the tab reopens ``unlinked``. The refusal therefore names the route that
    does create one rather than merely saying no.
    """
    response = app.post("/sessions", json={"profile": "quick_edit", "part": "widget"})
    assert response.status_code == 400
    body = cast("dict[str, Any]", response.json())
    assert body["reason"] == "invalid_params"
    assert body["route"] == "POST /parts/{part}/quick_edit"


def test_a_quick_edit_transcript_may_still_be_RESUMED_by_name(app: Workspace) -> None:
    """The narrowing, asserted so it cannot be widened back by accident.

    §14 makes a committed >250-event transcript a fixture requirement and
    G4.11's archive is keyed on ``(session_id, ordinal)``, so a persisted
    quick-edit transcript can only be read back by ``{session_id, resume: true}``
    — the deviation ``WorkspaceSessions.create`` already records. Refusing that
    too would make §14's own fixture unloadable, so §7A.2's refusal is scoped to
    the **create** path, which is the one it argues about ("a **bare**
    ``POST /sessions {profile:"quick_edit", part:"tread"}``").
    """
    response = app.post(
        "/sessions",
        json={
            "profile": "quick_edit",
            "part": "widget",
            "session_id": "sess-committed-quickedit",
            "resume": True,
        },
    )
    assert response.status_code == 200, response.text


def test_a_part_session_must_name_its_part(app: Workspace) -> None:
    """Unvalidated, this bound a part-profile session to ``None``.

    Every object-scoped call then fails ``scope_denied`` against that binding —
    a refusal the operator reads as a broken product rather than as a scope.
    """
    response = app.post("/sessions", json={"profile": "part"})
    assert response.status_code == 400
    assert cast("dict[str, Any]", response.json())["reason"] == "invalid_params"


def test_the_session_list_projects_what_each_profile_can_do(app: Workspace) -> None:
    """§7A.2: "the profile is never chosen silently … from a server projection".

    The booleans are read off ``agent_bridge/sessions.py::_SPECS``, the same
    table ``ToolDispatcher._authorize`` enforces, so a client that renders them
    is not keeping a copy of §7A.2's table — which is what the section forbids,
    because "a user who does not know their session cannot delegate reads
    ``scope_denied`` as a broken product".
    """
    body = cast("dict[str, Any]", app.get("/sessions").json())
    rows = {row["profile"]: row for row in cast("list[dict[str, Any]]", body["profiles"])}
    assert set(rows) == {"orchestrator", "part"}, "quick_edit is not creatable here (§7A.2)"
    assert rows["orchestrator"]["can_delegate"] is True
    assert rows["orchestrator"]["part_scoped"] is False
    assert rows["part"]["can_delegate"] is False
    assert rows["part"]["part_scoped"] is True


def test_an_envelope_parses_to_references_and_nothing_else() -> None:
    """The parser's own contract, without a project.

    Every field on :class:`ContextEnvelope` is a reference or a closed-vocabulary
    token; there is nowhere in it to put a number the client computed. Asserted
    on the parsed object so a member added to the wire without a field here is
    visible as a refusal rather than as a silent drop.
    """
    envelope = parse_envelope({"part": "widget", "explode_t": 0.25, "hidden_labels": ["a"]})
    assert envelope.part == "widget"
    assert envelope.explode_t == 0.25
    assert envelope.hidden_labels == ("a",)
    # `HttpRefusal` and not a bare `Exception`: the refusal's identity is the
    # assertion — an envelope refused as something else would be a member that
    # blew up rather than one the vocabulary closed against.
    with pytest.raises(HttpRefusal):
        parse_envelope({"explode_t": 4})
    with pytest.raises(HttpRefusal):
        parse_envelope({"pin_mode": "sticky"})
    with pytest.raises(HttpRefusal):
        parse_envelope([])


def test_compose_context_is_reachable_without_a_route(app: Workspace) -> None:
    """The function §19.19 names, called directly — the goldens' own entry point."""
    composed = compose_context(app.runtime, parse_envelope({"part": "widget"}))
    assert composed.block.startswith("# Workspace context")
    assert composed.truncated is False
