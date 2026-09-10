# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§2.4's error mapping, closed — including the two rows that are **not** errors.

``INTERFACE.md`` §2.4. Structured taxonomies survive the wire: the body is always
``{"status":"error", "reason": <machine reason>, "message": <human>, …data}`` and
the HTTP status is a coarse envelope over the reason, never a replacement for it.

The two sharpest rows are the ones that return **200**:

* an edit / param **CAS conflict** is a *successful, discriminated result*, and a
  4xx would make the editor's merge prompt (G5.20) indistinguishable from a
  transport failure;
* ``capability_not_available`` / ``image_model_required`` are discriminated
  ``capability_error`` results, and a 4xx would make a missing sandbox
  indistinguishable from a broken server.

The reason strings asserted here are the **engine's**. Where §2.4 named a string
the engine does not have, the engine wins and the divergence is recorded rather
than papered over — see ``test_the_post_retention_reason_is_the_engines``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.agent_bridge.app import AgentUnavailableError, UnknownSessionError
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.supervisor import SupervisorError
from hephaestus.http.errors import (
    CAPABILITY_REASONS,
    REASON_STATUS,
    STALE_SELECTION_REASONS,
    HttpRefusal,
    capability_result,
    error_body,
    refusal_for,
    status_for_reason,
)
from hephaestus.testing.workspace import uuid7, workspace


def test_every_error_body_carries_status_reason_and_message(tmp_path: Path) -> None:
    """The envelope, asserted on a real refusal rather than on the helper."""
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/nosuchpart/properties").json()
    assert body["status"] == "error"
    assert isinstance(body["reason"], str) and body["reason"]
    assert isinstance(body["message"], str) and body["message"]


def test_the_envelope_never_lets_payload_data_overwrite_reason_or_message() -> None:
    """``reason`` and ``message`` win over ``data``.

    A refusal payload that carried its own ``reason`` key could otherwise
    silently relabel itself, which is the one thing a machine-readable reason
    must not be able to do.
    """
    body = error_body("scope_denied", "denied", {"reason": "something_else", "status": "ok"})
    assert body["reason"] == "scope_denied"
    assert body["status"] == "error"
    assert body["message"] == "denied"


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        ("invalid_params", 400),
        ("invalid_part", 400),
        ("invalid_cursor", 400),
        ("idempotency_key_required", 400),
        ("idempotency_key_malformed", 400),
        ("addressing_error", 400),
        ("unauthorized", 401),
        ("scope_denied", 403),
        ("unknown_tool", 404),
        ("stale_selection", 409),
        ("session_busy", 409),
        ("part_busy", 409),
        ("key_expired", 409),
        ("key_timestamp_skew", 409),
        ("key_payload_mismatch", 409),
        ("artifact_expired", 410),
        ("busy", 429),
        ("process_down", 503),
        ("timeout", 504),
        # B-6: the application boundary's own three rows — a route the table
        # does not carry, a route it carries for the wrong method, and an
        # exception no branch of `refusal_for` maps.
        ("unknown_route", 404),
        ("method_not_allowed", 405),
        ("internal_error", 500),
        # The rows the sidecar names for itself (`SIDECAR_REFUSALS`), each with
        # the status class its condition belongs to and none of them 500-opaque.
        ("agent_unavailable", 503),
        ("session_exists", 409),
        ("no_active_run", 500),
        ("ambiguous_run", 500),
        # J-http-envelope-14: §2.9's git family, each with its own row now
        # rather than a literal at the raise site with no table row at all.
        ("git_verb_refused", 403),
        ("git_failed", 400),
        ("not_a_git_repository", 404),
        ("git_unavailable", 503),
        ("git_timeout", 504),
        # J-http-envelope-18: the size refusals, decided on purpose — 400/413
        # for the request rungs (malformed-by-size input, versus a transport
        # that will not carry a well-formed body at all), 413 beside it for
        # §22.4's pre-existing export ceiling.
        ("json_too_deep", 400),
        ("json_too_many_members", 400),
        ("json_array_too_long", 400),
        ("json_string_too_large", 400),
        ("prompt_too_large", 400),
        ("request_too_large", 413),
        ("export_too_large", 413),
        # J-http-envelope-12/-18: the three session-scoped addressing misses.
        # Each already reached 404 through the `unknown_`-family rule; each has
        # a row now so the table is the complete set of reasons this surface
        # emits and a rename cannot move a status in silence.
        ("unknown_session", 404),
        ("unknown_run", 404),
        ("unknown_question", 404),
    ],
)
def test_the_section_two_four_table_row_by_row(reason: str, status: int) -> None:
    """Each tabulated engine condition maps to its tabulated envelope."""
    assert REASON_STATUS[reason] == status
    assert status_for_reason(reason) == status


def test_the_post_retention_reason_is_the_engines_not_the_documents() -> None:
    """DEVIATION, asserted so it cannot be quietly "fixed" back.

    §2.4's 410 row reads ``snapshot_expired``, and **no such reason exists
    anywhere in the engine**: the opstore's post-retention refusal is
    ``artifact_expired`` (``opstore/src/opstore/errors.py``:69). §2.4's own rule —
    "the reason strings above are the engine's, not this document's" — decides
    it, so the table carries the engine's string.
    """
    from opstore.errors import ArtifactExpiredError

    assert ArtifactExpiredError.code == "artifact_expired"
    assert REASON_STATUS["artifact_expired"] == 410
    assert "snapshot_expired" not in REASON_STATUS


def test_the_two_expiry_shaped_reasons_are_not_interchangeable() -> None:
    """§2.5: first-sight skew is ``key_timestamp_skew``; post-horizon is ``key_expired``.

    Both are 409, and that is exactly why the reason has to carry the difference:
    a client that retried into a skew refusal should fix its clock, and one that
    hit the horizon should mint a new key. The status cannot say which.
    """
    from opstore.errors import KeyExpiredError, KeyTimestampSkewError

    assert KeyTimestampSkewError.code != KeyExpiredError.code
    assert REASON_STATUS[KeyTimestampSkewError.code] == REASON_STATUS[KeyExpiredError.code] == 409


def test_the_stale_selection_vocabulary_is_closed_at_five_and_keeps_malformed() -> None:
    """§2.4 TIGHTENING (binds G5.15): five values, ``malformed`` among them.

    ``malformed`` — which no gate clause names — is surfaced with its own reason,
    never folded into ``mismatched`` and never degraded to a generic 400. The
    resolver that produces these is Stage 5 (§19 item 8); the **vocabulary** is
    closed here so it cannot be collapsed before it is used.
    """
    assert set(STALE_SELECTION_REASONS) == {
        "rgb_ref",
        "wrong_mode",
        "mismatched",
        "expired",
        "malformed",
    }
    assert len(STALE_SELECTION_REASONS) == 5


def test_addressing_error_and_stale_selection_stay_distinct() -> None:
    """§2.4 TIGHTENING (binds G5.7).

    Flattening a ``focus`` miss into ``stale_selection`` would make the
    mask-domain clause untestable, so the two have distinct reasons *and*
    distinct statuses.
    """
    assert status_for_reason("addressing_error") == 400
    assert status_for_reason("stale_selection") == 409


def test_a_stale_selection_carries_its_five_value_reason_in_the_payload() -> None:
    """The full refusal payload rides verbatim, sub-reason included."""
    from hephaestus.agent_bridge.sessions import StaleSelectionError

    exc = StaleSelectionError("the ref does not resolve against A")
    # Stage 5's `SelectionResolver` (§19 item 8) is what will set this; the
    # exception carries no declared `reason` today, so the mapping is exercised
    # here the way the resolver will present it.
    setattr(exc, "reason", "mismatched")  # noqa: B010
    refusal = refusal_for(exc)
    assert refusal.status == 409
    assert refusal.reason == "stale_selection"
    assert refusal.body()["stale_reason"] == "mismatched"


def test_a_capability_refusal_is_a_two_hundred_discriminated_result() -> None:
    """§2.4 DECISION: ``capability_error`` at **200**, never a 4xx.

    Dispatch already tags these (``dispatch.py`` puts ``code`` into
    ``DispatchError.data`` for exactly this purpose), so the mapping is a
    translation rather than a guess.
    """
    for reason in sorted(CAPABILITY_REASONS):
        exc = DispatchError(reason, "no sandbox here", data={"code": reason})
        result = capability_result(exc)
        assert result is not None
        assert result["status"] == "capability_error"
        assert result["code"] == reason


def test_a_non_capability_dispatch_error_is_not_turned_into_a_two_hundred() -> None:
    """The 200 branch is narrow on purpose: two codes, and nothing else."""
    exc = DispatchError("invalid_params", "nope")
    assert capability_result(exc) is None
    assert refusal_for(exc).status == 400


def test_a_param_cas_conflict_is_two_hundred_with_the_discriminated_result(
    tmp_path: Path,
) -> None:
    """§2.4: an edit / param CAS conflict is **not an error**.

    It is the discriminated result carrying ``conflict{…}``, at 200, so the
    merge prompt can tell a conflict from a broken connection. Asserted end to
    end through the real route rather than on the mapping table, because the
    route is where a well-meaning 409 would be added.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.post(
            "/parts/widget/params",
            json={"values": {"width": 45.0}, "expected_state_hash": "sha256:stale"},
            key=uuid7(),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "conflict" in body
    assert body["conflict"]["current_state_hash"].startswith("sha256:")


def test_an_unknown_part_is_a_four_hundred_invalid_part_not_a_crash(
    tmp_path: Path,
) -> None:
    """A part-scoped route never crashes on an absent part — it refuses, named.

    UPDATED for J-http-envelope-3 (audit-2026-09-04): every part-scoped route
    now resolves the part through the shared ``resolve_part``, which raises
    404 ``unknown_part`` for a syntactically legal name this project does not
    have (the RC-4 fix — see ``test_http_parts_refusals.py`` for the full
    parametrised sweep over every part-scoped route). ``invalid_part`` is the
    OTHER rung of that resolver: a name that cannot be a part *at all*, which
    is the sibling test right below.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.get("/parts/nosuchpart/script")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_part"


def test_a_syntactically_illegal_part_name_is_invalid_part_not_unknown_part(
    tmp_path: Path,
) -> None:
    """The rung ``unknown_part`` is not: a name the store's own grammar rejects
    outright is a malformed request, refused before any part-list read.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.get("/parts/not-a-valid-identifier/script")
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_part"


def test_an_unmapped_reason_falls_through_a_named_family_not_a_silent_default() -> None:
    """The fallback families are rules, stated, not a bare ``.get(..., 400)``."""
    assert status_for_reason("unknown_skill") == 404
    assert status_for_reason("no_such_widget") == 404
    assert status_for_reason("generator_failed") == 400


def test_an_unrecognized_exception_is_re_raised_rather_than_mislabelled() -> None:
    """A mapper that guessed would turn a bug into a plausible-looking refusal."""
    with pytest.raises(ZeroDivisionError):
        refusal_for(ZeroDivisionError("not an engine condition"))


def test_an_http_refusal_maps_to_itself() -> None:
    """The layer's own refusals pass through the same mapping as the engine's."""
    refusal = HttpRefusal(404, "unknown_artifact_kind_for_route", "no")
    assert refusal_for(refusal) is refusal


def test_a_malformed_json_body_is_invalid_params(tmp_path: Path) -> None:
    """The body is parsed as bytes and refused by name, never coerced."""
    with workspace(tmp_path / "proj") as web:
        response = web.raw("POST", "/parts/widget/build", content=b"{not json", key=uuid7())
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_params"


def test_a_json_body_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    """Every mutation body is an argument document; a bare array is not one."""
    with workspace(tmp_path / "proj") as web:
        response = web.raw("POST", "/parts/widget/build", content=b"[1, 2, 3]", key=uuid7())
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_params"


def test_an_argument_the_canonical_schema_rejects_is_invalid_params(
    tmp_path: Path,
) -> None:
    """The route validates against the **canonical** tool schema, not its own.

    Same validator as the MCP boundary, so declared defaults are materialized
    identically on both transports and a payload hash over the normalized
    document means the same thing on each.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.post("/parts/widget/build", json={"params": "not an object"}, key=uuid7())
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_params"


def test_the_path_part_always_wins_over_a_part_named_in_the_body(tmp_path: Path) -> None:
    """A request whose path says ``widget`` must never mutate ``bracket``.

    Every part-addressed mutation route merges the path parameter **last**, so a
    body that names a different part cannot redirect the write. Without this,
    the URL a reader (or a log, or an audit) sees would not be the object the
    call touched.
    """
    with workspace(tmp_path / "proj") as web:
        before = (tmp_path / "proj" / "parts" / "bracket.py").read_text(encoding="utf-8")
        state = web.get("/parts/widget/params").json()["state_hash"]
        response = web.post(
            "/parts/widget/params",
            json={"name": "bracket", "values": {"width": 45.0}, "expected_state_hash": state},
            key=uuid7(),
        )
        after = (tmp_path / "proj" / "parts" / "bracket.py").read_text(encoding="utf-8")
        widget_params = web.get("/parts/widget/params").json()
    assert response.status_code == 200, response.text
    assert before == after
    assert {row["name"]: row["value"] for row in widget_params["params"]}["width"] == 45.0


def test_the_bridge_liveness_terminals_map_to_503_and_504() -> None:
    """§2.4's last two rows: ``TIMEOUT`` → 504, ``PROCESS_DOWN`` → 503.

    Those rows name the bridge's **numeric JSON-RPC codes**
    (``agent_bridge/protocol.py``), not reason strings — the engine has no string
    for either condition. The wire needs one, so it is the enum member name
    lowercased: deterministic and traceable back to its source, rather than a
    new vocabulary. Without this mapping both would have flattened into a 400
    and a stalled sidecar would have been indistinguishable from a bad request.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
    from hephaestus.http.errors import PROTOCOL_CODE_REASON

    timed_out = refusal_for(ProtocolError(ErrorCode.TIMEOUT, "the sidecar did not answer"))
    assert (timed_out.status, timed_out.reason) == (504, "timeout")

    down = refusal_for(ProtocolError(ErrorCode.PROCESS_DOWN, "sidecar exited"))
    assert (down.status, down.reason) == (503, "process_down")

    busy = refusal_for(ProtocolError(ErrorCode.BUSY, "all 16 run slots are occupied"))
    assert (busy.status, busy.reason) == (429, "busy")

    other = refusal_for(ProtocolError(ErrorCode.INVALID_REQUEST, "malformed frame"))
    assert (other.status, other.reason) == (400, "protocol_error")

    assert set(PROTOCOL_CODE_REASON.values()) <= set(REASON_STATUS)


def test_a_refusal_payload_rides_through_whole(tmp_path: Path) -> None:
    """§2.4: "full refusal payload verbatim" — every field, not just the reason.

    A misspelled part on ``POST /parts/{part}/build`` refuses ``unknown_part``
    (UPDATED for J-http-envelope-3: the part is resolved before the route
    reaches the dispatcher at all, so this is a 404 addressing miss rather than
    a dispatch-layer ``invalid_part``) and carries the known ``parts`` list the
    resolver computed. A mapping that kept only reason and message would throw
    away the one thing that makes the refusal actionable, and the client would
    have to re-derive the part list — the client-side derivation §1 forbids,
    one layer down.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.post("/parts/widgt/build", json={}, key=uuid7())
    body = response.json()
    assert response.status_code == 404
    assert body["reason"] == "unknown_part"
    assert sorted(body["parts"]) == ["bracket", "widget"]


def test_a_refusal_with_extra_data_keeps_it_and_cannot_relabel_itself() -> None:
    """Data enriches the envelope; it never overwrites ``reason`` or ``status``."""
    refusal = refusal_for(
        DispatchError("part_busy", "widget is being built", data={"lease": "held", "reason": "x"})
    )
    body = refusal.body()
    assert refusal.status == 409
    assert body["reason"] == "part_busy"
    assert body["status"] == "error"
    assert body["lease"] == "held"


# --------------------------------------------------------------------------
# §2.4, amended 2026-09-03: the two new session-route rows (§2.8(6))


def test_an_unmapped_supervisor_error_no_longer_reaches_the_client_unnamed() -> None:
    """The bug this amendment exists to fix, pinned at the mapping layer.

    Before the 2026-09-03 amendment ``refusal_for`` had no branch for a bare
    :class:`SupervisorError` at all: every isinstance check in the function was
    for something *else*, so it fell through to the trailing ``raise exc`` and
    reached the client as an unnamed 500 — over a transcript that was sitting
    intact on disk the whole time. This must no longer raise.

    UPDATED by the 2026-09-04 (B-11) amendment: a populated ``error`` envelope
    this module does not recognise is no longer folded into
    ``unknown_session``/``agent_unavailable`` either — that guess was itself the
    B-11(a) mislabel (an *answered* refusal reported as a dead runtime). An
    answered-but-unclassified envelope is now ``internal_error`` at 500: still
    named, still carries an incident id, and honest about which of "this
    request is bad" / "this runtime is gone" / "nobody classified this" is
    true.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = SupervisorError("session.create failed", error={"code": ErrorCode.INTERNAL_ERROR})
    refusal = refusal_for(exc)  # must not raise
    assert isinstance(refusal, HttpRefusal)
    assert (refusal.status, refusal.reason) == (500, "internal_error")
    assert isinstance(refusal.data.get("incident"), str) and refusal.data["incident"]


def test_unknown_session_error_maps_to_a_named_404_carrying_session_id() -> None:
    """§2.4's new row: sidecar doesn't know a listed session, after one
    re-adoption attempt → 404 ``unknown_session`` + ``{session_id}``.

    ``UnknownSessionError`` is ``agent_bridge/app.py``'s own named signal for
    exactly this condition (§2.8(6)) — asserted here as the CONTRACT between
    the bridge and this mapping layer, independent of whichever route or
    real-sidecar scenario produces one (``test_session_readopt.py`` exercises
    that through a real kill/respawn).
    """
    exc = UnknownSessionError("unknown session 'sess-x': not recovered", session_id="sess-x")
    refusal = refusal_for(exc)
    assert refusal.status == 404
    assert refusal.reason == "unknown_session"
    assert refusal.data.get("session_id") == "sess-x"
    assert status_for_reason("unknown_session") == 404


def test_agent_unavailable_error_maps_to_a_named_503_carrying_its_cause() -> None:
    """§2.4's other new row: no sidecar can serve ANY session route.

    Never collapsed into ``unknown_session`` — one says *this session*, the
    other says *this runtime*, and REASON_STATUS already carries
    ``agent_unavailable`` → 503 (§7A.8), reused rather than re-tabulated.
    """
    exc = AgentUnavailableError("no sidecar can serve session 'sess-x'", session_id="sess-x")
    refusal = refusal_for(exc)
    assert refusal.status == 503
    assert refusal.reason == "agent_unavailable"
    assert refusal.data.get("cause") == "sidecar_failed"
    assert REASON_STATUS["agent_unavailable"] == 503


def test_unknown_session_and_agent_unavailable_are_never_collapsed() -> None:
    """The two rows are asserted apart, deliberately, per the contract's own
    "NEVER COLLAPSED" clause: different reasons, different statuses, different
    remedies for what is superficially the same "a session route failed".
    """
    session = refusal_for(UnknownSessionError("unknown session 'x'", session_id="x"))
    runtime = refusal_for(AgentUnavailableError("no sidecar", session_id="x"))
    assert (session.status, session.reason) != (runtime.status, runtime.reason)
    assert session.reason != runtime.reason


def test_a_bare_supervisor_timeout_maps_to_504_not_agent_unavailable() -> None:
    """Round 2's fix: a hard-wait timeout is a live, slow sidecar, not a dead
    one, and must not fall into the ``agent_unavailable`` catch-all below it.

    ``Supervisor._call``'s own backstop (``agent_bridge/supervisor.py:566``)
    raises a bare ``SupervisorError`` with no ``error=`` envelope at all — the
    same shape ``AgentUnavailableError``'s catch-all is built to catch — so the
    mapping layer must recognise the message ITSELF (``_SUPERVISOR_TIMEOUT_RE``)
    before falling through, on the same discipline as ``_UNKNOWN_SESSION_RE``.
    Before this fix a slow-but-alive sidecar and a genuinely dead one were the
    same 503, and a client cannot tell "wait" from "fix the runtime" apart.
    """
    exc = SupervisorError("session.prompt timed out after 30.0s with no response")
    refusal = refusal_for(exc)
    assert (refusal.status, refusal.reason) == (504, "timeout")
    assert status_for_reason("timeout") == 504

    # A bare SupervisorError that does NOT match the fixed timeout shape still
    # falls through to the runtime-wide catch-all, unaffected by this branch.
    other = SupervisorError("no process to write to")
    other_refusal = refusal_for(other)
    assert (other_refusal.status, other_refusal.reason) == (503, "agent_unavailable")


# --------------------------------------------------------------------------
# B-11(a) — a malformed cursor is reported as a dead runtime


def test_a_supervisor_error_with_no_envelope_is_agent_unavailable() -> None:
    """The half of the structural rule that must stay true: silence is a dead
    runtime. ``Supervisor``'s own raise sites (no process, a respawn that gave
    up its budget, an unanswered deadline) construct a bare ``SupervisorError``
    with no ``error=`` kwarg at all, and that absence IS the "nothing answered"
    fact — not a guess.
    """
    exc = SupervisorError("no process to write to")
    refusal = refusal_for(exc)
    assert (refusal.status, refusal.reason) == (503, "agent_unavailable")


def test_a_supervisor_error_with_an_error_envelope_is_never_agent_unavailable() -> None:
    """The structural half of the B-11(a) fix, pinned WITHOUT naming the cursor
    message: a populated ``error`` envelope is proof the sidecar answered, so it
    must never fall through to ``agent_unavailable`` — whether or not this
    module recognises the message inside it.

    Before the fix, ``_refusal_for_supervisor_error`` only special-cased ONE
    invalid-params shape (`_UNKNOWN_SESSION_RE`); every other populated
    envelope — including the malformed-cursor message the sidecar has not been
    taught to emit through this path yet — fell through to the same catch-all
    a truly silent sidecar gets. This is exactly the mechanism B-11(a) names:
    "any future sidecar handler that throws a plain error […] still becomes
    -32603 and is still reported as a dead runtime." A mapper that special-cased
    only the cursor message would leave every OTHER answered-but-unrecognised
    envelope mislabelled; this test is written so it cannot be satisfied that
    way.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = SupervisorError(
        "session.create failed",
        error={
            "code": ErrorCode.INVALID_PARAMS,
            "message": "a future refusal this module has not been taught to name yet",
        },
    )
    refusal = refusal_for(exc)
    assert refusal.reason != "agent_unavailable"


def test_a_malformed_cursor_envelope_maps_to_invalid_cursor_at_400() -> None:
    """B-11(a) fix step 3: the sidecar names its own refusal, read rather than
    re-derived.

    ``agent/src/session/history.ts`` throws a NAMED ``MalformedCursorError`` for
    a token that does not decode and for the mutually-exclusive ``cursor``/
    ``after`` pair; ``main.ts``'s ``history.page`` handler re-throws it as an
    ``RpcError`` carrying ``data: {reason: "invalid_cursor"}`` rather than
    letting it become a bare ``-32603``. This unit pins the Python half of that
    contract — :func:`refusal_for` reading the sidecar's own ``data.reason``
    token off the JSON-RPC envelope — independent of a built sidecar.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = SupervisorError(
        "history.page failed",
        error={
            "code": ErrorCode.INVALID_PARAMS,
            "message": "malformed history cursor",
            "data": {"reason": "invalid_cursor"},
        },
    )
    refusal = refusal_for(exc)
    assert (refusal.status, refusal.reason) == (400, "invalid_cursor")
    assert status_for_reason("invalid_cursor") == 400


def test_the_sidecar_failed_refusal_never_carries_the_provider_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paired with ``test_http_attach.py``'s
    ``test_a_serve_starts_with_no_provider_config_and_names_why`` (not owned by
    this lane, so not imported here): THAT refusal is
    ``agent_unavailable``/``no_provider_config`` and correctly carries
    ``config_path`` — it names the file this process checked and found empty.
    THIS refusal is ``agent_unavailable``/``sidecar_failed`` — a session backend
    that WAS attached (an attach happened; ``config_path`` is on record) and
    then failed mid-call with no envelope. §2.4 says this path must not carry
    ``config_path``, because a stale path is worse than an absent one, and the
    refusal is already minted correctly where ``AgentUnavailableError``/the
    bare-``SupervisorError`` catch-all construct it (no ``config_path`` key in
    either literal). The six-line merge at ``http/app.py``'s endpoint guard
    (``if refusal.reason == "agent_unavailable" and "config_path" not in
    refusal.data: refusal.data = {**_attach_data(runtime), **refusal.data}``)
    is what reattaches it — unconditionally, for ANY ``agent_unavailable``,
    sidecar-failed included. That merge is the root cause and the ledger names
    its deletion explicitly; this test fails while it stands.
    """
    from hephaestus.http.agent_attach import AgentAttachState

    with workspace(tmp_path / "proj", agent=True) as web:
        # An attach DID happen in this process and is on record, config_path
        # and all — the state a real serve is in after a successful sign-in.
        web.runtime.attach_state = AgentAttachState(
            attached=True, config_path=str(web.root / ".heph" / "providers.json"), generation=1
        )

        def _boom(*_args: object, **_kwargs: object) -> str:
            raise SupervisorError("no process to write to")

        agent = web.agent
        assert agent is not None
        monkeypatch.setattr(agent, "create_session", _boom)

        response = web.post(
            "/sessions",
            json={"profile": "orchestrator", "model": {"provider_id": "fake", "model_id": "text"}},
        )

    assert response.status_code == 503
    body = response.json()
    assert body["reason"] == "agent_unavailable"
    assert body["cause"] == "sidecar_failed"
    assert "config_path" not in body


# --------------------------------------------------------------------------
# J-http-envelope-15 (audit-2026-09-04) — the supervisor path used to reduce
# `detail` and leave `message` a raw, unbounded `str(exc)` beside it: both
# `_refusal_from_envelope`'s and the below-the-runtime catch-all's
# `agent_unavailable` branches passed the exception through `reduce_detail`
# for `detail` and `str(exc)` positionally for `message`, and the reducer's
# own redaction loop iterated an empty `secrets` sequence by default — so the
# redaction half was a no-op even where it ran. The fix makes `secrets`
# required (not defaulted) at `_refusal_for_supervisor_error` and reduces
# BOTH fields: `message` is now a fixed operator sentence
# (`_AGENT_UNAVAILABLE_MESSAGE`), never the raw exception text, and `detail`
# is bounded through the same `reduce_detail`/`reduce_text` helpers the git
# and credential boundaries already use, with the caller's own bearer passed
# as a secret (`app.py` calls `refusal_for(exc, secrets=(runtime.token,))`).


def test_a_supervisor_failure_naming_the_bearer_leaks_it_in_neither_field() -> None:
    """A sidecar-level failure whose text embeds this process's own secret
    (the one secret this layer could plausibly leak) must not surface it in
    ``message`` or in ``detail``.
    """
    bearer = "sk-live-definitely-a-real-bearer-token"
    exc = SupervisorError(f"child died while holding {bearer} in its argv")
    refusal = refusal_for(exc, secrets=(bearer,))
    body = refusal.body()
    assert bearer not in body["message"]
    assert bearer not in str(body.get("detail", ""))
    assert (refusal.status, refusal.reason) == (503, "agent_unavailable")


def test_a_supervisor_failures_message_is_fixed_never_the_raw_exception_text() -> None:
    """``message`` is an operator sentence, not a second copy of the engine
    text — the same discipline the internal-error path already keeps for its
    own message (``test_the_internal_error_message_is_fixed_not_the_exceptions_own_text``
    in ``test_http_envelope.py``, not owned by this lane, is the sibling case).
    """
    exc = SupervisorError("no process to write to: pid 41317 exited with code -9")
    refusal = refusal_for(exc, secrets=())
    assert "41317" not in refusal.message
    assert "-9" not in refusal.message


def test_a_very_long_supervisor_message_is_bounded_the_same_as_detail() -> None:
    """The message is capped at the same budget the detail already was — a
    verbose exception must not amplify one field while the other stays
    bounded, which is exactly the asymmetry the ledger measured.
    """
    from hephaestus.http.agent_attach import DETAIL_MAX_CHARS

    huge = "x" * 20_000
    exc = SupervisorError(f"sidecar died: {huge}")
    refusal = refusal_for(exc, secrets=())
    assert len(refusal.message) <= DETAIL_MAX_CHARS + 40, (
        f"message is {len(refusal.message)} chars, unbounded beside a "
        f"{DETAIL_MAX_CHARS}-char detail"
    )
    body = refusal.body()
    detail = body.get("detail")
    if isinstance(detail, str):
        assert len(detail) <= DETAIL_MAX_CHARS + 40


# --------------------------------------------------------------------------
# The sidecar's own refusals, each named rather than flattened (§2.4, amended
# 2026-09-05). Every one of these is an ANSWERED frame, so the structural half
# of the B-11(a) fix routes it to `_refusal_from_envelope`; before the sidecar
# carried a `data.reason` for it, that meant an opaque `500 internal_error` for
# four conditions that had names, three of which had been 503s with a cause.
# The reasons are minted in `agent/src/main.ts`; these pin the Python half.


def _answered(message: str, *, code: int, data: dict[str, object]) -> SupervisorError:
    """One answered JSON-RPC refusal, shaped exactly as ``Supervisor._call`` raises it."""
    return SupervisorError(
        f"session.create failed: {{'message': {message!r}}}",
        error={"code": code, "message": message, "data": data},
    )


def test_an_unconfigured_runtime_is_503_agent_unavailable_with_a_cause() -> None:
    """``main.ts``'s ``requireRuntime``/``requireService``: the child answers,
    and what it answers is that it holds no runtime that can serve a turn.

    §7A.8's availability condition, so §7A.8's envelope — 503, a ``cause`` from
    the closed set, a ``detail``. Not ``internal_error``: "the server failed" is
    not what happened, and an opaque 500 tells an operator nothing about the one
    thing they can act on.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = _answered(
        "runtime.configure has not run yet",
        code=ErrorCode.INVALID_REQUEST,
        data={"reason": "agent_unavailable", "cause": "sidecar_failed"},
    )
    refusal = refusal_for(exc)
    assert (refusal.status, refusal.reason) == (503, "agent_unavailable")
    assert refusal.message == "runtime.configure has not run yet"
    assert refusal.data["cause"] == "sidecar_failed"
    assert refusal.data["detail"]
    # §2.4's 2026-09-03 RECONCILIATION: this path carries `cause` and `detail`
    # and deliberately not `config_path`.
    assert "config_path" not in refusal.body()


def test_a_runtime_whose_providers_all_failed_verification_is_also_503() -> None:
    """§23.7: a configured runtime whose every provider failed verification is
    unusable for exactly the same reason and gets exactly the same envelope —
    plus the provider's own code, so the refusal names what to fix.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = _answered(
        "provider 'openai' did not verify: provider_not_authenticated",
        code=ErrorCode.INVALID_REQUEST,
        data={
            "reason": "agent_unavailable",
            "cause": "provider_config_invalid",
            "provider_id": "openai",
            "unavailable_reason": "provider_not_authenticated",
        },
    )
    refusal = refusal_for(exc)
    assert (refusal.status, refusal.reason) == (503, "agent_unavailable")
    assert refusal.data["cause"] == "provider_config_invalid"
    assert refusal.data["provider_id"] == "openai"
    assert refusal.data["unavailable_reason"] == "provider_not_authenticated"


def test_a_sidecar_cause_outside_the_closed_set_is_not_passed_through() -> None:
    """The discipline ``agent_credentials._reason_of`` applies to §23.11's codes,
    applied to the one field this refusal is dispatched on: a vocabulary a
    downstream process can widen by answering with a new string is not closed.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode
    from hephaestus.http.agent_attach import ATTACH_CAUSES

    exc = _answered(
        "the runtime is sad",
        code=ErrorCode.INVALID_REQUEST,
        data={"reason": "agent_unavailable", "cause": "invented_by_a_future_sidecar"},
    )
    refusal = refusal_for(exc)
    assert refusal.status == 503
    assert refusal.data["cause"] == "sidecar_failed"
    assert refusal.data["cause"] in ATTACH_CAUSES


def test_a_sidecar_supplied_config_path_is_dropped_from_agent_unavailable() -> None:
    """A stale ``config_path`` is worse than an absent one, and this layer cannot
    keep one in sync — so a future sidecar cannot add the key by answering with it.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = _answered(
        "runtime.configure has not run yet",
        code=ErrorCode.INVALID_REQUEST,
        data={
            "reason": "agent_unavailable",
            "cause": "sidecar_failed",
            "config_path": "/somewhere/providers.json",
        },
    )
    assert "config_path" not in refusal_for(exc).body()


def test_a_duplicate_session_id_is_a_409_conflict_not_a_server_fault() -> None:
    """``SessionService.create``'s other refusal: the caller chose an id this
    runtime is already serving. A conflict on existing state — the request is
    well-formed and the runtime is healthy — so 409, and the ``session_id``
    rides through so the caller can address the session that already holds it.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = _answered(
        "session 's1' already exists",
        code=ErrorCode.INVALID_PARAMS,
        data={"reason": "session_exists", "session_id": "s1"},
    )
    refusal = refusal_for(exc)
    assert (refusal.status, refusal.reason) == (409, "session_exists")
    assert refusal.data["session_id"] == "s1"
    assert refusal.message == "session 's1' already exists"


def test_an_unattributable_tool_call_keeps_its_own_500_and_its_own_sentence() -> None:
    """``main.ts``'s ``currentRun``. Genuinely an internal fault, so 500 — but
    NOT ``internal_error``, whose fixed message and incident id exist for
    exceptions nobody classified and therefore nobody redacted. These two are
    classified where they are raised, they carry nothing from a provider or a
    filesystem, and the sentence is the entire diagnosis: it survives.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode
    from hephaestus.http.errors import INTERNAL_ERROR_MESSAGE

    none_active = refusal_for(
        _answered(
            "no active run for tool invocation",
            code=ErrorCode.INTERNAL_ERROR,
            data={"reason": "no_active_run"},
        )
    )
    assert (none_active.status, none_active.reason) == (500, "no_active_run")
    assert none_active.message == "no active run for tool invocation"
    assert none_active.message != INTERNAL_ERROR_MESSAGE
    assert "incident" not in none_active.body()

    ambiguous = refusal_for(
        _answered(
            "ambiguous run for tool invocation (2 runs in flight)",
            code=ErrorCode.INTERNAL_ERROR,
            data={"reason": "ambiguous_run", "runs_in_flight": 2},
        )
    )
    assert (ambiguous.status, ambiguous.reason) == (500, "ambiguous_run")
    assert ambiguous.data["runs_in_flight"] == 2


def test_an_envelope_that_names_no_reason_still_cannot_reach_agent_unavailable() -> None:
    """The half of the structural fix that must not be weakened by the rows
    above: reading a token the sidecar wrote is not the same as INFERRING one.

    An answered frame whose ``data`` names no reason — the shape every
    unclassified sidecar throw still has — must stay off the 503 path, or the
    B-11(a) regression (a live sidecar reported as a dead runtime, while the
    very next call to it returns 200) is back for every future handler.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    for data in ({}, {"reason": "a_reason_this_layer_does_not_know"}):
        exc = SupervisorError(
            "session.prompt failed",
            error={"code": ErrorCode.INVALID_REQUEST, "message": "something new", "data": data},
        )
        refusal = refusal_for(exc)
        assert refusal.reason == "internal_error", data
        assert refusal.status == 500, data


# --------------------------------------------------------------------------
# audit-2026-09-04 J-http-envelope-14/-18 — THE STANDING GUARD.
#
# The row-by-row test above is a list somebody has to remember to extend. This
# pair is the rule: it reads the HTTP package's own source and holds every
# refusal it constructs against `REASON_STATUS`. It is what turns "a reason
# raised at 403 with a table that says 400" — four git reasons did exactly that
# — into a red test rather than a divergence nothing computes and nothing sees.


def _refusal_constructions() -> list[tuple[str, int, int | None, str | None]]:
    """Every ``HttpRefusal(...)`` / ``_refuse(...)`` in ``hephaestus.http``.

    Returns ``(module, lineno, status, reason)`` with ``None`` where the
    argument is not a literal — a computed status (``status_for_reason(...)``)
    is *already* the table by construction and needs no assertion, and a
    computed reason cannot be resolved without running the code.

    ``events_ws`` is excluded: its module-private ``_refuse`` is a WebSocket
    close helper with an entirely different signature (socket, sentence), not a
    §2.4 refusal, and matching on the name alone would read its close messages
    as reason tokens.
    """
    import ast

    package = Path(__file__).parents[1] / "src" / "hephaestus" / "http"
    found: list[tuple[str, int, int | None, str | None]] = []
    for path in sorted(package.glob("*.py")):
        if path.name == "events_ws.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name not in {"HttpRefusal", "_refuse"}:
                continue
            status_arg, reason_arg = node.args[0], node.args[1]
            status = (
                status_arg.value
                if isinstance(status_arg, ast.Constant) and isinstance(status_arg.value, int)
                else None
            )
            reason = (
                reason_arg.value
                if isinstance(reason_arg, ast.Constant) and isinstance(reason_arg.value, str)
                else None
            )
            found.append((path.name, node.lineno, status, reason))
    return found


def test_every_hardcoded_refusal_status_agrees_with_the_shared_table() -> None:
    """No refusal in this package sends a status the §2.4 table disagrees with.

    THE guard J-http-envelope-14 asks for. Four git reasons were raised at 403,
    400, 503 and 404 with literals at their raise sites and **no rows at all**,
    so ``status_for_reason`` answered 400 for every one of them and disagreed
    with the wire on three — invisibly, because nothing round-tripped a status
    through the table. A per-reason list would have caught those four; only a
    walk catches the fifth one somebody adds next year.
    """
    disagreements = [
        f"{module}:{line} sends {status} for {reason!r}, "
        f"but the table says {status_for_reason(reason)}"
        for module, line, status, reason in _refusal_constructions()
        if status is not None and reason is not None and status_for_reason(reason) != status
    ]
    assert not disagreements, "\n".join(disagreements)


def test_every_named_refusal_reason_has_a_row_in_the_closed_table() -> None:
    """§2.4's table is the COMPLETE set of reasons this surface emits.

    J-http-envelope-18's sentence, made executable: a reason with no row is a
    defect. Three session-scoped reasons (``unknown_session``, ``unknown_run``,
    ``unknown_question``) reached the right status only through the
    ``unknown_``-family fallback, which is a rule about *spelling* — rename one
    of them and its status moves silently. The fallback stays, because it is
    the honest answer for an engine reason this package never spells; what it
    may no longer do is stand in for a row this package's own raise sites need.
    """
    orphans = sorted(
        {
            f"{reason!r} (raised at {module}:{line})"
            for module, line, _status, reason in _refusal_constructions()
            if reason is not None and reason not in REASON_STATUS
        }
    )
    assert not orphans, "reasons this package raises with no §2.4 row:\n" + "\n".join(orphans)


def test_the_standing_guard_is_not_vacuous() -> None:
    """A walk that finds nothing passes everything.

    Pinned as a floor rather than an equality so that adding a refusal does not
    fail this test; what it catches is the walk silently matching zero calls
    after a rename of ``HttpRefusal`` or a move of the package.
    """
    constructions = _refusal_constructions()
    assert len(constructions) >= 100, f"only {len(constructions)} refusal constructions found"
    pairs = [row for row in constructions if row[2] is not None and row[3] is not None]
    assert len(pairs) >= 60, f"only {len(pairs)} literal status/reason pairs found"
