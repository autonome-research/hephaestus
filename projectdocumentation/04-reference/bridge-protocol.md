# Agent bridge protocol

> **Verified against** `49a90c6` on 2026-09-12.
> Method sets printed from `hephaestus.agent_bridge.protocol`: 9 `py.*` requests,
> 3 `py.*` notifications, 19 sidecar requests, 2 sidecar notifications.
> Supervisor defaults read from `SupervisorConfig`.

The bridge is the private channel between the Python engine and the TypeScript
sidecar (`node agent/dist/main.js`). It is **not** a public API: it is two
trusted processes on one machine, and its design constraints come from that.

## The wire

LF-delimited JSON-RPC 2.0 over the child's stdin/stdout.

- Frames are UTF-8 JSON objects terminated by a single `\n`. **Protocol stdout
  never carries anything else** — logs go to stderr.
- Every frame carries `{"hv": 1, "jsonrpc": "2.0", …}`. An unknown `hv` fails
  closed.
- The decoder is **incremental**: it aborts as soon as an in-progress frame
  exceeds `wire.max_frame_bytes` (64 MiB), without buffering the whole oversized
  frame. `encode_frame` refuses to emit one outbound.

### Byte parity across languages

`framing.py` and `agent/src/framing.ts` share one wire contract, and
`encode_frame` produces **byte-for-byte identical output** to the TypeScript
`encodeFrame` for the same value — asserted by a cross-language golden fixture.
That relies on a canonical JSON serialization: recursively sorted object keys,
compact separators, raw (non-ASCII-escaped) UTF-8.

Byte parity is not an aesthetic. It is what lets a frame be hashed, compared or
replayed on either side without either side being the authority.

## Error codes

Standard JSON-RPC codes plus a Hephaestus application range, mirrored in
`agent/src/rpc.ts`:

| Code | Name |
| --- | --- |
| -32700 | `PARSE_ERROR` |
| -32600 | `INVALID_REQUEST` |
| -32601 | `METHOD_NOT_FOUND` |
| -32602 | `INVALID_PARAMS` |
| -32603 | `INTERNAL_ERROR` |
| -32000 | `BUSY` |
| -32001 | `FRAME_TOO_LARGE` |
| -32002 | `UNSUPPORTED_VERSION` |
| -32003 | `TIMEOUT` |
| -32004 | `PROCESS_DOWN` |

## The method vocabularies are frozen

Four closed sets. Each side may only originate what it declares.

### Python → sidecar: 19 requests

```
session.create      session.prompt      session.cancel      session.compact
session.model.get   session.model.set
history.page        query.snapshot      runtime.configure   shutdown
providers.list      providers.models
login.begin         login.complete      login.cancel        login.status
credentials.set_key credentials.signout credentials.status
```

### Sidecar → Python: 9 requests

```
py.tool_dispatch        py.ask_user          py.delegate
py.admission_capacity
py.jobstore_get  py.jobstore_put  py.jobstore_list  py.jobstore_delete
py.jobstore_checkpoint
```

### Notifications

| Direction | Methods |
| --- | --- |
| Python → sidecar | `cancel`, `session.answer`, `terminal.ack` |
| sidecar → Python | `event`, `terminal` |

## The supervisor

`agent_bridge/supervisor.py` owns the child. It is the *client* for the
`session.*` / `history.*` / `query.*` methods and the *server* for the `py.*`
requests the sidecar originates.

### Minimal environment

Only `PATH`, `HOME`, `LANG`, `TMPDIR` are forwarded, plus credential variables
named in an **explicit allowlist**. An ambient provider key (`ANTHROPIC_API_KEY`
and friends) is never forwarded unless allowlisted.

One `extra` channel carries app-owned, non-secret settings the supervisor itself
computes — currently only `HEPHAESTUS_AGENT_DIR`. It is applied last and never
read from the ambient environment, so it cannot smuggle a credential.

### `py.*` handlers run on a pool, never on the frame reader

A handler may issue **outbound** requests — a delegation prompts its child part
session over this same pipe — so running it inline on the reader thread would
block the only thread that can deliver its response.

The reader decodes and routes; `rpc.py_handler_workers` = 32 workers execute.
That is twice `admission.run_slots`, because a handler may nest one level.

When every worker is busy the request is refused with a named
`handler_overloaded` overload error **rather than queued behind the pipe**:
failing one tool call is strictly better than stalling every frame.

### Deadlines, and the credit that moves them

Each outbound request gets a monotonic id and a per-call deadline; the default is
`timeouts.tool_seconds`.

`timeouts.cad_build_seconds` is **not selectable here and never was**. Builds
travel sidecar-to-Python — the model calls the tool, the proxy issues
`py.tool_dispatch` — so the deadline that decides one is the sidecar's own RPC
peer default in `agent/src/rpc.ts` and `agent/src/tools/proxy.ts`, both of which
read the two classes off `schemas/bridge_limits.json`. A field on the supervisor
would be a correctly named field on the wrong object.

**Child-wait credit.** The supervisor tracks how long *it* has made the child
wait, and moves a pending call's effective deadline out by that amount:

```python
def _effective_deadline(self, call, credit):
    return call.deadline + max(0.0, credit - call.credit_at_send)
```

The credit closes on the transition to **zero in-flight handlers**, not per
handler, because the child waits *once* for a batch it issued in parallel.
Summing per handler would let a wedge be paid for with concurrency.

Without this, a sidecar blocked on a slow `py.tool_dispatch` would be judged
unresponsive for time the Python side itself consumed.

### The watchdog

A background thread kills the **whole** sidecar once a pending call passes its
effective deadline by `watchdog_grace_s` (5.0 s), polling every
`watchdog_interval_s`.

The order is fixed and observable: the set of tracked run ids goes to the
injected recovery hook **before** any terminal synthesis, and only then is the
child restarted.

### Bounded automatic respawn

An *unexpected* child exit — a crash, or a bridge torn down by an oversized
frame — no longer leaves the supervisor permanently childless waiting for a
watchdog that only fires while a call is pending.

| Setting | Default |
| --- | --- |
| `respawn_max_attempts` | 3 |
| `respawn_backoff_s` | 0.5 s, doubling per attempt |
| `respawn_backoff_max_s` | 5.0 s |
| `respawn_cooldown_s` | 30.0 s |

A child that survives the cooldown is deemed healthy and resets the attempt
counter, so a crash *loop* exhausts the budget and leaves the supervisor
**durably dead** with an error naming the attempt count, rather than thrashing
forever. A deliberate `close()` or `restart()` never triggers it.

The watchdog thread owns **every** automatic spawn, because `PR_SET_PDEATHSIG`
binds the child's life to the *thread* that forked it, and that thread lives as
long as the supervisor does.

### Re-configuration on every spawn

A fresh child is a blank runtime: it has never seen `runtime.configure`. A
post-spawn hook replays exactly the payload sent at start-up, and it fires for
*every* path that produces a child — initial start, explicit restart, and the
watchdog's own respawn.

Without it, a watchdog restart silently drops the provider configuration and
every later `session.create` / `session.prompt` fails with `runtime.configure has
not run yet`.

### Orphan-free

On Linux the child gets `PR_SET_PDEATHSIG=SIGKILL` so it dies with the
supervisor; an `atexit` hook and `close()` also kill it. **No sidecar survives
the supervisor.**

## The event pump

The pump consumes the sidecar's `event` and `terminal` notifications and does two
things.

### Events fan into per-client bounded queues

`events.buffered_events` = 1024 per client.

Explicitly **droppable** progress deltas coalesce to the latest per key
`(run_id, event_kind, tool_call_id)`. Never-dropped classes — audit, tool calls
and results, questions and answers, terminals — always append.

If the bounded queue still cannot make progress after coalescing, the affected
**run** is backpressure-cancelled and its final error routed through the terminal
channel.

That is the *durable* client policy. A non-durable observer — the browser's
WebSocket — is dropped instead, closing 4409 `resync_required`, because a stalled
tab must not kill an agent's work. See [the HTTP API](http-api.md).

### Terminals are durable before they are acknowledged

A `terminal` record is ingested into the opstore admission terminal channel in
**one transaction**, and only then is `terminal.ack` sent back naming the
terminal id.

Exactly one durable terminal per run; a duplicate terminal replays the same
durable state.

The pump is transport-agnostic: it calls injected callbacks to send `cancel` and
`terminal.ack`, so it composes with the real supervisor or a test double.

## Related

- The limits this page cites: [limits and configuration](limits-and-configuration.md).
- What a `py.tool_dispatch` resolves to: [agent tools](agent-tools.md).
- Working on the sidecar itself: [work on the sidecar](../03-how-to/work-on-the-sidecar.md).
