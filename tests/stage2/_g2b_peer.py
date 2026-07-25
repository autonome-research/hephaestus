#!/usr/bin/env python3
"""A scripted wire-protocol peer for the Gate G2 bridge-bounds runtime tests.

Speaks the frozen Hephaestus bridge protocol (LF-delimited ``{"hv":1,
"jsonrpc":"2.0",…}`` frames, protocol on stdout, logs on stderr) so the tests
drive the **real** Python bridge — :class:`~hephaestus.agent_bridge.supervisor.Supervisor`
framing/protocol, :class:`~hephaestus.agent_bridge.events.EventPump` coalescing
and terminal channel, :class:`~hephaestus.agent_bridge.admission.BridgeAdmission`
slots — without paying for a Pi model loop. ``server/tests/fake_sidecar.py``
covers the supervisor's own request/response paths; this peer adds the event and
terminal *volume* control those tests do not need:

``emit_terminals {runs, state}``
    one ``terminal`` notification per run id, all before any ack is processed;
``flood {run_id, progress, tool_call_ids}``
    ``progress`` deltas interleaved with the never-droppable classes (audit,
    tool_call, tool_result, question, answer);
``hold {run_id}``
    remember the run and answer immediately; a later ``cancel`` notification for
    that run emits its single ``cancelled`` terminal, and any other run is
    untouched;
``complete {run_id}``
    emit one ``completed`` terminal for a held run;
``acks {}``
    the ``terminal.ack`` notifications received so far, in arrival order.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, cast

HV = 1

_stdout_lock = threading.Lock()
_state_lock = threading.Lock()
_held: set[str] = set()
_acks: list[dict[str, str]] = []
_seq: dict[str, int] = {}


def _send(obj: dict[str, Any]) -> None:
    payload = (json.dumps({"hv": HV, "jsonrpc": "2.0", **obj}) + "\n").encode("utf-8")
    with _stdout_lock:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()


def _respond(req_id: Any, result: Any) -> None:
    _send({"id": req_id, "result": result})


def _next_seq(run_id: str) -> int:
    with _state_lock:
        value = _seq.get(run_id, 0)
        _seq[run_id] = value + 1
        return value


def _event(
    run_id: str, kind: str, payload: dict[str, Any], tool_call_id: str | None = None
) -> None:
    params: dict[str, Any] = {
        "run_id": run_id,
        "seq": _next_seq(run_id),
        "kind": kind,
        "payload": payload,
    }
    if tool_call_id is not None:
        params["tool_call_id"] = tool_call_id
    _send({"method": "event", "params": params})


def _terminal(run_id: str, state: str) -> None:
    _send(
        {
            "method": "terminal",
            "params": {
                "run_id": run_id,
                "terminal_id": f"peer:{run_id}:{state}",
                "state": state,
                "payload": {"reason": state},
            },
        }
    )


def _handle_request(req_id: Any, method: str, params: dict[str, Any]) -> None:
    if method == "echo":
        _respond(req_id, params)
    elif method == "emit_terminals":
        runs = [str(r) for r in cast("list[Any]", params.get("runs") or [])]
        state = str(params.get("state", "completed"))
        for run_id in runs:
            _terminal(run_id, state)
        _respond(req_id, {"count": len(runs)})
    elif method == "flood":
        run_id = str(params["run_id"])
        progress = int(cast("int", params.get("progress", 0)))
        keys = [str(k) for k in cast("list[Any]", params.get("tool_call_ids") or ["c0"])]
        critical = 0
        for index in range(progress):
            key = keys[index % len(keys)]
            _event(run_id, "progress", {"pct": index}, key)
            if index % 500 == 0:
                _event(run_id, "audit", {"i": index})
                _event(run_id, "tool_call", {"name": "measure", "i": index}, key)
                _event(run_id, "tool_result", {"ok": True, "i": index}, key)
                _event(run_id, "question", {"question": f"q{index}"})
                _event(run_id, "answer", {"answer": f"a{index}"})
                critical += 5
        _respond(req_id, {"progress": progress, "critical": critical})
    elif method == "hold":
        run_id = str(params["run_id"])
        with _state_lock:
            _held.add(run_id)
        _event(run_id, "audit", {"held": True})
        _respond(req_id, {"held": run_id})
    elif method == "complete":
        run_id = str(params["run_id"])
        with _state_lock:
            _held.discard(run_id)
        _event(run_id, "text_delta", {"text": "done"})
        _terminal(run_id, "completed")
        _respond(req_id, {"completed": run_id})
    elif method == "acks":
        with _state_lock:
            _respond(req_id, {"acks": list(_acks)})
    elif method == "held":
        with _state_lock:
            _respond(req_id, {"held": sorted(_held)})
    elif method == "shutdown":
        _respond(req_id, {"bye": True})
    else:
        _send({"id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}})


def _handle_notification(method: str, params: dict[str, Any]) -> None:
    if method == "terminal.ack":
        with _state_lock:
            _acks.append(
                {
                    "run_id": str(params.get("run_id", "")),
                    "terminal_id": str(params.get("terminal_id", "")),
                }
            )
    elif method == "cancel":
        run_id = str(params.get("run_id", ""))
        with _state_lock:
            known = run_id in _held
            _held.discard(run_id)
        if known:
            # Only the cancelled run's stream ends; siblings keep running.
            _terminal(run_id, "cancelled")


def _dispatch(msg: dict[str, Any]) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    if method is None:
        return  # a response to a request we never send
    params = cast("dict[str, Any]", msg.get("params") or {})
    if req_id is None:
        _handle_notification(str(method), params)
        return
    _handle_request(req_id, str(method), params)


def main() -> None:
    print(f"[g2b-peer] pid={os.getpid()}", file=sys.stderr, flush=True)
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
            threading.Thread(
                target=_dispatch, args=(cast("dict[str, Any]", parsed),), daemon=True
            ).start()


if __name__ == "__main__":
    main()
