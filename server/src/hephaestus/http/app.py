# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``server/http`` — the workspace API, as a closed route table.

``INTERFACE.md`` §2.3. Every route is ``/api/v1/…``, bearer-authenticated, JSON
except where noted. **A route not listed here is not Stage 4/5 work.** The prefix
is versioned because this is a client API, not the headless surface, and a
version segment is the cheapest way to keep it from calcifying into one.

Absent, deliberately: no ``POST /artifacts`` (the workspace mints nothing), no
``DELETE`` anywhere, and no route that takes a raw filesystem path in a request
body.

**Export/drawing/document routes exist as of Stage 10A** (``INTERFACE.md`` §22,
approved 2026-08-28). What §15.17 refused was two decisions welded together — a
*mechanism* decision (close ``/artifacts/{ref}/bytes`` by enumeration) and a
*product* decision (no export affordance); the product owner answered the second
and the first is untouched. ``/artifacts/{ref}/bytes`` still refuses an
``export``-kind ref by enumeration **and** refuses an export blob wearing another
kind's label by the store's own publication record (§19.24,
:mod:`hephaestus.http.artifacts`). Egress has its own third route with its own,
strictly narrower authorization (:mod:`hephaestus.http.exports`).

**Every tool route goes through** :meth:`ToolDispatcher.dispatch` **— there is no
bypass** (§2.2). Nothing in this module computes a result; it validates a
request, applies the §2.5 key ladder, calls dispatch, and maps refusals through
§2.4. That is the whole of mission rule 6 as it applies here, and
``server/tests/test_http_boundary.py`` asserts it mechanically rather than
trusting this paragraph.

The framework is **Starlette**, not FastAPI. ``INTERFACE.md`` §2 names no
framework; Starlette is already in the dependency graph as the transport
``fastmcp`` serves streamable HTTP on, so ``heph serve --mcp --web`` runs one
HTTP stack in one process rather than two. Adding FastAPI would be a second web
framework with no gate behind it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from itertools import count
from typing import Any, Final, cast

from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.limits import LimitError, validate_json_structure
from hephaestus.agent_bridge.project_projections import (
    list_parts_projection,
    open_project_projection,
)
from hephaestus.agent_bridge.serve_record import WORKSPACE_API_PREFIX
from hephaestus.agent_bridge.supervisor import SupervisorError
from hephaestus.contract import toolgen
from hephaestus.contract.tools_decl import READ_ARTIFACT_PAGE_MAX, TOOLS_BY_NAME
from hephaestus.core.checks.report import project_check_report
from hephaestus.mcp.validate import SchemaError, normalize_arguments
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route, WebSocketRoute
from starlette.websockets import WebSocket

from . import agent_attach, providers
from . import git_projection as git
from .agent_attach import AgentAlreadyAttached, AttachRefused
from .agent_credentials import (
    apply_credential_change,
    credentials_or_refuse,
    relay_async,
    runs_in_flight_or_refuse,
)
from .artifacts import (
    GLTF_KIND,
    artifact_bytes,
    artifact_meta,
    artifact_text_page,
    mime_for_kind,
)
from .context import compose_context, parse_envelope
from .errors import HttpRefusal, capability_result, error_body, refusal_for
from .events_ws import serve_events
from .exports import (
    EXPORT_ROUTE_TOOLS,
    export_arguments,
    export_bytes,
    exports_projection,
)
from .geometry import BUNDLE_HEADER, SOURCE_HEADER, gltf_for_ref
from .idempotency import (
    REPLAYED_FIELD,
    REPLAYED_HEADER,
    RestKeyError,
    require_key,
    rest_invocation,
    rest_payload_hash,
)
from .principal import verify_token
from .projections import (
    build_projection,
    checks_projection,
    params_projection,
    properties_projection,
)
from .runtime import WorkspaceRuntime
from .sessions import (
    QUICK_EDIT_PROFILE,
    SESSION_PROFILES,
    WorkspaceSessions,
    thread_projection,
)

__all__ = ["API_PREFIX", "ROUTE_TABLE", "WEBSOCKET_ROUTES", "build_app"]

#: Versioned because this is a client API, not the headless surface (§2.3).
#: Declared below both verbs (:mod:`hephaestus.agent_bridge.serve_record`) so the
#: server that serves it and the ``heph agent`` client that calls it read one
#: constant — a client-mode CLI spelling the prefix itself would be a second copy
#: of a versioned surface.
API_PREFIX: Final[str] = WORKSPACE_API_PREFIX

#: Immutable, content-addressed refs make this honest rather than optimistic.
_IMMUTABLE_CACHE: Final[str] = "public, max-age=31536000, immutable"

#: §22.3: the same immutability, **privately**. An export byte response is
#: fetched with the workspace bearer in an `Authorization` header, and a shared
#: cache is the one place that pair should never land.
_EXPORT_CACHE: Final[str] = "private, max-age=31536000, immutable"

#: The closed route table, as ``(method, template)`` pairs. Kept as data so the
#: §1 boundary test can assert the served surface *is* this list — a route added
#: to the app without a row here fails a test rather than shipping quietly.
ROUTE_TABLE: Final[tuple[tuple[str, str], ...]] = (
    # Project and parts (read, no idempotency key)
    ("GET", "/project"),
    ("GET", "/parts"),
    ("GET", "/parts/{part}/script"),
    ("GET", "/parts/{part}/build"),
    ("GET", "/parts/{part}/properties"),
    ("GET", "/parts/{part}/checks"),
    ("GET", "/parts/{part}/params"),
    ("GET", "/parts/{part}/dfm"),
    ("GET", "/checks"),
    # Artifacts
    ("GET", "/artifacts/{ref}/meta"),
    ("GET", "/artifacts/{ref}/text"),
    ("GET", "/artifacts/{ref}/bytes"),
    ("GET", "/artifacts/{ref}/gltf"),
    # Egress (§22, Stage 10A). The export **history** and the export **bytes**,
    # both reads. The bytes route is addressed by blob hash rather than by an
    # artifact ref — `export_hashes` is what the mutation returned and
    # `artifact:export:…` is a ref production does not mint — and it is
    # authorized by a `COMMITTED` `tp_exports` row, which is strictly narrower
    # than `/artifacts/{ref}/bytes`'s reachability check. That narrowness is why
    # it can exist without widening anything (§22.3).
    ("GET", "/parts/{part}/exports"),
    ("GET", "/exports/{export_blob}/bytes"),
    # Inspection and measurement (POST because their argument documents exceed
    # what a query string should carry; they take NO key — the key policy is per
    # route, not per HTTP verb).
    ("POST", "/parts/{part}/inspect"),
    ("POST", "/measure"),
    # The composer's "what will the agent be told?" disclosure (§7A.3, §19.20).
    # Project-scoped for the same reason `measure` is: its operands span parts
    # and artifacts and a session id is not among them. Read, no key — it
    # **starts no run and calls no tool**, which is the whole difference between
    # it and the prompt route it previews.
    ("POST", "/context/preview"),
    # Mutations — Idempotency-Key required, replayed byte-for-byte (§2.5)
    ("PUT", "/parts/{part}/script"),
    ("PATCH", "/parts/{part}/script"),
    ("POST", "/parts/{part}/params"),
    ("POST", "/parts/{part}/build"),
    ("POST", "/parts/{part}/dfm"),
    ("POST", "/project/config/dfm"),
    ("POST", "/git/tag"),
    # Egress, the writing half (§22.2, §22.3). Three keyed mutations that return
    # a result document and **no bytes**: collapsing production and download into
    # one response would make a retried *download* re-enter a keyed *mutation*,
    # would put a multi-megabyte binary where §2.4's refusal payload has to fit,
    # and would make "the export failed" and "the transfer failed" the same
    # event. Two steps, two failures, two error messages.
    ("POST", "/parts/{part}/export"),
    ("POST", "/parts/{part}/drawing"),
    ("POST", "/parts/{part}/doc"),
    # Streams, history, threading (§2.7, §2.8). `GET /events` is the WebSocket
    # upgrade; it is a row of this table like any other, and is served through
    # `WEBSOCKET_ROUTES` below rather than as an HTTP verb.
    ("GET", "/events"),
    ("GET", "/sessions"),
    ("GET", "/sessions/{id}/history"),
    ("GET", "/sessions/{id}/thread"),
    # Provider attachment (§23.0). Keyless for the same reason session control
    # is (see `CREDENTIAL_ROUTES`), and deliberately in the row of §23.0's table
    # that needs **no** sidecar: this route is the one that *creates* one, so
    # refusing it `agent_unavailable` would be the deadlock §23.0 exists to
    # remove.
    ("POST", "/providers/attach"),
    # Provider sign-in (§23.6). Split by dependency exactly as §23.0's table
    # splits it: `GET /providers` and `PUT /providers/specs` read and write a
    # FILE and stay serviceable with no sidecar; `/catalog` and every `auth/*`
    # row is a relay to Pi and refuses `agent_unavailable` when there is none.
    # Every row carries the route-level `not_loopback` precondition.
    ("GET", "/providers"),
    ("PUT", "/providers/specs"),
    ("GET", "/providers/catalog"),
    ("GET", "/providers/{id}/auth/status"),
    ("POST", "/providers/{id}/auth/key"),
    ("POST", "/providers/{id}/auth/begin"),
    ("POST", "/providers/{id}/auth/complete"),
    ("POST", "/providers/{id}/auth/cancel"),
    ("POST", "/providers/{id}/auth/signout"),
    ("POST", "/providers/auth/unlink"),
    # Credential discovery — Stage 10C (§23.5). `discover` is a POST despite
    # being a read so that reading the operator's home directory can never be
    # something a page issues incidentally; `adopt` is the one explicit act, and
    # its body carries the server-minted handle and nothing else.
    ("POST", "/providers/discover"),
    ("POST", "/providers/adopt"),
    # Session control — Idempotency-Key NOT required, and a supplied one is
    # ignored rather than honoured (§2.3, second table). Session control is not a
    # source/config/output mutation, and §2.5's byte-for-byte replay is incoherent
    # for a route whose whole meaning is a side effect on a live run.
    ("POST", "/sessions"),
    ("POST", "/sessions/{id}/prompt"),
    ("POST", "/sessions/{id}/answer"),
    ("POST", "/runs/{run_id}/cancel"),
    # Git projection (read)
    ("GET", "/git/status"),
    ("GET", "/git/log"),
    ("GET", "/git/diff"),
    ("GET", "/git/tags"),
)

#: The rows of :data:`ROUTE_TABLE` served as WebSocket upgrades rather than as
#: HTTP verbs. Kept as data beside the table so the §1 boundary test can assert
#: the served surface is the table across *both* transports.
WEBSOCKET_ROUTES: Final[tuple[str, ...]] = ("/events",)


# --------------------------------------------------------------------------
# request plumbing
# --------------------------------------------------------------------------


def _authorize(request: Request, runtime: WorkspaceRuntime) -> None:
    """The whole of this layer's authn: one bearer, constant-time compared.

    Without a token the app renders one non-interactive panel explaining how to
    obtain one; it never prompts for credentials, because there are none to
    prompt for (§2.2). No login, no cookie, no refresh, no user model.
    """
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value or not verify_token(value.strip(), runtime.token):
        raise HttpRefusal(401, "unauthorized", "a valid bearer token is required")


async def _json_body(request: Request) -> dict[str, Any]:
    """Parse the request body **as bytes**, then validate scalars ourselves.

    §2.5: payload hashing is byte-faithful — no Unicode normalization (NFC ≠
    NFD) — and unpaired surrogates are refused as ``invalid_unicode_scalar``
    *before* sizing and hashing. A JSON runtime that substituted U+FFFD would
    silently break the Stage 3 parity suite, so the decode is strict and the
    parsed document is walked by
    :func:`hephaestus.agent_bridge.limits.validate_json_structure`, which is the
    same bounded walk the bridge boundary runs (and which raises
    ``invalid_unicode_scalar`` for a ``\\uD800`` escape that survived JSON
    parsing as a lone surrogate).
    """
    raw = await request.body()
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HttpRefusal(400, "invalid_params", f"request body is not valid UTF-8: {exc}") from exc
    try:
        parsed: Any = json.loads(text)
    except ValueError as exc:
        raise HttpRefusal(400, "invalid_params", f"request body is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HttpRefusal(400, "invalid_params", "request body must be a JSON object")
    body = cast("dict[str, Any]", parsed)
    try:
        validate_json_structure(body)
    except LimitError as exc:
        raise HttpRefusal(400, exc.code, exc.message) from exc
    return body


def _int_param(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise HttpRefusal(400, "invalid_params", f"{name} must be an integer") from exc


def _part(request: Request) -> str:
    return str(request.path_params["part"])


def _session(request: Request) -> str:
    return str(request.path_params["id"])


def _ref(request: Request) -> str:
    return str(request.path_params["ref"])


def _attach_data(runtime: WorkspaceRuntime) -> dict[str, Any]:
    """The §7A.8 attach projection for a refusal's ``data``, or ``{}``.

    Empty only when **nothing in this process has attempted an attach** — a
    state a real serve is never in, because ``heph serve --web`` attaches at
    start-up and records the outcome either way. An in-process harness that
    never attached gets no cause rather than a guessed one: §7A.8's vocabulary
    answers "why did the attach produce nothing", and inventing an answer where
    there was no attempt would be the fabricated content §4.4 forbids.
    """
    state = runtime.agent_attach_state()
    return {} if state is None else state.projection()


def _attach_generation(runtime: WorkspaceRuntime) -> int:
    state = runtime.agent_attach_state()
    return 0 if state is None else state.generation


# --------------------------------------------------------------------------
# dispatch — the one path to the engine
# --------------------------------------------------------------------------


class _Api:
    """The route handlers, bound to one :class:`WorkspaceRuntime`."""

    def __init__(self, runtime: WorkspaceRuntime) -> None:
        self.runtime = runtime
        # tool_schema.md: mutating/stateful tools declare sequential execution.
        # The same lock the MCP app takes, for the same reason.
        self._sequential = asyncio.Lock()
        self._reads = count()

    # -- the single engine entry point ------------------------------------

    async def dispatch(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        entry_id: str,
        run_id: str,
    ) -> Any:
        """Validate against the canonical schema, then ``ToolDispatcher.dispatch``.

        The argument document is normalized by the *same* validator the MCP
        boundary runs (``hephaestus.mcp.validate``), so declared defaults are
        materialized identically on both transports and a payload hash over the
        normalized document means the same thing on each. There is no second
        schema, no second default table, and no HTTP-only coercion.
        """
        decl = TOOLS_BY_NAME.get(tool)
        if decl is None:  # pragma: no cover - every call site names a declared tool
            raise HttpRefusal(404, "unknown_tool", f"no such tool: {tool!r}")
        parameters = cast("dict[str, Any]", toolgen.mcp_declaration(decl)["inputSchema"])
        try:
            normalized = normalize_arguments(parameters, arguments)
        except SchemaError as exc:
            raise HttpRefusal(400, "invalid_params", str(exc)) from exc
        except LimitError as exc:
            raise HttpRefusal(400, exc.code, exc.message) from exc

        principal = self.runtime.dispatch_principal()
        params: dict[str, Any] = {
            "session_id": principal.session_id,
            "run_id": run_id,
            "tool": tool,
            "arguments": normalized,
            "invocation": {
                "session_id": principal.session_id,
                "entry_id": entry_id,
                "ordinal": 0,
                "provider_call_id": "rest",
            },
        }

        def run() -> Any:
            return self.runtime.dispatcher.dispatch(principal, params)

        if decl.sequential:
            async with self._sequential:
                return await asyncio.to_thread(run)
        return await asyncio.to_thread(run)

    async def read_tool(self, tool: str, arguments: dict[str, Any]) -> Any:
        """A keyless tool call (a read, an inspection, a measurement).

        These routes take **no** ``Idempotency-Key``: §2.3's key policy is per
        route, not per HTTP verb, and a read has nothing to replay. The entry id
        is a per-process counter rather than anything derived from the request,
        so two concurrent reads never share an invocation identity — none of
        these tools is an idempotency-contract member, but an identity that can
        collide is not one to hand a dispatcher.
        """
        return await self.dispatch(
            tool,
            arguments,
            entry_id=f"read:{tool}:{next(self._reads)}",
            run_id=f"web-{tool}",
        )

    async def keyed_mutation(
        self,
        request: Request,
        *,
        template: str,
        tool: str,
        arguments: dict[str, Any],
        after: Callable[[Any], None] | None = None,
    ) -> Response:
        """One row of §2.3's first table: the ladder, the call, the recorded body.

        Order matters and is the contract: the key is validated **before**
        anything executes (a missing or malformed key is "no execution"), the
        ladder claim happens **before** dispatch, and the body is recorded only
        after dispatch returns. A refusal raised mid-flight leaves an
        uncommitted claim, which does not block a corrected retry — the durable
        mutation authority is the core WAL keyed by the same invocation id.
        """
        method = request.method
        key = require_key(request.headers.get("idempotency-key"), method=method, template=template)
        digest = rest_payload_hash(
            project=str(self.runtime.root), method=method, template=template, body=arguments
        )
        invocation = rest_invocation(
            self.runtime.dispatch_principal().session_id, key, method=method, template=template
        )
        op_id = invocation.op_id
        recorded = await asyncio.to_thread(self.runtime.ledger.begin, op_id, digest, key=key)
        if recorded is not None:
            return _replayed(recorded.response)
        result = await self.dispatch(
            tool, arguments, entry_id=invocation.entry_id, run_id=f"web-{tool}"
        )
        await asyncio.to_thread(self.runtime.ledger.commit, op_id, digest, result)
        if after is not None:
            # Runs only on a FRESH execution: a replay's side record was written
            # by the execution it replays, and re-writing it would make a retry
            # look like a second run.
            after(result)
        return JSONResponse(_result_body(result))

    async def keyed_non_tool(
        self,
        request: Request,
        *,
        template: str,
        body: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> Response:
        """The §19-item-7 half: a keyed mutation with **no tool behind it**.

        ``POST /project/config/dfm`` and ``POST /git/tag`` have no ``ToolDecl``,
        no ``Invocation``, and no recorded-outcome row of their own, so the
        ledger extension records the *response body* under the same key space
        (project keyring HMAC, route, ``Idempotency-Key``). Without it those two
        rows of §2.3's table would be a header requirement with nothing behind
        them.
        """
        method = request.method
        key = require_key(request.headers.get("idempotency-key"), method=method, template=template)
        digest = rest_payload_hash(
            project=str(self.runtime.root), method=method, template=template, body=body
        )
        session = self.runtime.dispatch_principal().session_id
        op_id = f"{session}|rest-nontool:{template}:{key}|0|rest"
        recorded = await asyncio.to_thread(self.runtime.ledger.begin, op_id, digest, key=key)
        if recorded is not None:
            return _replayed(recorded.response)
        result = await asyncio.to_thread(operation)
        await asyncio.to_thread(self.runtime.ledger.commit, op_id, digest, result)
        return JSONResponse(_result_body(result))


def _result_body(result: Any) -> Any:
    """A dispatch result, on the wire.

    A tool result is already a document; a non-dict result (no canonical tool has
    one today) is wrapped rather than dropped.
    """
    if isinstance(result, dict):
        return cast("dict[str, Any]", result)
    return {"status": "ok", "result": result}


def _replayed(response: Any) -> Response:
    """§2.5's pinned REST replay shape.

    The stored body **byte-for-byte**, plus envelope field ``"replayed": true``
    (normative) and header ``Idempotency-Replayed: true`` (advisory). It does
    **not** degrade to the bridge's conflict shape: handing an operator client a
    conflict for its own committed success would be a lie, and would make a
    lost-response recovery indistinguishable from a genuine race.

    NAME COLLISION, recorded rather than hidden: ``write_part``/``edit_part``/
    ``create_part`` results already carry a ``replayed`` boolean of their own —
    the core WAL's answer to "did this write re-execute?". §2.5's normative
    envelope field has the same name, and on a REST replay it has the same truth
    value one layer up: neither the WAL nor this route did new work. So the
    marker **overlays** that field rather than sitting beside it under an
    invented name, and ``server/tests/test_http_parity.py`` asserts that the
    only difference between the stored body and the replayed body is exactly
    this key. A caller that needs the original WAL answer reads the first
    response, which is the one that carried it.
    """
    body = _result_body(response)
    if isinstance(body, dict):
        body = {**cast("dict[str, Any]", body), REPLAYED_FIELD: True}
    return JSONResponse(body, headers={REPLAYED_HEADER: "true"})


# --------------------------------------------------------------------------
# the app
# --------------------------------------------------------------------------


def build_app(runtime: WorkspaceRuntime) -> Starlette:
    """The Starlette app serving :data:`ROUTE_TABLE` over ``runtime``."""
    api = _Api(runtime)

    def guarded(
        handler: Callable[[Request], Awaitable[Response]],
    ) -> Callable[[Request], Awaitable[Response]]:
        """Bearer check + the §2.4 mapping, around every route.

        Wrapping rather than middleware so the mapping is visibly the *same* for
        every route, including the byte-serving ones: §2.4 is a closed table, and
        a route that mapped its own errors would be a second table.
        """

        async def wrapped(request: Request) -> Response:
            try:
                _authorize(request, runtime)
                return await handler(request)
            except RestKeyError as exc:
                refusal = refusal_for(HttpRefusal(_key_status(exc.reason), exc.reason, exc.message))
                return JSONResponse(refusal.body(), status_code=refusal.status)
            except DispatchError as exc:
                # §2.4 DECISION: a capability refusal is a *discriminated result*
                # at 200, never a 4xx — a missing sandbox must not be
                # indistinguishable from a broken server.
                capability = capability_result(exc)
                if capability is not None:
                    return JSONResponse(capability)
                refusal = refusal_for(exc)
                return JSONResponse(refusal.body(), status_code=refusal.status)
            except git.GitUnavailable as exc:
                body = error_body("git_unavailable", str(exc))
                return JSONResponse(body, status_code=503)
            except Exception as exc:
                try:
                    refusal = refusal_for(exc)
                except BaseException:
                    raise exc from None
                return JSONResponse(refusal.body(), status_code=refusal.status)

        return wrapped

    # -- read routes -------------------------------------------------------

    async def get_project(_: Request) -> Response:
        return JSONResponse(
            open_project_projection(
                runtime.layout,
                runtime.project_store,
                serve_mode=runtime.serve_mode,
                capabilities=runtime.capabilities(),
            )
        )

    async def get_parts(_: Request) -> Response:
        return JSONResponse(list_parts_projection(runtime.root, runtime.project_store))

    async def get_script(request: Request) -> Response:
        # `read_part` verbatim, paging fields intact: the route hands the tool's
        # own arguments through and returns its own result.
        arguments: dict[str, Any] = {"name": _part(request)}
        if "offset_line" in request.query_params:
            arguments["offset_line"] = _int_param(request, "offset_line", 1)
        if "limit_lines" in request.query_params:
            arguments["limit_lines"] = _int_param(request, "limit_lines", 2000)
        return JSONResponse(_result_body(await api.read_tool("read_part", arguments)))

    async def get_build(request: Request) -> Response:
        part = _part(request)
        result = await asyncio.to_thread(runtime.cad.current_build, part)
        return JSONResponse(build_projection(result))

    async def get_properties(request: Request) -> Response:
        return JSONResponse(await asyncio.to_thread(part_properties, runtime, _part(request)))

    async def get_part_checks(request: Request) -> Response:
        # §2.3: "the shared `heph check --json` serializer" — the SAME document
        # `GET /checks` returns, plus the part it was asked about. It is not
        # filtered, and that is a fact about the engine rather than a shortcut:
        # a project check is named `<file stem>:<check name>` and measures across
        # parts, so there is no part-scoped subset to return. Inventing one here
        # would be the client-side derivation §1 forbids, one layer down.
        part = _part(request)
        report = await asyncio.to_thread(project_checks, runtime)
        body = checks_projection(report)
        body["part"] = part
        return JSONResponse(body)

    async def get_checks(_: Request) -> Response:
        report = await asyncio.to_thread(project_checks, runtime)
        return JSONResponse(checks_projection(report))

    async def get_params(request: Request) -> Response:
        part = _part(request)
        probe = await asyncio.to_thread(runtime.cad.probe_part_params, part)
        state_hash = await asyncio.to_thread(runtime.cad.param_state_hash, "part", part)
        return JSONResponse(
            params_projection(probe.declaration, dict(probe.effective), state_hash, "part")
        )

    async def get_dfm(request: Request) -> Response:
        part = _part(request)
        last: dict[str, Any] | None = runtime.last_dfm(part)
        resolved_from: Any = None if last is None else last.get("resolved_from")
        body: dict[str, Any] = {
            "status": "ok",
            "part": part,
            "auto_run": bool(runtime.layout.manifest.dfm_auto_run),
            "last": last,
            "resolved_from": resolved_from,
        }
        return JSONResponse(body)

    # -- artifacts ---------------------------------------------------------

    async def get_artifact_meta(request: Request) -> Response:
        return JSONResponse(artifact_meta(runtime.store, _ref(request)))

    async def get_artifact_text(request: Request) -> Response:
        offset = _int_param(request, "offset_bytes", 0)
        page = _int_param(request, "max_bytes", READ_ARTIFACT_PAGE_MAX)
        return JSONResponse(artifact_text_page(runtime.store, _ref(request), offset, page))

    async def get_artifact_bytes(request: Request) -> Response:
        # §2.6's TIGHTENING, which does not wait for §19.24: every response from
        # this route carries `Content-Disposition: attachment` and
        # `X-Content-Type-Options: nosniff`. An SVG is a document with script
        # capability, the workspace origin holds the bearer token, and an
        # inline-rendered artifact SVG would be script execution on the token's
        # origin initiated by geometry. §22.3 puts the same pair on the
        # export-bytes route; putting them only there would have left the
        # mitigation on the route an SVG cannot currently be fetched through
        # while omitting it from the one it can.
        ref = _ref(request)
        data, mime = artifact_bytes(runtime.store, ref)
        return Response(
            data,
            media_type=mime,
            headers={
                "ETag": ref,
                "Cache-Control": _IMMUTABLE_CACHE,
                "Content-Disposition": "attachment",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def get_artifact_gltf(request: Request) -> Response:
        # §5.1 / §19 item 12. The route *does the minting* rather than hoping it
        # already happened: it resolves, or publishes on demand, the selection
        # bundle for that exact build ref — re-tessellating from the stored BREP
        # — and publishes the GLB under the `gltf` artifact kind. It never
        # returns an unlinked GLB; if the bundle cannot be minted it refuses
        # rather than degrading, because a viewport that is pickable but
        # unresolvable is the worst possible failure: it looks like it works.
        #
        # Off the event loop like every other engine call in this module: minting
        # tessellates and drives an offscreen GL session, and a blocked loop
        # would stall every other connection on this one process (§2.1).
        ref = _ref(request)
        published = await asyncio.to_thread(gltf_for_ref, runtime, ref)
        return Response(
            published.data,
            media_type=mime_for_kind(GLTF_KIND),
            headers={
                # The ETag is the *published GLB's* ref, not the requested build
                # ref: §2.6's `immutable` claim is honest only about the bytes
                # actually served, and those are content-addressed under the
                # `gltf` kind. A request by build ref and a request by GLB ref
                # therefore agree on the validator.
                "ETag": published.ref,
                "Cache-Control": _IMMUTABLE_CACHE,
                # The body is binary, so the provenance rides in a closed pair of
                # headers: the client learns which bundle backs the geometry from
                # the *server*, rather than decoding `asset.extras` out of the
                # blob — which would be the client reading a selection link, a
                # server value on §1's closed list.
                BUNDLE_HEADER: published.bundle_ref,
                SOURCE_HEADER: published.source_artifact_ref,
            },
        )

    # -- egress (§22) ------------------------------------------------------

    async def get_part_exports(request: Request) -> Response:
        # §22.6's retention obligation, made visible. Every export pins its blob
        # as an unconditional GC root and links it to its source build, and there
        # is no unpin surface anywhere in the product — so the panel carries a
        # history with a running byte total rather than a fire-and-forget button.
        # The total is computed here because §1 puts numbers on the server side.
        part = _part(request)
        return JSONResponse(await asyncio.to_thread(exports_projection, runtime.store, part))

    async def get_export_bytes(request: Request) -> Response:
        # §22.3's third route, with its own authorization argument. The two
        # headers below are the same pair `/artifacts/{ref}/bytes` carries, for
        # the same reason and with one difference that matters: `Cache-Control`
        # is **private**, not `public`, because this response is fetched with a
        # bearer in an `Authorization` header and a shared cache is the one place
        # that pair should never land.
        #
        # `Content-Disposition`'s filename is DERIVED from the blob digest and a
        # suffix drawn from a closed vocabulary — never from the recorded
        # `rel_path`, which for an agent-authored `target` may legally contain
        # `"` and `;`, the two characters that structure the parameter list
        # (§22.3's 2026-08-28 TIGHTENING).
        blob = str(request.path_params["export_blob"])
        data, file = await asyncio.to_thread(export_bytes, runtime.store, blob)
        return Response(
            data,
            media_type=file.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{file.filename}"',
                "X-Content-Type-Options": "nosniff",
                # Honest: the address *is* the digest.
                "ETag": file.blob,
                "Cache-Control": _EXPORT_CACHE,
            },
        )

    async def post_part_export(request: Request) -> Response:
        return await _export_mutation(request, template="/parts/{part}/export")

    async def post_part_drawing(request: Request) -> Response:
        return await _export_mutation(request, template="/parts/{part}/drawing")

    async def post_part_doc(request: Request) -> Response:
        return await _export_mutation(request, template="/parts/{part}/doc")

    async def _export_mutation(request: Request, *, template: str) -> Response:
        """One of §22.3's three keyed mutations, on the one dispatcher.

        The route validates (§22.1's refused arguments, §22.5's required pin),
        applies §2.5's key ladder, and calls `ToolDispatcher.dispatch` — nothing
        here computes an export. The result document is returned **verbatim**,
        bytes included only as `export_hashes`, and the download is a second
        request to a second route.
        """
        body = await _json_body(request)
        arguments = export_arguments(body, part=_part(request), template=template)
        return await api.keyed_mutation(
            request, template=template, tool=EXPORT_ROUTE_TOOLS[template], arguments=arguments
        )

    # -- inspection / measurement -----------------------------------------

    async def post_inspect(request: Request) -> Response:
        body = await _json_body(request)
        arguments = {**body, "name": _part(request)}
        result = await api.read_tool("inspect_part", arguments)
        return JSONResponse(_result_body(result))

    async def post_measure(request: Request) -> Response:
        # Project-scoped, not part-scoped: `clearance` and `interference` take
        # features from two different parts, and a `/parts/{part}/measure` route
        # would have to lie about one of its operands (§2.3).
        body = await _json_body(request)
        return JSONResponse(_result_body(await api.read_tool("measure", body)))

    async def post_context_preview(request: Request) -> Response:
        """§7A.3's disclosure: resolve an envelope, **start nothing**.

        The body is ``{context: {...}}`` — the same member the prompt route
        takes — or ``{}`` for the blank canvas. It calls no tool and opens no
        session, so it does not go through ``sessions_or_refuse``: a serve with
        no runtime can still show the operator what the agent *would* be told,
        and gating the disclosure on the runtime would have made the disabled
        composer's own explanation unavailable exactly when it is needed.

        The preview is **advisory**. `post_session_prompt` composes again, from
        this same function, at send time, and echoes the block it actually sent
        (§7A.3) — claiming this response were authoritative would be a promise
        two separate calls cannot keep.
        """
        body = await _json_body(request)
        unexpected = sorted(set(body) - {"context"})
        if unexpected:
            raise HttpRefusal(
                400,
                "invalid_params",
                "this route takes a context envelope and nothing else",
                data={"unexpected": unexpected},
            )
        envelope = parse_envelope(body.get("context"))
        composed = await asyncio.to_thread(compose_context, runtime, envelope)
        return JSONResponse(composed.projection())

    # -- mutations (key required) -----------------------------------------

    async def put_script(request: Request) -> Response:
        body = await _json_body(request)
        return await api.keyed_mutation(
            request,
            template="/parts/{part}/script",
            tool="write_part",
            arguments={**body, "name": _part(request)},
        )

    async def patch_script(request: Request) -> Response:
        body = await _json_body(request)
        return await api.keyed_mutation(
            request,
            template="/parts/{part}/script",
            tool="edit_part",
            arguments={**body, "name": _part(request)},
        )

    async def post_params(request: Request) -> Response:
        body = await _json_body(request)
        # The path wins over the body, on every part-addressed route: a request
        # whose path says `widget` and whose body says `bracket` must not mutate
        # `bracket`. `scope` defaults ahead of the body because it IS a body
        # choice (a project-scope write is legitimate here); `name` follows the
        # body because it is not.
        arguments = {"scope": "part", **body, "name": _part(request)}
        return await api.keyed_mutation(
            request, template="/parts/{part}/params", tool="set_params", arguments=arguments
        )

    async def post_build(request: Request) -> Response:
        body = await _json_body(request)
        return await api.keyed_mutation(
            request,
            template="/parts/{part}/build",
            tool="build_part",
            arguments={**body, "name": _part(request)},
        )

    async def post_dfm(request: Request) -> Response:
        part = _part(request)
        body = await _json_body(request)
        return await api.keyed_mutation(
            request,
            template="/parts/{part}/dfm",
            tool="run_dfm",
            arguments={**body, "name": part},
            after=lambda result: _record_dfm(runtime, part, result),
        )

    async def post_project_config_dfm(request: Request) -> Response:
        body = await _json_body(request)
        auto_run = body.get("auto_run")
        if not isinstance(auto_run, bool):
            raise HttpRefusal(400, "invalid_params", "auto_run must be a boolean")

        def write() -> dict[str, Any]:
            return _write_dfm_auto_run(runtime, auto_run)

        return await api.keyed_non_tool(
            request, template="/project/config/dfm", body=body, operation=write
        )

    # -- provider attachment (§23.0) ---------------------------------------

    async def post_providers_attach(request: Request) -> Response:
        """``POST /providers/attach`` — give a running serve an agent runtime.

        §23.0's first row: this route needs no sidecar because it **creates**
        one, so it is the one credential-adjacent route that never refuses
        ``agent_unavailable``. Without it the section could not be used in the
        only state it exists to fix.

        No ``Idempotency-Key``: attaching is not a source, config, or output
        mutation, and a byte-for-byte replay of "start a process" is incoherent.
        A second attach is refused ``agent_already_attached`` by name, which is a
        stronger guarantee than a replayed body would be.

        The route-level ``not_loopback`` precondition arrives here with §23.14
        item 2 (item 7 landed this route and recorded its absence as that item's
        work). Checked at the route and not inherited, like every other
        ``/providers/**`` row: §15.6 already says the serve is loopback-only,
        and §23 re-checks it anyway on the §2.6 pattern.
        """
        providers.loopback_or_refuse(runtime.bind_host)
        body = await _json_body(request)
        if body:
            # Closed, not permissive: §23's later routes carry real arguments,
            # and a route that silently ignored an unknown field today would
            # accept a misspelt one from a client written against tomorrow's.
            raise HttpRefusal(
                400,
                "invalid_params",
                "POST /providers/attach takes no arguments; "
                "provider specs are written through their own route",
                data={"unexpected": sorted(body)},
            )
        try:
            # NOT `asyncio.to_thread`: the sidecar's orphan-free death signal is
            # bound to the **spawning thread**, so a pooled worker's exit would
            # kill a perfectly healthy runtime. See `spawn_executor`.
            loop = asyncio.get_running_loop()
            state = await loop.run_in_executor(runtime.spawn_executor(), runtime.attach_agent)
        except AgentAlreadyAttached as exc:
            raise HttpRefusal(
                409,
                "agent_already_attached",
                str(exc),
                data=_attach_data(runtime),
            ) from exc
        except AttachRefused as exc:
            # NAMED, and the server is in its prior state: `attach_agent` binds
            # nothing until the sidecar has started and been configured.
            raise HttpRefusal(
                409,
                "attach_failed",
                str(exc),
                data=exc.state(generation=_attach_generation(runtime)).projection(),
            ) from exc
        return JSONResponse({"status": "ok", **state.projection()})

    # -- provider sign-in (§23) --------------------------------------------
    #
    # Every handler below opens with `providers.loopback_or_refuse`. It is
    # repeated per route rather than hoisted into `guarded` on purpose: §23.6
    # says the precondition is "checked at the route and **not inherited**", on
    # the §2.6 pattern. A precondition that lives in a wrapper is a precondition
    # a future route can be added without, and the failure mode is silent.

    def _providers_file() -> providers.ProvidersFile:
        providers.loopback_or_refuse(runtime.bind_host)
        return providers.read_providers_file(agent_attach.provider_config_path(runtime.root))

    def _provider_or_refuse(file: providers.ProvidersFile, provider_id: str) -> dict[str, Any]:
        for spec in file.providers:
            if str(spec.get("id", "")) == provider_id:
                return dict(spec)
        raise HttpRefusal(
            404,
            "provider_unknown",
            f"no provider {provider_id!r} is declared in {file.path}",
            data={"provider_id": provider_id},
        )

    def _auth_states(file: providers.ProvidersFile) -> dict[str, dict[str, Any]]:
        """Per-provider auth state, from the sidecar when there is one.

        With no sidecar this is empty and every row renders ``source: none`` —
        which is honest: Pi is the credential store, and with no Pi there is
        nothing that knows. It is NOT a probe: the sidecar answers out of what
        it already holds, and §15.41's "no background credential probe" stands.
        """
        backend = runtime.credentials
        if backend is None:
            return {}
        states: dict[str, dict[str, Any]] = {}
        for spec in file.providers:
            provider_id = str(spec.get("id", ""))
            if not provider_id:
                continue
            try:
                states[provider_id] = backend.credential_status(provider_id)
            except SupervisorError:
                # A sidecar that cannot answer is not a provider that is signed
                # out. The row keeps its default and the panel says "unused"
                # rather than claiming a state nothing observed.
                continue
        return states

    def _availability() -> dict[str, dict[str, Any]]:
        backend = runtime.credentials
        if backend is None:
            return {}
        return {str(row.get("id", "")): dict(row) for row in backend.provider_status()}

    async def get_providers(_: Request) -> Response:
        """``GET /providers`` — §23.8's two axes, and **no credential material**.

        §23.0's first row: no sidecar needed, and refusing this in the
        zero-config case is what made an earlier draft of §23 unusable in the
        only state it exists to fix.
        """
        file = _providers_file()
        # The sidecar reads go off the event loop: each is a blocking round trip
        # over a pipe, and a panel refresh must not stall the `GET /events`
        # socket the operator is watching while they sign in.
        auth_states = await asyncio.to_thread(_auth_states, file)
        return JSONResponse(
            providers.providers_projection(
                file,
                project_root=runtime.root,
                attach=_attach_data(runtime),
                availability=_availability(),
                auth_states=auth_states,
            )
        )

    async def put_providers_specs(request: Request) -> Response:
        """``PUT /providers/specs`` — the spec-only write (§23.6, §23.14 item 7).

        Named ``/specs`` and not ``/providers`` because it is **not** the whole
        file. A body carrying ``credential_allowlist`` or ``auth_source`` is
        refused ``allowlist_not_web_writable`` **by name** — the one refusal
        without which this section is an exfiltration primitive — and the
        on-disk values are carried across the write rather than taken from the
        request.
        """
        providers.loopback_or_refuse(runtime.bind_host)
        body = await _json_body(request)
        config_path = agent_attach.provider_config_path(runtime.root)
        current = providers.read_providers_file(config_path)
        specs = providers.validate_spec_write(body, current)
        acknowledge = providers.acknowledge_hosts(body)

        def write() -> dict[str, Any]:
            written = providers.write_specs(current, specs, acknowledge=acknowledge)
            return {
                "status": "ok",
                "config_path": str(written.path),
                "file_mode": written.file_mode,
                "providers": providers.provider_specs_of(written),
                "egress_acknowledged": [dict(row) for row in written.egress_acknowledged],
            }

        return await api.keyed_non_tool(
            request, template="/providers/specs", body=body, operation=write
        )

    async def get_providers_catalog(_: Request) -> Response:
        """``GET /providers/catalog`` — Pi's built-in catalog, live over the bridge.

        §23.1 rejects a Hephaestus-defined provider catalog outright: a curated
        "sign in with X" list maintained in this repo would be a second catalog
        beside Pi's, drifting the moment Pi ships a provider, which mission rule
        6 forbids. §23.0's third row, so this one **does** refuse
        ``agent_unavailable`` — correctly, because Pi is the catalog.
        """
        providers.loopback_or_refuse(runtime.bind_host)
        backend = credentials_or_refuse(runtime)
        catalog = await relay_async(backend.provider_catalog, provider_id="")
        return JSONResponse({"status": "ok", **catalog})

    async def get_provider_auth_status(request: Request) -> Response:
        """``GET /providers/{id}/auth/status`` — **metadata only** (§23.8)."""
        file = _providers_file()
        provider_id = request.path_params["id"]
        _provider_or_refuse(file, provider_id)
        backend = credentials_or_refuse(runtime)
        status = await relay_async(
            lambda: backend.credential_status(provider_id), provider_id=provider_id
        )
        return JSONResponse({"status": "ok", **status})

    async def post_provider_auth_key(request: Request) -> Response:
        """``POST /providers/{id}/auth/key`` — the §23.3 paste.

        The key is in the **body**: never a path segment, a query parameter, or
        a fragment. §2.2's reasoning about the bearer does not transfer — the
        bearer rides in a fragment because a fragment never reaches an access
        log or a ``Referer``, but a provider key is same-origin-visible to the
        page, does not expire with the serve, and is worth more than the token.
        Body or nowhere.
        """
        file = _providers_file()
        provider_id = request.path_params["id"]
        _provider_or_refuse(file, provider_id)
        body = await _json_body(request)
        key = body.get("key")
        if not isinstance(key, str) or not key.strip():
            raise HttpRefusal(400, "invalid_params", "key must be a non-empty string")
        scope = body.get("scope")
        if scope is None:
            # NOT defaulted. §23.2: a defaulted secret-persistence decision is
            # the single most consequential default a local tool can have, and
            # defaulting to `serve` "for safety" produces an operator who
            # retypes a key every morning until they stop using the product.
            raise HttpRefusal(
                400,
                "credential_scope_required",
                "say where this key should live: 'serve' (this serving process only, "
                "forgotten on restart) or 'project' (written to the app-owned auth.json)",
                data={"scopes": list(providers.CREDENTIAL_SCOPES)},
            )
        if scope not in providers.CREDENTIAL_SCOPES:
            raise HttpRefusal(
                400,
                "credential_scope_required",
                f"scope must be one of {', '.join(providers.CREDENTIAL_SCOPES)}",
                data={"scopes": list(providers.CREDENTIAL_SCOPES)},
            )
        # Before ANY credential write (§23.5): a write through the symlink would
        # land in the operator's own ~/.pi/agent/auth.json and overwrite the
        # login living there. Refresh through the link is safe; login is not.
        providers.guard_unlinked(runtime.root)
        backend = credentials_or_refuse(runtime)
        runs_in_flight_or_refuse(
            backend, confirm=body.get("confirm") is True, action="setting a credential"
        )
        result = await relay_async(
            lambda: backend.set_api_key(provider_id, key, scope=str(scope)),
            provider_id=provider_id,
        )
        providers.record_credential_source(file.path, provider_id=provider_id, source=str(scope))
        await apply_credential_change(runtime, backend)
        return JSONResponse(
            {
                "status": "ok",
                "provider_id": provider_id,
                "scope": scope,
                # §23.9: rotation has no verb — the response names the state it
                # replaced, so a rotation that landed in a different scope than
                # intended is visible now rather than in three weeks.
                "replaced": result.get("replaced", "none"),
            }
        )

    async def post_provider_auth_begin(request: Request) -> Response:
        """``POST /providers/{id}/auth/begin`` — start a subscription flow (§23.4).

        Returns **four non-secret values** for a device-code flow and an
        authorize URL for the fallback. The browser never touches the provider:
        the **sidecar** polls, honouring ``authorization_pending`` and
        ``slow_down``, and Pi mints and holds the PKCE verifier and the
        ``state``.
        """
        file = _providers_file()
        provider_id = request.path_params["id"]
        _provider_or_refuse(file, provider_id)
        body = await _json_body(request)
        flow_type = body.get("type", "device_code")
        if flow_type not in providers.AUTH_FLOW_TYPES:
            raise HttpRefusal(
                422,
                "unsupported_auth_type",
                f"type must be one of {', '.join(providers.AUTH_FLOW_TYPES)}",
                data={"flows": list(providers.AUTH_FLOW_TYPES)},
            )
        providers.guard_unlinked(runtime.root)
        backend = credentials_or_refuse(runtime)
        flow = await relay_async(
            lambda: backend.login_begin(provider_id, str(flow_type)), provider_id=provider_id
        )
        return JSONResponse({"status": "ok", **flow})

    async def post_provider_auth_complete(request: Request) -> Response:
        """``POST /providers/{id}/auth/complete`` — the operator's paste (§23.4).

        Pi's ``parseAuthorizationInput`` accepts a full redirect URL, a
        ``code#state`` pair, or a bare code, and **verifies ``state``**; a
        mismatch is ``authorization_state_mismatch`` and the credential is
        unchanged. This server never sees an authorization code, an access
        token, or a refresh token.
        """
        file = _providers_file()
        provider_id = request.path_params["id"]
        _provider_or_refuse(file, provider_id)
        body = await _json_body(request)
        text = body.get("input")
        if not isinstance(text, str) or not text.strip():
            raise HttpRefusal(
                400,
                "authorization_input_malformed",
                "paste the redirect URL, the code#state pair, or the authorization code",
            )
        backend = credentials_or_refuse(runtime)
        flow = await relay_async(
            lambda: backend.login_complete(provider_id, text), provider_id=provider_id
        )
        if str(flow.get("state")) == "complete":
            providers.record_credential_source(file.path, provider_id=provider_id, source="project")
            await apply_credential_change(runtime, backend)
        return JSONResponse({"status": "ok", **flow})

    async def post_provider_auth_cancel(request: Request) -> Response:
        """``POST /providers/{id}/auth/cancel`` — abandon a flow. Idempotent."""
        file = _providers_file()
        provider_id = request.path_params["id"]
        _provider_or_refuse(file, provider_id)
        backend = credentials_or_refuse(runtime)
        cancelled = await relay_async(
            lambda: backend.login_cancel(provider_id), provider_id=provider_id
        )
        return JSONResponse({"status": "ok", **cancelled})

    async def post_provider_auth_signout(request: Request) -> Response:
        """``POST /providers/{id}/auth/signout`` — §23.9's three properties.

        It does **not** delete the provider spec (the row stays, in state
        ``none``), it is refused while ``linked`` (unlink first — signing out
        through a symlink would sign the operator out of their own terminal),
        and it cannot fail halfway because Pi's ``modify`` is a serialized
        read-modify-write whose throwing operation propagates without writing.
        """
        file = _providers_file()
        provider_id = request.path_params["id"]
        _provider_or_refuse(file, provider_id)
        body = await _json_body(request)
        providers.guard_unlinked(runtime.root)
        backend = credentials_or_refuse(runtime)
        runs_in_flight_or_refuse(backend, confirm=body.get("confirm") is True, action="signing out")
        result = await relay_async(lambda: backend.sign_out(provider_id), provider_id=provider_id)
        providers.record_credential_source(file.path, provider_id=provider_id, source="none")
        await apply_credential_change(runtime, backend)
        return JSONResponse({"status": "ok", "provider_id": provider_id, **result})

    async def post_providers_auth_unlink(_: Request) -> Response:
        """``POST /providers/auth/unlink`` — stop borrowing (§23.5).

        Replaces the symlink with an own file and **does not read, copy, or
        modify the target**. A copy would put a second rotating refresh token
        beside the operator's, which is the failure mode ``link_auth_source``'s
        copy-versus-symlink reasoning already identified.
        """
        providers.loopback_or_refuse(runtime.bind_host)
        return JSONResponse({"status": "ok", **providers.unlink_auth_source(runtime.root)})

    # -- credential discovery — Stage 10C (§23.5) ---------------------------

    async def post_providers_discover(_: Request) -> Response:
        """``POST /providers/discover`` — the **offer**, and only when called.

        Nothing here is configured, linked, read into a runtime, or written to
        ``providers.json``. Each source is described by
        ``{kind, provider_id, model_ids, source_path}`` and by nothing else: the
        operator's ruling permits "a masked hint at most", which is a **ceiling**
        (§0.2a), and §15.41's *no masked key tail* is stricter and stands.
        """
        providers.loopback_or_refuse(runtime.bind_host)
        offers = providers.discover_sources(runtime.discoveries, project_root=runtime.root)
        return JSONResponse({"status": "ok", "sources": [offer.projection() for offer in offers]})

    async def post_providers_adopt(request: Request) -> Response:
        """``POST /providers/adopt`` — the one explicit act (§23.5 constraint 1).

        The body is ``{discovery_id}`` **only**. A body carrying a filesystem
        path under any key is refused ``path_not_web_writable``; an unknown or
        expired handle is refused ``discovery_source_unknown``. The offer
        already told the operator the path, so a path here would add no
        information they lack — it would only add a *client-chosen* path to a
        credential route, which is the one shape §23.5 forbids by name.
        """
        providers.loopback_or_refuse(runtime.bind_host)
        body = await _json_body(request)
        for name, value in sorted(body.items()):
            if name != "discovery_id" and providers.looks_like_path(value):
                raise HttpRefusal(
                    400,
                    "path_not_web_writable",
                    "adopt takes the discovery handle only; no provider route accepts a "
                    "filesystem path in a request body",
                    data={"fields": [name]},
                )
        unexpected = sorted(set(body) - {"discovery_id"})
        if unexpected:
            raise HttpRefusal(
                400,
                "invalid_params",
                "adopt takes discovery_id and nothing else",
                data={"unexpected": unexpected},
            )
        discovery_id = body.get("discovery_id")
        if not isinstance(discovery_id, str) or not discovery_id:
            raise HttpRefusal(400, "invalid_params", "discovery_id must be a non-empty string")
        offer = runtime.discoveries.resolve(discovery_id)
        config_path = agent_attach.provider_config_path(runtime.root)
        written = providers.adopt_offer(offer, config_path=config_path)
        return JSONResponse(
            {
                "status": "ok",
                "adopted": offer.projection(),
                "config_path": str(written.path),
                "file_mode": written.file_mode,
                "adopted_sources": [dict(row) for row in written.adopted_sources],
                "providers": providers.provider_specs_of(written),
            }
        )

    # -- sessions, history, threading (§2.7, §2.8) -------------------------

    def sessions_or_refuse() -> WorkspaceSessions:
        """The attached session layer, or a **named** refusal.

        A serve with no agent runtime (no provider config, or a machine without
        Node) still serves every read and mutation route; it simply has no
        sessions. Saying so by name beats an empty session list, which would read
        as "this project has never been driven by an agent".

        §7A.8/§19.25: the refusal carries the **cause** as well as the name. The
        serve used to know exactly why ``_attach_agent`` produced nothing and
        write it to a stderr no browser will ever read; the panel was left to
        render a state with its content missing, which §4.4 says reads as a bug
        rather than as a design. The ``data`` is the same closed projection
        ``POST /providers/attach`` returns — one shape for one fact.
        """
        sessions = runtime.sessions
        if sessions is None:
            raise HttpRefusal(
                503,
                "agent_unavailable",
                "this server has no agent runtime attached; "
                "attach one (POST /providers/attach) to create or attach sessions",
                data=_attach_data(runtime),
            )
        return sessions

    async def get_sessions(_: Request) -> Response:
        return JSONResponse(sessions_or_refuse().list_sessions())

    async def post_sessions(request: Request) -> Response:
        # No key: creating a session is not a source/config/output mutation, and
        # a duplicate is an extra *idle* session, not a lost or doubled write.
        # At-least-once is the stated consequence — `GET /sessions` lists the
        # orphan and the operator closes it (§2.3).
        sessions = sessions_or_refuse()
        body = await _json_body(request)
        profile = body.get("profile", "orchestrator")
        if profile not in SESSION_PROFILES:
            raise HttpRefusal(
                400,
                "invalid_params",
                f"profile must be one of {list(SESSION_PROFILES)}",
                data={"profile": profile},
            )
        part_raw = body.get("part")
        part = None if part_raw is None else str(part_raw)
        # §7A.2's two TIGHTENINGs (§19.26). `SESSION_PROFILES` is closed at
        # three and this route accepted all three; it must accept **two**.
        #
        # A `quick_edit` session's entire meaning is the seeding
        # `spawn_quick_edit` performs — part, source, provenance, crop ref and
        # `parent_session_id`, resolved against the pinned artifact, with
        # `stale_selection` raised before any lease is taken (§12.5). A bare
        # create produces that profile's *restrictions* and **none** of its
        # context: a scope the operator can feel but cannot see, and a
        # `parent_session_id` that is nothing, so §2.8's edge is never written
        # and the tab reopens `unlinked`. The refusal therefore names the route
        # that does create one rather than merely saying no.
        #
        # SCOPED TO **CREATION**, and the narrowing is named rather than
        # slipped in. §14 makes a committed >250-event transcript a fixture
        # requirement and G4.11's archive is keyed on `(session_id, ordinal)`,
        # so a persisted quick-edit transcript can only be read back by
        # `{session_id, resume: true}` — the deviation `WorkspaceSessions.create`
        # already records. Refusing that too would make §14's own fixture
        # unloadable, so the refusal is on the *create* path, which is the one
        # §7A.2 argues about ("a **bare** `POST /sessions {profile:"quick_edit",
        # part:"tread"}`"). RESIDUAL, recorded not hidden: `resume: true` on an
        # id with no persisted transcript is a fresh session under that name
        # (the sidecar's own behaviour), so that one path can still reach an
        # unseeded quick-edit session. It is the pre-existing resume deviation's
        # hole, not a new one, and closing it needs a "has this id a persisted
        # transcript?" question no surface answers today.
        if profile == QUICK_EDIT_PROFILE and not bool(body.get("resume", False)):
            raise HttpRefusal(
                400,
                "invalid_params",
                "a quick-edit session is created by POST /parts/{part}/quick_edit, "
                "which seeds it with the part, the resolved selection and its parent; "
                "creating one here would produce the profile's restrictions with none "
                "of its context",
                data={"profile": profile, "route": "POST /parts/{part}/quick_edit"},
            )
        if profile == "part" and part is None:
            # Unvalidated, this produced a part-profile session bound to nothing,
            # whose every object-scoped tool call fails `scope_denied` against a
            # `None` binding — a refusal the operator would read as a bug.
            raise HttpRefusal(
                400,
                "invalid_params",
                "a part session must name the part it is bound to",
                data={"profile": profile, "part": None},
            )
        # `session_id` + `resume` reopen a PERSISTED transcript by name. See
        # `WorkspaceSessions.create` for why the two gate clauses that need this
        # are unreachable without it; both arguments already existed on the
        # bridge, so this route forwards rather than invents.
        named_raw = body.get("session_id")
        named = None if named_raw is None else str(named_raw)
        resume = bool(body.get("resume", False))
        if resume and named is None:
            raise HttpRefusal(
                400,
                "invalid_params",
                "resume requires session_id: there is nothing to resume without a name",
                data={"resume": True},
            )
        return JSONResponse(
            await asyncio.to_thread(
                lambda: sessions.create(str(profile), part=part, session_id=named, resume=resume)
            )
        )

    async def get_session_history(request: Request) -> Response:
        sessions = sessions_or_refuse()
        session_id = _session(request)
        # The opaque base64url cursor is forwarded and returned UNMODIFIED, and
        # there is no page-size parameter: `HISTORY_PAGE_SIZE` lives in the
        # sidecar and page 1 freezes a high-water mark (§2.8).
        cursor = request.query_params.get("cursor")
        return JSONResponse(await asyncio.to_thread(lambda: sessions.history(session_id, cursor)))

    async def get_session_thread(request: Request) -> Response:
        # Deliberately NOT gated on an attached agent runtime. Threading is a
        # durable fact in `state.db` (§2.8's `tp_session_edges`), written when the
        # relationship was created and readable long after the process that
        # created it is gone. Refusing to answer "what was this session a child
        # of" because no model is configured today would make a durable record
        # unreadable for a reason that has nothing to do with it.
        return JSONResponse(thread_projection(runtime.edges, _session(request)))

    async def post_session_prompt(request: Request) -> Response:
        sessions = sessions_or_refuse()
        session_id = _session(request)
        body = await _json_body(request)
        text = body.get("text")
        if not isinstance(text, str) or not text:
            raise HttpRefusal(400, "invalid_params", "text is required and must be a string")
        run_raw = body.get("run_id")
        run_id = None if run_raw is None else str(run_raw)
        # §7A.3/§7A.4/§19.22 — the one optional member this route gained.
        #
        # THE INVARIANT, and it is the reason the block travels beside `text`
        # rather than inside it: **the request text is exactly what the operator
        # typed.** `BridgeRuntime.prompt` binds `text` to the run for
        # `VALIDATION.md` §4/§5, and `_critique.py`'s `prompt_number_diff` then
        # matches every number in "the request" against the build's own extents.
        # A context block carrying `bbox 250 x 140 x 5.5 mm` prepended to the
        # prompt would put the build's extents into the request and every one of
        # them would come back `matched: true` **against itself** — the rung that
        # exists to catch a design that does not meet its brief would be
        # measuring the workspace's own context block.
        #
        # The envelope is validated and composed HERE, on the request thread,
        # so its refusals (`unknown_part`, `unknown_artifact`, `stale_selection`,
        # `invalid_params`) reach the client as themselves rather than as a
        # failed run. §7A.3: "a lying client is caught, not believed."
        envelope = parse_envelope(body.get("context"))
        composed = await asyncio.to_thread(compose_context, runtime, envelope)
        block = composed.block or None
        return JSONResponse(
            await asyncio.to_thread(
                lambda: {
                    **sessions.run_prompt(session_id, text, run_id=run_id, context=block),
                    # The block ACTUALLY SENT, echoed — §7A.3 makes
                    # `/context/preview` advisory precisely because this is the
                    # composition that happened.
                    "context": composed.projection() if block is not None else None,
                }
            )
        )

    async def post_session_answer(request: Request) -> Response:
        # Governed by **question-id idempotency**, not by the header ladder:
        # idempotent on the question id, first answer wins (§2.7). A second
        # mechanism over it would be the duplication mission rule 6 forbids.
        sessions = sessions_or_refuse()
        session_id = _session(request)
        body = await _json_body(request)
        question_id = body.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise HttpRefusal(400, "invalid_params", "question_id is required")
        if "answer" not in body:
            raise HttpRefusal(400, "invalid_params", "answer is required")
        try:
            return JSONResponse(sessions.answer_question(session_id, question_id, body["answer"]))
        except KeyError as exc:
            raise HttpRefusal(
                404,
                "unknown_question",
                f"no question {question_id!r} is pending; it was answered, "
                "abandoned, or never asked",
                data={"question_id": question_id},
            ) from exc

    async def post_run_cancel(request: Request) -> Response:
        # Cancellation targets a **run**, so the route does. Idempotent by
        # construction: a repeated request_cancel on an already-cancelled run
        # changes nothing, so a key would record a replay of a no-op (§2.3).
        sessions = sessions_or_refuse()
        run_id = str(request.path_params["run_id"])
        return JSONResponse(await asyncio.to_thread(lambda: sessions.cancel_run(run_id)))

    async def events_socket(websocket: WebSocket) -> None:
        """``GET /events`` (§2.7) — the non-durable observer's socket."""
        sessions = runtime.sessions
        if sessions is None:
            await websocket.close(code=1008, reason="agent_unavailable")
            return
        await serve_events(websocket, sessions, runtime.token)

    # -- git ---------------------------------------------------------------

    async def get_git_status(_: Request) -> Response:
        return JSONResponse(await asyncio.to_thread(git.git_status, runtime.root))

    async def get_git_log(request: Request) -> Response:
        part = request.query_params.get("part")
        return JSONResponse(await asyncio.to_thread(git.git_log, runtime.root, part))

    async def get_git_diff(request: Request) -> Response:
        part = request.query_params.get("part")
        from_rev = request.query_params.get("from")
        if part is None or from_rev is None:
            raise HttpRefusal(400, "invalid_params", "part and from are required")
        to_rev = request.query_params.get("to")
        return JSONResponse(
            await asyncio.to_thread(
                lambda: git.git_diff(runtime.root, part=part, from_rev=from_rev, to_rev=to_rev)
            )
        )

    async def get_git_tags(_: Request) -> Response:
        return JSONResponse(await asyncio.to_thread(git.git_tags, runtime.root))

    async def post_git_tag(request: Request) -> Response:
        body = await _json_body(request)
        name = body.get("name")
        message = body.get("message")
        if not isinstance(name, str) or not isinstance(message, str):
            raise HttpRefusal(400, "invalid_params", "name and message are required strings")

        def tag() -> dict[str, Any]:
            return git.git_tag_create(runtime.root, name=name, message=message)

        return await api.keyed_non_tool(request, template="/git/tag", body=body, operation=tag)

    handlers: dict[tuple[str, str], Callable[[Request], Awaitable[Response]]] = {
        ("GET", "/project"): get_project,
        ("GET", "/parts"): get_parts,
        ("GET", "/parts/{part}/script"): get_script,
        ("GET", "/parts/{part}/build"): get_build,
        ("GET", "/parts/{part}/properties"): get_properties,
        ("GET", "/parts/{part}/checks"): get_part_checks,
        ("GET", "/parts/{part}/params"): get_params,
        ("GET", "/parts/{part}/dfm"): get_dfm,
        ("GET", "/checks"): get_checks,
        ("GET", "/artifacts/{ref}/meta"): get_artifact_meta,
        ("GET", "/artifacts/{ref}/text"): get_artifact_text,
        ("GET", "/artifacts/{ref}/bytes"): get_artifact_bytes,
        ("GET", "/artifacts/{ref}/gltf"): get_artifact_gltf,
        ("GET", "/parts/{part}/exports"): get_part_exports,
        ("GET", "/exports/{export_blob}/bytes"): get_export_bytes,
        ("POST", "/parts/{part}/export"): post_part_export,
        ("POST", "/parts/{part}/drawing"): post_part_drawing,
        ("POST", "/parts/{part}/doc"): post_part_doc,
        ("POST", "/parts/{part}/inspect"): post_inspect,
        ("POST", "/measure"): post_measure,
        ("POST", "/context/preview"): post_context_preview,
        ("PUT", "/parts/{part}/script"): put_script,
        ("PATCH", "/parts/{part}/script"): patch_script,
        ("POST", "/parts/{part}/params"): post_params,
        ("POST", "/parts/{part}/build"): post_build,
        ("POST", "/parts/{part}/dfm"): post_dfm,
        ("POST", "/project/config/dfm"): post_project_config_dfm,
        ("POST", "/git/tag"): post_git_tag,
        ("POST", "/providers/attach"): post_providers_attach,
        ("GET", "/providers"): get_providers,
        ("PUT", "/providers/specs"): put_providers_specs,
        ("GET", "/providers/catalog"): get_providers_catalog,
        ("GET", "/providers/{id}/auth/status"): get_provider_auth_status,
        ("POST", "/providers/{id}/auth/key"): post_provider_auth_key,
        ("POST", "/providers/{id}/auth/begin"): post_provider_auth_begin,
        ("POST", "/providers/{id}/auth/complete"): post_provider_auth_complete,
        ("POST", "/providers/{id}/auth/cancel"): post_provider_auth_cancel,
        ("POST", "/providers/{id}/auth/signout"): post_provider_auth_signout,
        ("POST", "/providers/auth/unlink"): post_providers_auth_unlink,
        ("POST", "/providers/discover"): post_providers_discover,
        ("POST", "/providers/adopt"): post_providers_adopt,
        ("GET", "/sessions"): get_sessions,
        ("POST", "/sessions"): post_sessions,
        ("GET", "/sessions/{id}/history"): get_session_history,
        ("GET", "/sessions/{id}/thread"): get_session_thread,
        ("POST", "/sessions/{id}/prompt"): post_session_prompt,
        ("POST", "/sessions/{id}/answer"): post_session_answer,
        ("POST", "/runs/{run_id}/cancel"): post_run_cancel,
        ("GET", "/git/status"): get_git_status,
        ("GET", "/git/log"): get_git_log,
        ("GET", "/git/diff"): get_git_diff,
        ("GET", "/git/tags"): get_git_tags,
    }
    sockets: dict[str, Callable[[WebSocket], Awaitable[None]]] = {"/events": events_socket}
    declared = set(ROUTE_TABLE)
    served = set(handlers) | {("GET", template) for template in sockets}
    missing = declared - served
    extra = served - declared
    if missing or extra:  # pragma: no cover - the boundary test asserts this too
        raise RuntimeError(f"route table drift: missing={sorted(missing)} extra={sorted(extra)}")
    if set(sockets) != set(WEBSOCKET_ROUTES):  # pragma: no cover - same
        raise RuntimeError(f"websocket route drift: {sorted(set(sockets) ^ set(WEBSOCKET_ROUTES))}")

    by_path: dict[str, dict[str, Callable[[Request], Awaitable[Response]]]] = {}
    for method, template in ROUTE_TABLE:
        if template in sockets:
            continue
        by_path.setdefault(template, {})[method] = guarded(handlers[(method, template)])
    routes: list[BaseRoute] = [
        Route(
            API_PREFIX + template,
            endpoint=_method_router(methods),
            methods=sorted(methods),
        )
        for template, methods in by_path.items()
    ]
    # The socket authenticates itself (§2.2 requires a bearer on the upgrade
    # too), so it is deliberately NOT wrapped in `guarded`: that wrapper's whole
    # output is a JSON `Response`, which is not a thing one can send down a
    # WebSocket that was never accepted.
    routes.extend(
        WebSocketRoute(API_PREFIX + template, endpoint=endpoint)
        for template, endpoint in sockets.items()
    )
    return Starlette(routes=routes)


def _method_router(
    methods: dict[str, Callable[[Request], Awaitable[Response]]],
) -> Callable[[Request], Awaitable[Response]]:
    """One Starlette endpoint fanning out to the per-method handlers of a path."""

    async def endpoint(request: Request) -> Response:
        handler = methods.get(request.method)
        if handler is None:  # pragma: no cover - Starlette rejects first
            return JSONResponse(
                error_body("method_not_allowed", f"{request.method} is not served here"),
                status_code=405,
            )
        return await handler(request)

    return endpoint


def _key_status(reason: str) -> int:
    """Ladder reasons that mean *no execution* at 400; the rest are §2.4's 409s."""
    if reason in ("idempotency_key_required", "idempotency_key_malformed"):
        return 400
    return 409


def project_checks(runtime: WorkspaceRuntime) -> Any:
    """``heph check``'s own run, under the workspace principal's check.

    §19 item 5: the serializer and the run are extracted
    (:mod:`hephaestus.core.checks.report`) and each caller applies its own
    principal check — the CLI's is "an operator on this filesystem", and this
    one's is the bearer already verified by :func:`_authorize`.
    """
    return project_check_report(runtime.layout, runtime.store)


def part_properties(runtime: WorkspaceRuntime, part: str) -> dict[str, Any]:
    """The §6.2 properties body, read from the **runtime-metadata build record**.

    Two reads exist and they are not equivalent. ``BuildResult.metadata`` is the
    §5.2 metadata *as the worker evaluated it* — a computed
    ``part.blank_size = f"{p.width} x …"`` is carried exactly like a literal —
    while ``cad_ops.script_metadata`` is a static AST parse that recovers string
    constants and nothing else. G4.3 asks for "all metadata fields from the
    script", and a field the script computes is a field the script declares, so
    the record wins wherever there is one.

    The fallback is not a silent second-best: a part with no current build (or a
    record written before ``metadata`` existed, which stores an empty map) has no
    runtime evaluation to report, and the literal parse is then the strongest
    honest answer. ``source`` says which one answered, so the panel and the e2e
    read a fact rather than infer it.
    """
    build = runtime.cad.current_build(part)
    if build is not None and build.metadata:
        return properties_projection(
            build.metadata, source="build_record", build_artifact_ref=build.artifact_ref
        )
    # `part_metadata` reads the part through the store, so an unknown part raises
    # the engine's own addressing refusal here rather than answering an empty map
    # for a part that does not exist.
    return properties_projection(runtime.cad.part_metadata(part), source="script_literals")


def _record_dfm(runtime: WorkspaceRuntime, part: str, result: Any) -> None:
    """Record a successful ``run_dfm`` result so ``GET /parts/{part}/dfm`` has one.

    Only ``status="ok"`` is recorded. A capability refusal or an error is not a
    DFM evaluation, and storing one as "the last DFM result" would make the GET
    route report a refusal as a finding-free run — silence reading as a pass,
    which §6.4 forbids by name.
    """
    if not isinstance(result, dict):
        return
    payload = cast("dict[str, Any]", result)
    if payload.get("status") == "ok":
        runtime.record_dfm(part, payload)


def _write_dfm_auto_run(runtime: WorkspaceRuntime, auto_run: bool) -> dict[str, Any]:
    """The ``[dfm] auto_run`` project-config write (§6.4).

    Two controls, not one: ``[dfm] auto_run`` in ``hephaestus.toml`` is a
    *project setting*, not a per-message flag, so the workspace exposes a **Run
    DFM** action (``POST /parts/{part}/dfm``) and this project-settings toggle
    separately. Collapsing them into one composer switch would imply a tool
    argument that does not exist.

    The manifest is rewritten minimally — the ``[dfm]`` table's ``auto_run`` line
    only — because it is the human's file and this is a checkbox, not a
    formatter.
    """
    path = runtime.layout.manifest_path
    text = path.read_text(encoding="utf-8")
    updated = _set_toml_dfm_auto_run(text, auto_run)
    path.write_text(updated, encoding="utf-8")
    # The setting must take effect now, not at the next serve: `CadOps` reads
    # `dfm_auto_run` off the layout it captured.
    runtime.reload_manifest()
    return {"status": "ok", "auto_run": auto_run}


def _set_toml_dfm_auto_run(text: str, auto_run: bool) -> str:
    """Set ``[dfm] auto_run`` in a manifest, preserving everything else.

    A line-level edit rather than a parse-and-dump: ``tomllib`` is read-only in
    the stdlib and a round-trip through any writer would reformat comments and
    ordering out of a file the human owns.
    """
    value = "true" if auto_run else "false"
    lines = text.splitlines()
    in_dfm = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_dfm = stripped == "[dfm]"
            continue
        if in_dfm and stripped.split("=")[0].strip() == "auto_run":
            lines[index] = f"auto_run = {value}"
            return "\n".join(lines) + "\n"
    if any(line.strip() == "[dfm]" for line in lines):
        out: list[str] = []
        for line in lines:
            out.append(line)
            if line.strip() == "[dfm]":
                out.append(f"auto_run = {value}")
        return "\n".join(out) + "\n"
    body = "\n".join(lines).rstrip("\n")
    return f"{body}\n\n[dfm]\nauto_run = {value}\n"
