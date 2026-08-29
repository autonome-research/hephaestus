# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The composer's context block, goldened (``INTERFACE.md`` §7A.3, §19.19).

§7A.3 asks for exactly this and says why: ``compose_context``'s output is
"deterministic in ``(references, project state)`` … and goldened at
``tests/stage4/goldens/context/<case>.txt`` **so a change to what the agent is
told is a diff in a review rather than a change nobody can see**".

That is the whole argument for the file family. The block is the one artefact in
this system that reaches a model's context window without any human reading it
first, so the review surface has to be a committed text file rather than an
assertion about a substring.

**Not renderer-pinned**, unlike its neighbour ``test_g4_section_golden.py``: the
block is composed from the build record, the metadata projection and the check
report, none of which touches a rasterizer. It runs on every PR.

The three cases are the three shapes §7A.3 distinguishes:

* **the blank canvas** — an envelope naming no reference composes *nothing*, and
  that is normative, not an optimization ("``context: null`` is the blank canvas
  and the server composes nothing");
* **a part alone** — the plainest non-empty envelope;
* **the pinned workspace** — §7A.12's case 2: pin A, the part, the Checks tab,
  a hidden geometry label, an explode parameter and a section plane. It is the
  case that proves the two honesty limits §7A.3 names: the block reports the
  hidden **toggle** and never what is visible, and it carries the explode
  **parameter** and never a displacement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hephaestus.testing.workspace_fixture import (
    CONTEXT_GOLDEN_CASES as CASES,
)
from hephaestus.testing.workspace_fixture import (
    CONTEXT_GOLDEN_DIR,
    resolve_context_case,
    stage4_goldens,
)


def goldens_dir() -> Path:
    return stage4_goldens() / CONTEXT_GOLDEN_DIR


def _preview(workspace: Any, envelope: dict[str, Any] | None) -> dict[str, Any]:
    """``POST /context/preview`` — the route the composer's disclosure renders.

    Asserted through the **route**, not through ``compose_context`` directly,
    because §7A.3's promise is about what the disclosure shows and what the
    prompt then sends. A golden taken from the function alone could stay green
    while the route stopped calling it.
    """
    response = workspace.client.post(
        "/api/v1/context/preview",
        json={"context": envelope},
        headers=workspace.headers,
    )
    response.raise_for_status()
    return dict(response.json())


@pytest.mark.parametrize("name,envelope", CASES, ids=[case[0] for case in CASES])
def test_the_composed_block_reproduces_its_committed_golden(
    workspace: Any, name: str, envelope: dict[str, Any]
) -> None:
    """The block, byte for byte, against ``goldens/context/<case>.txt``."""
    build_ref = str(workspace.get("/parts/tread/build")["artifact_ref"])
    body = _preview(workspace, resolve_context_case(envelope, build_ref))
    golden = goldens_dir() / f"{name}.txt"
    assert golden.exists(), (
        f"no committed golden for context case {name!r}. Re-baseline with "
        "`uv run python scripts/rebaseline_context_goldens.py` and READ the diff: "
        "this file is what the agent is told."
    )
    assert body["block"] == golden.read_text(encoding="utf-8"), (
        f"the composed context block for {name!r} differs from its golden. "
        "This is a change to what the agent is told about the operator's "
        "workspace; review the diff rather than re-baselining past it."
    )
    assert body["truncated"] is False


def test_the_blank_canvas_composes_nothing(workspace: Any) -> None:
    """§7A.3, normatively: an envelope naming no reference composes nothing.

    Both spellings are the blank canvas and both must produce the same empty
    block — ``context: null`` (the operator started a session with nothing
    open) and an envelope carrying only navigation tokens (they have a tab
    selected but no part, no pin and no selection). A server that composed a
    paragraph about tab positions for the second would be telling the model
    about the UI instead of about the project.
    """
    for envelope in (None, {"stage_tab": "viewport", "inspector_tab": "results"}):
        body = _preview(workspace, envelope)
        assert body["block"] == ""
        assert body["truncated"] is False
        assert body["sources"] == []


def test_the_preview_names_the_reads_it_answered_from(workspace: Any) -> None:
    """``sources`` is §7A.3's "reads only through the existing projections".

    The list is the resolved subset of
    :data:`hephaestus.http.context.CONTEXT_SOURCE_ROUTES`, in that fixed order,
    so a reviewer can see that a block naming a check verdict got it from the
    check report rather than from somewhere new. It is asserted as an exact list
    rather than by containment: a block composed from a *sixth* read would be
    the failure this field exists to make visible.
    """
    body = _preview(workspace, {"part": "tread"})
    assert body["sources"] == [
        "/parts/tread/build",
        "/parts/tread/properties",
        "/parts/tread/checks",
        "/parts/tread/dfm",
    ]


def test_the_preview_starts_no_run_and_calls_no_tool(workspace: Any) -> None:
    """§7A.3's one-line definition of this route, asserted rather than trusted.

    The fixture's serve has no agent runtime attached, so every session route
    refuses ``503 agent_unavailable``. The preview answering ``200`` on that same
    serve *is* the proof that it opened no session and started no run — and it
    is also the state the disabled composer needs, because a disclosure gated on
    the runtime would be unavailable exactly when the operator is trying to
    understand why the composer is disabled.
    """
    sessions = workspace.client.get("/api/v1/sessions", headers=workspace.headers)
    assert sessions.status_code == 503
    assert sessions.json()["reason"] == "agent_unavailable"

    body = _preview(workspace, {"part": "tread"})
    assert body["status"] == "ok"
    assert body["block"] != ""


def test_an_envelope_member_outside_the_closed_set_is_refused_by_name(workspace: Any) -> None:
    """The closed member set (§7A.3), refused rather than ignored.

    A silently dropped member is worse than a refusal: the operator saw the chip
    row, dropped nothing, and the model was never told. The refusal names the
    offending member **and** the admitted set, because a client cannot correct a
    vocabulary it is not shown.
    """
    response = workspace.client.post(
        "/api/v1/context/preview",
        json={"context": {"part": "tread", "bbox_mm": [250, 156, 5.5]}},
        headers=workspace.headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["reason"] == "invalid_params"
    # §2.4 spreads a refusal's `data` flat into the envelope beside
    # `reason`/`message`; there is no nested `data` object.
    assert body["unexpected"] == ["bbox_mm"]
    assert "part" in body["admitted"]


def test_a_part_this_project_does_not_have_is_refused_not_repeated(workspace: Any) -> None:
    """§7A.3's "a lying client is caught, not believed"."""
    response = workspace.client.post(
        "/api/v1/context/preview",
        json={"context": {"part": "no_such_part"}},
        headers=workspace.headers,
    )
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_part"


def test_the_block_names_the_hidden_toggle_and_never_what_is_visible(workspace: Any) -> None:
    """§7A.3's named honesty limit, asserted as words in the block.

    "The composed block therefore says *the operator has hidden the geometry
    labelled ``cleat_left``* and **never** *the operator can see 2 solids*.
    Camera framing and occlusion are not knowable server-side, not knowable
    client-side without computing over geometry, and are claimed by neither."

    The negative half is the half worth pinning: a later edit that helpfully
    added "2 of 3 solids visible" would be the client's screen described by a
    server that cannot see it.
    """
    body = _preview(workspace, {"part": "tread", "hidden_labels": ["cleat_left"]})
    block = body["block"]
    assert "has hidden the geometry labelled cleat_left" in block
    for forbidden in ("visible", "on screen", "can see"):
        assert forbidden not in block.lower().replace("visibility toggles", "")


def test_the_block_carries_the_explode_parameter_and_never_a_displacement(
    workspace: Any,
) -> None:
    """§7A.3: ``explode_t`` is a parameter, not a distance.

    The GLTF ships each solid's ``explode_offset`` and the client applies
    ``offset · t``. The block carries ``t``; a block that said how far anything
    moved would be the server restating a number it did not measure, computed in
    a scene graph it cannot see.
    """
    body = _preview(workspace, {"part": "tread", "explode_t": 0.5})
    block = body["block"]
    assert "exploded-view parameter t: 0.5 (0 is assembled)" in block
    assert "mm" not in block.split("## Viewport", 1)[1]
