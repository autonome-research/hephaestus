"""The gate drives the runtime that ships (audit-2026-09-04-broken.md B-2/B-3).

Gate G2 was green for months while nine model-visible tools answered
``not_implemented`` in ``heph agent``, ``heph serve --web`` and ``heph mcp``
alike. Nothing was wrong with the gate's *clauses*: the registry tools really did
return real content, delegation really did admit a child run and settle it. They
were wrong about the *subject*. ``_g2.py``'s ``G2Runtime`` opened the registry
set, constructed the ``DelegationService`` and built the ``ToolDispatcher``
itself, and overrode ``_on_py_request`` to add the ``py.delegate`` routing
production was missing — so every clause exercised a composition that existed
only in the test harness. A harness that supplies the product's capabilities
tests a runtime nobody ships.

B-2 moved that composition into ``agent_bridge/wiring.build_dispatcher`` and B-3
lifted the delegate route into ``BridgeRuntime._handle_delegate``; the harness
override was deleted. This file is the guard on that deletion. It asserts two
things the rest of the suite cannot see, because the rest of the suite asserts
*outcomes* and would be equally green if the harness quietly wired the
capabilities again:

* **the harness constructs nothing the product owns** — checked structurally,
  over ``_g2.py``'s own syntax tree, because that is the property (no
  ``ToolDispatcher(…)``, no ``DelegationService(…)``, no registry open) rather
  than any single call's result;
* **the shipped construction answers** — the nine tools B-2 named, driven
  through ``make_wired_project`` (``build_dispatcher``, no injections, no
  sidecar), none of them refusing ``not_implemented``.

The two capabilities the harness *does* still supply — a scripted vision child
and a scripted delegation coordinator — are legitimate and deliberately allowed:
production can bind neither until ``py.*`` dispatch leaves the supervisor's
single reader thread, and both arrive through the shipped ``bind_runtime`` seam
rather than by rebuilding the dispatcher. The test below pins that they arrive
that way and that the shipped binding still runs first.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import _g2
import jsonschema
import pytest
from _g2 import ORCH, REPO, G2Runtime
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.testing.tools_fixture import Project, make_wired_project

#: Constructions that belong to ``server/`` and to no test. ``RegistrySet`` and
#: ``RegistryOps`` are the registry stack ``wiring.resolve_registry`` opens;
#: ``DelegationService`` is the state machine ``build_dispatcher`` builds with a
#: real gate; ``ToolDispatcher`` and ``build_dispatcher`` are the composition
#: itself. A harness that calls any of them has taken the product's decision back.
PRODUCT_CONSTRUCTIONS = frozenset(
    {
        "ToolDispatcher",
        "DelegationService",
        "RegistryOps",
        "RegistrySet",
        "build_dispatcher",
    }
)

#: The nine tools audit-2026-09-04-broken.md B-2 found unwired in every shipped
#: runtime, with arguments good enough to reach their capability check.
B2_TOOLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("list_skills", {}),
    ("load_skill", {"name": "build123d-idioms"}),
    ("search_materials", {"query": "PLA"}),
    ("search_parts_store", {"query": "bearing"}),
    ("instance_store_part", {"id": "bearing_608", "params": {}}),
    ("delegate_part_agent", {"part": "widget", "prompt": "make it wider"}),
    ("get_delegation_status", {"delegation_ref": "dg-nope"}),
    ("cancel_delegation", {"delegation_ref": "dg-nope"}),
    ("query_snapshot", {"name": "widget", "question": "is it square?"}),
)


def _result_schema(tool: str) -> dict[str, Any]:
    document = cast(
        "dict[str, Any]",
        json.loads((REPO / "schemas" / "tools" / f"{tool}.schema.json").read_text("utf-8")),
    )
    return cast("dict[str, Any]", document["result"])


def _called_names(tree: ast.AST) -> set[str]:
    """Every callee's trailing identifier — ``X(…)`` and ``a.b.X(…)`` alike."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
            if isinstance(func.value, ast.Name):
                names.add(func.value.id)
    return names


@pytest.fixture
def wired(tmp_path: Path) -> Iterator[Project]:
    """The dispatcher a shipped runtime builds, over a real project, no sidecar."""
    project = make_wired_project(tmp_path / "proj")
    try:
        yield project
    finally:
        project.close()


# -- the harness owns no capability ---------------------------------------


def test_the_harness_constructs_nothing_the_product_owns() -> None:
    """``_g2.py`` may compose the product; it may not *be* it.

    Structural rather than behavioural on purpose: the failure this guards
    against is a future edit that re-adds ``registry=``/``delegation=`` to make a
    new clause pass locally. Every outcome test in this directory would stay
    green through that; this one would not.
    """
    source = Path(inspect.getfile(_g2)).read_text(encoding="utf-8")
    offending = _called_names(ast.parse(source)) & PRODUCT_CONSTRUCTIONS
    assert not offending, (
        f"tests/stage2/_g2.py constructs {sorted(offending)}: the capability set is "
        "hephaestus.agent_bridge.wiring.build_dispatcher's to decide, and a harness "
        "that decides it again is how B-2 stayed hidden through Gate G2"
    )

    assert not hasattr(_g2, "registry_ops"), (
        "_g2.registry_ops opened the registry set for the harness; the shipped runtime opens it now"
    )
    assert "registry_ops" not in _g2.__all__


def test_the_gate_runtime_takes_no_capability_by_constructor() -> None:
    """``G2Runtime`` accepts the two *live-sidecar* stand-ins and nothing else.

    ``registry=`` / ``delegation=`` / ``clock=`` were the injections that let the
    harness answer for the product. ``snapshot=`` and ``sandbox=`` remain, and
    are the two things a test legitimately owns: a scripted vision child, and the
    probed backend ``heph agent`` genuinely has not got.
    """
    accepted = set(inspect.signature(G2Runtime.__init__).parameters)
    assert not accepted & {"registry", "delegation", "clock"}, sorted(accepted)
    assert {"snapshot", "sandbox"} <= accepted, sorted(accepted)


def test_the_gate_runtime_keeps_the_shipped_delegate_route() -> None:
    """B-3: ``py.delegate`` is routed by ``BridgeRuntime``, not by the harness.

    ``G2Runtime`` used to override the routing itself, which is precisely why the
    illegal ``part_session_id: null`` placeholder in ``app.py`` was never reached
    by a gate test. Identity comparisons rather than a behavioural probe: an
    override that merely *happened* to agree today is still an override, and the
    next divergence would be silent.
    """
    assert G2Runtime._handle_delegate is BridgeRuntime._handle_delegate  # pyright: ignore[reportPrivateUsage]
    assert G2Runtime._route_py_request is BridgeRuntime._route_py_request  # pyright: ignore[reportPrivateUsage]


def test_the_scripted_capabilities_arrive_through_the_shipped_seam() -> None:
    """The harness may still script the vision child and the delegation runner —
    neither can exist in production while ``py.*`` dispatch runs on the reader
    thread — but it must hand them over through
    ``ToolDispatcher.bind_runtime`` *after* the shipped binding has run, not by
    rebuilding the dispatcher underneath it.
    """
    bind = G2Runtime._bind_runtime_capabilities  # pyright: ignore[reportPrivateUsage]
    body = ast.parse(textwrap.dedent(inspect.getsource(bind)))
    calls = _called_names(body)
    assert "super" in calls and "_bind_runtime_capabilities" in calls, (
        "the harness must call super()._bind_runtime_capabilities(): dropping it "
        "silently unbinds the snapshot caller the shipped runtime installs"
    )
    assert "bind_runtime" in calls
    assert not _called_names(body) & PRODUCT_CONSTRUCTIONS


# -- the shipped construction answers -------------------------------------


@pytest.mark.parametrize(("tool", "arguments"), B2_TOOLS, ids=[name for name, _ in B2_TOOLS])
def test_no_tool_b2_named_still_refuses_not_implemented(
    wired: Project, tool: str, arguments: dict[str, Any]
) -> None:
    """The B-2 regression pin, one tool at a time.

    ``not_implemented`` is the dispatcher saying "this runtime has no such
    capability", and for these nine that sentence was false: the registry stack
    and the delegation service need nothing but the project and its opstore.
    Each tool is asserted only on *that*, so a refusal with an honest reason —
    ``capability_not_available`` for a generator with no sandbox, ``not_found``
    for a delegation ref that never existed — passes, and only the B-2 answer
    fails.
    """
    wired.store.admission.admit("run-1")
    try:
        result = wired.call(tool, arguments)
    except DispatchError as exc:
        assert exc.reason != "not_implemented", f"{tool}: {exc}"
        return
    payload = cast("dict[str, Any]", result) if isinstance(result, dict) else {}
    assert payload.get("code") != "not_implemented", result


def test_the_registry_tools_answer_with_real_registry_content(wired: Project) -> None:
    """Not merely "not a refusal": the bytes come from the project's own
    verified registry set, delimited as untrusted reference content."""
    names = {entry["name"] for entry in wired.call("list_skills", {})}
    assert names, "list_skills over the bundled registries"
    page = wired.call("load_skill", {"name": sorted(names)[0]})
    assert page["content"].startswith("<<<HEPHAESTUS-REGISTRY-REFERENCE")


# -- the real gate, before admission --------------------------------------


def test_delegating_to_a_part_that_does_not_exist_is_rejected_before_admission(
    wired: Project,
) -> None:
    """``wiring.PartExistsGate``: the producer ``RejectionReason.INVALID_PART``
    never had.

    The default ``_AllowAllGate`` admitted this — a child run id minted, a slot
    reserved, and a terminal reported for a part that was never there — which is
    the second half of what made a wired-but-ungated delegation worse than an
    unwired one. The rejection must therefore be observable as *nothing having
    happened*: no child in the admission table, no delegation ref to poll.
    """
    wired.store.admission.admit("run-1")
    occupied = wired.store.admission.occupied_run_ids()

    result = wired.call("delegate_part_agent", {"part": "ghost", "prompt": "build it"})

    assert result["status"] == "rejected"
    assert result["reason"] == "invalid_part", result
    assert "child_run_id" not in result and "delegation_ref" not in result
    assert wired.store.admission.occupied_run_ids() == occupied
    jsonschema.validate(result, _result_schema("delegate_part_agent"))


def test_the_gate_admits_a_part_that_does_exist(wired: Project) -> None:
    """The contrast that makes the test above mean something: the same call for
    a real part is admitted, and reaches a durable ``interrupted`` terminal
    (no delegation runner can be bound yet) rather than being refused."""
    wired.store.admission.admit("run-1")
    result = wired.call(
        "delegate_part_agent", {"part": "widget", "prompt": "make it wider"}, principal=ORCH
    )
    assert result["status"] == "interrupted", result
    assert result["child_run_id"] and result["delegation_ref"]
    jsonschema.validate(result, _result_schema("delegate_part_agent"))
