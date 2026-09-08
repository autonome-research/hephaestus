"""``build_dispatcher``: the one place all three shipped runtimes construct the
tool dispatcher's capability set (docs/audit-2026-09-04-broken.md, B-2).

Today no shipped call site ever builds a ``ToolDispatcher`` with ``registry=``
or ``delegation=`` — only ``tests/stage2/_g2.py``'s ``BridgeRuntime`` subclass
and :mod:`hephaestus.testing.workflow_harness` do (the audit's root-cause
finding). These tests pin what ``hephaestus.agent_bridge.wiring.build_dispatcher``
must do once it exists, so a shipped runtime can be trusted to answer the five
registry tools and construct a real delegation service without a test-only
subclass:

* it resolves the project's real registries through ``RegistrySet.open`` — the
  same call ``cad_ops/_dfm.py:124`` already makes in production — and the five
  registry tools answer with real, non-``not_implemented`` content;
* it builds a ``DelegationService`` over the project's own admission/db, with a
  *real* gate: delegating to a part the project does not have is rejected
  before a child run is ever admitted, unlike the default ``_AllowAllGate``
  (``server/src/hephaestus/agent_bridge/delegation.py``), which the audit's
  B-2 dependency note names as the reason a wired-but-ungated delegation would
  report a nonexistent part's build as completed;
* a delegation to a part that DOES exist, with no ``delegation_runner``
  wired (the B-2 dependency on the reader-thread fix — see the ledger's
  "Dependencies outside this document"), synthesizes exactly one durable
  ``interrupted`` terminal — never a schema failure and never a silently
  invented completion;
* a registry pin that no longer verifies degrades the dispatcher to
  ``registry=None`` (the five tools keep their typed ``not_implemented``)
  rather than raising out of construction and taking the runtime down.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import DispatchError, ToolDispatcher
from hephaestus.agent_bridge.session_edges import SessionEdgeStore
from hephaestus.agent_bridge.wiring import build_dispatcher
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.registry import RegistryPin, merkle_digest, write_pins
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.tools_fixture import ORCH, make_wired_project, scaffold

REPO = Path(__file__).resolve().parents[2]

#: A tiny publishable skills registry, independent of the repo's bundled
#: ``registries/`` tree, so tampering it to prove the integrity-degrade path
#: never touches real shipped content.
_SKILLS_MANIFEST = """\
[registry]
name = "demo-skills"
kind = "skills"
version = "1.0.0"
license = "CC-BY-4.0"
description = "A one-page demo registry for the wiring tests."

[[skills]]
name = "alpha"
file = "alpha.md"
summary = "The only page."
"""


def _result_schema(tool: str) -> dict[str, Any]:
    document = cast(
        "dict[str, Any]",
        json.loads((REPO / "schemas" / "tools" / f"{tool}.schema.json").read_text("utf-8")),
    )
    return cast("dict[str, Any]", document["result"])


def _wired(tmp_path: Path, *, seed_ledger: bool = True) -> tuple[ToolDispatcher, Any]:
    """A scaffolded project's dispatcher, built the way every shipped runtime
    must (``build_dispatcher``), with no test-only injections."""
    root = tmp_path / "proj"
    scaffold(root)
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store, backend=UnsafeLocalBackend())
    if seed_ledger:
        seed_minimal_ledger(cad)
    dispatcher = build_dispatcher(
        layout,
        store,
        ProjectStore(layout, store),
        cad,
        backend=None,
        edges=SessionEdgeStore(store.db),
    )
    return dispatcher, store


def _call(
    dispatcher: ToolDispatcher, tool: str, arguments: dict[str, Any], *, run_id: str = "run-1"
) -> Any:
    return dispatcher.dispatch(
        ORCH,
        {
            "session_id": ORCH.session_id,
            "run_id": run_id,
            "tool": tool,
            "arguments": arguments,
            "invocation": {
                "session_id": ORCH.session_id,
                "entry_id": f"e-{tool}-{run_id}",
                "ordinal": 1,
                "provider_call_id": "c0",
            },
        },
    )


# -- the five registry tools, over real bundled-registry content -----------


def test_build_dispatcher_answers_the_registry_tools_with_real_content(
    tmp_path: Path,
) -> None:
    dispatcher, store = _wired(tmp_path)
    try:
        skills = _call(dispatcher, "list_skills", {})
        assert skills, "list_skills must be non-empty over the bundled registries"
        names = {entry["name"] for entry in skills}

        page = _call(dispatcher, "load_skill", {"name": sorted(names)[0]})
        assert page["content"].startswith("<<<HEPHAESTUS-REGISTRY-REFERENCE"), (
            "load_skill's text must arrive inside the provenance delimiters "
            "(RegistryOps.load_skill / wrap_reference), never bare"
        )

        materials = _call(dispatcher, "search_materials", {"query": "PLA"})
        assert materials, "search_materials must query the real materials registry"

        parts = _call(dispatcher, "search_parts_store", {"query": "bearing"})
        assert parts, "search_parts_store must query the real parts registry"
    finally:
        store.close()


def test_build_dispatcher_constructs_a_delegation_service(tmp_path: Path) -> None:
    dispatcher, store = _wired(tmp_path)
    try:
        # get_delegation_status on an unknown ref must reach a real
        # DelegationService (a typed "not_found"), not the "not_implemented"
        # refusal an unwired dispatcher gives.
        with pytest.raises(DispatchError) as ei:
            _call(dispatcher, "get_delegation_status", {"delegation_ref": "dg-nope"})
        assert ei.value.reason == "not_found"
    finally:
        store.close()


def test_delegate_to_an_existing_part_with_no_runner_synthesizes_one_interrupted_terminal(
    tmp_path: Path,
) -> None:
    """The B-2 dependency note: with ``delegation=`` wired and
    ``delegation_runner=`` absent, a ``delivery="prompt"`` delegation must not
    hang and must not invent a completion — exactly ONE durable
    ``interrupted`` terminal, schema-valid."""
    dispatcher, store = _wired(tmp_path)
    try:
        store.admission.admit("run-1")
        result = _call(
            dispatcher,
            "delegate_part_agent",
            {"part": "widget", "prompt": "make it wider", "delivery": "prompt"},
        )
        assert result["status"] == "interrupted", result
        jsonschema.validate(result, _result_schema("delegate_part_agent"))
    finally:
        store.close()


def test_delegate_to_a_nonexistent_part_is_rejected_before_admission(tmp_path: Path) -> None:
    """The real gate ``build_dispatcher`` constructs must reject a delegation to
    a part the project does not have, unlike the default ``_AllowAllGate`` —
    which admits it and (with no runner) reports an ``interrupted`` terminal
    for work that was never real (audit B-2, dependency note 3)."""
    dispatcher, store = _wired(tmp_path)
    try:
        store.admission.admit("run-2")
        result = _call(
            dispatcher,
            "delegate_part_agent",
            {"part": "does_not_exist", "prompt": "make it wider", "delivery": "prompt"},
            run_id="run-2",
        )
        assert result["status"] == "rejected", result
        jsonschema.validate(result, _result_schema("delegate_part_agent"))
    finally:
        store.close()


# -- a pinned registry that no longer verifies ------------------------------


def test_build_dispatcher_degrades_to_no_registry_on_a_tampered_pin(tmp_path: Path) -> None:
    """``RegistrySet.open`` raises ``RegistryIntegrityError`` for a pinned tree
    that no longer hashes to its pin. ``build_dispatcher`` must catch that and
    keep serving — the five registry tools stay at their typed
    ``not_implemented`` instead of the runtime failing to start."""
    root = tmp_path / "proj"
    scaffold(root)

    registry_root = tmp_path / "demo-skills"
    registry_root.mkdir()
    (registry_root / "registry.toml").write_text(_SKILLS_MANIFEST, encoding="utf-8")
    (registry_root / "alpha.md").write_text("# Alpha\n\nFirst page.\n", encoding="utf-8")
    digest = merkle_digest(registry_root)
    write_pins(root, {"skills": RegistryPin(name="skills", path=str(registry_root), digest=digest)})
    # Tamper AFTER pinning: the bytes on disk no longer hash to the pin.
    (registry_root / "alpha.md").write_text("# Alpha\n\nTampered.\n", encoding="utf-8")

    layout = load_project(root)
    store = open_store(layout)
    try:
        cad = CadOps(layout, store, backend=UnsafeLocalBackend())
        seed_minimal_ledger(cad)
        dispatcher = build_dispatcher(
            layout,
            store,
            ProjectStore(layout, store),
            cad,
            backend=None,
            edges=SessionEdgeStore(store.db),
        )
        with pytest.raises(DispatchError) as ei:
            _call(dispatcher, "list_skills", {})
        assert ei.value.reason == "not_implemented"
    finally:
        store.close()


# -- the deliberate asymmetry: a runtime with no sidecar --------------------


def test_a_sidecarless_runtime_keeps_the_registry_and_refuses_delegation(tmp_path: Path) -> None:
    """``heph mcp``'s shape, pinned so it stays a decision rather than a copy.

    MCP builds through the same :func:`build_dispatcher` — it was the third
    runtime with the five registry tools unwired, and it was broken by copying
    the bare construction — but passes ``delegation=False``. There is no sidecar
    in that process, so nothing could ever execute a child part agent; admitting
    a delegation there would reserve a slot and report a terminal for work that
    can never run. The registry family, which needs only the project and its
    opstore, must keep working.

    ``query_snapshot`` is the same asymmetry from the other side: MCP never
    calls :meth:`~hephaestus.agent_bridge.dispatch.ToolDispatcher.bind_runtime`,
    so the tool answers its declared ``capability_error`` rather than pretending
    to a vision child.
    """
    project = make_wired_project(tmp_path / "mcp-proj", delegation=False)
    try:
        assert project.call("list_skills", {}), "registries must work without a sidecar"

        for tool, arguments in (
            ("delegate_part_agent", {"part": "widget", "prompt": "widen it"}),
            ("get_delegation_status", {"delegation_ref": "dg-x"}),
            ("cancel_delegation", {"delegation_ref": "dg-x"}),
        ):
            with pytest.raises(DispatchError) as ei:
                project.call(tool, arguments)
            assert ei.value.reason == "not_implemented", tool
            assert tool in str(ei.value), "the refusal names the tool it refuses"

        snapshot = project.call("query_snapshot", {"name": "widget", "question": "how tall?"})
        assert snapshot["status"] == "capability_error"
        assert snapshot["code"] == "capability_not_available"
        jsonschema.validate(snapshot, _result_schema("query_snapshot"))
    finally:
        project.close()


def test_the_shipped_construction_never_runs_a_generator_unsandboxed(tmp_path: Path) -> None:
    """``instance_store_part`` with no secure backend refuses; it does not degrade.

    ``build_dispatcher`` is the single place a backend reaches ``RegistryOps``,
    and it drops an unsafe one — ``core/executor/sandbox/probe.py``'s
    ``refuse_unsafe`` states that registry content may never run unsandboxed. So
    a runtime that has only the unsafe local backend (``heph agent`` today)
    refuses this tool rather than executing a registry generator without a
    sandbox.
    """
    project = make_wired_project(tmp_path / "nosandbox")
    try:
        with pytest.raises(DispatchError) as ei:
            project.call("instance_store_part", {"id": "screw_socket_head_m3", "params": {}})
        assert ei.value.reason == "capability_not_available"
    finally:
        project.close()


# -- ProjectDelegationGate (J-agent-wiring-6) -------------------------------
#
# ``PartExistsGate`` closed the ``invalid_part`` clause (B-2); it left three
# more of the delegation protocol's declared reasons unreachable —
# ``part_busy``, ``session_busy`` and self-delegation's ``scope_denied`` — and
# left a permissive default (``_AllowAllGate``) reachable from any code that
# constructs a ``DelegationService`` without wiring a gate at all. These pin
# the richer gate directly, and the still-open mandatory-gate half of the fix.


class _FakeLiveRuns:
    """A minimal ``wiring.LiveRunView`` double: no store, no sidecar."""

    def __init__(self, *, owners: dict[str, str], live: frozenset[str]) -> None:
        self._owners = owners
        self._live = live

    def session_for_run(self, run_id: str) -> str | None:
        return self._owners.get(run_id)

    def live_sessions(self) -> frozenset[str]:
        return self._live


def test_project_delegation_gate_refuses_a_missing_part_an_illegal_identifier_and_traversal(
    tmp_path: Path,
) -> None:
    """The three ``invalid_part`` shapes the gate's docstring claims: absent,
    illegal (traversal), and — the case ``PartExistsGate`` alone pinned —
    simply not in the project's parts listing. An existing part is accepted
    (returns no rejection)."""
    from hephaestus.agent_bridge.delegation import Delivery, RejectionReason
    from hephaestus.agent_bridge.wiring import ProjectDelegationGate

    dispatcher, store = _wired(tmp_path)
    try:
        project_store = dispatcher._store  # pyright: ignore[reportPrivateUsage]
        gate = ProjectDelegationGate(project_store)
        for bogus in ("does_not_exist", "../../../etc/passwd", "", "..", "/etc/passwd"):
            assert gate.classify("run-1", bogus, Delivery.PROMPT) == RejectionReason.INVALID_PART, (
                bogus
            )
        assert gate.classify("run-1", "widget", Delivery.PROMPT) is None
    finally:
        store.close()


def test_project_delegation_gate_refuses_a_part_whose_own_session_has_a_live_turn(
    tmp_path: Path,
) -> None:
    """``part_busy``: the target part's own session already has a turn in
    flight. Delegating anyway would put two interleaved turns on one
    transcript — exactly what the per-session admission guard exists to
    prevent, only *after* a child run had already been minted."""
    from hephaestus.agent_bridge.delegation import Delivery, RejectionReason
    from hephaestus.agent_bridge.wiring import ProjectDelegationGate, part_session_id

    dispatcher, store = _wired(tmp_path)
    try:
        project_store = dispatcher._store  # pyright: ignore[reportPrivateUsage]
        live = _FakeLiveRuns(owners={}, live=frozenset({part_session_id("widget")}))
        gate = ProjectDelegationGate(project_store, live=live)
        assert gate.classify("run-orch", "widget", Delivery.PROMPT) == RejectionReason.PART_BUSY
    finally:
        store.close()


def test_project_delegation_gate_refuses_self_delegation(tmp_path: Path) -> None:
    """``scope_denied``: the parent run is already running on the very session
    this delegation would prompt — delegating to yourself."""
    from hephaestus.agent_bridge.delegation import Delivery, RejectionReason
    from hephaestus.agent_bridge.wiring import ProjectDelegationGate, part_session_id

    dispatcher, store = _wired(tmp_path)
    try:
        project_store = dispatcher._store  # pyright: ignore[reportPrivateUsage]
        live = _FakeLiveRuns(
            owners={"run-self": part_session_id("widget")},
            live=frozenset({part_session_id("widget")}),
        )
        gate = ProjectDelegationGate(project_store, live=live)
        assert gate.classify("run-self", "widget", Delivery.PROMPT) == RejectionReason.SCOPE_DENIED
    finally:
        store.close()


def test_project_delegation_gate_with_no_live_view_only_checks_existence(tmp_path: Path) -> None:
    """``live=None`` (the no-sidecar runtimes: ``heph mcp``, the CLI) keeps the
    part-existence check alone rather than claiming knowledge of live turns it
    does not have — it must never refuse an existing part as busy by guessing."""
    from hephaestus.agent_bridge.delegation import Delivery
    from hephaestus.agent_bridge.wiring import ProjectDelegationGate

    dispatcher, store = _wired(tmp_path)
    try:
        project_store = dispatcher._store  # pyright: ignore[reportPrivateUsage]
        gate = ProjectDelegationGate(project_store, live=None)
        assert gate.classify("run-1", "widget", Delivery.PROMPT) is None
    finally:
        store.close()


def test_a_delegation_service_constructed_with_no_gate_is_a_type_error(tmp_path: Path) -> None:
    """The other half of J-agent-wiring-6's fix: the permissive default must be
    unreachable from production code, not merely unused by it.
    ``build_dispatcher`` always passed a real gate, but nothing stopped a FUTURE
    call site from constructing ``DelegationService`` bare and silently
    admitting every delegation — so the fix removes the default and moves the
    allow-everything gate into the testing package
    (``hephaestus.testing.delegation_gates.AllowAllGate``), catching the class
    of bug rather than only this one instance of it.

    Two assertions, because either alone is weak. The ``TypeError`` is the
    runtime half; ``# type: ignore[call-arg]`` is the STATIC half — pyright runs
    in strict mode over ``server/`` and reports an unnecessary suppression, so
    if ``gate`` ever regains a default this line stops being ignorable and the
    type-check lane fails too. The second assertion pins the relocation: the
    permissive gate must not be importable from the production module, which is
    what "unavailable in production" actually means.

    Building the opstore the way ``server/tests/conftest.py``'s own ``store``
    fixture does, inline, so this file adds no new fixture dependency.
    """
    from hephaestus.agent_bridge.admission import bridge_store_config
    from hephaestus.agent_bridge.delegation import DelegationService, Delivery

    from opstore import OpStore

    store = OpStore.create(tmp_path / "gate-heph", bridge_store_config())
    try:
        with pytest.raises(TypeError):
            DelegationService(store.admission, store.db)  # type: ignore[call-arg]
    finally:
        store.close()

    delegation_module = importlib.import_module("hephaestus.agent_bridge.delegation")
    permissive = [
        name for name in dir(delegation_module) if "allowall" in name.lower().replace("_", "")
    ]
    assert permissive == [], (
        "the permissive delegation gate is still defined in the production "
        f"module (found {permissive}); J-agent-wiring-6 moves it to "
        "hephaestus.testing.delegation_gates so production cannot reach it"
    )
    from hephaestus.testing.delegation_gates import AllowAllGate

    assert AllowAllGate().classify("run-1", "widget", Delivery.PROMPT) is None
