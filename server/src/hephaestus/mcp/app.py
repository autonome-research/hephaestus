"""``HephaestusMCP``: the Stage 3 FastMCP application over the Stage 2 core.

One FastMCP app serves both transports (stdio and streamable HTTP; see
:mod:`hephaestus.mcp.cli_serve`). Everything below the MCP boundary is the code
the Pi bridge already uses:

* **Tool surface.** Every canonical tool is registered from
  :func:`hephaestus.core.toolgen.mcp_declarations` — declarations generated from
  :mod:`hephaestus.core.tools_decl` (and therefore byte-identical to
  ``schemas/tools/*.schema.json`` and ``schemas/mcp/tools.json``). No tool
  schema is written by hand here, so the CI drift contract covers MCP too. Three
  server-local verbs are added: ``open_project`` and ``list_parts`` (mission
  Stage 3), and ``answer_question`` — the follow-up call of the documented
  ``ask_user`` fallback.
* **Dispatch.** Calls go through the very same
  :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher` /
  :class:`~hephaestus.agent_bridge.cad_ops.CadOps` the Pi bridge uses, under an
  **mcp principal**: a local MCP client is orchestrator-equivalent (it *is* the
  agent), while the project it may touch is bound by ``open_project`` — an MCP
  session with no open project can call no project tool at all.
* **Idempotency.** Mutating tools derive their key from MCP session identity +
  canonical JSON-RPC request id, honoring an optional
  ``_meta["hephaestus.dev/idempotency-key"]``; the derived id is the same
  ``op_id`` the bridge feeds to the opstore opkeys/WAL layer (see
  :mod:`hephaestus.mcp.idempotency`).
* **ask_user → elicitation.** ``ask_user`` maps to ``ctx.elicit`` (proven in
  ``spikes/mcp_elicitation``). A client that does not advertise the elicitation
  capability gets the documented fallback instead: structured content
  describing the pending question plus the exact follow-up call to make.
* **Images.** ``inspect_part`` returns MCP image content within the
  ``schemas/bridge_limits.json`` budgets, alongside the artifact refs — the
  images are a *view* of immutable artifacts, never the record of them.
* **Executor policy.** Under ``heph serve`` the unsafe local executor is refused
  (``unsafe_refused``) through :func:`hephaestus.core.executor.sandbox.probe.refuse_unsafe`;
  serve builds only ever run on a probed secure backend.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.tools.base import Tool, ToolResult
from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.cad_ops import (
    CadOps,
    invalid_question_result,
    option_consequence,
    option_label,
    question_problems,
    requirement_ids,
)
from hephaestus.agent_bridge.dispatch import DispatchError, Invocation, Principal, ToolDispatcher
from hephaestus.agent_bridge.limits import LIMITS
from hephaestus.agent_bridge.protocol import ProtocolError
from hephaestus.core import toolgen
from hephaestus.core.errors import HephaestusError
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.probe import refuse_unsafe, secure_backend
from hephaestus.core.project_store.layout import ProjectLayout, load_project
from hephaestus.core.project_store.retention import DefaultProtectedRoots
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.tools_decl import TOOLS_BY_NAME
from opstore.types import JSONValue
from pydantic import ConfigDict

from mcp.types import (
    ClientCapabilities,
    ContentBlock,
    ElicitationCapability,
    ImageContent,
    TextContent,
)
from opstore import OpStore

from .idempotency import (
    IDEMPOTENCY_META_KEY,
    IdempotencyError,
    IdempotencyLedger,
    explicit_key_timestamp,
    mcp_invocation,
    payload_hash,
)
from .validate import SchemaError, normalize_arguments

__all__ = [
    "EXTRA_TOOL_NAMES",
    "HephaestusMCP",
    "build_app",
]

#: Server-local verbs added on top of the canonical ``tool_schema.md`` surface.
EXTRA_TOOL_NAMES: Final[tuple[str, ...]] = ("open_project", "list_parts", "answer_question")

_STATE_DB_NAME: Final[str] = "state.db"
_TEXT_MAX_BYTES: Final[int] = int(LIMITS["text_result"]["max_bytes"])
_TEXT_MAX_LINES: Final[int] = int(LIMITS["text_result"]["max_lines"])
_MAX_IMAGE_BYTES: Final[int] = int(LIMITS["image"]["max_image_bytes"])
_MAX_IMAGES: Final[int] = int(LIMITS["image"]["max_images_per_result"])

#: The MCP client is orchestrator-equivalent: it is the agent driving the project.
_MCP_PROFILE: Final[str] = "orchestrator"


class McpToolError(Exception):
    """A refusal to report to the MCP client as a discriminated error result."""

    def __init__(self, reason: str, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.data = data or {}

    def payload(self) -> dict[str, Any]:
        return {"status": "error", "reason": self.reason, "message": self.message, **self.data}


# --------------------------------------------------------------------------
# server-local tool declarations (not part of tool_schema.md)
# --------------------------------------------------------------------------

_OPEN_PROJECT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": False,
}

_LIST_PARTS_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_ANSWER_QUESTION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "question_id": {"type": "string"},
        "selection": {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
    },
    "required": ["question_id", "selection"],
    "additionalProperties": False,
}


@dataclass
class _PendingQuestion:
    """An ``ask_user`` question awaiting the fallback follow-up call."""

    question_id: str
    question: str
    options: tuple[str, ...]
    allow_free_text: bool
    multi: bool


@dataclass
class _Project:
    """One opened project: store, dispatcher, and its MCP idempotency ledger."""

    root: Path
    layout: ProjectLayout
    store: OpStore
    project_store: ProjectStore
    cad: CadOps
    dispatcher: ToolDispatcher
    ledger: IdempotencyLedger

    def close(self) -> None:
        self.store.close()


@dataclass
class _Session:
    """Per-MCP-session state: the bound project and any pending questions."""

    session_id: str
    project: _Project | None = None
    questions: dict[str, _PendingQuestion] = field(default_factory=dict[str, _PendingQuestion])


class HephaestusMCP:
    """The Stage 3 MCP runtime: project binding, dispatch, idempotency, questions."""

    def __init__(
        self,
        *,
        serve_mode: bool = False,
        backend: ExecBackend | None = None,
        name: str = "hephaestus",
    ) -> None:
        # ``heph serve`` never runs the unsafe local executor: refuse an injected
        # unsafe backend up front, and take the probed secure backend otherwise.
        if serve_mode and backend is not None and getattr(backend, "unsafe", False):
            refuse_unsafe(registry_content=False, serve=True)
        self.serve_mode = serve_mode
        self._backend = backend
        self._sessions: dict[str, _Session] = {}
        self._projects: dict[Path, _Project] = {}
        self._lock = threading.RLock()
        # tool_schema.md: mutating/stateful tools declare sequential execution.
        self._sequential = asyncio.Lock()
        self.app: FastMCP[None] = FastMCP(name)
        self._register_tools()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close every opened project store (idempotent)."""
        with self._lock:
            projects = list(self._projects.values())
            self._projects.clear()
            self._sessions.clear()
        for project in projects:
            project.close()

    def __enter__(self) -> HephaestusMCP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- session / project state ------------------------------------------

    def session(self, session_id: str) -> _Session:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = _Session(session_id=session_id)
                self._sessions[session_id] = state
            return state

    def principal(self, session_id: str) -> Principal:
        """The mcp principal: orchestrator-equivalent authz for a local client."""
        return Principal(session_id=f"mcp:{session_id}", profile=_MCP_PROFILE, part=None)

    def _backend_for(self, layout: ProjectLayout) -> ExecBackend:
        if self._backend is not None:
            if self.serve_mode and getattr(self._backend, "unsafe", False):
                refuse_unsafe(registry_content=False, serve=True)
            return self._backend
        if self.serve_mode:
            return secure_backend(layout.store_root)
        from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

        return UnsafeLocalBackend()

    def open_project(self, session_id: str, path: str | Path) -> _Project:
        """Bind ``path``'s project to this MCP session (opening it once per root)."""
        root = Path(path).expanduser().resolve()
        with self._lock:
            project = self._projects.get(root)
        if project is None:
            layout = load_project(root)
            store = _open_project_store(layout)
            project_store = ProjectStore(layout, store)
            cad = CadOps(layout, store, backend=self._backend_for(layout))
            project = _Project(
                root=root,
                layout=layout,
                store=store,
                project_store=project_store,
                cad=cad,
                dispatcher=ToolDispatcher(project_store, cad=cad),
                ledger=IdempotencyLedger(store),
            )
            with self._lock:
                existing = self._projects.get(root)
                if existing is None:
                    self._projects[root] = project
                else:  # pragma: no cover - concurrent first open of one root
                    project.close()
                    project = existing
        self.session(session_id).project = project
        return project

    def require_project(self, session_id: str) -> _Project:
        project = self.session(session_id).project
        if project is None:
            raise McpToolError(
                "no_project_open",
                "no project is bound to this MCP session; call open_project(path) first",
            )
        return project

    # -- tool registration -------------------------------------------------

    def _register_tools(self) -> None:
        for declaration in toolgen.mcp_declarations():
            name = str(declaration["name"])
            self.app.add_tool(
                _CanonicalTool(
                    runtime=self,
                    name=name,
                    description=str(declaration["description"]),
                    parameters=cast("dict[str, Any]", declaration["inputSchema"]),
                    meta=cast("dict[str, Any]", declaration["_meta"]),
                )
            )
        self.app.add_tool(
            _ServerTool(
                runtime=self,
                handler="open_project",
                name="open_project",
                description="Bind a Hephaestus project directory to this MCP session.",
                parameters=_OPEN_PROJECT_SCHEMA,
            )
        )
        self.app.add_tool(
            _ServerTool(
                runtime=self,
                handler="list_parts",
                name="list_parts",
                description="List the part scripts of the project bound to this session.",
                parameters=_LIST_PARTS_SCHEMA,
            )
        )
        self.app.add_tool(
            _ServerTool(
                runtime=self,
                handler="answer_question",
                name="answer_question",
                description=(
                    "Answer a pending ask_user question (the follow-up call of the "
                    "non-elicitation fallback)."
                ),
                parameters=_ANSWER_QUESTION_SCHEMA,
            )
        )

    # -- dispatch ----------------------------------------------------------

    async def call_canonical(
        self, name: str, raw_arguments: dict[str, Any], ctx: Context
    ) -> ToolResult:
        """Validate, authorize, idempotently dispatch, and package one tool call."""
        decl = TOOLS_BY_NAME[name]
        parameters = cast("dict[str, Any]", toolgen.mcp_declaration(decl)["inputSchema"])
        try:
            arguments = normalize_arguments(parameters, raw_arguments)
        except SchemaError as exc:
            raise McpToolError("invalid_params", str(exc)) from exc

        session_id = ctx.session_id
        if name == "ask_user":
            return await self._ask_user(session_id, arguments, ctx)

        project = self.require_project(session_id)
        invocation = self._invocation(session_id, ctx)
        if decl.idempotent:
            return await self._dispatch_idempotent(project, decl.name, arguments, invocation)
        result = await self._run_dispatch(
            project, decl.name, arguments, invocation, decl.sequential
        )
        return _tool_result(decl.name, result)

    def _invocation(self, session_id: str, ctx: Context) -> Invocation:
        request_context = ctx.request_context
        request_id: int | str = 0
        explicit: str | None = None
        if request_context is not None:
            request_id = request_context.request_id
            meta = request_context.meta
            extra = getattr(meta, "model_extra", None) if meta is not None else None
            if isinstance(extra, dict):
                candidate = cast("dict[str, Any]", extra).get(IDEMPOTENCY_META_KEY)
                if isinstance(candidate, str) and candidate:
                    explicit = candidate
        return mcp_invocation(session_id, request_id, explicit_key=explicit)

    async def _dispatch_idempotent(
        self,
        project: _Project,
        name: str,
        arguments: dict[str, Any],
        invocation: Invocation,
    ) -> ToolResult:
        op_id = invocation.op_id
        explicit = (
            invocation.entry_id[len("meta:") :] if invocation.entry_id.startswith("meta:") else None
        )
        digest = payload_hash(
            project=str(project.root),
            tool=name,
            arguments=arguments,
            target=_target_identity(arguments),
        )
        key_ts = explicit_key_timestamp(explicit) if explicit is not None else None
        try:
            recorded = await asyncio.to_thread(project.ledger.begin, op_id, digest, key_ts=key_ts)
        except IdempotencyError as exc:
            raise McpToolError(exc.reason, exc.message) from exc
        if recorded is not None:
            return _tool_result(name, recorded.response, replayed=True)
        try:
            result = await self._run_dispatch(project, name, arguments, invocation, True)
        except BaseException:
            await asyncio.to_thread(project.ledger.abort, op_id)
            raise
        await asyncio.to_thread(project.ledger.commit, op_id, result)
        return _tool_result(name, result)

    async def _run_dispatch(
        self,
        project: _Project,
        name: str,
        arguments: dict[str, Any],
        invocation: Invocation,
        sequential: bool,
    ) -> Any:
        # ``Invocation.session_id`` is already the namespaced mcp principal id.
        principal = Principal(session_id=invocation.session_id, profile=_MCP_PROFILE, part=None)
        params: dict[str, Any] = {
            "session_id": principal.session_id,
            "run_id": f"mcp-{invocation.entry_id}",
            "tool": name,
            "arguments": arguments,
            "invocation": {
                "session_id": invocation.session_id,
                "entry_id": invocation.entry_id,
                "ordinal": invocation.ordinal,
                "provider_call_id": invocation.provider_call_id,
            },
        }

        def run() -> Any:
            return project.dispatcher.dispatch(principal, params)

        if sequential:
            async with self._sequential:
                return await asyncio.to_thread(run)
        return await asyncio.to_thread(run)

    # -- ask_user ----------------------------------------------------------

    async def _ask_user(
        self, session_id: str, arguments: dict[str, Any], ctx: Context
    ) -> ToolResult:
        question = str(arguments["question"])
        raw_options = cast("list[Any]", arguments.get("options") or [])
        # VALIDATION.md §3: a question naming ledger ids is a clarification, and
        # its shape is enforced here — before the elicitation goes out — exactly
        # as it is on the sidecar path. Options may be plain strings or
        # ``{label, consequence}`` objects; elicitation is flat, so the label is
        # what the user picks from and the consequence rides in the message.
        if requirement_ids(cast("JSONValue", arguments.get("requirement_ids"))):
            problems = question_problems(
                cast("JSONValue", question), cast("JSONValue", raw_options)
            )
            if problems:
                return _tool_result("ask_user", invalid_question_result(problems))
        options = tuple(option_label(cast("JSONValue", o)) for o in raw_options)
        allow_free_text = bool(arguments.get("allow_free_text", True))
        multi = bool(arguments.get("multi", False))

        if not _client_supports_elicitation(ctx):
            return self._question_fallback(session_id, question, options, allow_free_text, multi)

        response_type = _elicit_response_type(options, allow_free_text, multi)
        displayed = tuple(_option_display(cast("JSONValue", o)) for o in raw_options)
        action, data = await _elicit(ctx, _elicit_message(question, displayed), response_type)
        if action != "accept":
            raise McpToolError(
                f"question_{action}d" if action == "decline" else f"question_{action}",
                f"the user did not answer the question ({action})",
            )
        selection = _coerce_selection(data, options, allow_free_text, multi)
        return _tool_result("ask_user", {"selection": selection})

    def _question_fallback(
        self,
        session_id: str,
        question: str,
        options: tuple[str, ...],
        allow_free_text: bool,
        multi: bool,
    ) -> ToolResult:
        """Documented fallback: structured content + the exact follow-up call.

        The client has not advertised the elicitation capability, so the question
        cannot be asked mid-call. Hephaestus records it, returns its full
        structure, and names the follow-up tool call that delivers the answer.
        """
        pending = _PendingQuestion(
            question_id=f"q-{uuid.uuid4().hex[:16]}",
            question=question,
            options=options,
            allow_free_text=allow_free_text,
            multi=multi,
        )
        self.session(session_id).questions[pending.question_id] = pending
        payload: dict[str, Any] = {
            "status": "question_pending",
            "reason": "elicitation_unsupported",
            "question_id": pending.question_id,
            "question": question,
            "options": list(options),
            "allow_free_text": allow_free_text,
            "multi": multi,
            "follow_up": {
                "tool": "answer_question",
                "arguments": {
                    "question_id": pending.question_id,
                    "selection": list(options) if multi else "<one of options>",
                },
            },
        }
        return _tool_result("ask_user", payload)

    def answer_question(self, session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve a pending fallback question; returns the ``ask_user`` result."""
        state = self.session(session_id)
        question_id = str(arguments["question_id"])
        pending = state.questions.pop(question_id, None)
        if pending is None:
            raise McpToolError(
                "unknown_question", f"no pending question {question_id!r} in this MCP session"
            )
        raw = arguments["selection"]
        selection = _coerce_selection(raw, pending.options, pending.allow_free_text, pending.multi)
        return {"selection": selection}


# --------------------------------------------------------------------------
# FastMCP tool adapters
# --------------------------------------------------------------------------


class _CanonicalTool(Tool):
    """One ``tool_schema.md`` tool, declared from the canonical schema document."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    runtime: HephaestusMCP

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        ctx = get_context()
        try:
            return await self.runtime.call_canonical(self.name, arguments, ctx)
        except McpToolError as exc:
            return _error_result(exc.payload())
        except DispatchError as exc:
            return _error_result({"status": "error", "message": str(exc), **exc.data})
        except ProtocolError as exc:
            return _error_result(
                {"status": "error", "reason": "protocol_error", "message": str(exc)}
            )
        except HephaestusError as exc:
            return _error_result({"status": "error", "reason": exc.code, "message": exc.message})


class _ServerTool(Tool):
    """A server-local verb (``open_project`` / ``list_parts`` / ``answer_question``)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    runtime: HephaestusMCP
    handler: str

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        ctx = get_context()
        try:
            arguments = normalize_arguments(self.parameters, arguments)
            session_id = ctx.session_id
            if self.handler == "open_project":
                return _tool_result(self.name, await self._open(session_id, arguments))
            if self.handler == "list_parts":
                return _tool_result(self.name, self._list_parts(session_id))
            return _tool_result(self.name, self.runtime.answer_question(session_id, arguments))
        except SchemaError as exc:
            return _error_result(
                {"status": "error", "reason": "invalid_params", "message": str(exc)}
            )
        except McpToolError as exc:
            return _error_result(exc.payload())
        except HephaestusError as exc:
            return _error_result({"status": "error", "reason": exc.code, "message": exc.message})

    async def _open(self, session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        project = await asyncio.to_thread(
            self.runtime.open_project, session_id, str(arguments["path"])
        )
        return {
            "status": "ok",
            "root": str(project.root),
            "name": project.layout.manifest.name,
            "units": project.layout.manifest.units,
            "parts": list(project.project_store.list_parts()),
            "serve_mode": self.runtime.serve_mode,
        }

    def _list_parts(self, session_id: str) -> dict[str, Any]:
        project = self.runtime.require_project(session_id)
        parts: list[dict[str, Any]] = []
        for name in project.project_store.list_parts():
            snapshot = project.project_store.read_part(name)
            parts.append(
                {
                    "name": name,
                    "path": str(snapshot.path.relative_to(project.root)),
                    "content_hash": snapshot.content_hash,
                    "snapshot_ref": snapshot.snapshot_ref,
                }
            )
        return {"status": "ok", "parts": parts}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _open_project_store(layout: ProjectLayout) -> OpStore:
    """Create-or-open the project's opstore (same configuration as the bridge)."""
    layout.store_root.mkdir(parents=True, exist_ok=True)
    layout.journal_dir.mkdir(parents=True, exist_ok=True)
    roots = DefaultProtectedRoots(layout)
    if (layout.store_root / _STATE_DB_NAME).exists():
        store = OpStore.open(layout.store_root, protected_roots=roots)
    else:
        store = OpStore.create(layout.store_root, bridge_store_config(), protected_roots=roots)
    roots.bind(store)
    return store


def _target_identity(arguments: dict[str, Any]) -> str | None:
    """The normalized target the payload hash binds to (part / check / ref)."""
    for key in ("name", "part", "delegation_ref"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return f"{key}:{value}"
    return None


def _client_supports_elicitation(ctx: Context) -> bool:
    request_context = ctx.request_context
    if request_context is None:  # pragma: no cover - never outside a request
        return False
    return bool(
        request_context.session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())
        )
    )


async def _elicit(ctx: Context, message: str, response_type: Any) -> tuple[str, Any]:
    """``ctx.elicit`` narrowed to ``(action, data)``.

    FastMCP's return type is generic in the response type, which is built at
    runtime from the ``ask_user`` arguments, so the result is unknown to the
    type checker and is narrowed here once instead of at every use.
    """
    outcome = await ctx.elicit(message, response_type=response_type)  # pyright: ignore[reportUnknownVariableType]
    action = str(getattr(outcome, "action", "decline"))  # pyright: ignore[reportUnknownArgumentType]
    data: Any = getattr(outcome, "data", None)  # pyright: ignore[reportUnknownArgumentType]
    return action, data


def _option_display(option: JSONValue) -> str:
    """``label — consequence`` when the option states one, else just the label."""
    consequence = option_consequence(option)
    label = option_label(option)
    return f"{label} — {consequence}" if consequence else label


def _elicit_message(question: str, options: Sequence[str]) -> str:
    if not options:
        return question
    listed = ", ".join(options)
    return f"{question}\n\nOptions: {listed}"


def _elicit_response_type(options: Sequence[str], allow_free_text: bool, multi: bool) -> Any:
    """Map ``ask_user`` shape onto an MCP elicitation response schema.

    MCP elicitation schemas are flat and primitive, so an "enum *or* free text"
    answer is not expressible: when free text is allowed the answer is a string
    (or list of strings) and the options ride in the message; otherwise the
    options become a single- or multi-select enum.
    """
    if options and not allow_free_text:
        return [list(options)] if multi else list(options)
    return list[str] if multi else str


def _coerce_selection(
    data: Any, options: Sequence[str], allow_free_text: bool, multi: bool
) -> str | list[str]:
    """Normalize an answer to the canonical ``{selection}`` value; validate it."""
    if multi:
        if isinstance(data, str):
            values = [data]
        elif isinstance(data, list):
            values = [str(item) for item in cast("list[Any]", data)]
        else:
            raise McpToolError("invalid_answer", "a multi-select answer must be a list of strings")
        if not allow_free_text:
            _require_options(values, options)
        return values
    if isinstance(data, list):
        items = cast("list[Any]", data)
        if len(items) != 1:
            raise McpToolError("invalid_answer", "this question accepts exactly one selection")
        value = str(items[0])
    else:
        value = str(data)
    if not allow_free_text:
        _require_options([value], options)
    return value


def _require_options(values: Sequence[str], options: Sequence[str]) -> None:
    allowed = set(options)
    for value in values:
        if value not in allowed:
            raise McpToolError(
                "invalid_answer", f"{value!r} is not one of the offered options {list(options)!r}"
            )


def _tool_result(name: str, payload: Any, *, replayed: bool = False) -> ToolResult:
    """Package a dispatch result as MCP content (+ images for ``inspect_part``)."""
    structured: dict[str, Any] = (
        cast("dict[str, Any]", payload) if isinstance(payload, dict) else {"result": payload}
    )
    images: list[ContentBlock] = []
    if name == "inspect_part":
        structured, images = _split_images(structured)
    meta = {"hephaestus.dev/replayed": True} if replayed else None
    content: list[ContentBlock] = [_text_block(structured), *images]
    return ToolResult(content=content, structured_content=structured, meta=meta)


def _error_result(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(content=[_text_block(payload)], structured_content=payload, is_error=True)


def _text_block(structured: dict[str, Any]) -> TextContent:
    """The JSON text block, held inside the §5 dual text cap (50 KiB / 2000 lines).

    Oversized results are *never* silently truncated into misleading JSON: the
    text block degrades to a machine-readable notice while the structured
    content — and the artifact refs that page it — stay complete.
    """
    text = json.dumps(structured, sort_keys=True, ensure_ascii=False)
    if len(text.encode("utf-8")) <= _TEXT_MAX_BYTES and text.count("\n") + 1 <= _TEXT_MAX_LINES:
        return TextContent(type="text", text=text)
    notice = json.dumps(
        {
            "status": "text_result_truncated",
            "message": (
                "the result exceeds the 50 KiB / 2000 line text cap; read the structured "
                "content, or page the value through read_artifact"
            ),
            "keys": sorted(structured),
        },
        sort_keys=True,
    )
    return TextContent(type="text", text=notice)


def _split_images(structured: dict[str, Any]) -> tuple[dict[str, Any], list[ContentBlock]]:
    """Move ``inspect_part`` image payloads into MCP image content blocks.

    The structured result keeps every image's *description* (view, channel,
    render artifact ref) so the client can still address the immutable artifact;
    only the base64 bytes move into the image blocks, within the
    ``schemas/bridge_limits.json`` per-image byte and per-result count budgets.
    """
    raw = structured.get("images")
    if not isinstance(raw, list):
        return structured, []
    blocks: list[ContentBlock] = []
    described: list[dict[str, Any]] = []
    for entry in cast("list[Any]", raw)[:_MAX_IMAGES]:
        if not isinstance(entry, dict):  # pragma: no cover - cad_ops emits dicts
            continue
        image = cast("dict[str, Any]", entry)
        data = image.get("data")
        meta = {k: v for k, v in image.items() if k != "data"}
        if isinstance(data, str) and len(base64.b64decode(data, validate=True)) <= _MAX_IMAGE_BYTES:
            blocks.append(
                ImageContent(
                    type="image",
                    data=data,
                    mimeType=str(image.get("mime_type", "image/png")),
                    _meta={"hephaestus.dev/render": meta},
                )
            )
            meta = {**meta, "inline": True}
        else:
            meta = {**meta, "inline": False}
        described.append(meta)
    reduced = dict(structured)
    reduced["images"] = described
    return reduced, blocks


def build_app(
    *, serve_mode: bool = False, backend: ExecBackend | None = None, name: str = "hephaestus"
) -> tuple[FastMCP[None], HephaestusMCP]:
    """Build the FastMCP app and the runtime that owns its state."""
    runtime = HephaestusMCP(serve_mode=serve_mode, backend=backend, name=name)
    return runtime.app, runtime
