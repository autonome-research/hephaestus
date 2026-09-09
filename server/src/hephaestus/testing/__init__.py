"""Test support for Hephaestus's own suites — **not** product API.

This package ships inside ``hephaestus-server`` only so that the three suites
which need the same harness can import it by name instead of reaching across
directories with ``sys.path`` tricks: ``server/tests`` (unit/integration),
``tests/stage2`` (the Gate G2 bridge suite) and any future consumer. Nothing in
the product imports it, no compatibility promise is made about it, and it must
never be imported from ``hephaestus.core``, ``hephaestus.agent_bridge``,
``hephaestus.bench`` or ``hephaestus.mcp``.

What lives here is exactly what more than one suite needs:

* :mod:`~hephaestus.testing.fake_openai` — a scripted, in-process
  OpenAI-compatible provider the real Node sidecar talks to;
* :mod:`~hephaestus.testing.tools_fixture` — a real project over a real opstore
  behind a real ``ToolDispatcher``;
* :mod:`~hephaestus.testing.projects` — the empty-but-real project scaffold;
* :mod:`~hephaestus.testing.sidecar` — locating and building the staged
  sidecar, resolving pnpm the way ``scripts/bootstrap.sh`` does, and refusing a
  stale stage on the build-skip path;
* :mod:`~hephaestus.testing.doubles` — deterministic clock/liveness oracles;
* :mod:`~hephaestus.testing.stream_assertions` — turn scripting plus the public
  event-stream invariants.

Suite-specific helpers stay in their suite. Note that ``tests/stage3`` is
deliberately absent: the Gate G3 client toolkit must import no ``hephaestus``
code at all, and a test enforces that structurally.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; the runtime path is lazy
    from .doubles import FakeClock, FakeLiveness, owner
    from .fake_openai import FakeOpenAI, RequestInfo, Turn, TurnResolver, start_fake_openai
    from .projects import scaffold_project
    from .sidecar import (
        REQUIRE_SIDECAR_ENV,
        SidecarUnavailable,
        agent_dir,
        build_agent_dist,
        node_available,
        node_executable,
        pnpm_command,
        record_staged_source_digest,
        sidecar_main,
        sidecar_source_digest,
        workflow_runner_main,
    )
    from .stream_assertions import (
        assert_stream_shape,
        events_of,
        kinds_of,
        last_tool_result,
        payload_of,
        text,
        tool_call,
    )
    from .tools_fixture import ORCH, PART_WIDGET, QUICK_WIDGET, Project, make_project, scaffold

__all__ = [
    "ORCH",
    "PART_WIDGET",
    "QUICK_WIDGET",
    "REQUIRE_SIDECAR_ENV",
    "FakeClock",
    "FakeLiveness",
    "FakeOpenAI",
    "Project",
    "RequestInfo",
    "SidecarUnavailable",
    "Turn",
    "TurnResolver",
    "agent_dir",
    "assert_stream_shape",
    "build_agent_dist",
    "events_of",
    "kinds_of",
    "last_tool_result",
    "make_project",
    "node_available",
    "node_executable",
    "owner",
    "payload_of",
    "pnpm_command",
    "record_staged_source_digest",
    "scaffold",
    "scaffold_project",
    "sidecar_main",
    "sidecar_source_digest",
    "start_fake_openai",
    "text",
    "tool_call",
    "workflow_runner_main",
]

# Which submodule owns each re-exported name. The re-exports are LAZY (PEP 562)
# because eagerly importing them costs ~4.4 s: `tools_fixture` pulls in
# `hephaestus.core`, which pulls in the CAD kernel. That was invisible while the
# only importers were suites that wanted the kernel anyway, and it became
# load-bearing when `hypothesis_profile` moved here — a pytest `-p` plugin is
# imported at STARTUP, so an eager package body would have added those seconds
# to every pytest session in the repository, including the ones with no
# `hephaestus.testing` consumer in them (`contract/tests` is a ~3.5 s lane).
# The `TYPE_CHECKING` block above keeps pyright and editors seeing real symbols.
_EXPORTS: dict[str, str] = {
    "FakeClock": "doubles",
    "FakeLiveness": "doubles",
    "owner": "doubles",
    "FakeOpenAI": "fake_openai",
    "RequestInfo": "fake_openai",
    "Turn": "fake_openai",
    "TurnResolver": "fake_openai",
    "start_fake_openai": "fake_openai",
    "scaffold_project": "projects",
    "REQUIRE_SIDECAR_ENV": "sidecar",
    "SidecarUnavailable": "sidecar",
    "agent_dir": "sidecar",
    "build_agent_dist": "sidecar",
    "node_available": "sidecar",
    "node_executable": "sidecar",
    "pnpm_command": "sidecar",
    "record_staged_source_digest": "sidecar",
    "sidecar_main": "sidecar",
    "sidecar_source_digest": "sidecar",
    "workflow_runner_main": "sidecar",
    "assert_stream_shape": "stream_assertions",
    "events_of": "stream_assertions",
    "kinds_of": "stream_assertions",
    "last_tool_result": "stream_assertions",
    "payload_of": "stream_assertions",
    "text": "stream_assertions",
    "tool_call": "stream_assertions",
    "ORCH": "tools_fixture",
    "PART_WIDGET": "tools_fixture",
    "QUICK_WIDGET": "tools_fixture",
    "Project": "tools_fixture",
    "make_project": "tools_fixture",
    "scaffold": "tools_fixture",
}


def __getattr__(name: str) -> Any:
    """Resolve a re-export on first use, then cache it in the module globals.

    A missing name must still raise :class:`AttributeError` with the module in
    the message, because that is what ``from hephaestus.testing import typo``
    reports and what :func:`hasattr` relies on.
    """
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
