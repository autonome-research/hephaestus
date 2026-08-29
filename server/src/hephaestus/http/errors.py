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
from hephaestus.agent_bridge.sessions import (
    RunInFlightError,
    SessionBusyError,
    StaleSelectionError,
)
from hephaestus.core.errors import HephaestusError
from opstore.errors import OpStoreError, ProtectedQuotaExceededError

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
    # §23.6's error mapping, 400 rows. Each is a NAMED refusal from §23.11's
    # closed vocabulary and none degrades to `invalid_params`.
    #
    # `allowlist_not_web_writable` is the one refusal without which the whole of
    # §23 is an exfiltration primitive: `credential_allowlist` and a spec's
    # `baseUrl` COMPOSE into arbitrary-environment-variable-to-arbitrary-host,
    # driven by a bearer token §23.13 concedes any page-script compromise holds.
    "allowlist_not_web_writable": 400,
    # …and its sibling, added by the 2026-08-28 credential ruling: an adopt body
    # carrying a filesystem path. A client-supplied path is what turns a
    # credential route into a traversal primitive.
    "path_not_web_writable": 400,
    "credential_scope_required": 400,
    "endpoint_not_loopback": 400,
    "egress_not_acknowledged": 400,
    "authorization_input_malformed": 400,
    # The `discovery_id` names no current offer (§23.6). Not `not_found`: the
    # handle is a capability this server minted and let expire, not an address.
    "discovery_source_unknown": 400,
    # The existing runtime refusal, hoisted to the route (§23.6): a spec whose
    # `credential` names a variable outside the on-disk allowlist. The web path
    # cannot add a name to that allowlist, which is the property mission rule 7
    # actually needs (§23.14 item 11).
    "credential_not_allowlisted": 400,
    # 401 — the only authentication this surface has.
    "unauthorized": 401,
    # 403 — dispatch's own object-scope and reviewer rules, unchanged.
    "scope_denied": 403,
    # §23.6's route-level precondition, checked at the route and not inherited.
    # §15.6 already says the serve is loopback-only; §23 re-checks it anyway on
    # the §2.6 pattern — a refusal a future configuration change could quietly
    # contradict is worse than no refusal, because a reader stops looking.
    "not_loopback": 403,
    # 404 — an unknown tool, part, or artifact.
    "unknown_tool": 404,
    "unknown_artifact": 404,
    "unknown_artifact_kind_for_route": 404,
    # §2.6's CORRECTION / §19.24: a ref whose kind segment disagrees with the
    # kind the store published its blob under. 404 rather than 403 because the
    # answer must not distinguish "you may not have this" from "this is not
    # here" — a 403 would confirm that the blob exists, which is precisely the
    # existence oracle §2.2 keeps this surface from being. It earns its own row
    # (the `unknown_`/`no_such_` family rule below would otherwise send it to
    # 400) because it is an addressing miss and not a malformed request.
    "artifact_kind_mismatch": 404,
    "unknown_part": 404,
    "not_found": 404,
    # §23.6's 404 row. `provider_unknown` and `model_unknown` are the engine's
    # own strings, reused rather than renamed (§23.11's "existing engine/runtime
    # codes reused").
    "provider_unknown": 404,
    "model_unknown": 404,
    # §22.3/§22.7: a blob no `COMMITTED` `tp_exports` row of the open project
    # names. Tabulated even though the `unknown_` family rule would already answer
    # 404, because §22.7's table states the status normatively and a reason whose
    # status is only implied is one refactor away from moving.
    "unknown_export": 404,
    # 413 — §22.4's ceiling. DEVIATION, recorded rather than reconciled: §2.4's
    # table has no row for this reason, because §22 is a later section than §2.4
    # and adds it. 413 rather than the fallback 400 for the same reason
    # `stale_selection` is a 409 and not a 400: the request is well formed and the
    # file exists — what fails is that this transport cannot carry it, which is
    # exactly what `Content Too Large` means. The refusal carries the size, the
    # ceiling and the on-disk path so the operator's next move is the CLI rather
    # than a retry that will fail identically.
    "export_too_large": 413,
    # §22.1's create-only collision, and a CORRECTION to that section's claim
    # that it is "**unreachable** from the browser by construction". It is not.
    # The no-target stem is content-addressed over the whole output set, so two
    # *fresh keys* over identical fields produce identical bytes, hence an
    # identical stem, hence `O_CREAT|O_EXCL` refusing the second — for the four
    # formats whose writers are byte-deterministic (stl, gltf/glb, 3mf, svg;
    # step and dxf stamp a wall-clock time into their own headers and so collide
    # with nothing). §22.2's TIGHTENING is what actually makes it unreachable:
    # the client mints one key per *submission* and the retry button does not
    # re-mint, so an unchanged resubmission is a ledger replay and never a second
    # execution. Since that is a client discipline rather than a construction,
    # the refusal has to be renderable, and it is named in the panel.
    #
    # 409 rather than the family fallback of 400: the request is well formed and
    # the server is healthy — what fails is that this exact file already exists,
    # which is a state conflict on the same footing as `session_busy`. No
    # existing test pins a status for this reason (the four that assert it read
    # `CadOpError.reason` off the dispatcher, below HTTP).
    "target_exists": 409,
    # 409 — refusals whose full payload rides through verbatim.
    "stale_selection": 409,
    "session_busy": 409,
    # §7A.5: a turn is already live where this one would run. A conflict on
    # live state, not a malformed request — and a REASON OF ITS OWN, never
    # folded into `session_busy`, which means a foreign lease holder owns the
    # session. The operator's remedy differs: wait or cancel, versus route
    # through the process that holds the lease.
    "run_in_flight": 409,
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
    # §23.0's attach, both of its refusals. 409 rather than 400 or 503, and the
    # reasoning is the same one that puts `session_busy` on this row: the request
    # is well formed and the server is healthy — what fails is a **state**
    # conflict. `attach_failed` is a serve whose provider configuration cannot
    # produce a sidecar right now (its closed `cause` says which), and
    # `agent_already_attached` is a serve that has one already. Neither is a
    # malformed request, and neither is `agent_unavailable`: §23.0's route table
    # puts `POST /providers/attach` in the row that **creates** a runtime, so
    # refusing it for the absence of one would restore the deadlock the route
    # exists to remove.
    "attach_failed": 409,
    "agent_already_attached": 409,
    # §23.6's 409 row. Each is a conflict on live credential state, not a
    # malformed request. `credential_rejected` carries §23.10's ruling that
    # "bad key" and "revoked key" are the SAME refusal: both are a 401 from the
    # provider, so inventing `credential_revoked` would be a distinction the
    # wire does not support, and a vocabulary that names a state it cannot
    # observe is worse than a coarse one that can.
    "auth_source_linked": 409,
    "login_already_in_progress": 409,
    "runs_in_flight": 409,
    "authorization_expired": 409,
    "authorization_state_mismatch": 409,
    "credential_rejected": 409,
    "credential_expired": 409,
    # The runtime's own code, now **per provider** (§23.7/§23.11): a declared
    # provider with no stored credential. 409 beside `credential_rejected`
    # because both are conflicts on credential state — one has no credential,
    # the other has one the provider refused — and neither is a malformed
    # request. It is NOT collapsed into `credential_rejected`: the operator's
    # remedy differs (sign in, versus rotate a key the provider rejected).
    "provider_not_authenticated": 409,
    # 422 — the provider offers sign-in flows, just not the one that was asked
    # for. Its own row because a silent substitution is what §23.6 forbids.
    "unsupported_auth_type": 422,
    # 429 — the PROVIDER's ceiling, deliberately distinct from §2.4's `busy`,
    # which is Hephaestus's own 16-slot admission ceiling. Collapsing the two
    # would tell an operator to wait for a queue that is not the one full.
    "provider_rate_limited": 429,
    # 502 — the provider could not be reached. Names the host and NEVER the
    # body: a provider's response text is the channel §23.6 exists to contain.
    "provider_unreachable": 502,
    # 503 — the session routes with no runtime behind them (§7A.8). Tabulated so
    # the reason has a status even where it is raised without one; the refusal
    # itself carries the closed `cause`, `config_path` and reduced `detail`.
    "agent_unavailable": 503,
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
    # 507 — §22.6 / §19.40's admission guard, now wired (`Publisher.freeze_inputs`
    # for builds, `ExportOps._guard_admission` for exports). DEVIATION, recorded
    # rather than reconciled: §2.4's table has no row for this reason either,
    # because §22 is a later section than §2.4 and adds it — §22.7's own table
    # carries it, with the note "(only once §19.40's guard is wired)".
    #
    # 507 rather than the fallback 400 or a 429: the request is well formed and
    # the server is healthy — what fails is that this project's *protected* bytes
    # already exceed its quota, so there is no room to produce the artifact. That
    # is `Insufficient Storage`, literally. Not 429: a 429 says "come back
    # later", and nothing about waiting changes this condition — the remedy is
    # `heph export unpin BLOB` or a larger quota, which is why the refusal
    # carries `usage` and why §19.40's CLI verbs had to exist before this row
    # could honestly be added.
    "protected_quota_exceeded": 507,
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
    if isinstance(exc, RunInFlightError):
        # §7A.5: the refusal names WHICH session holds the live run, because the
        # composer disables on it and a client needs the ids to offer a cancel.
        return HttpRefusal(
            409,
            "run_in_flight",
            str(exc),
            data={"session_id": exc.session_id, "run_id": exc.run_id, "scope": exc.scope},
        )
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
    if isinstance(exc, ProtectedQuotaExceededError):
        # §22.7: "the engine's reason verbatim, with `GcUsage`". The build path
        # raises this straight out of `Publisher.freeze_inputs` (core has no
        # `CadOpError` to wrap it in and inventing a core reason would be the
        # second name §22.6 forbids), so the numbers are attached here rather
        # than at four call sites. The export path reaches the same body through
        # `ExportOps._guard_admission` → `CadOpError` → `DispatchError`, whose
        # `data` rides through verbatim: one reason, one status, one payload
        # shape, two exception types because the two layers have two taxonomies.
        data = {} if exc.usage is None else {"usage": dict(exc.usage)}
        return HttpRefusal(status_for_reason(exc.code), exc.code, exc.message, data=data)
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
