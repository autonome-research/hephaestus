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
    """``invalid_part`` verbatim — the dispatcher's own reason, not a rewrite."""
    with workspace(tmp_path / "proj") as web:
        response = web.get("/parts/nosuchpart/script")
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

    A misspelled part on ``POST /parts/{part}/build`` refuses ``invalid_part``
    and carries the ``candidates`` the addressing layer computed. A mapping that
    kept only reason and message would throw away the one thing that makes the
    refusal actionable, and the client would have to re-derive the part list —
    the client-side derivation §1 forbids, one layer down.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.post("/parts/widgt/build", json={}, key=uuid7())
    body = response.json()
    assert response.status_code == 400
    assert body["reason"] == "invalid_part"
    assert sorted(body["candidates"]) == ["bracket", "widget"]


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

    Before this amendment ``refusal_for`` had no branch for a bare
    :class:`SupervisorError`: every isinstance check in the function is for
    something *else*, so it fell through to the trailing ``raise exc`` and
    reached the client as an unnamed 500 — over a transcript that was sitting
    intact on disk the whole time (the condition §2.3/§2.4's amendment note
    names explicitly). This must no longer raise.
    """
    from hephaestus.agent_bridge.protocol import ErrorCode

    exc = SupervisorError("session.create failed", error={"code": ErrorCode.INTERNAL_ERROR})
    refusal = refusal_for(exc)  # must not raise
    assert isinstance(refusal, HttpRefusal)
    assert refusal.status in (404, 503)
    assert refusal.reason in ("unknown_session", "agent_unavailable")


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
