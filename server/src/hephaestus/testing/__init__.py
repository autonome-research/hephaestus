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
* :mod:`~hephaestus.testing.sidecar` — locating and building ``agent/dist``;
* :mod:`~hephaestus.testing.doubles` — deterministic clock/liveness oracles;
* :mod:`~hephaestus.testing.stream_assertions` — turn scripting plus the public
  event-stream invariants.

Suite-specific helpers stay in their suite. Note that ``tests/stage3`` is
deliberately absent: the Gate G3 client toolkit must import no ``hephaestus``
code at all, and a test enforces that structurally.
"""

from __future__ import annotations

from .doubles import FakeClock, FakeLiveness, owner
from .fake_openai import FakeOpenAI, RequestInfo, Turn, TurnResolver, start_fake_openai
from .projects import scaffold_project
from .sidecar import (
    agent_dir,
    build_agent_dist,
    node_available,
    node_executable,
    sidecar_main,
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
    "FakeClock",
    "FakeLiveness",
    "FakeOpenAI",
    "Project",
    "RequestInfo",
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
    "scaffold",
    "scaffold_project",
    "sidecar_main",
    "start_fake_openai",
    "text",
    "tool_call",
    "workflow_runner_main",
]
