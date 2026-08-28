# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The §2.4 error mapping, closed — structured taxonomies survive the wire.

``INTERFACE.md`` §2.4. The body is always::

    {"status": "error", "reason": <machine reason>, "message": <human>, ...data}

and the HTTP status is a **coarse envelope over the reason**; it never replaces
it. A client that dispatches on status alone is reading the less informative
half of the response on purpose.

Two rows of the table are *not* errors and are enforced by their absence here:

* **edit / param CAS conflict → 200**, carrying the discriminated result with
  its ``conflict{…}``; and
* **``capability_not_available`` / ``image_model_required`` → 200**, carrying
  the discriminated ``capability_error`` result.

Both come back from ``ToolDispatcher`` as *results* in one case and as a
``DispatchError`` in the other, so :func:`capability_result` is where the second
is turned back into the 200 the gate needs. A 4xx there would make the editor's
merge prompt (G5.20) indistinguishable from a transport failure, and a missing
sandbox indistinguishable from a broken server.

**The reason strings are the engine's, not this module's.** Every constant below
is grounded in the code that raises it; where §2.4 named a string the engine
does not have, the engine wins and the divergence is recorded in the constant's
comment rather than papered over by inventing the string here.
"""

from __future__ import annotations

from typing import Any, Final

from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.limits import LimitError
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
from hephaestus.agent_bridge.sessions import SessionBusyError, StaleSelectionError
from hephaestus.core.errors import HephaestusError
from opstore.errors import OpStoreError

__all__ = [
    "CAPABILITY_REASONS",
    "PROTOCOL_CODE_REASON",
    "REASON_STATUS",
    "STALE_SELECTION_REASONS",
    "HttpRefusal",
    "capability_result",
    "error_body",
    "refusal_for",
    "status_for_reason",
]

#: ``INTERFACE.md`` §2.4, TIGHTENING (binds G5.15): the five-value
#: ``StaleReason`` vocabulary is closed and must not be collapsed. ``malformed``
#: — which no gate clause names — is surfaced with its own reason, never folded
#: into ``mismatched`` and never degraded to a generic 400.
STALE_SELECTION_REASONS: Final[tuple[str, ...]] = (
    "rgb_ref",
    "wrong_mode",
    "mismatched",
    "expired",
    "malformed",
)

#: The two discriminated *results* that must never become a 4xx (§2.4 DECISION).
CAPABILITY_REASONS: Final[frozenset[str]] = frozenset(
    {"capability_not_available", "image_model_required"}
)

#: The §2.4 table, reason by reason. Anything not listed falls through the
#: family rules in :func:`status_for_reason`, which are stated there rather than
#: hidden as a bare ``.get(..., 400)``.
REASON_STATUS: Final[dict[str, int]] = {
    # 400 — invalid input and every idempotency-key fault (§2.5's ladder).
    "invalid_params": 400,
    "invalid_part": 400,
    "invalid_cursor": 400,
    "invalid_ref": 400,
    "invalid_utf8_offset": 400,
    "invalid_unicode_scalar": 400,
    "idempotency_key_required": 400,
    "idempotency_key_malformed": 400,
    # `addressing_error` is a distinct status from `stale_selection`, and
    # deliberately so: TIGHTENING (binds G5.7) — flattening a `focus` miss into
    # a stale selection would make the mask-domain clause untestable.
    "addressing_error": 400,
    # 401 — the only authentication this surface has.
    "unauthorized": 401,
    # 403 — dispatch's own object-scope and reviewer rules, unchanged.
    "scope_denied": 403,
    # 404 — an unknown tool, part, or artifact.
    "unknown_tool": 404,
    "unknown_artifact": 404,
    "unknown_artifact_kind_for_route": 404,
    "unknown_part": 404,
    "not_found": 404,
    # 409 — refusals whose full payload rides through verbatim.
    "stale_selection": 409,
    "session_busy": 409,
    "part_busy": 409,
    "conflict": 409,
    # A build ref that cannot yield a *linked* GLB (§5.1). 409 rather than the
    # fallback 400: the request is well formed and the ref exists — what fails is
    # the server's ability to publish a bundle for that exact build, which is a
    # state conflict, not a malformed request. §5.1 forbids the alternative
    # ("if the bundle cannot be minted the route refuses rather than degrading"),
    # so this reason exists precisely so the refusal has somewhere honest to go.
    "gltf_not_published": 409,
    # The three opstore key refusals, each with its own meaning (§2.5):
    # `key_timestamp_skew` is a FIRST-SIGHT skew refusal (errors.py:39,
    # mcp/idempotency.py:180-185); `key_expired` is a key presented AFTER the
    # 30-day horizon (errors.py:27) and is never used for a freshness failure;
    # `key_payload_mismatch` (errors.py:31) is the same-key-different-payload
    # refusal, which is the one REST raises. MCP's own string for that condition
    # is the differently-named `idempotency_key_reuse` — the two transports keep
    # their own strings and neither is rewritten to match the other.
    "key_expired": 409,
    "key_timestamp_skew": 409,
    "key_payload_mismatch": 409,
    # 410 — a ref whose bytes are past retention.
    #
    # DEVIATION from INTERFACE.md §2.4, recorded rather than reconciled: the
    # table's row reads `snapshot_expired`, and no such reason exists anywhere in
    # the engine. The opstore's post-retention refusal is `artifact_expired`
    # (opstore/src/opstore/errors.py:69). §2.4's own rule — "the reason strings
    # above are the engine's, not this document's" — decides it: the engine wins.
    "artifact_expired": 410,
    # 429 — the 17th run against a 16-slot admission budget.
    "busy": 429,
    # 503 / 504 — the two bridge liveness terminals.
    "process_down": 503,
    "timeout": 504,
}

#: §2.4's last two rows — ``TIMEOUT`` / ``PROCESS_DOWN`` → 504 / 503 — name the
#: bridge's **numeric JSON-RPC codes** (``agent_bridge/protocol.py``:52-53), not
#: reason strings: the engine carries these conditions as codes and has no string
#: for them at all. The wire needs one, so it is the enum member name lowercased
#: — deterministic, greppable back to its source, and not a new concept. ``BUSY``
#: rides here too so a 17th-run refusal is a 429 whichever layer raises it
#: (``opstore.BusyError.code`` is already the string ``"busy"``).
PROTOCOL_CODE_REASON: Final[dict[int, str]] = {
    ErrorCode.TIMEOUT: "timeout",
    ErrorCode.PROCESS_DOWN: "process_down",
    ErrorCode.BUSY: "busy",
}


class HttpRefusal(Exception):
    """One mapped refusal: an HTTP status plus the §2.4 body it carries."""

    def __init__(
        self, status: int, reason: str, message: str, *, data: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message
        self.data: dict[str, Any] = dict(data or {})

    def body(self) -> dict[str, Any]:
        return error_body(self.reason, self.message, self.data)


def error_body(reason: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """The §2.4 envelope. ``reason`` and ``message`` always win over ``data``."""
    body: dict[str, Any] = dict(data or {})
    body.pop("status", None)
    body["status"] = "error"
    body["reason"] = reason
    body["message"] = message
    return body


def status_for_reason(reason: str) -> int:
    """The §2.4 status for an engine reason, with the fallback families named.

    The table above is the closed part. The engine's refusal vocabulary is
    larger than the table (every ``CadOpError`` reason, every ``RegistryError``
    reason), so two families carry the rest, and they are rules rather than a
    silent default:

    * anything spelled ``unknown_…`` or ``no_such_…`` is a **404** — it is an
      addressing miss by construction;
    * everything else reaching this function came through ``DispatchError`` or
      ``HephaestusError``, which are refusals of the *request*, so **400**.

    A refusal that deserves a different envelope earns a row in the table.
    """
    mapped = REASON_STATUS.get(reason)
    if mapped is not None:
        return mapped
    if reason.startswith(("unknown_", "no_such_")):
        return 404
    return 400


def refusal_for(exc: BaseException) -> HttpRefusal:
    """Map one engine exception onto its §2.4 status and body.

    Ordered most-specific first. Every branch keeps the engine's own reason
    string; none is rewritten, and none is collapsed into a neighbour.
    """
    if isinstance(exc, HttpRefusal):
        return exc
    if isinstance(exc, StaleSelectionError):
        # The five-value vocabulary rides as `reason` inside the payload when the
        # resolver supplies one (Stage 5's SelectionResolver, §19 item 8); the
        # envelope reason stays `stale_selection` so §2.4's row and G5.15's
        # enumeration are the same assertion.
        detail = getattr(exc, "reason", None)
        data: dict[str, Any] = {}
        if isinstance(detail, str) and detail in STALE_SELECTION_REASONS:
            data["stale_reason"] = detail
        return HttpRefusal(409, "stale_selection", str(exc), data=data)
    if isinstance(exc, SessionBusyError):
        return HttpRefusal(409, "session_busy", str(exc), data={"session_id": exc.session_id})
    if isinstance(exc, LimitError):
        return HttpRefusal(status_for_reason(exc.code), exc.code, exc.message)
    if isinstance(exc, DispatchError):
        # §2.4's "full refusal payload verbatim" is discharged here rather than by
        # a list of which reasons deserve it: `DispatchError.data` rides through
        # whole, so `part_busy`'s lease detail, `invalid_part`'s candidates, and
        # every other refusal's own fields reach the client intact. A curated set
        # of "verbatim reasons" would only be a second place to forget one.
        reason = exc.reason
        data = {k: v for k, v in exc.data.items() if k != "reason"}
        return HttpRefusal(status_for_reason(reason), reason, str(exc), data=data)
    if isinstance(exc, ProtocolError):
        reason = PROTOCOL_CODE_REASON.get(exc.code, "protocol_error")
        return HttpRefusal(status_for_reason(reason), reason, str(exc))
    if isinstance(exc, OpStoreError):
        return HttpRefusal(status_for_reason(exc.code), exc.code, exc.message)
    if isinstance(exc, HephaestusError):
        return HttpRefusal(status_for_reason(exc.code), exc.code, exc.message)
    raise exc


def capability_result(exc: DispatchError) -> dict[str, Any] | None:
    """The 200-status ``capability_error`` result for a capability refusal.

    ``tool_schema.md`` makes ``capability_not_available`` /
    ``image_model_required`` **discriminated results**, and dispatch already
    tags them (``dispatch.py`` puts ``code`` into ``DispatchError.data`` for
    exactly this). Returns ``None`` when this refusal is not one of them, so the
    caller falls through to :func:`refusal_for`.
    """
    code = exc.data.get("code")
    reason = code if isinstance(code, str) else exc.reason
    if reason not in CAPABILITY_REASONS:
        return None
    body: dict[str, Any] = {k: v for k, v in exc.data.items() if k not in ("reason", "code")}
    body["status"] = "capability_error"
    body["code"] = reason
    body["message"] = str(exc)
    return body
