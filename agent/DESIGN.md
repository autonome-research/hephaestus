# agent/ + agent_bridge — Design Contract (Stage 2)

> **STATUS — historical implementation contract.** This file was the
> implementation-time contract for Stage 2 (`agent/` sidecar + `agent_bridge`)
> and is kept for the reasoning it records. It is **not** normative today: the
> root documents (`architecture.md`, `mission_plan.md`, `script_contract.md`,
> `tool_schema.md`, `verification.md`, `repo_conventions.md`) are. Where this
> file and a root document disagree, the root document wins. Known drift: the
> Tier 3 corpus budgets these stage docs were written against were re-baselined
> in `verification.md` on 2026-07-25.

Binding for every Stage 2 implementation agent. Semantics live in
`agent/STAGE2_DIGEST.md` (distilled from architecture §4–§5, mission Stage 2/G2,
tool_schema, verification) — read it FIRST, then the root-doc sections for your
area. This file fixes structure: package layout, wire protocol names, codegen
pipeline, and ownership boundaries. Stage S dispositions in
`repo_conventions.md` are binding (thread-phase subpath imports; Pi tool gating
via allowlist, never `noTools:'all'`; minimal env).

## Packages

```
agent/                    pnpm package @hephaestus/agent (private, ESM, TS strict)
  package.json            EXACT pins: @earendil-works/pi-coding-agent 0.80.10,
                          @autonome-research/thread-phase 6.0.0, typescript,
                          @sinclair/typebox, vitest, eslint (no caret/tilde on
                          the two product deps)
  tsconfig.json           strict, NodeNext, ES2022
  src/
    main.ts               sidecar entry: stdio loop; stdout = protocol ONLY,
                          logs to stderr
    framing.ts            LF-delimited JSON-RPC 2.0 framer; incremental 64 MiB
                          wire cap (abort as soon as exceeded); frame version
                          field "hv": 1
    rpc.ts                bidirectional correlation (sidecar is server for
                          session.*/history.*; client for py.* calls), typed
                          errors, per-request timeouts
    limits.ts             loads schemas/bridge_limits.json (single source of
                          truth, committed at repo root schemas/); validators:
                          JSON depth/members/array caps, string/binary budgets,
                          PNG/JPEG bounded header parser before decode
    events.ts             normalized Hephaestus event vocabulary (run_id on
                          every event; kinds: text_delta, thought, tool_call,
                          tool_result, image, question, answer, audit,
                          progress, terminal); coalescing key
                          (run_id, event_kind, tool_call_id); droppable=only
                          progress deltas
    session/
      runtime.ts          app-owned ModelRuntime: anthropic + openai-compatible
                          (baseURL) + local endpoint providers; credential
                          allowlist injected by supervisor env; scripted
                          FakeModel provider for tests
      profiles.ts         session profiles: part / orchestrator / quick_edit /
                          query_snapshot — each: tools allowlist, resources,
                          system prompt, persistence dir (.heph/sessions/<id>),
                          budgets; query_snapshot: empty tools allowlist,
                          no extensions, no persistence, 1 turn, 1024 tokens,
                          60 s
      manager.ts          create/resume/cancel sessions; per-run
                          AbortController; session registry
      history.ts          history.page bridge method: Pi JSONL -> normalized
                          events, high-water cursor frozen at first page;
                          the `turn` ordinal on every event, the
                          {turn, seq, text, envelope, outcome?} user_prompts
                          entry, and the `after` tail read with its
                          always-present endCursor (INTERFACE.md §2.8)
      context.ts          K=3 image eviction w/ text stubs, T=70% compaction
                          request with pinned CAD summary, 90% budget
                          escalation via ask_user
    tools/
      schema.gen.ts       GENERATED TypeBox definitions — do not hand-edit;
                          produced by `uv run python -m hephaestus.contract.toolgen ts`
      registry.ts         builds the Pi custom-tool set per profile from
                          schema.gen.ts; sequential-execution declarations
      proxy.ts            validate input (TypeBox + x-hephaestus-maxUtf8Bytes)
                          -> py.tool_dispatch bridge call with trusted
                          invocation metadata -> validate result -> Pi content
                          (incl. inline images)
      preflight.ts        ask_user_must_be_alone sibling blocking (both source
                          orders); mutation sequencing
      invocation.ts       trusted invocation id: session UUID + persisted
                          entry ID + tool-call ordinal + provider call ID
    workflows/
      jobstore.ts         thread-phase JobStore impl delegating to
                          py.jobstore_* bridge methods (async, no native
                          sqlite)
      runner.ts           JobRunner via @autonome-research/thread-phase/session
                          + /patterns subpath imports ONLY; boundedFanout bound
                          = py.admission_capacity() at fan-out time
      cad_workflow.ts     decomposition -> part delegation (via py delegation
                          service, NOT the tool) -> cross-part checks ->
                          capped repair -> final verification
  test/                   vitest unit tests (fake bridge peer, fake model)

server/                   uv workspace member hephaestus-server
  pyproject.toml          name hephaestus-server; deps: hephaestus-core,
                          opstore (fastmcp/fastapi land in Stage 3)
  src/hephaestus/agent_bridge/
    supervisor.py         spawn packaged sidecar (node <agent dist>), minimal
                          env (PATH,HOME,LANG + approved credential vars from
                          config allowlist ONLY), watchdog, restart, orphan
                          handoff to coordinators before terminal synthesis
    framing.py            same wire contract as framing.ts; incremental cap
    protocol.py           method registry + "hv" version negotiation
    limits.py             loads schemas/bridge_limits.json (same file)
    dispatch.py           py.tool_dispatch: authz (object scope per session
                          principal) -> hephaestus.core call (build/measure/
                          inspect/read/edit/params/checks/export/registry) ->
                          result (+ images as refs/base64 within budgets);
                          idempotency via opstore opkeys with trusted
                          invocation ids
    admission.py          run admission over opstore.admission (16 slots),
                          terminal channel, acks, startup reconstruction
    delegation.py         delegation WAL over opstore admission per digest §3
                          (SUSPENDED_WAIT, FIFO resume priority, precedence)
    sessions.py           session service: per-session leases (.heph/locks via
                          opstore leases), profile assignment, session_busy
                          routing, quick-edit context seeding (artifact-bound
                          source + provenance + crop via core render/inspect)
    jobstore.py           py.jobstore_* methods over SQLite in .heph/state.db
                          (separate tables, prefix tp_)
    events.py             event pump: sidecar notifications -> per-client
                          queues; enforce coalescing/never-drop classes;
                          1024-event bound; backpressure-cancel path
    query_snapshot.py     ephemeral vision child orchestration over Stage 1
                          prepare_render_bundle + sidecar query profile
    cli.py                'heph agent' verb registration (mirrors cli_render
                          dispatch pattern): interactive stream rendering,
                          ask_user prompt UI, session pick/resume
  tests/                  package-local unit tests

schemas/                  repo-root cross-language contracts (committed)
  bridge_limits.json      every §5 numeric limit (single source both sides)
  tools/*.schema.json     canonical per-tool JSON Schema, generated from
                          hephaestus.contract.tools_decl by toolgen; committed;
                          drift-tested against tool_schema.md names
contract/src/hephaestus/contract/tools_decl.py
                          typed Python declaration of the FULL Stage 2 tool
                          surface (params, results, errors, conditionals,
                          x-hephaestus-maxUtf8Bytes, sequential/idempotent
                          flags, per-profile availability)
contract/src/hephaestus/contract/toolgen.py
                          emits JSON Schema + TypeBox (ts) + (Stage 3) MCP
                          declarations from tools_decl. hephaestus.core keeps
                          compatibility facades at the old module paths; the
                          engine itself never imports the contract.
registries/               skills/ (six references), parts/ (metric screws,
                          heat-set inserts), materials/ (plywoods, PLA/PETG,
                          6061); each registry: registry.toml + content;
                          Merkle tree hash pinning in hephaestus.toml;
                          heph registry verbs land with the tools
corpus/tasks/ + corpus/solutions/        public bench split v0 (8 tasks)
bench/                    workspace member hephaestus-bench (hephaestus.bench):
                          src/ holds runner + Wilson bound scoring; results/
                          holds the results JSON and run archives
tests/stage2/             gate tests (pytest side)
```

## Wire protocol (frozen names; both sides implement exactly these)

Python -> sidecar requests: `session.create {profile, part?, project_root,
session_id?, resume?}`, `session.prompt {session_id, run_id, prompt, images?,
context?}` (`context` is §7A.4's workspace-context block, sent as its own
user-role content block and recorded apart from `prompt` by §2.8(3)'s turn
marker — never concatenated into `prompt`),
`session.cancel {run_id}`, `session.compact {session_id}`, `history.page
{session_id, cursor?, after?}` (`cursor` continues a frozen page walk, `after`
is the tail read; both together are refused), `query.snapshot {run_id, question,
images}`,
`runtime.configure {providers, credentials}` (start-up only), `shutdown`.
Sidecar -> Python requests: `py.tool_dispatch {session_id, run_id, tool,
arguments, invocation}`, `py.jobstore_{get,put,list,delete,checkpoint}`,
`py.admission_capacity {}`, `py.delegate {parent_run_id, part, prompt,
delivery, deadline_seconds, invocation}`, `py.ask_user {run_id, question,
options, allow_free_text, multi}`.
Sidecar -> Python notifications: `event {run_id, seq, kind, ...}`,
`terminal {run_id, terminal_id, state, payload}`.
Python -> sidecar notifications: `cancel {run_id}`, `terminal.ack
{run_id, terminal_id}` flows back as method response; answer delivery:
`session.answer {run_id, question_id, selection}`.
Every frame: `{"hv":1, "jsonrpc":"2.0", ...}`. Unknown `hv` -> fail closed.

## Provider kinds and the `auth_source` link

`runtime.configure` carries provider specs of four kinds. Three are
**explicitly keyed** — `anthropic`, `openai_compatible`, `local` — and are
fully app-defined: the sidecar calls Pi's `registerProvider` with an `api`, an
optional `baseUrl`, a model list, and an `apiKey` taken *only* from the
`credentials` allowlist in the same payload. `process.env` is never consulted,
so an ambient key cannot reach a session.

The fourth, **`pi_native`**, names a provider that already exists in Pi's
built-in catalog (e.g. `openai-codex`, whose models are `gpt-5.4`, `gpt-5.5`,
`gpt-5.6-{luna,sol,terra}`, …). For it the sidecar calls `registerProvider`
**not at all**: endpoint, api, and model metadata come from Pi's bundled
catalog, and the credential comes from the app-owned `auth.json` that
`ModelRuntime.create({authPath})` reads. The spec therefore has no `apiKey`,
`baseUrl`, or `credential` field — only an id and model ids — so there is no
way for it to smuggle a key in. `createModelRuntime` verifies each such
provider up front and throws a typed `RuntimeConfigError` whose `code`
distinguishes `provider_unknown` (not in Pi's catalog),
`provider_not_authenticated` (`hasConfiguredAuth` false), and `model_unknown`,
rather than letting the failure surface as an opaque 401 mid-run.

**Isolation is preserved by default.** Pi's catalog is bundled with the
package, not read from `~/.pi`; with no credential in the project's
`.heph/agent/auth.json` a `pi_native` provider simply fails to configure. It
can never fall back to the operator's ambient login.

Making a stored credential visible is **opt-in and explicit**: the provider
config declares `"auth_source": "<abs path to an existing Pi auth.json>"`, and
the supervisor (`agent_bridge.app.link_auth_source`) makes
`<project>/.heph/agent/auth.json` a **symlink** to it before spawning the
sidecar.

Why a symlink and never a copy: an OAuth record rotates. Pi (or the sidecar)
refreshes the access token and rewrites the file, and the refresh token it
replaces is invalidated. A copy would go stale at best, and at worst refresh
independently — logging the user out of their own Codex/Pi session. One file
with one rotation, shared by both readers, is the only correct arrangement.
`link_auth_source` re-points an existing symlink and replaces Pi's empty `{}`
placeholder, but refuses (raising `AuthLinkError`) to overwrite a real
credential file, and names the path when the target is missing.

## Ownership boundaries

- Foundation agent owns: schemas/bridge_limits.json, tools_decl.py, toolgen.py,
  generated schemas/tools/*.schema.json + agent/src/tools/schema.gen.ts,
  framing/rpc/limits on BOTH sides, agent scaffolding (package.json, tsconfig,
  eslint, vitest), server package scaffolding.
- No agent edits another's files; integration agents are single-writer.
- Root pyproject: only the integration agent, only for workspace member +
  pyright include additions.
- The fake model and fake OpenAI-compatible server live in agent/src/session/
  runtime.ts (FakeModel) + agent/test helpers; pytest drives them through the
  real bridge via a test-only supervisor config.

## Quality bars (G2)

`pnpm --dir agent test`, `pnpm --dir agent typecheck` (tsc strict), eslint
clean, `uv run pytest tests/stage2 -q` exit 0; server/ ruff + pyright strict;
no test may resolve a global pi/thread-phase install (isolation tests plant
hostile globals); schema drift tests across Python decl / committed JSON /
TypeBox / tool_schema.md names.
