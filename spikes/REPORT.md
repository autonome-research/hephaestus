# Stage S De-risking Spike Report — Hephaestus

Date: 2026-07-24
Scope: Synthesis of the five Stage S spikes (cad_kernel, mcp_elicitation, agent_runtime, sandbox, bridge) for Gate GS review. Evidence file existence was verified on disk on the report date; all 57 claimed evidence paths exist (zero missing).

## Summary table

| Spike | Status | One-line verdict |
|---|---|---|
| cad_kernel | PASS | build123d 0.11.1 / OCCT 7.9.3 deterministic (STL raw bytes; STEP after header normalization); headless render byte-stable only via Mesa llvmpipe EGL; OCCT sanity 0.9 s vs 600 s budget |
| mcp_elicitation | PASS | fastmcp 3.4.4 + mcp 1.28.1 mid-call elicitation proven end-to-end on stdio AND streamable HTTP (protocol 2025-11-25); no ask_user fallback needed |
| agent_runtime | PASS | pi-coding-agent 0.80.10 + thread-phase 6.0.0 on Node 25 / pnpm: no native better-sqlite3; custom tools, resume, compact, cancel, JobRunner with injected JobStore all proven; use /session + /patterns subpath imports |
| sandbox | PASS | bubblewrap 0.11.2 containment green on all 14 probes (net, fs, pid, env, traversal) with rlimit/wall-clock kills, fail-closed detection, and Docker parity |
| bridge | PASS | Python-Node LF-JSON-RPC sidecar: 12/12 scenarios green twice (timeouts, size caps both directions, cancel, ask_user suspension, crash+restart, 20 concurrent calls, no orphans) |

**Overall: GREEN.** All five spikes pass. No Gate GS fallback path (alternative CAD kernel, elicitation workaround, native-sqlite replacement, Docker-only sandbox, or alternative IPC) needs to be taken. Several dispositions (not fallbacks) must be recorded at Gate GS — see "Fallback decisions and Gate GS dispositions" at the end.

---

## 1. cad_kernel — PASS

**What was proven**

- **Determinism:** Two separate-process builds of the parametric box (80x60x30 mm, R4 fillets, D12 hole) produced identical sha256 for 9-decimal metrics (volume/area/bbox) and byte-identical binary STL. Raw STEP bytes differ only in the FILE_NAME header timestamp; after normalizing that single header line (`box_build.py::normalize_step`) the STEP body is byte-identical (`out/step_diff.log` shows exactly one differing line).
- **Headless rendering:** pyrender + EGL works headless. Default EGL selects the NVIDIA GPU and is NOT reliably byte-stable (one pair differed by 2 pixels, off-by-one). Forcing the Mesa llvmpipe software device (`PYOPENGL_PLATFORM=egl` + `EGL_DEVICE_ID`, LLVM 22.1.5) yields byte-identical 640x480 PNGs across processes, SSIM 1.0. **CI renderer choice: EGL surfaceless + llvmpipe**, with matplotlib-Agg 3D as a proven byte-identical fallback. osmesa is unavailable on this host (no libOSMesa) and unnecessary.
- **OCCT sanity (0.9 s compute / 3.2 s process, of the 600 s budget):** oversized R1000 fillet fails as required (build123d ValueError; raw OCP `StdFail_NotDone` "BRep_API: command not done", 0.01 s); sequential boolean union of 30 overlapping boxes -> 1 solid in 0.77 s; STEP round-trip of a nontrivial part -> equal solid count, volume rel diff 4.8e-15 (budget 1e-3), export 0.010 s / import 0.017 s — 1-3 orders of magnitude inside the verification.md <= 30 s shelf.

**Versions:** Python 3.13.12 (CPython, uv-managed), build123d 0.11.1, cadquery-ocp-novtk 7.9.3.1.1 (via cadquery-ocp-proxy 7.9.3.1.1), OCCT 7.9.3 (`OCP.__version__ == 7.9.3.1`), trimesh 4.12.2, pyrender 0.1.45, pyopengl 3.1.0, matplotlib 3.11.1, scikit-image 0.26.0, numpy 2.5.1, Mesa llvmpipe LLVM 22.1.5.

**Evidence (all verified present):** `spikes/cad_kernel/box_build.py`, `run_determinism.sh`, `render_box.py`, `run_render_determinism.sh`, `occt_sanity.py`, `run_all.sh`, `requirements.in`, `requirements.lock.txt`, `RESULTS.md`, `out/run_all.log`, `out/determinism_summary.log`, `out/render_summary.log`, `out/occt_sanity.log`, `out/step_diff.log`.

**Caveats**

- STEP export is not raw-byte-identical (FILE_NAME timestamp). **Decision:** hash STL raw; hash STEP through the header normalizer. Normalized bodies are byte-identical.
- osmesa untested (libOSMesa absent); the CI image must ship Mesa with the surfaceless EGL platform.
- GPU EGL is not byte-stable and `LIBGL_ALWAYS_SOFTWARE=1` does NOT prevent NVIDIA EGL selection — the software device must be pinned via `EGL_DEVICE_ID` (device 1 on this host; device 0 on GPU-less CI).
- `cadquery-ocp` proper was not installed; build123d resolves to cadquery-ocp-proxy -> cadquery-ocp-novtk (same OCP bindings, VTK-free). `OCP.Standard.Standard_Version` is absent in this distribution, so OCCT version is evidenced via `OCP.__version__` and the STEP header "Open CASCADE STEP processor 7.9".
- Spike is a standalone uv venv + `requirements.lock.txt`; a transient `uv init` workspace-member addition to root `pyproject.toml` was reverted. Files were left uncommitted for the orchestrator; `out/` logs are gitignored (`spikes/**/out/`).

---

## 2. mcp_elicitation — PASS

**What was proven**

- MCP mid-call elicitation works end-to-end on **both** stdio and streamable HTTP (`http://127.0.0.1:8765/mcp`) with fastmcp 3.4.4 server + pure official mcp-SDK 1.28.1 client (ClientSession with an elicitation_callback, no FastMCP client code), negotiated protocol 2025-11-25.
- `echo_server.py` exposes `echo` and an `ask` tool using `ctx.elicit` with a dataclass response_type `{name: str, quantity: int}`. `scripted_client.py` answered the mid-call `elicitation/create` programmatically with `ElicitResult(action='accept', content={'name':'widget','quantity':7})`.
- Assertions: elicitation message arrived verbatim; `requestedSchema.properties` round-tripped as exactly `['name','quantity']`; answer round-tripped into the tool result as `answered:bracket:name=widget:quantity=7`; `echo` returned `echo:hello-spike`. Both transports exited 0 (ask latency ~0.005 s stdio, ~0.008 s HTTP); two consecutive full `run_all.sh` runs exited 0.
- **Consequence: no fallback design is needed for tool_schema.md `ask_user`.**

**Versions:** Python 3.13.12, fastmcp 3.4.4, mcp 1.28.1, pydantic 2.13.4, uvicorn 0.51.0, httpx 0.28.1, MCP protocol 2025-11-25.

**Evidence (all verified present):** `spikes/mcp_elicitation/echo_server.py`, `scripted_client.py`, `run_all.sh`, `RESULTS.md`, `pyproject.toml`, `uv.lock`, `out/versions.log`, `out/stdio.log`, `out/http.log`, `out/run2_summary.log`.

**Caveats**

- Only the **accept** path was exercised; decline/cancel are handled by the server code but not client-asserted — Stage 3 must add those cases.
- Only dataclass (structured object) response_type proven; option-list/scalar elicitation forms not exercised (not needed for ask_user's shape).
- Standalone uv project with exact `==` pins; a transient root-workspace registration by `uv init` was fully reverted (root pyproject.toml/uv.lock verified to contain zero spike/fastmcp references). `out/` logs gitignored; scripts uncommitted pending orchestrator.

---

## 3. agent_runtime — PASS

**What was proven**

- Exact-pinned `@earendil-works/pi-coding-agent@0.80.10` (engines node>=22.19.0) and `@autonome-research/thread-phase@6.0.0` (engines node>=22.5.0) install under pnpm 10.6.5 / Node v25.2.1 in ~6 s with no required install scripts.
- **Native audit:** better-sqlite3 is completely absent — `SqliteJobStore` runs on builtin `node:sqlite` via an internal driver that documents the migration. The only `.node` files are Pi-side prebuilds (pi-tui darwin/win32, clipboard linux) and none load at runtime.
- **Import hygiene:** the thread-phase root barrel eagerly loads the openai SDK (513 modules, inert at import time); the `/session` (JobRunner/JobStore) and `/patterns` (free-runner) subpaths load 13 modules with zero openai and zero native addons. **Disposition: import subpaths in production.**
- **Runtime proofs (all exit 0):** Pi session with only a custom `heph_fake` tool (tools allowlist) against a ~40-line local fake OpenAI-compatible SSE server via `ModelRuntime.registerProvider({baseUrl, api:"openai-completions"})` — tool executed with streamed args, `text_delta`/`tool_execution` events streamed, 7-entry JSONL session persisted in an app-owned sessionDir and resumed via `SessionManager.continueRecent`; `compact()` returned a real summary (10->3 messages); `abort()` cancelled a stalled stream in ~500 ms; JobRunner with an injected custom fully-async in-memory JobStore reached COMPLETED with 5 durable + 5 live events, and a second job was cancelled to terminal CANCELLED.
- Full API enumerations for both packages (session creation, provider config, custom tools, tool disabling, events, compaction, cancel, resume; JobRunner/JobStore/phases/patterns; AgentAdapter not required) are in `spikes/agent_runtime/RESULTS.md` with cited export names. Committed as `d8790aa`.

**Versions:** Node v25.2.1, pnpm 10.6.5, @earendil-works/pi-coding-agent 0.80.10, @autonome-research/thread-phase 6.0.0, typebox 1.1.38, openai 6.49.0 (via thread-phase) / 6.26.0 (via pi-ai), @earendil-works/pi-ai 0.80.10, @earendil-works/pi-agent-core 0.80.10.

**Evidence (all verified present):** `spikes/agent_runtime/RESULTS.md`, `package.json`, `pnpm-lock.yaml`, `trace_imports.mjs`, `fake_openai_server.mjs`, `pi_session_proof.mjs`, `pi_compact_cancel_proof.mjs`, `threadphase_jobrunner_proof.mjs`, `out/00_versions_engines.log` through `out/08_threadphase_jobrunner.log` (9 logs).

**Caveats**

- Root-barrel import pulls openai eagerly; **record the /session + /patterns subpath-import disposition in repo_conventions.md at Gate GS.**
- Pi's `noTools:"all"` strips custom tools too; use the `tools:[...]` allowlist or `noTools:"builtin"` to disable only built-in coding tools.
- `node:sqlite` emits an ExperimentalWarning when `/session` is imported (cosmetic; builtin module; moot with an injected JobStore).
- `compact()` rejects small sessions ("Nothing to compact") under default `keepRecentTokens=20000`; the proof shrank the window via `SettingsManager.inMemory`.
- JobRunner live events are emitted on per-job channel `job:<id>`, not a global "event" channel.
- `out/` logs are gitignored by design; re-run the four scripts to regenerate.

---

## 4. sandbox — PASS

**What was proven**

- **bubblewrap lane:** `sandbox_runner.py` launches a child CPython 3.13.12 under bwrap with read-only `/project` bind, tmpfs `/tmp` and `/run`, private `/proc` + `/dev`, `--unshare-net/-pid/-user/-ipc/-uts`, `--clearenv`, and `--remount-ro /` to seal the base tmpfs; exact 40-token argv captured verbatim in `out/bwrap_argv.txt`.
- **All 14 probes behave as required:** read `/etc/shadow` (ENOENT); writes into `/project/`, `/`, `/etc`, `/home` (EROFS/ENOENT); TCP to 1.1.1.1:443 (ENETUNREACH) and to a live host loopback listener (ECONNREFUSED — proves netns isolation); `../` traversal and symlink-to-`/home` escape (ENOENT); `os.kill` of a real host pid (ESRCH); host-env leak via `/usr/bin/env` (sentinel HEPH_SANDBOX_SENTINEL absent) — all BLOCK; legit sha256 compute + `/tmp` write and project-file read SUCCEED.
- **Resource limits:** infinite loop SIGKILL'd via process group at wall_seconds=3.003 (returncode -9); 2 GiB allocation under 256 MiB RLIMIT_AS/RLIMIT_DATA raises MemoryError (killed=true).
- **Fail-closed detection:** `detect_capability` returns usable=true only after a live sandboxed run confirms network and `/etc/shadow` actually block; with `PATH=/nonexistent-dir-only` it returns usable=false, reason "bwrap not on PATH".
- **Docker parity** on `python:3.13-slim` with `--network none --read-only --tmpfs /tmp --memory 256m`: all host-escape probes block (host_containment_ok=true); 2 GiB alloc OOM-killed (exit 137); infinite loop killed (exit 137). Four probes that "pass" reads in Docker touch only the container's own ephemeral rootfs (its own /etc/shadow, empty /home), not host files, and are split out as `container_internal_reads`, excluded from containment scoring.

**Versions:** Linux 7.0.9-arch2-1 x86_64, bubblewrap 0.11.2, sandboxed Python 3.13.12 (uv relocated CPython), runner venv 3.13.12, Docker 29.5.1, image `python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91` (internal Python 3.13.14).

**Evidence (all verified present):** `spikes/sandbox/sandbox_runner.py`, `probes.py`, `run_spike.py`, `docker_parity.sh`, `RESULTS.md`.

**Caveats**

- Ran on the local Arch host, NOT the actual CI/release image (that image does not exist yet at Stage S); argv and probe logic are image-agnostic and ready to re-run inside it.
- seccomp intentionally out of scope per the task; containment relies on namespaces + read-only mounts + rlimits, not syscall filtering.
- Memory cap via RLIMIT_AS surfaces as a graceful MemoryError in Python; Docker's cgroup cap hard-kills (exit 137). Both terminate the over-allocation, by different mechanisms.
- Transient root workspace-member addition by `uv init` was reverted (member line removed, root uv.lock re-locked to 0 sandbox refs). Root *.md files untouched.
- Docker parity needs network to pull the image on first run (cached thereafter). `out/` logs gitignored; regenerate via `.venv/bin/python run_spike.py` and `./docker_parity.sh`.

---

## 5. bridge — PASS

**What was proven**

- **Fixture:** `node_sidecar.mjs` (LF-delimited JSON-RPC with an incremental framer enforcing a 1 MiB frame cap, methods echo/slow/ask_user+answer/image/big, `$/cancel` handling, spontaneous event notifications, stderr-only logging) and `supervisor.py` (spawn/supervise, id correlation, per-call timeouts, bounded pending queue returning structured busy, both-direction size guards, cancellation, crash fail-fast plus restart, clean shutdown, ps/pgrep orphan helpers).
- **12/12 scenarios green on two consecutive runs** (2.79 s and 2.76 s, pytest exit 0): round trip; oversized frames both directions (1.2 MiB outbound rejected by sidecar with structured -32001 without crashing; 1.5 MiB inbound discarded by the Python framer with structured `frame_too_large_inbound`; bridge healthy after both); 0.4 s timeout on a 5 s call; queue overflow at max_pending=3 returning busy then draining; `$/cancel` observed by the sidecar (-32800 response plus cancelled event); ask_user suspension marker and answer completion with double-answer rejection; base64 PNG magic verification; SIGKILL mid-call surfacing process_crash returncode=-9 then restart with a new pid and successful echo; 20 interleaved concurrent calls correlating correctly.
- Per-test teardown asserts via `ps` that the sidecar pid is gone and `pgrep -f` finds no orphan, plus a post-suite orphan sweep. Committed as `cddb8fb` on main.

**Versions:** Node v25.2.1 (system binary), Python 3.13.12 (pinned via `.python-version`), uv 0.11.3, pytest 9.1.1, pluggy 1.6.0.

**Evidence (all verified present):** `spikes/bridge/node_sidecar.mjs`, `supervisor.py`, `test_bridge.py`, `run.sh`, `RESULTS.md`, `pyproject.toml`, `uv.lock`, `.python-version`, `out/pytest.log`, `out/versions.log`, `out/orphans.log` (out/ gitignored).

**Caveats**

- 1 MiB frame cap stands in for the contractual 64 MiB in architecture.md S5; JSON depth/member caps, image pixel budgets, run-slot admission, and the terminal channel are Stage 2+ scope, deliberately absent.
- An inbound oversized frame cannot be correlated (discarded unparsed), so the supervisor fails the oldest pending call; production must tie this to run-scoped teardown (documented in RESULTS.md).
- Sidecar id-null protocol errors are routed to the oldest pending call that bypassed the local outbound size guard (sound here because only such calls can trigger them).
- The thread-phase-phase-calling-Pi half of mission_plan Stage S item (e) was covered by the agent_runtime spike, not this fixture.
- Node was the system v25.2.1 binary, not project-pinned; Gate GS version pinning into repo_conventions.md remains a separate orchestrator step.

---

## Evidence verification

Every evidence file listed by every spike (57 paths total, including gitignored `out/` logs) was checked with `ls` on 2026-07-24: **all present, none missing.** Note that `spikes/**/out/` is gitignored by the root `.gitignore`, so those logs exist on this host only and must be regenerated from the committed scripts elsewhere. agent_runtime (`d8790aa`) and bridge (`cddb8fb`) are committed; cad_kernel, mcp_elicitation, and sandbox source files are in the working tree awaiting the orchestrator's commit.

## Fallback decisions and Gate GS dispositions

**Gate GS fallback paths required: none.** Specifically:

1. **MCP elicitation is adequate** on both transports — the ask_user fallback design contemplated by mission_plan.md is NOT needed.
2. **STEP determinism** — raw STEP bytes are NOT deterministic (FILE_NAME timestamp), but this does not trigger a kernel fallback. Accepted disposition: hash STL raw bytes; hash STEP through the one-line header normalizer (`box_build.py::normalize_step`), under which output is byte-identical.
3. **CI render backend chosen:** pyrender + EGL surfaceless pinned to Mesa llvmpipe via `EGL_DEVICE_ID` (never GPU EGL; do not rely on `LIBGL_ALWAYS_SOFTWARE`); matplotlib-Agg 3D retained as proven byte-identical fallback. CI image must ship Mesa with surfaceless EGL.
4. **thread-phase imports:** production code must import `/session` and `/patterns` subpaths only (openai-free, native-free); record in repo_conventions.md at Gate GS (orchestrator action — not done here by design).
5. **Pi tool gating:** use `tools:[...]` allowlist or `noTools:"builtin"`; `noTools:"all"` strips custom tools.
6. **Sandbox:** bubblewrap is the primary lane with fail-closed capability detection; Docker parity confirmed as the portability lane. Re-run probes inside the eventual CI/release image.

**Accepted version set (to pin at Gate GS):** Python 3.13.12 (uv), Node v25.2.1 (needs project pinning), pnpm 10.6.5, uv 0.11.3, build123d 0.11.1, cadquery-ocp-novtk/proxy 7.9.3.1.1 (OCCT 7.9.3), trimesh 4.12.2, pyrender 0.1.45 + Mesa llvmpipe (LLVM 22.1.5) surfaceless EGL, fastmcp 3.4.4, mcp 1.28.1 (protocol 2025-11-25), @earendil-works/pi-coding-agent 0.80.10, @autonome-research/thread-phase 6.0.0, bubblewrap 0.11.2, pytest 9.1.1.

**Follow-ups carried forward (not blockers):** elicitation decline/cancel assertions (Stage 3); 64 MiB frame cap + depth/member caps + run-slot admission (Stage 2+); re-run sandbox probes in the real CI image; ship Mesa surfaceless EGL in the CI image; commit the three uncommitted spikes.
