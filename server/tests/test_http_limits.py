# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""J-http-limits-1, -2, -4, -6, -7 — the request-side and refusal-side ceilings.

``INTERFACE.md`` §2.4/§2.5/§7A.4. Four related bounds:

* **J-http-limits-1** — a POST body is refused past a transport ceiling
  *before it is buffered*, and the prompt route's ``text`` is refused past its
  own, smaller, declared cap. Both numbers come from
  ``schemas/bridge_limits.json`` (``http.max_request_bytes``,
  ``prompt.max_utf8_bytes``); neither is a literal in the server.
* **J-http-limits-2** — a refusal body is bounded: a client string
  interpolated into both the message and the machine payload must not turn a
  16 MiB input into a 33 MB response.
* **J-http-limits-4** — a turn's own event list is bounded by the same key
  the live socket path already uses, in **both** places it accumulated: the
  bridge's per-run buffer in the serving process (the half that matters for a
  long orchestrator run) and the list returned from
  ``POST /sessions/{id}/prompt`` for a client with no socket. Overflow is
  reported by name, there is an ``include_events`` opt-out, and the WebSocket
  path is untouched. Its two layers are tested together here, in the file named
  for the item, rather than split across the layer boundary they compose over.
* **J-http-limits-6/-7** — the git subprocess and the capability probe (both
  request-path work that used to run inline) no longer block unrelated
  requests; this file adds the cross-route concurrency assertion the ledger
  says pins the two items together (the per-subprocess and per-probe unit
  tests live in ``test_git_projection.py``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.http import app as app_module
from hephaestus.testing.workspace import workspace

# --------------------------------------------------------------------------
# J-http-limits-1 — a body refused before it is buffered


def test_a_body_over_the_ceiling_with_a_declared_length_is_413_before_buffering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Content-Length`` above the cap refuses without a byte read.

    The ceiling is monkeypatched down to a small number so the test does not
    have to actually construct (and transmit) tens of megabytes to prove the
    point.
    """
    monkeypatch.setattr(app_module, "REQUEST_MAX_BYTES", 1000)
    with workspace(tmp_path / "proj") as web:
        oversized = b"x" * 2000
        response = web.client.request(
            "POST",
            "/api/v1/context/preview",
            content=oversized,
            headers={
                "Authorization": f"Bearer {web.runtime.token}",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 413, response.text
    body = response.json()
    assert body["reason"] == "request_too_large"
    assert body["max_bytes"] == 1000


def test_a_body_one_byte_under_the_ceiling_is_not_refused_for_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the boundary: under the cap, size is not the refusal."""
    monkeypatch.setattr(app_module, "REQUEST_MAX_BYTES", 1000)
    with workspace(tmp_path / "proj") as web:
        # A well-formed, small body that stays under the (patched) ceiling.
        response = web.post("/context/preview", json={"context": None})
    assert response.status_code == 200, response.text


def test_a_chunked_body_with_no_declared_length_is_still_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``Content-Length`` cannot evade the cap: the stream itself is bounded.

    ``httpx``'s test transport does not chunk on the wire the way a real
    client would, so this exercises the guarantee through the same code path
    with a generator body and no length header — the shape the ceiling's
    second rung exists for.
    """
    monkeypatch.setattr(app_module, "REQUEST_MAX_BYTES", 1000)

    def body() -> Any:
        for _ in range(20):
            yield b"x" * 200  # 4000 bytes total, well past the 1000-byte cap

    with workspace(tmp_path / "proj") as web:
        response = web.client.request(
            "POST",
            "/api/v1/context/preview",
            content=body(),
            headers={
                "Authorization": f"Bearer {web.runtime.token}",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 413, response.text
    assert response.json()["reason"] == "request_too_large"


def test_a_prompt_text_at_the_cap_succeeds_and_one_byte_over_is_refused(
    tmp_path: Path,
) -> None:
    """§7A.4's own, smaller cap: the prompt route's ``text``, not the transport."""
    from hephaestus.agent_bridge.limits import PROMPT_MAX_UTF8_BYTES

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")

        at_cap = "a" * PROMPT_MAX_UTF8_BYTES
        expected = agent.session_model(session)["model_state"]["revision"]
        ok = web.post(
            f"/sessions/{session}/prompt",
            json={"text": at_cap, "expected_model_revision": expected},
        )
        assert ok.status_code == 200, ok.text

        over_cap = "a" * (PROMPT_MAX_UTF8_BYTES + 1)
        refused = web.post(
            f"/sessions/{session}/prompt",
            json={"text": over_cap, "expected_model_revision": expected},
        )
    assert refused.status_code == 400, refused.text
    body = refused.json()
    assert body["reason"] == "prompt_too_large"
    # And no prompt was recorded by the fake agent for the refused text.
    assert over_cap not in [text for text, _ctx in agent.prompts]


def test_the_prompt_cap_is_measured_in_utf8_bytes_not_characters(tmp_path: Path) -> None:
    """An astral-plane prompt lands on the side of the boundary its *bytes* put it.

    The ledger asks for this case by name because the two plausible measures
    disagree by a factor of four here: ``U+1D54F`` is one character and four
    UTF-8 bytes, so a character count would admit a prompt four times the size
    the sidecar is willing to carry. The enforcer is the bridge's own, so both
    surfaces cut the same string in the same place.
    """
    from hephaestus.agent_bridge.limits import PROMPT_MAX_UTF8_BYTES

    astral = "\U0001d54f"  # MATHEMATICAL DOUBLE-STRUCK CAPITAL X — 4 UTF-8 bytes
    assert len(astral.encode("utf-8")) == 4
    at_cap = astral * (PROMPT_MAX_UTF8_BYTES // 4)
    assert len(at_cap.encode("utf-8")) == PROMPT_MAX_UTF8_BYTES
    assert len(at_cap) < PROMPT_MAX_UTF8_BYTES, "a character count would not be the same test"

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        expected = agent.session_model(session)["model_state"]["revision"]
        ok = web.post(
            f"/sessions/{session}/prompt",
            json={"text": at_cap, "expected_model_revision": expected},
        )
        assert ok.status_code == 200, ok.text
        over = web.post(
            f"/sessions/{session}/prompt",
            json={"text": at_cap + astral, "expected_model_revision": expected},
        )

    assert over.status_code == 400, over.text
    assert over.json()["reason"] == "prompt_too_large"


def test_the_request_ceiling_is_the_shared_limits_document_s_own_key() -> None:
    """The ceiling is ``http.max_request_bytes``, not a literal and not the frame cap.

    The ledger's fix is explicit that this number must be sourced from
    ``schemas/bridge_limits.json`` "so neither becomes a seventh un-sourced
    literal". For one round it read ``wire.max_frame_bytes`` instead, which is a
    different number for a different job: 64 MiB is what the **bridge
    transport** may carry between two trusted processes, and reading it here
    left the ledger's own reproduction — a 64 MiB body of unknown 1 MiB members
    — buffered in full before anything looked at it.
    """
    import inspect

    from hephaestus.agent_bridge.limits import (
        LIMITS,
        MAX_FRAME_BYTES,
        MAX_REQUEST_BYTES,
        PROMPT_MAX_UTF8_BYTES,
    )

    assert app_module.REQUEST_MAX_BYTES == MAX_REQUEST_BYTES
    assert LIMITS["http"]["max_request_bytes"] == MAX_REQUEST_BYTES
    # Small, as the ledger argues: well under the frame ceiling, and above the
    # prompt cap with room for the largest legitimate body (a part script).
    assert MAX_REQUEST_BYTES < MAX_FRAME_BYTES // 16
    assert MAX_REQUEST_BYTES > PROMPT_MAX_UTF8_BYTES
    # And nowhere written down twice: neither value appears as a literal in the
    # module that enforces it.
    source = inspect.getsource(app_module)
    assert str(MAX_REQUEST_BYTES) not in source
    assert str(MAX_FRAME_BYTES) not in source


def test_a_body_at_the_real_ceiling_is_admitted_and_one_byte_over_is_413(
    tmp_path: Path,
) -> None:
    """The boundary at the **shipped** number, not a patched one.

    Both sides over the wire, with a declared length. At the cap the refusal is
    the route's own (an unadmitted member) — proving size was not the reason;
    one byte over it is 413 ``request_too_large`` naming the ceiling and the
    exact observed size.
    """
    cap = app_module.REQUEST_MAX_BYTES

    def body_of(total: int) -> bytes:
        head, tail = b'{"padding":"', b'"}'
        return head + b"x" * (total - len(head) - len(tail)) + tail

    with workspace(tmp_path / "proj") as web:
        headers = {
            "Authorization": f"Bearer {web.runtime.token}",
            "Content-Type": "application/json",
        }
        at_cap = web.client.request(
            "POST", "/api/v1/context/preview", content=body_of(cap), headers=headers
        )
        over_cap = web.client.request(
            "POST", "/api/v1/context/preview", content=body_of(cap + 1), headers=headers
        )

    assert at_cap.status_code == 400, at_cap.text
    assert at_cap.json()["reason"] == "invalid_params", (
        "a body AT the ceiling must be refused by the route, not by the ceiling"
    )
    assert over_cap.status_code == 413, over_cap.text
    refused = over_cap.json()
    assert refused["reason"] == "request_too_large"
    assert refused["max_bytes"] == cap
    assert refused["observed_bytes"] == cap + 1


def test_an_oversized_stream_is_abandoned_instead_of_being_read_to_the_end() -> None:
    """ "Refused **before it is buffered**" is the property, so count the bytes.

    Driven against ``_read_body`` itself with a stream that records what it was
    asked for, because the in-process ``TestClient`` materialises a request body
    before the app ever runs — a wire-level test can prove the 413 (the case
    above does) but cannot see whether the *server* stopped reading. A body
    shaped like the ledger's reproduction — many megabytes of members the route
    never admits, with no declared length — must cost this process a bounded
    read, not the sender's whole payload.
    """
    import asyncio
    from typing import ClassVar, cast

    from hephaestus.http.errors import HttpRefusal

    cap = app_module.REQUEST_MAX_BYTES
    chunk = 64 * 1024
    yielded = 0

    class _Stream:
        """A chunked body with no ``Content-Length``, eight times the ceiling."""

        headers: ClassVar[dict[str, str]] = {}

        def stream(self) -> Any:
            async def chunks() -> Any:
                nonlocal yielded
                for _ in range((cap * 8) // chunk):
                    yielded += chunk
                    yield b"x" * chunk

            return chunks()

    with pytest.raises(HttpRefusal) as raised:
        asyncio.run(app_module._read_body(cast("Any", _Stream())))  # pyright: ignore[reportPrivateUsage]

    assert raised.value.reason == "request_too_large"
    assert raised.value.data["observed_bytes_at_least"] > cap
    assert yielded <= cap + chunk, (
        f"the reader consumed {yielded} bytes of an 8x-oversized body: it is "
        "buffering past the ceiling instead of aborting at it"
    )


# --------------------------------------------------------------------------
# J-http-limits-2 — refusal bodies are bounded, not amplified


def test_a_refusal_naming_an_oversized_value_is_bounded_not_amplified(
    tmp_path: Path,
) -> None:
    """A context preview naming a very large part must not return a
    proportionally large refusal — the exact amplifier the ledger measured
    (a ratio of 2.00 from one string written into both the message and the
    payload).
    """
    huge_name = "n" * 200_000
    with workspace(tmp_path / "proj") as web:
        response = web.post("/context/preview", json={"context": {"part": huge_name}})
    assert response.status_code in (400, 404), response.text
    assert len(response.content) < 10_000, (
        f"refusal body is {len(response.content)} bytes for a {len(huge_name)}-byte input"
    )


def test_a_short_refusal_value_is_unaffected_by_the_bound(tmp_path: Path) -> None:
    """The positive case: an ordinary-sized value is not touched by clipping."""
    with workspace(tmp_path / "proj") as web:
        response = web.post("/context/preview", json={"context": {"part": "no_such_part"}})
    assert response.status_code == 404
    assert response.json().get("part") == "no_such_part"


def test_an_oversized_artifact_ref_is_refused_at_the_door_by_its_own_grammar(
    tmp_path: Path,
) -> None:
    """J-http-limits-2's second half: "validate at the door".

    Clipping the reply closes the amplifier; it does not stop a value that
    *cannot* be a ref from reaching a store lookup that then quotes it back.
    Both envelope members that carry a ref are checked against the store's own
    grammar before anything is looked up, and the refusal names WHICH member —
    an envelope carries two, and a refusal that does not say which is not
    actionable.
    """
    huge = "z" * 200_000
    with workspace(tmp_path / "proj") as web:
        by_ref = web.post("/context/preview", json={"context": {"artifact_ref": huge}})
        by_selection = web.post(
            "/context/preview",
            json={"context": {"selection": {"selection_id": "s1", "bundle_ref": huge}}},
        )
    for response, field in ((by_ref, "artifact_ref"), (by_selection, "selection.bundle_ref")):
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["reason"] == "invalid_ref"
        assert body["field"] == field
        assert len(response.content) < 10_000


def test_a_well_formed_but_unknown_artifact_ref_is_still_the_store_s_answer(
    tmp_path: Path,
) -> None:
    """The door check is a GRAMMAR check and nothing more: a ref that is
    well formed and simply absent must still reach the store and come back
    with the artifact route's own reason, not a parser's.
    """
    ref = "artifact:blob:sha256:" + "0" * 64
    with workspace(tmp_path / "proj") as web:
        response = web.post("/context/preview", json={"context": {"artifact_ref": ref}})
    assert response.status_code == 404, response.text
    assert response.json()["reason"] == "unknown_artifact"


def test_a_structural_limit_refusal_takes_its_status_from_the_shared_table(
    tmp_path: Path,
) -> None:
    """J-http-envelope-18: the body reader's ``LimitError`` wrap is one wrap for
    five reasons, so its status must be the table's rather than a literal.

    Asserted through the wire because that is where the divergence would show:
    the reason is computed (``exc.code``), so the AST guard in
    ``test_http_errors.py`` cannot see this site at all.
    """
    from hephaestus.agent_bridge.limits import MAX_JSON_DEPTH
    from hephaestus.http.errors import status_for_reason

    nested: Any = "leaf"
    for _ in range(MAX_JSON_DEPTH + 4):
        nested = [nested]
    with workspace(tmp_path / "proj") as web:
        response = web.post("/context/preview", json={"context": {"hidden_labels": nested}})
    body = response.json()
    assert body["reason"] == "json_too_deep", body
    assert response.status_code == status_for_reason("json_too_deep") == 400


# --------------------------------------------------------------------------
# J-http-limits-4 — a turn's events are bounded, with an opt-out


def test_the_prompt_response_carries_a_bounded_tail_with_a_truncation_flag(
    tmp_path: Path,
) -> None:
    """A long tool-heavy run's event list is capped at the same bound the live
    socket already uses, and the response says so — asserted at the model
    layer directly (``WorkspaceSessions``), which is where the bound lives,
    rather than reconstructing a run long enough to trigger it over HTTP.
    """
    from hephaestus.http.sessions import LIVE_BUFFER_MAX

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        run_id = "run-many-events"
        agent._run_sessions[run_id] = session  # pyright: ignore[reportPrivateUsage]

        def script(a: Any, sid: str, run: str, text: str, answerer: Any) -> None:
            for i in range(LIVE_BUFFER_MAX + 50):
                a.emit(run, i, "text_delta", payload={"text": "x"})

        agent.on_prompt = script
        response = web.post(
            f"/sessions/{session}/prompt",
            json={
                "text": "go",
                "run_id": run_id,
                "expected_model_revision": agent.session_model(session)["model_state"]["revision"],
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["events"]) == LIVE_BUFFER_MAX, (
        f"the response carried {len(body['events'])} events against a bound of {LIVE_BUFFER_MAX}"
    )
    assert body.get("events_truncated") is True, (
        "an overflowing turn must say so, not just silently cap"
    )
    assert body.get("events_dropped", 0) == 50


def test_include_events_false_returns_an_empty_list_with_status_intact(
    tmp_path: Path,
) -> None:
    """The opt-out: a client already holding the socket can decline the tail."""
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        response = web.post(
            f"/sessions/{session}/prompt",
            json={
                "text": "go",
                "include_events": False,
                "expected_model_revision": agent.session_model(session)["model_state"]["revision"],
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["events"] == []
    assert body["run_status"] == "completed"


def test_the_run_s_own_event_buffer_is_bounded_and_drops_from_the_front() -> None:
    """The memory half: the bridge's per-run buffer, not just the response.

    ``_Run.events`` was a plain list for the life of a turn, so a long
    tool-heavy orchestrator run accumulated every event it ever emitted **in the
    serving process** — the half the ledger names as mattering — while the live
    socket path had a bound, coalescing and a backpressure cancel from the same
    key. This asserts the bound, the drop count, and **which end survives**:
    the tail, because the one consumer is a prompt caller reading a turn that
    has just ended; a reader who needs the run's opening reads durable history.
    """
    from hephaestus.agent_bridge.app import _Run  # pyright: ignore[reportPrivateUsage]
    from hephaestus.agent_bridge.events import BUFFERED_EVENTS_MAX

    run = _Run(run_id="r", session_id="s")
    overflow = 7
    for seq in range(BUFFERED_EVENTS_MAX + overflow):
        run.record({"kind": "text_delta", "seq": seq})

    assert len(run.events) == BUFFERED_EVENTS_MAX
    assert run.events_dropped == overflow
    # Oldest-first eviction, stated: the opening is gone, the end is intact.
    assert run.events[0]["seq"] == overflow
    assert run.events[-1]["seq"] == BUFFERED_EVENTS_MAX + overflow - 1
    # And a run under the bound is untouched — every turn in the tree.
    short = _Run(run_id="r2", session_id="s")
    short.record({"kind": "text_delta", "seq": 0})
    assert list(short.events) == [{"kind": "text_delta", "seq": 0}] and not short.events_dropped


def test_the_socket_path_still_receives_the_events_the_run_buffer_drops() -> None:
    """The bound must not cost the live surface anything.

    ``_on_notification`` hands each event to the pump — which owns the socket's
    own bounded queues, its coalescing and its backpressure cancel — *before*
    the per-run buffer sees it. Driven through the real notification sink with
    the two collaborators it touches, so the ordering is asserted rather than
    read.
    """
    import threading
    from typing import cast

    from hephaestus.agent_bridge.app import (
        BridgeRuntime,
        _Run,  # pyright: ignore[reportPrivateUsage]
    )
    from hephaestus.agent_bridge.events import BUFFERED_EVENTS_MAX

    run = _Run(run_id="r", session_id="s")

    class _Sink:
        """Exactly the attributes ``_on_notification`` reaches for."""

        def __init__(self) -> None:
            self._pump = self
            self._lock = threading.Lock()
            self._runs = {run.run_id: run}
            self.delivered: list[dict[str, Any]] = []

        def on_notification(self, method: str, params: dict[str, Any]) -> None:
            self.delivered.append(params)

        def _on_event(self, params: dict[str, Any]) -> None:
            BridgeRuntime._on_event(cast("Any", self), params)  # pyright: ignore[reportPrivateUsage]

    sink = _Sink()
    emitted = BUFFERED_EVENTS_MAX + 7
    for seq in range(emitted):
        BridgeRuntime._on_notification(  # pyright: ignore[reportPrivateUsage]
            cast("Any", sink), "event", {"run_id": "r", "kind": "text_delta", "seq": seq}
        )

    assert len(sink.delivered) == emitted, (
        "the pump — and so every socket client — must see every event, including "
        "the ones the request-response buffer drops"
    )
    assert len(run.events) == BUFFERED_EVENTS_MAX
    assert run.events_dropped == 7


def test_the_response_reports_the_drops_the_backend_s_bound_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two halves compose: a backend that dropped events says so on the wire.

    With the run buffer bounded, ``len(result.events)`` is itself a tail, so a
    response layer that counted only its own cut would report a 10,000-event run
    as a complete 1,024-event one — truncation, silently. The count travels on
    ``PromptResult.events_dropped``.
    """
    from dataclasses import replace

    from hephaestus.agent_bridge.app import PromptResult
    from hephaestus.http.sessions import PROMPT_EVENTS_MAX

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        real_prompt = agent.prompt

        def bounded(*args: Any, **kwargs: Any) -> PromptResult:
            result = real_prompt(*args, **kwargs)
            return replace(
                result,
                events=[{"kind": "text_delta", "seq": seq} for seq in range(PROMPT_EVENTS_MAX)],
                events_dropped=50,
            )

        monkeypatch.setattr(agent, "prompt", bounded)
        response = web.post(
            f"/sessions/{session}/prompt",
            json={
                "text": "go",
                "expected_model_revision": agent.session_model(session)["model_state"]["revision"],
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["events"]) == PROMPT_EVENTS_MAX
    assert body["events_truncated"] is True, (
        "events the backend's own bound dropped must still be reported as truncation"
    )
    assert body["events_dropped"] == 50


# --------------------------------------------------------------------------
# J-http-limits-6/-7 — an in-flight subprocess/probe does not stall unrelated
# routes


def test_a_slow_capability_probe_does_not_delay_an_unrelated_concurrent_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion the ledger says pins J-http-limits-6 and -7 together: a
    project request whose capability probe is slow must not stall a
    concurrent, unrelated request by more than about a second.

    ``is_work_tree`` (``git rev-parse``, the same call ``_git_available`` makes)
    is monkeypatched to sleep, driven through two threads against the SAME
    in-process app. ``TestClient``/``httpx`` here does not run a real ASGI
    reactor loop, so this proves the work happens off whatever thread is
    asking — the unit-level "off the event loop" claim (``asyncio.to_thread``
    at the route) is a property of the shipped code, checked by reading
    ``get_project``'s body rather than re-asserted here.
    """
    import threading

    from hephaestus.http import runtime as runtime_module

    def slow_is_work_tree(_root: Path) -> bool:
        time.sleep(1.5)
        return True

    monkeypatch.setattr(runtime_module, "is_work_tree", slow_is_work_tree)

    with workspace(tmp_path / "proj") as web:
        durations: dict[str, float] = {}

        def slow_request() -> None:
            started = time.monotonic()
            web.get("/project")
            durations["project"] = time.monotonic() - started

        def fast_request() -> None:
            time.sleep(0.1)  # let the slow one start first
            started = time.monotonic()
            web.get("/parts")
            durations["parts"] = time.monotonic() - started

        t1 = threading.Thread(target=slow_request)
        t2 = threading.Thread(target=fast_request)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    assert durations.get("project", 0.0) >= 1.4, "the slow probe did not actually run"
    assert durations.get("parts", 99.0) < 1.0, (
        f"an unrelated request took {durations.get('parts')}s while a slow "
        "capability probe was in flight"
    )


def test_two_successive_project_reads_probe_capabilities_at_most_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The TTL cache: a page load's worth of ``GET /project`` calls must not
    each pay for a fresh probe — the ledger's own reproduction (two
    consecutive calls each paying 25 s against a failing probe) is exactly
    what a cache with no TTL would still do.
    """
    from hephaestus.http import runtime as runtime_module

    calls = 0
    real_is_work_tree = runtime_module.is_work_tree  # pyright: ignore[reportPrivateImportUsage]

    def counted(root: Path) -> bool:
        nonlocal calls
        calls += 1
        return real_is_work_tree(root)

    monkeypatch.setattr(runtime_module, "is_work_tree", counted)

    with workspace(tmp_path / "proj") as web:
        first = web.get("/project")
        second = web.get("/project")
    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1, f"expected exactly one probe across two reads, got {calls}"
