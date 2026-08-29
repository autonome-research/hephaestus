# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Run-scoped request text: ``VALIDATION.md`` §4/§5's request, bound per **run**.

``INTERFACE.md`` §7A.4 / §19.23. ``CadOps`` held exactly one ``_request_text``
for the whole project — one field per *runtime*, not per session and not per run
— and every session shared it. The 2026-08-28 review named what that costs the
moment two turns overlap: the second ``set_request_text`` clobbers the first, so
session A's build is critiqued against session B's prompt and
``prompt_number_diff`` reports a **fabricated request diff**. That is precisely
the failure §7A.4 exists to prevent, and a per-session guard could not have
saved it, because the field is not per session either.

The fix is to bind the text where it belongs: to the run that carries it.

* :func:`bind_run_request_text` records ``run_id -> text`` when a run starts.
  ``BridgeRuntime.prompt`` is the one caller — the only place that sees the
  operator's words before the model paraphrases them.
* :func:`active_run` scopes the *reading* side. ``py.tool_dispatch`` carries the
  ``run_id`` of the turn making the call, so the one dispatcher (mission rule 6)
  enters this scope around every routed tool and ``CadOps.request_text`` answers
  for **that** run. A :class:`~contextvars.ContextVar` is what makes it hold:
  the supervisor's reader thread handles py requests serially today and a thread
  pool would work identically, because each dispatch sets and resets its own
  scope rather than mutating one shared field.

**Presence is the authority, not truthiness.** A run whose text is bound to
``None`` (an empty prompt) is *known* to have no request; a run that was never
bound at all — a raw dispatch from a test, an HTTP tool route, an MCP call —
falls back to whatever the embedder set on the ops object. Collapsing the two
would either fabricate a request for a run that has none or silently strip the
request from every non-run caller, and both are the kind of quiet reinterpretation
"unknown is a first-class state" (``_base.py``) forbids.

The registry is process-wide rather than a field on ``CadOps`` for one concrete
reason: ``WorkspaceRuntime.reload_manifest`` (§6.4's DFM setting) rebuilds
``CadOps`` and rebinds the runtime to the new object, and a binding that lived on
the old instance would vanish mid-turn. Run ids are minted per process
(``BridgeRuntime.new_run_id``), so keying on them across a rebind is exact.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

__all__ = [
    "RUN_REQUEST_BINDINGS_MAX",
    "active_run",
    "active_run_id",
    "bind_run_request_text",
    "inherit_run_request_text",
    "release_run_request_text",
    "request_text_for_active_run",
    "run_request_text",
]

#: Bound on the binding table, for the same reason ``BridgeRuntime`` bounds its
#: run→session map: a long-lived serving process runs unboundedly many runs, and
#: a release that never arrives (a crashed turn) must not grow the table forever.
#: Eviction is oldest-first and is a **backstop**: every run started through
#: ``BridgeRuntime.prompt`` releases its own binding in a ``finally``.
RUN_REQUEST_BINDINGS_MAX: Final[int] = 256

#: ``run_id -> request text``. The value may be ``None`` (a run with no request);
#: membership, not the value, is what says the run is bound.
_bindings: OrderedDict[str, str | None] = OrderedDict()
_lock = threading.Lock()

#: The run whose tool call is executing on this thread/context, or ``None`` when
#: the caller is not a run at all (an HTTP tool route, MCP, a direct test call).
_active_run: ContextVar[str | None] = ContextVar("hephaestus_active_run", default=None)


def bind_run_request_text(run_id: str, text: str | None) -> None:
    """Bind ``run_id``'s request text — the operator's words, exactly.

    ``VALIDATION.md`` §4 diffs the numbers in the request against the built
    geometry and §5 hands the reviewer the request verbatim, so what is stored
    here is the prompt itself: never a composed context block (§7A.4), never a
    paraphrase. Empty or whitespace-only text binds ``None``, which still marks
    the run **bound** — it is known to have no request rather than unknown.
    """
    cleaned = text.strip() if text is not None else None
    with _lock:
        _bindings[run_id] = cleaned or None
        _bindings.move_to_end(run_id)
        while len(_bindings) > RUN_REQUEST_BINDINGS_MAX:
            _bindings.popitem(last=False)


def inherit_run_request_text(parent_run_id: str, child_run_id: str) -> None:
    """Give a child run its parent's request text (``app.py``'s delegation rule).

    A delegated part agent is working the *original* request; its build is
    critiqued against that, not against the orchestrator's hand-off sentence,
    which is why delegated prompts never pass through ``BridgeRuntime.prompt``.
    With the text bound per run, that inheritance has to be said out loud here
    rather than fall out of a shared field. A parent with no binding leaves the
    child unbound — the absence is inherited too, never invented.
    """
    with _lock:
        if parent_run_id not in _bindings:
            return
        _bindings[child_run_id] = _bindings[parent_run_id]
        _bindings.move_to_end(child_run_id)
        while len(_bindings) > RUN_REQUEST_BINDINGS_MAX:
            _bindings.popitem(last=False)


def release_run_request_text(run_id: str) -> None:
    """Drop ``run_id``'s binding when its turn is over. Idempotent."""
    with _lock:
        _bindings.pop(run_id, None)


def run_request_text(run_id: str) -> str | None:
    """The text bound to ``run_id``, or ``None`` when it has none or is unbound."""
    with _lock:
        return _bindings.get(run_id)


def active_run_id() -> str | None:
    """The run whose tool call is executing here, or ``None`` outside a run."""
    return _active_run.get()


@contextmanager
def active_run(run_id: str | None) -> Generator[None]:
    """Scope a tool call to its run, so ``request_text`` answers for that run.

    ``run_id`` may be ``None`` or empty — an HTTP tool route and an MCP call
    carry no run — and then nothing is scoped and the ops object's own text is
    what a reader sees. Resetting through the token (never ``set(None)``) keeps
    nesting honest if a routed op ever dispatches another.
    """
    token = _active_run.set(run_id or None)
    try:
        yield
    finally:
        _active_run.reset(token)


def request_text_for_active_run(fallback: str | None) -> str | None:
    """The active run's request text, or ``fallback`` when no run is bound here.

    One lock for presence *and* value: a late tool call from a released run must
    resolve to that run's absence, not to a neighbouring run's request.
    """
    run_id = _active_run.get()
    if run_id is None:
        return fallback
    with _lock:
        if run_id not in _bindings:
            return fallback
        return _bindings[run_id]
