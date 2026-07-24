# Spike D+G — pinned Pi SDK + thread-phase audit

Status: **pass**. All claims below are backed by scripts in this directory and
logs under `out/` (gitignored; re-run the scripts to regenerate).

## 1. Pinning and engines (`out/00_versions_engines.log`, `out/01_pnpm_install.log`)

| Component | Version | Engines declared |
|---|---|---|
| `@earendil-works/pi-coding-agent` | **0.80.10** (exact pin) | `node >=22.19.0` |
| `@autonome-research/thread-phase` | **6.0.0** (exact pin) | `node >=22.5.0` |
| `typebox` (tool-schema helper, matches Pi's own dep) | 1.1.38 | none |
| Node | v25.2.1 (satisfies both; repo target >=22.19 also satisfies both) | — |
| pnpm | 10.6.5 | — |

`pnpm install` succeeded in ~6 s, 134 packages. pnpm ignored build scripts for
`@google/genai` and `protobufjs` (the only package with a postinstall script is
`protobufjs@7.6.5`, via Pi → pi-ai → @google/genai) and everything still works,
i.e. no required install script.

## 2a. Native addons / better-sqlite3 (`out/02_native_audit.log`, `out/03_deps_audit.log`)

- **`better-sqlite3` is completely absent** — not in the lockfile, not in any
  `package.json` in the tree (`pnpm why better-sqlite3` empty; `grep -c` in
  lockfile = 0). thread-phase 6.0.0's `SqliteJobStore` is built on the Node
  **builtin `node:sqlite`** (`DatabaseSync`) via an internal `SqliteDriver`
  whose header comment explicitly documents the better-sqlite3 → node:sqlite
  migration. Native-free requirement: **met**.
- `.node` files present in the tree (all Pi-side, none loaded at runtime in
  our proofs):
  - `@earendil-works/pi-tui` prebuilds for darwin/win32 only (TUI key handling)
  - `@mariozechner/clipboard-linux-x64-gnu` (prebuilt clipboard helper,
    dependency of pi-coding-agent). No compile-on-install anywhere (no
    `binding.gyp` in the tree).
- Runtime check: neither the thread-phase `/session` free-runner path nor the
  full Pi SDK session proof loaded any `.node` file (asserted in
  `threadphase_jobrunner_proof.mjs`; `trace_imports.mjs` shows
  `nativeAddonsLoaded: []` for every thread-phase entry point).

## 2b. Transitive `openai` SDK (`out/03_deps_audit.log`, `out/05_threadphase_import_trace.log`)

`openai` is **present** twice: `6.49.0` as a direct dependency of thread-phase
and `6.26.0` under `@earendil-works/pi-ai`. Import-trace results
(`trace_imports.mjs`, module resolve hooks):

| Import path | modules loaded | openai modules | disposition |
|---|---|---|---|
| `@autonome-research/thread-phase` (root barrel) | 724 | **513 loaded** | present-and-loaded (via `createInferenceClient` / `runAgentWithTools` re-exports; inert — nothing instantiated, no network at import) |
| `@autonome-research/thread-phase/session` (JobRunner/JobStore) | 13 | **0** | absent from load graph |
| `@autonome-research/thread-phase/patterns` (free-runner patterns) | 13 | **0** | absent |
| `@autonome-research/thread-phase/tools` | 166 | 0 | absent |

**Disposition for Gate GS:** production code should import from the
`/session` and `/patterns` subpaths (both openai-free and native-free); the
root barrel eagerly loads the openai SDK and should be avoided in the sidecar.
`runPipeline`/`Phase` are only re-exported from the root barrel, but
`JobRunner.start(jobId, phases, ctx)` executes phases directly from `/session`
without touching the orchestrator's root export (proven at runtime, 13 modules
total).

## 2c. Pi SDK public API surface (from `dist/index.d.ts`, `docs/sdk.md`, `examples/sdk/`)

All names below are actual exports of `@earendil-works/pi-coding-agent@0.80.10`:

- **Session creation:** `createAgentSession(options) → { session: AgentSession }`;
  full-control variants `createAgentSessionServices` /
  `createAgentSessionFromServices` / `createAgentSessionRuntime`
  (`AgentSessionRuntime` owns `newSession()/switchSession()/fork()/importFromJsonl()`).
- **ModelRuntime / provider config:** `ModelRuntime.create({ authPath,
  modelsPath, modelsStorePath, allowModelNetwork, catalogBaseUrl })` +
  `modelRuntime.registerProvider(id, ProviderConfigInput)` where
  `ProviderConfigInput = { baseUrl, apiKey, api, headers, models[], … }` and
  `api` includes `"openai-completions"` (pi-ai `KnownApi`). **Arbitrary
  OpenAI-compatible baseURL incl. local http endpoints: yes, proven** —
  no extension file needed, fully programmatic, and `authPath`/`agentDir`
  overrides sandbox away ambient `~/.pi` credentials/resources.
- **Custom tools:** `defineTool({ name, label, description, parameters:
  TypeBox schema, execute(toolCallId, params, signal, onUpdate, ctx) })`
  passed via `CreateAgentSessionOptions.customTools`; execute returns
  `AgentToolResult { content: (Text|Image)[], details }`.
- **Disabling built-in coding tools:** `tools: string[]` allowlist,
  `noTools: "all" | "builtin"`, `excludeTools: string[]`. Caveat found at
  runtime: `noTools: "all"` empties **custom** tools too — use the
  `tools: ["heph_fake"]` allowlist (or `noTools: "builtin"`).
- **Event streaming:** `session.subscribe(listener)` with `AgentSessionEvent`
  union: `message_update` (`text_delta`/`thinking_delta`),
  `tool_execution_start/update/end`, `message_start/end`, `agent_start/end`,
  `turn_start/end`, `queue_update`, `compaction_start/end`,
  `auto_retry_start/end`.
- **Compaction:** `session.compact(customInstructions) → CompactionResult
  { summary, firstKeptEntryId, tokensBefore, estimatedTokensAfter }`,
  `session.abortCompaction()`; standalone `compact`/`shouldCompact`/
  `findCutPoint`/`DEFAULT_COMPACTION_SETTINGS` also exported.
- **Cancel:** `session.abort()`; per-tool `AbortSignal` in `execute`.
- **Session resume from a directory:** `SessionManager.create(cwd, sessionDir)`,
  `SessionManager.open(path)`, `SessionManager.continueRecent(cwd, sessionDir)`,
  `SessionManager.list/listAll`, `SessionManager.inMemory()`; JSONL session
  files (`CURRENT_SESSION_VERSION`, `parseSessionEntries`, `migrateSessionEntries`).

## 2d. thread-phase public API (from `dist/index.d.ts` + subpath typings)

- **JobRunner** (`/session`): `new JobRunner(store: JobStore, { heartbeatMs })`;
  `create`, `start → JobRunHandle { jobId, signal, result, cancel() }`, `run`,
  `cancel`, `heartbeat`, `reconcileAbandoned(staleAfterMs)`; live events on
  EventEmitter channel `job:<id>`.
- **JobStore**: v3 interface is **fully async (every method returns a
  Promise)** and injectable — the doc comment states sqlite is just the
  bundled default and other backends "just need to implement this interface".
  19 methods incl. `createJob`, `acquireExclusive`, `setRunning`,
  `setCompleted/Failed/Cancelled/Abandoned`, `setAbandonedIfStale`,
  `finalizeJob`, `appendEvent`, `getEvents(afterId)` (resume cursor),
  `heartbeat`, `close`. A custom in-memory async store was injected and
  exercised end-to-end (see 3b). This is the seam for the mission's
  Python-SQLite bridge store.
- **Free-runner phase/pattern APIs:** `Phase { name, checkpointKey?,
  run(ctx): AsyncGenerator<PipelineEvent> }`, `runPipeline`,
  `runPipelineToSummary`, `completedCheckpointsFromEvents`, `requireCtx`;
  `/patterns`: `parallelPhases`, `boundedFanout(-Of)`, `intentGate`, `match`,
  `whileCondition`, `withRetry`, `subPipeline`.
- **AgentAdapter surface:** lives in the separate `./agents` +
  `./agents/authoring` subpaths and is **not required** — nothing in
  `/session` or `/patterns` imports it (13-module load graph). Mission
  constraint (free-runner only, no adapter dependency) is satisfiable.

## 3. Runtime proofs

### 3a. Pi session (`pi_session_proof.mjs` + `fake_openai_server.mjs`, log `out/06_pi_session_proof.log`, exit 0)

Fake OpenAI-compatible SSE server (~40 lines, `node:http`) + real Pi session:

- session created with `tools: ["heph_fake"]` — `session.agent.state.tools`
  contains exactly `heph_fake`, no built-in read/bash/edit/write/grep/find/ls;
- provider `heph-fake` registered with `baseUrl http://127.0.0.1:<port>/v1`,
  `api: "openai-completions"`; server received exactly 2 POSTs to
  `/v1/chat/completions`, first offering exactly one tool (`heph_fake`);
- streamed tool call executed the real `execute()` with parsed args
  (`ping: "from-fake-server"`); `tool_execution_start/end` events observed;
- final text streamed via `message_update`/`text_delta` ("HEPH_FINAL: tool
  roundtrip ok");
- session persisted as JSONL (7 entries) inside the **app-owned sessionDir**,
  and a second `createAgentSession` with
  `SessionManager.continueRecent(cwd, sessionDir)` resumed the same file with
  4 messages reloaded.

### 3b. Compaction + cancel (`pi_compact_cancel_proof.mjs`, log `out/07_compact_cancel_proof.log`, exit 0)

- after 4 tool-roundtrip turns, `session.compact("keep it terse")` fired
  `compaction_start/end`, returned a non-empty summary produced through the
  fake server, and shrank messages 10 → 3. (Needed
  `SettingsManager.inMemory({ compaction: { keepRecentTokens: 10 … } })` —
  default keepRecentTokens=20000 rejects tiny sessions with "Nothing to
  compact".)
- against a deliberately stalling SSE server, `session.abort()` cancelled a
  live stream in ~500 ms total and `prompt()` resolved cleanly.

### 3c. thread-phase free-runner + custom async JobStore (`threadphase_jobrunner_proof.mjs`, log `out/08_threadphase_jobrunner.log`, exit 0)

- custom in-memory **async** JobStore injected into `JobRunner`; two-phase
  pipeline ran to `COMPLETED` with `finalResult` persisted; 5 events durable
  and 5 streamed live on `job:<id>`; a second slow job was cancelled via
  `JobRunHandle.cancel()` → terminal `CANCELLED`, `signal.aborted === true`;
- module hygiene asserted in-process: **0 openai modules, 0 native addons,
  13 modules total** loaded through the `/session` import path.

## Caveats

- `node:sqlite` emits an ExperimentalWarning when `/session` is imported
  (SqliteJobStore is eagerly re-exported); builtin module, cosmetic only, and
  irrelevant when a custom JobStore is injected.
- The root thread-phase barrel eagerly loads the openai SDK; use subpath
  imports in production (fallback decision candidate for `repo_conventions.md`).
- `noTools: "all"` also removes custom tools; use the `tools` allowlist.

## Re-run

```bash
cd spikes/agent_runtime && pnpm install
node trace_imports.mjs "@autonome-research/thread-phase/session"
node pi_session_proof.mjs
node pi_compact_cancel_proof.mjs
node threadphase_jobrunner_proof.mjs
```
