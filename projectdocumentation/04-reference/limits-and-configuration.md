# Limits and configuration

> **Verified against** `16f9613` on 2026-09-12.
> Values printed from `schemas/bridge_limits.json`; enforcement sites read in code.

## One file, both languages

`schemas/bridge_limits.json` is the single declaration of every numeric bound on
the agent bridge. Python reads it through `hephaestus.agent_bridge.limits`;
TypeScript reads the same file through `agent/src/limits.ts`. The file's own
preamble forbids duplicating a limit literal in code on either side.

The file is staged into the wheel at build time, so an installed package resolves
it without the repository. Resolution order:

1. `$HEPHAESTUS_BRIDGE_LIMITS` if set,
2. the packaged copy at `hephaestus/core/_data/bridge_limits.json`,
3. a walk up from the module to `schemas/bridge_limits.json`.

## The limits

27 numeric leaves. Values verified by printing the file.

### Wire and request size

| Key | Value | Enforced |
| --- | --- | --- |
| `wire.frame_version` | 1 | both sides; an unknown version fails closed |
| `wire.max_frame_bytes` | 67108864 | both sides, aborting an in-progress line before its newline |
| `http.max_request_bytes` | 1048576 | Python only; checked against `Content-Length` before any byte is read, then again mid-stream |

### JSON structure

| Key | Value | Note |
| --- | --- | --- |
| `json.max_depth` | 64 | |
| `json.max_members` | 10000 | |
| `json.max_array_items` | 10000 | |
| `json.max_string_bytes` | 16777216 | **per string**, key or value, not an aggregate |

### Binary and images

| Key | Value | Note |
| --- | --- | --- |
| `binary.max_binary_bytes` | 33554432 | the per-result aggregate across image blocks |
| `image.max_image_bytes` | 8388608 | one image |
| `image.max_width` / `max_height` | 4096 | checked from the header before decode |
| `image.max_total_pixels` | 33554432 | |
| `image.max_images_per_result` | 4 | also a schema `maxItems` |

### Concurrency

| Key | Value | Note |
| --- | --- | --- |
| `rpc.max_pending` | 64 | TypeScript only |
| `rpc.py_handler_workers` | 32 | Python only; twice the run slots, because a handler may nest one level |
| `admission.run_slots` | 16 | Python only |
| `events.buffered_events` | 1024 | both sides |

### Timeouts

| Key | Value | Bounds |
| --- | --- | --- |
| `timeouts.tool_seconds` | 120 | one tool call |
| `timeouts.turn_seconds` | 600 | one model turn |
| `timeouts.cad_build_seconds` | 300 | one build, on the side a build actually crosses |
| `timeouts.delegation.deadline_default_seconds` | 600 | a delegated child |
| `timeouts.delegation.deadline_min_seconds` | 1 | |
| `timeouts.delegation.deadline_max_seconds` | 1200 | |
| `timeouts.delegation.grace_seconds` | 60 | the sidecar's margin over the child's deadline |

**A turn is not a tool.** These three numbers are deliberately different classes.
A turn runs a model round trip plus every tool the model asks for, one of which
may be a build; bounding a turn by the tool number made the watchdog kill the
whole sidecar over latency that was never a fault.

### Prompt and text

| Key | Value |
| --- | --- |
| `prompt.max_utf8_bytes` | 32768 |
| `text_result.max_bytes` | 51200 |
| `text_result.max_lines` | 2000 |

### The census test

`tests/stage2/test_bridge_bounds_limits.py` asserts three things, and the second
is the one that catches drift: every declared limit has a boundary test, **every
boundary test names a limit that still exists**, and the reviewed
deliberately-unenforced list is empty. A renamed or deleted key fails the suite.

## Limits declared outside that file

Two numbers are not in the limits document and are worth knowing:

| Name | Value | Where |
| --- | --- | --- |
| `MAX_REPAIR_ROUNDS` | 2 | a TypeScript literal in the CAD workflow |
| `MAX_PARTS` | 8 | the same file |

## Engine ceilings and their environment overrides

These live in the engine rather than the bridge. Each falls back to its default
on an unparseable or non-positive value.

| Constant | Default | Override |
| --- | --- | --- |
| solve wall clock | 60 s | `HEPHAESTUS_SOLVE_TIMEOUT_S` |
| solve iterations | 200 | `HEPHAESTUS_SOLVE_ITER_MAX` |
| verification pass | 300 s | `HEPHAESTUS_VERIFY_TIMEOUT_S` |
| parameter-solve build budget | 240 builds | `HEPHAESTUS_SOLVE_BUILD_BUDGET` |
| solid diff | 300 s | `HEPHAESTUS_COMPARE_TIMEOUT_S` |
| scan distance | 300 s | `HEPHAESTUS_SCAN_TIMEOUT_S` |
| motion sweep | 300 s | `HEPHAESTUS_MOTION_TIMEOUT_S` |
| mesh sew | 120 s | `HEPHAESTUS_MESH_SEW_TIMEOUT_S` |
| mesh import size | 512 MiB | `HEPHAESTUS_MESH_MAX_BYTES` |
| mesh triangles | 20000000 | `HEPHAESTUS_MESH_MAX_TRIANGLES` |
| mesh points | 50000000 | `HEPHAESTUS_MESH_MAX_POINTS` |

The solve wall clock is a **production** bound. A suite that needs longer
declares its own budget rather than inheriting it; the stage-13C suite does
exactly that, because on a battery-throttled CPU the same solve takes four times
as long and the ceiling is not what that suite is testing.

## Sandbox resource limits

Applied to the build worker in a pre-exec hook and inherited through bubblewrap:

| Limit | Value |
| --- | --- |
| CPU seconds | 120 |
| address space and data | 6 GiB |
| processes | 4096 |
| core dumps | 0 |

The CPU limit is stricter than the 300 second wall clock, so a compute-bound
build is stopped by the CPU rlimit first. The process limit must exceed the
invoking user's live kernel task count or the user namespace clone fails.

## Store configuration

| Field | Default | Effect |
| --- | --- | --- |
| `run_slots` | 16 | admission budget |
| `idempotency_window_s` | 30 days | a first-seen key older than this is expired |
| `tombstone_margin_s` | 7 days | added to the window for the recognised horizon |
| `freshness_skew_s` | 300 s | a first-seen key further than this from the clock is refused |
| `quota_bytes` | 10 GiB | protected-bytes ceiling |
| `retention_s` | 30 days | default retention class |
| `preview_retention_s` | 7 days | preview class |
| `key_retirement_retention_s` | 37 days | retired signing keys stay verifiable |

## Environment variables

| Variable | Effect |
| --- | --- |
| `HEPHAESTUS_BRIDGE_LIMITS` | path to an alternate limits document |
| `HEPHAESTUS_AGENT_PROVIDERS` | path to a provider config |
| `HEPHAESTUS_AGENT_DIR` | the sidecar's credential directory |
| `HEPHAESTUS_NODE` | the Node binary to use |
| `HEPHAESTUS_PNPM` | the pnpm invocation to use |
| `HEPHAESTUS_SIDECAR` | an explicit staged sidecar path |
| `HEPHAESTUS_REQUIRE_SIDECAR` | turn "no toolchain" from a skip into a named failure |
| `HEPHAESTUS_SKIP_SIDECAR_BUILD` | reuse the staged sidecar; refuses when the stage is stale |
| `HEPHAESTUS_WHEELHOUSE` | wheel directory for the packaging lanes |
| `HEPH_EGL_DEVICE` | override the EGL device chosen for rendering |
| `HEPH_WEB_API` | the API the web dev server proxies to |
| `OPSTORE_CRASH_POINT` | inject a crash at a named point; test-only |

The engine ceilings above add their own variables; the store reads exactly one.

## Project configuration

`hephaestus.toml` at the project root:

```toml
[project]
name = "bracket"
units = "mm"

[params]
# project-scope parameter values

[dfm]
auto_run = false
```

`name` is required and non-empty. `units` defaults to `mm`. `[params]` holds
plain numbers; booleans are rejected. `name` and `units` may also appear at the
top level, in which case the top level wins.
