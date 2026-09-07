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

import logging
import re
import uuid
from collections.abc import Sequence
from typing import Any, Final, cast

from hephaestus.agent_bridge.app import AgentUnavailableError, UnknownSessionError
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.limits import LimitError
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
from hephaestus.agent_bridge.sessions import (
    RunInFlightError,
    SessionBusyError,
    StaleSelectionError,
)
from hephaestus.agent_bridge.supervisor import SupervisorError
from hephaestus.core.errors import HephaestusError
from opstore.errors import OpStoreError, ProtectedQuotaExceededError

from .agent_attach import ATTACH_CAUSES, DETAIL_MAX_CHARS, reduce_detail, reduce_text

__all__ = [
    "CAPABILITY_REASONS",
    "CLIP_MARKER",
    "INTERNAL_ERROR_MESSAGE",
    "PROTOCOL_CODE_REASON",
    "REASON_STATUS",
    "REFUSAL_VALUE_MAX_CHARS",
    "SIDECAR_REFUSALS",
    "STALE_SELECTION_REASONS",
    "HttpRefusal",
    "capability_result",
    "clip_text",
    "error_body",
    "internal_error",
    "refusal_for",
    "router_refusal",
    "status_for_reason",
]

#: Where the ``internal_error`` incident id and its traceback are joined. Named
#: rather than the module ``__name__`` so an operator has one logger to raise.
_LOG: Final[logging.Logger] = logging.getLogger("hephaestus.http")

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
    # §2.9's git family, audit-2026-09-04 J-http-envelope-14. All five were
    # raised with a status written as a literal at the raise site and had no row
    # here, so :func:`status_for_reason` answered 400 for every one of them and
    # disagreed with the wire on three. The literals are gone
    # (``git_projection`` now looks each status up here) and the reasoning for
    # each status is recorded where every other reason's is:
    #
    # * `git_failed` — the subcommand ran and exited non-zero. A refusal of the
    #   *request* (a bad revision, an unknown path), so 400 with the family.
    # * `git_timeout` — the subcommand exceeded `GIT_TIMEOUT_SECONDS`. 504
    #   beside the bridge's own `timeout` row and for the same reason: a
    #   deadline crossed is not a malformed request, and the remedy is to wait
    #   or to ask for less, not to fix the arguments.
    "git_failed": 400,
    "git_timeout": 504,
    # 401 — the only authentication this surface has.
    "unauthorized": 401,
    # 403 — dispatch's own object-scope and reviewer rules, unchanged.
    "scope_denied": 403,
    # §23.6's route-level precondition, checked at the route and not inherited.
    # §15.6 already says the serve is loopback-only; §23 re-checks it anyway on
    # the §2.6 pattern — a refusal a future configuration change could quietly
    # contradict is worse than no refusal, because a reader stops looking.
    "not_loopback": 403,
    # §2.9's enumeration refusal: a verb outside `ALLOWED_SUBCOMMANDS`. 403 and
    # not 400 because the request is well formed and the server is healthy —
    # what fails is that the workspace *may not* run it, which is the same fact
    # `scope_denied` states one row above.
    "git_verb_refused": 403,
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
    # §2.9: the project root is not inside a git work tree. An addressing miss
    # on the project's OWN state — the answer to "show me this project's
    # history" is that there is no history to address — so it sits with the
    # other 404s rather than reading as a malformed request.
    "not_a_git_repository": 404,
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
    # §2.7/§7A.6's three session-scoped addressing misses, tabulated for the
    # same reason `unknown_export` is, and now for a second one: the standing
    # guard in `server/tests/test_http_errors.py` asserts that **every** reason
    # this package raises with a literal name has a row here, so the table can
    # be read as the complete set §2.4 presents it as. Each would already reach
    # 404 through the `unknown_` family rule below; a status that is only
    # implied is one refactor away from moving (audit-2026-09-04
    # J-http-envelope-12, -18).
    #
    # * `unknown_session` — the id names no session this project knows, from
    #   the thread route's durable check and from the sidecar's own refusal
    #   (`SIDECAR_REFUSALS` below), which is why it is not a synonym for
    #   `not_found`.
    # * `unknown_run` — a cancel for a run this server never issued. §2.3's
    #   idempotence is a property of a *run's lifecycle*, not a licence to
    #   accept an unknown address, so a finished run is still 200 and an
    #   unissued one is this.
    # * `unknown_question` — an `ask_user` id that is neither live nor in the
    #   bounded settled map: answered long ago and evicted, abandoned, or never
    #   asked. §7A.6 reads it as exactly that disjunction.
    "unknown_session": 404,
    "unknown_run": 404,
    "unknown_question": 404,
    # §2.4, amended 2026-09-04 (J-http-envelope-18): the size refusals, decided
    # ON PURPOSE rather than left as one careful row and two literals.
    #
    # The **request** rungs are 400/413 and the split is the point. A string
    # inside a well-formed body that exceeds the per-value cap is a
    # malformed-by-size *input*, refused before anything executes, so it sits
    # with `invalid_params` at 400 — that is `json_string_too_large`, raised as
    # a `LimitError` by the shared bounded walk, and `prompt_too_large`, which
    # is the §7A.4 `text` cap the prompt route now applies. A **body** past the
    # transport ceiling is different in kind: nothing about it has been parsed,
    # and the server is declining to carry it at all, which is literally what
    # `Content Too Large` means — so `request_too_large` is 413 beside
    # `export_too_large`, and neither is the fallback 400.
    # The other four rungs of the same structural walk. They reached 400 through
    # the fallback and agreed with it, which is precisely why nobody noticed
    # they were untabulated: `status_for_reason` answering correctly by accident
    # is what the fallback is *for*, and it is not a row. The standing guard in
    # `server/tests/test_http_errors.py` cannot see them either — they are
    # raised as `LimitError(code, ...)` and re-wrapped with a computed reason —
    # so a row here is the only place their status can be stated at all.
    "json_too_deep": 400,
    "json_too_many_members": 400,
    "json_array_too_long": 400,
    "json_string_too_large": 400,
    "prompt_too_large": 400,
    "request_too_large": 413,
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
    # The sidecar's own conflict on a caller-chosen session id (`main.ts`'s
    # `session.create` handler, over `SessionService.create`): that id is
    # already live in this runtime. A conflict on existing state, on the same
    # footing as `target_exists` directly above — not a malformed request (the
    # id is well-formed and the caller may legitimately want the session that
    # already bears it) and emphatically not a server fault.
    "session_exists": 409,
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
    # §2.9: `git` is not installed. 503 beside the other runtime-absence reasons
    # (`agent_unavailable`, `process_down`): a dependency this process needs is
    # not present, which is a fact about the server rather than the request.
    "git_unavailable": 503,
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
    # §2.4, amended 2026-09-04 — the three rows the ROUTER and the server-fault
    # path need. Until they existed, a route miss, a wrong method and every
    # unmapped exception left this process without an envelope at all: Starlette
    # answered `text/plain` with no `status`, no `reason` and no `message`, and
    # `web/src/api/client.ts` turned all three into an unnamed `transport_error`
    # — the exact condition §2.4's 2026-09-03 amendment exists to make
    # impossible. They are tabulated here, beside the engine's own reasons, and
    # the first two are *this layer's* strings on purpose: no engine raises
    # them, because the condition is "no engine code ran at all".
    #
    # No route matched. NOT the `unknown_`/`no_such_` family fallback and not
    # `not_found`: `not_found` is an addressing miss inside the project (a part,
    # an artifact), while this one says the ADDRESS SPACE has no such route —
    # different remedies (fix the id, versus fix the URL), and §2.4's rule that
    # two conditions with different remedies never share a reason applies to
    # this pair exactly as it does to `unknown_session`/`agent_unavailable`.
    "unknown_route": 404,
    # The route exists and does not serve this method. Its refusal MUST keep the
    # `Allow` header the router attaches (see `router_refusal`): the envelope is
    # an addition to that header, never a replacement for it.
    "method_not_allowed": 405,
    # The one reason in this table that is NOT the engine's, and the only one
    # that names the *absence* of an engine condition: an exception no branch of
    # `refusal_for` classified. Its message is fixed (`INTERNAL_ERROR_MESSAGE`)
    # and carries a correlation id instead of `str(exc)`, because this row is
    # reached only by exceptions nobody has classified and therefore nobody has
    # redacted — the same argument §23.6 makes for never echoing a provider's
    # error text back to a browser.
    "internal_error": 500,
    # Two 500s that are NOT `internal_error`: the sidecar classified them itself
    # (`main.ts`'s `currentRun`), so they keep their own name and their own
    # sentence. `internal_error`'s fixed message plus incident id is for
    # exceptions nobody has classified and therefore nobody has redacted; these
    # two are a run-attribution fault whose message ("no active run for tool
    # invocation", "ambiguous run … (N runs in flight)") is written by the code
    # that raises it, carries nothing from a provider or a filesystem, and is
    # the only thing that tells an operator which of the two happened.
    "no_active_run": 500,
    "ambiguous_run": 500,
}

#: ``INTERFACE.md`` §2.4, amended 2026-09-04: the refusals the **router** raises
#: before any endpoint runs, keyed by the status Starlette's own
#: ``HTTPException`` carries — which is the only fact this layer has about a
#: request that matched nothing.
_ROUTER_REASONS: Final[dict[int, str]] = {404: "unknown_route", 405: "method_not_allowed"}

#: The refusals the **sidecar** may name for itself, read off the JSON-RPC error
#: ``data.reason``. CLOSED, on exactly the discipline
#: ``http/agent_credentials.PROVIDER_REFUSALS`` already applies to §23.11's
#: vocabulary: a set a downstream process can add members to by answering with a
#: new string is not closed, and the whole value of a closed vocabulary is that
#: it is testable by enumeration. A reason outside it is not passed through — it
#: falls to the code-based branches below.
#:
#: ``invalid_cursor`` is §2.8's, raised by ``agent/src/main.ts``'s history
#: handler for a token that does not decode and for the mutually-exclusive
#: ``cursor``/``after`` pair; ``unknown_session`` is §2.4's, raised by the same
#: file's create handler for a ``resume`` naming a transcript that does not
#: exist. Both are *the sidecar's* refusals because both are questions only the
#: sidecar can answer — §2.8 forbids this layer from decoding a cursor, and
#: nothing above the sidecar knows which session directories exist.
#:
#: The other four are the same discipline applied to the refusals ``main.ts``
#: already had, which the 2026-09-04 structural fix would otherwise have
#: flattened into an opaque ``internal_error`` — a strictly *less* informative
#: answer than the one that shipped before it:
#:
#: * ``agent_unavailable`` — ``requireService``/``requireRuntime``: the child is
#:   answering, but it holds no runtime that can serve a turn (``configure`` has
#:   not run, or every declared provider failed §23.7 verification). §7A.8's
#:   availability condition, and the only thing an operator can act on, so it
#:   keeps §7A.8's 503 and its ``cause`` (see :func:`_agent_unavailable_data`).
#:   This is NOT the catch-all reintroduced: this layer still never *infers*
#:   ``agent_unavailable`` from an answered frame — the runtime states it, about
#:   itself, in the one place that knows.
#: * ``session_exists`` — a caller-chosen session id already live in the
#:   runtime: 409, the conflict family.
#: * ``no_active_run`` / ``ambiguous_run`` — ``currentRun``: a tool invocation
#:   that cannot be attributed to a run. Internal faults (500) that keep their
#:   own sentence, because the sentence is the whole diagnosis.
SIDECAR_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        "agent_unavailable",
        "ambiguous_run",
        "invalid_cursor",
        "no_active_run",
        "session_exists",
        "unknown_session",
    }
)

#: ``INTERFACE.md`` §2.4, amended 2026-09-04. The **fixed** sentence every
#: ``internal_error`` carries. Never ``str(exc)``: see the table row above.
INTERNAL_ERROR_MESSAGE: Final[str] = (
    "the server failed while handling this request; quote the incident id to "
    "join this refusal to the traceback in the server log"
)


#: The per-value ceiling every string in a §2.4 refusal body is bounded to
#: (audit-2026-09-04 J-http-limits-2). Two orders of magnitude above
#: :data:`~.agent_attach.DETAIL_MAX_CHARS` on purpose: a ``detail`` is one
#: operator sentence, while a refusal's ``data`` legitimately carries a
#: candidate list, a lease record or a stale-selection payload, and a bound
#: tight enough for the first would truncate the second. What it is sized
#: *against* is the amplifier: the largest string this surface admits is 16 MiB
#: (``json.max_string_bytes``), and this turns a 33.5 MB refusal into one under
#: eight kilobytes.
REFUSAL_VALUE_MAX_CHARS: Final[int] = 2048

#: What a clipped value says about itself. ``{dropped}`` is the character count
#: removed, so a reader can tell "this is the value" from "this is its head".
CLIP_MARKER: Final[str] = "…[{dropped} more characters clipped]"


#: The operator sentence every ``agent_unavailable`` this module mints carries.
#: Fixed, because the *variable* half — what the runtime actually said — is
#: ``detail``, which is bounded and redacted; putting the same text in both
#: fields (which is what an unbounded ``str(exc)`` message did) made one of them
#: a second, unbounded copy of the other (J-http-envelope-15).
_AGENT_UNAVAILABLE_MESSAGE: Final[str] = (
    "this server has no agent runtime that can serve the request; "
    "see `cause` for why and `detail` for what the runtime reported"
)


def internal_error(exc: BaseException) -> HttpRefusal:
    """§2.4's ``internal_error`` row: a fixed message plus a correlation id.

    The id is minted here and logged here **with the traceback**, so the two
    halves an operator has to join — the sentence a browser shows and the stack
    a server log holds — are written by one function and cannot drift. Nothing
    of ``exc`` crosses to the client: an exception that reached this row is one
    no branch of :func:`refusal_for` classified, so no branch has redacted it
    either, and §23.6's rule about never echoing an unredacted error text back
    to a browser is not weakened just because the text is ours.
    """
    incident = uuid.uuid4().hex[:12]
    _LOG.error("unhandled request failure (incident %s)", incident, exc_info=exc)
    return HttpRefusal(500, "internal_error", INTERNAL_ERROR_MESSAGE, data={"incident": incident})


def router_refusal(status: int, *, method: str, path: str) -> HttpRefusal | None:
    """§2.4's two router rows, or ``None`` for a status this table does not name.

    ``None`` rather than a guessed reason: the router raises exactly 404 and 405
    (Starlette's ``Router.not_found`` and ``Route.handle``), and no endpoint in
    this application raises an ``HTTPException`` of its own. Should one ever
    appear, it is a condition nobody classified, and the caller sends it to
    :func:`internal_error` rather than letting this function invent a name for
    it — the same reason :func:`refusal_for` ends in a bare ``raise``.
    """
    reason = _ROUTER_REASONS.get(status)
    if reason is None:
        return None
    message = (
        f"{method} {path} is not a route this server serves"
        if reason == "unknown_route"
        else f"{method} is not served at {path}"
    )
    return HttpRefusal(status, reason, message, data={"method": method, "path": path})


#: ``INTERFACE.md`` §2.4 (:709-711, :745-771), amended 2026-09-03. The exact
#: string ``main.ts``'s three ``unknown session '${sessionId}'`` throw sites
#: (``agent/src/main.ts:505,668,680``) put on the wire, so ``unknown_session``'s
#: ``session_id`` can be *recovered* from an engine message that is otherwise
#: opaque here — the same discipline as ``STALE_SELECTION_REASONS`` above:
#: the engine's own vocabulary, read rather than re-derived. This is NOT the
#: forbidden §2.8(3) recovery (stripping a "# Workspace context" heading from an
#: application-state-dependent block with no reliable terminator): this pattern
#: is the whole of a fixed, single-purpose RPC error message with one capture
#: group, written by the one function that raises it.
_UNKNOWN_SESSION_RE: Final[re.Pattern[str]] = re.compile(r"^unknown session '(.+)'$")

#: The exact string ``Supervisor._call`` (``agent_bridge/supervisor.py:566``) puts
#: on the wire for its own hard-wait backstop: ``f"{method} timed out after
#: {deadline_s}s with no response"``. Read rather than re-derived, on the same
#: discipline as ``_UNKNOWN_SESSION_RE`` above — a fixed, single-purpose message
#: with no ``error`` envelope (this raise never passes ``error=``), so it would
#: otherwise fall straight into the catch-all 503 below and mislabel a live but
#: slow sidecar as a dead one. §2.4 already has a row for this: ``timeout`` →
#: 504 (``REASON_STATUS["timeout"]`` above), the same status the bridge's own
#: ``ErrorCode.TIMEOUT`` protocol code maps to — a call that timed out because
#: the sidecar never answered is the same fact whether the deadline was caught
#: by the protocol layer or by this supervisor-level backstop, and the two must
#: not diverge into different statuses for what a client experiences identically.
_SUPERVISOR_TIMEOUT_RE: Final[re.Pattern[str]] = re.compile(
    r"^.+ timed out after .+s with no response$"
)


def _refusal_for_supervisor_error(exc: SupervisorError, secrets: Sequence[str]) -> HttpRefusal:
    """§2.4's two new rows, both reached only through :class:`SupervisorError`.

    **Preferred path.** ``agent_bridge/app.py`` already does the §2.8(6) work —
    one re-adoption attempt, then a named :class:`SessionRouteError` subclass
    (:class:`UnknownSessionError` / :class:`AgentUnavailableError`) carrying its
    own ``reason`` and ``session_id`` (and, for the latter, ``cause``). Reading
    those attributes is preferred over re-deriving the same fact from the raw
    JSON-RPC envelope, because the bridge is the one place that actually ran
    the re-adoption attempt and knows which of the two conditions it left
    behind; a second, independent classification here could disagree with it.

    **Fallback path.** A bare :class:`SupervisorError` that is *not* one of
    those subclasses — a call site that has not been routed through the
    bridge's naming yet, or a re-adoption-blind caller (``workflows.py``,
    the CLI) that lets the raw exception surface. ``exc.error`` is the
    sidecar's JSON-RPC error envelope, populated **only** when the failure is
    an *answered* refusal — ``Supervisor.call`` sets it exactly once, from a
    genuine ``{"error": …}`` response frame (``agent_bridge/supervisor.py:568``).
    Every other raise site in that module (no process, a failed write, an
    unanswered deadline, a respawn that gave up its budget) constructs a
    :class:`SupervisorError` with no ``error`` kwarg at all, so its absence is
    not a guess — it is the module's own distinction between "the sidecar
    answered with a refusal" and "there was no sidecar to answer".

    **That distinction is now load-bearing** (§2.4, amended 2026-09-04): an
    answered refusal is handed to :func:`_refusal_from_envelope` and can never
    be *classified as* ``agent_unavailable`` by this layer, and only the
    *unanswered* half — no envelope at all — reaches the two liveness branches
    at the end. An answered frame in which the sidecar names
    ``agent_unavailable`` about itself is a different thing entirely, and is
    read as the token it is (see :data:`SIDECAR_REFUSALS`).

    **``secrets`` is required, not defaulted** (audit-2026-09-04
    J-http-envelope-15). Both ``agent_unavailable`` branches used to build
    ``detail`` through :func:`~.agent_attach.reduce_detail` with the argument
    omitted — so the redaction loop iterated an empty sequence and did nothing —
    and put a raw, unbounded ``str(exc)`` in ``message`` beside the bounded
    detail. A silent default is what let that pass review, so this parameter has
    none: the caller must say which secrets this layer holds (``guarded`` passes
    the serve bearer, the one secret this process owns that a sidecar message
    could quote back), and passing ``()`` is then a visible claim rather than an
    omission.
    """
    if isinstance(exc, UnknownSessionError):
        return HttpRefusal(
            404, exc.reason, reduce_text(str(exc), secrets), data={"session_id": exc.session_id}
        )
    if isinstance(exc, AgentUnavailableError):
        return HttpRefusal(
            503,
            exc.reason,
            # The operator sentence and the engine text are DIFFERENT fields
            # with different jobs: `message` says what this server concluded,
            # `detail` is the reduced text the runtime produced. Both are
            # bounded and both are redacted; making them the same string would
            # be the duplication §2.4 already refuses elsewhere.
            _AGENT_UNAVAILABLE_MESSAGE,
            data={"cause": exc.cause, "detail": reduce_detail(exc, secrets)},
        )
    if exc.error:
        # **THE STRUCTURAL HALF** (§2.4, amended 2026-09-04). A populated
        # ``error`` is the supervisor's own proof that the sidecar *answered*:
        # ``Supervisor._call`` sets it exactly once, from a genuine
        # ``{"error": …}`` response frame, and every other raise site in that
        # module constructs the exception with no ``error`` kwarg at all. An
        # answer is proof of liveness, so this module can never *infer*
        # ``agent_unavailable`` from here — the mislabel is removed BY
        # CONSTRUCTION rather than by enumerating the messages that must not
        # reach it. That is the whole fix: before it, any answered refusal
        # this module had not been taught to name (a malformed history cursor,
        # most visibly) was reported as a dead runtime while the very next call
        # to the same process returned 200, and the panel told the operator to
        # attach a runtime that was already attached.
        #
        # AMENDED (2026-09-05): the rule is "never *inferred*", not "never
        # produced". A sidecar that answers ``data.reason:
        # "agent_unavailable"`` is stating, about itself, that it holds no
        # runtime that can serve a turn (``runtime.configure`` has not run, or
        # every declared provider failed §23.7 verification) — §7A.8's
        # availability condition, reported by the only process that knows it.
        # Reading that token is the same discipline as reading
        # ``invalid_cursor``; it is the *guess* the structural fix removed, and
        # the guess stays removed: an envelope that does not name the reason
        # still cannot reach 503 from this branch. Flattening these two into
        # ``internal_error`` instead was a strictly less informative answer
        # than the one that shipped before the fix — an opaque 500 with a fixed
        # sentence, where an operator previously got a 503 naming the runtime.
        return _refusal_from_envelope(exc, secrets)
    # A hard-wait timeout (no `error` envelope — see `_SUPERVISOR_TIMEOUT_RE`)
    # is a live, slow sidecar, not an unreachable one. Checked before the
    # catch-all below so it is never folded into `agent_unavailable`: the two
    # already have distinct §2.4 rows (`timeout` → 504, `agent_unavailable` →
    # 503) with different remedies (wait / retry, versus fix the runtime), and
    # this module must not re-collapse a distinction the bridge's own protocol
    # codes (`PROTOCOL_CODE_REASON[ErrorCode.TIMEOUT]` above) already keep.
    if _SUPERVISOR_TIMEOUT_RE.match(str(exc)):
        return HttpRefusal(504, "timeout", reduce_text(str(exc), secrets))
    # Everything else is *this runtime's* sidecar being unreachable: a spawn
    # that failed, a child that died with no respawn budget left, a call sent
    # into (or timed out against) a process that stopped answering. §7A.8's
    # closed `cause` vocabulary already has exactly the member for "the process
    # itself is the problem" (`ATTACH_CAUSES` in `agent_attach.py`), reused
    # rather than widened. `config_path` is deliberately absent: this module
    # never opens the providers file, and a client that got this far already
    # holds that value from the attach it made (`POST /providers/attach`,
    # §7A.8) — carrying a second copy here would be a value this refusal cannot
    # keep in sync with the one that matters.
    return HttpRefusal(
        503,
        "agent_unavailable",
        _AGENT_UNAVAILABLE_MESSAGE,
        data={"cause": "sidecar_failed", "detail": reduce_detail(exc, secrets)},
    )


def _refusal_from_envelope(exc: SupervisorError, secrets: Sequence[str]) -> HttpRefusal:
    """Name a refusal the sidecar **answered** with, from the frame's own fields.

    Ordered by how much the sidecar said, most explicit first, and every branch
    reads the engine rather than re-deriving it:

    1. ``data.reason`` inside :data:`SIDECAR_REFUSALS` — the sidecar named its
       own refusal, so this layer copies the token and forwards the rest of
       ``data`` as the refusal's body. This is the seam that lets §2.8's
       ``invalid_cursor`` be minted *in the sidecar* (the only place allowed to
       decode a cursor) and still arrive as a 400 with its own name; the closed
       set is what keeps a downstream process from widening §2.4's vocabulary
       by answering with a new string. ``agent_unavailable`` is the one member
       whose body is not forwarded verbatim — see
       :func:`_agent_unavailable_data` for why ``cause`` is re-checked here.
    2. the ``INVALID_PARAMS`` + ``unknown session '<id>'`` shape, for the three
       ``main.ts`` throw sites that carry no ``data`` (see
       :data:`_UNKNOWN_SESSION_RE`).
    3. a bridge protocol code that already has a §2.4 row
       (:data:`PROTOCOL_CODE_REASON`).
    4. anything else: the sidecar answered with a fault nobody has classified,
       which is exactly what ``internal_error`` names. A 500 rather than the old
       503 is the honest half of the fix — "this server failed" is true, "this
       server has no runtime" was not.
    """
    error = exc.error
    raw = error.get("data")
    fields: dict[str, Any] = (
        {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if isinstance(raw, dict)
        else {}
    )
    named = fields.get("reason")
    if isinstance(named, str) and named in SIDECAR_REFUSALS:
        raw_message = error.get("message")
        raw_text = raw_message if isinstance(raw_message, str) and raw_message else str(exc)
        # The sidecar is another process: its sentence is foreign text on the
        # same footing as a provider's or git's, so it is bounded and redacted
        # before it becomes a wire message (J-http-envelope-15).
        text = reduce_text(raw_text, secrets)
        data = {k: v for k, v in fields.items() if k != "reason"}
        if named == "agent_unavailable":
            data = _agent_unavailable_data(data, text)
        return HttpRefusal(status_for_reason(named), named, text, data=data)
    code = error.get("code")
    message = error.get("message")
    if code == ErrorCode.INVALID_PARAMS and isinstance(message, str):
        match = _UNKNOWN_SESSION_RE.match(message)
        if match is not None:
            return HttpRefusal(
                404,
                "unknown_session",
                reduce_text(message, secrets),
                data={"session_id": match.group(1)},
            )
    reason = PROTOCOL_CODE_REASON.get(code) if isinstance(code, int) else None
    if reason is not None:
        return HttpRefusal(status_for_reason(reason), reason, reduce_text(str(exc), secrets))
    return internal_error(exc)


def _agent_unavailable_data(fields: dict[str, Any], message: str) -> dict[str, Any]:
    """§7A.8's body for an ``agent_unavailable`` the **sidecar** named.

    Three rules, and each is the one §2.4/§7A.8 already states for this refusal
    raised anywhere else — restated here because the value now arrives from
    another process:

    * ``cause`` is checked against :data:`~.agent_attach.ATTACH_CAUSES` and
      falls back to ``sidecar_failed``. The vocabulary is closed, and a set a
      downstream process can add a member to by answering with a new string is
      not closed — the same argument ``agent_credentials._reason_of`` makes for
      §23.11's codes, applied to the one field this refusal is dispatched on.
    * ``detail`` is guaranteed. §2.4's 2026-09-03 RECONCILIATION says this
      refusal carries ``cause`` **and** ``detail``; the sidecar's own sentence
      is the honest value, bounded by ``DETAIL_MAX_CHARS`` for the same reason
      :func:`~.agent_attach.reduce_detail` bounds its own — a refusal is a
      sentence for an operator, not a log.
    * ``config_path`` is dropped if a future sidecar ever sends one. The same
      RECONCILIATION is explicit that this path does not carry it: this layer
      cannot keep such a value in sync, and "a stale ``config_path`` is worse
      than an absent one, because a client would act on it".
    """
    cause = fields.get("cause")
    detail = fields.get("detail")
    return {
        **{k: v for k, v in fields.items() if k not in ("cause", "detail", "config_path")},
        "cause": cause if isinstance(cause, str) and cause in ATTACH_CAUSES else "sidecar_failed",
        "detail": (detail if isinstance(detail, str) and detail else message)[:DETAIL_MAX_CHARS],
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


def clip_text(value: str) -> str:
    """One string, bounded to :data:`REFUSAL_VALUE_MAX_CHARS`, **marked** if cut.

    Marked and not silently shortened: §2.4's whole discipline is that a client
    is told what happened, and a value quietly returned three characters shorter
    than it was sent is the silence :mod:`hephaestus.http.context` refuses one
    layer up (its ``TRUNCATION_MARKER`` sets the same precedent for the composed
    block).
    """
    if len(value) <= REFUSAL_VALUE_MAX_CHARS:
        return value
    dropped = len(value) - REFUSAL_VALUE_MAX_CHARS
    return value[:REFUSAL_VALUE_MAX_CHARS] + CLIP_MARKER.format(dropped=dropped)


def _clipped(value: Any) -> Any:
    """:func:`clip_text` over one ``data`` value, recursing into containers."""
    if isinstance(value, str):
        return clip_text(value)
    if isinstance(value, dict):
        return {k: _clipped(v) for k, v in cast("dict[Any, Any]", value).items()}
    if isinstance(value, list):
        return [_clipped(item) for item in cast("list[Any]", value)]
    if isinstance(value, tuple):
        return [_clipped(item) for item in cast("tuple[Any, ...]", value)]
    return value


def error_body(reason: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """The §2.4 envelope. ``reason`` and ``message`` always win over ``data``.

    **Bounded** (``INTERFACE.md`` §2.4, audit-2026-09-04 J-http-limits-2). Every
    refusal that interpolates a client string into both its sentence and its
    machine payload was an amplifier: a context preview naming a 16 MiB part
    returned a 33.5 MB 404 — a ratio of exactly 2.00, because the same string
    was written twice. Clipping happens **here**, at the one function every
    refusal body goes through, rather than at each of the dozens of raise sites
    that interpolate an argument, because a per-site clip is a rule the next
    refusal does not inherit.

    ``reason`` is deliberately **not** clipped: it is a closed vocabulary whose
    every member is short, and a truncated reason would be a token no client can
    dispatch on. ``status`` is this module's own literal.
    """
    body: dict[str, Any] = {k: _clipped(v) for k, v in (data or {}).items()}
    body.pop("status", None)
    body["status"] = "error"
    body["reason"] = reason
    body["message"] = clip_text(message)
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


def refusal_for(exc: BaseException, *, secrets: Sequence[str] = ()) -> HttpRefusal:
    """Map one engine exception onto its §2.4 status and body.

    Ordered most-specific first. Every branch keeps the engine's own reason
    string; none is rewritten, and none is collapsed into a neighbour.

    ``secrets`` are the values *this process holds* that a message from another
    process could quote back — the serve bearer, in practice. They reach only
    the branches whose text came from somewhere else (the sidecar's); every
    other branch's message was written in this repository and has nothing to
    redact. Defaulted to empty because most callers are exercising an engine
    exception with no foreign text in it at all; ``build_app``'s guard, which is
    the one path a browser reaches, passes the bearer explicitly.
    """
    if isinstance(exc, HttpRefusal):
        return exc
    if isinstance(exc, SupervisorError):
        # §2.4, amended 2026-09-03: the two named rows a session route reaches
        # when a call for a session the runtime lists fails at the bridge.
        # Placed before every ``HephaestusError``-family branch below because
        # ``SupervisorError`` is not one of that hierarchy and, unhandled here,
        # falls all the way to the bare ``raise exc`` — which is exactly how an
        # intact 29 KB transcript became a permanent unnamed 500 (§2.4's own
        # amendment note).
        return _refusal_for_supervisor_error(exc, secrets)
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
