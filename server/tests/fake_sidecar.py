#!/usr/bin/env python3
"""A scripted fake sidecar speaking the frozen Hephaestus wire protocol.

Stands in for ``node agent/dist/main.js`` in supervisor tests: reads
LF-delimited ``{"hv":1,"jsonrpc":"2.0",...}`` frames on stdin and writes frames
on stdout (logs to stderr only). Behavior is driven by the request ``method``:

* ``echo``          -> responds with the params
* ``session.create``-> responds ``{"session_id": ...}``
* ``session.prompt``-> emits an ``event`` + a ``terminal`` notification, then
                       responds ``{"accepted": true}``
* ``sleep``         -> never responds (watchdog / timeout exercise)
* ``ask_py``        -> sends a ``py.tool_dispatch`` request back to the
                       supervisor and relays the response
* ``env_probe``     -> responds with a snapshot of selected env vars
* ``crash``         -> exits the process immediately (crash injection)
* ``big``           -> writes a single oversized (> cap) frame then exits

Env vars:

* ``FAKE_SIDECAR_EMIT_READY`` toggles a startup ``event`` notification;
* ``FAKE_SIDECAR_REQUIRE_CONFIGURE`` makes the process model the real sidecar's
  per-process configuration: ``session.*`` is refused with the real error
  (``-32600 runtime.configure has not run yet``) until ``runtime.configure``
  arrives *on this process*. That is the whole point of the respawn regression
  tests — a fresh child that was never re-configured must be observably broken;
* ``FAKE_SIDECAR_CONFIGURE_LOG`` names a file each received ``runtime.configure``
  payload is appended to (one compact JSON object per line), so a test can prove
  the payload replayed after a respawn is identical to the initial one;
* ``FAKE_SIDECAR_DIE_AFTER_S`` makes the process exit (rc 9) that many seconds
  after start-up without being asked to — a sidecar that cannot stay up, which
  is what the bounded-respawn (crash-loop) test needs;
* ``FAKE_SIDECAR_SPAWN_LOG`` names a file one line is appended to per process
  start, so a test can count how many children were actually spawned;
* ``FAKE_SIDECAR_CONFIGURE_FAILS`` makes ``runtime.configure`` answer with an
  error — a child that starts but can never be made usable, which is what the
  bounded-respawn test for a failing spawn hook needs.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import cast

HV = 1

_stdout_lock = threading.Lock()


def _send(obj: dict[str, object]) -> None:
    obj = {"hv": HV, "jsonrpc": "2.0", **obj}
    payload = (json.dumps(obj) + "\n").encode("utf-8")
    with _stdout_lock:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()


def _respond(req_id: object, result: object) -> None:
    _send({"id": req_id, "result": result})


def _notify(method: str, params: dict[str, object]) -> None:
    _send({"method": method, "params": params})


# py.* responses arriving back from the supervisor, keyed by id.
_py_pending: dict[int, dict[str, object]] = {}
_py_lock = threading.Lock()
_py_event = threading.Condition(_py_lock)
_next_py_id = [1000]


def _call_py(method: str, params: dict[str, object], timeout: float = 5.0) -> dict[str, object]:
    with _py_lock:
        pid = _next_py_id[0]
        _next_py_id[0] += 1
    _send({"id": pid, "method": method, "params": params})
    deadline = time.monotonic() + timeout
    with _py_event:
        while pid not in _py_pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"error": {"code": -32003, "message": "py call timeout"}}
            _py_event.wait(remaining)
        return _py_pending.pop(pid)


#: Set by ``runtime.configure``; never survives the process, exactly like the
#: real sidecar's provider registry.
_configured = [False]


def _record_configure(params: dict[str, object]) -> None:
    _configured[0] = True
    path = os.environ.get("FAKE_SIDECAR_CONFIGURE_LOG")
    if not path:
        return
    line = json.dumps(params, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)


def _needs_configure(method: str) -> bool:
    return (
        bool(os.environ.get("FAKE_SIDECAR_REQUIRE_CONFIGURE"))
        and not _configured[0]
        and method.startswith("session.")
    )


def _handle(msg: dict[str, object]) -> None:
    method = msg.get("method")
    req_id = msg.get("id")

    # Response to a py.* request we originated.
    if method is None and req_id is not None:
        with _py_event:
            _py_pending[int(cast("int", req_id))] = msg
            _py_event.notify_all()
        return

    if req_id is None:
        return  # a notification from the supervisor (cancel / ack): ignore

    params = cast("dict[str, object]", msg.get("params") or {})

    if _needs_configure(str(method)):
        _send(
            {
                "id": req_id,
                "error": {"code": -32600, "message": "runtime.configure has not run yet"},
            }
        )
        return

    if method == "echo":
        _respond(req_id, params)
    elif method == "runtime.configure":
        _record_configure(params)
        if os.environ.get("FAKE_SIDECAR_CONFIGURE_FAILS"):
            _send({"id": req_id, "error": {"code": -32603, "message": "configure refused"}})
        else:
            _respond(req_id, {"ok": True})
    elif method == "session.create":
        _respond(req_id, {"session_id": f"sess-{req_id}"})
    elif method == "session.prompt":
        run_id = str(params.get("run_id", f"run-{req_id}"))
        _notify("event", {"run_id": run_id, "seq": 1, "kind": "audit", "payload": {"m": "start"}})
        _notify(
            "terminal",
            {"run_id": run_id, "terminal_id": f"t-{run_id}", "state": "completed", "payload": {}},
        )
        _respond(req_id, {"accepted": True})
    elif method == "sleep":
        pass  # never respond
    elif method == "env_probe":
        names = cast("list[object]", params.get("names") or [])
        snapshot = {str(n): os.environ.get(str(n)) for n in names}
        _respond(req_id, {"env": snapshot})
    elif method == "ask_py":
        resp = _call_py(
            "py.tool_dispatch",
            {
                "session_id": params.get("session_id", "s"),
                "run_id": params.get("run_id", "r"),
                "tool": params.get("tool", "read_part"),
                "arguments": params.get("arguments") or {},
                "invocation": params.get("invocation") or {},
            },
        )
        _respond(req_id, {"py": resp})
    elif method == "crash":
        os._exit(7)
    elif method == "big":
        size = int(cast("int", params.get("bytes", 70 * 1024 * 1024)))
        sys.stdout.buffer.write(b'{"hv":1,"jsonrpc":"2.0","id":1,"result":"')
        sys.stdout.buffer.write(b"x" * size)
        sys.stdout.buffer.write(b'"}\n')
        sys.stdout.buffer.flush()
        os._exit(0)
    else:
        _send({"id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}})


def _record_spawn() -> None:
    path = os.environ.get("FAKE_SIDECAR_SPAWN_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {time.monotonic()}\n")


def _arm_suicide() -> None:
    """Exit unasked after ``FAKE_SIDECAR_DIE_AFTER_S`` seconds (crash-loop mode)."""
    raw = os.environ.get("FAKE_SIDECAR_DIE_AFTER_S")
    if not raw:
        return
    delay = float(raw)

    def die() -> None:
        time.sleep(delay)
        os._exit(9)

    threading.Thread(target=die, daemon=True).start()


def main() -> None:
    _record_spawn()
    _arm_suicide()
    if os.environ.get("FAKE_SIDECAR_EMIT_READY"):
        _notify("event", {"run_id": "boot", "seq": 0, "kind": "audit", "payload": {"ready": True}})
    print(f"[fake-sidecar] pid={os.getpid()}", file=sys.stderr, flush=True)
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline()
        if not line:
            break
        if not line.strip():
            continue
        try:
            parsed: object = json.loads(line)
        except json.JSONDecodeError:
            _send({"id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        if isinstance(parsed, dict):
            msg = cast("dict[str, object]", parsed)
            # Dispatch each message on its own thread so a handler that calls
            # back into the supervisor (ask_py) does not block the reader from
            # receiving the supervisor's response.
            threading.Thread(target=_handle, args=(msg,), daemon=True).start()


if __name__ == "__main__":
    main()
