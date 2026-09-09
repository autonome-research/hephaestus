"""``heph mcp``'s capability set, and the asymmetry it keeps on purpose (B-2).

``heph mcp`` was the third runtime that built a bare ``ToolDispatcher`` and so
answered ``not_implemented`` for the five registry tools — not by any decision of
its own, but by copying a construction that predated them
(audit-2026-09-04-broken.md B-2). It now opens each project through
``agent_bridge/wiring.build_dispatcher``, the one owner of that answer.

What it passes to that function is where MCP genuinely differs, and the
difference is deliberate:

* ``delegation=False`` — there is **no sidecar** in this process, so nothing here
  could ever execute a child part agent. Admitting a delegation would reserve a
  slot, mint a child run id and mint a durable terminal for work no one will do;
  the typed ``not_implemented`` is the honest answer.
* ``bind_runtime`` is never called — ``query_snapshot``'s vision child is a
  *session* on a sidecar, so the tool keeps ``capability_not_available``.

Both halves were, until this file, asserted nowhere: ``server/tests/test_wiring.py``
pins the shape by calling ``build_dispatcher(delegation=False)`` itself, which
proves what that argument does and not that ``mcp/app.py`` passes it. Deleting
the argument left every test in the repository green. These tests read the real
:class:`~hephaestus.mcp.app.HephaestusMCP` — ``build_app`` → ``open_project`` →
the dispatcher that project actually holds — so the asymmetry is pinned on the
object a stock MCP client talks to.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge import wiring
from hephaestus.agent_bridge.dispatch import DispatchError, Principal, ToolDispatcher
from hephaestus.contract.tools_decl import TOOLS_BY_NAME
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.mcp import app as mcp_app
from hephaestus.mcp.app import HephaestusMCP, build_app
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.tools_fixture import scaffold

SESSION = "mcp-session-1"

#: The three tools ``delegation=False`` withholds — ``tools_decl``'s own list, so
#: a family that grows is covered without editing this file.
DELEGATION_TOOLS = ("delegate_part_agent", "get_delegation_status", "cancel_delegation")

#: The MCP principal ``HephaestusMCP._run_dispatch`` builds. Orchestrator, so a
#: delegation refusal below is the capability answering — never ``scope_denied``.
MCP_PRINCIPAL = Principal(session_id=f"mcp:{SESSION}", profile="orchestrator", part=None)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return scaffold(tmp_path / "proj")


@pytest.fixture
def runtime() -> Iterator[HephaestusMCP]:
    # Injected on purpose: with nothing injected ``build_app()`` probes bwrap
    # and refuses ``sandbox_denied`` on a host without it (J-agent-wiring-4).
    _, rt = build_app(backend=UnsafeLocalBackend())
    try:
        yield rt
    finally:
        rt.close()


def _dispatcher(rt: HephaestusMCP, root: Path) -> ToolDispatcher:
    """The dispatcher one opened project holds — the shipped object, not a copy."""
    rt.open_project(SESSION, root)
    return rt.require_project(SESSION).dispatcher


def _call(dispatcher: ToolDispatcher, tool: str, arguments: dict[str, Any]) -> Any:
    return dispatcher.dispatch(
        MCP_PRINCIPAL,
        {
            "session_id": MCP_PRINCIPAL.session_id,
            "run_id": f"mcp-e-{tool}",
            "tool": tool,
            "arguments": arguments,
            "invocation": {
                "session_id": MCP_PRINCIPAL.session_id,
                "entry_id": f"e-{tool}",
                "ordinal": 1,
                "provider_call_id": "call_0",
            },
        },
    )


# -- what MCP gained ------------------------------------------------------


def test_an_opened_project_answers_the_registry_tools(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """B-2: the five registry tools work here, exactly as they do under serve.

    They need only the project and its opstore, so there was never a reason for
    ``heph mcp`` to refuse them — and until ``build_dispatcher`` it did.
    """
    dispatcher = _dispatcher(runtime, project_root)

    skills = _call(dispatcher, "list_skills", {})
    assert skills, "list_skills must answer from the bundled registries"
    page = _call(dispatcher, "load_skill", {"name": sorted(s["name"] for s in skills)[0]})
    assert page["content"].startswith("<<<HEPHAESTUS-REGISTRY-REFERENCE")
    assert _call(dispatcher, "search_materials", {"query": "PLA"})
    assert _call(dispatcher, "search_parts_store", {"query": "bearing"})


# -- what MCP withholds, and why ------------------------------------------


@pytest.mark.parametrize("tool", DELEGATION_TOOLS)
def test_every_delegation_tool_refuses_by_name(
    runtime: HephaestusMCP, project_root: Path, tool: str
) -> None:
    """No sidecar, therefore no delegation: a typed ``not_implemented`` naming
    the tool, rather than an admitted delegation nothing will execute."""
    dispatcher = _dispatcher(runtime, project_root)
    arguments: dict[str, Any] = (
        {"part": "widget", "prompt": "make it wider"}
        if tool == "delegate_part_agent"
        else {"delegation_ref": "dg-anything"}
    )
    with pytest.raises(DispatchError) as ei:
        _call(dispatcher, tool, arguments)
    assert ei.value.reason == "not_implemented"
    assert tool in str(ei.value), "the refusal must name the tool the model asked for"


def test_query_snapshot_stays_capability_not_available(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """The vision child is a session on a sidecar; MCP never calls
    ``bind_runtime``, so the tool answers the discriminated capability error —
    **not** an exception, and not ``not_implemented``: the tool is wired, the
    runtime simply cannot ask.
    """
    dispatcher = _dispatcher(runtime, project_root)
    seed_minimal_ledger(runtime.require_project(SESSION).cad)

    result = _call(dispatcher, "query_snapshot", {"name": "widget", "question": "is it square?"})

    assert result == {
        "status": "capability_error",
        "code": "capability_not_available",
        "message": "no multimodal snapshot provider is configured for this runtime",
    }


def test_the_refusal_is_the_only_thing_the_delegation_family_can_do(
    runtime: HephaestusMCP, project_root: Path
) -> None:
    """The families are named from the contract, not from this file: if a fourth
    delegation tool is declared, it must arrive in ``DELEGATION_TOOLS`` here (and
    be refused) rather than quietly becoming the one MCP tool that admits work
    it cannot run."""
    declared = {
        name
        for name, decl in TOOLS_BY_NAME.items()
        if "delegat" in name and "orchestrator" in decl.profiles
    }
    assert declared == set(DELEGATION_TOOLS), declared


# -- that the asymmetry is MCP's own decision, not an accident -------------


def test_open_project_asks_for_the_shipped_wiring_with_delegation_off(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The argument itself, observed at the call site.

    Every assertion above would survive ``delegation=`` being dropped from
    ``mcp/app.py`` *if* the default were ``False``; and the shape tests in
    ``test_wiring.py`` would survive it being dropped whatever the default is,
    because they pass the argument themselves. This is the one test that fails
    when ``heph mcp`` stops making the decision — and it wraps the real function
    rather than replacing it, so the project it opens is still the shipped one.
    """
    seen: list[dict[str, Any]] = []
    real = wiring.build_dispatcher

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(mcp_app, "build_dispatcher", spy)
    _, rt = build_app(backend=UnsafeLocalBackend())
    try:
        _dispatcher(rt, project_root)
    finally:
        rt.close()

    assert len(seen) == 1, "one project, one construction"
    assert seen[0]["delegation"] is False, seen[0]


def test_the_asymmetry_holds_under_serve_mode(project_root: Path) -> None:
    """``heph serve --mcp`` (``mcp/cli_serve.py``: ``build_app(serve_mode=True)``)
    differs from an embedded ``build_app()`` in exactly one thing — an injected
    unsafe backend is refused up front instead of merely warned about; both
    probe bwrap when nothing is injected (J-agent-wiring-4). It gains no
    sidecar by being served, so the two withheld capabilities are withheld there
    too. Pinned separately because "serve" is the mode an operator exposes to a
    client, and a future serve-only branch is where a silent divergence would go.
    """
    try:
        _, rt = build_app(serve_mode=True)
    except Exception as exc:
        pytest.skip(f"secure sandbox probe unavailable: {exc}")
    try:
        dispatcher = _dispatcher(rt, project_root)
        assert _call(dispatcher, "list_skills", {}), "registries are served either way"
        with pytest.raises(DispatchError) as ei:
            _call(dispatcher, "delegate_part_agent", {"part": "widget", "prompt": "x"})
        assert ei.value.reason == "not_implemented"
        seed_minimal_ledger(rt.require_project(SESSION).cad)
        snapshot = _call(
            dispatcher, "query_snapshot", {"name": "widget", "question": "is it square?"}
        )
        assert snapshot["code"] == "capability_not_available"
    finally:
        rt.close()
