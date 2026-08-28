# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§14's parity lane: the same cases through HTTP and through dispatch.

``INTERFACE.md`` §14 and §2.5. G5.19 requires REST mutation idempotency tested
**independently of MCP-over-HTTP**, and §2.5 adds the REST replay shape to the
Stage 3 transport-parity suite "as a third lane". This file is that lane's
server-side half: the same **mutation / replay / conflict / paging** cases run
through the HTTP route and through :meth:`ToolDispatcher.dispatch`, and the
outcomes are asserted equal.

What "equal" means is the interesting part, and §2.5 pins it:

* **Mutation** — identical result documents. Both transports call one dispatcher
  over one core; a difference here would mean the route had grown a projection
  of its own.
* **Paging** — identical pages at every cursor, because both call one
  ``page_text``.
* **Conflict** — identical discriminated results. A CAS conflict is a *result*,
  at 200, on both transports.
* **Replay** — deliberately **not** identical, and this is the one place the
  lanes diverge on purpose. The bridge resolves a retry of a committed
  ``edit_part`` to ``conflict`` with the live hash, because the retrying
  principal is a *model* that must be told a hash it does not hold. REST replays
  the stored body byte-for-byte with ``"replayed": true``, because the retrying
  principal is the same operator client re-sending its own committed call.
  Handing it a conflict for its own success would be a lie, and would make a
  lost-response recovery indistinguishable from a genuine race. The test asserts
  **both** shapes, so the divergence is a decision on the record rather than a
  drift someone discovers later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hephaestus.testing.workspace import Workspace, uuid7, workspace


def _widget_hash(web: Workspace) -> str:
    return str(web.get("/parts/widget/script").json()["content_hash"])


# --------------------------------------------------------------------------
# reads and paging
# --------------------------------------------------------------------------


def test_read_parity_the_route_returns_the_dispatch_result_verbatim(
    tmp_path: Path,
) -> None:
    """Lane 1 vs lane 2 on a read: byte-equal documents."""
    with workspace(tmp_path / "proj") as web:
        route = web.get("/parts/widget/script").json()
        direct = web.dispatch("read_part", {"name": "widget"}, entry="parity-read")
    assert route == direct


def test_paging_parity_every_cursor_agrees(tmp_path: Path) -> None:
    """Lane 1 vs lane 2 across a whole paged read, cursor by cursor.

    The first page agreeing proves nothing; a boundary contract fails at the
    awkward offset, so the assertion walks the whole blob at a page size small
    enough to land mid-line repeatedly.
    """
    with workspace(tmp_path / "proj") as web:
        ref = next(
            p["snapshot_ref"] for p in web.get("/parts").json()["parts"] if p["name"] == "widget"
        )
        offset = 0
        while True:
            route = web.get(
                f"/artifacts/{ref}/text",
                params={"offset_bytes": str(offset), "max_bytes": "13"},
            ).json()
            direct = web.dispatch(
                "read_artifact",
                {"ref": ref, "offset_bytes": offset, "max_bytes": 13},
                entry=f"parity-page-{offset}",
            )
            assert {k: v for k, v in route.items() if k != "status"} == direct
            if not route["truncated"]:
                break
            offset = route["next_offset_bytes"]


# --------------------------------------------------------------------------
# mutation
# --------------------------------------------------------------------------


def test_mutation_parity_one_dispatcher_one_result(tmp_path: Path) -> None:
    """The same ``edit_part`` through both lanes produces the same document.

    Run on two separate projects so neither lane's write is the other's
    precondition — a sequential run would let the second see the first's result
    and agree for the wrong reason.
    """
    with workspace(tmp_path / "a") as via_http, workspace(tmp_path / "b") as via_dispatch:
        arguments: dict[str, Any] = {
            "name": "widget",
            "expected_hash": _widget_hash(via_http),
            "old_str": "20.0",
            "new_str": "22.0",
        }
        route = via_http.request(
            "PATCH",
            "/parts/widget/script",
            json={k: v for k, v in arguments.items() if k != "name"},
            key=uuid7(),
        )
        direct = via_dispatch.dispatch("edit_part", arguments, entry="parity-edit")

    assert route.status_code == 200, route.text
    body = route.json()
    # `path` is absolute and therefore project-specific; everything else is the
    # engine's answer and must match exactly.
    assert {k: v for k, v in body.items() if k != "path"} == {
        k: v for k, v in direct.items() if k != "path"
    }


def test_build_mutation_parity(tmp_path: Path) -> None:
    """The same for a build: identical results modulo the refs they mint.

    A build publishes content-addressed artifacts, so two independent projects
    with identical inputs mint identical refs — which makes this a stronger
    assertion than it looks, and would fail loudly if either lane injected a
    per-transport field.
    """
    with workspace(tmp_path / "a") as via_http, workspace(tmp_path / "b") as via_dispatch:
        route = via_http.post("/parts/widget/build", json={}, key=uuid7())
        direct = via_dispatch.dispatch("build_part", {"name": "widget"}, entry="parity-build")
    assert route.status_code == 200, route.text
    assert set(route.json()) == set(direct)
    assert route.json()["status"] == direct["status"] == "ok"
    assert route.json()["effective_params"] == direct["effective_params"]
    assert route.json()["artifact_ref"] == direct["artifact_ref"]


# --------------------------------------------------------------------------
# conflict
# --------------------------------------------------------------------------


def test_conflict_parity_a_stale_hash_is_the_same_discriminated_result(
    tmp_path: Path,
) -> None:
    """§2.4: a CAS conflict is a **result at 200** on both lanes, not an error.

    A 4xx on the HTTP lane would make the editor's merge prompt (G5.20)
    indistinguishable from a transport failure — and would break parity with a
    dispatcher that has always returned a document here.
    """
    stale = "sha256:" + "0" * 64
    with workspace(tmp_path / "a") as via_http, workspace(tmp_path / "b") as via_dispatch:
        route = via_http.request(
            "PATCH",
            "/parts/widget/script",
            json={"expected_hash": stale, "old_str": "20.0", "new_str": "22.0"},
            key=uuid7(),
        )
        direct = via_dispatch.dispatch(
            "edit_part",
            {"name": "widget", "expected_hash": stale, "old_str": "20.0", "new_str": "22.0"},
            entry="parity-conflict",
        )
    assert route.status_code == 200, route.text
    body = route.json()
    assert body["applied"] is False
    assert direct["applied"] is False
    assert body["conflict"] == direct["conflict"]
    assert body["conflict"]["current_hash"].startswith("sha256:")


def test_param_conflict_parity(tmp_path: Path) -> None:
    """The same for the param CAS: one discriminated ``conflict`` on both lanes."""
    stale = "sha256:" + "0" * 64
    with workspace(tmp_path / "a") as via_http, workspace(tmp_path / "b") as via_dispatch:
        route = via_http.post(
            "/parts/widget/params",
            json={"values": {"width": 45.0}, "expected_state_hash": stale},
            key=uuid7(),
        )
        direct = via_dispatch.dispatch(
            "set_params",
            {
                "scope": "part",
                "name": "widget",
                "values": {"width": 45.0},
                "expected_state_hash": stale,
            },
            entry="parity-param-conflict",
        )
    assert route.status_code == 200, route.text
    assert route.json()["conflict"] == direct["conflict"]


# --------------------------------------------------------------------------
# replay — where the lanes diverge, on purpose
# --------------------------------------------------------------------------


def test_replay_parity_rest_replays_the_body_while_the_bridge_reports_conflict(
    tmp_path: Path,
) -> None:
    """§2.5's third-transport shape, asserted **against** the bridge's.

    Same operation, same key-shaped retry, two deliberately different answers:

    * dispatch (the bridge lane) resolves a retry of a committed ``edit_part``
      to ``applied: false`` + the live ``current_hash``, because its CAS gate
      runs in front of an idempotency key owned by ``hephaestus.core`` and the
      retrying principal is a model that must be told a hash it does not hold;
    * REST replays the stored response **byte-for-byte** with ``"replayed":
      true`` and the ``Idempotency-Replayed`` header, because the retrying
      principal is the same operator client re-sending its own committed call.

    Neither duplicates work and neither discards bytes. The test exists so that
    the divergence stays a decision rather than becoming a surprise.
    """
    with workspace(tmp_path / "a") as via_http, workspace(tmp_path / "b") as via_dispatch:
        key = uuid7()
        edit = {"expected_hash": _widget_hash(via_http), "old_str": "20.0", "new_str": "23.0"}
        first = via_http.request("PATCH", "/parts/widget/script", json=edit, key=key)
        assert first.status_code == 200, first.text
        assert first.json()["applied"] is True
        replay = via_http.request("PATCH", "/parts/widget/script", json=edit, key=key)

        arguments = {"name": "widget", **{"expected_hash": _widget_hash(via_dispatch)}}
        arguments.update({"old_str": "20.0", "new_str": "23.0"})
        bridge_first = via_dispatch.dispatch("edit_part", arguments, entry="parity-replay")
        assert bridge_first["applied"] is True
        bridge_retry = via_dispatch.dispatch("edit_part", arguments, entry="parity-replay")

    # REST: the stored body, byte for byte, plus the two replay markers.
    #
    # COLLISION, recorded rather than hidden: `write_part`/`edit_part` results
    # already carry a `replayed` boolean of their own — the core WAL's answer to
    # "did this write re-execute". §2.5's normative envelope field has the same
    # name and, on a REST replay, the same truth value at a different layer:
    # neither the WAL nor the route did new work. So the marker overlays that
    # field, and the assertion below states exactly that — the ONLY difference
    # between the stored body and the replayed body is `replayed`.
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    stored, replayed_body = first.json(), replay.json()
    assert {k: v for k, v in replayed_body.items() if k != "replayed"} == {
        k: v for k, v in stored.items() if k != "replayed"
    }
    assert replayed_body["replayed"] is True
    assert stored["replayed"] is False

    # Bridge: the conflict shape with the live hash it wrote itself.
    assert bridge_retry["applied"] is False
    assert bridge_retry["conflict"]["current_hash"] == bridge_first["content_hash"]

    # …and the divergence is real, not an artefact of the fixture.
    assert replayed_body["applied"] is not bridge_retry["applied"]


def test_a_rest_replay_never_degrades_to_the_conflict_shape(tmp_path: Path) -> None:
    """Stated as its own assertion because it is the failure mode §2.5 names.

    A replay that carried ``conflict{current_hash}`` would be telling the client
    its own committed write had raced — making a lost-response recovery
    indistinguishable from a genuine conflict, which is exactly the distinction
    the REST shape exists to preserve.
    """
    with workspace(tmp_path / "proj") as web:
        key = uuid7()
        edit = {"expected_hash": _widget_hash(web), "old_str": "20.0", "new_str": "24.0"}
        assert web.request("PATCH", "/parts/widget/script", json=edit, key=key).status_code == 200
        replay = web.request("PATCH", "/parts/widget/script", json=edit, key=key).json()
    assert "conflict" not in replay
    assert replay["applied"] is True
    assert replay["replayed"] is True


def test_a_discriminated_conflict_result_replays_as_itself(tmp_path: Path) -> None:
    """§2.5: the two discriminated-result families are **unaffected** by the shape.

    Their discriminated result *is* the stored response, so a replay returns the
    conflict it originally returned — not a success, and not a second conflict
    computed fresh against a hash that has moved on.
    """
    stale = "sha256:" + "0" * 64
    with workspace(tmp_path / "proj") as web:
        key = uuid7()
        edit = {"expected_hash": stale, "old_str": "20.0", "new_str": "25.0"}
        first = web.request("PATCH", "/parts/widget/script", json=edit, key=key).json()
        assert first["applied"] is False
        replay = web.request("PATCH", "/parts/widget/script", json=edit, key=key).json()
    assert replay.pop("replayed") is True
    assert replay == first  # the conflict IS the stored response, replayed as such
