"""``py.tool_dispatch``: session-principal authz -> core call -> idempotent result.

The sidecar sends ``py.tool_dispatch {session_id, run_id, tool, arguments,
invocation}``; this module resolves it against a bound session **principal**:

1. **Profile availability.** A tool is only dispatchable by a session whose
   profile is in ``ToolDecl.profiles`` (orchestrator-only tools — delegation,
   ``edit_globals``/``read_globals``, the project-check family — reject
   part/quick-edit sessions with ``scope_denied``).
2. **Object scope.** A part / quick-edit session is bound to one normalized part
   id; any tool addressing a *different* part — by ``name``, by ``part``, or by a
   cross-part ``"<part>/<selector>"`` measurement selector — as well as a nameless
   ``scope="project"`` ``set_params`` / ``run_checks``, is ``scope_denied``
   (digest §2). The orchestrator addresses every part.
3. **Core routing.** File-CRUD tools go through
   :class:`~hephaestus.core.project_store.store.ProjectStore`; everything
   geometric, parametric, check-related, artifact-related or export-related goes
   through :class:`~hephaestus.agent_bridge.cad_ops.CadOps`; the delegation
   family goes through :class:`~hephaestus.agent_bridge.delegation.DelegationService`;
   ``query_snapshot`` goes through
   :class:`~hephaestus.agent_bridge.query_snapshot.QuerySnapshotService`; the
   registry family (skills / parts store / materials) goes through
   :class:`~hephaestus.core.registry.RegistryOps` over hash-pinned registries.

Every mutation family is idempotent on the **trusted invocation id** via opstore
opkeys: a retry of a committed write replays the recorded outcome, and a
same-id/different-payload presentation is a hard mismatch
(``KeyPayloadMismatchError`` for the file/param WAL, ``key_payload_mismatch`` for
the export and delegation WALs). Two families resolve a retry to a *discriminated
result* rather than a replay, because their compare-and-swap gate runs in front of
an idempotency key owned by ``hephaestus.core``: an ``edit_part``/``write_part``
retry returns ``conflict`` with the live hash it wrote itself, and a project-check
retry returns ``already_exists`` (create) or ``conflict(kind="stale_hash")``
(edit). Neither duplicates work nor discards bytes — the caller reconciles from
the returned live hash — and ``edit_globals`` claims its key *before* the CAS
precisely so it replays ``applied`` instead.

Authz / capability / not-implemented failures raise :class:`DispatchError` (a
:class:`~hephaestus.agent_bridge.protocol.ProtocolError` subclass carrying a
stable ``reason``); the supervisor maps it to a JSON-RPC error frame, and the
sidecar proxy turns recognized ``capability_not_available`` /
``image_model_required`` codes into discriminated tool results.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from hephaestus.contract.tools_decl import (
    IDENT_PATTERN,
    READ_ARTIFACT_PAGE_MAX,
    TOOLS_BY_NAME,
    ToolDecl,
)
from hephaestus.core.errors import (
    AddressingError,
    HephaestusError,
    IncoherentProjectSnapshotError,
    ValidationError,
)
from hephaestus.core.project_store.store import ProjectStore, WriteConflictError
from hephaestus.core.registry import TEXT_MAX_LINES, RegistryError, RegistryOps
from opstore.types import TerminalState

from .cad_ops import (
    CadOpError,
    CadOps,
    ParamConflict,
    active_run,
    check_template,
    clarification_gate,
    inherit_run_request_text,
)
from .delegation import (
    DEADLINE_DEFAULT_S,
    DelegationError,
    DelegationPhase,
    DelegationRow,
    DelegationService,
    Delivery,
    Rejected,
)
from .limits import LimitError, enforce_max_utf8_bytes
from .protocol import ErrorCode, ProtocolError
from .query_snapshot import (
    BudgetLedger,
    QuerySnapshotError,
    QuerySnapshotService,
    RenderBundle,
    SnapshotCaller,
    SnapshotUsage,
)

__all__ = [
    "BLANK_TEMPLATES",
    "CAD_TOOLS",
    "DELEGATION_TOOLS",
    "MUTATION_TOOLS",
    "NOT_IMPLEMENTED_TOOLS",
    "REGISTRY_TOOLS",
    "REVIEWER_PROFILE",
    "STORE_TOOLS",
    "DelegationRunner",
    "DispatchError",
    "Invocation",
    "Principal",
    "ToolDispatcher",
]

#: The VALIDATION.md §5 termination-review profile: project-wide reads only.
REVIEWER_PROFILE: str = "reviewer"

#: Tools whose result never re-does work: idempotency-contract members.
MUTATION_TOOLS: frozenset[str] = frozenset(
    name for name, decl in TOOLS_BY_NAME.items() if decl.idempotent
)

#: Registry-backed tools: contextual skills/materials and the executable parts
#: store, served from hash-pinned registries through :class:`RegistryOps`.
REGISTRY_TOOLS: frozenset[str] = frozenset(
    {"load_skill", "list_skills", "search_parts_store", "instance_store_part", "search_materials"}
)

#: Everything ``py.tool_dispatch`` deliberately does NOT route into the core.
#: ``ask_user`` never reaches this method at all — the sidecar proxy sends it as
#: ``py.ask_user`` so the run can suspend on the human answer.
NOT_IMPLEMENTED_TOOLS: frozenset[str] = frozenset({"ask_user"})

#: The routing table, as four disjoint families (the audit test asserts that
#: these plus :data:`NOT_IMPLEMENTED_TOOLS` exactly cover the declared surface).
STORE_TOOLS: frozenset[str] = frozenset(
    {"read_part", "create_part", "edit_part", "write_part", "read_globals"}
)
CAD_TOOLS: frozenset[str] = frozenset(
    {
        "build_part",
        "inspect_part",
        "set_params",
        "edit_globals",
        "list_project_checks",
        "create_project_check",
        "read_project_check",
        "edit_project_check",
        "measure",
        # COMPARE.md §2 — read-only, freely retryable, stores nothing.
        "compare_solids",
        # MESH_INGEST.md §7.2 — the same terms against a scan target, and the
        # one new tool of the whole stage.
        "compare_to_scan",
        "run_checks",
        "record_requirements",
        "read_requirements",
        "update_requirement",
        # ASSEMBLY.md §3 — the constraint quartet. Model-writable (declaring is
        # cheap, reversible and measured), but never erasing: a withdrawal is a
        # new generation carrying its reason.
        "declare_constraint",
        "update_constraint",
        "read_constraints",
        "check_assembly",
        # KINEMATICS.md §6 (Stage 9A/9B) — the joint, pose and motion-check
        # quartets plus check_motion, on the 8C quartet decision unchanged:
        # model-writable because declaring is cheap, reversible and measured,
        # never erasing.
        "declare_joint",
        "update_joint",
        "read_joints",
        "declare_pose",
        "update_pose",
        "read_poses",
        "declare_motion_check",
        "update_motion_check",
        "read_motion_checks",
        "check_motion",
        # KINEMATICS.md §5/§6 (Stage 9C) — the coupling triplet, same decision.
        "declare_coupling",
        "update_coupling",
        "read_couplings",
        "read_artifact",
        # INGEST.md §2 — read-only, freely retryable. There is deliberately no
        # `add_reference`: registration is operator-side, so the model's only
        # relationship with references/ is reading them.
        "list_references",
        "read_reference",
        "export_part",
        "query_snapshot",
        "run_dfm",
        "generate_drawing",
        "generate_doc",
    }
)
DELEGATION_TOOLS: frozenset[str] = frozenset(
    {"delegate_part_agent", "get_delegation_status", "cancel_delegation"}
)

#: Minimal create-templates (Stage 1 owns richer scaffolds; blank is enough here).
BLANK_TEMPLATES: dict[str, str] = {
    "blank": "from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n",
    "solid": "from build123d import *\n\n\nwith BuildPart() as part:\n    Box(10, 10, 10)\n",
    "sheet": "from build123d import *\n\n\nwith BuildSketch() as sk:\n    Rectangle(50, 50)\n",
    "from_store": "from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n",
}

_IDENT_RE = re.compile(IDENT_PATTERN)

#: Selector-bearing arguments whose ``"<part>/<selector>"`` prefix addresses a part.
_SELECTOR_FIELDS: tuple[str, ...] = ("a", "b")

#: ``compare_solids`` target prefix naming another part (COMPARE.md §2).
_PART_TARGET_PREFIX: str = "part:"

#: Tools whose ``name`` argument is NOT a part id, so object-scope enforcement
#: must not read it as one: a skill name, and (INGEST.md §2) a reference name.
_NON_PART_NAME_TOOLS: frozenset[str] = frozenset(
    {"load_skill", "read_reference", "list_references"}
)


class DispatchError(ProtocolError):
    """A dispatch-layer refusal; ``reason`` is a stable machine token."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        code: int = ErrorCode.INVALID_PARAMS,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message)
        self.reason = reason
        self.data: dict[str, Any] = {"reason": reason, **(data or {})}


@runtime_checkable
class DelegationRunner(Protocol):
    """Executes an admitted child delegation to its single durable terminal.

    Injected by the session/workflow integration (it owns part sessions and the
    sidecar); the delegation *state machine* itself lives in
    :mod:`hephaestus.agent_bridge.delegation`. When no runner is configured a
    synchronous ``delivery="prompt"`` delegation cannot execute, so the dispatcher
    finalizes it as exactly one ``interrupted`` terminal rather than inventing a
    completion.
    """

    def run(self, service: DelegationService, row: DelegationRow) -> None: ...


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
    profile: str  # "part" | "orchestrator" | "quick_edit" | "reviewer"
    part: str | None  # bound part id for part/quick_edit; None for orchestrator/reviewer

    @property
    def is_orchestrator(self) -> bool:
        return self.profile == "orchestrator"

    @property
    def is_reviewer(self) -> bool:
        """VALIDATION.md §5: project-wide *read-only* termination reviewer."""
        return self.profile == REVIEWER_PROFILE


class _NullLedger:
    """Charges nothing (the budget ledger is owned by the session service)."""

    def charge(self, run_id: str, usage: SnapshotUsage) -> None:
        return None


class _CadBundlePreparer:
    """Adapts :class:`CadOps` render-bundle preparation to the snapshot service."""

    def __init__(self, cad: CadOps, name: str, views: tuple[str, ...], artifact_ref: str | None):
        self._cad = cad
        self._name = name
        self._views = views
        self._artifact_ref = artifact_ref

    def prepare(self, run_id: str, question: str, image_refs: tuple[str, ...]) -> RenderBundle:
        bundle = self._cad.render_bundle(self._name, self._views, self._artifact_ref)
        images_raw = bundle.get("images")
        refs: list[str] = []
        payloads: list[bytes] = []
        if isinstance(images_raw, list):
            for entry in cast("list[Any]", images_raw):
                if not isinstance(entry, dict):
                    continue
                record = cast("dict[str, Any]", entry)
                ref = record.get("render_artifact_ref")
                png = record.get("png")
                if isinstance(ref, str):
                    refs.append(ref)
                if isinstance(png, str):
                    payloads.append(bytes.fromhex(png))
        return RenderBundle(image_refs=tuple(refs), images=tuple(payloads))


class ToolDispatcher:
    """Authz + idempotent core routing for one project's ``py.tool_dispatch``."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        cad: CadOps | None = None,
        delegation: DelegationService | None = None,
        delegation_runner: DelegationRunner | None = None,
        snapshot_caller: SnapshotCaller | None = None,
        budget_ledger: BudgetLedger | None = None,
        registry: RegistryOps | None = None,
    ) -> None:
        self._store = store
        self._cad = cad
        self._registry = registry
        self._delegation = delegation
        self._delegation_runner = delegation_runner
        self._snapshot_caller = snapshot_caller
        self._ledger: BudgetLedger = budget_ledger or _NullLedger()

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
        run_id = str(params.get("run_id", ""))
        self._authorize(principal, decl, arguments)
        try:
            # INTERFACE.md §7A.4/§19.23: the run this call belongs to is the
            # scope ``CadOps.request_text`` answers in. Entered HERE — the one
            # dispatcher every tool rides (mission rule 6) — so no op has to
            # remember to ask, and two overlapping turns cannot read each
            # other's request. An absent run id (an HTTP tool route, MCP) scopes
            # nothing and leaves the ops object's own text in force.
            with active_run(run_id):
                return self._route(principal, decl, arguments, invocation, run_id)
        except ParamConflict as exc:
            # A stale expected_state_hash is a discriminated *result*, not an error.
            return {
                "effective": dict(exc.current.values),
                "rejected": [],
                "stale_parts": [],
                "conflict": {
                    "current_state_hash": exc.current.state_hash,
                    "current_values": dict(exc.current.values),
                },
            }
        except CadOpError as exc:
            raise DispatchError(
                exc.reason,
                exc.message,
                data={
                    **({"code": exc.reason} if exc.reason == "capability_not_available" else {}),
                    **dict(exc.data),
                },
            ) from exc
        except RegistryError as exc:
            # Registry refusals are already typed (unknown_skill, invalid_params,
            # generator_failed, sandbox_denied, registry_integrity, ...); the
            # capability code rides through so the proxy discriminates it.
            raise DispatchError(
                exc.reason,
                exc.message,
                data={
                    **({"code": exc.reason} if exc.reason == "capability_not_available" else {}),
                    **dict(exc.data),
                },
            ) from exc
        except AddressingError as exc:
            raise DispatchError(
                "invalid_part", exc.message, data={"candidates": list(exc.candidates)}
            ) from exc
        except IncoherentProjectSnapshotError as exc:
            raise DispatchError("incoherent_project_snapshot", exc.message) from exc

    # -- authorization -----------------------------------------------------

    def _authorize(self, principal: Principal, decl: ToolDecl, arguments: dict[str, Any]) -> None:
        if principal.profile not in decl.profiles:
            raise DispatchError(
                "scope_denied",
                f"tool {decl.name!r} is not available to a {principal.profile} session",
            )
        if principal.is_orchestrator:
            return  # orchestrator addresses every part / project scope
        if principal.is_reviewer:
            # VALIDATION.md §5: the reviewer reads the whole project (it judges
            # every part) and may change none of it. The generated `reviewer`
            # tool profile already excludes mutation and delegation; this is the
            # second, independent enforcement of the same rule, so a future
            # profiles= edit cannot silently hand the reviewer a write.
            if decl.name in MUTATION_TOOLS or decl.name in DELEGATION_TOOLS:
                raise DispatchError(
                    "scope_denied",
                    f"tool {decl.name!r} mutates or delegates; a reviewer session may do neither",
                )
            return
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
        if isinstance(name, str) and name and decl.name not in _NON_PART_NAME_TOOLS:
            parts.append(name)
        part = arguments.get("part")
        if isinstance(part, str) and part:
            parts.append(part)
        if decl.name == "compare_solids":
            # COMPARE.md §2: a "part:<name>" target addresses that part, so a
            # bound session may not reach another part through it. An
            # "import:<path>" target addresses no part — confinement for it is
            # the INGEST.md §1 walk, one layer down.
            target = arguments.get("target")
            if isinstance(target, str) and target.startswith(_PART_TARGET_PREFIX):
                name = target[len(_PART_TARGET_PREFIX) :]
                if _IDENT_RE.match(name):
                    parts.append(name)
        if decl.name == "measure":
            # A cross-part "<part>/<selector>" resolves outside a bound session.
            for field in _SELECTOR_FIELDS:
                selector = arguments.get(field)
                if not isinstance(selector, str) or "/" not in selector:
                    continue
                prefix = selector.split("/", 1)[0]
                if _IDENT_RE.match(prefix):
                    parts.append(prefix)
        return parts

    # -- routing -----------------------------------------------------------

    def _route(
        self,
        principal: Principal,
        decl: ToolDecl,
        arguments: dict[str, Any],
        invocation: Invocation,
        run_id: str,
    ) -> Any:
        store_handler = {
            "read_part": self._read_part,
            "create_part": self._create_part,
            "edit_part": self._edit_part,
            "write_part": self._write_part,
            "read_globals": self._read_globals,
        }.get(decl.name)
        if store_handler is not None:
            return store_handler(arguments, invocation)
        if decl.name in NOT_IMPLEMENTED_TOOLS:
            raise DispatchError(
                "not_implemented",
                f"{decl.name!r} is not routed through py.tool_dispatch in this runtime",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        if decl.name in REGISTRY_TOOLS:
            return self._registry_op(decl, arguments)
        if decl.name in DELEGATION_TOOLS:
            return self._delegation_op(decl, arguments, invocation, run_id)
        cad = self._cad
        if cad is None:
            raise DispatchError(
                "not_implemented",
                f"tool {decl.name!r} needs the CAD core, which is not wired in this runtime",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        cad_handler = {
            "build_part": self._build_part,
            "inspect_part": self._inspect_part,
            "set_params": self._set_params,
            "edit_globals": self._edit_globals,
            "list_project_checks": self._list_project_checks,
            "create_project_check": self._create_project_check,
            "read_project_check": self._read_project_check,
            "edit_project_check": self._edit_project_check,
            "measure": self._measure,
            "compare_solids": self._compare_solids,
            "compare_to_scan": self._compare_to_scan,
            "run_checks": self._run_checks,
            "record_requirements": self._record_requirements,
            "read_requirements": self._read_requirements,
            "update_requirement": self._update_requirement,
            "declare_constraint": self._declare_constraint,
            "update_constraint": self._update_constraint,
            "read_constraints": self._read_constraints,
            "check_assembly": self._check_assembly,
            "declare_joint": self._declare_joint,
            "update_joint": self._update_joint,
            "read_joints": self._read_joints,
            "declare_pose": self._declare_pose,
            "update_pose": self._update_pose,
            "read_poses": self._read_poses,
            "declare_motion_check": self._declare_motion_check,
            "update_motion_check": self._update_motion_check,
            "read_motion_checks": self._read_motion_checks,
            "check_motion": self._check_motion,
            "declare_coupling": self._declare_coupling,
            "update_coupling": self._update_coupling,
            "read_couplings": self._read_couplings,
            "read_artifact": self._read_artifact,
            "list_references": self._list_references,
            "read_reference": self._read_reference,
            "export_part": self._export_part,
            "query_snapshot": self._query_snapshot,
            "run_dfm": self._run_dfm,
            "generate_drawing": self._generate_drawing,
            "generate_doc": self._generate_doc,
        }.get(decl.name)
        if cad_handler is None:  # pragma: no cover - every declared tool is routed
            raise DispatchError(
                "not_implemented",
                f"tool {decl.name!r} is not wired",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        return cad_handler(principal, cad, arguments, invocation)

    # -- geometry ----------------------------------------------------------

    def _build_part(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # VALIDATION.md §3: the clarification gate runs BEFORE any geometry, over
        # the ledger's own tags, and refuses with a discriminated result. It is a
        # dispatch-layer rule precisely so no prompt, profile or model choice can
        # route around it — every build path (sidecar, MCP, REST) comes through
        # here. No idempotency key is claimed: the refusal did no work, so the
        # same invocation id may build for real once the assumption is resolved.
        gate = clarification_gate(cad.ledger_state())
        if gate.blocked:
            return gate.to_result()
        raw_params = arguments.get("params")
        params = cast("dict[str, Any]", raw_params) if isinstance(raw_params, dict) else None
        try:
            return cad.build_part(str(arguments["name"]), params, op_id=inv.op_id)
        except AddressingError:
            raise
        except HephaestusError as exc:
            raise DispatchError("build_failed", exc.message) from exc

    def _inspect_part(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        raw_views = arguments.get("views")
        views = (
            [str(v) for v in cast("list[Any]", raw_views)] if isinstance(raw_views, list) else None
        )
        try:
            return cad.inspect_part(
                str(arguments["name"]),
                views=views,
                channel=str(arguments.get("channel", "rgb")),
                mask_mode=str(arguments.get("mask_mode", "solid")),
                section_plane=_opt_str(arguments, "section_plane"),
                explode=float(arguments.get("explode", 0.0)),
                last_good=bool(arguments.get("last_good", False)),
                artifact_ref=_opt_str(arguments, "artifact_ref"),
                focus=_opt_str(arguments, "focus"),
            )
        except AddressingError:
            raise
        except ValidationError as exc:
            raise DispatchError("invalid_params", exc.message) from exc
        except HephaestusError as exc:
            raise DispatchError("build_failed", exc.message) from exc

    # -- parameters --------------------------------------------------------

    def _set_params(
        self, principal: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        scope = str(arguments.get("scope", "part"))
        name = _opt_str(arguments, "name")
        if scope == "project":
            if name is not None:
                raise DispatchError(
                    "invalid_params", "set_params scope='project' must not name a part"
                )
        else:
            name = name or principal.part
            if name is None:
                raise DispatchError("invalid_params", "set_params scope='part' requires a name")
        raw_values = arguments.get("values")
        if not isinstance(raw_values, dict):
            raise DispatchError("invalid_params", "set_params requires a values object")
        values = cast("dict[str, Any]", raw_values)
        try:
            return cad.set_params(
                scope,
                name,
                values,
                expected_state_hash=str(arguments["expected_state_hash"]),
                op_id=inv.op_id,
            )
        except AddressingError:
            raise
        except HephaestusError as exc:
            raise DispatchError("invalid_params", exc.message) from exc

    # -- globals -----------------------------------------------------------

    def _edit_globals(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # The whole discriminated contract (opkey-first CAS, sandbox validation,
        # invalid_overrides vs stale_hash, projection advance) lives in CadOps so
        # the ordering that makes a lost-response retry replay stays in one place.
        return cad.edit_globals(
            expected_hash=str(arguments["expected_hash"]),
            old_str=str(arguments["old_str"]),
            new_str=str(arguments["new_str"]),
            op_id=inv.op_id,
        )

    # -- project checks ----------------------------------------------------

    def _list_project_checks(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        limit = max(1, min(100, int(arguments.get("limit", 100))))
        cursor = _opt_str(arguments, "cursor")
        state = cad.check_state()
        if cursor is None:
            if state.status == "invalid":
                payload: dict[str, Any] = {
                    "status": "invalid_check_generation",
                    "check_set_generation": str(state.generation),
                    "check_set_ref": state.bundle_ref,
                }
                diagnostics = cad.check_diagnostics_ref(state)
                if diagnostics is not None:
                    payload["diagnostics_ref"] = diagnostics
                return payload
            # The first page FREEZES the immutable lexical index; later pages read
            # exactly that content-addressed manifest, so concurrent mutation
            # cannot alter them.
            bundle_ref = state.bundle_ref
            generation = state.generation
            position = 0
        else:
            bundle_ref, generation, position = _decode_cursor(cursor)
        items = cad.check_bundle_items(bundle_ref)
        page = items[position : position + limit]
        result: dict[str, Any] = {
            "status": "ok",
            "items": page,
            "total": len(items),
            "check_set_generation": str(generation),
            "check_set_ref": bundle_ref,
        }
        if position + limit < len(items):
            result["next_cursor"] = _encode_cursor(bundle_ref, generation, position + limit)
        return result

    def _create_project_check(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        name = str(arguments["name"])
        description = str(arguments.get("description", "")).replace("\n", " ").strip()
        if name in cad.check_names():
            raise DispatchError("already_exists", f"project check {name!r} already exists")
        cad.write_check(name, check_template(description), op_id=inv.op_id)
        script, content_hash, snapshot_ref = cad.read_check(name)
        return {
            "path": str(cad.layout.checks_dir / f"{name}.py"),
            "initial_script": script,
            "content_hash": content_hash,
            "snapshot_ref": snapshot_ref,
        }

    def _read_project_check(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        script, content_hash, snapshot_ref = cad.read_check(str(arguments["name"]))
        return {
            "script": script,
            "numbered_script": _numbered(script),
            "content_hash": content_hash,
            "snapshot_ref": snapshot_ref,
            "truncated": False,
            "oversized_line": False,
        }

    def _edit_project_check(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        name = str(arguments["name"])
        expected_hash = str(arguments["expected_hash"])
        old_str = str(arguments["old_str"])
        new_str = str(arguments["new_str"])
        script, content_hash, snapshot_ref = cad.read_check(name)
        if content_hash != expected_hash:
            return {
                "status": "conflict",
                "kind": "stale_hash",
                "current_hash": content_hash,
                "current_script": script,
                "current_truncated": False,
                "current_oversized_line": False,
                "current_snapshot_ref": snapshot_ref,
                "base_snapshot_ref": f"artifact:part-snapshot:{expected_hash}",
                "attempted_snapshot_ref": snapshot_ref,
            }
        occurrences = script.count(old_str)
        if occurrences != 1:
            return {
                "status": "validation_error",
                "kind": "contract",
                "diagnostics": f"old_str occurs {occurrences} times in {name!r}; must be unique",
            }
        candidate = script.replace(old_str, new_str, 1)
        kind = cad.validate_check_source(name, candidate)
        if kind is not None:
            return {
                "status": "validation_error",
                "kind": kind,
                "diagnostics": f"checks/{name}.py failed {kind} validation in the check sandbox",
            }
        cad.write_check(name, candidate, op_id=inv.op_id)
        _script, new_hash, new_ref = cad.read_check(name)
        return {
            "status": "applied",
            "diff": _unified_diff(old_str, new_str),
            "content_hash": new_hash,
            "snapshot_ref": new_ref,
            "journal_ref": new_ref,
        }

    # -- measurement / checks ---------------------------------------------

    def _measure(
        self, principal: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        part = _opt_str(arguments, "part") or principal.part
        return cad.measure(
            str(arguments["kind"]),
            str(arguments["a"]),
            _opt_str(arguments, "b"),
            part=part,
            artifact_ref=_opt_str(arguments, "artifact_ref"),
            project_snapshot_ref=_opt_str(arguments, "project_snapshot_ref"),
        )

    def _compare_solids(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.compare_solids(
            str(arguments["part"]),
            str(arguments["target"]),
            align=str(arguments.get("align", "as_posed")),
        )

    def _compare_to_scan(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("declared_transform")
        transform = [float(cast("float", v)) for v in cast("list[Any]", raw)] if raw else None
        return cad.compare_to_scan(
            str(arguments["part"]),
            str(arguments["scan"]),
            units=str(arguments["units"]),
            align=str(arguments.get("align", "as_posed")),
            declared_transform=transform,
        )

    def _run_checks(
        self, principal: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        scope = str(arguments.get("scope", "part"))
        if scope == "project":
            return cad.run_project_checks(_opt_str(arguments, "project_snapshot_ref"))
        name = _opt_str(arguments, "name") or principal.part
        if name is None:
            raise DispatchError("invalid_params", "run_checks scope='part' requires a name")
        try:
            return cad.run_part_checks(name)
        except AddressingError:
            raise
        except HephaestusError as exc:
            raise DispatchError("build_failed", exc.message) from exc

    # -- requirement ledger (VALIDATION.md §2) -----------------------------

    def _record_requirements(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("entries")
        if not isinstance(raw, list):
            raise DispatchError("invalid_params", "record_requirements requires an entries array")
        entries: list[Mapping[str, Any]] = []
        for item in cast("list[Any]", raw):
            if not isinstance(item, dict):
                raise DispatchError("invalid_params", "each requirement entry must be an object")
            entries.append(cast("Mapping[str, Any]", item))
        return cad.record_requirements(entries, op_id=inv.op_id).to_json()

    def _read_requirements(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.ledger_state().to_json()

    def _update_requirement(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # No `provenance` argument: this is the model's own hand on the ledger, so
        # it takes the default and `asked`/`resolution` are refused here with
        # `invalid_requirement` (VALIDATION.md §3 — the clarification record is the
        # runtime's to write). The sidecar's schema already rejects them a layer
        # earlier; py.tool_dispatch is also the MCP/REST path, which does not.
        fields = {key: value for key, value in arguments.items() if key != "id"}
        return cad.update_requirement(
            str(arguments["id"]), cast("Mapping[str, Any]", fields), op_id=inv.op_id
        ).to_json()

    # -- constraints (ASSEMBLY.md §3) --------------------------------------

    def _declare_constraint(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # The whole entry is the argument object: ASSEMBLY.md §1 puts the declared
        # numbers at the entry's top level, so the wire shape and the stored shape
        # are one shape and nothing has to be re-assembled here.
        return cad.declare_constraint(cast("Mapping[str, Any]", arguments), op_id=inv.op_id)

    def _update_constraint(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("patch")
        if not isinstance(raw, dict):
            raise DispatchError("invalid_params", "update_constraint requires a patch object")
        reason = arguments.get("reason")
        if not isinstance(reason, str):
            raise DispatchError("invalid_params", "update_constraint requires a reason")
        return cad.update_constraint(
            str(arguments["id"]), cast("Mapping[str, Any]", raw), reason, op_id=inv.op_id
        )

    def _read_constraints(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.read_constraints()

    def _check_assembly(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("ids")
        ids: list[str] | None = None
        if isinstance(raw, list):
            ids = [str(item) for item in cast("list[Any]", raw)]
        elif raw is not None:
            raise DispatchError("invalid_params", "check_assembly ids must be an array")
        return cad.check_assembly(ids)

    # -- kinematics (KINEMATICS.md §6, Stage 9A) ---------------------------

    def _declare_joint(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # The whole entry is the argument object: KINEMATICS.md §1 writes a
        # joint entry as one JSON shape, so the wire shape and the stored shape
        # are one shape (the declare_constraint rule).
        return cad.declare_joint(cast("Mapping[str, Any]", arguments), op_id=inv.op_id)

    def _update_joint(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("patch")
        if not isinstance(raw, dict):
            raise DispatchError("invalid_params", "update_joint requires a patch object")
        reason = arguments.get("reason")
        if not isinstance(reason, str):
            raise DispatchError("invalid_params", "update_joint requires a reason")
        return cad.update_joint(
            str(arguments["id"]), cast("Mapping[str, Any]", raw), reason, op_id=inv.op_id
        )

    def _read_joints(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.read_joints()

    def _declare_pose(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        return cad.declare_pose(cast("Mapping[str, Any]", arguments), op_id=inv.op_id)

    def _update_pose(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("patch")
        if not isinstance(raw, dict):
            raise DispatchError("invalid_params", "update_pose requires a patch object")
        reason = arguments.get("reason")
        if not isinstance(reason, str):
            raise DispatchError("invalid_params", "update_pose requires a reason")
        return cad.update_pose(
            str(arguments["id"]), cast("Mapping[str, Any]", raw), reason, op_id=inv.op_id
        )

    def _read_poses(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.read_poses()

    def _declare_motion_check(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # The whole entry is the argument object: KINEMATICS.md §4 writes a
        # motion check as one JSON shape, so the wire shape and the stored
        # shape are one shape (the declare_joint rule).
        return cad.declare_motion_check(cast("Mapping[str, Any]", arguments), op_id=inv.op_id)

    def _update_motion_check(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("patch")
        if not isinstance(raw, dict):
            raise DispatchError("invalid_params", "update_motion_check requires a patch object")
        reason = arguments.get("reason")
        if not isinstance(reason, str):
            raise DispatchError("invalid_params", "update_motion_check requires a reason")
        return cad.update_motion_check(
            str(arguments["id"]), cast("Mapping[str, Any]", raw), reason, op_id=inv.op_id
        )

    def _read_motion_checks(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.read_motion_checks()

    def _declare_coupling(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        # The whole entry is the argument object: KINEMATICS.md §5 writes a
        # coupling as one JSON shape, so the wire shape and the stored shape
        # are one shape (the declare_joint rule).
        return cad.declare_coupling(cast("Mapping[str, Any]", arguments), op_id=inv.op_id)

    def _update_coupling(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        raw = arguments.get("patch")
        if not isinstance(raw, dict):
            raise DispatchError("invalid_params", "update_coupling requires a patch object")
        reason = arguments.get("reason")
        if not isinstance(reason, str):
            raise DispatchError("invalid_params", "update_coupling requires a reason")
        return cad.update_coupling(
            str(arguments["id"]), cast("Mapping[str, Any]", raw), reason, op_id=inv.op_id
        )

    def _read_couplings(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        return cad.read_couplings()

    def _check_motion(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        # KINEMATICS.md §6 `check_motion(ids?)`, completed by Stage 9B: `ids`
        # narrows which motion CHECKS run (the check_assembly shape); the
        # joint and pose sections are always evaluated in full.
        raw = arguments.get("ids")
        ids: list[str] | None = None
        if isinstance(raw, list):
            ids = [str(item) for item in cast("list[Any]", raw)]
        elif raw is not None:
            raise DispatchError("invalid_params", "check_motion ids must be an array")
        return cad.check_motion(ids)

    # -- artifacts ---------------------------------------------------------

    def _read_artifact(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        # Clamp defensively to the canonical schema's bounds; the sidecar proxy
        # already validates them, but py.tool_dispatch is also the MCP/REST path.
        offset = max(0, int(arguments.get("offset_bytes", 0)))
        page = int(arguments.get("max_bytes", READ_ARTIFACT_PAGE_MAX))
        page = max(1, min(READ_ARTIFACT_PAGE_MAX, page))
        return cad.read_artifact(str(arguments["ref"]), offset, page)

    # -- references (INGEST.md §2) -----------------------------------------

    def _list_references(
        self, _p: Principal, cad: CadOps, _arguments: dict[str, Any], _inv: Invocation
    ) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", cad.list_references())

    def _read_reference(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        raw_page = arguments.get("page")
        page = (
            int(raw_page) if isinstance(raw_page, int) and not isinstance(raw_page, bool) else None
        )
        return cad.read_reference(
            str(arguments["name"]),
            page=page,
            offset_bytes=max(0, int(arguments.get("offset_bytes", 0))),
        )

    # -- export ------------------------------------------------------------

    def _export_part(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        return cad.export_part(
            str(arguments["name"]),
            str(arguments["format"]),
            artifact_ref=_opt_str(arguments, "artifact_ref"),
            target=_opt_str(arguments, "target"),
            layout=str(arguments.get("layout", "as_built")),
            blank=_opt_mapping(arguments, "blank"),
            kerf_mm=_opt_float(arguments, "kerf_mm"),
            op_id=inv.op_id,
        )

    # -- documents ---------------------------------------------------------

    def _generate_drawing(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        """Mission Stage 6: a dimensioned/assembly/exploded sheet as PDF + SVG.

        Both files land under ``.heph/exports/`` through the same §7 export
        contract ``export_part`` uses, so the drawing is a pinned, provenance-
        hashed artifact and a lost-response retry replays it rather than
        producing a second sheet.
        """
        return cad.generate_drawing(
            str(arguments["name"]),
            str(arguments["kind"]),
            sheet=str(arguments.get("sheet", "A4")),
            artifact_ref=_opt_str(arguments, "artifact_ref"),
            target=_opt_str(arguments, "target"),
            op_id=inv.op_id,
        )

    def _generate_doc(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        """Mission Stage 6: BOM / assembly instructions / spec as markdown + JSON."""
        return cad.generate_doc(
            str(arguments["name"]),
            str(arguments["kind"]),
            artifact_ref=_opt_str(arguments, "artifact_ref"),
            target=_opt_str(arguments, "target"),
            op_id=inv.op_id,
        )

    # -- dfm ---------------------------------------------------------------

    def _run_dfm(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], _inv: Invocation
    ) -> dict[str, Any]:
        """Mission Stage 6: the process rule pack over a resolved artifact.

        Nothing is decided here — artifact/process/material resolution and the
        sandbox boundary all live in :mod:`~.cad_ops._dfm`, so the MCP and REST
        paths get the identical contract. A refusal keeps its typed reason
        (``capability_not_available`` rides through to the proxy as a
        discriminated tool result).
        """
        return cad.run_dfm(
            str(arguments["name"]),
            process=_opt_str(arguments, "process"),
            artifact_ref=_opt_str(arguments, "artifact_ref"),
            project_snapshot_ref=_opt_str(arguments, "project_snapshot_ref"),
        )

    # -- query_snapshot ----------------------------------------------------

    def _query_snapshot(
        self, _p: Principal, cad: CadOps, arguments: dict[str, Any], inv: Invocation
    ) -> dict[str, Any]:
        caller = self._snapshot_caller
        if caller is None:
            return {
                "status": "capability_error",
                "code": "capability_not_available",
                "message": "no multimodal snapshot provider is configured for this runtime",
            }
        name = str(arguments["name"])
        question = str(arguments["question"])
        raw_views = arguments.get("views")
        views = (
            tuple(str(v) for v in cast("list[Any]", raw_views))
            if isinstance(raw_views, list) and raw_views
            else ("iso",)
        )
        preparer = _CadBundlePreparer(cad, name, views, _opt_str(arguments, "artifact_ref"))
        service = QuerySnapshotService(preparer, caller, self._ledger)
        child_run_id = f"qs-{inv.op_id}"
        try:
            outcome = asyncio.run(
                service.run(inv.session_id, child_run_id, question, image_refs=())
            )
        except QuerySnapshotError as exc:
            raise DispatchError(exc.code, exc.message) from exc
        return {
            "status": "ok",
            "answer": outcome.text,
            "render_artifacts": list(outcome.refs),
            "usage": {
                "output_tokens": outcome.usage.output_tokens,
                "input_tokens": outcome.usage.input_tokens,
                "turns": outcome.usage.turns,
                "cost": outcome.usage.cost,
            },
        }

    # -- registries --------------------------------------------------------

    def _registry_op(self, decl: ToolDecl, arguments: dict[str, Any]) -> Any:
        """Route the five registry tools over hash-pinned registry content.

        Contextual results (``load_skill``) already arrive wrapped in the
        provenance delimiters :func:`~hephaestus.core.registry.wrap_reference`
        writes — this layer never unwraps them, and never hands registry text to
        a caller outside that wrapper. Executable results
        (``instance_store_part``) have already been built under the secure
        sandbox by the time they get here; without a sandbox-capable
        :class:`RegistryOps` the core refuses with ``capability_not_available``
        rather than running a generator unsandboxed.
        """
        registry = self._registry
        if registry is None:
            raise DispatchError(
                "not_implemented",
                f"tool {decl.name!r} needs the registry stack, which is not wired in this runtime",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        if decl.name == "list_skills":
            return registry.list_skills()
        if decl.name == "load_skill":
            return registry.load_skill(
                str(arguments["name"]),
                int(arguments.get("offset_line", 1)),
                int(arguments.get("limit_lines", TEXT_MAX_LINES)),
            )
        if decl.name == "search_materials":
            return registry.search_materials(str(arguments["query"]))
        if decl.name == "search_parts_store":
            return registry.search_parts_store(
                str(arguments["query"]), int(arguments.get("max_results", 5))
            )
        raw_params = arguments.get("params")
        params = cast("dict[str, Any]", raw_params) if isinstance(raw_params, dict) else {}
        raw_pos = arguments.get("pos")
        pos = cast("dict[str, Any]", raw_pos) if isinstance(raw_pos, dict) else None
        raw_instance = arguments.get("instance")
        instance = raw_instance if isinstance(raw_instance, str) else None
        return registry.instance_store_part(str(arguments["id"]), params, pos, instance)

    # -- delegation --------------------------------------------------------

    def _delegation_op(
        self, decl: ToolDecl, arguments: dict[str, Any], inv: Invocation, run_id: str
    ) -> dict[str, Any]:
        service = self._delegation
        if service is None:
            raise DispatchError(
                "not_implemented",
                f"tool {decl.name!r} needs the delegation service, which is not wired",
                code=ErrorCode.METHOD_NOT_FOUND,
            )
        try:
            if decl.name == "delegate_part_agent":
                return self._delegate(service, decl, arguments, inv, run_id)
            ref = str(arguments["delegation_ref"])
            if decl.name == "cancel_delegation":
                return _delegation_result(service.cancel(ref))
            return _delegation_result(service.check_deadline(ref))
        except DelegationError as exc:
            raise DispatchError(exc.code, exc.message) from exc

    def _delegate(
        self,
        service: DelegationService,
        decl: ToolDecl,
        arguments: dict[str, Any],
        inv: Invocation,
        run_id: str,
    ) -> dict[str, Any]:
        part = str(arguments["part"])
        prompt = str(arguments["prompt"])
        try:
            enforce_max_utf8_bytes(prompt, decl.max_utf8_fields["prompt"], field="prompt")
        except LimitError as exc:
            if exc.code != "prompt_too_large":
                raise DispatchError(exc.code, exc.message) from exc
            return {
                "status": "rejected",
                "reason": "prompt_too_large",
                "part_session_id": _part_session_id(part),
            }
        delivery = Delivery(str(arguments.get("delivery", "prompt")))
        deadline = int(arguments.get("deadline_seconds", DEADLINE_DEFAULT_S))
        outcome = service.delegate(
            run_id,
            part,
            prompt,
            delivery=delivery,
            deadline_seconds=deadline,
            invocation=inv.op_id,
            # INTERFACE.md §2.8: the two ids the durable session edge is about.
            # This is the layer that holds both — the WAL is keyed by runs, and
            # the conventional part session id is minted here.
            parent_session_id=inv.session_id,
            child_session_id=_part_session_id(part),
        )
        if isinstance(outcome, Rejected):
            return {
                "status": "rejected",
                "reason": str(outcome.reason),
                "part_session_id": _part_session_id(part),
            }
        row = outcome
        # INTERFACE.md §7A.4/§19.23 + ``app.py``'s delegation rule: the child part
        # agent is working the ORIGINAL request, so its build is critiqued against
        # that and not against this hand-off sentence. That used to fall out of one
        # shared ``_request_text``; with the text bound per run it has to be said,
        # and the child's own run id is the only key its tool calls will carry.
        inherit_run_request_text(run_id, row.child_run_id)
        if delivery is Delivery.FOLLOW_UP:
            # The slot is reserved at ADMITTED and held through terminal ack.
            return _delegation_result(row)
        runner = self._delegation_runner
        if row.phase is not DelegationPhase.TERMINAL:
            if runner is None:
                # No coordinator can execute the child: synthesize exactly ONE
                # durable terminal instead of inventing a completion.
                row = service.ingest_terminal(
                    row.delegation_ref,
                    TerminalState.INTERRUPTED,
                    error="no delegation runner configured",
                )
            else:
                runner.run(service, row)
                row = service.get(row.delegation_ref)
        if row.phase is DelegationPhase.TERMINAL:
            row = service.resume_parent(row.delegation_ref)
        return _delegation_result(row)

    # -- wired file-CRUD handlers ------------------------------------------

    def _read_part(self, arguments: dict[str, Any], _inv: Invocation) -> dict[str, Any]:
        name = str(arguments["name"])
        try:
            snap = self._store.read_part(name)
        except AddressingError as exc:
            raise DispatchError("invalid_part", str(exc)) from exc
        result: dict[str, Any] = {
            "script": snap.content,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "line_count": snap.content.count("\n") + (0 if snap.content.endswith("\n") else 1),
            "truncated": False,
        }
        if self._cad is not None:
            result["part_param_state_hash"] = self._cad.param_state_hash("part", name)
            result["project_param_state_hash"] = self._cad.param_state_hash("project", None)
        return result

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
        result: dict[str, Any] = {
            "path": str(snap.path),
            "initial_script": snap.content,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "replayed": outcome.replayed,
        }
        if self._cad is not None:
            result["part_param_state_hash"] = self._cad.param_state_hash("part", name)
            result["project_param_state_hash"] = self._cad.param_state_hash("project", None)
        return result

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
        result: dict[str, Any] = {
            "script": snap.content,
            "numbered_script": _numbered(snap.content),
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "truncated": False,
            "oversized_line": False,
        }
        if self._cad is not None:
            result["project_param_state_hash"] = self._cad.param_state_hash("project", None)
        return result


# --------------------------------------------------------------------------
# small helpers


def _opt_str(arguments: Mapping[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    return None if value is None else str(value)


def _opt_float(arguments: Mapping[str, Any], key: str) -> float | None:
    """A schema-validated optional number argument (``export_part.kerf_mm``)."""
    value = arguments.get(key)
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float):  # pragma: no cover - schema-constrained
        raise DispatchError("invalid_params", f"{key} must be a number")
    return float(value)


def _opt_mapping(arguments: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    """A schema-validated optional object argument (``export_part.blank``)."""
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):  # pragma: no cover - schema-constrained
        raise DispatchError("invalid_params", f"{key} must be an object")
    return cast("Mapping[str, Any]", value)


def _numbered(script: str) -> str:
    lines = script.splitlines()
    width = len(str(max(len(lines), 1)))
    return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, start=1))


def _unified_diff(old_str: str, new_str: str) -> str:
    return f"-{old_str.rstrip(chr(10))}\n+{new_str.rstrip(chr(10))}"


def _encode_cursor(bundle_ref: str, generation: int, position: int) -> str:
    """Opaque cursor binding the frozen index ref, its generation and position."""
    payload = json.dumps(
        {"ref": bundle_ref, "gen": generation, "pos": position},
        sort_keys=True,
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int, int]:
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        decoded = cast("dict[str, Any]", json.loads(raw.decode("utf-8")))
        return str(decoded["ref"]), int(decoded["gen"]), int(decoded["pos"])
    except Exception as exc:
        raise DispatchError("invalid_cursor", f"malformed cursor {cursor!r}") from exc


def _part_session_id(part: str) -> str:
    """The conventional per-part session id (the session service owns the real map)."""
    return f"part:{part}"


def _delegation_result(row: DelegationRow) -> dict[str, Any]:
    """Project a delegation row onto the tool's discriminated result variants."""
    result: dict[str, Any] = {
        "status": row.status(),
        "part_session_id": _part_session_id(row.part),
        "child_run_id": row.child_run_id,
        "delegation_ref": row.delegation_ref,
    }
    if row.result_artifact_ref is not None:
        result["result_artifact_ref"] = row.result_artifact_ref
    if row.error is not None:
        result["error"] = {"message": row.error}
    return result
