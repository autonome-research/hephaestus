# Spike E — Python↔Node JSON-RPC-over-stdio bridge fixture

Status: **pass** — 12/12 pytest tests green on two consecutive runs (2.79s,
2.76s), pytest exit code 0, post-suite `pgrep` orphan sweep clean.

## What was proven

Mission plan Stage S item (e), first half: a supervised Python↔Node bridge
with the architecture.md §5 concepts at spike scale (1 MiB frame cap standing
in for the contractual 64 MiB):

| Concept | Evidence (test) |
|---|---|
| Tool-call round trip + correlation | `test_round_trip_and_spontaneous_events`, `test_concurrent_calls_correlate_correctly` (20 interleaved calls, per-caller payload check) |
| Bounded framing, supervisor→sidecar | `test_oversized_frame_rejected_by_sidecar`: 1.2 MiB frame ⇒ structured `-32001` id-null error from the sidecar's incremental framer; sidecar stays alive and resynchronizes |
| Bounded framing, local outbound guard | `test_oversized_frame_rejected_by_supervisor_outbound_guard`: frame never written to the pipe |
| Bounded framing, sidecar→supervisor | `test_oversized_frame_rejected_inbound`: `big` (1.5 MiB) discarded by the Python incremental framer ⇒ structured `frame_too_large_inbound`; bridge stays healthy |
| Per-call timeout | `test_per_call_timeout`: 0.4 s timeout on a 5 s call returns structured `timeout` in <2 s, then cancels sidecar-side |
| Bounded pending queue ⇒ `busy` | `test_pending_queue_overflow_returns_busy`: max_pending=3, 4th call returns structured `busy`; admitted calls complete; capacity released |
| Cancellation observed by sidecar | `test_cancellation_observed_by_sidecar`: `$/cancel` notification ⇒ `-32800` response + spontaneous `cancelled` event |
| `ask_user` suspension/resume | `test_ask_user_suspension_and_resume`: suspension marker with `question_id`, follow-up `answer` completes, double-answer rejected |
| Image payload | `test_image_payload_round_trip`: base64 decodes, `\x89PNG\r\n\x1a\n` magic verified |
| Crash reporting + restart | `test_crash_reporting_and_restart_recovery`: SIGKILL mid-call ⇒ structured `process_crash` with `returncode=-9`, fast-fail `process_down` while down, reaped (no zombie), restart with new pid, echo recovers |
| Clean shutdown, no orphans | `test_clean_shutdown_leaves_no_orphan` + every test's teardown asserts `ps` shows the pid gone and `pgrep -f node_sidecar.mjs` finds nothing |

## Versions (out/versions.log)

- Node v25.2.1, uv 0.11.3, Python 3.13.12 (pinned via `.python-version`),
  pytest 9.1.1. Isolated uv project (`spikes/bridge/pyproject.toml` +
  `uv.lock`); nothing installed into the workspace root environment.

## How to run

```
spikes/bridge/run.sh        # logs to spikes/bridge/out/{versions,pytest,orphans}.log
```

## Files

- `node_sidecar.mjs` — sidecar: LF-delimited JSON-RPC, incremental framer with
  1 MiB guard, methods `echo`/`slow`/`ask_user`+`answer`/`image`/`big`,
  `$/cancel` notification handling, spontaneous `event` notifications
  (`ready`, `tick`, `cancelled`, `ask_user_completed`); logs only to stderr.
- `supervisor.py` — spawn/supervise, id correlation, per-call timeouts,
  bounded pending queue, both-direction size guards, cancel, crash fail-fast +
  restart, clean shutdown, `ps`/`pgrep` orphan helpers.
- `test_bridge.py` — the 12 scenarios above.

## Deliberate spike-scale simplifications (not architecture deviations)

- 1 MiB cap vs the contractual 64 MiB; no JSON depth/member caps, image pixel
  budgets, run-slot admission, or terminal channel — those are Stage 2+ scope.
- An inbound oversized frame cannot be correlated (it is discarded unparsed),
  so the supervisor fails the *oldest* pending call; the production bridge
  ties this to run-scoped teardown instead.
- Sidecar id-null protocol errors are routed to the oldest pending call that
  bypassed the local size guard (only such calls can trigger them here).
- The second half of Stage S item (e) — thread-phase phase calling a pre-built
  Pi session with durable JobRunner events — is out of scope for this fixture
  (covered by the agent_runtime spike track).
