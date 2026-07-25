"""``py.tool_dispatch``: session-principal authz -> core call -> idempotent result.

The sidecar sends ``py.tool_dispatch {session_id, run_id, tool, arguments,
invocation}``; this module resolves it against a bound session **principal**:

1. **Profile availability.** A tool is only dispatchable by a session whose
   profile is in ``ToolDecl.profiles`` (orchestrator-only tools — delegation,
   ``edit_globals``, the project-check family — reject part/quick-edit sessions
   with ``scope_denied``).
2. **Object scope.** A part / quick-edit session is bound to one normalized part
   id; any tool addressing a *different* part by name — or a nameless
   ``scope="project"`` ``set_params`` / ``run_checks`` — is ``scope_denied``
   (digest §2). The orchestrator addresses every part.
3. **Core routing.** Wired file-CRUD tools go through
   :class:`~hephaestus.core.project_store.store.ProjectStore`, whose CAS writes
   are idempotent on the **trusted invocation id** via opstore opkeys (a retry of
   a committed write replays the recorded outcome; a same-id/different-payload
   presentation raises ``KeyPayloadMismatchError``). Registry tools and the CAD
   geometry/delegation tools return a typed ``not_implemented`` pending their
   integration agents.

Authz / not-implemented failures raise :class:`DispatchError` (a
:class:`~hephaestus.agent_bridge.protocol.ProtocolError` subclass carrying a
stable ``reason``); the supervisor maps it to a JSON-RPC error frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from hephaestus.core.errors import AddressingError, HephaestusError
from hephaestus.core.project_store.store import ProjectStore, WriteConflictError
from hephaestus.core.tools_decl import TOOLS_BY_NAME, ToolDecl

from .cad_ops import CadOps
from .limits import enforce_max_utf8_bytes
from .protocol import ErrorCode, ProtocolError

__all__ = [
    "BLANK_TEMPLATES",
    "MUTATION_TOOLS",
    "REGISTRY_TOOLS",
    "DispatchError",
    "Invocation",
    "Principal",
    "ToolDispatcher",
]

#: Tools whose result never re-does work: idempotency-contract members.
MUTATION_TOOLS: frozenset[str] = frozenset(
    name for name, decl in TOOLS_BY_NAME.items() if decl.idempotent
)

#: Registry-backed tools stubbed until the registry agent lands.
REGISTRY_TOOLS: frozenset[str] = frozenset(
    {"load_skill", "list_skills", "search_parts_store", "instance_store_part", "search_materials"}
)

#: Minimal create-templates (Stage 1 owns richer scaffolds; blank is enough here).
BLANK_TEMPLATES: dict[str, str] = {
    "blank": "from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n",
    "solid": "from build123d import *\n\n\nwith BuildPart() as part:\n    Box(10, 10, 10)\n",
    "sheet": "from build123d import *\n\n\nwith BuildSketch() as sk:\n    Rectangle(50, 50)\n",
    "from_store": "from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n",
}


class DispatchError(ProtocolError):
    """A dispatch-layer refusal; ``reason`` is a stable machine token."""

    def __init__(self, reason: str, message: str, *, code: int = ErrorCode.INVALID_PARAMS) -> None:
        super().__init__(code, message)
        self.reason = reason
        self.data: dict[str, Any] = {"reason": reason}


@dataclass(frozen=True)
class Invocation:
    """Trusted invocation metadata; the idempotency key is derived, never model-set."""

    session_id: str
    entry_id: str
    ordinal: int
    provider_call_id: str

    @classmethod
    def from_params(cls, session_id: str, raw: dict[str, Any] | None) -> Invocation:
        raw = raw or {}
        return cls(
            session_id=str(raw.get("session_id", session_id)),
            entry_id=str(raw.get("entry_id", "")),
            ordinal=int(raw.get("ordinal", 0)),
            provider_call_id=str(raw.get("provider_call_id", "")),
        )

    @property
    def op_id(self) -> str:
        """Stable idempotency raw id: unique across distinct persisted entries.

        Repeated provider ids (``call_0`` across entries) stay distinct because
        the persisted entry id and ordinal are part of the key.
        """
        return f"{self.session_id}|{self.entry_id}|{self.ordinal}|{self.provider_call_id}"


@dataclass(frozen=True)
class Principal:
    """The session identity a dispatch is authorized against."""

    session_id: str
    profile: str  # "part" | "orchestrator" | "quick_edit"
    part: str | None  # bound part id for part/quick_edit; None for orchestrator

    @property
    def is_orchestrator(self) -> bool:
        return self.profile == "orchestrator"


class ToolDispatcher:
    """Authz + idempotent core routing for one project's ``py.tool_dispatch``."""

    def __init__(self, store: ProjectStore, *, cad: CadOps | None = None) -> None:
        self._store = store
        self._cad = cad

    # -- entry point -------------------------------------------------------

    def dispatch(self, principal: Principal, params: dict[str, Any]) -> Any:
        """Handle one ``py.tool_dispatch`` request; returns the tool result."""
        tool_name = str(params.get("tool", ""))
        decl = TOOLS_BY_NAME.get(tool_name)
        if decl is None:
            raise DispatchError(
                "unknown_tool", f"no such tool: {tool_name!r}", code=ErrorCode.METHOD_NOT_FOUND
            )
        arguments: dict[str, Any] = dict(params.get("arguments") or {})
        invocation = Invocation.from_params(principal.session_id, params.get("invocation"))
        self._authorize(principal, decl, arguments)
        return self._route(principal, decl, arguments, invocation)

    # -- authorization -----------------------------------------------------

    def _authorize(self, principal: Principal, decl: ToolDecl, arguments: dict[str, Any]) -> None:
        if principal.profile not in decl.profiles:
            raise DispatchError(
                "scope_denied",
                f"tool {decl.name!r} is not available to a {principal.profile} session",
            )
        if principal.is_orchestrator:
            return  # orchestrator addresses every part / project scope
        bound = principal.part
        if bound is None:
            raise DispatchError("scope_denied", f"{principal.profile} session has no bound part")
        # Nameless project-scope operations are orchestrator-only.
        if decl.name in {"set_params", "run_checks"} and arguments.get("scope") == "project":
            raise DispatchError(
                "scope_denied",
                f"{decl.name} scope='project' is not available to a part session",
            )
        for addressed in self._addressed_parts(decl, arguments):
            if addressed != bound:
                raise DispatchError(
                    "scope_denied",
                    f"{principal.profile} session bound to {bound!r} may not address {addressed!r}",
                )

    @staticmethod
    def _addressed_parts(decl: ToolDecl, arguments: dict[str, Any]) -> list[str]:
        """Part ids the arguments address (for object-scope enforcement)."""
        parts: list[str] = []
        name = arguments.get("name")
        if isinstance(name, str) and name and decl.name != "load_skill":
            parts.append(name)
        part = arguments.get("part")
        if isinstance(part, str) and part:
            parts.append(part)
        return parts

    # -- routing -----------------------------------------------------------

    def _route(
        self,
        principal: Principal,
        decl: ToolDecl,
        arguments: dict[str, Any],
        invocation: Invocation,
    ) -> Any:
        handler = {
            "read_part": self._read_part,
            "create_part": self._create_part,
            "edit_part": self._edit_part,
            "write_part": self._write_part,
            "read_globals": self._read_globals,
        }.get(decl.name)
        if handler is not None:
            return handler(arguments, invocation)
        if decl.name in {"build_part", "inspect_part"} and self._cad is not None:
            return self._cad_op(decl.name, arguments)
        if decl.name in REGISTRY_TOOLS:
            raise DispatchError(
                "not_implemented",
                f"registry tool {decl.name!r} awaits the registry agent",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        # Enforce the prompt cap here even though the delegation body is not yet
        # wired (parity with the generated TypeBox validator).
        prompt = arguments.get("prompt")
        if decl.name == "delegate_part_agent" and isinstance(prompt, str):
            enforce_max_utf8_bytes(prompt, decl.max_utf8_fields["prompt"], field="prompt")
        raise DispatchError(
            "not_implemented",
            f"tool {decl.name!r} is not wired in this runtime-core slice",
            code=ErrorCode.METHOD_NOT_FOUND,
        )

    # -- geometry handlers (build / inspect via CadOps) --------------------

    def _cad_op(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._cad is not None
        name = str(arguments["name"])
        try:
            if tool == "build_part":
                raw_params = arguments.get("params")
                params: dict[str, Any] | None = None
                if isinstance(raw_params, dict):
                    params = cast("dict[str, Any]", raw_params)
                return self._cad.build_part(name, params)
            raw_views = arguments.get("views")
            views = cast("list[Any]", raw_views) if isinstance(raw_views, list) else None
            return self._cad.inspect_part(
                name,
                views=None if views is None else [str(v) for v in views],
                channel=str(arguments.get("channel", "rgb")),
                mask_mode=str(arguments.get("mask_mode", "solid")),
                section_plane=(
                    str(arguments["section_plane"])
                    if arguments.get("section_plane") is not None
                    else None
                ),
                explode=float(arguments.get("explode", 0.0)),
                last_good=bool(arguments.get("last_good", False)),
                artifact_ref=(
                    str(arguments["artifact_ref"])
                    if arguments.get("artifact_ref") is not None
                    else None
                ),
                focus=str(arguments["focus"]) if arguments.get("focus") is not None else None,
            )
        except AddressingError as exc:
            raise DispatchError("invalid_part", str(exc)) from exc
        except HephaestusError as exc:
            raise DispatchError("build_failed", exc.message) from exc

    # -- wired handlers ----------------------------------------------------

    def _read_part(self, arguments: dict[str, Any], _inv: Invocation) -> dict[str, Any]:
        name = str(arguments["name"])
        try:
            snap = self._store.read_part(name)
        except AddressingError as exc:
            raise DispatchError("invalid_part", str(exc)) from exc
        return {
            "script": snap.content,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "line_count": snap.content.count("\n") + (0 if snap.content.endswith("\n") else 1),
            "truncated": False,
        }

    def _create_part(self, arguments: dict[str, Any], inv: Invocation) -> dict[str, Any]:
        name = str(arguments["name"])
        template = str(arguments.get("template", "blank"))
        initial = BLANK_TEMPLATES.get(template, BLANK_TEMPLATES["blank"])
        try:
            outcome = self._store.write_part(name, initial, base_hash=None, op_id=inv.op_id)
        except WriteConflictError as exc:
            # File already exists — create fails without mutation.
            raise DispatchError(
                "already_exists", f"part {name!r} already exists", code=ErrorCode.INVALID_PARAMS
            ) from exc
        snap = outcome.snapshot
        return {
            "path": str(snap.path),
            "initial_script": snap.content,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "replayed": outcome.replayed,
        }

    def _edit_part(self, arguments: dict[str, Any], inv: Invocation) -> dict[str, Any]:
        name = str(arguments["name"])
        expected_hash = str(arguments["expected_hash"])
        old_str = str(arguments["old_str"])
        new_str = str(arguments["new_str"])
        try:
            snap = self._store.read_part(name)
        except AddressingError as exc:
            raise DispatchError("invalid_part", str(exc)) from exc
        if snap.content_hash != expected_hash:
            return {
                "applied": False,
                "conflict": {
                    "current_hash": snap.content_hash,
                    "current_script": snap.content,
                    "current_snapshot_ref": snap.snapshot_ref,
                },
            }
        occurrences = snap.content.count(old_str)
        if occurrences == 0:
            return {"applied": False, "diff": "", "line": 0}
        if occurrences > 1:
            raise DispatchError(
                "ambiguous_edit",
                f"old_str occurs {occurrences} times in {name!r}; must be unique",
            )
        new_content = snap.content.replace(old_str, new_str, 1)
        line = snap.content[: snap.content.index(old_str)].count("\n") + 1
        return self._commit_write(name, new_content, expected_hash, inv, extra={"line": line})

    def _write_part(self, arguments: dict[str, Any], inv: Invocation) -> dict[str, Any]:
        name = str(arguments["name"])
        expected_hash = str(arguments["expected_hash"])
        script = str(arguments["script"])
        try:
            self._store.read_part(name)  # ensure it exists / register drift base
        except AddressingError as exc:
            raise DispatchError("invalid_part", str(exc)) from exc
        return self._commit_write(name, script, expected_hash, inv)

    def _commit_write(
        self,
        name: str,
        content: str,
        base_hash: str,
        inv: Invocation,
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            outcome = self._store.write_part(name, content, base_hash=base_hash, op_id=inv.op_id)
        except WriteConflictError as exc:
            return {
                "applied": False,
                "conflict": {
                    "current_hash": exc.live_hash,
                    "current_script": exc.live_content,
                    "current_snapshot_ref": exc.live_snapshot_ref,
                    "base_snapshot_ref": exc.base_ref,
                    "attempted_snapshot_ref": exc.attempted_ref,
                },
            }
        snap = outcome.snapshot
        result: dict[str, Any] = {
            "applied": True,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "replayed": outcome.replayed,
        }
        if extra:
            result.update(extra)
        return result

    def _read_globals(self, _arguments: dict[str, Any], _inv: Invocation) -> dict[str, Any]:
        snap = self._store.read_globals()
        if snap is None:
            raise DispatchError(
                "invalid_part", "project has no globals.py", code=ErrorCode.INVALID_PARAMS
            )
        return {
            "script": snap.content,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "truncated": False,
        }
