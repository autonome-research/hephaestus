<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Audit 2026-09-04: janky

The 2026-09-04 audit produced two ledgers. The twelve items whose surfaces are
broken outright are in [audit-2026-09-04-broken.md](audit-2026-09-04-broken.md).
This is the other one: 147 items — 137 confirmed defects and ten that turned
out not to be — covering the surfaces that work and lie, refuse by the wrong
name, cost seconds they do not need to cost, or promise a behaviour nothing
delivers.

Every item here was re-reproduced against the working tree on 2026-09-04 —
against a live `heph`, a live serve, a real Node sidecar, or a browser driven
by CDP — and is recorded with what was observed and what the governing clause
says instead. The ten that came back **not defects** are in the last section
with the evidence, so nobody re-chases them.

Four numbers set the shape of the work. `heph --version` costs 2.9 s and needs
to cost 0.14 s. `GET /parts/{part}/params` runs a full sandboxed CAD build to
read a dict that a 0.5 ms literal pass already answers. Ten `_UsageError`
classes and eleven `_guard()` wrappers give one condition — "not a Hephaestus
project" — two exit codes and two message shapes across fourteen verbs. And a
closed vocabulary is transcribed by hand into as many as four files, in two
languages, with a comment in each naming the others as its mirror.

## Summary

| id | title | severity | effort | primary files |
|---|---|---|---|---|
| J-cli-robustness-5 | One "not a project" condition, two exit codes across fourteen verbs | medium | L | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-6 | `--json` ignored on refusals: prose on stderr, nothing on stdout | medium | M | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-14 | OCCT writes ANSI diagnostics to stdout, corrupting `--json` and MCP stdio | high | M | `core/src/hephaestus/geom/step_io.py` |
| J-cli-robustness-21 | Six `except ImportError: pass` blocks delete a verb on any broken dependency | high | M | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-3 | `heph registry pin` writes an absolute host path into a committed manifest | high | M | `core/src/hephaestus/core/registry/_pins.py` |
| J-cli-robustness-1 | `reference add --name` classifies the name instead of the source file | medium | S | `core/src/hephaestus/core/project_store/references.py` |
| J-cli-robustness-2 | `heph lint --request` without `--requirements` is a silent no-op | medium | S | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-4 | `--project` is a boolean on `check` and a directory everywhere else | low | S | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-7 | `--json` listings: one envelope, four bare arrays | low | M | `core/src/hephaestus/core/cli_import.py` |
| J-cli-robustness-8 | `heph import list` loses the declared unit — it is never persisted | medium | M | `core/src/hephaestus/core/cli_import.py` |
| J-cli-robustness-9 | `heph import add` silently re-admits a file under a contradictory unit | medium | M | `core/src/hephaestus/core/cli_import.py` |
| J-cli-robustness-10 | "has no current successful build" said about a part that does not exist | medium | M | `core/src/hephaestus/core/render/inspect.py` |
| J-cli-robustness-11 | `heph export list <unknown part>` reports "no exports recorded", exit 0 | low | S | `server/src/hephaestus/agent_bridge/cli_export.py` |
| J-cli-robustness-12 | `heph lint .` says "no such file" about a directory that exists | low | S | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-13 | `heph goldens` with no flag refuses instead of verifying | low | M | `core/src/hephaestus/core/cli_render.py` |
| J-cli-robustness-15 | `heph check` badges an unevaluated check FAIL and prints its error object | medium | S | `core/src/hephaestus/core/cli.py` |
| J-cli-robustness-16 | `--expected-hash` is never validated; a malformed value becomes a ref | medium | S | `core/src/hephaestus/core/cli_authoring.py` |
| J-cli-robustness-17 | `solve placement --bound bogus` is accepted and means nothing | medium | M | `core/src/hephaestus/core/cli_solve.py` |
| J-cli-robustness-20 | Module `main()` entry points traceback where `heph` refuses | low | S | `core/src/hephaestus/core/cli_render.py` |
| J-cli-robustness-22 | `--project` resolves differently on `heph agent` and `heph serve --web` | medium | M | `server/src/hephaestus/http/cli_web.py` |
| J-cli-startup-1 | `heph` startup is 2.9 s: five registration sites import the CAD and MCP stacks | high | M | `core/src/hephaestus/core/cli.py` |
| J-cli-startup-2 | `cad_ops/__init__.py` makes registering `heph export list` cost 3.5 s | high | S | `server/src/hephaestus/agent_bridge/cad_ops/__init__.py` |
| J-cli-startup-3 | `hephaestus/mcp/__init__.py` eagerly imports `.app` — fastmcp at parser build | high | S | `server/src/hephaestus/mcp/__init__.py` |
| J-cli-startup-4 | `hephaestus/http/__init__.py` eagerly imports the whole workspace API | high | S | `server/src/hephaestus/http/__init__.py` |
| J-cli-startup-5 | `MESH_UNITS` imported from `geom` at parser-build time (missed by both audits) | high | S | `core/src/hephaestus/core/cli_import.py` |
| J-agent-wiring-4 | `heph agent` runs model-authored scripts with no OS sandbox, by default | high | M | `server/src/hephaestus/agent_bridge/cad_ops/_base.py` |
| J-http-envelope-3 | An unknown part is answered six ways across the part routes, three of them 200 | high | L | `server/src/hephaestus/http/app.py` |
| J-http-envelope-5 | `focus` and `view` are unvalidated client strings in the model's context block | high | M | `server/src/hephaestus/http/context.py` |
| J-http-envelope-16 | Two routes §2.3 lists and G5.12 cites are not served | high | L | `server/src/hephaestus/http/app.py` |
| J-http-limits-1 | POST bodies are buffered whole with no ceiling; the 32 KiB prompt cap is unapplied | high | M | `server/src/hephaestus/http/app.py` |
| J-http-limits-6 | The one request-path subprocess with no timeout takes the server down | high | S | `server/src/hephaestus/http/git_projection.py` |
| J-http-limits-7 | `GET /project` probes git and bwrap inline on the event loop | high | S | `server/src/hephaestus/http/runtime.py` |
| J-cli-startup-7 | `GET/POST /parts/{part}/params` runs a sandboxed build to read a dict | high | L | `server/src/hephaestus/agent_bridge/cad_ops/_params.py` |
| J-build-state-1 | `GET /parts/{part}/build` hides a newer failure and never populates `error` | medium | M | `server/src/hephaestus/http/app.py` |
| J-http-envelope-1 | `config_path` is merged onto a refusal §2.4 says must not carry it | medium | S | `server/src/hephaestus/http/app.py` |
| J-http-envelope-4 | A focus that matches nothing refuses `invalid_part`, not `addressing_error` | medium | S | `server/src/hephaestus/agent_bridge/dispatch.py` |
| J-http-envelope-6 | `agent_unavailable`'s cause goes stale after `PUT /providers/specs` | medium | M | `server/src/hephaestus/http/runtime.py` |
| J-http-envelope-7 | `thread_state` has two producers with two definitions | medium | S | `server/src/hephaestus/http/sessions.py` |
| J-http-envelope-8 | `GET /sessions/{id}/thread` fabricates a one-node graph for any string | medium | S | `server/src/hephaestus/http/sessions.py` |
| J-http-envelope-10 | `POST /sessions/{id}/prompt` silently accepts unknown body members | low | S | `server/src/hephaestus/http/app.py` |
| J-http-envelope-11 | `git_failed` returns the full argv and raw git stderr | medium | S | `server/src/hephaestus/http/git_projection.py` |
| J-http-envelope-12 | `POST /runs/{run}/cancel` refuses an unknown run `not_found`; FakeAgent answers 200 | low | S | `server/src/hephaestus/http/sessions.py` |
| J-http-envelope-13 | The idempotency refusal message embeds the composed ledger key | low | S | `opstore/src/opstore/opkeys.py` |
| J-http-envelope-14 | Four git reasons carry hardcoded statuses with no `REASON_STATUS` row | medium | S | `server/src/hephaestus/http/errors.py` |
| J-http-envelope-15 | `reduce_detail` called with no secrets; `message` untruncated beside it | medium | S | `server/src/hephaestus/http/errors.py` |
| J-http-envelope-18 | `json_string_too_large` is 400, `export_too_large` is 413, neither is tabulated | low | S | `server/src/hephaestus/http/errors.py` |
| J-http-envelope-19 | `UNAUTHORIZED_CLOSE_CODE` is dead: closing before accept is an HTTP 403 | low | S | `server/src/hephaestus/http/events_ws.py` |
| J-http-envelope-20 | `GET /parts/{part}/script` is the only 200 body with no `status` | low | S | `server/src/hephaestus/http/app.py` |
| J-http-limits-2 | Refusal bodies echo client strings twice — a 32 MiB request returns 33.5 MB | medium | M | `server/src/hephaestus/http/errors.py` |
| J-http-limits-4 | A turn's events accumulate unbounded in memory and in the response | medium | M | `server/src/hephaestus/agent_bridge/app.py` |
| J-agent-wiring-7 | The second answerer of an `ask_user` gets 404, not `accepted:false` | medium | S | `server/src/hephaestus/http/sessions.py` |
| J-web-viewport-1 | A `PanelNote` inside a `PanelSection` sizes the label column to 487px | high | S | `web/src/system/Panel.module.css` |
| J-web-stream-1 | The Stream `<aside>` keeps a grid row for a child that was deleted | high | S | `web/src/components/Shell.module.css` |
| J-web-stream-2 | A selected session with an empty transcript renders literally nothing | medium | S | `web/src/components/stream/StreamPanel.tsx` |
| J-web-stream-3 | The composer's `agent_unavailable` refusal overflows the column by 214px | medium | S | `web/src/components/stream/Composer.module.css` |
| J-web-stream-4 | One attach cause stated three times, one sentence rendered twice | medium | S | `web/src/components/stream/Composer.tsx` |
| J-web-stream-6 | "Add a provider" re-reads an unchanged file and prints a raw reason code | medium | M | `web/src/components/ProvidersPanel.tsx` |
| J-web-stream-8 | Checks and DFM render `measured` through `JSON.stringify` | medium | M | `web/src/system/format.ts` |
| J-web-viewport-2 | Section plate header overlapped; C19's e2e never mounts a plate | medium | M | `web/src/components/stage/viewport/Viewport.tsx` |
| J-web-viewport-3 | The explode control's Collapse button paints outside its own card | medium | M | `web/src/components/stage/viewport/ExplodeSlider.module.css` |
| J-web-viewport-4 | A 7ch readout cannot hold `0.00` plus Chrome's spin buttons | low | S | `web/src/system/Input.module.css` |
| J-web-viewport-5 | The held-artifact part lives in a tooltip and is lost on reload | medium | M | `web/src/state/workspace.ts` |
| J-web-viewport-7 | The workspace opens on the one fixture part that has never been built | low | S | `web/src/App.tsx` |
| J-web-viewport-9 | §4.1's "every panel below inherits that marking" has no consumer | medium | M | `web/src/components/Shell.tsx` |
| J-cli-startup-8 | Script tab blocks on "Loading parameters…" instead of rendering stale rows | medium | S | `web/src/components/stage/ParamSliders.tsx` |
| J-web-stream-5 | The providers panel's "duplicated explanation" is the composer's | low | S | `web/src/components/ProvidersPanel.tsx` |
| J-web-stream-7 | The project observer re-creates its socket on every query settle | low | S | `web/src/api/projectRefresh.ts` |
| J-web-stream-9 | The terminal band prints an internal id as prose | low | S | `web/src/components/stream/Transcript.tsx` |
| J-web-stream-10 | A rejected token renders "No workspace token" above "was not accepted" | low | S | `web/src/components/NoToken.tsx` |
| J-web-stream-11 | `ExportChrome` re-implements `ExportView`'s state machine and has diverged | medium | M | `web/src/components/inspector/ExportPanel.tsx` |
| J-web-stream-12 | Raw NUL bytes make two TypeScript sources binary to grep | medium | S | `web/src/state/visibility.ts` |
| J-web-stream-13 | `LIVE_DEDUPE_WINDOW = 1024` claims a coupling it copied by hand | low | S | `web/src/stream/live.ts` |
| J-web-stream-14 | `SESSION_PROFILES` names two sets; a `reviewer` session can be listed | medium | M | `server/src/hephaestus/http/sessions.py` |
| J-agent-results-1 | `m.mass` reports mm³ volume labelled grams — no caller binds a density | high | M | `core/src/hephaestus/core/checks/facade.py` |
| J-http-limits-3 | `read_part`/`read_globals`/`read_project_check` declare paging and implement none | high | M | `server/src/hephaestus/agent_bridge/dispatch.py` |
| J-agent-results-2 | `edit_part` with an absent `old_str` returns a success-shaped no-op | high | S | `server/src/hephaestus/agent_bridge/dispatch.py` |
| J-agent-results-3 | `read_artifact` on a binary artifact returns a complete, empty page | medium | S | `server/src/hephaestus/agent_bridge/cad_ops/_artifacts.py` |
| J-agent-results-8b | An unresolvable solve reports generation `-1` and refs `""` | medium | M | `core/src/hephaestus/core/placement.py` |
| J-agent-results-9 | `run_checks(scope="project")` returns the project name in a field named `part` | low | M | `core/src/hephaestus/core/types.py` |
| J-agent-results-11 | Addressing refusals leak the host path and drop the candidate list | low | S | `server/src/hephaestus/agent_bridge/dispatch.py` |
| J-agent-results-8a | `check_motion` reports `artifact_refs {"carriage": ""}` for a missing part | low | S | `core/src/hephaestus/core/motion.py` |
| J-agent-results-S5 | Check-file snapshots are minted as `artifact:part-snapshot:` | low | S | `server/src/hephaestus/agent_bridge/cad_ops/_checks.py` |
| J-http-envelope-9 | A cursor naming an unknown high-water mark reads as a complete, empty history | medium | M | `agent/src/session/history.ts` |
| J-agent-wiring-6 | Delegation accepts a part that does not exist and reports it completed | medium | S | `server/src/hephaestus/agent_bridge/delegation.py` |
| J-cli-startup-9 | `run_checks(scope="part")` pays 3.4 s for a part that declares zero CHECKS | medium | M | `server/src/hephaestus/agent_bridge/cad_ops/_checks.py` |
| J-agent-wiring-13 | `py.*` handlers run inline on the single reader thread | high | M | `server/src/hephaestus/agent_bridge/supervisor.py` |
| J-mirrors-and-dx-1 | The event vocabulary is hand-written in four files, paired by no test | high | L | `server/src/hephaestus/agent_bridge/events.py` |
| J-mirrors-and-dx-2 | JSON-RPC codes, methods and notifications duplicated whole | high | M | `server/src/hephaestus/agent_bridge/protocol.py` |
| J-mirrors-and-dx-6 | Fourteen closed workspace vocabularies duplicated Python↔web | high | L | `server/src/hephaestus/http/context.py` |
| J-mirrors-and-dx-3 | Ten limit error-code strings written twice | medium | M | `server/src/hephaestus/agent_bridge/limits.py` |
| J-mirrors-and-dx-4 | `EventCoalescer` is dead and already divergent in three ways | medium | S | `agent/src/events.ts` |
| J-mirrors-and-dx-5 | Jobstore key padding: a named constant on one side, `:012d` on the other | medium | S | `agent/src/workflows/jobstore.ts` |
| J-mirrors-and-dx-7 | `event_identity.py` hand-ported into the browser client | medium | S | `web/src/api/events.ts` |
| J-mirrors-and-dx-8 | Six per-profile budget literals duplicated across the bridge | medium | S | `agent/src/session/profiles.ts` |
| J-mirrors-and-dx-9 | `SESSION_PROFILES` names three sets; the web copy cites a missing symbol | medium | M | `web/src/api/sessions.ts` |
| J-mirrors-and-dx-10 | The web client hardcodes 1024, 4409 and `resync_required` | medium | S | `web/src/stream/live.ts` |
| J-mirrors-and-dx-11 | Same-language duplicates: `_clean` ×2, the AnchorRef decoder ×2 | low | S | `core/src/hephaestus/core/assembly.py` |
| J-mirrors-and-dx-31 | `main.ts` registers 17 handlers as module-level side effects | low | M | `agent/src/main.ts` |
| J-build-state-5 | Four hand-copied bounded-subprocess loops; two never got the fixes | medium | L | `core/src/hephaestus/core/project_compare.py` |
| J-build-state-3 | A crashed verification child is refused `solver_timeout` with no evidence | medium | M | `core/src/hephaestus/core/placement.py` |
| J-build-state-4 | A crashed compare child is `compare_timeout` with a 300 s it never reached | medium | M | `core/src/hephaestus/core/project_compare.py` |
| J-build-state-2 | A failed terminal write during process loss is swallowed twice | medium | S | `server/src/hephaestus/agent_bridge/app.py` |
| J-http-envelope-2 | `GET /favicon.ico` returns 500 with a full ASGI traceback | medium | S | `server/src/hephaestus/http/serve.py` |
| J-http-limits-8 | `timeouts.cad_build_seconds` is dead: the field is on the wrong side | high | M | `server/src/hephaestus/agent_bridge/supervisor.py` |
| J-http-limits-11 | `rpc.ts` hardcodes 120 s; the CAD class and D+60 s are unreachable | high | M | `agent/src/rpc.ts` |
| J-http-limits-9 | `binary.max_binary_bytes` is exported on both sides and validated by nothing | low | M | `schemas/bridge_limits.json` |
| J-http-limits-10 | `admission.queued_prompts` describes a prompt queue that does not exist | low | S | `schemas/bridge_limits.json` |
| J-mirrors-and-dx-18 | The first documented test command is red on every developer machine | high | M | `CONTRIBUTING.md` |
| J-mirrors-and-dx-25 | The documented bootstrap leaves no `pnpm` on PATH — 32 tests skip silently | high | M | `server/src/hephaestus/testing/sidecar.py` |
| J-mirrors-and-dx-32 | `scripts/bootstrap.sh` and `scripts/heph` are run by no job and no test | high | M | `scripts/bootstrap.sh` |
| J-mirrors-and-dx-14 | Two deadlock-regression tests hang instead of failing | high | S | `server/tests/test_cancel_lock_leak.py` |
| J-mirrors-and-dx-15 | The Khronos glTF validator test is skipped everywhere | medium | M | `docker/ci/Dockerfile` |
| J-mirrors-and-dx-17 | `HEPHAESTUS_SKIP_SIDECAR_BUILD=1` runs whatever is staged | medium | M | `server/src/hephaestus/testing/sidecar.py` |
| J-mirrors-and-dx-19 | `exports.test.tsx` leaks a stubbed global `URL` into the §22.7 block | medium | S | `web/vitest.config.ts` |
| J-mirrors-and-dx-20 | A vitest test runs `tsc -p` into the shared `agent/dist` | medium | S | `agent/test/session/concurrency.test.ts` |
| J-mirrors-and-dx-22 | `testpaths` excludes core, server, contract and bench | medium | S | `pyproject.toml` |
| J-mirrors-and-dx-27 | ruff excludes `bench` with no reason; 5 lint and 4 format findings behind it | medium | S | `pyproject.toml` |
| J-mirrors-and-dx-28 | `agent/test` is never type-checked — and type-checks clean today | medium | S | `agent/tsconfig.json` |
| J-mirrors-and-dx-30 | `contract/tests` is documented and run by no CI job | medium | S | `contract/tests` |
| J-mirrors-and-dx-13 | Six Hypothesis `@settings` without `deadline=None`, against seven with it | low | S | `core/tests/test_addressing.py` |
| J-mirrors-and-dx-16 | `pid_alive()` forks `ps` per poll | low | S | `server/src/hephaestus/agent_bridge/supervisor.py` |
| J-mirrors-and-dx-21 | Four independent bind-and-release free-port helpers | low | S | `server/src/hephaestus/testing/` |
| J-mirrors-and-dx-23 | One wall-clock budget with provenance, one without | low | S | `core/tests/test_fixtures_build.py` |
| J-mirrors-and-dx-24 | Fixed sleeps used as negative assertions in four suites | low | S | `server/tests/test_supervisor.py` |
| J-mirrors-and-dx-26 | CI type-checks a narrower target than the config declares | low | S | `pyproject.toml` |
| J-mirrors-and-dx-34 | The pnpm pin is copied into six places | low | S | `agent/package.json` |
| J-mirrors-and-dx-35 | `opstore` lacks the `<3.15` bound every sibling declares | low | S | `opstore/pyproject.toml` |
| J-mirrors-and-dx-36 | Both eslint configs use the untyped recommended preset | low | M | `web/eslint.config.js` |
| J-cli-startup-6 | Nothing pins the CLI startup budget | medium | S | `core/tests` |
| J-http-limits-5 | The workspace fixture git-commits `.heph/`, including a live bearer | medium | S | `server/src/hephaestus/testing/workspace_fixture.py` |
| J-cli-robustness-18 | docs/cli.md promises `heph build` with no argument builds every part | medium | M | `docs/cli.md` |
| J-cli-robustness-19 | Four further docs/cli.md facts do not match the shipped behaviour | low | M | `docs/cli.md` |
| J-http-envelope-17 | §2.4's table contradicts itself on an unknown part | medium | S | `INTERFACE.md` |
| J-agent-results-S4 | STAGE2_DIGEST §7 still excludes four tools that shipped in Stage 6 | low | S | `agent/STAGE2_DIGEST.md` |
| J-mirrors-and-dx-33 | docs_check covers 29 documents; INTERFACE.md is not one of them | medium | M | `scripts/docs_check.py` |
| J-mirrors-and-dx-29 | Four documents teach the `pnpm --dir` form two others call broken | medium | S | `repo_conventions.md` |
| J-mirrors-and-dx-37 | INTERFACE.md's unfinished register names landed work as outstanding | medium | S | `INTERFACE.md` |

Ten further items were investigated and are **not** defects; they are listed
with their evidence in [Not defects](#not-defects) so they are not re-chased.

## Workflow plan

Nine lanes. Each lane owns its files outright; where two lanes touch one file
the order is stated and is not optional, because in every such case the second
lane's edit sits inside a region the first lane rewrites.

**This plan runs after the broken ledger's.** The two documents share files in
every surface, and the twelve broken items rewrite the regions these items edit —
`refusal_for`'s exception handlers, the tool dispatcher's construction, the
published-artifact resolver, the panel and cube CSS, the cursor and resume
refusals. So wherever a lane here shares a file with one of that document's lanes
A–G, **this lane runs after it**, item by item:

| lane here | runs after (broken ledger) | shared files |
| --- | --- | --- |
| L1 | A | `core/src/hephaestus/core/cli.py`, the `cli_*.py` beside it |
| L2 | A | `core/src/hephaestus/core/cli.py`'s registration block |
| L3 | B | `core/src/hephaestus/core/placement.py`, `core/src/hephaestus/core/assembly.py` |
| L4 | D, F | `http/app.py`, `errors.py`, `sessions.py`, `projections.py`, `context.py` |
| L5 | C, D, E | `agent_bridge/app.py`, `delegation.py`, `agent/src/main.ts`, `agent/src/session/history.ts` |
| L6 | B, C, F | `cad_ops/_base.py`, `_measure.py`, `_checks.py`, `dispatch.py`, `core/types.py` |
| L7 | F, G | `web/src/system/`, `web/src/components/stream/`, `web/src/viewport/`, `web/src/copy.ts`, `web/e2e/` |
| L8 | — (after L4, L5, L7, so after the broken plan transitively) | `schemas/`, the generated modules |
| L9 | A, C, D, E | `docs/cli.md`, `server/src/hephaestus/testing/`, `tests/stage2/` |

Where a lane below names a `B-<n>` item, that item is **owned by the broken
ledger** and is listed only to say what else lands in the same files and in what
order; nothing here re-specifies it.

**L1 — the CLI refusal boundary.** Owns `core/src/hephaestus/core/cli.py`,
every `cli_*.py` beside it, `server/src/hephaestus/agent_bridge/cli_export.py`,
`server/src/hephaestus/http/cli_web.py`, `server/src/hephaestus/agent_bridge/cli.py`
and `core/tests/test_cli.py`. Items: J-cli-robustness-1, -2, -3, -4, -5, -6,
-7, -8, -9, -10, -11, -12, -13, -15, -16, -17, -20, -22, and the B-10 family
from the broken ledger. Land the shared `cli_errors` module first (J-5); every
other item in the lane is then a two-line adoption.

**L2 — CLI startup.** Owns `server/src/hephaestus/mcp/__init__.py`,
`server/src/hephaestus/http/__init__.py`,
`server/src/hephaestus/agent_bridge/cad_ops/__init__.py`,
`server/src/hephaestus/agent_bridge/cli.py`'s module-level imports,
`core/src/hephaestus/geom/mesh.py`, and the optional-verb registration block of
`core/src/hephaestus/core/cli.py`. Items: J-cli-startup-1 through -5 and
J-cli-robustness-21, which rewrites the same six `try/except ImportError`
blocks. **Runs after L1** — both edit `core/src/hephaestus/core/cli.py`, L1 in
`main()` and the handlers, L2 in `build_parser`.

**L3 — kernel subprocess honesty.** Owns `core/src/hephaestus/geom/step_io.py`,
`core/src/hephaestus/core/executor/imports.py`,
`core/src/hephaestus/core/project_compare.py`,
`core/src/hephaestus/core/motion.py`,
`core/src/hephaestus/core/scan_compare.py`,
`core/src/hephaestus/core/placement.py`'s `_verify`,
`core/src/hephaestus/core/checks/engine.py` and
`server/src/hephaestus/agent_bridge/cad_ops/_compare.py`. Items:
J-cli-robustness-14, J-build-state-3, -4, -5, J-mirrors-and-dx-11 (whose second
half promotes the anchor decoder out of `core/src/hephaestus/core/motion.py`; its
first half touches `core/src/hephaestus/core/assembly.py`, so that half runs after
the broken ledger's lane B). Extract the shared bounded-pass
helper (J-build-state-5) before the two reason splits, or the crash/ceiling
discrimination is written three more times. **Runs after L1** for
`core/src/hephaestus/core/cli_diff.py`.

**L4 — the HTTP envelope.** Owns `server/src/hephaestus/http/app.py`,
`errors.py`, `serve.py`, `context.py`, `sessions.py`, `runtime.py`,
`projections.py`, `git_projection.py`, `events_ws.py`, `agent_attach.py`,
`idempotency.py` and `opstore/src/opstore/opkeys.py`. Items: B-6 and B-11 from
the broken ledger, J-http-envelope-1 through -20 except -4, -9 and -17;
J-http-limits-1, -2, -4, -6, -7; J-build-state-1; J-agent-wiring-7;
J-cli-startup-7. Land B-6's exception handlers first: several items add a
reason, and a reason with no envelope is not a fix.

**L5 — bridge and sidecar runtime.** Owns
`server/src/hephaestus/agent_bridge/supervisor.py`, `app.py`, `delegation.py`,
`agent/src/main.ts`, `agent/src/rpc.ts`, `agent/src/session/history.ts`,
`agent/src/limits.ts` and the `timeouts` block of `schemas/bridge_limits.json`.
Items: J-agent-wiring-13, -6; J-build-state-2; J-http-envelope-9;
J-http-limits-8, -9, -10, -11; J-mirrors-and-dx-31. J-agent-wiring-13 first:
until `py.*` dispatch is off the reader thread no handler may call back into
the sidecar, so the delegation half of B-2 cannot land.

**L6 — tool results.** Owns `server/src/hephaestus/agent_bridge/dispatch.py`,
`cad_ops/_artifacts.py`, `cad_ops/_checks.py`, `cad_ops/_measure.py`,
`cad_ops/_params.py`, `cad_ops/_base.py`,
`core/src/hephaestus/core/checks/facade.py`, `core/src/hephaestus/core/types.py`
and `contract/src/hephaestus/contract/tools_decl.py`. Items: B-1 and B-4 from
the broken ledger, J-agent-results-1, -2, -3, -8a, -8b, -9, -11, -S5;
J-http-limits-3; J-http-envelope-4 (the one-line `AddressingError` relabel, which
lives in this lane's file); J-cli-startup-9; J-agent-wiring-4. **Runs after L2**
for `core/src/hephaestus/core/types.py` and **before L5** for
`contract/src/hephaestus/contract/tools_decl.py`. Batch every declaration edit
and regenerate the schemas once: `contract/tests/test_toolgen.py` fails on a
partial regeneration.

**CORRECTION (2026-09-08), `hephaestus.geom`'s package `__init__`.** J-cli-startup-1
says "do **not** make `core/src/hephaestus/geom/__init__.py` lazy", because the
solver's omission from that block is a load-bearing guarantee. The lane made it
lazy anyway, and the reason is recorded here rather than hidden: once
`cad_ops/__init__.py` stopped importing eagerly (J-cli-startup-2), a latent
cycle — `geom.nesting` → `core.cutfile` → `core.dfm` → `core.dfm.context` →
`geom.topology` — became a live `ImportError` on the plain line `from
hephaestus.agent_bridge.cad_ops import CadOps`, because nothing imported
`hephaestus.geom` first any more. The fix is the same root cause one layer down
(RC-2): a package `__init__` may not turn a leaf import into a whole-closure
import. The guarantee the ledger was protecting is kept structurally instead of
by eagerness: `solve` is absent from the lazy export map and
`core/tests/test_cli_startup.py::TestGeometryPackageIsLazy` pins both halves —
the cycle stays broken and `hephaestus.geom.solve` is still unreachable from the
package surface. The cycle itself was then cut at its root by the L3 follow-up
(`geom/nesting.py` no longer imports `core.cutfile`).

**OPEN AFTER REVIEW (2026-09-08).** The independent review of waves 2 and 3
found three residuals that are recorded here rather than closed by assertion:
(1) `scan_compare.bounded_scan_distance` and `mesh_solid.bounded_mesh_solid`
run on the shared helper but still spell a dead child as `scan_timeout` /
`mesh_sew_timeout` with a ceiling it never hit — J-build-state-4 kept scan as
the behaviour-preserving control, so the split (`scan_child_died`,
`mesh_sew_child_died`, bench refund rows, `compare_to_scan`'s map) is the next
lane's first item; (2) `_bounded_floor` in `bench/src/hephaestus/bench/cadgenbench/_score.py` is a
sixth hand-copied supervision loop outside the engine tree, with no death
drain, that the structural guard cannot see; (3) the stage-13B `bench` fixture
is a session project that proposals recorded through it pollute for later
`bench_copy` counts — CI's alphabetical order hides it, a reordered run does
not; (4) FIXED 2026-09-09 — the sidecar's own vitest suite left an empty
`auth.json` (mode 0600, `{}`) in this package, because `agent/src/main.ts`
reads `HEPHAESTUS_AGENT_DIR` at module load and falls back to `process.cwd()`,
which under vitest is the checkout; Pi then writes its placeholder there on
first run. `agent/test/setup.ts` now gives every test process a temporary agent
dir before any test imports `main.ts`, and `agent/test/agent_dir.test.ts` pins
the invariant against the ENV rather than the file, so it holds for a test
nobody has written yet. L8 (J-mirrors-and-dx-1..10) remains deferred by
decision.

**2026-09-09, and one defect the audit missed.** J-mirrors-and-dx-16 (the
liveness helper forking a process per poll) is fixed: it reads
`/proc/<pid>/stat` with the process listing kept behind an availability check
as the portable fallback, and a zombie-is-dead test exists for the first time.
Residual (2) above (`_bounded_floor`) is still open. Two more closed the same
day, both surfaced by CI run 34418449613 rather than by the audit: the
admission-slot leak recorded in this register is fixed — the acknowledgement
lived only on the dispatcher's success path, so a coordinator that raised left
its child ADMITTED forever, and the failure path now finalizes the delegation
`interrupted` and resumes the parent before re-raising — and a class of bare
SQLite reads on the shared connection is gone. The latter answered `GET
/parts/{part}/exports` with a 500 (`InterfaceError: bad parameter or other API
misuse`): `opstore` enforces "no read without `reading()`" for its own package
only, and fifteen bare statements had accumulated across six consumer modules,
each one a concurrent write away from the same crash. A structural test now
extends that guarantee to the consumer packages.

**The repair-cap "nondeterminism" is FIXED, and it was never a workflow defect
(2026-09-09).** This register recorded that
`tests/stage2/test_workflow_gate.py::test_workflow_repair_cap_stops_without_claiming_verification`
"occasionally repairs BOTH parts instead of the shelf alone". It reproduces
about one run in ten under CPU load (six busy cores beside it) and the cause is
one layer down: a part's DELEGATION fails, and `repairTargets`
(`agent/src/workflows/cad_workflow.ts`) then targets that part by its own
documented rule — a part whose delegation did not complete is retried. Both
parts being repaired is the correct response to the failure, not a bug in the
cap. Two distinct delegation failures were captured, and both are races on the
child's admission row rather than anything the workflow decides:

- `InterfaceError: bad parameter or other API misuse`, and
- `NotFoundError: run cr-… has no admission row` from
  `DelegationService.dispatch`.

Both are the same defect, and it was inside `opstore` itself:
`AdmissionControl.get`, `get_terminal`, `active_count` and
`pending_resume_count` read on the BARE connection, passing
`self._db.conn` to a helper (`self._fetch_terminal(self._db.conn, …)`,
`_count(self._db.conn, …)`). `opstore/tests/test_db_read_lock.py` exists to
forbid exactly that and could not see it: its pattern matched
`.conn.execute(`, so handing the connection to a helper walked straight
through. The event pump calls `get_terminal` on every terminal frame, so any
concurrent write turned a delegation into a failure, and `repairTargets`
correctly retried the part whose delegation failed. All four now take
`reading()`; both structural checks match the MENTION of the raw connection
rather than a call shape, which is what makes the aliased spelling visible.
The reproduction — six busy cores beside the gate — went from about one run in
ten to 0 in 40. The audit did not find the
defect underneath them: `POST /sessions/{id}/prompt` named no timeout, so a
whole TURN inherited `SupervisorConfig.default_timeout_s`, which is
`timeouts.tool_seconds` — a TOOL bound around a turn that runs a model round
trip plus every tool the model asks for, one of which the sidecar itself allows
`cad_build_seconds`. The watchdog's remedy for an overdue call is to kill the
entire sidecar, so a turn slower than 120 s destroyed every session in the
process. It surfaced as two flaky browser tests (CI run 34327109619) and would
have surfaced in production as a killed session on any slow model reply. Fixed
in two halves, both with regression tests: a turn is bounded by a new
`timeouts.turn_seconds` (600 s, the delegated child's own default, because a
delegated child turn IS a turn), and the watchdog now credits a pending call's
deadline with the time the child spent blocked on a `py.*` request this
supervisor had not answered yet — a child waiting on us is not unresponsive,
and the credit is the union of those intervals, never their sum.

**CORRECTION (2026-09-07), the L2/L6 constructor overlap.** The line above named
`core/src/hephaestus/core/types.py` as the only reason L6 runs after L2. It is
not the important one. J-agent-wiring-4's fix — "the CAD-ops constructor takes a
required backend, so the compiler finds every caller" — is *declared* in
`cad_ops/_base.py` (L6's) but is only **reachable** through `cad_ops/__init__.py`
(L2's): J-cli-startup-2 rewrote that module to assemble `CadOps` inside a
function, and the assembled class carries a deliberately signature-free
`__init__(*args, **kwargs)` that forwards to `CadOpsState.__init__`. That
forwarding is what makes L6's required keyword arrive at every construction
site, and — since the forwarded declaration is what pyright reads — a lane that
restated the signature there instead would fork the constructor across two files
and hide the drift from the type checker. So: **L6's constructor change lands
after L2's assembly rewrite, and neither lane may restate the other's
signature.** Landing them in the other order makes J-agent-wiring-4 look
complete while `CadOps(layout, store)` still type-checks.

**L7 — web layout, copy and state.** Owns `web/src/`, `web/test/`, `web/e2e/`
and `web/vitest.config.ts`. Items: J-web-viewport-1 through -5, -7, -9;
J-web-stream-1 through -12; J-cli-startup-8; J-mirrors-and-dx-19. J-web-stream-13
and -14 edit this lane's files but are generator work: they belong to L8, which
runs after this lane. Order inside
the lane: J-web-viewport-1 (two CSS lines) unblocks B-8; J-web-stream-1 (one CSS
line) unblocks J-web-stream-2; J-web-stream-4 before J-web-stream-6, which
closes J-web-stream-5 as a no-op.

**L8 — cross-language vocabularies.** Owns `schemas/` (except the `timeouts`
block L5 holds), a new generator beside
`contract/src/hephaestus/contract/toolgen.py`, and the generated modules it
emits. Items: J-mirrors-and-dx-1 through -10, J-web-stream-13, -14.
**Runs last** among the lanes that touch `server/src/hephaestus/http/context.py`,
`providers.py`, `sessions.py`, `agent_attach.py` (L4), `agent/src/rpc.ts`,
`agent/src/limits.ts` (L5) and `web/src/api/` and `web/src/stream/` (L7): its edits replace literals
with reads and are mechanical only once the behaviour above them has settled.

**STATUS (2026-09-07): DEFERRED BY DECISION, not dropped.** Waves 1-3 landed L1
through L7 and L9; L8 did not run, and the reason is the "runs last" clause
above rather than capacity. Its edits are mechanical only once the behaviour
above them has settled, and that behaviour moved in the same wave — §2.4's
envelope (L4), the bridge timeout classes (L5) and the stream client (L7) all
changed underneath the vocabularies L8 would generate from. Generating from a
definition still being argued about produces a generator that is rewritten with
it. The cost of the deferral, recorded so it is not rediscovered: adding a member
to any of these vocabularies still means editing every mirror by hand, and
nothing fails when one is missed — each item enumerates its mirror sites. The
same decision, with the same reasoning, is recorded in `INTERFACE.md` §19's
"Open by decision, not by oversight" paragraph, which is where a reader planning
new work will look.

**L9 — tests, CI and documentation.** Owns `pyproject.toml`, the workflow files,
`CONTRIBUTING.md`, `scripts/docs_check.py`, `scripts/bootstrap.sh`,
`server/src/hephaestus/testing/`, `tests/`, `opstore/pyproject.toml`,
`agent/tsconfig.json`, `agent/eslint.config.js`, `web/eslint.config.js`, and the
documentation set. Items: J-mirrors-and-dx-13 through -30 except -19 (L7's, in `web/test/`) and
-32 through -37; J-cli-startup-6; J-http-limits-5; J-cli-robustness-18, -19; J-http-envelope-17;
J-agent-results-S4. Order inside the lane: J-mirrors-and-dx-18 (the
`pinned_image` marker) before -22 and -30; J-mirrors-and-dx-32 (bootstrap in CI)
before -25; J-mirrors-and-dx-33 (widen the docs checker) before -29.
**Runs after L1** for `docs/cli.md`.

Every lane drafts its own INTERFACE.md amendments and hands them to L9, which
makes one editing pass per section. Three sections attract more than one lane —
§2.3/§2.4 (L4, L6), §5.5 (L7), §19/§20 (L9) — and editing them three times is
how a table gains two contradictory rows.

## Shared root causes

Ten mechanisms account for a hundred of the items below. They are stated once
here; each item names the one it belongs to rather than restating it.

**RC-1 — there is no single CLI error boundary.**
`core/src/hephaestus/core/cli.py` maps the engine taxonomy to exit codes in one
place and is bypassed ten times: `_UsageError` is redefined in
`core/src/hephaestus/core/cli.py`, `cli_assembly.py`, `cli_authoring.py`,
`cli_cam.py`, `cli_import.py`, `cli_motion.py`, `cli_references.py`,
`cli_registry.py`, `cli_solve.py` and
`server/src/hephaestus/agent_bridge/cli_export.py`, with eleven `_guard()`
wrappers. Each catches a different subset, none knows about `--json`, and
`core/src/hephaestus/core/cli_diff.py`'s additionally downgrades
`AddressingError`. Produces J-cli-robustness-5, -6, -10, -11, -12, -20, -22.

**RC-2 — import is registration, and a package `__init__` re-exports
everything.** `build_parser` registers a subcommand by importing its module, so
every module-level import in that module *and in its parent package* runs on
every `heph` invocation. Four of the five expensive sites are the same failure:
a cheap leaf (`mcp/cli_serve.py`, `http/cli_web.py`, `agent_bridge/cli_export.py`,
`geom/mesh.py`'s `MESH_UNITS`) cannot be reached without executing an eager
re-export block. `core/src/hephaestus/geom/__init__.py` already documents the
hazard for `solve` and the reasoning was never generalised. Produces
J-cli-startup-1 through -5, and J-cli-robustness-21 sits in the same six blocks.

**RC-3 — a closed vocabulary is transcribed rather than read.** The repository
single-sources numbers (`schemas/bridge_limits.json`, read at import) and tool
schemas (generated by `contract/src/hephaestus/contract/toolgen.py`, drift-tested)
and has no mechanism at all for closed *string* vocabularies, so twelve of them
were written by hand into two to four files each, every copy carrying a comment
naming the others as its mirror. `web/src/api/exports.ts` is the one place that
hit the wall and discharged it, with a test that reads the committed schema from
disk. Produces J-mirrors-and-dx-1 through -10, J-web-stream-13, -14.

**RC-4 — the engine's reason is relabelled or invented at a boundary.**
`server/src/hephaestus/agent_bridge/dispatch.py` rewrites every `AddressingError`
into `invalid_part`, discarding a code the engine already set correctly;
`server/src/hephaestus/http/app.py`'s `_part()` resolves nothing, so four routes
project a document about a part that does not exist; three `cli_*` handlers drop
the candidate list the central handler preserves. Produces J-http-envelope-3, -4,
J-agent-results-11, and the client half of J-web-stream-6.

**RC-5 — a machine string reaches a reading surface.** `JSON.stringify` output
in a check row, `f"{cause}: {detail}"` in a `role="alert"`, raw git stderr and a
full argv in a refusal body, an untruncated `str(exc)` beside a bounded `detail`,
a composed ledger key in an operator sentence, an internal terminal id as prose.
INTERFACE.md §4.7 already forbids the first by name and prescribes its shape.
Produces J-web-stream-6, -8, -9, J-http-envelope-11, -13, -15,
J-agent-results-11.

**RC-6 — the build record drops facts the worker computed.**
`core/src/hephaestus/core/types.py`'s `BuildResult` keeps the *hash* of the
params declaration and not the declaration, so no reader can answer "what are
this part's bounds?" from the current build and the HTTP route falls back to a
3 s sandboxed rebuild. The same file's own comments record the identical mistake
having been made and repaired twice before, for `metadata` and `checkpoints`.
Produces J-cli-startup-7, -9, B-5 in the broken ledger, and the latent
`check_names` case.

**RC-7 — the 3.35 s sandbox floor.** Measured with a trivial box:
sandbox spawn plus worker interpreter plus the build123d import, paid identically
by `build_part`, `probe_part_params`, `run_part_checks` and `run_dfm`. Every
item that touches it works around it with a hash-guarded read; the durable fix
is a warm pooled worker, which is its own design item and is deliberately not
smuggled into any of them.

**RC-8 — four hand-copied bounded-subprocess loops.** The same thirty-line
spawn/poll/deadline/drain/kill body appears in
`core/src/hephaestus/core/project_compare.py`,
`core/src/hephaestus/core/motion.py`,
`core/src/hephaestus/core/scan_compare.py` and
`core/src/hephaestus/core/placement.py`. The newest copy carries two correctness
fixes the two oldest never received, and all four answer a crashed child with the
*ceiling's* reason name. Produces J-build-state-3, -4, -5.

**RC-9 — declaration-first debt.** `schemas/bridge_limits.json` and
`contract/src/hephaestus/contract/tools_decl.py` declare bounds and result
members that no call site implements — `timeouts.cad_build_seconds`,
`binary.max_binary_bytes`, `admission.queued_prompts`, and the paging contract on
three read tools — while `architecture.md`, `agent/STAGE2_DIGEST.md` and
`tool_schema.md` state them as fact. `tests/stage2/test_bridge_bounds_limits.py`
institutionalised three of them as a pinned exception list rather than a failing
gate. Produces J-http-limits-3, -8, -9, -10, J-http-envelope-16.

**RC-10 — a gate that passes degenerately.** §5.5 C19's e2e selects the whole
section plate instead of its header and never mounts one, so it asserts nothing;
`tests/stage2/_g2.py` subclasses the shipped runtime and injects the wiring
production omits; `tests/stage7h/test_docs_set.py` asserts a verb *appears* in
the documentation and never executes an example; the renderer-pinned goldens are
excluded from CI by a hand-maintained path list rather than a marker. Produces
J-web-viewport-2, J-cli-robustness-18, -19, J-mirrors-and-dx-18, and the shape of
B-2 and B-12 in the broken ledger.

## CLI

### J-cli-robustness-5 — the "not a Hephaestus project" refusal exits 1 for ten verbs and 2 for four

**severity** medium · **surface** cli · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** — · **root cause** RC-1

**Symptom.** One condition produces two exit codes and two message shapes. A CI
script that branches on the exit code of `heph check` versus `heph part list`
gets different answers for the same broken working directory.

**Reproduction.** In an empty directory, run each verb in turn:

```console
$ mkdir noproj && cd noproj
$ heph part list; echo $?
heph: error (validation_error): no hephaestus.toml found at or above …
1
$ heph check; echo $?
heph: no hephaestus.toml found at or above …
2
```

Observed: exit 1 with the `error (validation_error):` prefix for part, params,
prompt, render, diff, scan, proposals, import, reference, export, assembly,
joints and motion; exit 2 with a bare `heph:` prefix for check, registry list,
cam emit and build. Expected: one code and one message, and per
`docs/cli.md` and `core/src/hephaestus/core/cli.py:59-60` that code is 2.

**Root cause.** RC-1. `find_project_root` raises `ValidationError`. Four call
sites wrap it — `core/src/hephaestus/core/cli.py:162-166` for build and check,
and the module-local `_project_root` in `core/src/hephaestus/core/cli_cam.py:82`
and `core/src/hephaestus/core/cli_registry.py:70` — and re-raise it as their own
`_UsageError`, which their `_guard` maps to exit 2. Every other verb calls
`find_project_root` directly and lets the `ValidationError` reach
`core/src/hephaestus/core/cli.py:836-838`, which prints the `error (…)` form and
returns 1. `git log -S'class _UsageError'` shows ten separate introductions
across seven feature commits, the first being b0715f6 "feat(core): Stage 0B CAD
engine, Gate G0B green"; nobody hoisted the first one. The spec is right and the
code is wrong on the exit-1 side, but the *documentation* contradicts itself:
`docs/cli.md` fixes exit 2 for "no project" in its exit-code table and then
prints the exit-1 message shape as its worked example.

**Fix.** One boundary. Add `cli_errors.py` beside
`core/src/hephaestus/core/cli.py` exporting `UsageError`,
`guard(command, *, json_attr="json")`, `project_root_or_refuse(start)`,
`ensure_writable_dir(path, flag)` and `refuse(exc, *, json_out)`.
`project_root_or_refuse` wraps `find_project_root` and raises `UsageError` with
today's message text. Delete the ten module-local `_UsageError` classes and the
eleven `_guard` functions in favour of the shared pair; `guard()` reproduces
`main()`'s taxonomy exactly, so a module `main()` behaves like the real CLI
(J-cli-robustness-20 falls out of this). Re-export `UsageError` as `_UsageError`
from `core/src/hephaestus/core/cli.py` for one release so the raise sites can be
migrated in a second pass. Amend the worked example in `docs/cli.md` to the
exit-2 form so the table and the transcript agree. Breaking for scripts that
branch on exit 1 for those ten verbs — the documented value is 2, and the message
text is unchanged apart from the dropped prefix; call it out in a release note.

**Tests.** A parametrised `core/tests/test_cli.py` case over the full verb list
derived from `build_parser()`, asserting exit 2 and the bare message shape
outside a project. It is red for ten verbs and green for four today, which is
what makes the diff mechanical and reviewable. The existing
`test_build_outside_project_exits_2` and `test_check_outside_project_exits_2`
become instances of it.

### J-cli-robustness-6 — `--json` is ignored on refusals

**severity** medium · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-cli-robustness-5 · **root cause** RC-1

**Symptom.** With `--json` requested, a refusal prints prose to stderr and leaves
stdout empty. A caller piping stdout into a parser sees an empty document and
cannot tell "refused" from "crashed".

**Reproduction.** `heph part show nosuch --json` prints
`heph: part 'nosuch' does not exist under …/parts (candidates: bracket, primary)`
on stderr, exits 2, and writes nothing to stdout. Same for
`heph diff primary part:nosuch --json` (exit 1) and
`heph export unpin notahash --json` (exit 2). Expected: a JSON refusal envelope
on stdout carrying `status`, `code`, `message` and, for an addressing error,
`candidates`, with the exit code unchanged.

**Root cause.** RC-1. Every `_guard` and `main()` formats refusals with
`print(..., file=sys.stderr)` and has no access to `args`:
`core/src/hephaestus/core/cli.py:807-838` receives only the exception, and the
eleven wrappers close over the command rather than the parsed namespace. The one
place that honours the flag, `core/src/hephaestus/core/cli_solve.py:234`, proves
the pattern was wanted and was never hoisted — it arrived with the Stage 13A
solve verbs, years of commits after the first `_guard`. `docs/cli.md` already
documents a JSON refusal for `part create`'s `already_exists`, and
`server/src/hephaestus/agent_bridge/dispatch.py` always returns a structured
refusal, so the direction is settled and applied in two places out of twenty.

**Fix.** Make `guard()` namespace-aware: it receives `args`, so on refusal it
checks `getattr(args, "json", False)` and emits one envelope shape on stdout —
`{"status":"error","code":…,"message":…}` plus `candidates` for an addressing
error — instead of prose on stderr. Exit codes are unchanged. `main()` already
has `args` in scope and passes the same flag into `refuse()`. Verbs whose refusal
already has a bespoke JSON shape keep theirs; `refuse()` is only the fallback.
Add a paragraph to `docs/cli.md` after the exit-code section stating the envelope.
Additive for anyone parsing success output; a caller scraping stderr under
`--json` would need updating, and there is none in the tree.

**Tests.** A parametrised `core/tests/test_cli.py` case over every verb that
registers `--json`, asserting a refusal produces parseable JSON on stdout and an
empty stderr; derive the verb list from `build_parser()` so it self-maintains.

### J-cli-robustness-14 — OCCT writes ANSI diagnostics to stdout

**severity** high · **surface** cli · **verdict** partially confirmed ·
**effort** M · **risk** medium · **depends on** — · **root cause** —

**Symptom.** The auditor reported a stderr leak. It is a **stdout** leak, which
is materially worse: `heph diff … --json` on a malformed STEP emits only an
ANSI-coloured OCCT string on stdout, and `heph serve --mcp` uses stdout as the
JSON-RPC transport.

**Reproduction.** Admit a malformed STEP and diff against it, splitting the
streams:

```console
$ printf 'ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n' > /tmp/bad.step
$ heph import add /tmp/bad.step
$ heph diff primary import:bad.step --json 2>/dev/null
\x1b[32;1m**** ERR StepFile : Incorrect Syntax : Fails Count : 1 ****\x1b[0m
```

Observed: stdout carries exactly that line and nothing else; the named refusal
goes to stderr (`2>&1 1>/dev/null` keeps only
`heph: error (validation_error): import 'bad.step' is not a readable STEP part`).
Also reproduces on the first uncached `heph build` of a part importing it.
Expected: stdout carries the JSON refusal envelope or nothing.

**Root cause.** `core/src/hephaestus/geom/step_io.py:86` runs OCCT's STEP parser
in-process, and OCCT's `Message_Messenger` installs a printer on C++ `std::cout`,
which shares fd 1 with Python and is invisible to any Python-level redirection.
Nothing in the tree ever mutes it — a grep for `Message_`, `SetTraceLevel` or
`printer` across `core/src/hephaestus/` returns nothing. This is a *parent*
leak, not a worker leak: `core/src/hephaestus/core/executor/sandbox/bwrap.py:354-361`
captures the worker's streams with `subprocess.PIPE`, but `stage_import` →
`_convert_step` (`core/src/hephaestus/core/executor/imports.py:706-762`) runs in
the harness, converting each import once before staging it, so both
`heph diff` (`core/src/hephaestus/core/project_compare.py:344-350`) and the first
build of an importing part parse STEP in the CLI process. `docs/cli.md` states
the contract flatly — under `--mcp` on stdio, stdout is the transport and
diagnostics go to stderr, always — so the code is wrong and the spec is
unambiguous. A symptom-only fix cannot work: filtering the string, or
redirecting `sys.stdout`, does nothing about a write from C++ to fd 1, and
fixing only `step_io` leaves the mesh path and every other in-parent OCP call
able to print.

**Fix.** Two layers, because the messenger API is version-sensitive. Add
`occt_messages.py` under `core/src/hephaestus/geom/` exporting
`quiet_messenger()` — which removes the default printer from OCP's default
messenger, or installs one that routes into Python logging at DEBUG — and a
`kernel_quiet()` context manager that `os.dup2`s fd 1 onto fd 2 for its duration
and restores in a `finally`. Call `quiet_messenger()` wherever OCP is first bound
in `core/src/hephaestus/geom/__init__.py`; wrap the reader block at
`core/src/hephaestus/geom/step_io.py:80-98`, the two conversion sites in
`core/src/hephaestus/core/executor/imports.py`, and the `read_step_bytes` call in
`core/src/hephaestus/core/project_compare.py:344`. Redirect always to fd 2, never
conditionally, so the same code is correct for the CLI and for MCP. Add one line
to `repo_conventions.md` requiring in-parent kernel calls to run under
`kernel_quiet()`, so the next one inherits the rule. No output-format change on
any success path.

**Tests.** `core/tests/test_import_step.py` gains a subprocess test asserting
that `heph diff <part> import:bad.step --json` writes no ESC byte to stdout and
that stdout is empty or valid JSON; the same for a cold-staging build of a part
importing a malformed STEP; and a broad guard in `core/tests/test_cli_pipeline.py`
that for every `--json` verb the suite exercises, stdout parses as JSON.

### J-cli-robustness-21 — six `except ImportError: pass` blocks delete a verb

**severity** high · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** — · **root cause** RC-2

**Symptom.** Any `ImportError` anywhere in the transitive closure of
`agent_bridge.cli`, `cli_export`, `cli_bench`, `mcp.cli_serve` or `http.cli_web`
silently deletes the corresponding verb. The user sees
`invalid choice: 'serve'`, which is exactly what they would see if the server
package were simply not installed.

**Reproduction.** Inject a broken dependency ahead of a real one:

```console
$ echo 'raise ImportError("No module named brokendep", name="brokendep")' > /tmp/inj/fastmcp.py
$ PYTHONPATH=/tmp/inj heph serve --mcp
heph: error: argument command: invalid choice: 'serve' (choose from 'build', …)
```

Observed: `serve` is absent from the usage line entirely, exit 2, and nothing
mentions fastmcp, brokendep or an import failure. Expected: the verb present and
refusing by name, or a message naming the missing module and saying the server
package is installed but incomplete.

**Root cause.** `core/src/hephaestus/core/cli.py:751-798` holds six
`try: … except ImportError: pass` blocks with no inspection of `exc.name`.
`ImportError` cannot distinguish "the module I asked for is absent" from
"something it imports is absent", and the comments at
`core/src/hephaestus/core/cli.py:744-746` state the intent — the engine CLI stays
Node-free and fully functional without the server package, which `PACKAGING.md`
governs and which is correct — implemented with a net wide enough to swallow
genuine breakage. `git log -S'except ImportError:' -- core/src/hephaestus/core/cli.py`
returns six copies across five commits, beginning with 7b9c89b "feat(agent):
Stage 2A runtime core — bridge, sidecar, tool codegen, heph agent". The verbs
affected pull the heaviest graphs, so they have the most transitive dependencies
to break. Narrowing one block leaves five, and re-raising would break the
supported core-only install: the fix must discriminate.

**Fix.** Discriminate on `exc.name`. Add a helper to
`core/src/hephaestus/core/cli.py` — `_optional_verb(sub, module_path, register, verb)`
— which imports, and on `ImportError` compares `exc.name` against the module
path: a missing module that is the package (or its parent) means the package is
genuinely absent, so skip silently as today; anything else, including a `None`
name, registers a **stub** subparser whose handler prints
`heph: the 'serve' verb is installed but could not load: <exc>` and returns 2.
The stub keeps `heph --help` honest and makes the failure self-diagnosing. Note
that the nested block at `core/src/hephaestus/core/cli.py:792-798` currently lets
a broken `http.cli_web` take `--mcp` down with it; the two halves of `serve` must
be reported separately. Document the two message shapes in `docs/install.md` so a
user can tell an uninstalled package from a broken one. The core-only install is
byte-identical.

**Tests.** `core/tests/test_cli.py`: with a monkeypatched importer raising
`ImportError(name="hephaestus.agent_bridge")` the `agent` verb is absent (the
supported case); with `ImportError(name="some_third_party")` the verb is
registered and invoking it exits 2 naming the module; a broken `http.cli_web`
does not remove `--mcp`.

### J-cli-robustness-3 — `heph registry pin` writes an absolute host path into a committed manifest

**severity** high · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** In a fresh project on a machine with an editable install,
`heph registry list` reports registries living inside the developer's clone, and
`heph registry pin dfm` writes that absolute path into `hephaestus.toml` — a file
the documentation tells you to commit. The project is then unusable on any other
machine.

**Reproduction.** In a fresh project, `heph registry list` prints
`path: /home/<user>/…/hephaestus/registries/dfm`; `heph registry pin dfm` then
adds a `[registries.dfm]` block whose `path` is that absolute string, beside a
digest. Expected: a project-relative path, or a symbolic marker meaning "the
registries bundled with this installation" that resolves per machine.

**Root cause.** `core/src/hephaestus/core/registry/_pins.py:129-136`'s
`bundled_registries_root()` walks `Path(__file__).resolve().parents` for a
directory containing the bundled registry tree, which under an editable install
is the clone root. `bundled_pins()` at
`core/src/hephaestus/core/registry/_pins.py:139-148` then builds a `RegistryPin`
whose `path` is that absolute string, and
`core/src/hephaestus/core/cli_registry.py:205-231` takes it as the value to
persist when `--path` is omitted: a runtime-resolution convenience leaking into
persisted state. `git log -S'bundled_pins'` shows the concept beginning as a
read-time fallback in 5329250 "feat(agent): Stage 2B product layer — full tool
surface, thread-phase, registries, bench" and later being reused as a *write*
source. There is a second, undocumented behaviour split: `pyproject.toml` excludes
the registry tree from the wheel, so on a real wheel install
`bundled_registries_root()` returns `None` and the same command refuses "has no
recorded path". `docs/registry-pinning.md` shows the canonical pin as a
project-relative path and says a pin in git is a reviewable claim about which
bytes a design was verified against — an absolute path into somebody's home
directory is exactly the note-to-yourself that clause rules out. Rewriting the
path as relative at write time would produce a worse string and leave the deeper
problem: the pinned bytes are the *installation's*, so the digest a teammate
verifies against depends on which version they installed.

**Fix.** Give bundled registries a symbolic identity. `bundled_pins()` returns
`path="bundled:<kind>"`; `RegistryPin.resolve()` maps that scheme through
`bundled_registries_root()` at read time and raises a named `ValidationError`
when the installation ships none, naming `--path DIR` as the remedy. Refuse, in
`core/src/hephaestus/core/cli_registry.py`, to persist any absolute path outside
the project root that did not come from an explicit `--path`. Keep
`heph registry list` printing the resolved path — an operator wants to know where
the bytes are — and add the symbolic form as a field in its `--json` record. Add
a "Bundled registries" subsection to `docs/registry-pinning.md` stating that the
digest still pins the bytes and that a machine whose installation ships different
bytes fails `heph registry verify` by design; amend the absolute-path example in
`docs/cli.md`. Old absolute pins keep resolving, so there is no migration.

**Tests.** `core/tests/test_registry_digest.py`: `bundled_pins()` returns
`bundled:` paths and `RegistryPin.resolve` round-trips them; `heph registry pin dfm`
in a temporary project writes the symbolic form and the manifest text contains no
absolute path; with `bundled_registries_root` patched to `None` a project pinning
`bundled:dfm` refuses by name rather than tracebacking; an explicit `--path`
still records what the operator asked for.

### J-cli-robustness-1 — `reference add --name` classifies the name, not the source file

**severity** medium · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Registering a file under an operator-chosen name is refused for an
unsupported extension `''`, because classification runs on the name rather than
on the file being registered. The documented example, `--name bearing-datasheet`,
is one of the refused forms.

**Reproduction.** `heph reference add ../wk/note.txt --name ds` →
`heph: error (validation_error): reference 'ds': unsupported extension ''
(supported: ['.jpeg', '.jpg', '.md', '.pdf', '.png', '.txt'])`, exit 1;
`--name ds.txt` succeeds. Expected: `registered ds (document, text/plain, 1 page(s))`,
the kind and mime coming from `note.txt`.

**Root cause.** `core/src/hephaestus/core/project_store/references.py:352-370`'s
`add_file` computes `target_name` and hands only the *name* to `add_bytes`, which
calls `classify(name)` at `references.py:382` — a pure suffix lookup at
`references.py:119-133`. `add_bytes` is the bytes-only entry point where the name
is the only source of truth; `add_file` has the source path and discards it.
`git log -S'def add_file'` returns one commit, eb0c2f2 "feat: Stage 8A ingest —
import_step expression term + reference documents/images": the bytes entry point
was written first and the file entry point layered on top, inheriting a
classification it did not need. INGEST.md makes `kind` a stored property of the
entry, and `references.py:75`'s name pattern explicitly permits an extensionless
name, so the spec and `docs/cli.md` both already promise the working behaviour.
Appending the source suffix to the name instead would change the name a later
requirement ledger cites, so the classification, not the name, must move.

**Fix.** `add_bytes` gains a keyword-optional `mime_type`; when it is `None` it
classifies from the name as today, otherwise it derives the kind from the mime
sets. `add_file` classifies `path.name` and forwards the result, and passes the
source name into `_check_magic` so a mismatched source is still caught. Add one
clarifying sentence to `docs/cli.md` — the kind and mime come from the source
file's extension, and `--name` may be any plain filename. Additive at the API
level; names previously refused now succeed and no stored entry changes.

**Tests.** `core/tests/test_cli_references.py`: a text file under an
extensionless name lists as `document`/`text/plain`; the documented `.pdf` form
with `--name bearing-datasheet`; an unsupported *source* extension is still
refused whatever `--name` says; `add_bytes` with no mime still classifies from
the name.

### J-cli-robustness-2 — `heph lint --request` without `--requirements` is a silent no-op

**severity** medium · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** The flag documented as "the rule that catches a model inventing a
spec" does nothing on its own: it is accepted, the file is read, zero findings
are produced, exit 0. The output is identical with and without it, and because a
missing path *is* refused, the flag looks live.

**Reproduction.** `heph lint parts/primary.py --request /tmp/req.txt` prints
`parts/primary.py: clean`, exit 0. Expected: `unsourced_requirement` findings, or
a usage refusal saying `--request` needs `--requirements`, exit 2.

**Root cause.** `core/src/hephaestus/core/cli.py:522-531` populates `entries`
only inside `if raw_requirements is not None`, and the `--request` branch at
`core/src/hephaestus/core/cli.py:550-565` calls `lint_requirements(entries, …)`
with that empty list. The rule is a join between a ledger and a request text and
one operand is missing, so it yields nothing by construction. Both flags landed
in 379edd7 "feat(validation): Stage 2V validation ladder, Gate G2V green"; the
guard at `core/src/hephaestus/core/cli.py:525` was written to protect the
threshold-vs-ledger rules and the request branch simply reuses `entries`.
`docs/cli.md` is ambiguous — it names both flags and then attributes the rule to
`--request` alone — while INGEST.md makes `unsourced_requirement` a join that
structurally needs the ledger. Rewording the documentation alone leaves a
validation tool that accepts a flag, reports "clean", and lets a user conclude
the rule passed.

**Fix.** Refuse the incomplete pair, following the precedent at
`core/src/hephaestus/core/cli_solve.py:442-449`: early in the lint handler, a
`--request` with no `--requirements` raises `UsageError` naming the join and the
governing section, exit 2. Extend the flag's help text and rewrite the
`docs/cli.md` paragraph so both flags are required together, showing the
two-flag invocation as the worked example. Nothing in the tree passes `--request`
alone.

**Tests.** `core/tests/test_lint_ledger.py`: the lone flag exits 2 naming
`--requirements`; the two-flag form over a ledger entry with no support in the
request text produces exactly one `unsourced_requirement` finding — which
positively pins a rule that is untested through the CLI today.

### J-cli-robustness-4 — `--project` is a boolean on `check` and a directory elsewhere

**severity** low · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** One flag name means two things in one CLI, and the collision
surfaces as a bare argparse error with no hint that this verb's `--project` takes
no value.

**Reproduction.** `heph check --project ./demo` →
`heph: error: unrecognized arguments: ./demo`, exit 2.

**Root cause.** `core/src/hephaestus/core/cli.py:626-632` registers `--project`
as `store_true`; `server/src/hephaestus/agent_bridge/cli.py:582` and
`server/src/hephaestus/http/cli_web.py:74-79` register it with `metavar='DIR'`.
`store_true` consumes nothing, so the directory becomes an unmatched positional.
The boolean is the original (b0715f6 "feat(core): Stage 0B CAD engine, Gate G0B
green") and the directory meaning arrived with `heph agent` in 7b9c89b, so the
later, more visible meaning created the collision. `docs/cli.md` documents both
and is silent on the clash; nothing in the parser construction detects it.
Improving the message alone keeps two meanings for one name and leaves the trap
for the next engine verb that wants a directory.

**Fix.** Rename the boolean to `--snapshot`, keeping `--project` as an accepted
alias via a single `add_argument("--snapshot", "--project", dest="project", …)`
so no script breaks and the handler is untouched. Then add a build-time invariant
in `build_parser()`: after every subparser registers, walk the built actions and
assert no option string maps to both a zero-arity and a value-taking action
across verbs — the same shape as the route-table drift check the HTTP layer
already runs at import. Keep it cheap; `build_parser` is the startup hot spot.
Document `--snapshot` in `docs/cli.md` and note the former spelling.

**Tests.** `core/tests/test_cli.py`: the two spellings behave identically; a
synthetic subparser registering a conflicting arity raises at `build_parser()`.

### J-cli-robustness-7 — `--json` listings: one envelope, four bare arrays

**severity** low · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** —

**Symptom.** `heph part list --json` returns an object with `status`; `import
list`, `reference list`, `registry list` and `lint --json` return bare arrays. A
generic wrapper cannot treat list verbs uniformly and the array verbs have
nowhere to put a status or a future cursor.

**Reproduction.** `heph part list --json` → `{"parts": [...], "status": "ok"}`;
`heph import list --json`, `heph reference list --json` and
`heph lint parts/primary.py --json` → `[]`; `heph registry list --json` → a bare
array of objects.

**Root cause.** Each verb prints its own JSON with no shared serializer.
`core/src/hephaestus/core/cli_authoring.py:126-140` emits the tool projection,
which is already an envelope because the CLI and the tool return the same bytes
by design (8709f21 "CLI: agent-shaped heph part/script/params/prompt verbs");
`core/src/hephaestus/core/cli_import.py:418`,
`core/src/hephaestus/core/cli_references.py:93` and
`core/src/hephaestus/core/cli.py:566` each `json.dumps` a list directly, and
`server/src/hephaestus/agent_bridge/cli_export.py:121-156` built a third, richer
envelope independently. Nobody chose the array form; it is what `json.dumps` of a
list produces. `docs/cli.md` documents `--json` per verb without fixing a shape,
so this is a convention gap rather than a violated clause — which is why it is
low, and why changing one verb without writing the rule down would just move the
inconsistency.

**Fix.** Write the convention into `repo_conventions.md`: a `--json` listing
emits an object with `status` and one plural array key, never a bare array. Wrap
the four; `lint --json` becomes `{"status": …, "findings": [...]}` with the status
reflecting whether any error-severity finding is present. Update the affected
rows in `docs/cli.md` and re-record the sample in `docs/registry-pinning.md`.
Breaking for any consumer parsing those arrays; nothing in the tree parses them —
the web client uses the HTTP API — so version it in a release note and sequence
it after the higher-value work.

**Tests.** A parametrised `core/tests/test_cli.py` case: for every listing verb
that registers `--json`, the output parses to an object containing `status`.
Drive the verb list from a small explicit table so adding a listing verb forces a
conscious entry.

### J-cli-robustness-8 — `heph import list` loses the declared unit

**severity** medium · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** `--units` is compulsory on a mesh import and is echoed back on add,
and then stored nowhere: neither `import list` nor `import list --json` shows a
unit, so the operator cannot recover what they declared.

**Reproduction.** `heph import add /tmp/tri.stl --units mm` prints
`copied tri.stl (mesh, units=mm) …`; `heph import list --json` returns
`[{"kind":"mesh","name":"tri.stl","path":"imports/tri.stl","sha256":"…"}]` — no
`units` key.

**Root cause.** `core/src/hephaestus/core/cli_import.py:345` threads the unit into
the human line and into the generated part script and writes it to no store.
`core/src/hephaestus/core/cli_import.py:408-426` reconstructs every record by
walking the filesystem and hardcodes `units=None` at
`core/src/hephaestus/core/cli_import.py:417`, so the `if units is not None`
branch of `_record` never fires for a listing. There is no imports index at all:
`imports/` is the only state. The tell is that `_record` was designed to carry a
unit and had no source for it on the list path. MESH_INGEST.md's whole
justification for the compulsory flag is that the unit is *not recoverable from
the file* — which makes discarding it after admission the exact failure the
clause guards against. Printing the unit back out of the seeded part script would
only work for imports that used `--part` and would depend on a script the user
may have edited.

**Fix.** Record admissions in project state. Check
`core/src/hephaestus/core/project_store/projections.py` first — `heph build`
already synchronises import state, so extend that projection rather than adding a
second store; failing that, add an imports index modelled on the
generation-under-lock pattern in
`core/src/hephaestus/core/project_store/references.py`. `_cmd_add` records
`{name, kind, digest, units}` after the copy; `_cmd_list` joins the index against
the filesystem walk so a hand-copied file is still listed, with a null unit and a
`recorded: false` marker rather than being hidden. Say in `docs/cli.md` and
MESH_INGEST.md that the declared unit is recorded with the admission. Additive:
pre-existing imports report a null unit and must not be refused.

**Tests.** `core/tests/test_cli_import.py`: an import declared in inches lists as
inches; a STEP import reports no unit at all (the flag is forbidden there); a
file hand-copied into the imports directory is still listed with a null unit.

### J-cli-robustness-9 — `heph import add` silently re-admits under a contradictory unit

**severity** medium · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-cli-robustness-8

**Symptom.** Re-adding an already-admitted mesh with a different `--units`
succeeds with exit 0 and no warning. Any part script or scan already written
against the first declaration now describes a different physical object, and
nothing says so — and after J-cli-robustness-8 the contradiction is invisible in
the listing too.

**Reproduction.** `heph import add /tmp/tri.stl --units mm` then the same file
with `--units in`: both print `copied tri.stl (mesh, units=…)` and exit 0.

**Root cause.** There is no admission record to conflict with, so
`core/src/hephaestus/core/cli_import.py:342-402` has nothing to compare against,
and the copy helper is deliberately idempotent-by-rename. The invariant is
understood one layer down and never surfaced: the staging layer at
`core/src/hephaestus/core/executor/imports.py:706-762` makes the unit part of the
staged artifact's identity, so two declarations already produce two distinct
staged blobs. MESH_INGEST.md bakes the declared unit's scale into the staged
canonical blob, so a silent re-declaration silently changes geometry that earlier
work depends on. Warning on stderr without refusing would leave the mutation in
place and, since the CLI records nothing, leave no way to audit which unit any
import currently carries.

**Fix.** Once the admission index exists, make re-admission checked: identical
bytes and identical unit is an idempotent success naming the prior admission; the
same name with different bytes or a different unit is refused
`import_bytes_conflict` / `import_unit_conflict`, naming both declarations, with
an explicit `--redeclare` flag as the escape. Reuse the existing ingress error,
which already carries a reason. On a successful `--redeclare`, mark dependent
parts stale, mirroring the rule that a replaced import makes its importers stale.
Document the three outcomes in `docs/cli.md` and name the two reasons in
MESH_INGEST.md.

**Tests.** `core/tests/test_cli_import.py`: same file twice with the same unit is
exit 0 and one index entry; the same name with a different unit is exit 1 naming
both units, with the imports directory unchanged; with `--redeclare`, exit 0, the
index updated, and every importing part marked stale.

### J-cli-robustness-10 — unknown-part messages assert the wrong fact, and `diff` downgrades the error

**severity** medium · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-cli-robustness-5 · **root cause** RC-1, RC-4

**Symptom.** `heph render nosuch` and `heph diff primary part:nosuch` both say
the part "has no current successful build", sending the user to build a part that
does not exist. `diff` additionally reports exit 1 with no candidates where
`render` reports exit 2 with them.

**Reproduction.** `heph render nosuch` →
`heph: part 'nosuch' has no current successful build to inspect (candidates: bracket, primary)`,
exit 2. `heph diff primary part:nosuch` →
`heph: error (addressing_error): part 'nosuch' has no current successful build to compare`,
exit 1, no candidates. Expected from both:
`part 'nosuch' does not exist under …/parts (candidates: …)`, exit 2, with the
build-state message reserved for a part that exists and was never built.

**Root cause.** Two defects. The message:
`core/src/hephaestus/core/render/inspect.py:386-392` and
`core/src/hephaestus/core/project_compare.py:289-296` both test
`current is None or current.artifact_ref is None` and raise one error for two
distinct conditions without first asking whether the part exists — with the part
list right there, already being passed as `candidates`. The exit code:
`core/src/hephaestus/core/cli_diff.py:167-171` catches `HephaestusError` broadly,
so `AddressingError` never reaches `core/src/hephaestus/core/cli.py:812-818`'s
dedicated arm, which would have printed the candidates and returned 2. The two
message sites arrived in different commits and copied the same phrasing;
`core/src/hephaestus/core/project_store/store.py:224-229` gets it right for
`read_part` and is what `heph part show nosuch` prints, so the correct wording
already exists in the tree. `core/src/hephaestus/core/assembly.py:134-141` is the
governing vocabulary and is explicit that a missing part and a part with no
current build are separate named reasons *because the fix differs*; ASSEMBLY.md
forbids conflating them. Fixing only the wording leaves `diff`'s exit code and
candidate list wrong, which is the half a script consumes.

**Fix.** Check existence before build state at both sites, reusing the store's
exact wording, and delete `cli_diff`'s local guard so `main()`'s arm applies (or
adopt the shared `guard()` from J-cli-robustness-5, which handles it). Audit the
six sibling sites for the same conflation —
`core/src/hephaestus/core/cam.py`, `core/src/hephaestus/core/scan_compare.py`,
`core/src/hephaestus/core/assembly.py`, `core/src/hephaestus/core/placement.py`
and `core/src/hephaestus/core/render/posed.py` — and check the assembly one
routes to its existing `missing_part` reason. No spec change: the vocabulary is
already correct. `heph diff` on a missing part moves from exit 1 to the
documented exit 2 and gains candidates.

**Tests.** `core/tests/test_render_inspect_cli.py`: `render nosuch` says "does
not exist", exit 2, with candidates; a part that *exists* and was never built
still says "has no current successful build" — the guard against over-correcting;
and a diff-level case for the exit code. A parametrised test across the sibling
sites asserting the two states produce two different messages.

### J-cli-robustness-11 — `heph export list <unknown part>` reports "no exports recorded", exit 0

**severity** low · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-cli-robustness-5 · **root cause** RC-1

**Symptom.** Filtering on a part that does not exist is indistinguishable from
filtering on a real part with no exports. A typo reads as a clean answer.

**Reproduction.** `heph export list nosuchpart` → `no exports recorded`, exit 0.
Expected: the refusal `heph part show nosuchpart` gives — the part does not
exist, with candidates, exit 2.

**Root cause.** `server/src/hephaestus/agent_bridge/cli_export.py:108-120` passes
the name straight into a records filter; a name matching nothing yields an empty
list, which falls into the `if not rows` branch at
`server/src/hephaestus/agent_bridge/cli_export.py:159-161`. The part name is
never validated against the project's parts even though the layout is in scope
two lines above. This is a genuinely local omission — the verb was written as a
read-only filter and filters return empty — but `core/src/hephaestus/core/cli.py:60`
fixes "unknown part" as exit 2 across the CLI and three sibling verbs honour it.

**Fix.** Validate the filter argument before filtering, raising the same
`AddressingError` shape with candidates that
`core/src/hephaestus/core/project_store/store.py:224-229` uses, so this does not
become a fourth spelling of "unknown part"; the local guard must map it to exit 2,
which the shared `guard()` does. Keep "no exports recorded" for a real part with
no rows. One clause in `docs/cli.md`.

**Tests.** `server/tests/test_cli_export.py`: an unknown part exits 2 with
candidates; a real part with no exports still prints "no exports recorded", exit 0.

### J-cli-robustness-12 — `heph lint .` says "no such file" about a directory

**severity** low · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-cli-robustness-5 · **root cause** RC-1

**Symptom.** Pointing lint at a directory produces a message that is false — the
path exists — and no hint that lint takes one script.

**Reproduction.** `heph lint .` → `heph: no such file: .`, exit 2. Expected:
a message naming the real condition and the shape of a correct invocation.

**Root cause.** `core/src/hephaestus/core/cli.py:508-510` treats
`not path.is_file()` as absence, and `Path('.').is_file()` is false for the other
reason. The same conflation appears at `core/src/hephaestus/core/cli.py:534` and
`core/src/hephaestus/core/cli.py:552`, at
`core/src/hephaestus/core/cli_authoring.py:95`, and at
`core/src/hephaestus/core/cli_references.py:70` and
`core/src/hephaestus/core/cli_import.py:337` — six sites with one copied idiom,
none a regression. Neither `docs/cli.md` nor the code is wrong in a contract
sense; the message is simply inaccurate, which is why this is low. Fixing one
site leaves five identical misstatements.

**Fix.** Add `require_input_file(path, *, what)` to the new `cli_errors` module,
distinguishing missing from not-a-file, and adopt it at all six sites with the
right noun for each (`part script`, `requirements file`, `request file`). Whether
`heph lint DIR` should lint every part script is a feature question, not a bug
fix; if taken, `heph lint` with no argument meaning the whole project is the
shape that matches `heph check`. Message text only; the exit code stays 2.

**Tests.** Extend the existing missing-file case in `core/tests/test_cli.py` with
a directory case asserting the not-a-directory wording, and the same for the
references and import verbs.

### J-cli-robustness-13 — `heph goldens` with no flag refuses instead of verifying

**severity** low · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** B-10

**Symptom.** A bare verb with exactly one useful mode refuses rather than doing
it or showing help, so the flag adds a step without adding a decision.

**Reproduction.** `heph goldens` →
`heph goldens: nothing to do (pass --update to regenerate)`, exit 2.

**Root cause.** `core/src/hephaestus/core/cli_render.py:186-190` refuses when the
update flag is absent, and the flag is registered as a plain `store_true` at
`core/src/hephaestus/core/cli_render.py:270` rather than as one of two modes. The
guard exists because regeneration is destructive and the author wanted an explicit
act — a sound instinct expressed as a dead flag. Unchanged since 1dc94c9
"feat(render): Stage 1 render service and grounded observation, Gate G1 green".
`docs/cli.md` shows only the update form and explains the dirty-tree refusal as
the safety mechanism, so the safety argument is already carried elsewhere and the
flag is a second belt; the exit-code table reserves 2 for "you asked for something
impossible", and asking for nothing is not that. Changing the exit code to 0 alone
leaves a verb that does nothing by default, which is the actual complaint.

**Fix.** Give the verb a read-only mode: with no flag it verifies the corpus
against the committed sidecars — renderer string, script hash, per-image digests
— prints a per-golden table and exits 1 on drift, 0 otherwise, the same shape as
`heph registry verify`. Extract `verify_goldens(out_dir, specs)` beside the
updater in `core/src/hephaestus/core/render/goldens.py` so the CLI and
`tests/render/test_goldens.py` share one implementation instead of the test
asserting the renderer string inline. Document both modes and their exit codes.
If the verify mode is judged out of scope, the minimum is: no flag prints the
subparser help and exits 0.

**Tests.** `core/tests/test_render_inspect_cli.py`: the bare verb against the
committed corpus exits 0 (marked slow — it renders); a corrupted sidecar exits 1
naming the drifted golden. Refactor `tests/render/test_goldens.py` onto the
shared verifier.

### J-cli-robustness-15 — `heph check` badges an unevaluated check FAIL and prints its error object

**severity** medium · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** A check that could not be *evaluated* is reported as a failed
*measurement*: the human output shows `FAIL (measured: {"error": {…}})`. The
spec's four-value badge vocabulary collapses to two, and `error` reads as `fail`.

**Reproduction.** Add a project check whose predicate addresses a nonexistent
part and run `heph check`:
`raiser:raises: FAIL (measured: {"error": {"type": "AddressingError", …}})`,
exit 1. Expected: `raiser:raises: error — addressing_error: unknown part …`, and a
line that does not claim a measurement was taken.

**Root cause.** `core/src/hephaestus/core/cli.py:419-427` renders a two-valued
verdict and unconditionally dumps the measured object. The correct classifier is
one import away: `core/src/hephaestus/core/checks/report.py:92-110` returns
`not_run`/`error`/`pass`/`fail` and is documented there as deliberately ranking
`error` above `fail`, because a check that could not be evaluated has no verdict
to report. The CLI printer predates it (b0715f6) and the classifier was extracted
later, when the HTTP route and the web badges needed the four-value vocabulary
(bb546fd "feat(stage4): server/http + the read-only web workspace"); the CLI was
never retrofitted. `heph check --json` is already correct and is bound to the web
client by a byte-parity gate, so only the human column is wrong. Prettifying the
measured column alone would keep the FAIL badge — asserting a verdict the engine
declined — and leave `not_run` unrepresentable in the CLI at all.

**Fix.** Import the shared classifier in `core/src/hephaestus/core/cli.py` and
print its state; for pass and fail keep the measured value, for error print the
code and message extracted from the measured envelope, and handle the
unverifiable shape the same way. The exit code stays 1 whenever anything is not
`pass` — an unevaluated check is not a green run — but the word must not be FAIL.
Document the four states and the exit rule in `docs/cli.md`. Do **not** touch
`--json`: it is bound to the web client by byte parity.

**Tests.** `core/tests/test_cli.py`: a raising predicate prints `error`, not FAIL,
and not the raw dict; a check hitting the wall-clock ceiling prints `error` for
the unverifiable shape; pass and fail rows are unchanged; and a parity assertion
that the printed state equals the shared classifier's for every check in a report.

### J-cli-robustness-16 — `--expected-hash` is never validated

**severity** medium · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Any string is accepted. The conflict document then reports a
`base_snapshot_ref` manufactured by prefixing an artifact kind onto user input —
a malformed ref handed back as if it named something.

**Reproduction.** `heph script write primary --file parts/primary.py --expected-hash bogusnothash --json`
exits 1 with a conflict whose `base_snapshot_ref` is
`artifact:part-snapshot:bogusnothash`. Expected:
`heph: --expected-hash must be 'sha256:<64 hex>' (got 'bogusnothash')`, exit 2 —
a malformed hash is usage, not a conflict.

**Root cause.** `core/src/hephaestus/core/cli_authoring.py:245-247` checks only
truthiness and passes the raw string down; on mismatch the conflict payload at
`core/src/hephaestus/core/cli_authoring.py:109-119` publishes the synthesized ref.
The tool surface has the identical shape at
`server/src/hephaestus/agent_bridge/dispatch.py:760-774`, so the CLI is faithfully
mirroring an unvalidated tool contract and the gap is shared, not CLI-only. Both
halves were written to validate presence and not format (8709f21 mirroring
7b9c89b). `docs/cli.md` distinguishes a *stale* hash (a conflict, exit 1) from a
*missing* one (usage, exit 2) and has no third case for malformed, so the spec is
incomplete and the code treats malformed as stale. Validating only the CLI leaves
the tool surface minting the same malformed refs for models, which is the
higher-traffic path.

**Fix.** One content-hash validator used by both. Add `parse_content_hash(value)`
to `core/src/hephaestus/core/hashing.py`, which already owns hash formatting,
accepting the prefixed form and normalising a bare 64-hex digest, raising
`ValidationError` otherwise. Call it in the CLI inside the usage region so a
malformed value exits 2, and in the dispatcher and params paths so a malformed
`expected_hash` returns `validation_error` rather than a conflict. Fold in the
hand-rolled digest check in
`server/src/hephaestus/agent_bridge/cli_export.py:291-297` so there is one
grammar. Add the third case to `docs/cli.md` and say in `tool_schema.md` that a
malformed `expected_hash` is a validation error. Well-formed stale hashes behave
exactly as before.

**Tests.** `core/tests/test_cli_authoring.py`: a malformed value exits 2 naming
the expected form; a well-formed stale one still returns the conflict document.
A dispatcher test for the `validation_error`, and unit tests for the parser
covering both spellings, short, long and non-hex.

### J-cli-robustness-17 — `solve placement --bound bogus` is accepted and means nothing

**severity** medium · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** —

**Symptom.** A `--bound` with no `=` is accepted as an unbounded window on a
variable named `bogus` — a flag whose own help says "never clamped in silence" is
silently ignored. Because the constraint checks fire first, the malformed bound is
never reported even on the failing path.

**Reproduction.** A `solve placement` invocation with `--bound bogus` and no
declared constraint refuses `declare at least one --constraint ID`, exit 2, never
mentioning the bound; adding a nonexistent constraint refuses that instead,
exit 1, still silent about the bound. Tracing the parser at
`core/src/hephaestus/core/cli_solve.py:489-506`: partitioning on `=` yields an
empty window, partitioning that on `:` yields two empty bounds, both map to
`None`, and the entry becomes an unbounded window with no error at any point.

**Root cause.** Two defects. The parser raises only on a float conversion
failure, so a spec with no separator is indistinguishable from a legitimately
half-open window, and no check confirms the variable is a real free variable. And
the ordering: the request is constructed at
`core/src/hephaestus/core/cli_solve.py:453-467` *before* the argument-shape checks
at `core/src/hephaestus/core/cli_solve.py:470-472`, with the semantic refusals
later still, so pure-argument errors are reported after — or instead of — being
reported at all. The parser was written lenient so half-open windows would work
and the leniency swallowed the missing separator; the help text at
`core/src/hephaestus/core/cli_solve.py:337` states the intent it does not enforce.
Requiring only the `=` leaves an unknown variable name still silent, and leaving
the ordering means a user fixing one argument error at a time pays a full solve
setup per run.

**Fix.** Require the separator and the window's colon in the bound parser, with a
message naming the expected form. Hoist every pure-argument check — provenance,
weighting, non-empty constraints and free set, bounds, starts — above the request
construction and collect them, so several bad flags produce one refusal listing
all of them. After the free set is resolved, refuse a `--bound` naming a variable
that is not in it, reusing the existing invalid-request refusal rather than
inventing a reason. Apply the same ordering to the pose and params solve verbs,
which share the pattern. Say in `docs/cli.md` that argument-shape errors are
reported before the project is opened.

**Tests.** A solve CLI case: a separator-less bound exits 2 naming the flag
*without needing a project*, which is what proves the ordering; an unknown
variable is refused by name once the free set is known; genuinely half-open
windows still parse; several bad flags produce one refusal listing all of them.

### J-cli-robustness-20 — module `main()` entry points traceback where `heph` refuses

**severity** low · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-cli-robustness-5 · **root cause** RC-1

**Symptom.** `python -m hephaestus.core.cli_render` and its three siblings do not
map the engine taxonomy, so the condition `heph` refuses cleanly produces a raw
traceback under the module entry points tests and tooling use.

**Reproduction.** From a non-project directory, invoking the render module
directly raises `ValidationError: no hephaestus.toml found at or above …` as a
traceback, exit 1, where the real CLI prints a one-line refusal and exits 2.

**Root cause.** `core/src/hephaestus/core/cli_render.py:280-291`,
`core/src/hephaestus/core/cli_registry.py:485-496`,
`server/src/hephaestus/agent_bridge/cli.py:606` and the bench CLI each build a
parser and call the command with no `try/except`; the taxonomy lives only in
`core/src/hephaestus/core/cli.py:807-838`. Each `main()` was added alongside its
module as a test convenience and none inherited the taxonomy, because the taxonomy
was never extractable. These entries are documented as test-only, so the blast
radius is tests and manual debugging — but it means a test exercising a module
`main()` observes different behaviour from the product, which weakens those tests.

**Fix.** Extract the taxonomy from `main()` into `dispatch(command, args)` in the
new `cli_errors` module — the body of `core/src/hephaestus/core/cli.py:807-838`
plus the `OSError` arm the B-10 family adds — and have all five entry points call
it. Note in `CONTRIBUTING.md` that a module `main()` goes through it. Module entry
points change from traceback to refusal; grep for tests asserting
`pytest.raises(ValidationError)` around a module `main()` before landing.

**Tests.** A parametrised case over the five entry points asserting identical exit
codes and no traceback for the same no-project condition.

### J-cli-robustness-22 — `--project` resolves differently on `heph agent` and `heph serve --web`

**severity** medium · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-cli-robustness-5 · **root cause** RC-1

**Symptom.** The same directory, the same failure, two exit codes and two message
shapes — on the two verbs whose comments each assert they mirror the other, and
which the documentation says resolve identically so `heph agent` can find the
serve record `heph serve --web` wrote.

**Reproduction.** In a non-project directory, `heph agent --project .` →
`heph: not a Hephaestus project (no hephaestus.toml found at or above .: …)`,
exit 2; `heph serve --web --project .` →
`heph: error (validation_error): no hephaestus.toml found at or above .: …`,
exit 1.

**Root cause.** `server/src/hephaestus/agent_bridge/cli.py:369-373` wraps the
resolver in a broad `except Exception` and refuses with exit 2;
`server/src/hephaestus/http/cli_web.py:138` does not resolve at all, passing the
root down so the error propagates to `core/src/hephaestus/core/cli.py:836-838`
and returns 1. The two verbs *do* agree on the not-a-directory precheck — that
half was consciously mirrored, comment and all — and diverge only on the
not-a-project half, because one resolves eagerly and the other defers. Each
file's comment asserts parity with the other; they were written in different
commits and neither was tested. `docs/cli.md` demands parity and names the
`validation_error` shape, which is the serve behaviour, while its own exit-code
table and `core/src/hephaestus/core/cli.py:59-60` put "no project" at exit 2 —
so the code is wrong and the documentation is internally inconsistent about which
of the two is correct.

**Fix.** Route both through the shared `project_root_or_refuse`, and make
`serve --web` resolve **eagerly** so both fail at the same point with the same
message; pass the resolved root into the serve entry point. Replace the broad
`except Exception` on the agent side, which also swallows non-validation bugs.
Keep both not-a-directory prechecks exactly as they are — they agree and their
comments explain why the walk-up must not apply there. Replace the two mutually
referential comments with one pointing at the shared helper, so the parity claim
names a mechanism rather than a promise. Amend `docs/cli.md` to name the actual
shape. `serve --web` moves from exit 1 to 2; confirm the eager resolve does not
change where the serve token and record are written.

**Tests.** A parametrised case over both verbs for a non-project directory, a
file and a missing path, asserting identical exit codes and identical stderr
bodies — the test whose absence let two comments claim parity for three stages —
plus a real subdirectory inside a project still walking up for both.

### J-cli-startup-1 — `heph` startup is 2.9 s: five registration sites import the CAD and MCP stacks

**severity** high · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** — · **root cause** RC-2

**Symptom.** Every `heph` invocation, including `heph --version`, pays about
three seconds before printing anything.

**Reproduction.** `heph --version` measured 2.885 s, 2.888 s, 2.937 s;
`heph --help` 3.391 s and 3.112 s. A bare interpreter start is 0.016-0.020 s and
importing the CLI module alone is 68 ms, so ~2.8 s is spent inside
`build_parser()`. Marginal per-module cost in registration order: the agent
bridge CLI 1707 ms, the MCP serve module 407 ms, everything else under 20 ms.
Expected, and measured on a prototype with all five sites deferred:
`build_parser()` 108 ms, total 0.142 s, no heavy module in `sys.modules`, and
`heph --help` byte-identical to today's output.

**Root cause.** RC-2. Five chains reach a heavy dependency:
`server/src/hephaestus/agent_bridge/cli.py:57-58` imports the app and the CAD ops
at module level, pulling `server/src/hephaestus/agent_bridge/cad_ops/__init__.py`'s
21 domain modules and, through `core/src/hephaestus/geom/metrics.py:49-55`,
build123d and OCP (1.60 s) plus scikit-learn (0.31 s); importing
`server/src/hephaestus/agent_bridge/cli_export.py`,
`server/src/hephaestus/mcp/cli_serve.py` and
`server/src/hephaestus/http/cli_web.py` each run an eager parent `__init__`
although all three leaves already defer their real work; and
`core/src/hephaestus/core/cli_import.py:444` imports the mesh unit tuple from
`core/src/hephaestus/geom/mesh.py` inside `add_subparsers`, running
`core/src/hephaestus/geom/__init__.py`. The single most expensive line was added
in b8b6a48 "feat(workspace): all ten plan items — composer, export, local-first
sign-in, design system" for two string helpers that live in a stdlib-only module.
Three comments in `core/src/hephaestus/core/cli.py` assert this registration is
free; measurement says otherwise, and `architecture.md`'s engine-first invariant
is honoured in letter (the CLI works without the server package) and violated in
spirit. Deleting the one obvious import leaves 1.1 s; fixing only the two sites
both audit reports name leaves 1.844 s, because neither found the mesh-units site.

**Fix.** Two structural moves. Make the four offending package `__init__` files
lazy with a module `__getattr__` over a name-to-submodule map, plus
`if TYPE_CHECKING` re-imports for the type checker; every existing `from … import`
consumer keeps working and pays only on first attribute access, and a submodule
import then executes a body that does nothing. Move
`server/src/hephaestus/agent_bridge/cli.py`'s five top-level imports into the
functions that use them — all five names are used only inside function bodies or
in string annotations, and `add_subparsers` needs neither, so the help text is
provably untouched. Do **not** make `core/src/hephaestus/geom/__init__.py` lazy:
its docstring makes the *omission* of the solver from that block a load-bearing
guarantee, and a `__getattr__` would silently restore reachability — relocate the
constant instead (J-cli-startup-5). Correct the three false comments and state the
invariant: registration may import only modules whose closure excludes build123d,
fastmcp, starlette and the geometry package. Public names are preserved in all
four packages, so there is no API change; verify with a strict type-check pass and
re-run the HTTP boundary test, which is an AST pass and is unaffected by a
`__getattr__`.

**Tests.** A subprocess test modelled on the existing import-boundary tests:
after `build_parser()`, `sys.modules` contains none of build123d, OCP,
scikit-learn, scipy, sympy, fastmcp, IPython, starlette or uvicorn. Plus a
byte-identical `heph --help` golden and per-verb help goldens for the four
affected verbs, so a deferred import that drops an argument is caught. Prefer the
`sys.modules` assertion to a wall-clock one: it is exact and CI-stable.

### J-cli-startup-2 — `cad_ops/__init__.py` makes registering `heph export list` cost 3.5 s

**severity** high · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-cli-startup-1 · **root cause** RC-2

**Symptom.** The comment at `core/src/hephaestus/core/cli.py:760-761` states that
the export verbs need no Node and no network and that `list` imports no geometry
kernel. Registering them imports build123d, OCP and scikit-learn.

**Reproduction.** Importing `server/src/hephaestus/agent_bridge/cli_export.py` in
a fresh interpreter takes 3498 ms and leaves build123d in `sys.modules`.
Expected: about 35 ms — its own module-level imports are argparse, json, sys,
pathlib, the project layout, the opstore and one leaf module whose own imports are
stdlib plus the opstore.

**Root cause.** RC-2. `server/src/hephaestus/agent_bridge/cli_export.py:74`
imports a submodule, so Python executes
`server/src/hephaestus/agent_bridge/cad_ops/__init__.py:91-198`, which eagerly
imports all 21 domain mixins to assemble the public surface; three of them pull
the geometry package. The leaf it wants,
`server/src/hephaestus/agent_bridge/cad_ops/export_history.py`, is never even
re-exported from that `__init__` — it has three consumers and is a pure leaf. The
package split (e6e919f "refactor: split cad_ops/registry/harness into domain
packages; explicit test support") created the eager aggregate; the comment was
written from the shape of the leaf's own imports without accounting for the
package init. Making this one verb register nothing would leave the aggregate
eager for the three other consumers and let the next module that reaches for an
export constant reintroduce the same 3.5 s.

**Fix.** Make the aggregate lazy with the same `__getattr__` pattern, preserving
its long public name list verbatim; this is J-cli-startup-1's change and this item
is its consumer. Rewrite the comment so it names the real mechanism. The narrower
alternative — moving the leaf up one level and leaving a re-export shim — fixes
this one site and nothing else, and is recorded only as a fallback. About twenty
in-repo consumers import names from the aggregate and all keep working through the
`__getattr__`.

**Tests.** Covered by J-cli-startup-1's closure assertion; add a focused
subprocess case asserting that importing the export CLI leaves build123d out of
`sys.modules`, so the specific claim in the comment is mechanically true.

### J-cli-startup-3 — the MCP package eagerly imports its app

**severity** high · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-2

**Symptom.** The comment at `core/src/hephaestus/core/cli.py:780-781` says the
handler imports FastMCP lazily so registering costs nothing. It costs 407 ms warm
and 2878 ms cold.

**Reproduction.** Importing `server/src/hephaestus/mcp/cli_serve.py` in a fresh
interpreter takes 2878 ms; warm, the residue is fastmcp at 207 ms (of which
IPython is 203 ms) plus the MCP package and pydantic. Expected: about zero — the
module is written to be free, importing its app inside the serve function.

**Root cause.** RC-2. `server/src/hephaestus/mcp/__init__.py:10` re-exports from
`server/src/hephaestus/mcp/app.py`, which imports fastmcp and the CAD ops, so the
entire geometry closure arrives before the leaf's first line runs. Both the eager
re-export and the registration were written in one commit, 687d8a1 "feat(mcp):
Stage 3 MCP server — FastMCP over the shared dispatcher, Gate G3 green"; the lazy
import inside the serve function shows registration was *intended* to be free and
the package init made it impossible. The ordering rules the module cites govern
import *direction*, not eagerness, so no clause is violated — only the comment is
false. Switching the import spelling in the CLI does not help: the parent runs
either way, and dropping the registration would delete `heph serve --mcp` from the
help output.

**Fix.** Lazy re-export in the MCP package `__init__`, with `if TYPE_CHECKING`
imports and a `__getattr__` over a name map; the public name list stays
byte-identical. Correct the comment to say both the handler and the package init
are lazy and that a test asserts it. Every existing attribute-access consumer,
including the MCP unit tests and the stdio flow gate, is unaffected.

**Tests.** A subprocess assertion that importing the MCP serve module leaves
fastmcp, the MCP package and IPython out of `sys.modules`, plus the shared
`build_parser` closure test.

### J-cli-startup-4 — the HTTP package eagerly imports the whole workspace API

**severity** high · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-2

**Symptom.** `server/src/hephaestus/http/cli_web.py` is the most expensive module
in the sweep at 4290 ms cold, despite importing nothing beyond argparse, sys,
pathlib and typing.

**Reproduction.** Importing it in a fresh interpreter takes 4290 ms; 9 ms when
everything else is already loaded — that is, all of its cost is its parent's.

**Root cause.** RC-2. `server/src/hephaestus/http/__init__.py:33-35` imports the
app (the closed route table, and through it starlette routing and every
projection), the principal module and the runtime, which pulls the CAD ops and
hence build123d, OCP and scikit-learn. The leaf is a textbook lazy registration
module defeated by its package init. Both arrived in bb546fd "feat(stage4):
server/http + the read-only web workspace"; the package docstring is entirely
about import *direction* — the author was thinking hard about which way imports
point and not at all about when they fire. A symptom fix that skipped the web half
of the serve verb would silently drop three flags from `heph serve --help`, which
is the regression the two-half assembly exists to prevent.

**Fix.** Lazy re-export in the HTTP package `__init__` with the same pattern,
preserving the public name list; extend the docstring's layer note with one
sentence saying names resolve on first access so a submodule import stays free.
The serve assembly in the CLI needs no change. Tests that import the app, runtime
and sessions modules directly are unaffected; re-run the HTTP boundary test
explicitly, since it is the file most sensitive to import-shape changes.

**Tests.** A subprocess assertion that importing the web CLI module leaves
starlette and build123d out of `sys.modules`, plus the shared closure test.

### J-cli-startup-5 — `MESH_UNITS` is imported from the geometry package at parser-build time

**severity** high · **surface** cli · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-2

**Symptom.** With the four server-side sites fixed, `heph --help` is still 1.8 s.
A fifth site, named by neither audit report, imports the whole geometry package
for a four-element tuple of unit names.

**Reproduction.** With the four package inits stubbed, `build_parser()` takes
1844 ms and loads build123d, OCP, scikit-learn, IPython, scipy and sympy; an
import spy traces the first build123d import to
`core/src/hephaestus/core/cli_import.py:444` inside `add_subparsers`, through
`core/src/hephaestus/geom/__init__.py` and
`core/src/hephaestus/geom/measure.py:42`. With the constant relocated,
`build_parser()` is 108 ms, no heavy module loads, and `heph --help` is
byte-identical.

**Root cause.** RC-2. The import is deliberately placed *inside* `add_subparsers`
rather than at module level — the author was import-cost-aware — but
`add_subparsers` is not the handler: it runs on every invocation. The constant
itself is a literal four-string tuple with no geometry in it. Introduced by
03da17a "engine: heph import add (STEP/mesh into imports/) (#36)".
`core/src/hephaestus/geom/__init__.py:55-65` already documents this exact hazard
for the solver and explains why re-exporting it there would "quietly make the
exclusion false while every test still passed"; the reasoning was never
generalised. Hard-coding the four values in the CLI would fix the 1.8 s and fork
MESH_INGEST.md's normative unit set into a second literal with nothing pinning
them together — precisely the failure the geometry docstring warns about.

**Fix.** Relocate the constant to `core/src/hephaestus/core/types.py`, which is
already on the geometry package's dependency allowlist and costs about 8 ms to
import, carrying its specification citation with it; re-export it from
`core/src/hephaestus/geom/mesh.py` so every existing import path and both internal
uses are unchanged; import the leaf from the CLI. Name the geometry package
explicitly in the new registration invariant alongside build123d, fastmcp and
starlette. No public path changes and the existing geometry import-boundary test
stays green with no edit.

**Tests.** An identity assertion that the two import paths yield the same object —
the anti-fork guard; the `build_parser` closure test extended to assert the
geometry package itself is absent; and a help golden for the import verb so the
unit choices stay pinned to four values.

### J-agent-wiring-4 — `heph agent` runs model-authored scripts with no OS sandbox

**severity** high · **surface** cli · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** The reported symptom was that `run_dfm` under `heph agent` always
refuses `unsafe_refused` while the identical call succeeds under `heph serve`.
The larger finding: `heph agent` is the only shipped verb that executes
model-authored part scripts with no OS sandbox, with no flag, and the warning it
prints names a flag the verb does not have.

**Reproduction.** Building the agent's CAD ops the way
`server/src/hephaestus/agent_bridge/app.py:364` does yields an unsafe local
backend and `run_dfm` refuses
`unsafe_refused: … unsafe-local backend refuses registry content; registry code
may only execute under a probed secure sandbox`; the serve construction yields a
bubblewrap backend and the same call returns ok. The build in the agent
configuration prints
`WARNING: --unsafe-local-executor: running the build worker WITHOUT OS sandboxing`
— naming a flag `heph agent --help` does not list.

**Root cause.** `server/src/hephaestus/agent_bridge/cad_ops/_base.py:268-271`
defaults to the unsafe local backend when none is injected, with a comment saying
it is for fast tests and that production wiring passes a probed secure backend;
`server/src/hephaestus/agent_bridge/app.py:364` builds the CAD ops with no
backend and `server/src/hephaestus/agent_bridge/cli.py:407-414` injects none. So
the *test* default is the shipped default for `heph agent`, and for the MCP stdio
mode too. `heph serve --web` escapes only because
`server/src/hephaestus/http/runtime.py:160` probes a secure backend and injects
it. The unsafe backend refuses any job whose origin is a registry, which is every
DFM predicate and every parts-store generator. The default came from e6e919f,
a *refactor* whose stated purpose was explicit test support; the one production
caller with no injection inherited it. `core/src/hephaestus/core/executor/sandbox/unsafe.py:9`
is the governing clause and says "Never a default"; `heph build` obeys it at
`core/src/hephaestus/core/cli.py:169-178`. Injecting a secure backend at the agent
CLI alone leaves the defaulting constructor for every future caller and would
silently break `heph agent` on a machine with no bubblewrap.

**Fix.** Make the unsafe backend impossible to acquire by omission: the CAD-ops
constructor takes a required backend, so the compiler finds every caller — the
~20 test sites then pass an explicit unsafe backend, which is what they intend.
Give `heph agent` the same explicit, warned opt-in `heph build` has: add
`--unsafe-local-executor`, export the existing backend-selection helper from
`core/src/hephaestus/core/cli.py` so all three model-facing runtimes share it
instead of copying the probe-and-warn logic a third time, and map a refused probe
to the verb's named exit-2 path. Give MCP stdio the same treatment. Reword the
warning so it stops naming one CLI's flag. Document the posture and the flag in
`docs/cli.md`. **Compatibility break:** `heph agent` on a machine with no working
bubblewrap currently builds unsandboxed and will refuse `sandbox_unavailable`
unless the flag is passed — the correct posture, matching `heph build` since Stage
0, but it belongs in release notes and in the troubleshooting section of
`docs/install.md`.

**Tests.** The constructor with no backend is a `TypeError`; `heph agent` with no
flag constructs a bubblewrap-backed CAD ops (skipped where bubblewrap is absent)
and with the flag constructs the unsafe one and prints the warning; with the probe
forced to fail the verb exits 2 with a named refusal, not a traceback; and
`run_dfm` through the agent's construction returns ok on a bubblewrap host, which
is the direct pin for the reported symptom.

## HTTP API

### J-http-envelope-3 — an unknown part is answered six ways, three of them 200

**severity** high · **surface** http · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** B-6, J-http-envelope-17 · **root cause** RC-4

**Symptom.** For a part that does not exist: the script route refuses
`invalid_part`, params and properties refuse `addressing_error`, build answers
200 `not_built`, checks answers 200 with the whole project report and the unknown
name echoed, DFM and exports answer 200 with empty documents, the inspect and DFM
posts refuse `invalid_part`, and only the context preview answers correctly with
404 `unknown_part`. A client cannot tell "this part is gone" from "this part has
never been built", and three routes fabricate a document about a part that does
not exist.

**Reproduction.** Request every part-scoped route for a name absent from the
project. Observed as above; expected 404 `unknown_part` with the known part list,
which INTERFACE.md's error table already specifies and which
`server/src/hephaestus/http/errors.py:135` already maps.

**Root cause.** RC-4, compounded. `server/src/hephaestus/http/app.py:304-305`
resolves nothing — it returns the path parameter as a string — so each route
discovers the miss, or does not, as a side effect: routes that reach the engine
through the dispatcher get the relabelled `invalid_part`, routes that call the
engine directly surface `addressing_error`, and routes that project a store read
with no part lookup return an empty projection with the caller's string echoed
into it. `server/src/hephaestus/http/context.py:385-401` is correct because it
checks the project's part list explicitly — the one place the check exists,
written when §7A.3 forced someone to ask the question and answered in the wrong
place to be shared. Patching each route would be six edits the next part-scoped
route does not inherit, and would leave the relabel wrong for every other
addressing miss.

**Fix.** Resolve the part where it enters the layer. Extract the context module's
membership test into a shared `resolve_part(runtime, name)` raising a 404
`unknown_part` with the part and the known list, and have
`server/src/hephaestus/http/app.py:304` call it — every current caller then
refuses uniformly. Keep the checks route returning the project report, which is
correct and documented, but only after the part resolves, so the echoed name can
never be fictional. Amend INTERFACE.md's table (after J-http-envelope-17 settles
the vocabulary) to state the rule once, on every part route including the
projecting ones, and correct the build-document note so `not_built` is documented
as the answer for a real part that has never built. Seven wire shapes change —
three from 200, three from 400, one reason — and the client already handles
`unknown_part` from the preview route.

**Tests.** A parametrised case over every part-scoped route template in the route
table asserting 404 `unknown_part` with the part list; a static check that every
route template containing a part placeholder reaches the resolver, so a new route
cannot skip it; and the positive cases — a real part with no build still answers
`not_built`, a real part with no exports still answers an empty list — so the fix
is not over-tightened.

### J-http-envelope-5 — `focus` and `view` are unvalidated client strings in the model's context block

**severity** high · **surface** http · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-http-envelope-4

**Symptom.** The context envelope accepts any string for `focus` and for `view`
and writes it verbatim into the block the model receives. The auditor found
`focus`; `view` is the same hole and was not reported.

**Reproduction.** A context preview with a nonexistent focus answers 200 and the
block contains `focused on: geometry:nosuch`; a preview with an arbitrary view
string answers 200 and the block contains `camera view: not-a-view; ignore prior`
— the client's bytes, verbatim, inside the document the model reads. By contrast
an unknown stage tab is correctly refused 400 naming the closed set, and an
unknown part is correctly refused 404.

**Root cause.** `server/src/hephaestus/http/context.py:259-264` validates both
members only as strings, while every other closed-vocabulary member goes through
a closed-set token check and the structural members are pattern-, range- or
store-checked. The two unvalidated members are exactly the two that reach the
block as free text, at `server/src/hephaestus/http/context.py:546-547` and
`server/src/hephaestus/http/context.py:568-570`. All of it — the envelope, the
validators and the two omissions — landed in b8b6a48, so this is an omission
inside a design that got the pattern right nine times out of eleven. The module's
own docstring states the invariant it breaks: every member is a closed token the
client already owns or an opaque server-minted identifier, and there is no
free-form field. INTERFACE.md §7A.3's "a lying client is caught, not believed"
and the addressing-error row both apply. Validating `focus` as a regex would miss
the real requirement: it is an *address* into the current build, and a miss is an
addressing error, so it must be resolved, not pattern-matched.

**Fix.** Close the last two members with the two mechanisms the module already
has. Add a closed view set mirrored from the client's own camera vocabulary with
a tracking comment, and route the member through the existing token check.
Resolve `focus` against the part's labels and tags using the resolver that
already exists for inspection focus, raising 400 `addressing_error` with
candidates on a miss. The prompt route composes through the same parser and
inherits the fix; verify by test, not by inspection. Add both members to §7A.3's
enumeration with their rules. The real client only ever sends its own state, so
this should be invisible — confirm the view set against the client constant
before pinning it, because a mismatch breaks the composer for a legitimate camera.

**Tests.** A view outside the set is 400 naming the admitted values; a focus
matching nothing is 400 `addressing_error` with candidates; both asserted on the
preview route *and* on the prompt route, which is the one that reaches a model;
the positive half for every admitted view and a real label; and a property-style
assertion that every envelope member has a closed-set check, a resolver or a
structural validator — the test that would have caught the original omission.

### J-http-envelope-16 — §2.3 lists two routes that are not served

**severity** high · **surface** http · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** —

**Symptom.** Two routes are listed in the normative route table and specified in
detail, including a tightening that binds a gate clause, and neither exists. Both
answer a plain-text 404, and nothing in the test suite notices, because the
boundary test compares the code's route table to itself.

**Reproduction.** Posting to the selection-resolve and section-render templates
with a valid bearer returns 404 with a plain-text body; neither template appears
in `server/src/hephaestus/http/app.py`'s route table.

**Root cause.** The table simply lacks the rows, and `build_app`'s drift check
asserts the served set equals the table — code against code. There is no check in
either direction against the specification's markdown table, and
`scripts/docs_check.py` has no route-table awareness. So the specification can
name a route that does not exist, indefinitely, with a green suite — and here it
has: §12.3 is written as shipped behaviour and a gate clause cites it as evidence,
so a gate row is currently evidenced by a 404. The rows date to the interface
draft; the implementation commit shipped 19 of 20 gate clauses and was explicit
that it did not land everything. What is missing is not the implementation
decision but the record: §2.3 was never marked, and no test binds the two tables.

**Fix.** Two separable decisions. The product question — are these Stage 5 work
or specification debris — is answered by checking whether the two engine functions
§12.3 names exist; if they do the routes are a thin binding, if not the clause is
unlanded. If unlanded, mark both rows as new work in the style the neighbouring
row already uses and add them to the unfinished register, which itself needs an
audit pass. If landing them, honour §12.3's tightening: an unlinked asset must
produce a stale-selection refusal server-side, never by the client reading asset
metadata. Either way, add the binding test: parse §2.3's route rows out of
INTERFACE.md — the tables are regular — and assert set equality with the route
table, modulo an explicit new-work allowlist. That requires widening the docs
checker to read INTERFACE.md at all (J-mirrors-and-dx-33), which is its
prerequisite.

**Tests.** The route-table binding test is the deliverable and is worth landing
before the product decision; if the routes are implemented, tests for both request
shapes including the unlinked-asset tightening.

### J-http-limits-1 — POST bodies are buffered whole with no ceiling

**severity** high · **surface** http · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-http-limits-2

**Symptom.** The prompt route accepts an 8 MB `text` and feeds it to the model —
a real token spend that ends in an overflow compaction and a failed run. The only
guard is a per-string 16 MiB cap that fires after the whole body is resident, and
unknown body members are silently ignored, so the padding never has to hide in
`text` at all.

**Reproduction.** An 8 MB prompt is accepted, 200, and forwarded. A prompt one
byte over the declared 32 KiB cap is accepted. A 64 MiB body carrying 64 unknown
1 MiB members is accepted, 200, in 2.11 s. A 16 MiB+1 string is refused 400
`json_string_too_large`. Expected: a body above a transport ceiling refused 413
before it is buffered, and a `text` above the declared cap refused 400
`prompt_too_large` — the reason two other prompt boundaries already raise.

**Root cause.** `server/src/hephaestus/http/app.py:273` reads the entire body into
memory, then decodes, parses and only then walks the structure; that walk enforces
depth, member count and per-value string size and has no aggregate rung, so the
theoretical ceiling is ten thousand members times 16 MiB. The prompt handler at
`server/src/hephaestus/http/app.py:1449-1487` type-checks `text` and passes it
straight down; the byte cap is imported and applied at every *other* prompt
boundary and never here. `heph serve --web` runs uvicorn with defaults, so there
is no transport guard either; above 64 MiB the frame layer finally objects, as a
supervisor error mapped to 503 `agent_unavailable` rather than a named size
refusal. Both halves of the omission arrived in bb546fd, a month after the prompt
cap was in force, so Stage 4 built a new prompt boundary beside an existing,
enforced limit and did not connect them. `agent/STAGE2_DIGEST.md` is unqualified:
the prompt is capped and enforced by four validators and is never truncated.
Capping only `text` leaves the buffering hole for every other POST route; capping
only the body leaves a 15 MiB `text` going to the model.

**Fix.** Two rungs, both sourced from `schemas/bridge_limits.json` so neither
becomes a seventh un-sourced literal. Add an HTTP request ceiling to the shared
limits document and export it beside the frame cap; in the body reader, reject on
`Content-Length` before reading and then stream, aborting past the cap so a
chunked body cannot evade it — peak allocation is then bounded by the cap rather
than by the sender. In the prompt handler, apply the existing UTF-8 byte enforcer
and map its refusal to 400. Add `request_too_large` (413) and `prompt_too_large`
(400) to the status table and to INTERFACE.md's §2.4 rows, and surface the byte
count in the composer so the operator learns the bound before the POST. Mirror
the new key in the TypeScript limits interface.

**Tests.** A body just over the ceiling, with and without a content length, is
413 with the limit and observed size; one byte under is accepted; a prompt at
exactly the cap succeeds and one byte over is 400 with no prompt recorded by the
fake agent; an astral-plane string measured as exact UTF-8 lands on the right side
of the boundary; and an assertion that a very large body is refused without being
buffered.

### J-http-limits-6 — the one request-path subprocess with no timeout

**severity** high · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-http-limits-2

**Symptom.** The git helper runs a subprocess with no timeout. With a `git` that
sleeps 30 s, one project request returned at 30.05 s and, while it was in flight,
requests for parts and for git status — one of which touches no git at all — both
timed out at the client's 20 s. Every other request-path subprocess in the
repository passes a timeout.

**Reproduction.** With a sleeping `git` shim on PATH and a real serve, one project
request took 30.05 s and two concurrent unrelated requests timed out at 20 s.
Expected: a bounded call and a named refusal past the ceiling, with no effect on
unrelated routes.

**Root cause.** `server/src/hephaestus/http/git_projection.py:111` runs the
subprocess with `capture_output` and `check=False` and no `timeout`. That helper
is the single choke point for four git routes, one post, *and* — through the
work-tree probe and the runtime's capability projection — the project route. The
git routes wrap it in a worker thread, so a hang there consumes one of forty pool
workers; the project route does not, so a hang there blocks the event loop, which
is why the demonstration takes down routes that never touch git. The module's
docstring argues carefully about argv safety and says nothing about time. The
two defects compose into a total outage and are separable: this item is the
timeout, J-http-limits-7 the event loop. Adding a timeout alone converts a total
outage into thread-pool exhaustion — slower to notice, same end state.

**Fix.** Bound the subprocess, name the refusal, and give the whole git reason
family rows in the status table so no git condition depends on the fallback: add
`git_timeout` (504) beside `git_verb_refused` (403), `git_failed` (400),
`git_unavailable` (503) and `not_a_git_repository` (404), which are hardcoded at
their raise sites today and would otherwise resolve to 400 (J-http-envelope-14).
Map the timeout expiry to a named refusal carrying the subcommand and the ceiling.
While in the function, route the raw stderr through the bounding helper
(J-http-envelope-11) and check the work-tree probe inherits the timeout. State the
bound in INTERFACE.md §2.9. A repository so large that a legitimate log or diff
exceeds the ceiling would newly refuse, so size it against a realistic project and
consider a larger bound for diff than for a ref lookup.

**Tests.** With a sleeping `git`, the status route returns 504 `git_timeout`
carrying the ceiling and the process keeps serving; a concurrency case asserting
an in-flight project request does not delay an unrelated one by more than a
second — the assertion that pins this item and J-http-limits-7 together; and a
closed-table assertion for the five git statuses.

### J-http-limits-7 — `GET /project` probes git and bwrap inline on the event loop

**severity** high · **surface** http · **verdict** partially confirmed ·
**effort** S · **risk** low · **depends on** J-http-limits-6

**Symptom.** The project route is `async` and calls the runtime's capability
probe synchronously, running both a git subprocess and the sandbox capability
probe on the event loop, while twenty-eight other sites in the same file use a
worker thread.

**Reproduction.** With a sleeping `git`, one project request blocked every other
route for its whole duration (see J-http-limits-6). With a `bwrap` shim that
stalls 25 s, the capability call cost 25.035 s and 25.034 s on two consecutive
calls — the probe is never cached on failure, by design, so every project request
pays it again. The audit's "cold probe up to 60 s" is the *ceiling*, not the
typical cost: measured cold on a healthy machine it is 61 ms, warm 3 ms.

**Root cause.** The runtime's capability map combines a sandbox-backend probe and
a work-tree check. The probe caches only *successful* results — deliberately, so
installing bubblewrap later is picked up — so an unavailable result is re-probed
on every call, and a probe means spawning a version check and then a full
sandboxed worker under a wall clock. The work-tree check goes through the
unbounded git helper. Neither is wrapped, and the file's own established pattern
is a worker thread; this route is the first in the read-routes section and the
shortest, written before the pattern hardened. No clause governs the ASGI layer's
threading, so this is an implementation defect against the file's own convention —
which is worth turning into a stated invariant. Moving the call off the loop alone
converts an event-loop stall into thread-pool consumption: on a machine where the
probe fails, every project request still pays 25-60 s and the web client polls
this route.

**Fix.** Move the capability call to a worker thread, matching the file's other
twenty-eight sites, and give the capability map a short time-to-live cache at the
runtime layer with an explicit refresh parameter, invalidated on attach, detach
and project rebind. Document why the cache lives there rather than in the probe:
the probe's fail-open re-check is right for a build about to run and wrong for a
projection served on every page load, and the 25 s measurement is what disproves
its "cheap" assumption. With J-http-limits-6's timeout the worst case becomes a
bounded git call plus a bounded probe, both off the loop. Add one normative
sentence that no route performs subprocess or blocking filesystem work on the
event loop, and note in the project row that capabilities may be up to the
staleness window old.

**Tests.** With a failing sandbox shim, two successive project requests perform
exactly one probe; the shared concurrency assertion from J-http-limits-6; and
refresh bypassing the cache while attach and detach invalidate it.

### J-cli-startup-7 — the params routes run a sandboxed CAD build to read a dict

**severity** high · **surface** http · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** — · **root cause** RC-6, RC-7

**Symptom.** Reading a part's parameter declaration takes 2.8-3.4 s in-process
(3.9-4.1 s over a socket; the write path 4.4-5.1 s) against 0.010 s for reading
the script it is declared in. A part that declares no parameters at all pays the
same.

**Reproduction.** In-process against the workspace fixture: the script route
0.010 s; the params route 3.151 s, then 2.755 s for a part that declares **zero**
parameters, then 3.439 s for an identical repeat — no caching. At the operations
layer the probe is 2.78-2.83 s and the sandboxed run 3.80 s; the floor for a
trivial box in the same sandbox is 3.346 s, so essentially all of it is sandbox
spawn plus worker interpreter plus the build123d import. The literal pass in
`core/src/hephaestus/core/params.py:282-316` returns identical declarations for
the same two scripts in 0.486 ms and 0.126 ms.

**Root cause.** RC-6 and RC-7. `server/src/hephaestus/http/app.py:638-644` calls
the probe, which at
`server/src/hephaestus/agent_bridge/cad_ops/_params.py:114-129` freezes inputs and
runs the full build path, then discards everything except two fields. Two cheaper
authorities exist and neither is consulted: the static literal pass that
`heph params` has used since 8709f21 "CLI: agent-shaped heph part/script/params/prompt
verbs" — written three days *after* the route shipped in bb546fd — and the last
build, whose worker computes the declaration on every build and whose publisher
revalidates its hash under locks, while `core/src/hephaestus/core/types.py:435-463`
persists only the *hash*. The same file's comments record that exact omission
having been diagnosed and repaired twice before, for two other fields. Caching the
probe still costs 3 s per part per serve and needs an invalidation key it does not
have; hiding the latency in the client leaves the write path and every model
`set_params` call at 4-5 s; and the worker cannot be optimised, since the floor is
a trivial box.

**Fix.** Persist the declaration on the build record, then resolve the read
through a three-tier ladder that attributes which tier answered. Tier 1, about a
millisecond: the current build's recorded declaration, when its input hashes
revalidate against the live script and parameters — this is the sandbox's own
answer, already hash-revalidated by the publisher, so it is authoritative for
bounds validation too. Tier 2, about half a millisecond: the static literal pass,
but only when every declared key resolved to a fully literal parameter, which is
exactly the completeness condition `heph params` relies on. Tier 3, unchanged: the
sandboxed probe, for a changed script carrying a computed parameter the literal
pass cannot resolve. Effective values recompose cheaply from declaration defaults,
the last build's values and the parameter store. Add a source field to the
projection so the client can say where the number came from, and keep the *write*
path on tiers 1 and 3 only — a write must never be validated against a
literal-only reading. Amend INTERFACE.md's params row with the resolution order
and the attribution, and `tool_schema.md` to say bounds validation resolves against
a sandbox-evaluated declaration, recorded or fresh. The new record field defaults
empty, so older records deserialise and fall through; no migration and no rebuild.
A **warm pooled worker** would cut the floor for every sandboxed operation at once
and is recorded here as the deferred alternative the ladder makes unnecessary for
reads.

**Tests.** The regression guard is shaped as an invocation count, not a
timing: spy the sandboxed run and assert it is invoked **zero** times for a part
with a current build and an unmodified script, and for a part with no build whose
parameters are all literal. Equivalence: for every part in the two corpus
fixtures, tiers 1 and 2 produce the same rows as the probe. Fall-through: a
computed default takes tier 3 and its rows carry real bounds. Staleness: editing
the script to change a bound and reading without rebuilding must not serve the
recorded declaration — the whole safety argument, and it shares its reasoning with
B-5, so review the two together.

### J-build-state-1 — `GET /parts/{part}/build` hides a newer failure and never populates `error`

**severity** medium · **surface** http · **verdict** partially confirmed ·
**effort** M · **risk** low · **depends on** B-5

**Symptom.** A part whose most recent build attempt failed reads as a healthy
success: the build post answers with the error, and an immediately following
build read answers 200 `ok`, `current: true`, the superseded artifact, no `error`
key and the old geometry count. The precedence is deliberate and pinned by a test,
so the defect is not that the failure is deprioritised — it is that the document
has no member in which to say the newest attempt failed. `heph part show` does not
even have the fallback, so the CLI and HTTP disagree for a first-fail part.

**Reproduction.** Build a part, replace its script with a raising statement,
build again — the post returns the error record with checkpoints — then read the
build route: 200, `ok`, `current: true`, no `error`, geometry count 1. Separately,
`heph part show --json` for a first-fail part emits `not_built` where the route
emits the failure.

**Root cause.** `server/src/hephaestus/http/app.py:606-616` reads two unordered
pointers with a fixed precedence and discards the loser; neither the build record
nor the bundle carries a timestamp, so the route could not ask which is newer even
if it wanted to. The projection emits `error` only when the record it was handed
carries one, so a current success structurally cannot produce the key — the
audit's "never populated" is a consequence of the precedence, not a separate bug.
The precedence itself is stated as intent in the operations layer's docstring and
asserted by a test, and was introduced narrowly by 3e5a9f1 "engine: project
statement checkpoints onto GET /build", whose message says in as many words that
current successful builds still win so the geometry count is unchanged. That
commit did not update the CLI, which is where the divergence entered. Inverting
the precedence would empty the geometry tree whenever a rebuild failed while a
good artifact was pinned, contradicting the viewport rule that a rebuild keeps the
last completed artifact; adding `error` to a successful record would violate the
record's own invariant.

**Fix.** Keep the precedence and add a `last_failure` member carrying the failed
record's error and checkpoints. Recency without adding a clock: a last-failure
record whose script hash *differs* from the current build's necessarily post-dates
it, and one whose hash matches predates it and is dropped — reusing a field
already on every record instead of a schema migration. Read both pointers
unconditionally (both are lock-free) and pass them into the projection. Give
`heph part show` the same fallback and the same member, making the "same document"
claim in INTERFACE.md's build row true again; amend that row to add the member and
to state the precedence and its reason, so the next reader does not re-litigate
it. Additive: the key is absent in every case that behaves as today, and no
status, geometry count or checkpoint field moves.

**Tests.** Extend the existing precedence test to keep every current assertion —
that is the by-design half — and add that the failure is reachable; a negative
case where a failure recorded *before* the current success leaves the member
absent, proving the recency rule discriminates; the first-fail path unchanged; and
a CLI/HTTP parity test across all three states.

### J-http-envelope-1 — `config_path` is merged onto a refusal §2.4 says must not carry it

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** —

**Symptom.** Every `agent_unavailable` raised below the runtime — the
sidecar-died-mid-request path — comes back carrying the provider configuration
path, which the specification states this path must not carry. A client following
the instruction to treat that field as present on the attach refusal and absent on
this one cannot tell the two apart.

**Reproduction.** Any sidecar-level failure returns a 503 body containing
`attached`, `config_path`, `generation`, `cause`, `detail`, `reason` and
`message`. Expected: `cause` and `detail` and deliberately not the path, because
a stale path is worse than an absent one — a client would act on it.

**Root cause.** `server/src/hephaestus/http/app.py:571-576`, inside the guard
wrapper's exception arm, merges the whole attach projection into any
`agent_unavailable` refusal that does not already carry the path, citing a promise
the §2.4 table used to make. `server/src/hephaestus/http/errors.py:369-382`, which
mints that refusal, carries the *opposite* comment — the path is deliberately
absent because this module never opens the providers file — and correctly omits
it. Both halves landed in one commit, e3ef904 "fix(server): re-adopt a session the
sidecar forgot, and refuse by name instead of an unnamed 500", and the
specification amendment that superseded the merge is that commit's own ancestor,
landing 66 minutes earlier. So the implementation was written against a reading of
the table the same branch had already corrected.

**Fix.** Delete the six-line merge. The refusal is already correct where it is
minted. Leave the attach projection helper alone — it is used by the two
attach-shaped refusals, which correctly carry the path — and add one line to its
docstring naming its two callers and saying it is not for the below-the-runtime
path; add a cross-reference at the minting site so nobody re-derives the merge.
No specification change: the clause is recent and explicit. Three keys disappear
from one refusal shape and no test asserts them there; the attach tests assert
them on the *attach* refusal and are unaffected. Land it with B-6, which edits the
same wrapper. B-11's fix carries the same six-line deletion, because the merge sits
inside the wrapper B-11 rewrites: it is one change, applied once, by whichever of
the two reaches the wrapper first.

**Tests.** A supervisor error with no error envelope, driven through a session
route on an attached runtime, produces `agent_unavailable` with a cause and a
detail and **no** `config_path`; and the mirror assertion that the attach refusal
still carries it, written as an explicitly paired contract.

### J-http-envelope-4 — a focus that matches nothing refuses `invalid_part`

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-http-envelope-17 · **root cause** RC-4

**Symptom.** An inspect request whose focus names no solid or tag answers 400
with reason `invalid_part` and a message about the focus. The reason names the
wrong thing — the part is fine — and the table has a dedicated row for exactly
this condition that this route never reaches.

**Reproduction.** Build a part, then post an inspect with a focus naming nothing:
400, `invalid_part`, candidates present, message
`focus 'geometry:nosuch' matches no labeled solid or tag`. Expected: 400
`addressing_error`, which is what the engine already raises at
`core/src/hephaestus/core/render/inspect.py:497-502`.

**Root cause.** RC-4. `server/src/hephaestus/agent_bridge/dispatch.py:425-428`
catches the engine's addressing error and re-raises it as `invalid_part`,
discarding `exc.code`. Every addressing miss in the engine — a bad part prefix, a
bad anchor, a bad focus — therefore arrives at the HTTP layer as `invalid_part`.
`server/src/hephaestus/http/errors.py:96-101` keeps a row for the correct reason
with a comment saying flattening it would make a clause untestable — and the
flattening happens one layer below where that comment is written, contradicting
the module header's rule that the reason strings are the engine's. The relabel
predates the HTTP layer (5329250), when `invalid_part` was the tool surface's own
vocabulary and the correct reason had no HTTP meaning. Special-casing the focus
message in the route would fix one refusal and leave every other addressing error
mislabelled, including on the MCP surface, which shares the dispatcher.

**Fix.** Stop rewriting the engine's code at the boundary: re-raise with
`exc.code` and the candidates. Verify no consumer branches on the old string from
this path — the delegation vocabulary defines its own unrelated constant — and
extend the status-table comment to record that the correct reason now arrives from
the dispatcher as well as from the direct-call routes. Settle the vocabulary in
INTERFACE.md first (J-http-envelope-17): a syntactically illegal part name is
`invalid_part`, a legal name the project lacks is `unknown_part`, and a selector
*inside* a part is `addressing_error`. The candidates ride through unchanged, so a
client that renders them is unaffected; check `tool_schema.md`'s documented refusal
vocabulary for the inspect tool.

**Tests.** An inspect with an unmatched focus on a part that exists and has built
asserts the correct reason with candidates — so the assertion is about the focus,
not the part; a dispatcher unit test that an engine addressing error surfaces with
its own code, asserted for two distinct raise sites so the test is about the rule;
and the sibling assertion that a syntactically invalid name is still `invalid_part`.

### J-http-envelope-6 — the attach cause is frozen at the last attempt and goes stale

**severity** medium · **surface** http · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** After writing a provider configuration, a credential route still
refuses 503 with cause "no provider config" while the providers listing reports
the configuration exists. The refusal tells the operator to do the thing they
have just done.

**Reproduction.** On a serve started with no provider configuration, write one,
then read the providers listing (reports the file exists) and an auth-status route
(still refuses with the stale cause).

**Root cause.** `server/src/hephaestus/http/runtime.py:329-334` returns a stored
attach state written at exactly three places — attach, attach failure and detach —
and the specs-write route touches none of them.
`server/src/hephaestus/http/agent_credentials.py:109-129` reads that stale object
and puts its projection straight into the refusal, so a fact about the last attach
*attempt* is presented as a fact about the present. Both the write route and the
cause-carrying refusal landed in b8b6a48. The §23 design deliberately separates
"write a config" from "attach a runtime" — a serve with no configuration must
still be able to read and write one — which is right; the consequence that the
cause outlives its condition was not followed through. The runtime's detach path
shows the authors were alert to the hazard in the other direction, with a comment
about not overwriting a real cause with one that never happened.
Special-casing the one cause fixes the observed sequence and leaves every other
cause with the same lifetime problem.

**Fix.** Invalidate on write rather than derive on read: add a runtime method that
recomputes the no-runtime state from disk under the existing attach lock,
preserving the generation counter, and call it from every route that changes what a
future attach would find. Do **not** attempt an attach — §23 separates the two
deliberately, and an implicit attach from a config write is the deadlock that
section removes. When a configuration now exists and nothing is attached, the
honest cause is "a config exists and no runtime has been attached to it"; if the
closed cause set has no member for that, the message must carry it, because the
vocabulary may not widen without a specification change — and a new member needs a
client change and a copy string. State in §7A.8 that the cause describes the
current reason, not the last attempt, and that a route changing what an attach
would find invalidates it. Recompute inside the lock and keep the generation
monotonic.

**Tests.** Open a workspace with no configuration, assert a credential route
refuses with the absent-config cause, write specs, and assert the cause is no
longer that and the listing agrees; assert the generation is unchanged by an
invalidation, since it counts spawns; and the detach direction, so a config write
cannot overwrite a state the operator did cause.

### J-http-envelope-7 — `thread_state` has two producers with two definitions

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** For the same session, the listing reports `unlinked` while the thread
route reports `linked`. The web client reads the first for its tab attribute and
the second for the tree, so one session is labelled both ways on one screen.

**Reproduction.** Create a session, record a child edge for it, then read the
listing (`unlinked`, no parent) and the thread route (`linked`, two nodes).

**Root cause.** Two independent derivations about 140 lines apart in one file:
`server/src/hephaestus/http/sessions.py:572` sets the state from the presence of a
*parent* edge alone, while
`server/src/hephaestus/http/sessions.py:429-437` sets it from a parent **or** any
children. A session that is a parent and not a child satisfies the second and not
the first. `web/src/stream/thread.ts` re-implements the second rule client-side
for the tab list while the panel takes the state from the listing, so both
definitions are present in the client too and the divergence is rendered. Both
landed in bb546fd; neither carries a note that the other exists, and the thread
projection's docstring explains its rule at length without mentioning the
listing's. The specification defines the two values and never defines the
predicate, so it permits both readings and therefore does not forbid the
disagreement — spec and code both need work. Editing either site to match the
other closes this instance and leaves three derivations of one field.

**Fix.** Decide the definition, implement it once on the edge store, and have both
projections call it. The right definition is "this session participates in a
thread" — parent or children — because that is what the UI uses it for and because
a session with children is manifestly not isolated. Delete the now-redundant
expression in the thread projection rather than leaving it as a second copy. Note
the cost: the listing does two edge reads per row instead of one, so if the listing
can be large, group the query while the code is open — it is a local read, not a
bridge probe, so the rule that the listing never probes the runtime is untouched.
Define the predicate normatively in the session sections and state that both routes
report the same value. Sessions that are parents flip from `unlinked` to `linked`,
which correctly removes the "why is this unlinked" copy from an orchestrator with a
quick-edit child.

**Tests.** For a session with a child edge, one with a parent edge and an isolated
one, both routes report the same value; a store-level unit test over the four
shapes including a session with both; and the client-side derivation asserted to
agree with the document-level state.

### J-http-envelope-8 — the thread route fabricates a one-node graph for any string

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** medium · **depends on** —

**Symptom.** The thread route answers 200 for a session id that has never
existed, returning a one-node tree naming it. A client cannot distinguish "this
session exists and is a root" from "this session does not exist", and the node it
renders is content the server invented about nothing.

**Reproduction.** Requesting the thread of an id no session ever had returns 200
with a single depth-0 node, `unlinked`, null parent — identically against the fake
backend and against a real sidecar.

**Root cause.** `server/src/hephaestus/agent_bridge/session_edges.py:194-218`
always synthesises a depth-0 root, deliberately and for a good reason stated in
its own comment: a session with no edges is a one-node tree, which is the honest
answer for a transcript that predates the edge table. That is correct for a
session that *exists*. The route passes the path parameter straight through with
no existence check — the same non-resolver as the part case. The route's comment
correctly explains why it must not gate on an *attached runtime*, since threading
is a durable fact, and that argument was allowed to also excuse not checking
whether the session exists, which is a different question with a different answer.
Rejecting unknown ids in the route alone would leave the store's synthesised root
available to any other caller with the same trap.

**Fix.** Check that the id names something before projecting a tree, against the
**durable** record rather than the attached runtime, so the route keeps the
property its comment defends: a session exists if it appears in the edge table as
parent or child, or has a persisted transcript, or is currently listed. Raise 404
`unknown_session` with the id — the reason the error module and the web client
already handle. Leave the store's synthesiser alone and add one docstring line
saying the caller is responsible for having established existence. If the durable
transcript check is awkward from that layer, the narrower correct fix is to refuse
when the id has neither an edge row nor a listing entry, accepting that with no
runtime attached a pre-existing edgeless transcript would 404 — record that limit
explicitly rather than leaving it implicit. State the refusal in the thread
section and keep the one-node answer for a session that exists with no edges: the
two must not be conflated, because that is precisely what the code does today.

**Tests.** An id that never existed is 404 with the id; the two positive cases —
an existing session with no edges still returns its one-node tree, and a session
with children returns the full tree, the second asserted with **no** agent
attached, pinning the route's independence from the runtime; and a session known
only through the edge table still answers 200.

### J-http-envelope-10 — the prompt route silently accepts unknown body members

**severity** low · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** A prompt body carrying a member the route does not know is accepted
and the run proceeds. A client that misspells the context member gets a turn with
no workspace context and no indication anything was dropped — the failure mode the
sibling preview route refuses by name.

**Reproduction.** Posting a prompt with an extra member returns 200 and the run
completes with the extra member ignored; the same shape on the context preview
route returns 400 naming the unexpected key.

**Root cause.** `server/src/hephaestus/http/app.py:1451-1489` reads three members
and never compares the key set against an admitted set, while
`server/src/hephaestus/http/app.py:819-827` does exactly that check for the
preview route and the envelope parser does it for the envelope's own members — so
the discipline exists twice in the module and is missing at the one route where
the consequence is a model turn rather than a preview. The prompt route predates
the context member; b8b6a48 added the member and, at the same time, added the
strict check to the *new* route without bringing the older one along. The
specification is silent for this body, and the principle is stated in the code
rather than the spec.

**Fix.** Add a `_closed_body(body, admitted, *, what)` helper beside the existing
body reader and call it from the prompt route, then replace the preview route's
open-coded set difference with it so there is one implementation. Audit the
remaining server-defined bodies — session create, answer, inspect, measure — and
apply it where the body is genuinely closed; do **not** apply it to a body that is
a tool's argument document passed through verbatim, since those are validated by
the canonical schema and a second gate would be a second table. State the rule
once in §2.3 with that exception named. The real client sends exactly the admitted
members.

**Tests.** An unknown member is 400 naming it; the full admitted set together is
accepted; and one parametrised assertion across every route the helper covers, so
the rule is tested as a rule.

### J-http-envelope-11 — `git_failed` returns the full argv and raw git stderr

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-http-envelope-14 · **root cause** RC-5

**Symptom.** A failed git subcommand returns its argv — including ref names and,
indirectly, filesystem structure — and git's unfiltered stderr as the refusal's
message: a channel from a subprocess straight to a browser, with no reduction, no
truncation and no redaction.

**Reproduction.** A diff against a bogus revision returns 400 with `argv`,
`returncode` and `message: fatal: bad revision 'deadbeefdeadbeef'`.

**Root cause.** RC-5. `server/src/hephaestus/http/git_projection.py:120-126`
raises with `completed.stderr` as the message and the argv in the data. The
module one directory over already has the pattern —
`server/src/hephaestus/http/agent_attach.py:191-204` truncates to a fixed budget
and redacts known secrets, and
`server/src/hephaestus/http/agent_credentials.py:133-142` states the rule: construct
an operator-facing sentence from the code and never echo what came back. The git
projection landed whole in bb546fd; the containment discipline arrived later with
§23 and was never applied backwards to the older subprocess boundary. The related
missing timeout in the same five lines is J-http-limits-6. Truncating the message
here leaves the argv, which is the more informative half.

**Fix.** Build the message from the subcommand and the exit code, move the stderr
into a bounded, reduced `detail` — lifting the existing reducer into a shared
module so git and credentials share one implementation rather than two — and drop
the argv, or reduce it to the subcommand name, which is already public through the
allowed-verb refusal. Add the timeout in the same edit. Strengthen §2.9 to say a
git failure returns a named reason, the subcommand and a bounded detail, never raw
stderr and never the argv, and add a general sentence to §2.4 that any refusal
text produced by a subprocess or a remote is bounded and reduced before it reaches
the wire.

**Tests.** A failing subcommand asserts the reason, a message that does not
contain git's stderr verbatim, a bounded detail and no argv key; a stderr
containing a long absolute path is truncated to the shared bound; and a timeout
case producing a named refusal rather than a hung request.

### J-http-envelope-12 — cancelling an unknown run refuses `not_found`, and the fake backend answers 200

**severity** low · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Cancelling a run the server never admitted answers 404 with the
generic `not_found`, a message naming an internal table, and no run id in the
data — on a route the specification calls idempotent by construction. Worse, the
fake backend answers 200 for the same request, so no in-process test can observe
the real behaviour.

**Reproduction.** Against a real bridge, cancelling an unissued run returns 404
`not_found` with the message "run … has no admission row"; against the fake
backend the same request returns 200 with an ok status.

**Root cause.** The route forwards to the backend, which forwards to admission
control, which raises the generic not-found error at
`opstore/src/opstore/admission.py:206`; nothing in the HTTP layer names the run or
picks a run-specific reason. The divergence exists because
`server/src/hephaestus/testing/fake_agent.py` implements cancel as a no-op with no
admission lookup, so the two backends disagree and only the sidecar-backed lane —
which skips silently without pnpm — sees the truth. The idempotence clause covers
a run that *existed*; it is silent on one that never did, so the specification is
under-specified and the code is inconsistent between backends. Adding the run id
to the data fixes the cosmetic half and leaves the divergence, which is what makes
the behaviour untested.

**Fix.** Decide once: a client asking to cancel an id the server never issued has
a bug, and a quiet no-op would hide it, while a run that did exist and has
finished stays 200 — which is what the idempotence clause is actually about.
Catch the admission miss and refuse 404 `unknown_run` with the id; the reason
needs no new table row, since the unknown-family rule already yields 404, but add
one anyway for the same reason the export equivalent has one. Then teach the fake
backend the same refusal — the load-bearing half, without which the contract stays
untested. Extend the idempotence note to say idempotence is a property of a run's
lifecycle, not a licence to accept an unknown address.

**Tests.** The unknown-run case asserted against **both** backends so they are
pinned to one answer; cancelling a completed run is still 200; and a unit
assertion that the fake and the real admission agree on the condition.

### J-http-envelope-13 — the idempotency refusal message embeds the composed ledger key

**severity** low · **surface** http · **verdict** partially confirmed ·
**effort** S · **risk** very low · **depends on** — · **root cause** RC-5

**Symptom.** A key-ladder refusal's message embeds the full internal ledger key:
namespace prefix, principal fingerprint, route template, the client's own key,
ordinal and lane — an internal composition rendered as an operator sentence.

**Reproduction.** A request whose idempotency key carries a far-past embedded
timestamp returns 409 `key_expired` with a message quoting the whole composed key.

**Root cause.** RC-5. `opstore/src/opstore/opkeys.py:178-184` formats the raw
identifier into both refusal messages, and the identifier reaches it fully
composed from the HTTP prefix, the principal's session id and the route template.
The error layer passes the engine's message through verbatim, correctly, since
§2.4 promises the engine's own message — the opstore's message was written for a
log, and §2.4 later made every engine message a wire message, and nobody revisited
the ones that assumed a private audience. **Correction to the audit's framing:**
the fingerprint is a truncated hash of the bearer and the only party who can
receive the message is one holding a valid bearer for this serve, so this is an
internal identifier in an operator sentence, not a credential disclosure — hence
low.

**Fix.** Keep the engine's reason verbatim and give the operator a sentence about
their own key: name the condition and the window rather than the identifier, and
attach the raw identifier as a structured attribute for logs if a caller needs it.
If the wire refusal should carry an identifier, carry the client's own key header
value, which the client already holds. Sweep the sibling messages in the same file
for the same shape — the HMAC-bound normalised key has even less business on a
wire. State the general rule once in §2.4: a refusal's message names what the
caller sent, never a server-internal identifier; correlation belongs in the log,
keyed by the incident id B-6 introduces. Message text only; check the transport
parity suite does not compare message strings.

**Tests.** The two refusal messages do not contain the raw identifier; the leak
sweep is extended to assert no refusal body contains the principal's token id;
and the ladder's reasons and statuses are unchanged.

### J-http-envelope-14 — four git reasons carry hardcoded statuses with no table row

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** —

**Symptom.** The git reasons are raised at 403, 400, 503 and 404 and none has a
row in the status table, so the shared status function returns 400 for all four
and disagrees with the wire on two of them. The module whose entire purpose is to
be the one closed table has four reasons it does not know about.

**Reproduction.** The status function returns 400 for each of the four names and
reports none as tabulated, while the routes send 403, 400, 503 and 404.

**Root cause.** The statuses are literals at the raise sites in
`server/src/hephaestus/http/git_projection.py` and at
`server/src/hephaestus/http/app.py:562-565`, where the unavailable branch builds a
§2.4 body by hand rather than going through the mapping — the one place in the
wrapper that does. None round-trips through the table, so the divergence is
invisible until something does. All four landed with the git projection in
bb546fd, by which time the table was already the module's stated single source, so
this is an omission rather than a sequencing accident. Adding rows without
removing the literals leaves two sources of truth that agree today.

**Fix.** Add the four rows with the grounded comments the neighbouring rows carry
(plus `git_timeout` from J-http-limits-6), replace the literal statuses with the
table lookup, and route the hand-built body through the refusal type so the
wrapper has no bespoke construction. Then add the standing guard that makes this
class a build failure: a test that walks every refusal construction in the HTTP
package and asserts its status equals the table's for its reason. Add the rows to
INTERFACE.md's §2.4 table, noting that the not-a-repository case is an addressing
miss on the project's own state and therefore 404, and that the unavailable case
is 503 beside the other runtime-absence reasons. No wire change.

**Tests.** The table's row-by-row test extended with the four; the standing
status-comes-from-the-table guard, which is the most valuable part and may surface
other refusals with the same shape; and assertions that the four wire statuses are
unchanged, pinning the refactor as behaviour-preserving.

### J-http-envelope-15 — the supervisor path reduces the detail and not the message

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-5

**Symptom.** Both `agent_unavailable` branches build their detail through the
bounding helper with the secrets argument omitted — so the redaction half is a
no-op — and put a raw, unbounded exception string in `message` beside it. The
detail is capped at a few hundred characters while the message next to it is not.

**Reproduction.** A sidecar-level failure returns a truncated `detail` and an
untruncated `message` derived from the same exception.

**Root cause.** RC-5. `server/src/hephaestus/http/errors.py:345-351` and
`server/src/hephaestus/http/errors.py:376-382` both pass the exception through the
reducer for the detail and `str(exc)` positionally for the message; the reducer's
redaction loop iterates an empty sequence because its secrets parameter defaults
to empty. Both branches arrived in e3ef904, reusing a helper whose secrets
argument exists because the credential path needed it; the session path had no
obvious secret to pass and so passed none, and the message was never considered as
a second copy of the same text. Capping the message alone leaves the redaction
inert; passing secrets alone leaves the message unbounded.

**Fix.** One reduction for the whole refusal, not one field of it: pass the
message through the same bounding, and pass the secrets this layer actually knows
— the serve bearer is the one secret this process holds that could appear in a
sidecar message, and it costs one substring scan. Make the secrets argument
explicit at both call sites (or required), because a silent default is what let
this pass review. If message and detail then carry the same string, make them
differ meaningfully — the message is the operator sentence, the detail the reduced
engine text — rather than duplicating. Lift the reducer into a shared module
alongside the git reduction from J-http-envelope-11 so the surface has one
bounding function. State in §2.4 that every text field of a refusal is bounded and
redacted, which covers this item and two others.

**Tests.** A supervisor error whose text embeds the serve bearer produces a
refusal in which the token appears in neither field; a very long message is bounded
against the same constant as the detail; and the leak sweep extended to the session
routes.

### J-http-envelope-18 — two size refusals, two statuses, neither tabulated

**severity** low · **surface** http · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** J-http-envelope-14

**Symptom.** Two refusals for the same shape of condition — a payload the
transport will not carry — answer with different statuses, and only one is
tabulated. A client cannot learn from §2.4 that an oversized request is 400 while
an oversized export is 413.

**Reproduction.** The status function reports the request-string reason as 400 and
untabulated (it reaches 400 through the family fallback) and the export reason as
413 and tabulated; §2.4's table contains neither.

**Root cause.** The export reason has an explicit row with a deviation note saying
the table lacks it because §22 is a later section; the request-string reason is
raised as a bridge limit error and wrapped with the status hardcoded at the wrap
site. So the difference is not a decision — it is one reason that got the careful
treatment and one that got a literal, and neither made it into a table presented as
closed. The 400/413 split is defensible and undocumented, which makes it
indistinguishable from an accident; this is the third symptom of one condition,
alongside J-http-envelope-14 and J-http-envelope-17.

**Fix.** Decide on purpose and write the reasoning down: keep 400 for the
oversized *request* (a malformed-by-size input refused before anything executes,
beside the other input faults) and 413 for the oversized *export* (a well-formed
request for bytes this transport cannot carry). Add both rows plus the
quota-exceeded reason that carries the same unamended note, derive the wrap site's
status from the table, and replace the deviation notes with references to the rows
that then exist. Add the sentence that makes the guard meaningful: the table is the
complete set of reasons this surface emits, and a reason without a row is a defect.
No wire change if the recommended split is kept.

**Tests.** The row-by-row test extended; the status-from-the-table guard from
J-http-envelope-14 covers it permanently; and the two cases asserted side by side
in one test, so the deliberate difference is visible.

### J-http-envelope-19 — the unauthorized WebSocket close code is dead

**severity** low · **surface** http · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** —

**Symptom.** The events module exports a WebSocket close code for the
unauthorized case and passes it to `close()`, but the close happens before
`accept()`, so the connection is refused as an HTTP 403 and the code is discarded.
A reader would reasonably believe a client sees it.

**Reproduction.** An unauthenticated upgrade against a real serve returns
`403 Forbidden` with no handshake, no close frame and no code; in-process the test
client raises a disconnect with an empty reason.

**Root cause.** `server/src/hephaestus/http/events_ws.py:114-122` closes before
accepting; under ASGI a close sent in the connect phase is delivered as an HTTP
rejection, and the code and reason have nowhere to go. The refusal itself is
deliberate and correct — the comment two lines above explains that an
unauthenticated upgrade is denied at the handshake rather than accepted and then
closed, which would leak the existence of a valid stream — and the constant simply
outlived its meaning. Both landed in bb546fd. The specification requires a bearer
on the upgrade and the 403 satisfies it; nothing documents what an unauthorized
upgrade looks like on the wire, which is why nobody noticed.

**Fix.** Delete the constant from the module and its export list, call `close()`
with no code, and extend the comment to say the client observes a handshake
rejection and that the code is not delivered. Then check the sibling close in
`server/src/hephaestus/http/app.py:1520-1526`, which has the same shape for the
`agent_unavailable` condition — a *reachable operator* condition whose whole §7A.8
vocabulary is discarded — and decide deliberately: accept-then-close with a code
and reason, which leaks nothing because the bearer already validated and for which
the client's reconnect path already has a precedent, or keep the rejection and make
the client read the condition from a REST route. The auth case must stay
refuse-before-accept; that one is a security property. Document both upgrade
refusals in §2.2 or §2.7.

**Tests.** An unauthenticated upgrade is refused at the handshake, asserted in a
form that does not mention a close code; and the unavailable upgrade behaves as
decided — it has no test today that observes what a client actually sees.

### J-http-envelope-20 — the script route is the only 200 body with no `status`

**severity** low · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Every other 200 document on the surface opens with an ok status; the
script document does not, so a client cannot use one predicate to tell a success
document from a refusal, and the client's type encodes the exception permanently.

**Reproduction.** The script route returns content hash, line count, two parameter
state hashes, the script, a snapshot ref and a truncation flag — and no status —
while every other read route in the same sweep carries one.

**Root cause.** The route returns the read tool's own result document verbatim,
which INTERFACE.md's script row requires, and tool results are discriminated
differently, so the route is faithfully implementing a clause that collides with
§2.4's envelope convention. The web client absorbed the exception rather than
surfacing it. The specification is internally inconsistent — one clause demands
the tool result verbatim, another establishes the status as the envelope
discriminator, and nothing reconciles them — so this is a specification defect with
a code consequence. Adding the field here without deciding the rule invites the
same question at the next passthrough route. **Adjacent, and owned elsewhere:** the
documented line paging on this same route is a no-op, which is J-http-limits-3;
whoever opens these two functions should fix both rather than touching them twice.

**Fix.** Settle the rule — the status is a property of every document this surface
returns, and a verbatim tool result is wrapped rather than exempted, since
"verbatim" means no field is dropped or renamed, which adding one does not violate
— then check why the other tool-backed routes already carry it and make the script
route consistent with its siblings rather than inventing a new wrapper. Update the
client type and delete its exception comment. Amend §2.4 with the rule and the
script row with the added member.

**Tests.** A boundary assertion that every 200 document the API can return has a
status member, derived from the route table so a future route inherits it; and the
script document specifically, asserting the status plus every pre-existing field,
so "verbatim" is pinned as well as the addition.

### J-http-limits-2 — refusal bodies echo client strings twice

**severity** medium · **surface** http · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** — · **root cause** RC-5

**Symptom.** A context preview naming an 8 MB part returns a 16 MB 404. Pushed to
the parse-level maximum, a 16 MiB part name returns a 33,554,553-byte 404 in
0.61 s — a ratio of exactly 2.00, because the same string is written into both the
message and the machine payload.

**Reproduction.** A preview whose part name is exactly the maximum admitted string
returns a 33.5 MB body whose keys are message, part, parts, reason and status,
with the part and the message each carrying the full 16 MiB. Adding a second
maximal member leaves the response the same size, confirming the amplifier is
per-field.

**Root cause.** RC-5. `server/src/hephaestus/http/context.py:385-401` interpolates
the untrusted value into the human message and into the machine payload, both
unclipped, and the refusal body merges the payload with no per-value budget — so
every refusal in the codebase that interpolates client input is an amplifier of the
same shape. Separately, the envelope parser validates the *key set* and not the
*value grammar*, even though part names have a grammar the store enforces, so an
8 MB name passes the parser untouched and is only rejected by a membership test
whose refusal quotes it. The module's own docstring states the principle it
half-keeps: a lying client is caught, not believed. Clipping this one field leaves
the same pattern at the git refusal, the supervisor path and every dispatcher
message that interpolates an argument.

**Fix.** Clip at the envelope and validate at the door. Add a byte budget and a
code-point-safe clip in the error module, applied by the body builder to the
message and recursively to every string in the data, with an explicit marker —
a silently shortened value would be the silence the specification forbids — and
leave the reason unclipped, since it is a closed vocabulary. Then validate the
part name in the envelope parser against the store's own identifier pattern,
imported rather than restated, refusing 400 naming the field; likewise bound the
artifact ref and selection members against their existing grammars. The supervisor
path inherits the clip automatically; while there, thread the secrets argument
J-http-envelope-15 needs. Add one normative line to §2.4 that a refusal body is
bounded, and one to §7A.3 that a value which cannot match its field's grammar is
refused before any store lookup. Check the client's reason map handles the new
400 for malformed input, which today produces a 404.

**Tests.** A refusal whose data carries a megabyte string produces a body of a few
kilobytes with the marker and an intact reason and status; a short value is
byte-identical to today; the oversized part name is 400 naming the field and the
response is under a kilobyte; a legal-but-absent name is still 404 with the name
intact; and a property-style check that for every reason the body builder stays
under budget.

### J-http-limits-4 — a turn's events accumulate unbounded in memory and in the response

**severity** medium · **surface** http · **verdict** partially confirmed ·
**effort** M · **risk** low · **depends on** —

**Symptom.** The prompt route blocks for the whole model turn and its body repeats
every event that was simultaneously delivered on the events socket. **The
duplication is by design and documented** — the socket is the live surface and the
list is what a client with no socket renders instead, so a run is never invisible —
so the audit's framing is wrong. The defect underneath is that the buffer is a
plain unbounded list, so a long tool-heavy run accumulates every event in the
serving process *and* ships them all in one response, with no bound and no way for
a socket-connected client to decline them.

**Reproduction.** The prompt response carries a status, session and run id, the run
status, the terminal, the context and every event of the turn — the same events the
socket delivered — and the run's event list is created with no maximum length and
no drop policy.

**Root cause.** `server/src/hephaestus/agent_bridge/app.py:122-129` accumulates
every normalised event for the life of the turn in an unbounded list, returned
whole at `server/src/hephaestus/agent_bridge/app.py:1169`, copied per event by the
HTTP layer and serialised. The live path *has* a bound — the buffered-events limit,
with coalescing of droppable progress deltas and a documented backpressure cancel —
so the two halves of one event stream have different memory disciplines. Nothing
here is a bug in the duplication itself: the no-socket client is a real consumer.
Removing the events would blind that client on a machine where the upgrade fails;
bounding only the response leaves the growth in the serving process, which is the
half that matters for a long orchestrator run.

**Fix.** Give the request-response path the same bound the socket path already has,
from the same key: make the run's buffer a bounded deque sized by the buffered-events
limit, count drops, and carry a truncation flag through the prompt result into the
response. Add an `include_events` body member, defaulting to today's behaviour, so a
client holding the socket can decline them — noting that this interacts with
J-http-envelope-10, whose member validation must be taught the new name. Have the web
client, which always holds the socket, send `false`, which also removes one source
from its dedupe window. State in §2.3 and §2.7 that the response carries a bounded
tail for clients with no socket, that the bound is the shared limit, and that
overflow is reported; extend the buffered-events sentence in `architecture.md` to
cover both delivery paths. Runs shorter than the bound — every test in the tree —
are byte-identical.

**Tests.** A scripted run emitting more than the bound: the body carries exactly
the bound with the truncation flag while the socket delivered all of them; the
opt-out returns an empty list with the run status and terminal intact and the
socket unaffected; and the no-socket client still renders a full short run from the
body alone. Assert which end of the deque survives and say so in the docstring:
dropping the oldest is right for a live tail and wrong if a consumer needs the run's
opening.

### J-agent-wiring-7 — the second answerer of a question gets 404, not `accepted:false`

**severity** medium · **surface** http · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Two clients answer one broadcast question. The winner gets 200 with
`answered_by: "self"`. The loser gets 404 `unknown_question` — "it was answered,
abandoned, or never asked" — and its widget renders as abandoned, telling the
operator the question was thrown away when in fact it was answered, and never
showing them what the run was told. The `accepted: false` branch the route exists
to serve is unreachable.

**Reproduction.** Driving the pending-question registry directly: the first answer
returns accepted with `self`, the asker resumes, and a second answer for the same
id raises a key error, which the route maps to 404; the registry is empty by then.
Confirmed end to end against a real serve and a real sidecar.

**Root cause.** `server/src/hephaestus/http/sessions.py:316-318` removes the
question from the registry in a `finally`, the instant the suspended tool call
wakes; the answer method looks the id up in that same map and raises when it is
gone. The `accepted: false` branch at
`server/src/hephaestus/http/sessions.py:327-328` is therefore reachable only inside
the microsecond between setting the event and the waiting thread completing its
`finally` — a race the loser essentially always loses. There is no retention of
answered questions, and the answered flag and its projection describe a state the
registry never keeps long enough to observe. The registry, the accepted flag, the
`self`/`other` mapping and the removal were all written in **one** commit
(bb546fd), so the loser branch was authored dead — invisible then, because the
workspace shipped read-only and nothing could produce a second answerer. §7A.7
later enabled the post without revisiting the registry's lifetime. Making the route
swallow the error and synthesise a refusal would be a lie in the other direction:
it cannot tell "answered by someone else" from "abandoned by a cancel", and the
abandoned path depends on that 404 staying truthful.

**Fix.** Separate the *suspension* lifetime from the *record* lifetime: keep the
live map exactly as it is, and add a bounded settled map the asker's `finally`
moves the entry into rather than dropping it. Answering then resolves live-and-
unanswered (record, wake, accept), settled (return the winner's selection unchanged,
not accepted — so both clients agree on what the run was told), or neither (the key
error, and the 404 keeps its exact current meaning, which §7A.6 depends on).
Abandoned questions can move into the same map with a flag, enabling a discriminated
abandoned response later without another lifetime change — an optional second step;
the minimal fix is the first two branches. Bound the map by count with oldest-first
eviction, so a very old loser degrades to today's 404 and nothing grows without
limit; record that bound in §2.7. The web client already renders the corrected
response.

**Tests.** Two answers to one question: 200 accepted with `self`, then 200 not
accepted with `other` and the **winner's** selection; a never-asked id is still
404, pinning that the fix did not soften the real case; an abandoned question after
a cancel behaves as decided; eviction past the bound degrades to 404 and nothing
grows; and the widget renders the corrected response as answered rather than
abandoned.

## Web UI

Four items in this section are web-facing halves of the cross-language mirror
group and are described with it: J-mirrors-and-dx-6, -7, -9 and -10 in
[Sidecar and server internals](#sidecar-and-server-internals).

### J-web-viewport-1 — a note inside a panel section sizes the label column to 487px

**severity** high · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-11

**Symptom.** Every inspector panel's label column is far wider than its labels.
Inside the 434px bill-of-materials dialog the label track is still 487.6px, so the
value track collapses to 0px and every value cell is a zero-width box 133px
outside the dialog's right edge. The audit attributed this to the dialog being a
flex box; both of its stated causes are true statements about the code and neither
is the mechanism.

**Reproduction.** In a 900px inspector body the sourcing panel computes tracks of
487.625px, 348.375px and 8px for labels reading "Pin", "Process", "Stock form",
with its single note measuring 492px in track 1; the DFM panel 202.8px, export
172.5px, provenance 82.7px, checks 79.4px. Injecting a full-span rule for section
children recomputes the same panel to 123.406px, 712.594px and 8px and grows the
first value cell from 312 to 677px; in the dialog it goes from 487.625/0/8 to
123.406/220.391/8 and the value cell from 0 to 184px.

**Root cause.** RC-11. `web/src/system/Panel.module.css:73-77` gives the panel
body's direct children a full span and a zero minimum width, with a comment saying
anything that is not itself a three-column row spans all three. There is no
equivalent rule for a *section's* children. A section is itself a subgrid, so it
inherits the tracks, but its children are auto-placed: a data table self-spans and
is fine, a prose note has no column rule and lands in column 1, where its
measure-limited maximum width becomes the label track's intrinsic size. Above
about 500px of container that is merely ugly; below it the value track's zero
minimum collapses it exactly. All of it — the body rule, the section subgrid and
the note's measure — landed in one commit (b8b6a48), and no test measures a track.
Changing the track definition to cap the label column caps the damage without
removing it; deleting the note's measure would fix the tracks and break the
typographic rule for every panel sentence.

**Fix.** One rule mirroring the one that already exists, so the two containers of
the three-track grid behave identically: give a section's direct children the same
full span and zero minimum, with a comment naming the measurement as the retired
defect. Give the data table the last word on its own span by asserting the computed
value in the test rather than relying on cascade order. Extend the panel's doc
comment and add the negative half to §4.7: prose inside a panel spans all three
tracks and contributes to none of their intrinsic sizes — a column sized by a
sentence is not a column. Pure CSS; no attribute or selector changes. The visible
change is that value columns widen in seven panels, which will move pixels, so any
panel screenshot baseline needs refreshing; the viewport control-region thresholds
are measured elsewhere and are unaffected.

**Tests.** For each inspector tab, the first track is under 40% of the body width —
which fails today for sourcing at 54%, and at 69% in a 1024px window; every value
cell has a non-zero width and is contained in its panel, which is the single
assertion that catches this item and B-8 together.

### J-web-stream-1 — the stream column keeps a grid row for a deleted child

**severity** high · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-11

**Symptom.** The stream column is 956px tall and the panel inside it is 177px, so
the composer sits immediately under the tab strip instead of at the column's
bottom, the transcript scroll region is 32px, and about 780px of the peer column is
empty. This is not specific to empty sessions — it is the column's steady state
whenever the transcript is shorter than the column.

**Reproduction.** Walking the computed styles from the panel to the body at
1600x1000: the aside is a grid, 956px tall, with rows resolving to 176.5px and
779.5px and exactly one child; the panel's computed height is 176.5px despite a
stylesheet rule asking for the full height. Forcing a single full-height row moves
the panel to 956px, the scroll region to 812px and the composer to the column's
bottom edge.

**Root cause.** RC-11. `web/src/components/Shell.module.css:150` declares two rows
— a template written when the aside had two children, an eyebrow band and the
panel. The band was deleted by dd9ee1c "feat(web): the refinement round — the
transcript becomes the story of the run" and the template was not, so the one
remaining child is auto-placed into the content-sized first row and the second row
absorbs the rest with nothing in it. The panel's percentage height then resolves
against a content-sized track and every flex child inside it has no leftover height
to claim. The collapsed-state override eight lines below already uses the correct
single-row template, so half the rule was fixed and half was missed. Patching only
the empty-session case leaves the same void for every short transcript and leaves
the panel's own height declaration inert.

**Fix.** The aside holds exactly one child in both of its states, so it needs
exactly one definite row: collapse the two rules into one full-height row and
delete the now-identical collapsed override — two rules that must agree are the
shape this bug came in. The panel's height then resolves and its flex column does
the rest, which it already does correctly. Re-check the narrow-window overlay rail
and the collapsed band, which now share the same row. Amend the clause that struck
the eyebrow band to state that the aside holds one child and therefore one row, and
that a second track is a track for a band that clause struck. Visual only, and it
is the repair; refresh any geometry-sensitive baseline.

**Tests.** A stylesheet assertion beside the existing one that gives the body one
definite row — one line that would have caught the deletion — plus a source
assertion that the aside has one child per branch, and an end-to-end check that the
composer's bottom edge is within a pixel of the column's and the panel's height
equals the aside's, run for an empty session too.

### J-web-stream-2 — a session with an empty transcript renders nothing

**severity** medium · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-web-stream-1

**Symptom.** Selecting a session that has never been prompted leaves the
transcript region an empty list: no empty state, no heading, no icon, and the
panel reports that the history read *succeeded* and is complete. The read worked
and there is nothing to show, and the interface says nothing about that.

**Reproduction.** With such a session selected, the transcript's text and the
stream body's text are both empty strings, no empty-state attribute is present, and
the panel reports live, complete, one page.

**Root cause.** `web/src/components/stream/Transcript.tsx:36-38` maps rows with no
branch for zero rows, and the panel's only stream empty state is gated on the
*session list* being empty — a different and, when a session is selected, false
claim. `web/src/stream/sessionEmpty.ts` describes the no-sessions case only, and
the copy file has no string for "this session has no turns yet", so the state has
no producer of any copy anywhere. The transcript has been rewritten four times and
has never carried an empty branch; it stayed invisible because until the composer
could create a session the browser could not produce a zero-event one. INTERFACE.md
§3.3's fifth principle is explicit that every state — refusal, absence, no runtime
— is a first-class composed state with a shape, an icon, a heading and, where an
action exists, a button. A minimum height or a spinner would misreport the state,
since the read has completed; and with J-web-stream-1 fixed the void becomes 812px
rather than 780px, so the two must land together.

**Fix.** One composed state, decided in a pure predicate beside the other stream
decisions rather than inline — this column already keeps its badge and counter
decisions there for the same reason. It is true only when a session is selected,
there is no runtime fault, the panel is not unavailable, the history is complete
and the row count is zero; every other combination already has its own composed
state and must not be shadowed. Render it in the stream body, before the scroll
host, not inside the transcript component, which renders the closed row vocabulary
and decides nothing. It carries an icon, a heading and one sentence naming the fact,
and **no** action: the composer below it is the action, and a create affordance
here is forbidden by §7.1. Give it flex growth so it occupies the leftover height.
Add §7.4(e) stating the state and its testable form. Purely additive: a new
predicate, two copy keys and one element with a new attribute.

**Tests.** The predicate table-driven over its six exclusions; a render test
asserting the new attribute is present and that the rendered text contains neither
the no-sessions title nor a create-session string; and an end-to-end check that the
state occupies more than half the transcript region, which requires J-web-stream-1.

### J-web-stream-3 — the composer's refusal overflows the column by 214px

**severity** medium · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-11

**Symptom.** On a project with no provider configuration, the composer's refusal
renders the configuration path in a chip 621px wide inside a 395px column, whose
right edge is 214px past the column's. The overflow is clipped, so the end of the
path is off screen and there is no ellipsis to say so — on a refusal whose entire
point is to *name* the file the server looked for.

**Reproduction.** Walking every descendant of the stream aside: two elements
overflow to the same x — the path paragraph and its chip, both 621px wide against a
395px flex column and a 420px aside. The parent chain shows the refusal as a flex
column with cross-axis alignment set to start. (The audit called this the
"runtime-fault band"; there is no runtime fault here — it is the composer's
unavailable refusal.)

**Root cause.** RC-11. `web/src/components/stream/Composer.module.css:146` sets the
refusal's cross-axis alignment to start rather than stretch, so each flex item is
sized to its own maximum content along the cross axis and the paragraph becomes the
minimum width of its no-wrap child. The paragraph declares a zero minimum width and
an anywhere break — clearly written to make the path wrap — and neither can fire,
because the paragraph is unconstrained and its child is a chip, which is no-wrap by
construction, so its own full-width cap resolves against the 621px paragraph and is
a no-op. Three declarations that each look like they handle overflow, none able to,
because the container's cross-axis sizing defeats all three. All of it landed in
b8b6a48 with the chip markup, and a later chrome pass changed an identical
alignment on a neighbouring rule and left this one. The layout tests assert that the
*columns* shrink; nothing asserts that content inside the stream column fits it.

**Fix.** Two changes, one structural and one semantic. Structural: the refusal
stretches its children, with the action button overriding back to its intrinsic
width — without that override the button renders full width. Semantic: a filesystem
path in a 395px column is not chip material; a chip is a compact readout and this is
a ninety-character identifier the operator must read in full, so render it as
wrapping code text and give the paragraph a full-width cap. Keep the machine-readable
attribute on the paragraph, which is what tests and harnesses read. Apply the same
treatment to the rail panel, which renders the same path and already wraps it
correctly. Add the testable half to §7A.8 — the path wraps rather than truncating,
and no element of the refusal extends beyond the column at any admitted width — and
add to §4.7 that a chip is never the container for a value whose whole text is
load-bearing.

**Tests.** Stylesheet assertions that the alignment is not start and that the path
has a full-width cap; an end-to-end invariant that for every descendant of the stream
aside the right edge is inside the aside's, run at two widths — the general
invariant that would catch the next one too; and a render assertion that the full
path appears as text, not only as an attribute.

### J-web-stream-4 — one attach cause stated three times, one sentence rendered twice

**severity** medium · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-5

**Symptom.** With no provider configuration the stream column states one cause
four times: the composed heading and sentence, the mapped cause, the raw engine
detail restating the path, and then the identical disabled-control sentence again —
two different elements rendering the same string inside one form.

**Reproduction.** Collecting every leaf element under the aside whose text contains
the unavailable sentence returns two: the empty state's body and the disabled
control's reason span. The mapped cause reads "No provider configuration was found
at:" and the detail reads "no provider config at <path>" — the same fact plus a
second copy of the path the chip above already shows.

**Root cause.** Two independent duplications in one block. The composer renders the
disabled reason as an empty-state body *and* hands the same reason to the send
control, which renders it as a visible span — one string, two render sites, no
coordination. And it renders both the mapped cause and the raw detail, which the
server derives from one raise, so the two are the same fact and the detail
additionally re-prints the path. Both landed in b8b6a48, whose author was already
fighting this: a comment in the same file explains that the remedy rides on the one
action rather than a fourth paragraph, because four stacked paragraphs and a button
in a narrow column is the wall an operator reads as a broken chat. INTERFACE.md
§4.7's second empty-state rule — a shared cause is detected once, one cause, one
sentence — is normative and quoted in the code. Deleting the detail paragraph
leaves the doubled sentence, a different mechanism at a different layer, and leaves
the detail unmapped for the causes where it genuinely carries new information.

**Fix.** One rule for this refusal, applied in both places it is rendered: the cause
is the sentence, the configuration path is the named file, and the detail is
diagnostic — it renders only where it adds information the mapped cause does not
(the invalid-config and sidecar-failed causes, whose detail is a reduced exception)
and then behind the disclosure §4.7 prescribes, never as a fourth bare paragraph.
Put the redundancy decision in a pure, tested predicate in the attach API module
rather than a JSX condition. Structurally, where the composed refusal is mounted the
control's reason is carried on the title and the machine-readable attribute only, so
the sentence is rendered once. Keep every attribute unconditionally so tests and
harnesses still read them. Add both rules to §7A.8 and §7A.9.

**Tests.** With the absent-config cause, the sentence occurs exactly once in the
rendered text, the path exactly once, and no rendered text equals the raw detail;
with the invalid-config cause the detail *is* reachable; and the predicate covered
for every member of the attach cause vocabulary, which also pins that list against
the server's.

### J-web-stream-6 — "Add a provider" re-reads an unchanged file and prints a raw reason code

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-web-stream-4 · **root cause** RC-4, RC-5

**Symptom.** On a project with no provider configuration the rail's most prominent
action is labelled "Add a provider". Clicking it adds nothing — it posts the attach
route, which re-reads the same missing file — and the panel then renders, in a live
alert region, a machine reason code, a colon, and the server's raw engine message.
The same route is labelled "Attach a runtime" in the composer a few inches away.

**Reproduction.** The button is labelled "Add a provider" with no title; after the
click the refusal region reads `no_provider_config: no provider config at <path>`.
The server's envelope is well formed and structured, carrying the attached flag, the
path, the generation, the cause, the detail, the reason and a message the server
composed as cause-colon-detail.

**Root cause.** Two joined defects. The label:
`web/src/components/ProvidersPanel.tsx:379-391` wires the "add" copy to the attach
call, and the specification's own route table says that route *creates a runtime*
from an existing configuration and cannot create configuration; the identical call
is labelled "Attach a runtime" in the composer. The mapping: the panel funnels every
failure through a shared refusal-text helper whose map has twenty-five entries and
no row for this reason, so its fallback returns the raw message. Meanwhile the same
refusal document carries a structured cause, and the composer already maps it — the
mapping exists, one component uses it and the other does not. The composer is not
clean either: its own attach-error branch renders the raw message for the same
route. All of it landed in b8b6a48; the fallback was correct for the auth routes it
was written for, whose reasons are all in the map, and was then reused for a route
whose reason is not. §23.14 requires these routes' §2.4 error mapping. Adding one
row for the reason would replace the raw string with a single generic sentence and
*discard* the structured cause, so three different conditions would read identically
— losing the one piece of information the operator needs.

**Fix.** Make the structured cause the single mapped vocabulary shared by both
surfaces: move the cause map out of the composer's copy namespace into a
surface-neutral one, add a helper that extracts the cause from an attach refusal,
and extend the shared refusal-text helper to consult it. **Remove the raw-message
fallback entirely** — that is the root fix, and it closes this class for every
provider route at once — falling back to the generic error title instead. Render the
refusal through the §4.7 banner recipe: title, sentence, reason code as a code chip,
retry button, and never the code inside the sentence. Fix the composer's raw branch
the same way. Rename the button to match the route and give it a title naming what
the press does, reserving "Add a provider" for a control that writes provider specs.
Two compatibility surfaces: removing the fallback changes behaviour for every
provider refusal whose reason is absent from the map, so pair it with a test that
the map covers every reason the server can emit; and the rename changes text that
end-to-end tests select by role and name, so migrate them onto the stable attribute
in the same commit.

**Tests.** A rejected attach renders the mapped sentence with no underscore and no
colon-prefixed code, with the code in a chip; a class-closing assertion that the
helper returns a mapped string for every known reason and the generic title — never
the raw text — for an unknown one; the composer's branch likewise; and a copy lint
that no rendered refusal text matches a machine-reason shape.

### J-web-stream-8 — Checks and DFM render `measured` through `JSON.stringify`

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** moderate · **depends on** — · **root cause** RC-5

**Symptom.** The Checks panel prints a typed addressing error as raw JSON at the
same weight and colour as a passing check's formatted value, with the actual
information — you referenced a part that does not exist — about 120 characters in,
inside JSON punctuation. The DFM panel does the same for every finding. The same
panels format numeric measurements correctly, so the JSON is a fall-through, not a
style.

**Reproduction.** A check whose predicate addresses a missing part renders
`measured: {"error":{"type":"AddressingError","code":"addressing_error","message":"unknown part …"}}`
beside rows reading `measured: 250 × 156 × 5.5`; four DFM findings render their
fact maps as JSON objects, one of them truncated mid-token.

**Root cause.** RC-5. `web/src/system/format.ts:114` ends in a `JSON.stringify`
fall-through, and both panels call it on a value the engine defines as a map. The
check result's measured field is typed as unknown and, for a check whose
*measurement* failed, carries an error envelope the engine already treats as a
distinct verdict — so the client has the structure and the vocabulary and renders
neither. The machine-readable attribute legitimately serialises; the bug is that
the same serialisation is also the human text. INTERFACE.md §4.7 contains a clause
written *as a known defect* — "a reading surface never receives `JSON.stringify`
output" — naming this exact check row, explaining that the actual information is
buried, and prescribing the fix: the message renders as the row value, the code as
a chip, and the raw object goes behind a disclosure. The clause was written and the
implementation never followed; the sibling components specified in the same
paragraph were built. Special-casing the addressing shape fixes one row and leaves
DFM, every other error envelope, and the fall-through free to stringify the next
object someone passes it.

**Fix.** Make the fall-through impossible rather than unlikely: the formatter stops
being total over unknown and returns null for anything it cannot render as a scalar,
so every call site must say what it does with a structure — the compiler becomes the
enforcement. Add two small readers beside it, one for the error envelope and one for
a flat fact map, and render them per §4.7: message plus a code chip plus a
disclosure, or label/value pairs through the existing table primitive. Keep every
machine-readable attribute unchanged, so selectors, the archive matcher and the audit
harness are unaffected and only visible text moves. Extend the §4.7 clause beyond the
check row to any measured map and any tool-result field a panel renders, with the
testable negative: no rendered text node matches a JSON opening. Land it as one
commit — the signature widening surfaces every call site, some unrelated, and a
half-migrated tree is worse than either state.

**Tests.** An error envelope renders its message with no braces or quotes, a code
chip, and the attribute still carrying the serialisation; a DFM fact map renders
three label/value pairs and no braces; a repo-wide guard that the formatter's return
type admits null so future call sites must handle the structure; and an end-to-end
assertion on the fixture's known error row.

### J-web-viewport-2 — the section plate header is overlapped, and its gate never mounts a plate

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** — · **root cause** RC-10, RC-11

**Symptom.** With a server-rendered section plate up, the plate's header bar is
covered on the left by the appearance cluster and on the right by the view cube, so
the artifact reference §5.3 requires be shown is partly unreadable. Every viewport
overlay is also painted over the plate image, addressing a canvas the plate has
replaced.

**Reproduction.** With a rendered plate, the header occupies a band across the
plate's top edge and both overlay clusters sit inside it; testing the seven named
surfaces plus the header pairwise yields eight overlaps, because the plate is inset
to the whole well and therefore also intersects the grid readout, the explode
slider and the section control.

**Root cause.** RC-11 for the collision and RC-10 for why it survived. The plate is
absolutely positioned over the whole well with a full-bleed header, while the
appearance cluster and the view cube each seat themselves in the same top inset
from opposite sides, and the viewport renders them after the plate in DOM order —
no component knows the other exists; the appearance cluster's own comment reasons
about the *cube* and not about the plate. The gate that should have caught it is
degenerate: `web/e2e/viewport.spec.ts:513-521` lists the whole plate in the surface
set where the clause names the plate's *header*, the helper skips any selector that
matches nothing, and the test never engages a section — so the assertion has never
run against a plate, and if it did it would fail on the plate intersecting
everything. The clause and the test were written in one commit. Nudging the two
clusters down while a plate is up makes the boxes disjoint and leaves the deeper
incoherence: six controls painted over a rendered image they cannot affect.

**Fix.** Fix the test first — it is the thing that failed — by selecting the plate's
header rather than the plate, adding a second pairwise sweep with a plate mounted,
and giving that sweep a minimum-surface floor so a plate that fails to mount fails
the test instead of shrinking the set. Then make §5.3's sentence true in layout:
while a *rendered* plate covers the well, the plate owns the well, so the four
canvas-authoring overlays — cube, appearance cluster, axis triad, grid readout —
unmount, the section control stays because it is the exit, and the explode slider
stays only while engaged. The surface set under a plate then reduces to three,
disjoint by construction. Harden the header itself with the truncation recipe the
panel title already uses, so a long reference ellipses inside the bar rather than
running to the edge. Amend C19 to name the plate-mounted state, say which overlays
unmount and why, and correct the surface to the header. Unmounting four overlays is
a visible product decision and should be confirmed as intent; the alternative —
offsetting them — satisfies the clause's letter and leaves the incoherence. The test
change is zero-risk and should land first regardless, because it converts a silent
pass into a red build.

**Tests.** The plate-mounted pairwise sweep with a surface floor; with a rendered
plate, the three canvas-authoring overlays have no elements and the section control
has one; and the header's reference node contained within the header's box.

### J-web-viewport-3 — the explode control paints outside its own card

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-web-viewport-2 · **root cause** RC-11

**Symptom.** With a section engaged at a 1600px window the explode card shrinks to
113px while its contents need 172px, the label wraps, and the Collapse button is
drawn entirely on the canvas outside the card's border. At 1280px the card is 18px
wide and every child is outside it. Nothing yields, because the ladder looks only
at the stage width and both are above its trigger.

**Reproduction.** Before engaging a section the card is 606px wide with every child
inside it; after engaging, the card is 113px with a scroll width of 172px, the
slider wrapper ends 16px past the card's right edge and the Collapse button's text
runs 24 to 61px onto the canvas; the section control sits beside it at its natural
624px and does not shrink.

**Root cause.** RC-11, three compounding facts. The clause gives the explode
*slider* a 120px minimum track, and the stylesheet puts the minimum on the inner
wrapper while the *card* is free to shrink below it — so the content overflows a
card with no overflow rule. The section control is explicitly not flexible, which is
literally what the clause says, but its natural size is 131px collapsed and 624px
engaged, and the yield trigger was derived from the collapsed one. And the ladder
compares a width constant against the stage width, never measuring the band's actual
demand, which now depends on whether a section is engaged, whether explode is
engaged and how wide the readout's numbers are. All of it — the band, the flex split
and the three constants — landed in dd9ee1c together with the clause, measured in one
state. The band's own comment says no occupant is absolutely positioned over another
because they are flex siblings, which is true of the siblings and silent about a
sibling's content escaping its own box. Adding an overflow rule replaces a button
painted on the canvas with a button that is invisible and unreachable; moving the
minimum onto the card overflows the section control instead; lowering the trigger
yields the slider on a wide screen whenever no section is engaged.

**Fix.** Give each occupant a floor it cannot be pushed below — the card's floor is
the track minimum plus its measured chrome — and let the engaged section control
wrap internally under pressure instead of evicting its neighbour, which it can
already do. Then make the ladder measure the band: the viewport already owns a
resize observer, so compare the band's scroll width to its client width and drive
the yield from an overflow flag OR'd with the existing constants, escalating in the
clause's stated order. Keep the constants, so the specified behaviour below the
trigger is unchanged; the overflow term only ever yields *earlier*, which means C18's
"nothing yields above 560px" must be amended to "nothing yields above 560px while the
band fits" rather than silently broken. Also name the section control's two natural
sizes in the clause, and add the missing negative half: no band occupant paints
outside its own card in any state. Every data attribute is unchanged, so the existing
yield assertions still pass.

**Tests.** With a section engaged at 1600, every child of the explode card and of the
section control is contained in its parent — which fails today; the band's scroll
width never exceeds its client width at four widths; and at a width where the band
would overflow, the explode control has yielded and the section control is still
expanded, pinning the order.

### J-web-viewport-4 — a 7ch readout cannot hold `0.00`

**severity** low · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-web-viewport-3 · **root cause** RC-11

**Symptom.** The editable numeric readout beside the explode and section sliders
clips its last glyph. §4.7 makes the readout editable precisely so a value can be
read and typed exactly, and a readout that cannot show four characters undoes that.

**Reproduction.** Both readouts report a client width of 48 and a scroll width of
51-52 for the value `0.00`. Suppressing the number input's spin buttons drops the
scroll width to exactly the client width; widening the box as well leaves headroom
for a signed three-digit offset.

**Root cause.** RC-11. `web/src/system/Input.module.css:78-89` sizes the readout in
character units as a border box, so the content box is about 40px, which the four
glyphs would fit — but the element is a number input and the browser lays its spin
buttons inside the content box, adding a few unavoidable pixels. A second, larger
instance is latent: the section offset renders six- and seven-glyph values that
overflow a 40px content box regardless of spin buttons. It all dates to the design
system commit that replaced an inert text readout with an editable input — correct
in kind and one size step too small — and no test measures a rendered width.

**Fix.** Suppress the spin buttons, which are a redundant coarser stepper beside a
range input that already steps and are what makes the box unmeasurable, and size the
box for the *widest value the control can produce* — sign, integer digits and the
declared precision — plus padding and borders, rather than for a magic character
count. Add a zero minimum width so the readout can still shrink in a flex row, with
J-web-viewport-3's card floor absorbing the pressure. Comment the rule with the
measurement. Add the legibility sentence to §4.7: the editable readout renders its
value in full at every value the control can reach. The same primitive backs the
parameter sliders, where it matters more, because an out-of-bounds typed value must
stay visible. The readout grows by a few pixels inside a band J-web-viewport-3 is
re-measuring, so land them together.

**Tests.** For both readouts, the scroll width never exceeds the client width at
minimum, middle and maximum values; the same for a parameter readout carrying a
rejected out-of-bounds value; and a source assertion that the spin-button
suppression is declared.

### J-web-viewport-5 — the held-artifact part lives in a tooltip and is lost on reload

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** Hold an artifact on one part, select another: the viewport and export
show the first part's geometry while the inspector shows the second's, and the only
statement of that split is a tooltip and a data attribute — no visible words.
Reload the same URL and even the tooltip degrades to a generic sentence: the
workspace no longer knows the pin came from another part, though the URL still says
the pin is held.

**Reproduction.** After holding and switching, the pin chip's title names the source
part and a data attribute carries it, while the visible text is a build digest, the
word "held" and a follow-current action. After reloading the identical URL the
attribute is null and the title is generic; the pin mode and reference in the hash
are unchanged.

**Root cause.** `web/src/state/workspace.ts:286-291` keeps the source part as a
private instance field explicitly outside the serialised record — "not URL state:
the closed record does not grow a field for a sentence" — written on hold and
cleared on follow-current and on adopting any state that is not pinned or carries a
different reference, with a comment that already names the reload case: a pasted URL
can hold a reference without saying which part minted it. The visibility half is
separate: the chip spends the composed sentence only on the title attribute, and
while the shell mints a pin-mode attribute whose comment says any panel can style
against it, a grep finds three consumers and all three are the chip itself — the
inheritance clause is unimplemented (J-web-viewport-9). Both landed in 737c885
"web: pin / header / export axis honesty (chrome polish PR 3)", so the loss on
reload is a known consequence of a deliberate closed-record decision; what was never
resolved is whether §4.1's visible, inherited marking can be satisfied by a tooltip.
Promoting the sentence to visible text still loses it on reload; adding a URL field
widens a vocabulary closed for a reason.

**Fix.** Stop *remembering* which part the pin came from and start *reading* it. The
pinned reference is an artifact reference and the artifact-metadata route is already
served and keyless, so replace the private field with a query whose projection names
the artifact's part: the fact becomes a server value, attributable, surviving a
reload and a pasted URL, and the closed record does not grow. If the projection does
not name the part today, that is the one small server change this needs — a field,
not a route. Then render the source part as visible text beside the "held" word when
it differs from the selection, keeping the attribute for tests, and mark the two
axes (J-web-viewport-9), which is where §4.1 is actually discharged. Resolve the
§4.1/§4.5 tension explicitly in the specification rather than leaving it to the
reader. If the query is judged too large for this pass, the honest interim is to stop
clearing the field when the reference is unchanged — which fixes back and forward
within a session but not a reload, and the comment must say so.

**Tests.** Hold, switch, reload, and assert the source part is still named as visible
text — which fails today; the same for a pasted URL in a fresh context, the case the
current comment says cannot work; an assertion that the marking is carried by words,
not colour alone; and a store test that the workspace object no longer carries a
derived fact.

### J-web-viewport-7 — the workspace opens on the one part that has never been built

**severity** low · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** With no part in the URL the workspace selects the first part the
server lists, which is alphabetical, and in the fixture that is the part with no
build — so the first screen is the not-built absence and every panel below is an
empty state.

**Reproduction.** Opening with no part route selects the alphabetically first part
and the viewport reports the not-built absence; the parts route returns the three
parts in alphabetical order.

**Root cause.** `web/src/App.tsx:66-74` takes position zero of the server's list
with no regard for build state, and the server's ordering is alphabetical — so the
default is "the alphabetically first part", which correlates with nothing an
operator cares about. It has been that since the workspace's first commit, and the
comment there defends the *kind* of decision correctly (a navigation default, never
rendered as a fact) while saying nothing about which part is a good default. The
absence it lands on is much newer, so before that amendment the same default
produced a blank well and the defect was less visible rather than less real. No
clause is violated: the specification says what the not-built state is and never
says a project must not open in it, and it is silent on the default — which is what
let a default that always shows an absence ship. Renaming the fixture part hides it
on this fixture and leaves the rule.

**Fix.** Make the default "the first part that has something to show, else the first
part". Cheapest correct route: have the parts listing include each part's build
state — a projection the client already receives per part from the build route, so
hoisting it into the list makes the default a one-line pick with no extra request —
and choose the first part that is not unbuilt, falling back to position zero so a
wholly unbuilt project still lands on the composed absence and its two remedies.
Reject the client-side alternative: it would make the landing part depend on request
timing, which is worse than a stable wrong answer. State the default and its
fallback in §4.5 so the choice is reviewable rather than a comment. This crosses
into the server and needs a Python test; the landing part changes for any project
whose alphabetically first part is unbuilt, including the fixture, so grep the
end-to-end specs for that name before landing.

**Tests.** Opening with no part route selects a part whose viewport is ready; a
wholly unbuilt project still lands on the absence with both remedy strings; the
listing projection's build-state vocabulary matches the build route's so the two
cannot drift; and a unit test of the selector.

### J-web-viewport-9 — "every panel below inherits that marking" has no consumer

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-web-viewport-5

**Symptom.** While the pin is held, only the header chip shows it. The stage, the
inspector and the stream look identical to the unheld state, even though the stage
is showing one part's artifact while the inspector is showing another's — on the
element §4.1 calls the most important in the document, because the held-pin gates
are exactly the case where a user must not be able to forget which build they are
looking at.

**Reproduction.** With a pin held on one part and another selected, exactly two
elements carry pin marking: the shell root and the chip. A grep for the marking
attribute across the client returns six hits — three comments, two mints, and CSS in
the chip's own module, all three of which scope to the chip. No rule anywhere selects
a descendant of the marked root.

**Root cause.** `web/src/components/Shell.tsx:53-56` mints the attribute on the shell
root with a comment saying "the attribute is the inheritance: any panel can style
against it". That sentence is the whole defect — the attribute is a *mechanism* for
inheritance, not the inheritance, and nothing below the header opts in. The panels
most in need of it are the ones the §4.5 amendment splits onto the other axis: the
inspector and script tab follow rail selection while the stage and export follow the
pin, so while held, two regions describe two different artifacts with no visual
distinction. The clause is old and survives every strike and amendment in §4.1
unchanged, so it has been live and unimplemented for the whole life of the workspace
— which mission rule 1's ledger explicitly forbids in either direction. Tinting every
panel is the obvious patch and the wrong shape: it marks all four regions
identically when the actual fact is that two follow the pin and two follow the
selection, and it would collide with the rule that colour is never the sole carrier.

**Fix.** Discharge the clause by marking each region with *what it is showing*, in
words, only while the two axes disagree — the condition the chip already computes.
The stage region carries a one-line marker naming the pinned part's held artifact,
with the reference attributed; the inspector carries the counterpart naming the
selected part. Both render through the existing note and badge primitives at a text
token, so the colour rule is satisfied without colour, and both mount *only* in the
split state — a marker that is always on is not a marking. The attributes stay as the
machine-readable half and gain human-readable consumers; rewrite the shell's comment
so the next reader does not mistake the attribute for the clause. Replace §4.1's
sentence with the concrete testable rule: which regions mark, in which state, with
what words, and the negative half. If the marking is judged not worth the pixels,
the only other honest exit is §4.1's own precedent — strike the clause, state why,
and record it as named new work; leaving a live clause with a consumer-less hook is
the one option the ledger rules out. Mount the markers *inside* their regions, since
the drawer-height parity assertion is at risk from a new row.

**Tests.** With a split pin, each marker names its own part as visible text — neither
exists today; with the pin held on the selected part neither mounts, which is the
negative half; the markers' accessible text carries both part names; and the
drawer-height parity across stage tabs with the markers mounted.

### J-cli-startup-8 — the Script tab blocks on "Loading parameters…"

**severity** medium · **surface** web · **verdict** partially confirmed ·
**effort** S · **risk** low · **depends on** J-cli-startup-7

**Symptom.** Opening the Script tab shows a loading note for several seconds. The
audit reports it on every visit; the code says the blocking note appears on the
first visit per part and after the cache entry expires, and that a revisit inside
the query cache's window renders instantly and refetches behind the reader.

**Reproduction.** The server half reproduces exactly (J-cli-startup-7): the params
read is 3.151 s against 0.010 s for the script. The client half was read from
source: `web/src/components/stage/ParamSliders.tsx:167-169` returns a full-panel
note whenever the query has no data — no placeholder, no previous-data retention —
and the panel is mounted only while the Script tab is open, so it unmounts on every
tab switch while the *query cache* survives.

**Root cause.** Two layers. The dominant one is server latency, which will be
visible however the client renders it. The client amplifies it by treating "no data
yet" as a full-panel replacement, so the tab's rail is empty text for the whole
request, and a part switch is a different query key and therefore always hits the
undefined branch on first arrival. The panel's loading branch is the standard shape
used by its siblings and is conspicuous only because this one endpoint is hundreds
of times slower. Fixing only the client hides a real cost that also lands on the
*write* path and on every model parameter write, neither of which a placeholder
helps — so this item must not be fixed alone.

**Fix.** Land J-cli-startup-7 first; then make the panel non-blocking so the
remaining latency, and any future one, is not a blank rail: keep previous data
across a part switch, replace the full-panel note with a skeleton that preserves the
layout, and render the loading string only when there is genuinely nothing to show.
**Guard the commit path while placeholder data is showing** — the state hash a
placeholder carries belongs to the previous part and must never be sent as the
expected hash — and land that guard in the same change, or the fix introduces a
correctness bug in exchange for a cosmetic one. Surface J-cli-startup-7's source
attribution through the existing fact mechanism so "from the current build" and
"evaluated now" are visible. Note in the panel conventions that a placeholder row
set is never commit-eligible; that is the one thing a future reader could get wrong.

**Tests.** With the query in placeholder state the commit handler is disabled and no
write is issued; a part switch keeps the panel's layout with no loading string; and,
with J-cli-startup-7 landed, an end-to-end assertion that the Script tab paints its
sliders well under a second on a warm fixture.

### J-web-stream-5 — the providers panel's "duplicated explanation" is the composer's

**severity** low · **surface** web · **verdict** partially confirmed · **effort** S ·
**risk** none · **depends on** J-web-stream-4, J-web-stream-6

**Symptom.** The rail's providers panel renders its explanation exactly once — a
heading, one sentence, two buttons and one discovery caption — and no sentence
repeats within it. What *is* duplicated across the page is the configuration path:
the rail prints it under a disclosure and the composer prints it twice more, so one
ninety-character path appears three times on one screen.

**Reproduction.** The panel's full text, with the configuration section closed and
open, contains no repeated sentence. The sign-in dialog the audit's script tried to
open is never present on that fixture: with zero provider rows there is no sign-in
control, and the button labelled "Add a provider" is the attach button
(J-web-stream-6), not a dialog opener.

**Root cause.** The audit's script clicked a button expecting a dialog, received the
attach re-read instead, and screenshotted the unchanged page; the "duplicated
explanation" reading appears to come from that screenshot, in which the rail's
explanation and the composer's refusal both describe the missing configuration.
That cross-surface duplication is real and is J-web-stream-4; the within-panel
duplication the bullet asserts does not exist. The panel's copy is single-sourced
and has never contained a duplicate pair. Two surfaces mentioning one condition is
*intended* — §23's placement decision exists so an operator can go from a refusing
session route to a running turn without leaving the page — while two surfaces
printing the same *sentence* is not.

**Fix.** No change to the panel's explanation. Fold the residual value into
J-web-stream-4: after that lands, the composer states the cause once and names the
path once, and the rail names the same path once behind a disclosure, which is a
different affordance answering a different question and is correct as shipped. Do
**not** drop the chip from the composer to reduce the count: that trades a §7A.8
obligation — the refusal names the file — for tidiness. Optionally sharpen §4.7's
rule to say it governs the identical sentence within one surface, and that two
surfaces may each name a shared condition once, which is what §23 relies on. Record
in the audit follow-up that the screenshot does not show a sign-in dialog, which is
itself evidence for J-web-stream-6.

**Tests.** A guard rather than a fix: no string in the rendered providers panel
appears twice as a leaf text node, in any state — which makes the claim checkable
rather than judged from a screenshot.

### J-web-stream-7 — the project observer re-creates its socket on every query settle

**severity** low · **surface** web · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Three WebSockets are created per page load and one is closed. Two open
sockets is intended — the stream column subscribes to the selected session and the
project observer to every enumerated session — but the third create is churn: a
socket that handshakes, sends a subscribe frame, and is torn down three milliseconds
later and replaced by another with a byte-identical frame.

**Reproduction.** A protocol trace records two sockets created at 79 ms, the first
subscribing to the selected session at 86 ms and the second to all three at 97 ms; a
third created at 104 ms; the second closed at 107 ms and the third sending the
identical three-session frame. Net two open, one wasted round trip.

**Root cause.** `web/src/api/projectRefresh.ts:112` lists both a stable key — the
subscribed ids joined into a string, computed precisely so the effect keys on the
*content* of the set — and the id **array** itself, which is memoised on two queries
that settle at different times, so when the second lands the memo returns a new array
whose joined form is unchanged, the identity comparison fails, and the socket is
closed and reopened. The selected session in the same list adds a second reconnect on
every tab switch even when the set is identical. The stable key is defeated by the
value it was derived from sitting beside it. The two-owner design is deliberate and
documented — the column's socket drops frames for unselected sessions and the column
unmounts when collapsed — so the audit's headline is by design and only the churn is
a defect; it is invisible without a protocol trace because the resume cursor is null,
so no events are lost, only a connection. Counting sockets and concluding "two is one
too many" would lead to merging the owners and reintroducing both holes the second
owner was added to fix.

**Fix.** Key the effect on content, not identity: read the array and the selection
through refs — the technique the stream hook already uses for its cursor, so it is
idiomatic here — and reduce the dependency list to the stable key and the client.
Derive the subscribe frame's id list from the key itself so the frame and the key
cannot disagree. Comment the trap, because the next reader will otherwise re-add the
array to satisfy an exhaustive-dependency lint — and check whether that lint is even
enforced here, since the config uses an untyped preset (J-mirrors-and-dx-36). State
in §7A.11 that two sockets per page is the specified steady state and that the
observer reconnects only when its subscribed set changes.

**Tests.** With a fake socket factory: settling the second query with the same id set
constructs exactly one socket, changing the set constructs exactly one more, and
switching the selection with an unchanged set constructs none; plus a protocol-level
end-to-end assertion that a load and one tab switch create exactly two sockets, since
unit tests cannot see connection churn.

### J-web-stream-9 — the terminal band prints an internal id as prose

**severity** low · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-5

**Symptom.** A live run's terminal band renders three lines: "Run ended", the
outcome, and "Terminal: terminal:run-…" — an internal identity, labelled with a noun
that reads as a shell terminal, at the same weight as the outcome the operator
actually needs.

**Reproduction.** `web/src/components/stream/Transcript.tsx:481-486` renders the id
with a label whenever the payload carries one; the same value is already on the band
as a data attribute at `web/src/components/stream/Transcript.tsx:471-473`, with a
comment explaining that the attribute is the exact identity.

**Root cause.** RC-5. The band renders every field of the terminal payload in the
same visual register, because §7.3 says the band *carries* the state and the terminal
id and "carries" was read as "prints" — which the attribute already satisfies twice
over. The id's only functional role in the client is backpressure detection, and the
band renders that as its own explanatory sentence anyway, so the operator never needs
to read the id to learn the fact it encodes. §7.1's 2026-09-03 amendment sets the
house rule for exactly this — the UUID stays on the title and the data attribute —
and was applied to session tabs only, one component over. Deleting the line without
amending the clause invites it back; hiding the id entirely would break the
backpressure story, which needs it machine-readable.

**Fix.** Move the id to the register the house rule assigns it: keep the data
attribute, add the id to the band's title, remove the visible line and its now-unused
style, and drop or repurpose the label copy key. The band then reads as the outcome
plus, where applicable, the backpressure sentence, which is the human form of what the
id encodes. Amend §7.3 so "carrying" is unambiguous, with the testable negative that
no visible transcript text matches the id shape.

**Tests.** A rendered terminal row carries the attribute and the title and no visible
id; a general copy assertion that no visible text the transcript produces looks like a
prefixed machine identifier, catching the class; and an end-to-end check that the
band's text does not contain the value of its own attribute.

### J-web-stream-10 — a rejected token renders "No workspace token"

**severity** low · **surface** web · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** —

**Symptom.** Opening the workspace with a token the server rejects renders a heading
saying there is no token above a paragraph saying the token this page holds was not
accepted. The heading and the body assert opposite things about the same state, and
the heading is the one an operator reads first.

**Reproduction.** A fresh context loading with an invalid token reports the
unauthorised absence in its data attribute, the heading "No workspace token" and the
correct rejected body, with four unauthorised responses recorded. Note that a
fragment-only navigation from an already-loaded page does not re-run the claim and
will not reproduce it.

**Root cause.** `web/src/components/NoToken.tsx:54-57` branches the *body* on the
absence kind and leaves the heading unconditional. The two-valued absence was
introduced to distinguish absence-at-open from a live rejection — its comment says a
rejection forgets the token and tells the gate so the panel remounts — and the
distinction reached the attribute and the body and never the heading, because the
copy file has no heading string for the second state. The gate's tests assert that
the attribute flips and that the body's wording changes, so the suite covers both
halves the change touched and neither notices the heading it did not. §2.2 speaks
only of "without a token", so it does not authorise or forbid the second state the
client actually has; the server's own error table already distinguishes missing from
invalid.

**Fix.** Make the heading track the same value the body and the attribute already
track: add one copy string and derive both strings from one branch, so a future
half-update is unrepresentable. Leave the shared guidance — start the server, open
the address it prints — unconditional, since it serves both states, as do the paste
field and the hold action. Add to §2.2 that the panel has two states and names both,
with the testable form that they share no string except the invitation to paste.

**Tests.** Extend the existing two-absence render test to assert the headings differ
and that the rejected heading is the new string; add a heading assertion to the
live-rejection remount test, so both paths are covered.

### J-web-stream-11 — the export chrome re-implements the export panel's state machine

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** moderate · **depends on** —

**Symptom.** Two components drive the same submission with the same five pieces of
state and the same three helpers, and only the pure helpers are shared. The refusal
mapping is written three times — once unexported, twice inlined — and the two run
implementations disagree about which state a new run clears, so in the panel a stale
fact renders beside a fresh refusal: after a successful export, a second refused
submission leaves the previous run's kerf block on screen under a live alert,
attributed by the fact primitive to a submission that produced no kerf at all.

**Reproduction.** The panel's run sets the state, clears the refusal and, on failure,
sets it — and never touches the result or the download refusal, while its markup
renders the kerf block unconditionally on the result and the refusal beside it. The
chrome's run additionally clears both. The chrome's two catch blocks each inline,
byte for byte, the body of the panel's refusal-mapping helper, which is declared
without an export and therefore cannot be imported.

**Root cause.** The chrome was written by copying the panel's stateful half: the
three *pure* helpers are exported and imported, and the one helper left
module-private was inlined instead — twice. Having two copies then let the two run
bodies drift, and whoever fixed the stale-result bug fixed it in the chrome and did
not carry it back, because nothing links them. In the panel the stale result is not
merely untidy: the fact primitive exists to bind a rendered value to the server
answer it came from, so a fact surviving into a submission that produced no answer is
a §1/§4.6 violation, not a cosmetic one. Adding one clear to the panel fixes today's
divergence and leaves three copies of the mapping and two hand-maintained state
machines, plus the panel's uncleaned download refusal — a second, independent
staleness.

**Fix.** Extract the shared half into one hook: both components hold identical state
and run identical transitions and differ only in the submission they build and the
markup they render, so a hook returning the state and the two actions makes the
divergence unrepresentable while each component keeps its own markup, which is the
part that legitimately differs. Move the four helpers and the hook into a module
neither component owns, re-exporting from the old path during the transition so
existing imports resolve. The hook's run clears the refusal, the download refusal and
the result before issuing — the correct semantics for a *new* submission, which the
chrome already has. **The one real hazard:** the submission-key map is module-scoped
on purpose, so a tab remount does not mint a new key for an already-sent submission;
moving it into hook state would silently break the at-most-once guarantee and look
like a passing refactor. Move it verbatim with its comment and keep the reset helper
as the test seam. Add the tightening to §22.2 — a new submission clears the previous
one's result and download refusal, and no fact may survive into a submission other
than the one that produced it — and add to `repo_conventions.md` that two components
driving one route share one state machine, since exported pure helpers are not
sufficient.

**Tests.** A successful export carrying a kerf followed by a refused submission
asserts the refusal is present and no kerf fact is rendered, driven from one shared
table against **both** components — the paired assertion is what keeps them from
drifting again; a failed download followed by a success clears the download refusal;
the same idempotency key is sent across a remount for an unchanged submission and a
fresh one when any field changes; and a cheap textual guard that the refusal literal
appears once per component. Whoever opens the test file should also fix the stubbed
global whose teardown leaks into the next block (J-mirrors-and-dx-19).

### J-web-stream-12 — raw NUL bytes make two TypeScript sources binary to grep

**severity** medium · **surface** web · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** —

**Symptom.** Four raw null bytes sit inside template literals in two source files.
Both are reported as binary data, a plain grep for the exported functions of one of
them returns nothing, and ripgrep reports a binary match with a byte offset instead
of the line. The bytes are invisible in every editor and diff, so a reader cannot see
them and a reviewer cannot review them.

**Reproduction.** Scanning both files for null bytes finds two in the transcript's
repeat signature and two in the visibility store's key prefixes; grepping the
visibility store for its exports exits non-zero with no output, while forcing text
mode finds them at their real lines.

**Root cause.** Two separate introductions with different stories. The visibility
store writes the separator as an *escape* in its key builder, and the nineteen-line
comment above it explains why at length: a raw null in a source file is invisible in
every editor and diff, and two independent readers of the module both transcribed it
as a space, each producing a key that matched nothing and a toggle that silently did
nothing, so the separator is spelled there and nowhere else, and a caller that
hand-builds a key is a caller that can get it wrong again. Two functions eight lines
below then hand-build the prefix with raw bytes — the comment's rule violated by the
file the comment is in, in the exact way it predicts, in its only commit. The
transcript's signature builder has no comment about its separator at all and gained
its bytes later, in a commit whose long message does not mention them. Functionally
both work, so no test fails; the harm is entirely to greppability, reviewability and
the file's own stated invariant. The correct pattern exists on the Python side, where
the same coalescing key is built as an escape with a docstring naming it. Replacing
the four bytes fixes today's files and guarantees tomorrow's, since the class is
undetectable by reading, by review, and by the tool one would use to look for it.

**Fix.** Three layers. Correct the bytes; remove the hand-building that let them
exist, by giving the visibility store a prefix helper beside its key builder so the
module's own "spelled here and nowhere else" rule is satisfied; and for the
transcript, prefer replacing the ad-hoc concatenation with a structured
serialisation — a signature used only for equality needs no sentinel character,
which removes the separator question entirely. Then add the mechanical check: extend
the repository's file scanner to fail on any control character other than tab and
newline in a tracked source, wired into CI beside the linters, and sweep the tree
once before enabling it so it lands green. Add the rule and its rationale to
`repo_conventions.md` and name the check in `CONTRIBUTING.md`. Semantically
identical, so nothing runtime, stored or wire changes.

**Tests.** The repository-level control-character check is the deliverable — it is
what would have caught both introductions; plus a transcript test pinning the
coalescing property the separator exists for, which is untested today, and a
visibility test asserting the two prefix builders agree with the key builder for a
name containing a space.

### J-web-stream-13 — the dedupe window claims a coupling it copied by hand

**severity** low · **surface** web · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** — · **root cause** RC-3

**Symptom.** The client's duplicate-detection window is a literal with a comment
asserting it is the server's bound, and the resync close code and reason are
literals too. Raising the shared limit moves the server's replay bound and silently
leaves the client's window where it is, after which a resume replaying more than the
window re-appends duplicates the window has already forgotten.

**Reproduction.** `web/src/stream/live.ts:80` is a bare 1024 whose comment
(`web/src/stream/live.ts:75-79`) says the server's per-client queue bound is 1024 and
that the live buffer's replay can never exceed what the buffer holds. That premise is
correct — the server's bound is read from `schemas/bridge_limits.json` — and the
mechanism is a hand copy. The close code and reason at
`web/src/stream/live.ts:65-67` duplicate the server's.

**Root cause.** RC-3. The client has no limits loader at all: both other consumers
read the shared document, and the browser has no filesystem and no route serves the
document, so the third consumer took the only route available. The document's own
preamble names two consumers; there are three. The comment also reasons from the
per-client *queue*, which is the drop policy, while the bound that governs replay
length is the live ring — the two are equal today by a decision, not an identity, so
if they were ever decoupled the comment would still read as sound while the number
became wrong.

**Fix.** Generate a small limits module for the client alongside the vocabulary
generator (J-mirrors-and-dx-1), emitting the numeric subset the client legitimately
needs, and put the resync code and reason in the events document. The window becomes
the generated buffered-events value and its comment states the derivation instead of
asserting it, naming the ring rather than the queue. Amend the shared document's
preamble to name all three consumers and the generation route for the browser one,
and point the specification's resync pair at the events document.

**Tests.** A drift test reading the committed documents from disk and asserting the
window equals the shared bound and the close pair equals the server's — the pattern
the export suite already proves — plus a behavioural companion: a replay of exactly
the window's worth of seen identities appends nothing and one more re-appends the
first, documenting the edge as tested rather than assumed safe.

### J-web-stream-14 — `SESSION_PROFILES` names two sets, and a reviewer session can be listed

**severity** medium · **surface** web · **verdict** partially confirmed ·
**effort** M · **risk** moderate · **depends on** B-9 · **root cause** RC-3

**Symptom.** One identifier denotes the complete runtime profile enum in one place
and the operator-openable subset in another, with a third constant alongside. The
client transcribes the subset and types every session row with it — but the listing
route applies no profile filter, and the review path creates sessions on that same
runtime with a runtime-internal profile. So an ephemeral termination-reviewer child
can appear in the browser's session strip as an attachable, promptable session,
typed as something it is not.

**Reproduction.** The bridge declares five profiles; the sidecar declares the same
five; the HTTP layer declares three admissible ones and, separately, two creatable
ones; the client transcribes the three. The listing decorates rows and filters
nothing, and its rows come from the runtime's principal map, which the review path
writes. The audit's line numbers are off and it counts three *sets* where there are
two plus a subset; the client's set and the HTTP layer's agree.

**Root cause.** RC-3, plus an enforcement gap. The three-member set is a *write*-side
validator applied at session creation and nowhere on the read side, while the HTTP
module's own docstring asserts the opposite — that the runtime-internal profiles are
ephemeral, own-budget, read-only-allowlist and "are not offered to a client that
could then prompt them". The client's title renderer degrades gracefully on an
unknown profile, so a leaked row would title itself rather than crash. No test pins
any of these lists against another. Renaming the client constant fixes the collision
and leaves the listing gap, which is the half with a user-visible consequence.

**Fix.** Three named sets, one place each: the complete enum and its creatable subset
in the shared vocabulary document, read by the bridge and the HTTP layer and
generated for the sidecar; the HTTP layer's admissible set renamed to say what it is
(client-visible), and **applied on the read side** so the docstring becomes true —
filtering in the HTTP projection, not in the bridge, which legitimately owns every
session. Extend the profiles projection the response already carries so the client
has a server answer instead of a transcription, and delete the client constant,
keeping only the union type. Consider widening the row's profile type to admit an
unrecognised server word, since the renderer already handles it and a type that lies
is worse than one that admits the possibility. State in §2.3 that the listing
projects only client-visible profiles and that the visible set is served. **The
filter changes the contents of a served route** — reviewer and snapshot rows stop
being returned, which is correct and which the project observer should not have been
subscribing to anyway — so ship it with its tests rather than splitting it, and review
the server tests that assert on listings.

**Tests.** Sessions created under each of the five profiles: the listing returns
exactly the client-visible ones; the three sets are asserted to nest, so they cannot
invert; a drift test pinning the client's union against the server's tuple and the
sidecar's list against the bridge enum; and the graceful degradation on an unknown
profile pinned as intended behaviour rather than luck.

## Agent tools

### J-agent-results-1 — `measure(kind="mass")` reports the volume in cubic millimetres, labelled grams

**severity** high · **surface** agent-tools · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** —

**Symptom.** The mass of a 40×20×6 mm box is reported as 4799.999… grams —
numerically identical to its volume in cubic millimetres and about 370 times the
true mass of that box in aluminium. No density, material or assumption appears
anywhere in the result, so the model cannot tell the number is a placeholder.

**Reproduction.** Building that box and measuring its mass returns
`{"value": 4799.999999999999, "units": "g", …}`; measuring its volume returns the
same number in cubic millimetres.

**Root cause.** `core/src/hephaestus/core/checks/facade.py:700-706` falls back to a
default density of 1.0 and `core/src/hephaestus/geom/measure.py:104-106` is a
unit-agnostic volume-times-density product documented as grams *when the density is
in grams per cubic millimetre*. Nothing binds a real density: the measure operation
does not pass one, and the executor's only production call passes imports and scan
data only. Three units are in play in one path — the materials registry stores
kilograms per cubic metre, the kernel needs grams per cubic millimetre, and the
facade's own docstring says grams per cubic centimetre. The single place that gets
it right is the bill-of-materials builder, which converts explicitly and returns
nothing when there is no material — the honest precedent this path should copy. The
default has existed since the engine's first commit and has never been changed;
the materials registry with real densities arrived later and was wired into the
manufacturing surfaces only. `script_contract.md`'s own worked example declares a
mass threshold in grams, so the code is wrong against a normative clause. **The fix
is already specified**: PHYSICS.md diagnoses this line by line and prescribes the
conversion constant and the refusal — but that document marks itself a
non-normative draft, so this is a known, specified, unshipped bug rather than an
unrecognised one, and the units half has no dependency on the FEA machinery the
draft is gated behind. Adding an assumed-density field to the tool result leaves
the same wrong number inside checks, where a predicate sees a bare float and no
disclosure at all.

**Fix.** Ship the units half now, independently. Put the kilograms-to-grams-per-
cubic-millimetre conversion at exactly one boundary — beside the resolved materials
record — and convert there and nowhere else. Delete the default density and make the
facade raise a named `mass_density_unbound` refusal, naming the part and saying a
mass is not a volume, when neither an explicit density nor a bound part density
exists; correct the docstring's third unit. Bind the density where it is known: the
worker resolves the part's material through the pinned registry the same way the DFM
and document paths already do, and the measure operation passes densities for every
addressed part that resolves one. Make the disclosure structural in the tool result —
the density, the material and its source — and return the discriminated refusal for a
part with no resolvable material. Amend the tool declaration and regenerate.
**Tightening:** a mass without a material stops returning a number. No corpus check
calls it, so the corpus is safe; two in-tree tests pin the implicit default and must
be rewritten as explicit-density tests, and PHYSICS.md's own audit item — every
fixture and corpus mass call — must be discharged before merge.

**Tests.** With no material, a named refusal; with an explicit density, an exact
product; with a registry material, the volume-times-density conversion, asserted as a
cross-path parity against the bill of materials so the two conversion sites cannot
drift; and the regression that would have caught this on day one — mass and volume
are not equal for any non-unit density.

### J-http-limits-3 — three read tools declare paging and implement none

**severity** high · **surface** agent-tools · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** — · **root cause** RC-9

**Symptom.** Asking for one line of a script from line 9999 returns the whole script
with a false truncation flag and no cursor. **Correcting the audit:** the two sibling
tools do not implement paging either — they merely emit the *static* members. The
model-facing consequence is the sharp one: the sidecar's text renderer chops a tool
result at its byte budget with a truncation marker of its own, so on a large script
the model receives a JSON string cut mid-value while the result says it is not
truncated and gives it no cursor — exactly the loss the tool contract forbids, since
the model is supposed to continue losslessly by byte cursor.

**Reproduction.** The script read returns the same document with and without paging
arguments, and its key set carries no paging members beyond a false truncation flag;
the globals read likewise returns a byte-identical document with paging arguments and
emits the static members only. The only genuine implementation in the repository is
the skill loader.

**Root cause.** RC-9. `server/src/hephaestus/agent_bridge/dispatch.py:1350-1366`
reads only the name, returns the content whole and hardcodes the truncation flag;
the globals handler takes its arguments under an underscore — the underscore is the
proof it discards them — and the project-check handler reads only the name. The HTTP
route faithfully forwards the paging arguments, so its own comment about handing the
tool's arguments through is true and the behaviour is still wrong. The declaration
side is complete: the contract gives the tool both parameters and splices the paging
result fields in, and the committed schemas are generated from it, so MCP clients see
the same promise. Both halves — the declaration and the unpaged handler — landed in
one commit, 7b9c89b, and a correct, tested pager already exists in-repo with byte and
line budgeting, absolute cursors and oversized-line detection. The client even
recorded the gap: a "reality note" in the script-paging hook says the shipped handler
does not implement paging today and that its continuation path is dormant against the
current engine and correct the day it is not. Implementing paging in the *route*
would satisfy a curl probe, break the verbatim contract and the test that pins it,
leave the **model** — the primary consumer, and the one being silently truncated —
unpaged, and leave the two sibling tools untouched.

**Fix.** One shared pager in the dispatcher, reusing the existing paginator rather
than writing a fourth: a helper that encodes to bytes, builds the line-start index,
pages, and returns the page plus the four declared fields, omitting the cursors when
they are absent. All three handlers adopt it; the numbering helper gains a start
argument, since it always starts at one today and would mislabel every page after the
first; the full file's line count stays a fact about the file, not the page. The route
needs no change — add a comment pointing at the dispatcher so the next reader does not
re-add paging there — and the client's dormant continuation path comes alive as
written. Resolve the one unsupportable declared member: the tool's result lists a
parameters field nothing can produce without a build, so either populate it from the
script's literals or strike it from the declaration and the documented signature —
never from the sandboxed probe, which would put a multi-second build inside a read.
Behaviour change for every caller: today's callers pass no paging arguments, so the
default page must return the whole file for every in-tree fixture; files above the
budget change to a first page with a cursor, which is the intended fix and which both
the client and the model already know how to continue.

**Tests.** A script longer than the budget: page one is truncated with an absolute
cursor, and reading the artifact from that cursor continues exactly — no overlap, no
gap, byte-identical when concatenated; an offset past the end returns an empty page
rather than the whole file; a one-line limit returns one line and the numbering starts
at the page's first line; a single oversized line reports its own flag and offset; the
same three assertions for the two sibling tools; the route's equality with a direct
dispatch extended to a paged case; and a schema-conformance test that every declared
paging member is produced for a truncating input — the gate that would have caught the
original commit.

### J-agent-results-2 — `edit_part` returns a success-shaped no-op for an absent match

**severity** high · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** A failed exact-match edit is indistinguishable from a no-op success:
not applied, an empty diff, line zero — no reason, no diagnostics, no near-miss
candidates. The model's only recourse is to re-read the file and guess. Its
stale-hash conflict is also missing half the declared payload. The same defect
reaches the REST surface, which dispatches the same tool and returns 200 with the
identical body.

**Reproduction.** An edit whose old text is absent returns exactly three fields with
no reason, while the two sibling editors return a named validation error with
diagnostics naming the occurrence count. A stale-hash edit returns a conflict with
three fields where the declaration lists nine — and the *same tool's* later
compare-and-set path builds the full one.

**Root cause.** `server/src/hephaestus/agent_bridge/dispatch.py:1410-1411` returns
early for zero occurrences while the very next branch raises a proper ambiguity
refusal for more than one — the zero case was simply never given a name. Separately,
the stale-hash pre-check builds its own three-field conflict while the store's
compare-and-set failure builds the declared one, so one tool has two conflict shapes
and the specification declares one. The early return is Stage 2A (7b9c89b); the
named refusal in the two sibling editors is Stage 2B (5329250), the *next day* — Stage
2B wrote the globals and project-check editors with a named refusal and a complete
payload and the Stage 2A part-file editor was never brought forward. This is the same
one-day divergence inside one file that produces J-agent-results-11. The
specification's promise that an exact-match failure returns closest candidates is
unimplemented for all three editors. Adding a reason and stopping leaves the two
conflict shapes, which is what makes the continuation rule unenforceable: a model
that receives no truncation flag cannot know whether the returned script is the whole
file, and the early-return path applies no cap at all, so a large part blows the
model's context limit.

**Fix.** Give the part editor the same refusal vocabulary as its siblings —
a discriminated validation error whose diagnostics name the occurrence count — plus a
bounded near-miss block that discharges the candidates clause: at most three
`{line, text, ratio}` entries from a close-match pass over the file's lines or
sliding windows, deterministic in cutoff, count and ordering, since the tool result
feeds the bench. Keep the not-applied flag so the existing schema and every caller
keep working. Extract one conflict-payload helper used by *both* the pre-check and
the compare-and-set path, emitting the full declared field set with the cap applied
and the continuation cursor set when it bites — the CLI already has this helper, so
reuse it rather than writing a third. Apply the same near-miss block to the two
sibling editors so all three satisfy the clause identically. Declare the new members
and regenerate. Additive on the result; the only removal is the impoverished conflict
branch, replaced by a strict superset. The HTTP fix is free, since the route
dispatches the same tool.

**Tests.** An absent match returns the contract kind with diagnostics naming the part
and at least one candidate pointing at the nearest real line, asserted to have the
**same shape** as the sibling editor's for the same input — a parity test, so the two
cannot diverge again; the two conflict paths produce byte-identical key sets; a part
over the cap conflicts with a usable continuation cursor; and the REST route carries
the reason.

### J-agent-results-3 — `read_artifact` on a binary artifact returns a complete, empty page

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Reading a build artifact returns the success branch of the result
schema — empty content, an octet-stream mime, zero offset, the real byte total and a
false truncation flag — asserting that a multi-kilobyte artifact was read completely
and is empty. The model has no discriminator to branch on, the mime type is a
free-form string in the schema, and nothing names the tool that *would* read this
artifact.

**Reproduction.** Reading a build reference returns exactly that document. (The
audit's quote omits the mime type, which is present; that softens the finding without
removing it.)

**Root cause.** `server/src/hephaestus/agent_bridge/cad_ops/_artifacts.py:70-93`
branches on the artifact kind and constructs a page-shaped dictionary rather than a
refusal, and reuses the same shape for any unknown kind whose bytes fail to decode.
The result schema has exactly two branches — the page and an invalid-offset refusal —
so there is no third shape for the binary case to occupy, and the code takes the only
one available. The binary kind set was *widened* by a later commit when the web
workspace added its own artifact kinds, rather than reconsidered. The tool
documentation says binary artifacts return metadata and must be consumed by their
dedicated path: the code obeys the first half and leaves the second unenforceable,
because nothing in the payload says which path. Setting the content to null would
leave the result in the success branch, so the sidecar's validation still types it as
a completed read and the model still has nothing to branch on; and it would leave the
sneakier second case, where an artifact of an unknown kind whose bytes do not decode
returns the same empty success and the model cannot tell an unsupported kind from
corrupt bytes.

**Fix.** Add a third discriminated branch — a binary-artifact status carrying the
kind, the mime, the byte total, the tool that consumes it and a sentence — with the
consuming tool taken from a small explicit map beside the binary kind set, asserted
total at import so a new binary kind cannot be added without naming its reader. Add a
fourth for the undecodable case, because "this kind is binary by design" and "these
bytes are not UTF-8" are different facts. Keep the page-shaped fields for one release
so a naive consumer does not crash, with the status making the discriminator
unambiguous. Declare both branches and regenerate the schemas and the TypeBox module
together, since the drift test enforces that they land as one. Replace the
documentation's one-sentence rule with the two status names and the mapping, so a
future binary kind has to declare its reader. Check the HTTP text route emits the same
discriminator or an equivalent refusal.

**Tests.** Reading a build, a render and an export reference each returns the binary
status with the right kind, a real consuming tool and the true byte total; a text kind
is byte-identical to today, including the paging contract; a non-decoding unknown kind
returns the *other* status; and the reader map is total over the binary kind set — the
guard that stops a new kind reverting to the empty page.

### J-agent-results-8b — an unresolvable solve reports sentinel generations and refs

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** An unresolvable solve returns generations of `-1` and proposal, proposal
reference and trace reference of `""`. Minus one is not a generation and the empty
string is not a reference; both are typed as real values in the schema, so a consumer
that records or diffs generations records minus one as if it were one. For the
stale-inputs refusal in particular the generations *are* known at raise time and are
thrown away.

**Reproduction.** A solve whose joint anchors a missing part returns the unresolvable
verdict with those five sentinels, an empty solver core and an empty verification
block, beside a correct reason, subject and detail.

**Root cause.** `core/src/hephaestus/core/placement.py:829-908` types the generations
as integers and the three references as strings with no nullable option, so the two
unresolvable constructors have no way to say "not established" and pass the
sentinels; the refusal exception carries only a reason, a detail and a subject, so
even the raises that happen *after* the generations were read cannot report them.
This is the newest defect in the cluster, introduced by 715400e "feat(stage13): the
solver proposes, nothing applies" — the same commit that wrote the docstring the
sentinels contradict, which reasons carefully about not claiming solver-core or
verification blocks and then fills the two adjacent integer fields with minus one
because the dataclass required an int. SOLVER.md's "refusals are not verdicts" rule —
a kill decided nothing, and giving it a verdict spelling would let a timeout read as
an outcome — is the principle, and the specification is silent on how a refusal
encodes a fact it never established. Nulling the fields only on the unresolvable path
would miss the more useful half: for the resolution-time refusals the generations are
known and are exactly what a reader needs.

**Fix.** Make "not established" representable and report what *was* established:
widen the generations and the three references to nullable with a null default and
emit JSON null, deleting the sentinel literals; add the two generations to the
refusal exception and populate them at every raise site that occurs after the
corresponding state was loaded. Accept both null and the legacy sentinel when reading
a stored proposal, so an old document does not resurface one. Add the clause to
SOLVER.md's refusal rule — a refusal encodes an unestablished fact as null, never as a
sentinel inside the field's normal domain, and reports every fact it did establish —
and list which fields are nullable on which verdict. **The real risk:** the record's
canonical form is the input to the byte-identity determinism claim and to the
proposal store's content addressing, so this changes every refusal record's hash;
that is acceptable for a one-time encoding fix done in one commit with the
determinism suite green.

**Tests.** An unresolvable solve emits null for all five and the sentinel appears
nowhere in the canonical form; a stale-inputs refusal *reports* the generations it was
refused against — the half a null-everywhere fix would lose; the byte-identity
assertions re-run over a refusal record; and a stored document containing the legacy
sentinel loads as null.

### J-agent-results-9 — a project-scope check report returns the project name in a field named `part`

**severity** low · **surface** agent-tools · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** —

**Symptom.** A project-scope check run returns a report whose part field holds the
*project* name. Reading that part refuses, and if a project ever has a part sharing
its name the field becomes actively misleading rather than merely empty.

**Reproduction.** Running project checks on a project with one part whose name
differs returns a payload whose part field is the project's name.

**Root cause.** `core/src/hephaestus/core/types.py:572-599` gives the report a
mandatory part field — the record was defined for the part-scope case — and both
project-scope callers satisfy it by passing the project name:
`server/src/hephaestus/agent_bridge/cad_ops/_checks.py:266` and
`core/src/hephaestus/core/checks/report.py:77`, the latter being `heph check`. The
operations layer then copies the report's JSON and overwrites only four keys, so the
part field rides through untouched. Project scope was bolted onto a part-shaped
record rather than the record being widened, in the commit that added it (5329250).
The specification declares the result type for both scopes and says nothing about
this field in project scope, and the architecture record never names it — so both are
incomplete, and the code answers with a value that is not a part. Every check result
in the payload is correct; this is a naming and shape defect. Blanking the field in
the operations layer alone would leave `heph check --json` — the named joint the HTTP
route and the CLI both call — still emitting the project name under the same key.

**Fix.** Give the record a scope-aware subject: add a scope discriminator, make the
part nullable, and move the project name — genuinely useful provenance — into its own
field rather than masquerading as a part. Thread the scope through the check runner
so both project-scope callers pass it and the operations layer stops overwriting the
key it now receives correctly; make the part-scope payload pass its scope explicitly
rather than hardcoding it. Default the scope to part when reading a record written
before the change, so every stored report still loads. Declare the change, regenerate,
and render the project field where the CLI renders the part today. State the fields
and the discriminator in the architecture record and in the tool documentation.
Consumers to thread in the same commit: the web check panel, the CLI JSON, the bench
grader's report reading and any retained check-report artifact.

**Tests.** Project scope returns the discriminator, a null part and the project name;
part scope returns the discriminator, the part and the project name; a document with
no discriminator loads as part scope; and the CLI JSON carries the project under its
own key.

### J-agent-results-11 — addressing refusals leak the host path and drop the candidates

**severity** low · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** — · **root cause** RC-4

**Symptom.** Every part-addressing refusal names the operator's home directory, and
three call sites throw away the useful half: reading an unknown part returns a reason
with **no** candidates, while building the same unknown part returns the same reason
*with* them. The message reaches HTTP clients verbatim.

**Reproduction.** Reading, editing or writing an unknown part returns a message
naming the absolute parts directory and a payload carrying only the reason; building
it returns the same message and a payload carrying the reason and the two candidates.

**Root cause.** Two independent causes at the same three sites. The store and the
check reader interpolate an absolute directory into the message, where the error's
candidate list already carries everything a caller can act on; the sibling refusal for
imports raises the *relative* form, and the documented CLI paths are relative, so the
relative form is what the documented surface uses. And
`server/src/hephaestus/agent_bridge/dispatch.py:1355`, `:1400` and `:1429` each wrap
the engine's addressing error locally and drop the candidates, even though the
dispatcher's central handler already preserves them — the three local handlers shadow
the good one. The three lossy handlers are Stage 2A and the central one is Stage 2B,
the next day: the same one-day divergence that produces J-agent-results-2, in the
same pair of commits. No clause forbids a host path in an error message and one tool
deliberately returns a path, so the path half is an inconsistency to normalise rather
than a violation; the candidates half is a straightforward defect against the
dispatcher's own stated contract.

**Fix.** Delete the three local handlers so the central one catches — the reason
string is identical, so this is purely widening — and make the two path-bearing
messages project-relative by interpolating the directory-name constants rather than a
resolved path, so a refactor cannot reintroduce an absolute one. Optional hardening
worth doing in the same pass: one redaction of the project root applied where engine
messages become HTTP response bodies, so a message from an unaudited path cannot leak
the tree — cheap, and it makes the property testable in one place. Add the rule to
the tool documentation's conventions, which already refuses absolute paths as
*inputs*: a refusal names project-relative locations only, with the one deliberate
exception documented as such. Grep for tests asserting the absolute form before
landing.

**Tests.** The three read/write/edit refusals carry the same candidates as the build
refusal for the same name — a parity test across the four, so a future local handler
cannot silently reappear; no refusal message contains the project root, asserted
across five verbs; the HTTP body for an unknown part carries candidates and no
filesystem root; and the credential-leak sweep extended to the root string.

### J-agent-results-8a — `check_motion` reports an empty-string artifact reference

**severity** low · **surface** agent-tools · **verdict** partially confirmed ·
**effort** S · **risk** low · **depends on** —

**Symptom.** A motion check whose joint anchors a nonexistent part returns a map of
that part name to an empty artifact reference. The model sees a part mapped to a
reference whose id is the empty string, which reads as "this part has an artifact"
rather than "this part contributed nothing" — while the real reason is already
elsewhere in the same payload, as a named unresolvable reason with a detail.

**Reproduction.** The motion payload carries the empty-string mapping beside a
blocking joint whose reason names the missing part and whose detail names the known
parts.

**Root cause.** `core/src/hephaestus/core/assembly.py:652-663` returns the empty
string for a part whose geometry could not be loaded, and that map goes straight onto
the motion and assembly statuses, is serialised verbatim to the model, *and* is stored
as the projection's parts map. The sentinel is deliberate at the persistence layer —
the projection documents it as recording the reference each part contributed at
evaluation time, with the empty string meaning the part had no current build then,
which is itself a fact the next build invalidates — and the projection loader
*requires* every value to be a string, so null would raise. It was introduced by
8f781f8 "feat(stage9a): joints and posed evaluation — Gate G9A green" for the
projection, and the model-facing exposure is incidental. No clause anywhere defines
the value domain of this field, so the specification is incomplete and the code is
defensible: this is a presentation and documentation defect, not a correctness one.
Changing the accessor to emit null would break the projection loader and change the
persisted map that staleness comparison keys on — a store-format change for a
presentation problem.

**Fix.** Keep the store's sentinel; make the model-facing document say what it means.
In the two statuses' serialisation only — not in the projection, which is built from
the dataclass field rather than the serialisation, so the split costs nothing — map
an unresolved part to null, and accept both encodings on read so a status written
before the change still loads. Widen the declared value type and regenerate. Leave
the projection loader's string requirement exactly as it is. The deliverable is really
the specification sentence: define the field's value domain in both check tools' rows
— the reference each addressed part contributed at evaluation time, null for a part
whose geometry could not be loaded, whose reason appears in that part's own outcome.
The cheaper alternative — keep the empty string and document it — is defensible given
the reason is already in the payload, but it leaves a magic empty string in a
model-facing document, which is the category of thing this codebase otherwise refuses.

**Tests.** A constraint anchoring a missing part yields null in the serialised
document while the projection's map still holds the empty string; the round trip
accepts both encodings; and the projection loader still refuses a non-string, so the
store's contract is pinned as unchanged.

### J-agent-results-S5 — check-file snapshots are minted under the part-snapshot kind

**severity** low · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** The project-check read and edit tools return snapshot and journal
references of the part-snapshot kind for a file that is not a part. A reader holding
one cannot tell whether it snapshots a part script or a check script; the kind is the
type tag in an otherwise opaque capability, and it lies.

**Reproduction.** Reading a project check returns a snapshot reference whose kind
segment is the part kind.

**Root cause.** `server/src/hephaestus/agent_bridge/cad_ops/_checks.py:75-86` mints
the reference with the part kind because the payload happens to be Python source and
that kind is registered as readable text, so the reference works through the artifact
reader. Every consumer inherits the wrong kind from that one call, including the
conflict payload and the base reference the edit tool reconstructs. The same commit
that added these tools also added two correctly-named check kinds in the same file, so
the correct pattern was being written alongside and the snapshot reference reused the
nearest existing kind. Because references are content-addressed there is no collision
hazard, so the defect is one of type honesty — but the kind routes retention classes
and dispatches the artifact reader, so it is not decorative. Changing the returned
string without registering the new kind as readable text would make the reference
unreadable and silently degrade the conflict-continuation contract.

**Fix.** Introduce a check-snapshot kind as first-class: mint it in the reader,
register it with the Python-source mime so the artifact reader keeps working, and
switch the edit tool's reconstruction of the base reference — **in the same commit**,
or a client's own reconstruction from its expected hash will not match the server's.
Accept both kinds on read for one release, since retained check-report and journal
evidence carries the old one. Audit the retention configuration for a kind-keyed rule:
a new kind must be classified, not defaulted. State in the project-check tool rows
that these references are of the new kind and are readable, so the continuation rule
applies to them too.

**Tests.** The read, create and edit tools return references of the new kind and the
artifact reader returns the check source with the source mime; a stale conflict's base
and current references share a kind — which they did not have to before, and a
mismatched pair is exactly what a client-side reconstruction would produce; a legacy
reference pointing at a check blob still reads; and the new kind is classified for
collection rather than defaulted.

### J-http-envelope-9 — a cursor naming an unknown mark reads as a complete, empty history

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** B-11a

**Symptom.** A well-formed cursor whose frozen mark names no entry, and whose offset
is past the end, answers 200 with no events, done, and an end cursor echoing the bogus
mark. A client walking history stops and renders an empty transcript as complete — the
same visible outcome as a genuine end of history, with no way to tell them apart, on a
session with hundreds of recorded events.

**Reproduction.** Requesting history with such a cursor returns an ok status, no
events, no prompts, done, and the bogus cursor echoed back, against a session with
250-plus events.

**Root cause.** `agent/src/session/history.ts:611-614` widens the frozen snapshot to
the *whole log* when the mark is not found, with a comment saying it should not happen
for append-only logs, and then a slice past the end yields an empty page and a done
flag — two lenient fallbacks composing into a confident wrong answer. Note the
interaction with the malformed-cursor item: a cursor that fails to *decode* throws and
becomes a runtime-unavailable refusal, while a cursor that decodes to nonsense
silently succeeds, so the same class of client error takes two opposite paths
depending on which kind of nonsense it is. The specification covers the *legitimate*
past-the-end case — a tail token beyond the current end returns no events, done, and
the same end cursor — and that clause is correct and is about a quiet session; the
code reuses its shape for a condition the clause is not about. Refusing a missing mark
alone leaves the past-the-end case inside a valid snapshot, which produces the same
silent empty page; refusing both without distinguishing the legitimate quiet tail
would break polling.

**Fix.** Distinguish three conditions the code currently answers identically. A mark
that names no entry in a non-empty log is a malformed-cursor refusal, mapped through
the same invalid-parameters path the decode failure will take once B-11a lands — with
the empty-mark case, which the sidecar itself mints for an empty session, still
working. An offset strictly greater than the snapshot's length is a client error; an
offset *equal* to it is the legitimate done case and must stay 200, which is the whole
of the care required. Mirror both refusals in the fake agent so the contract is
testable without a sidecar, and restage the bundle. Add the negative half to the
history clause: a cursor whose frozen mark names no entry, or whose offset lies
strictly beyond the snapshot it names, is refused — it is not reported as an exhausted
walk, because a client cannot distinguish that from a genuinely empty transcript.

**Tests.** An unknown mark over a non-empty log throws; an empty mark over an empty
log still returns the empty page; an offset equal to the length returns done with no
error and an offset strictly greater throws; end to end, a bogus mark is refused while
an unqualified read still returns the full transcript, proving the events were there
all along; and the polling contract — a valid tail token at the exact end returns done
with a byte-identical end cursor — as the regression the fix must not break.

### J-agent-wiring-6 — delegation accepts a part that does not exist

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** B-2

**Symptom.** Delegating to a part name absent from the project is admitted: a durable
delegation row and a child run are created and the orchestrator is told the work
completed. The model believes a part it never created has been built. The declared
rejection reason for exactly this case is emitted by nothing.

**Reproduction.** With a real delegation service and a completing runner, delegating
to a name absent from the parts directory returns a completed status with a synthesised
part session id, a child run id and a delegation reference; the gate in force is the
permissive default.

**Root cause.** `server/src/hephaestus/agent_bridge/delegation.py:148-152` defaults
the pre-admission gate to one that never rejects, with a comment saying tests inject
their own, and no non-test code constructs a gate — every construction in the
repository is under a test or the testing package, and only two of those pass one. The
dispatcher's delegation path reads the part name straight out of the arguments and
never touches the project store, minting the session id from the string alone. The
service's own docstring names where the check should live — pre-admission
classification is a policy the session service owns and is injected — and that session
service is itself never constructed outside tests, because the per-session lease layer
it belongs to was superseded in production by a coarser process-level record, and the
gate went with it. The rejection reason and the gate protocol were authored together,
correctly, on day one. The tool documentation says delegation is to an *existing* part
and that a rejection before admission has no child run or reference. Adding an
existence check inside the dispatcher would put policy in the state machine, which the
service separates deliberately for testability, and would leave three more declared
reasons unreachable.

**Fix.** Implement the gate the protocol was designed for, in the layer that has the
facts, and inject it where the wiring change constructs the service: a project gate
holding the project store and the live-run map, classifying an illegal or absent part
as the invalid-part reason, a part whose own session has a live turn as part-busy, a
session held by a foreign live owner as session-busy, and self-delegation as
scope-denied — closing a clause that is documented and untested. All four checks are
reads, which the protocol requires. Resolve the part through the store rather than a
bare file test, so the same refusal and candidate suggestions the read tool gives are
what the delegation reports. Then make the permissive default unavailable in
production: move it into the testing package so a service constructed without a gate
is a type error — the change that stops the class rather than the instance. Name the
gate's home in the digest, and record that the lease service was superseded, which is
undocumented and is why the gate had no obvious home.

**Tests.** The gate refuses a missing part, an illegal identifier and a traversal
attempt and accepts an existing one; delegating to a nonexistent part returns the
rejection with **no** child run or reference keys and no durable row, pinning the
no-child clause; self-delegation is refused, closing an untested clause; and a service
constructed with no gate is a type error.

### J-cli-startup-9 — `run_checks(scope="part")` pays a full rebuild for a part with no checks

**severity** medium · **surface** agent-tools · **verdict** partially confirmed ·
**effort** M · **risk** medium · **depends on** J-cli-startup-7 · **root cause** RC-6, RC-7

**Symptom.** The audit reports that a part-scope check run takes as long as a build
and appears to rebuild. It does not merely appear to: it *is* a rebuild, by design.
What is defensibly wrong is that it costs the same for a part that declares **no**
checks at all, where there is provably nothing to re-run.

**Reproduction.** Against the workspace fixture, building a part takes 3.316 s and
running its checks 3.434 s and 3.609 s, both returning an empty check map, because the
fixture part declares none — and each run spawns the sandbox, re-imports the kernel in
the worker, re-executes the script, rebuilds the geometry and publishes a preview.
The floor for a trivial box in the same sandbox is 3.346 s.

**Root cause.** RC-6 and RC-7. `server/src/hephaestus/agent_bridge/cad_ops/_checks.py:178-207`
unconditionally freezes inputs, runs the full worker build and publishes a preview.
The rebuild is intrinsic and correct: the predicates are lambdas that exist only in
the worker's namespace, which the worker says in as many words, and the script
contract confirms they are script-local closures over a facade bound to the built
geometry — so there is no way to re-run a real predicate without re-executing the
script. The avoidable cost is the empty case: the build record persists the check
results, so an empty map plus unchanged inputs is a complete answer. Note that the
declared check *names* are computed by the worker and dropped at publication — the same
omission class as RC-6 — so an empty results map is currently ambiguous between
"declared none" and "declared some that failed to register". Returning the recorded
results for *any* part would satisfy the latency complaint and break the tool's whole
purpose: a check that passed on the recorded build may fail against an edited script,
and this tool is the model's verification step, which the sidecar's own guidance tells
it to prefer.

**Fix.** One conservative precondition: when the part has a current successful build
whose input hashes revalidate against the live script, parameters and dependencies,
**and** whose recorded check map is empty, return the empty report immediately with
the recorded artifact reference; every other case takes the existing path unchanged.
Factor the input-hash revalidation out of the publisher into a reusable read-only
predicate, so this item and J-cli-startup-7's first tier share **one** implementation
of "is the current build still an answer for the live inputs" — extracted twice, the
two copies drift, and the drift is a correctness bug rather than a style one. Persist
the declared check names alongside the parameters declaration so the empty case is a
recorded fact rather than an inference. Do **not** extend the fast path to a non-empty
check set. Add one sentence to the tool's row saying a part whose current build
recorded no checks and whose inputs are unchanged answers from the record, because
there is no predicate to re-run. Behaviour-preserving for every part that declares a
check; the one observable change is that the empty case no longer mints a preview
artifact, so grep for assertions on preview counts.

**Tests.** Spying the sandboxed run: zero invocations for a part with a current build
and no checks, returning an empty map with the current reference; the same part after
an edit that adds a check takes the full path and returns the new verdict — the
staleness guard; a part with a non-empty check map **always** takes the full path even
when unchanged, which is the contract test that stops the optimisation creeping; and
the existing preview-publication and failing-check coverage unchanged.

## Sidecar and server internals

### J-agent-wiring-13 — `py.*` handlers run inline on the single reader thread

**severity** high · **surface** server-core · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** No user-visible symptom today, because every shipped handler that could
block was stubbed out or answers from local state. It is the structural reason the
delegation half of the wiring work cannot land, and it already degrades a shipped
guarantee: while a question is suspended waiting for a human, the reader thread is
blocked, so **no** frame from the sidecar can be read — including the response of a
prompt on a *different* session. The promise that a part session and the orchestrator
may think at the same time is defeated for the duration of any pending question.

**Reproduction.** Static and unambiguous: one reader thread is created at start; the
read loop calls the frame handler inline for every decoded frame; the frame handler
routes an inbound request to the dispatcher, which calls the registered handler
inline on that same thread; and an outbound call writes a request frame and blocks
waiting for a response that can only be delivered by the thread now inside the
handler. The file states the invariant itself at
`server/src/hephaestus/agent_bridge/supervisor.py:373-374` — a hook is fired outside
the process lock on purpose, because it issues real requests and a blocking call
under that lock would deadlock against the reader thread.

**Root cause.** The inbound path has no work queue: read loop, frame handler,
dispatcher and handler are one synchronous call chain on the reader thread, and the
outbound call is blocking request/response over the same pipe, so any handler that
re-enters closes the cycle. The design is coherent for handlers that answer from
local state, which is every handler that ships. The question handler already violates
the spirit by blocking the reader thread on an event for as long as a human takes,
without closing the cycle, so it manifests as a stall rather than a hang. Both the
dispatch shape and the stubbed delegation handler were written in 7b9c89b, and they
are the same decision seen from two sides: the runtime-core slice could not execute a
child *because its own transport could not survive one*, so delegation was deferred to
a second supervised process with its own reader thread — which is exactly why the
delegation runner works there. Threading one handler just for delegation fixes one
handler and leaves the class open for the next re-entrant one, and leaves the
question stall, which is a live degradation today.

**Fix.** Move `py.*` handling off the reader thread onto a bounded worker pool,
preserving frame order for notifications and the existing error mapping: the
supervisor gains a small pool created at start and shut down after the child is gone;
the dispatcher submits the request and the worker runs the handler and sends the reply
exactly as today. Verify the frame writer is thread-safe now that two workers can
reply concurrently. Backpressure matters — an unbounded pool lets a misbehaving
sidecar spawn threads without limit — so when the queue saturates, reply with a named
overload error rather than blocking the reader: failing one tool call is strictly
better than stalling the pipe. Source the worker count from the shared limits document
rather than a literal. Add a normative sentence to the design document that a handler
may issue outbound requests and therefore runs on a bounded pool, never on the frame
reader. **Ordering change to reason about:** requests could previously only be
processed one at a time in arrival order and can now complete out of order — already
true of every response, which is correlated by id — but this makes two concurrent
stateful tool dispatches from one sidecar actually concurrent for the first time,
where the HTTP side has an explicit lock and the main sidecar path has none. Confirm
the store's idempotency covers it or add a per-project lock for sequential tools in
the same change.

**Tests.** A handler that itself issues an outbound call returns within a short
timeout — the test that hangs today and is the direct pin; two concurrent handlers
each sleeping complete in about one sleep, not two; a saturated pool returns the
overload error while an unrelated outbound call still completes; and, with a question
pending on one session, a prompt on another completes.

### J-build-state-5 — four hand-copied bounded-subprocess loops

**severity** medium · **surface** server-core · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** — · **root cause** RC-8

**Symptom.** The same thirty-line spawn/poll/deadline/drain/kill loop is written four
times. The audit called two of them byte-identical; the precise finding is worse. The
newest copy carries **two** correctness fixes the other three never received — a
post-deadline drain of the pipe, and a recomputation that a run which answered can
never be reported as having died. So a compare or motion pass whose child answered a
millisecond before the ceiling is reported as a timeout with its answer sitting unread
in the pipe.

**Reproduction.** Diffing the compare and motion loops shows them identical modulo
indentation, the per-protocol receive body and one comment reflow. The scan copy has,
after the main loop and before the cleanup, a second drain whose comment says a
direction that finished a millisecond before the ceiling is a measurement and throwing
it away because the clock ran out while it sat in a buffer would make the refusal
poorer than the run actually was — and then recomputes the death flag so that
"the subprocess died" can never be said about a run that answered. Neither the compare
nor the motion copy has either. The fourth, in the placement verifier, never sets a
death flag at all.

**Root cause.** RC-8. Process supervision is policy living beside each caller instead
of in one module, so every fix has to be re-applied by hand and nothing enforces that
it was. Concretely: an end-of-file inside the death drain can be raised *after* an
earlier receive in that same drain already produced an outcome, so a run that answered
is marked dead — the recomputation is exactly that repair; and the compare and motion
loops exit on the deadline without looking at the pipe again, so a terminal message
that landed during the final poll window is discarded. Three commits in copy order:
the original with the bench-audit repairs, a copy into motion whose own docstring
names its source, a third into the placement verifier citing motion, and a fourth into
scan that silently *improved* it — the two fixes appear in that commit alone and its
long message mentions neither, so they were never flagged for back-porting and nobody
knew to. The comparison specification assigns process management to the engine as a
concern and never says which module owns it. Back-porting the two fixes by hand fixes
today's drift and guarantees tomorrow's: four copies of a five-part invariant with
nothing pairing them — and it does not help the two reason-split items, which each
need the death signal the loop computes.

**Fix.** One helper module owning the loop, with each caller keeping only its message
protocol and its refusal vocabulary. Take the scan body as the implementation, since it
is the only correct one, so the refactor reads as "three call sites gain two fixes"
rather than as a rewrite. The helper is pure Python with no geometry import, keeping
the solver's import-closure clause trivially satisfiable at the placement call site,
and exports an outcome carrying the terminal message, the death flag and the exit
code; the only thing that differs between the four is a callback that says whether a
message is terminal. It owns the spawn and pipe close, the poll and deadline loop, the
drain on death, the join before reading the exit code — keep the compare copy's
comment, which is the best-written of the four and explains why the join precedes the
read — the post-deadline drain, the death recomputation and the kill/join/close
cleanup. The per-site phrasing stays at the call sites, because each cites its own
specification section. Name the owning module in the comparison specification, and add
a line to the quality bars extending the "supplies policy, does not duplicate
machinery" rule to subprocess supervision inside the engine. Scan is
behaviour-preserving and is the control; the other three are behaviour-*correcting*,
so their gates need review rather than a mechanical re-run.

**Tests.** A new suite parametrised over all four call sites, one case per behaviour
only the newest copy had: a child that sends its terminal message inside the last poll
window is **not** reported as cut short — which fails today for three of the four; a
child that answers and then closes the pipe is not reported as dead; a child that exits
without answering yields the real exit code. Every existing bounded-compare, motion,
scan and solver assertion must pass unmodified, especially the ones that pin no child
outliving its ceiling, which is the property most at risk in a cleanup-block refactor.
Plus a structural guard, in the spirit of the existing purity greps, that the
multiprocessing import appears in the helper and in no other engine module — which is
what stops a fifth copy.

### J-build-state-4 — a crashed compare child is refused as a timeout with a ceiling it never reached

**severity** medium · **surface** server-core · **verdict** partially confirmed ·
**effort** M · **risk** medium-high · **depends on** J-build-state-5 · **root cause** RC-8

**Symptom.** When the comparison subprocess dies without sending a terminal message,
the parent raises the *timeout* refusal carrying a 300-second ceiling, after however
long the child took to die — measured at 2.73 seconds. The child's traceback goes to
the server's stderr and never reaches the caller, and the structured refusal carries no
exit code. Four surfaces are told "timeout": the model's tool error, the CLI's JSON,
the check report's unverifiable entry, and the bench budget refunder. The remedy the
tool documentation offers the model — raise the ceiling — is wrong for a crash.

**Reproduction.** Forcing the child to die before its first send yields the timeout
reason with an elapsed time of 2.73 s and a declared ceiling of 300 s, and a message
that says both "subprocess died (exit code 1)" *and* "ceiling 300s" — the prose carries
the truth and the machine fields do not.

**Root cause.** RC-8. `core/src/hephaestus/core/project_compare.py:501-519` computes
the distinction and discards it: the death branch rewrites the *message* only, and the
raise is unconditionally the timeout type carrying the ceiling. The refusal reason is a
closed literal set with no member for a dead child, so the timeout type hardcodes its
reason and its serialisation emits the ceiling. Its own docstring states the
conflation as intent — the subprocess hit the ceiling *or died* — and the motion module
is the identical case one file over. Downstream, the tool mapping's comment reads
"the ceiling kill is a structured refusal" about both cases, and the check engine
records it as unverifiable with a docstring saying "not a pass, and **not a crash**" —
exactly backwards when the child crashed. **Partially confirmed** because the tool
documentation explicitly blesses it: it says a comparison that cannot finish, or whose
subprocess dies, refuses with the timeout reason. So the code is compliant — and the
*governing* comparison clause names only the ceiling kill and never mentions a crash,
so the tool documentation widened a reason without the owning document saying so, and
the clause about a timed-out predicate being neither a pass nor a crash is false for
the crash case. Adding an exit code to the existing refusal leaves the reason name —
the only field four consumers key on — still saying timeout, and leaves the ceiling
asserting a bound that was never reached; fixing compare alone leaves the byte-for-byte
identical conflation in motion and the third in the placement verifier, three
vocabularies drifting apart one fix at a time.

**Fix.** Split the reason and share the carriage: introduce a common base holding the
partial facts and the lost measurements, with the timeout keeping the ceiling and a new
child-died refusal carrying the exit code and emitting **no** ceiling. Every existing
catch becomes a catch of the base, so no site can be missed — the base is what makes
this safe. Do the same for motion in the same change, or the two specification
vocabularies drift again. The tool mapping catches the base, maps the reason from the
exception and carries the exit code; the check engine catches the base and keeps the
entry unverifiable — never a pass, which is right — with the reason now
distinguishing, so a predicate whose child keeps crashing is diagnosable instead of
looking slow; fix its "not a crash" docstring. The CLI formatter handles both and must
stop printing a ceiling for the crash case. Add the new reasons to the bench's
refundable harness-fault vocabulary, or a crash is charged where a timeout is refunded.
Amend the comparison clause to state the two-reason vocabulary and that both carry the
partial facts, and remove the parenthetical from the tool documentation, giving the
crash its own sentence with a remedy that is not "raise the ceiling".

**Tests.** The existing dying-child test retargeted: the new type, the exit code, **no**
ceiling key, and the partial facts still present; the silent-child case likewise; the
genuine ceiling keeps its reason *with* the ceiling — the assertion that proves a split
rather than a rename; a predicate whose child dies records the new reason and does not
pass; the same pair for motion; and a bench test that the new reasons are refundable.

### J-build-state-3 — a crashed verification child is refused as a solver timeout

**severity** medium · **surface** server-core · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-build-state-5 · **root cause** RC-8

**Symptom.** Any outcome of the placement verification pass other than a terminal
message — the ceiling, a kernel crash, a child that dies at spawn, an out-of-memory
kill — lands on one solver-timeout refusal. The author knew: the message reads "did not
finish within N seconds … **or** its process died (exit code M)", packing both facts
into one sentence because the code has no death flag to discriminate with. Machine
consumers see only the reason, so a crash is indistinguishable from a ceiling and the
model is steered toward raising a timeout that never fired. The same raise passes no
payload, so the refusal carries nothing at all.

**Reproduction.** `core/src/hephaestus/core/placement.py:1889-1907` polls, breaks when
the child is no longer alive, and never sets a death flag — unlike its three siblings,
all of which do — and the raise at
`core/src/hephaestus/core/placement.py:1910-1918` is unconditional with no payload. The
serialisation then merges an empty payload, so no best iterate and no verified
residuals appear; the solve-side timeout, by contrast, has a test asserting its best
iterate, while the two tests for this path assert only the reason.

**Root cause.** RC-8. This is the fourth and most degraded copy of the loop: the three
siblings rewrite the message from a ceiling phrasing to a death phrasing, and this one
concatenates both into a static string. Its docstring names its source and says it took
the compare/motion loop with one terminal message instead of a stream — it knew where
it came from and dropped the part it thought was about streaming. The refusal vocabulary
it must choose from has seven members and none means "the verification process died",
so even a discriminating loop would have had nothing to name: the vocabulary gap is
upstream of the loop gap. The empty payload is a third, independent miss at the same
raise. SOLVER.md closes the run-time refusal list at those seven and separately mandates
that the pass run in a killable separate process — so the specification mandates the
mechanism whose failure mode it declines to name — and its clause promising that the
timeout carries the best iterate and its verified residuals is false on this path.
Rewording the message changes nothing for any machine reader; adding a death flag with
no vocabulary member leaves the code with a distinction it cannot express.

**Fix.** Widen the closed vocabulary by one — a verification-process-died reason —
adopt the shared bounded-pass helper so the death flag and exit code exist, raise the
new reason with the exit code for the death case and keep the timeout for the ceiling,
and thread the caller's best iterate into the verifier so **both** branches carry the
payload the clause promises, as the solve-side path already does. Add the member to the
run-time family mapping so the tool error maps it rather than falling through. It must
**not** be added to the verdict sets: the existing whole-tuple assertion that no refusal
name is a verdict spelling then guards the new member for free, which is the dangerous
mistake — a kill readable as an outcome — caught by an existing test. Add the member to
the specification's closed list with its rationale, state in the process sections that a
pass's death is reported distinctly from its ceiling and carries the exit code, and
either keep the best-iterate promise (this fix's option) or exempt the verification
refusals explicitly; leaving it is a false clause. The member must be added to the tool
schemas and the CLI documentation in the same change or they drift.

**Tests.** A child that exits with a known status yields the new reason with that exit
code, and the reason is not in the verdict set; the existing assertion that the
verification subprocess is dead after its ceiling still yields the *timeout* reason,
which is what proves the two are discriminated rather than renamed; the ceiling refusal
now carries the best iterate, mirroring the solve-side test and failing today; and the
solver's import-closure clause still holds after the verifier imports the shared helper.

### J-build-state-2 — a failed terminal write during process loss is swallowed twice

**severity** medium · **surface** sidecar · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** When the sidecar dies, the runtime synthesises one interrupted terminal
per tracked run. Each synthesis is wrapped in a bare catch-and-continue, and the whole
hook is wrapped again in a suppress-everything one layer up. A store-level failure —
a busy database, a full disk, a corrupted state file — therefore leaves the run with no
terminal and its admission slot occupied, and produces no log line, no event and no
archived row: there is no logging configured anywhere in the engine or the server, so
there is no fallback channel either. The run keeps appearing live indefinitely, which
is exactly what the digest says must never happen.

**Reproduction.** Static, and the call graph is unambiguous: the supervisor records a
restart and fires a recovery event whose helper wraps the hook in a blanket
suppression; the hook's loop body ends in a bare catch-and-continue; and the terminal
insertion it calls opens a transaction that can raise a not-found, a terminal conflict
or any database error. A grep for a logger across the engine and server source returns
nothing, so none of those paths is recorded anywhere.

**Root cause.** Two suppressions doing two different jobs written the same way. The
supervisor's blanket suppression is correct in intent — its comment says a recovery-hook
fault must not wedge the restart path — and records nothing, so it converts a store
fault into silence. The hook's inner catch is doing per-run isolation, so one bad run
does not cost the others their terminals, and catches the store failure with the same
net. Between them, the only observable difference between "the terminal was written"
and "the write failed" is a row nobody reads until the next startup reconstruction —
which does repair a diverged admission row, but only on a restart, and cannot repair a
terminal that was never inserted. The swallow is original (7b9c89b) and has never been
revisited; the observability channel it should use was added *later*, by the commit that
gave the supervisor a restart-event list and a bounded stderr tail archived per run, and
the terminal-synthesis path was never wired into it. The architecture's terminal
precedence ends with "at most one semantically distinct terminal", which writing zero
satisfies — the loophole — while the digest's stronger promise never to leave an unowned
job appearing live is violated. Narrowing the inner catch alone leaves the outer
suppression catching the re-raise one frame up: same silence, one layer removed. A log
line would go nowhere.

**Fix.** Separate the two suppressions by what they are for, and give the unexpected
case the archived-evidence channel that already exists and already ships per run. Add a
recovery-fault recorder beside the restart recorder, appending to the same list with the
same shape plus a run id, with its detail passed through the registered redactor, since
a database error message can carry a path. The supervisor's fire-and-suppress keeps its
guarantee and records instead of suppressing. The hook names its two *expected*
exceptions — a run never admitted here, and another writer winning the race the
existing guard is already testing for — and records anything else before continuing;
the continue is retained deliberately, so one failing run does not cost the others
their terminals. Give the acknowledgement call the same treatment, since a successful
insert followed by a failed acknowledgement is a distinct state that only the next
startup repairs. Add one sentence to the restart flow: a terminal synthesis or
acknowledgement that fails is recorded as archived evidence and repaired on the next
start, never dropped; and tighten the architecture's "at most one terminal" so a
failure to write one is itself recorded. No API or wire change.

**Tests.** A recovery hook that raises: the restart path still completes *and* a fault
row lands in the restart events; a store double whose terminal insertion fails for one
of two tracked runs asserts that the **other** run still gets its terminal — the
assertion that pins the continue and would catch anyone "fixing" it into a re-raise —
that a fault row names the failing run, and that the failing run has **no** terminal,
so the fix records the leak rather than pretending to have written one; and a
token-shaped fault detail is redacted.

### J-http-envelope-2 — a missed path under the bundle returns 500 with an ASGI traceback

**severity** medium · **surface** server-core · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** —

**Symptom.** Every page load logs a traceback and answers 500. The browser requests a
favicon unconditionally, the built bundle contains none, and the static handler's 404
escapes as an unhandled exception. Every other path miss under the bundle behaves the
same way.

**Reproduction.** Against a real serve with the real bundle, the favicon and a deep
route both return 500 with a plain-text content type, and the log carries a traceback
ending in the static handler raising a 404; in-process the test client raises the same
exception. The API path correctly 404s, because that half reaches an application.

**Root cause.** `server/src/hephaestus/http/serve.py:230-266` returns a bare ASGI
callable that dispatches to either the API application or a static-files instance. The
static handler raises an HTTP exception for a missing file, and in a Starlette
*application* that is caught by the exception middleware — here there is no application
and no middleware between the raise and the server, so it is reported as an unhandled
ASGI exception. The API half is unaffected only because it is itself an application
carrying its own stack. The wrapper's docstring explains, correctly, why the bundle is
composed *around* the app rather than mounted inside it — so the closed-route-table
assertion stays strong — and composing around the app also composed around its exception
handling. Shipping a favicon would silence the observed symptom and leave every other
miss — a stale asset URL after a rebuild, a mistyped path, a probe — answering 500 with
a traceback. Same class as the missing envelope handlers: a boundary emitting responses
with no exception handler.

**Fix.** Give the static branch the exception handling every other response path has,
by wrapping the static instance in exception middleware or making it a one-route
application used only as the non-API target — either turns the raise into a real 404 —
and keep the dispatch shape, noting in the comment that both branches are now
exception-carrying applications, which is the property the raw callable lacked. Decide
and record the miss policy explicitly: the client keeps all navigation state in the URL
fragment and never pushes a new path, so there is no client-side route to fall back to
and a path miss is a genuine 404, **not** a single-page fallback — say so in the
docstring, because a future reader will otherwise add the fallback. Add the icon link
to the document so the browser stops requesting the file at all; that is the cosmetic
half and is worth doing alongside, not instead. One line in §3: a path the bundle does
not contain answers 404, and the bundle is not a single-page fallback, because the
client keeps its navigation state in the fragment.

**Tests.** Over a bundle directory containing only the document, two missing paths
return 404 and nothing is raised with server exceptions enabled; the root and the
document still return the bundle's HTML, guarding against an over-broad wrap; and an
end-to-end assertion that the browser console records no failing favicon request.

### J-http-limits-8 — the CAD-build timeout class is dead, on the wrong side of the bridge

**severity** high · **surface** server-core · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-http-limits-11 · **root cause** RC-9

**Symptom.** The 300-second CAD-build budget three documents state as fact is
unreachable. The supervisor's configuration carries the value and nothing selects it, so
a build lasting between two and five minutes is still running happily in the sandbox
while the layer above has already given up at 120 seconds.

**Reproduction.** A grep for the configuration field returns exactly three hits: its
own definition, the dead-limit registry entry, and the test that pins it as dead. The
call always uses the default timeout unless a caller passes one, and no caller passes
the CAD class. Meanwhile the executor genuinely budgets 300 seconds — from a **second**,
duplicated literal that does not read the shared limits document.

**Root cause.** RC-9. The class was placed on the wrong side of the bridge: the
supervisor's call is the Python-to-sidecar direction, and a build never travels that
way. Builds travel sidecar-to-Python — the model calls the tool, the proxy issues a
dispatch request, and the deadline that decides is the sidecar's RPC peer default,
hardcoded at 120 seconds (J-http-limits-11). So the field could never have had a call
site: it is a correctly named field on the wrong object. Underneath, the executor's own
wall clock is a separate literal, so the two numbers that must agree are related only by
coincidence and by prose. The field and its dead-ness are original (7b9c89b), and the
module docstring asserts the behaviour as fact; the dead-limit registry that records the
gap arrived in the *next* stage, which noticed and documented rather than wired.
Selecting the field inside the call would satisfy the grep and change nothing
observable, and the test pinning it would go green over a still-broken system; raising
the default to 300 would break the tool-timeout guarantee for every other tool.

**Fix.** Enforce the class where builds actually run — the sidecar's RPC layer, which is
J-http-limits-11 — then delete the wrong-direction field and its constant, amend the
supervisor's docstring to say the default is the tool timeout and the CAD class is
enforced by the sidecar's peer in the tool-call direction, naming the file, and make the
executor's wall clock a read of the same shared key so the executor budget and the
bridge budget are one number (the engine already stages the shared document into its
package data). Move the key out of the dead-limit registry into the TypeScript-owned set
and update the closed-set assertion. Correct the three documents to say *where* the 300
lives. **Behaviour change:** a build that fails at 120 seconds today will run to 300,
which is the intent but lengthens worst-case turn latency and interacts with the
delegation deadline arithmetic — and the sidecar's own prompt budgets must not be
shorter, or a long build simply dies one layer up.

**Tests.** The dead-limit meta-test with the key moved, plus an assertion that the
executor's wall clock equals the shared limit, which pins the two numbers together; the
sidecar-side selection test from J-http-limits-11; and an integration test with a
deliberately slow build asserting the result comes back rather than an RPC timeout —
driven through the limits-file override with a tiny tool timeout and a small CAD
timeout, so it is affordable in CI.

### J-http-limits-11 — the sidecar hardcodes a 120-second deadline for every call

**severity** high · **surface** sidecar · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** — · **root cause** RC-3, RC-9

**Symptom.** `agent/src/rpc.ts:115` defaults every outbound deadline to a literal
120 000 ms while the Python half reads the same number from the shared document. The
limits module *types* both timeout keys and exports neither. The one production peer is
constructed with no options, so that literal is the effective deadline for every tool
call — and the seam does not exist: the request type has no timeout parameter and the
proxy's request builder returns a two-element tuple, so the tool proxy structurally
cannot ask for a different deadline. This is why the CAD class is dead, and it also caps
delegation: a synchronous delegation with a ten-minute deadline blocks the Python side
well past two minutes and the sidecar's RPC layer rejects it long before the child's own
deadline, contradicting the documented bridge deadline of the child's deadline plus a
grace.

**Reproduction.** The peer's default is a literal; the limits module exports eleven
other constants and neither timeout; the entry module constructs the peer with no
options; and the only non-default construction anywhere is a test. The single per-call
override in production is a zero for the ask-user request — no timer, correct for a
human question, and proof the third argument works and is simply never used for the
other classes.

**Root cause.** RC-3 and RC-9, joined. Three linked omissions: the limits module types
the timeout block and exports no constant, so the peer has nothing to import and reaches
for a literal; the peer's per-call argument exists but the request type erases it, so the
layer that *knows* which tool is running cannot pass it; and there is no machine-readable
notion of a tool's timeout class, so any per-tool selection would be a hand-written list
— which is this repository's recurring failure mode. The literal is original (7b9c89b),
the same commit that put the dead field on the supervisor: both halves of the CAD class
were written in one sitting and neither was connected. The shared document's own preamble
says no limit literal may be duplicated in code on either side, which this violates
directly. Replacing the literal with the shared value removes the duplication and changes
nothing observable, leaving the CAD class and the delegation deadline still unreachable —
the visible bug would survive the fix that appears to address it.

**Fix.** Export the three deadlines from the shared document; make the peer's default the
tool timeout; widen the request type so a caller may pass a timeout and the request
builder returns it; and make the choice **data rather than a hand-written list** by adding
a timeout class to the tool declaration, defaulting to the ordinary class and set to the
CAD class on the tools that run the sandboxed worker — one declaration, flowing through
the existing generator into the sidecar's schema module and the committed schemas, so no
list is written twice. The proxy then selects the CAD deadline for a CAD-class tool, the
child's deadline plus the grace for a synchronous delegation, and the peer default
otherwise; the explicit zero for the human question stays and gains a comment naming it
the third class. Correct the two documents to say where the class is selected from, and
document the new declaration field. **Behaviour change:** CAD tools get 300 seconds and
synchronous delegations get their deadline plus the grace — both the documented intent,
both lengthening the window a wedged tool holds an admission slot.

**Tests.** The peer's default equals the shared value — a parity assertion, not a
literal; a CAD-class tool is issued with the CAD deadline and a non-CAD tool with the
ordinary one; a synchronous delegation is issued with its deadline plus the grace and a
follow-up delegation with the default, asserted on the captured third argument; a
Python-to-TypeScript parity test that the CAD-class tool sets agree; and the three
exported constants equal the document. Note the sidecar's tests are outside its
type-check today (J-mirrors-and-dx-28), so a signature change will not be caught there
until that lands — run the unit suite.

### J-http-limits-9 — the binary payload cap is exported on both sides and validated by nothing

**severity** low · **surface** server-core · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** — · **root cause** RC-9

**Symptom.** A grep for the constant over the whole tree returns exactly three hits:
the Python export, the TypeScript export, and the test that pins it as dead. No producer
or consumer of a binary payload checks it.

**Reproduction.** Those three hits, and no others. The per-image and per-result image
caps *are* enforced; the binary cap is not.

**Root cause.** RC-9. The limit has no defined subject. The bridge's only binary payloads
are the base64 image blocks in tool results, already bounded per image and per result —
and eight megabytes times four is exactly the binary cap, which strongly suggests the
intended meaning is the *aggregate* per-result budget. Nothing sums them, so a result with
four maximal images is bounded only by the per-image check passing four times, and any
future non-image binary payload has no bound at all. Declared and exported in 7b9c89b,
recorded as dead by the commit that created the exception registry, and never wired in
the months since. The architecture enumerates the image budget precisely and never
separately names a binary-bytes budget, so the specification arguably does not require
this limit and the limits document is the thing that is wrong; if the aggregate reading
is right, the code is wrong and the architecture should name the aggregate. Adding a check
without deciding the subject would *invent* a bound, which is the thing this codebase's
own discipline forbids.

**Fix.** Decide the subject, then either enforce or delete — do not leave a third state.
Recommended: adopt the aggregate reading, which is arithmetically implied, and enforce it
where binary payloads are assembled, on **both** sides, since the repository's rule is
that no limit is enforced on one side only: the sidecar's image loop accumulates decoded
lengths and refuses past the cap with its existing error class, and Python gains the
symmetric enforcer beside its byte-length one. Move the key from the dead registry into
the covered set with a boundary test and update the closed-set assertion. Add the
aggregate to the architecture's image-budget sentence. If the decision goes the other
way, delete the key, both exports, the TypeScript interface field and the registry entry —
and say in the commit why the limit had no subject. No behavioural change for any result
the tree produces, since four maximal images is already the ceiling by construction.

**Tests.** A boundary test at exactly the cap and one byte over, mirroring the existing
image-budget tests; and a result whose four images sum just over the aggregate is refused
while just under is accepted.

### J-http-limits-10 — the queued-prompts limit describes a queue that does not exist

**severity** low · **surface** server-core · **verdict** confirmed · **effort** S ·
**risk** very low · **depends on** — · **root cause** RC-9

**Symptom.** A per-session queued-prompt bound is declared in the shared document and
typed in the sidecar's limits interface, and neither side exports it; no queue structure,
no queue depth and no producer of a queue-full refusal exists outside the delegation
service's own unrelated vocabulary. The architecture states it as one of the system's
bounds.

**Reproduction.** Four references to the key: the document, the TypeScript type, the
dead-limit registry entry and its closed-set assertion. The store's configuration has run
slots only, and admission computes free capacity as slots minus active minus pending,
refusing the next run immediately.

**Root cause.** RC-9. The key was written from an early design in which prompts queued
behind a busy session; the design that shipped serialises per session with a *refusal*
instead — a second live turn on one session is refused by name — and refuses past the
slot count outright. Those two mechanisms together make a prompt queue redundant and, more
than that, contradictory: a queued prompt on a session that already has a live turn is
exactly the state the in-flight refusal exists to prevent. The specification is wrong and
the code is right: the architecture sentence describes a mechanism superseded by two
tightenings the interface document records at length and which are tested. Implementing a
queue to satisfy the limit would contradict that record and reintroduce the interleaved-
turns-on-one-transcript condition the lease design exists to prevent.

**Fix.** Delete the key from the shared document, narrow the sidecar's interface field,
remove the registry entry and update the closed-set assertion — no production code reads
it. Correct the architecture's bounds sentence to describe what shipped: the pending-request
and run-slot bounds and the buffered-event bound, with a second live turn on one session
refused by name and a run past the slot count refused as busy, and no prompt queue —
cross-referencing the interface clauses so the two documents agree in one direction. Confirm
with the design owner that no queue is planned; the interface record reads as settled.

**Tests.** The dead-limit meta-test with the key gone from both the declared set and the
registry, which fails loudly if it is ever re-added without an enforcement site — the
gate's whole purpose. Plus a documentation check that the architecture's bound enumeration
names only keys present in the shared document, which is the missing gate that let the
prose and the file drift and would also have caught J-http-limits-8.

### J-mirrors-and-dx-31 — module-level RPC registration in the sidecar entry point

**severity** low · **surface** server-core · **verdict** partially confirmed ·
**effort** M · **risk** medium · **depends on** —

**Symptom.** Five engine modules exceed 2700 lines and the sidecar's entry module is
959 lines with seventeen handlers registered as module-level side effects. Four of the
five Python modules are size without a demonstrated cost; the entry module's shape has a
demonstrated, measurable one.

**Reproduction.** The line counts are as reported, with a clear gap below the fifth. The
entry module constructs a peer bound to standard output, registers seventeen handlers at
module scope, attaches input handlers and logs its own process id — so importing it
starts a process.

**Root cause.** **Assessment, not a rewrite proposal.** The largest file is a
*declaration table* — the single source the tool schemas are generated from — where length
is a feature and splitting would multiply the drift surface; the other four are large
domain modules whose size the audit reports with no evidence of a concrete cost, and none
was found. The entry module is different, and its cost is measured: because importing it
starts a process, the one test that covers its per-run context scoping must compile the
whole source tree and spawn a child (J-mirrors-and-dx-20) — the only test in the sidecar
suite that does either. It conflates three roles — dependency construction, handler
registration and process wiring — so there is no seam at which a test can attach, and
every consequence follows from that. Its shape is original and grew by accretion; the
commit that had to add the child-process test is the first time the shape cost something
concrete. No specification sets a module-size limit, so nothing is "wrong" against a
clause: the recommendation rests on the testing cost, not on a line count.

**Fix.** For the Python modules: **no action recommended**, recorded so the next audit
does not re-raise it — length alone is not the finding, and the declaration table's length
is load-bearing. If a cost appears later, it should be raised with that evidence. For the
sidecar: extract a dependency builder and a `registerHandlers(peer, deps)` from the entry
module, wrapping the seventeen registrations verbatim, and move the peer construction, the
input wiring and the startup log into a `main()` invoked only when the module is the
process entry point — no handler bodies change, so the diff is indentation plus three
function boundaries. Add one line to the design document's module map: the entry module
exports its registration and performs no work at import, and the process wiring lives in
its main — the sentence that stops the next handler being appended at module scope. The
packaged sidecar must behave identically, and the packaging test plus the bridge suites
drive the real spawned sidecar end to end and are the guard; the entry-point guard must
work under **both** build outputs, since the bundler rewrites module identity.

**Tests.** The packaging and bridge suites unchanged, as the primary guard; plus a new
in-process test registering handlers against an in-memory peer — the coverage the current
shape makes impossible.

### Cross-language mirrors

Twelve closed vocabularies are transcribed by hand rather than read (RC-3).
J-mirrors-and-dx-1 states the shared mechanism and the fix; the ten items after it
are its members and are recorded with what makes each one specific. Four of them are
web-facing (J-mirrors-and-dx-6, -7, -9, -10) and are described here rather than in
[Web UI](#web-ui), because they are one change.

### J-mirrors-and-dx-1 — the event vocabulary is hand-written in four files

**severity** high · **surface** server-core · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** — · **root cause** RC-3

**Symptom.** The ten-member event vocabulary is transcribed independently in four
files across two languages. Nothing compares them, so a fifth kind added to one is
invisible to the other three until a runtime surface silently drops it.

**Reproduction.** Four identical ten-element lists — the bridge's, the sidecar's, the
web client's and the test-assertion helper's — each with a prose comment claiming to
mirror one of the others. No test reads more than one of them; the sidecar's own test
iterates its list against a predicate in the same file.

**Root cause.** RC-3. The repository has a working single-source mechanism for two of
the three kinds of cross-language contract and none for the third. Numbers live in
`schemas/bridge_limits.json`, read at import by `core/src/hephaestus/core/limits.py`,
`server/src/hephaestus/agent_bridge/limits.py` and `agent/src/limits.ts`, and staged
into wheels by `core/hatch_build.py` and `contract/hatch_build.py`. Tool schemas are
generated by `contract/src/hephaestus/contract/toolgen.py` into the committed schema
directory, the sidecar's generated module and the MCP declarations, and drift-tested by
`contract/tests` and the stage-2 gate. Closed *string* vocabularies got neither: they
were written by hand into whichever file needed them next, with the coupling carried by
a comment. The first hand-written mirror and the generator-plus-drift-test pattern
shipped in the **same commit** (7b9c89b), which is the whole finding: the mechanism
existed on day one and was scoped to the tool surface only. `CONTRIBUTING.md` claims CI
diffs the Python declaration, the committed schema, the generated definitions, the MCP
declarations and the documentation against each other — and names *event* schemas
explicitly, while CI diffs none of them. So the claim is the design and the delivery
stopped at tools. One test asserting today's four lists are equal fixes four lists and
leaves nine more vocabularies unguarded, and does nothing about the next one, because
a developer adding a closed vocabulary has no place to put it and no test that notices.

**Fix.** One mechanism, on the repository's own two precedents, in three parts.
**Canonical documents** beside the shared limits file: an events document (kinds,
droppable set, resync code and reason, identity separators, jobstore key shape), a
protocol document (version, error codes, the four method and notification sets), a
limit-errors document (codes and message templates), a vocabularies document (the
fourteen workspace sets), and a profiles document (the per-profile budgets).
**Readers and generators**: Python reads the JSON directly at import, exactly as the
limits module does, with no generated Python — and the two build hooks widen from
staging one file to staging the directory, so packaging keeps working. TypeScript is
*generated* rather than read, because a browser has no filesystem and both sides need
string-literal union types a runtime read cannot produce: a generator beside the tool
generator, with the same byte-determinism contract, emits one module per side and is
wired into the existing regeneration command so one invocation refreshes every
artifact. **The census test**, modelled on the tool generator's drift test: the
generated modules are byte-fresh; every declared vocabulary matches its document
through an explicit table; and — the self-defending half — an AST walk over the
governed modules fails on any module-level collection of string literals whose name is
not in the census. That last clause is what stops the twelfth vocabulary in two years'
time. Mirror it on the client side with tests that read the documents from disk, the
pattern the export suite already proves. Amend the contributing claim to name the
documents and the census so its "event schemas" half becomes true, add the documents to
the design document's inventory, and add the rule to `repo_conventions.md`: a closed
vocabulary that exists in more than one language lives in the schema directory and is
read or generated, never transcribed. No wire change — every document is seeded from
today's values — and the one real risk is the packaging change, which the staged-data
invariant test must be extended to cover.

**Tests.** The three census clauses; the client-side and sidecar-side equality suites;
and the vocabulary drift clauses added to the stage-2 gate, so the census runs in a job
that actually exists (J-mirrors-and-dx-30).

### J-mirrors-and-dx-2 — the JSON-RPC envelope, methods and error codes duplicated whole

**severity** high · **surface** server-core · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** Eleven error codes, eight sidecar request methods, nine Python request
methods, two sidecar notifications and three Python notifications are written twice,
each file's docstring pointing at the other as the mirror. A method added to one side
is a method-not-found at runtime, caught by no test.

**Reproduction.** Reading `server/src/hephaestus/agent_bridge/protocol.py:42-108`
beside `agent/src/rpc.ts:13-73`: the same eleven name-to-number pairs, the same sixteen
method strings — including the same eight credential methods, each carrying a
near-identical multi-line rationale in both languages — and the same notification sets.

**Root cause.** RC-3. The frame shape was fixed by the design document as prose and
both implementations were transcribed from that prose. The numeric half of the same
envelope *is* single-sourced: both files import the frame version from their respective
limits modules, which read the shared document — so the file demonstrates the correct
pattern for its one numeric member and the wrong one for its sixteen string members.
Both halves were authored together in 7b9c89b, and the eight credential methods were
later appended to both by hand. Asserting today's four sets match freezes the current
methods and does nothing about the next amendment, which is exactly how the credential
methods got hand-appended twice; it also leaves the error-code table, the part most
likely to drift silently, because a wrong number produces a plausible-looking error
rather than a crash.

**Fix.** Fold into the shared mechanism: a protocol document carries the version, the
error codes and the four sets; the Python module reads it, keeping its attribute
spellings so no call site changes; the sidecar re-exports from the generated module,
keeping its exported names so its own consumers are untouched. The frame version keeps
its existing route through the limits document — the two documents stay separate
because one is numeric caps and one is protocol identity. Replace the design document's
prose method list with a pointer to the document and a statement that both
implementations are derived from it.

**Tests.** The census assertion that the two sides agree, including the error-code
integers, plus the sidecar-side equality suite.

### J-mirrors-and-dx-3 — ten limit error-code strings written twice

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** The bounded-validator refusal codes are raised as bare literals in both
`server/src/hephaestus/agent_bridge/limits.py` and `agent/src/limits.ts`, with their
message templates transcribed to match. The two validators are supposed to refuse
identically on either side of the bridge and nothing checks that they name the same
refusal.

**Reproduction.** Twelve raise sites on the Python side and seven on the TypeScript
side use the same code strings inline, with matching message text. The *numbers* in
those messages are single-sourced — the shared document's preamble says no limit
literal may be duplicated on either side — and the codes the numbers are reported under
are not.

**Root cause.** RC-3, with a scope mismatch: the shared document was scoped by its own
preamble to *numeric* limits, so the refusal vocabulary that reports those limits fell
outside it and was written twice, at the raise sites, in both languages. Both validators
were written in one sitting (7b9c89b). The specification is too narrow rather than
wrong — it constrains numbers and not the codes that report them — and the code follows
the narrow specification faithfully. Asserting the ten strings match leaves the message
templates, which carry the operator-visible numbers, unpaired.

**Fix.** A limit-errors document carrying the codes *and* their message templates, so
the two sides cannot report one refusal with different text; Python reads it and raises
through it with no inline literals; TypeScript generates a code union and narrows its
error type against it, so an unknown code stops compiling. Extend the shared document's
preamble to name the companion document, so a reader of either finds the other. Codes
and message text are byte-identical to today.

**Tests.** A census assertion that both raise-site inventories cover exactly the
document's codes — an AST walk on the Python side and a source scan on the TypeScript
side, matching the existing source-inspection precedent — and the existing refusal
assertions parametrised over the document's list.

### J-mirrors-and-dx-4 — the sidecar's coalescer is dead and already divergent

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-1

**Symptom.** The TypeScript coalescing buffer is referenced only by its own unit test,
and it already computes overflow, drain order and slot reuse differently from the Python
queue it claims to mirror. A future author who wires it up gets three behaviour changes
for free.

**Reproduction.** Every reference outside `agent/src/events.ts` is in its own test —
no production call site. Three divergences: **bound occupancy**, where the TypeScript
push reports overflow against a list holding progress *and* durable events while the
Python queue counts durable events only, with progress in a separate map that never
counts, so a progress flood overflows one buffer and not the other; **drain order**,
where Python sorts by sequence and TypeScript returns insertion order; and **slot
reuse**, where Python moves a coalesced key to the end to preserve arrival order and
TypeScript overwrites in place.

**Root cause.** Stage 2A wrote a sidecar-side coalescer in anticipation of the sidecar
buffering its own events; the design settled on the Python side owning per-client
queues, and the class was left in place with a unit test that pins *its own* behaviour
rather than the contract — so the divergences are not merely unnoticed, they are pinned
by a green test. The specification defines one observer buffer, its bound and its drop
policy and assigns it to the server-side observer, so the code is wrong: §2.7 describes
one buffer and the repository ships two with different arithmetic. Deleting the class
alone would be right and incomplete: the same file holds the live event vocabulary the
sidecar needs, and its coalescing key's separator is itself a cross-language contract
with the Python side.

**Fix.** Delete the outcome type and the coalescer class from the sidecar module and the
corresponding block from its test; keep the event kind, the droppable predicate, the
coalescing key and the event type, re-sourced from the generated module, and keep the
key's unit test, since that key *is* a live cross-language contract. Add a docstring
line to the surviving Python queue stating it is the only coalescer, replacing the
symmetry the sidecar module implied. Carry the coalescing separator in the events
document so the one surviving coupling is documented rather than commented. If a future
stage genuinely needs sidecar-side coalescing, it re-lands against a shared conformance
vector file rather than a hand-written twin. Zero runtime impact: nothing imports the
deleted symbols.

**Tests.** The retained key test, now asserted against the document; and the existing
progress-flood clause on the Python side as the surviving overflow contract, with an
assertion naming the queue as its only implementation.

### J-mirrors-and-dx-5 — the jobstore key padding is a named constant on one side and a format spec on the other

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** Both sides write into the same key namespace and both zero-pad the event
id so prefix listing sorts. The width is a named constant on one side and a format-spec
digit buried in an interpolation on the other. If they diverge, prefix listing silently
returns events out of order — a durable-store ordering bug with no exception.

**Reproduction.** Four sites: the sidecar's constant and its padding call, the Python
writer's inline interpolation, and the test transcribing the same spec twice more.
Neither production site comments the other.

**Root cause.** RC-3, with a shape difference: the Python writer builds the key inline
at its single call site rather than through a helper, so there is no Python symbol to
pair with the sidecar's exported key function. The sidecar side did the right thing;
the shared format therefore has no shared anchor. Both writers were authored in one
commit (5329250) and the padding typed twice. The design document describes the
namespace as a cross-language contract and neither it nor any schema states the width —
so the specification omits a load-bearing constant and the code duplicates it. Bumping
both to a shared constant fixes the width and leaves the *format* built by two
independent expressions, so a change to the separator reproduces the identical bug.

**Fix.** Carry the digit count and the separator in the events document, together with
a small vector list; extract a Python key helper beside the writer reading the document
and mirroring the sidecar's function exactly, and call it from the writer and from the
test instead of retyping the spec; source the sidecar's constant from the generated
module. State in the design document that the key format is the document's and is
implemented once per language against shared vectors. Key bytes are unchanged, so
existing stores keep listing correctly.

**Tests.** The same committed vectors driven through both implementations.

### J-mirrors-and-dx-6 — fourteen closed workspace vocabularies duplicated Python-to-web

**severity** high · **surface** web · **verdict** confirmed · **effort** L ·
**risk** medium · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** Every closed vocabulary the workspace routes validate against exists as a
hand-written list in Python and a second hand-written list in TypeScript, each pair
carrying a comment asserting the mirror. A value added to one side is a refusal or a
dead control on the other, and no test pairs any of them.

**Reproduction.** Pair for pair: the eleven context-envelope members; the stage tabs;
the seven inspector tabs; the seven attach causes; and the four provider vocabularies —
same members, same order. Several comments explicitly name the twin, so the coupling is
documented and unenforced. The counter-example is real and works: the export suite reads
the committed tool schemas from disk with plain file access and asserts the client's
enums equal the engine's.

**Root cause.** RC-3. The export module states the problem and the workaround in its own
comment — the engine's table is a Python object, a browser cannot reach it, and no route
serves a tool schema, so the lists are *transcribed* from the generated, committed
schemas — and then discharges it with a test. Every other vocabulary hit the identical
wall and took the transcription **without** the discharging test, because there was no
committed document to read: the schema directory held tool schemas and limits and
nothing else. All fourteen pairs, including the compliant one, were authored in one very
large commit (b8b6a48), so the correct pattern and the incorrect one shipped together
and the only difference is that tool enums had a document to read. §22.1 extends the
no-derived-fact rule to enums explicitly — the engine's enum *is* the closed vocabulary
and the client renders it from the engine's table, never from a list of its own — so the
specification is right and the code violates it fourteen times. Fourteen equality tests
would each pin one pair and would not stop the fifteenth vocabulary, which is the actual
failure mode: one of these lists was appended to on both sides by hand, and the comments
say so.

**Fix.** A vocabularies document carrying all fourteen with the section that governs
each; the Python modules read it; the client's generated module is re-exported under
today's names from the four API and state modules, so no component import changes and
the order — which matters, since two of the lists are asserted in specification order —
is preserved. Then extend the client's existing custom lint rule with a companion check
that flags a module-level constant array of string literals outside the generated
module: the client-side half of the census, in the repository's own lint idiom rather
than a new one. Promote the export module's per-file deviation note into the general
rule in `repo_conventions.md` and shorten the comment to a pointer, and delete the two
Python comments that assert a coupling which will then be enforced.

**Tests.** Every closed vocabulary equals the document, in order, on both sides; and the
new lint rule covered by its own test.

### J-mirrors-and-dx-7 — the event identity module hand-ported into the browser client

**severity** medium · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** The two separators that decide which namespace a serialised event id
belongs to, and the three functions over them, exist as an independent transcription in
the browser client. A change to either separator silently reclassifies every id on one
side only.

**Reproduction.** `server/src/hephaestus/http/event_identity.py:53-80` against
`web/src/api/events.ts:92-137`: the same two separator constants and the same three
functions, function for function, including the three-valued fallback and its rationale
restated in both docstrings. The client side additionally carries a genuinely valuable
note about integer precision — knowledge that exists on only one side of a supposedly
mirrored pair.

**Root cause.** RC-3. The identity scheme is transport-level and therefore needed in the
browser, and no route serves a schema document, so the client transcribed it — the same
wall as the workspace vocabularies, the same absent document, the same commit
(bb546fd). Pinning the two separators leaves the surface precedence undefined by test:
an id containing *both* separators resolves the same way on both sides today only
because both were written in the same order, and that precedence is unwritten in either
specification section.

**Fix.** Carry the separators, the surface vocabulary and a vector table — including the
both-separators and neither-separator cases — in the events document; both languages
take the constants from it and both test suites drive the same vectors, which also
*documents* the precedence that is currently accidental. Add one sentence to the history
section fixing that precedence, since the vectors will then pin it. Keep the client's
precision note where it is: it is client-specific truth.

**Tests.** Both suites parametrised over the shared vectors.

### J-mirrors-and-dx-8 — six per-profile budget literals duplicated across the bridge

**severity** medium · **surface** agent-tools · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** The snapshot and reviewer budgets — maximum turns, maximum output tokens,
timeout — are declared as literals on both sides of the bridge. Both sides *enforce*
them, deliberately, and nothing checks that they enforce the same numbers, so a raised
budget on one side is silently clamped by the other.

**Reproduction.** `agent/src/session/profiles.ts:55-67` against
`server/src/hephaestus/agent_bridge/query_snapshot.py:51-56` and
`server/src/hephaestus/agent_bridge/review.py:201-205`: the same three numbers each,
with both sides commenting the double enforcement as intentional. Note the unit
mismatch — milliseconds on one side, seconds on the other — so the literals are not even
textually comparable by grep.

**Root cause.** RC-3, with the reasoning stated and then stranded: the sidecar's comment
says these are session-policy defaults rather than bridge wire limits, so they live there
rather than in the shared limits document. That correctly declines to put session policy
in the *wire-limits* document — and, having no other document, falls back to duplication.
The missing thing is a second document, not a different reading of the first. An equality
test would need a unit conversion baked into it, which is the same transcription risk one
level up.

**Fix.** A profiles document with seconds as the canonical unit, matching the limits
document's convention; Python reads it directly; the sidecar derives its millisecond
constants from the generated module, keeping its exported names, so the conversion
happens once in code a test can drive. Keep the double *enforcement* — it is deliberate
defence in depth — and remove only the double declaration. Point the two governing
sections at the document as the machine-readable form of the budget each states.

**Tests.** Both sides' effective numbers, after unit conversion, equal the document.

### J-mirrors-and-dx-9 — one name for three session-profile sets, citing a symbol that does not exist

**severity** medium · **surface** web · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-mirrors-and-dx-1, J-mirrors-and-dx-6 · **root cause** RC-3

**Symptom.** One name denotes three different closed sets, plus a fourth related set
under a different name, and the client's copy is documented as mirroring a symbol that
is **not in the file it cites** — so a reader following the comment finds nothing and
cannot tell which set is authoritative.

**Reproduction.** The bridge declares a five-member profile enum; the sidecar declares
the same five under the shared name; the client declares three under that name, in a
different order, with a comment citing the HTTP module — where a grep for that name
returns nothing, because that module declares a *two*-member creatable set instead.

**Root cause.** RC-3, over three legitimately different concepts collapsed onto one
name: the bridge's five are *implementable* profiles, the HTTP layer's two are
*operator-creatable* — served as a projection precisely so the composer names the profile
it will use without keeping a client-side copy — and the client's three are the profiles
a client may *address*. The client constant is exactly the client-side copy the HTTP
module's comment says must not exist, and §7A.2 says the profile is never chosen from a
client-side copy. It was written for the read-only Stage 4 client, before the projection
existed; the projection and the creatable set came later and the now-redundant constant
was not removed. Renaming it fixes the collision and leaves the specification violation.

**Fix.** Three named sets, one place each: the enum and its creatable subset in the
vocabularies document, read by the bridge and the HTTP layer and generated for the
sidecar; and on the client, **delete** the constant and its type — the composer already
receives the profiles projection from the listing, which is what §7A.2 requires — taking
any token it needs for routing from the served projection or from the generated module
under an unambiguous name. Delete the false citation comment. **Behaviour change:** the
composer's offered profiles become whatever the server serves, which today is two rather
than the three the client hardcodes, so a control may disappear from the create
affordance — the specification-correct behaviour, since the third profile is created by
a different route that refuses it by name, but it belongs in the change description. See
also J-web-stream-14, which is the read-side half of the same confusion.

**Tests.** The create affordance offers exactly the served profiles; the projection
equals the document's creatable subset; and the bridge enum equals the document's five.

### J-mirrors-and-dx-10 — the web client hardcodes three server constants

**severity** medium · **surface** web · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-1 · **root cause** RC-3

**Symptom.** The buffered-event bound, the resync close code and its reason are retyped
as literals in the browser client, one of them under a comment that asserts a coupling to
a value it copied by hand. This is the same finding as J-web-stream-13, recorded here
because its fix is part of the mirror mechanism.

**Reproduction.** See J-web-stream-13.

**Root cause.** RC-3. The client has no limits loader at all — the two other consumers
read the shared document, and the browser has no filesystem and no route serves it — so
the third consumer transcribed. The document's preamble names two consumers; there are
three.

**Fix.** Generate a client limits module from the shared document alongside the
vocabulary generator, emitting the numeric subset the client legitimately needs; carry the
resync pair in the events document; the window becomes the generated value and its
comment states the derivation rather than asserting it, naming the ring rather than the
queue. Amend the preamble to name all three consumers and the generation route for the
browser one.

**Tests.** The drift assertions in J-web-stream-13.

### J-mirrors-and-dx-11 — same-language duplicates in two module pairs

**severity** low · **surface** server-core · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Two pairs of byte-identical private helpers in the same language, each pair
already carrying divergent docstrings — the classic first stage of a real behavioural
divergence.

**Reproduction.** The argument-cleaning helper in the assembly and motion operation
modules is identical in body, and the two docstrings already diverge: one reasons about a
null tolerance not being a tolerance of zero, the other about a null limit being an absent
field rather than a declared zero-travel range, and the second ends by naming the first as
the authority. In the engine, the anchor decoder in
`core/src/hephaestus/core/assembly.py:366-382` and
`core/src/hephaestus/core/motion.py:429-445` are byte-identical apart from the function
name, both returning the same type the first module owns; the small string helper beside
them is duplicated too and appears unused at the second site.

**Root cause.** The operations package was split into domain modules and each got its own
copy of the shared cleaner rather than a shared module. In the engine, the second module
needed to decode a type the first owns and copied the decoder rather than importing it —
the decoder is private, so importing would have meant promoting it, and copying was
cheaper. Nothing is wrong against a clause, and the conventions state the general
preference for extraction over duplication; the second docstring's "the other module's
rule" is an explicit admission that one copy is authoritative. A careless fix would
discard the two genuinely different domain rationales, which should survive as call-site
comments.

**Fix.** One definition per pair. Move the cleaner into a shared module in the operations
package with a docstring merging both rationales. Promote the anchor decoder beside the
type it constructs, delete the copy, and delete the string helper if it is unused after
that — a static check will say. Optionally add the extraction rule to the quality bars
beside the existing durability sentence.

**Tests.** The existing suites cover both call sites; add a round-trip test for the
promoted decoder over the fields the second module relied on, so it has a test of its own
rather than only indirect coverage.

## Tests and CI

### J-mirrors-and-dx-18 — the first documented test command is red on every developer machine

**severity** high · **surface** tests · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** — · **root cause** RC-10

**Symptom.** The first pytest command `CONTRIBUTING.md` gives a new contributor fails on
any machine whose renderer differs from the pinned image's — which is every machine that
is not the pinned image. CI hides this by excluding exactly those files by path.

**Reproduction.** Running the section-golden gate on a developer machine fails with a
message naming the renderer it was baselined on and the one this machine renders with,
and telling the reader to re-baseline inside the pinned image. Both affected files are
inside the configured test paths, so the documented command collects them, while CI
passes an ignore for one and never lists the other on a stock runner.

**Root cause.** RC-10, from two correct decisions with no bridge between them. Failing
loudly rather than skipping is deliberate and right, and the golden suite says so: a
renderer mismatch is reported by name because a golden is valid only for its image and
renderer pair, and a suite that quietly passed on the wrong rasterizer would be asserting
nothing. CI excludes them from stock runners for the same reason and runs them in the
image. What is missing is a *selector*: nothing marks these tests as image-scoped, so
neither the marker expression nor the documented command can deselect them — the
repository has the tool and used it once, for slow tests. The exclusion dates to the
commit whose own subject says the browser gate was deferred to the pinned image; the
ignore list was the workaround chosen instead of a marker. Changing the failure to a skip
would destroy the property the comment refuses to give up; changing the documentation
alone leaves CI's ignore list as a second, hand-maintained copy of which tests are
image-scoped.

**Fix.** Add a pinned-image marker on the existing slow-marker precedent and mark the two
renderer-pinned modules. The documented command deselects both markers; the stock CI lanes
drop the path ignore in favour of the marker expression; and the golden lane *selects* the
marker, so it cannot silently lose a module the way a path list can. State in
`CONTRIBUTING.md` what is deselected and where it runs, and add the pinned-image lane as
an explicitly optional local step so the excluded coverage is discoverable rather than
invisible. Extend the existing workflow-structure assertions to require that no stock lane
collects a pinned-image test and that the golden lane collects all of them — otherwise the
ignore-list problem simply moves. No test behaviour changes, only selection, and the job
names are unchanged so the release prior-gate list is unaffected. This marker is also where
J-mirrors-and-dx-15's validator lane belongs.

**Tests.** The two structural assertions above, plus the acceptance criterion: the
documented command is green on a developer machine.

### J-mirrors-and-dx-25 — the documented bootstrap leaves no `pnpm` on PATH

**severity** high · **surface** tests · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-mirrors-and-dx-32

**Symptom.** Following the repository's own first documented command produces a checkout
in which every sidecar-backed test skips, because the script's preferred route runs pnpm
through a package runner and the guards test for a `pnpm` on PATH.

**Reproduction.** The bootstrap's check mode reports the pnpm route as a downloaded-on-
demand runner invocation; `which pnpm` finds nothing; and `tests/stage2` alone then reports
**357 passed, 32 skipped**, every skip reading that node or pnpm is unavailable and the
bridge tests need the packaged sidecar. The guard is one predicate at
`server/src/hephaestus/testing/sidecar.py:119`, repeated at about twenty call sites across
six suites.

**Root cause.** Two correct components with incompatible interfaces. `scripts/bootstrap.sh`
resolves pnpm through a documented preference order precisely because a PATH pnpm is
unreliable under corepack — `CONTRIBUTING.md` and `docs/install.md` each spend a paragraph
on why. The testing helper asks the one question the bootstrap deliberately avoids. Neither
is wrong alone; nothing reconciles them, and the reconciliation failure is expressed as a
*skip* rather than an error. Both scripts are new in the working tree, added with the
documentation refresh, so this is a fresh mismatch: the bootstrap is new, the guards are
old, and nothing tested the pair. The documentation presents the script as *the* way to get
a working checkout, so both the specification and the code are wrong — the doc promises a
working checkout and the code's definition of working differs from the script's. Telling
developers to install pnpm globally contradicts the analysis that produced the script.

**Fix.** Three parts. Teach the guards the bootstrap's resolution: one shared helper
implementing the same preference order — an environment override, then a PATH binary, then
the package runner with the pin read from the sidecar's manifest — with every call site
routed through it and the runner invocation returned as a command list rather than a single
path. Have the bootstrap record its resolution so the two agree by construction. And make
the skip loud when it should not have happened: honour a require-sidecar environment
variable that turns such a skip into a failure, set in every CI job that installs node —
the same fail-rather-than-skip policy the renderer gate already applies. Say in
`CONTRIBUTING.md` and `docs/install.md` what the bootstrap does and does not enable and how
to prove the sidecar lanes are running. The runner fallback downloads on first use, which
is already what the bootstrap does, so it introduces no new network behaviour for anyone
following the documentation; CI is unaffected except that a regression which would have
skipped now fails, which is the point — expect at least one surprise.

**Tests.** The helper falls back to the runner with the pin from the manifest; a structural
assertion that every CI job installing node sets the require variable; and the acceptance
criterion — after the documented bootstrap, the stage-2 suite reports zero node or pnpm
skips.

### J-mirrors-and-dx-32 — the bootstrap and launcher scripts are run by no job and no test

**severity** high · **surface** build-system · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** The onboarding path — the very first command a new contributor runs — has no
automated coverage at all, and it is new, unlanded code.

**Reproduction.** No workflow and no test references either script; they are referenced
only from prose, in five documents. The check mode works today and prints a clean
prerequisite table.

**Root cause.** The scripts were written as part of the documentation refresh and CI lanes
were not extended, because CI does its own setup — the Python sync plus a pnpm action — and
therefore never exercises the path a human takes. The two setup paths have no point of
contact, which is exactly the gap that produced J-mirrors-and-dx-25. `README.md` and
`CONTRIBUTING.md` present the script as the entry point and `docs/install.md` says it takes
a fresh clone to a fully built checkout, so the documentation makes a strong claim about a
script nothing verifies — and the contributing document makes the workflow file the required
check, so a claim not in it is not enforced. A lane that runs only the check mode proves the
prerequisite detection and nothing about the six build steps, which is where the
fully-built claim lives; and neither proves what J-mirrors-and-dx-25 found.

**Fix.** Two lanes, both cheap. Add the check mode to the existing documentation job —
seconds, no new setup, catching a broken prerequisite table on every change. Then add a
dedicated job on a bare checkout with **no** Python sync and no pnpm action before it,
installing the tooling the way the documentation tells a human to, running the full script,
and then asserting the criterion that matters: with the require-sidecar variable set, a
sidecar-backed suite passes — which is what would have caught J-mirrors-and-dx-25. Add a
small test for the launcher's clone resolution through a symlink, which is pure path logic.
**Coupling to respect:** adding a job turns the prior-gate assertion red until the release
workflow's list is updated, which the workflow file itself records — do both in one change.
The full lane depends on network package resolution outside the lockfiles, so pin what can
be pinned and give it a generous timeout.

**Tests.** The two lanes are the tests, plus the launcher's symlink resolution and the
prior-gate assertion kept green.

### J-mirrors-and-dx-14 — two deadlock-regression tests hang instead of failing

**severity** high · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** The two tests whose entire subject is a lock leak hang forever when the lock
actually leaks. There is no per-test timeout anywhere in the repository, so the failure mode
of the regression under test is a job timeout with no test name attached.

**Reproduction.** Both tests start a worker, spin on a flag with a short sleep, and then
join with **no** timeout. The flag is set in the worker's cleanup, so if the worker blocks on
the leaked lock the flag is never set, the main thread spins forever, and the join would
block forever too. The lockfile carries no timeout plugin and the pytest configuration sets
no timeout; the only backstop is the job's own wall clock.

**Root cause.** The tests were written as positive regression checks and the negative path —
the regression recurring — was never given a bound; the spin is doubly unbounded, with no
deadline of its own and no join timeout. Several other suites in the same tree use the
deadline idiom, so the repository has the pattern and these two files do not. They were
written *as* the fix for a lock leak, which is why their hang-on-recurrence behaviour matters:
they are the tripwire for the bug they were born from. No clause governs test timeouts, so
the code is wrong in the sense that a regression test which hangs instead of failing is not a
regression test. Adding a timeout plugin alone gives a global guillotine with no message about
*which* lock leaked; adding a join timeout alone leaves the preceding spin unbounded.

**Fix.** Bound both loops locally with the repository's own deadline idiom and fail with a
message naming the leaked lock, then assert the worker is no longer alive after a bounded
join. Add the timeout plugin as well, but as a coarse safety net with a generous global
default and a thread-based method — not as the primary mechanism, because the local bound is
what produces a diagnosable failure, and the thread method does not kill the process, so it
will not interfere with the subprocess-heavy stage suites. Add to the quality bars that a
test which waits on another thread or process bounds the wait and fails by name. Watch one
full CI run before relying on the global default.

**Tests.** The changed tests are themselves the test; confirm the new message appears within
the bound by reverting the durability fix locally.

### J-mirrors-and-dx-22 — the configured test paths exclude four suites

**severity** medium · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-18

**Symptom.** The most natural command a contributor types silently runs a subset:
`pyproject.toml:128` discovers the durability suite and the stage gates only, so the engine,
server, contract and bench suites are never collected. Anyone who does not read past the
first command gets a green run that never touched the engine or the server.

**Reproduction.** The configured paths are two entries; `CONTRIBUTING.md` documents the split
explicitly and compensates with a second command.

**Root cause.** The paths were set when the repository had the durability package and the
stage gates and were never widened as four more packages grew their own suites — the entry
dates to the first scaffolding commit, when those two genuinely were all there was. The
documentation is right about what happens and wrong about what should happen: it documents a
workaround rather than fixing the configuration. Widening the paths *alone* would collect the
renderer-pinned goldens and make the bare command red, so this item and J-mirrors-and-dx-18
must land together.

**Fix.** Widen the paths to the five suite directories and set the default marker expression
to deselect the slow and pinned-image markers, so the bare command is both complete and green;
anyone wanting the excluded lanes overrides the expression. Leave bench out until it has
tests, and say so in a comment, so the omission is documented rather than forgotten — the
standard the workflow file already holds itself to. Collapse the two documented pytest
commands into one, with one sentence naming the deselected markers and where they run, and
say plainly that the single command is much slower, which is the honest cost of its being
true. Add a structural assertion that every directory containing tests is either inside the
configured paths or in an explicit allowlist with a reason.

**Tests.** The discovery census above.

### J-mirrors-and-dx-30 — the contract suite is documented and run by no job

**severity** medium · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-22

**Symptom.** A green, fast suite that pins the tool-surface size and the engine-to-contract
import direction runs only if a developer types the second documented pytest command.

**Reproduction.** No workflow references the directory; running it takes 3.46 s for eleven
passing tests. It is also outside the configured paths, so the bare command misses it too.

**Root cause.** CI lanes are organised by stage gate plus three package lanes, and the
contract package became a package in the refactor that created it with no lane added — the
package-lane pattern was not extended. Much of its generator test is duplicated by the
stage-2 drift suite, which *does* run, so freshness, determinism and declaration-to-schema
drift are covered there; what runs **nowhere** is the surface-size pin, with its long comment
about what adding a tool costs, and both import-direction tests — an architecture boundary
with no enforcement. `CONTRIBUTING.md` and the package's own README list the suite in the
default local checks, and the required checks are the workflow file plus the current stage's
gates, so the documentation is right and CI does not implement it. Adding the directory to an
existing lane fixes this suite and misses the general question — which other test directories
run nowhere.

**Fix.** Add the directory to the fast package lane, or give it a small lane of its own for
clarity, and include it in the widened test paths. Then add the census: a structural assertion
that every directory containing tests is named by a CI job or listed in an explicit allowlist
with a reason. The documentation needs no change; CI catches up to it.

**Tests.** The census assertion.

### J-mirrors-and-dx-27 — ruff excludes `bench` with no stated reason

**severity** medium · **surface** build-system · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** One entry sits in the lint exclusion list beside five that each carry a
documented justification, and it has none. Behind it is real, small debt.

**Reproduction.** The exclusion list has eight entries; the comment above it justifies the
frozen-evidence and part-script ones in detail and says nothing about this one. With the
exclusion lifted, the linter reports five errors, three of them auto-fixable — including an
unsorted export list — and four files that would be reformatted. Meanwhile the package's
source *is* inside the type-checker's configured include and is clean, so it is type-checked
and not linted.

**Root cause.** The entry was added in the same refactor that added the package's source to
the type-checker's include — one tool's coverage widened, the other's narrowed, in one commit
— and the comment block above the list was not extended, so the entry has no justification
and reads as an oversight, which the evidence supports. `CONTRIBUTING.md`'s claim is
self-fulfilling — an exclusion moves the boundary rather than violating it — but the workflow
file's stronger house standard applies: everything excluded is excluded for one documented
reason, rather than to make CI pass. Fixing the nine findings and removing the entry fixes
today and not the class: an undocumented exclusion entry.

**Fix.** Remove the entry, fix the nine findings — three automatically, two by hand, four by
formatting — and add a structural test that every string in the exclusion list appears in the
comment block immediately preceding it, turning the house standard into a check. If any
exclusion is kept, extend the comment to justify it. No behavioural change.

**Tests.** The linter and formatter green over the whole tree, which the existing lint step
already runs; plus the documented-exclusion assertion.

### J-mirrors-and-dx-28 — the sidecar's tests are never type-checked, and type-check clean

**severity** medium · **surface** build-system · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** The sidecar's type-check covers its source only, while the web package checks
source, tests and end-to-end specs, and `CONTRIBUTING.md` claims strict type-checking for the
sidecar package.

**Reproduction.** `agent/tsconfig.json` includes the source only and additionally excludes
the test directory — a redundant exclusion, since the include already admits only the source.
Type-checking source and tests together under the sidecar's own strict options produces
**zero errors**, so the fix lands green. Mitigating fact the audit did not note: the linter
*does* cover the tests, so the explicit-any rule and the import restriction already apply
there.

**Root cause.** The configuration does double duty: it is the *build* configuration, with an
output directory and declarations, and the configuration the type-check runs with. Adding the
tests to its include would emit compiled tests into the build output on every build, so the
exclusion is load-bearing for the build and wrong for the check, and the two uses were never
separated. The web package has no such tension because its configuration emits nothing. The
shape is original to the package's first commit, when the test directory was small, and was
never revisited as the suite grew to ten files. Deleting the redundant exclusion changes
nothing; widening the include would break the build and, since the build output is what the
packaged sidecar's entry resolution and one test both point at, that would be a real
regression.

**Fix.** Split build from check, as the web package implicitly has: a second configuration
extending the base with emission disabled and both directories included, with the type-check
script pointing at it and the build configuration untouched, so the build output is
byte-identical. Drop the redundant exclusion and add a one-line comment saying which
configuration builds and which checks. Measured green today, so this immediately starts
protecting ten files.

**Tests.** The existing type-check step now covers the tests; confirm the wiring once by
introducing a deliberate type error in a test file.

### J-mirrors-and-dx-15 — the glTF validator test is skipped everywhere

**severity** medium · **surface** tests · **verdict** partially confirmed · **effort** M ·
**risk** medium · **depends on** J-mirrors-and-dx-18 · **root cause** RC-10

**Symptom.** A test whose own docstring says it strengthens a CI image that installs the
binary is skipped on every machine and in every job, because no image installs it — while
`mission_plan.md` states glTF validation as a project claim.

**Reproduction.** The skip fires unless the validator is on PATH; the only other references
are the plan's claim, the renderer module and the test's own docstring; the image installs the
renderer, sandbox and browser dependencies and no validator.

**Root cause.** Two-sided: the test was written against a planned image capability, and the
image was later built without it, with nothing connecting the skip condition to the image's
contents. The commit that added the test says in its own subject that the pinned image was
deferred. **Correcting the framing:** the test is *designed* as a bonus lane — its docstring
says so and explains that the in-process structural validator asserts the invariants without
the binary — so "never executed" is true and "broken test" is not the right reading. Deleting
it would remove the only place the plan's claim is attempted; installing an unpinned binary
would let a renderer-adjacent gate drift under a floating version, which is what the pinned
image exists to prevent.

**Fix.** Install a pinned validator into the image and run the test in the lane that already
runs inside it, then make the skip *impossible* there: keep the skip for developer machines
but fail by name when the image-digest variable is set and the binary is absent — the
fail-rather-than-skip precedent the renderer gate already sets. Record in the image's README
what the binary is for and which test consumes it, as that file already does for every other
baked tool. Alternatively, if baking is judged not worth it, amend the plan's claim to name
the in-process structural check as the delivered one and delete the bonus test; both are
defensible and the current state — a claim with no lane — is not. Adding to the image is a
digest bump, which the repository treats as a re-baseline change with its own rules, so this
is **cheapest to land alongside a golden re-baseline**.

**Tests.** The test running in the golden lane, and the same test failing rather than
skipping when the image-digest variable is set.

### J-mirrors-and-dx-17 — the sidecar build skip runs whatever is staged

**severity** medium · **surface** tests · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** —

**Symptom.** The escape hatch that makes sidecar-backed lanes affordable also makes them
silently assert against stale TypeScript. The integrity manifest that exists proves the staged
tree has not been tampered with — never that it matches the source it was built from.

**Reproduction.** With the skip variable unset the helper bundles and stages; with it set it
resolves the staged tree directly. Resolution verifies the manifest on every branch, and the
manifest hashes the *staged* files at stage time — a self-consistency proof, not a freshness
proof. Nothing hashes the sidecar's source, its manifest, its lockfile or the shared limits
document. Separately, the resolution cache stores a `None` result, so once any call in a
process finds no toolchain, every later call in that process skips even if the situation
changed.

**Root cause.** The manifest was designed for a security property — a tampered limits file is
a fail-closed refusal — and reused for a freshness question it cannot answer: integrity hashes
outputs, freshness hashes inputs. The variable was added to make CI and local runs cheap and
correctly did not want to re-run the bundler, and it removed the only thing keeping outputs and
inputs coupled. It arrived with the packaging work, whose whole subject was the *packaged*
sidecar — the freshness question belongs to the development sidecar and was not in that
commit's frame. `PACKAGING.md` governs identity and is silent on freshness;
`CONTRIBUTING.md`'s rule that the packaged sidecar is the only sidecar is about identity too.
Deleting the variable makes every sidecar-backed invocation pay a bundle, which is why it
exists; a warning would be ignored.

**Fix.** Record a source digest in the staged manifest at stage time — a sorted-path hash over
the sidecar's sources, its manifest, its lockfile, its type configuration, its bundler script
and the shared limits document — surfaced as manifest metadata rather than as a hashed payload
entry, so the security property is untouched. On the skip path, recompute and compare, and on
mismatch raise naming the number of differing files and the **one command** that fixes it. Stop
caching a negative resolution, or cache it behind a sentinel a fixture can clear. Add a short
section to `PACKAGING.md` distinguishing the integrity manifest from the source digest and
stating that the skip path checks the latter, and note the variable and its guard in
`CONTRIBUTING.md`. Treat a manifest with no digest as unknown and warn once for exactly one
release, so nobody's checkout breaks on upgrade. The refusal will fire on genuinely stale
checkouts, which is the point and will feel like a new failure — the message must name the
exact commands.

**Tests.** The staged manifest records a source digest; touching a source file changes it;
skipping the build over a stale stage raises; and a negative resolution is not memoised.

### J-mirrors-and-dx-19 — a stubbed global leaks between test blocks

**severity** medium · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Two globals are replaced by one describe block and never restored after its
last test, so a later block runs against a stubbed object that is not even constructible.

**Reproduction.** The only restore is an unstub call inside the first block's own setup hook;
there is no teardown anywhere in the file and no global unstub setting in
`web/vitest.config.ts`. After the block's last test the stub remains for the whole later
block, and because the stub is a spread of a *constructor* it is a plain object: any
construction in the later block would throw. The suite is green today only because that block
renders markup and happens not to construct one.

**Root cause.** An unstub in a setup hook protects the *next* test in the same block and
nothing after the block; the test runner has a configuration option for exactly this and it is
off. The file also mixes two stubbing styles — a helper and three inline calls — so no single
teardown site is obvious. Both blocks were written in one commit and the ordering hazard was
never exercised. Moving the unstub into a teardown fixes this file and leaves every other file
free to do the same thing; the configuration flag is the root fix, and it is one line.

**Fix.** Enable global unstubbing in the web test configuration and in the sidecar's for
symmetry — it has no stubbing today, and the flag is free insurance — then delete the now
redundant unstub call and add one assertion in the later block that constructs a real object,
so the leak cannot silently return. Verify no test relies on a stub surviving into a sibling;
the export suite is the only file that stubs at all.

**Tests.** The new construction assertion, which fails today under the leak; and one shuffled
run to confirm no other file depended on ordering.

### J-mirrors-and-dx-20 — a test compiles the whole sidecar into the shared build output

**severity** medium · **surface** tests · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-31

**Symptom.** A unit test compiles the sidecar's source tree into the shared build directory as
a setup step, so the test run mutates a build output that other tooling — and, on a developer
machine, a concurrently running Python lane — also writes.

**Reproduction.** The test's setup runs the type-checker over the package and the tests spawn
the built entry point. **Correcting the framing:** no other test in the package touches the
build output, so the intra-runner hazard the audit describes does not exist. The real collision
is cross-process: the Python testing helper runs the bundler into the same directory from any
lane, and the package build is a separate CI step, so a developer running the two suites in two
terminals has two writers on one directory. Secondary cost: every run of the package's tests
pays a full compile even when one file of ten needs it.

**Root cause.** The sidecar's entry module cannot be imported: it constructs a peer bound to
standard output, registers seventeen handlers as module-level side effects and attaches input
handlers, so a test of its per-run context scoping has no way to reach it except by spawning
the built entry, and no way to guarantee the built entry matches the source except by building
first. This is J-mirrors-and-dx-31's root cause seen from the test side; the file's own header
comment documents the constraint rather than removing it.

**Fix.** Two steps, and the first is worth landing alone. **Minimal and correct now:** compile
to a per-run temporary directory and spawn from there — the test already creates and removes a
temporary directory, so the machinery is present — after which nothing writes the shared output
except the build steps that own it. **Root cause, with J-mirrors-and-dx-31:** once the entry
module exports its handler registration and confines its wiring to a guarded main, the test
imports and registers against an in-memory peer pair, needs no compile, no child process and no
build output at all, turning a multi-second build-and-spawn test into a millisecond one.

**Tests.** The same assertions against a private output directory; and, after the extraction,
against an in-memory peer, with the packaging and bridge suites as the end-to-end guard.

### J-cli-startup-6 — nothing pins the CLI startup budget

**severity** medium · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** J-cli-startup-1, J-cli-startup-2, J-cli-startup-3,
J-cli-startup-4, J-cli-startup-5 · **root cause** RC-2, RC-10

**Symptom.** Three comments in the CLI module assert that registering a subcommand costs
nothing; all three are false and have been for months. No test, lint or job checks the claim.

**Reproduction.** No test that calls the parser builder inspects the loaded module set: the
builder is called in seven suites, all for behaviour. The two existing import-boundary tests
cover the durability package and the geometry package, not the CLI.

**Root cause.** RC-2 and RC-10. Registration by import gives no signal: a new registration that
imports a heavy module still produces correct help text and correct behaviour, so every
functional test passes, and the only observable is wall time, which nothing measures. The
repository already owns the right technique — the durability boundary test runs a subprocess
and inspects the loaded modules, precisely because an in-process assertion measures the session
rather than the boundary — and never applied it to the CLI. The three false comments date from
three different commits and none was accompanied by a test. Both the specification and the
conventions are silent: no startup budget and no registration-import rule is written down, so
there is nothing for a reviewer to point at, and the nearest normative statement is about
functionality without the server package rather than about cost — which is exactly why the
current code can satisfy it while loading the whole server.

**Fix.** One subprocess test asserting the parser builder's import closure excludes the CAD
kernel, the geometry package, the MCP and web stacks and their heavy transitive dependencies,
plus byte-identical help goldens — the whole parser's and the four affected verbs' — in the
same file, so a deferred import that drops an argument is caught alongside. **Assert on module
names, never on wall time:** the closure is exact and stable, a timing assertion is not; if a
time bound is wanted it belongs in the bench with a generous ceiling. Write the convention into
`repo_conventions.md` — a subcommand module registered by the parser builder may import, at
module level or inside its registration, only modules whose closure excludes those stacks, and
the handler is where the real import belongs — name the test in `CONTRIBUTING.md`'s lane list,
and state the budget in `docs/cli.md` as a user-visible promise. Generate the goldens **before**
the fixes land: the prototype's help output is byte-identical to today's, so goldens captured
now still pass afterwards. Verify the test is red on the current tree before trusting it — a
boundary test never seen red is worth little.

**Tests.** The closure assertion, the help goldens, and the identity assertion from
J-cli-startup-5.

### J-http-limits-5 — the workspace fixture commits the build store, including a live bearer

**severity** medium · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Worse than reported. The fixture materialiser copies whatever build store the
developer's checkout happens to hold — on this machine including a serve token, signing keys and
the state database — and then commits all of it, because it ships no ignore file. Measured on
this checkout, eleven of twenty-three tracked files are build-store files, and the committed
serve token is byte-identical to the checkout's: a live bearer written into a git object.

**Reproduction.** From the real checkout, the materialised project has no ignore file and
tracks the token, a key, the state database, the serve record, a probe record, four blobs and
two session transcripts. From a *pristine* source with the store removed it still tracks the
state database, a key, a blob and both transcripts, because two of the materialiser's own steps
create the store **before** the commit. Any subsequent serve activity then shows as dirty
build-store entries in the git status projection — which is what the workspace's dirty markers
render, and what the auditor observed.

**Root cause.** Three omissions compose. The copy has no ignore argument, so anything untracked
in the fixture directory — and the build store is gitignored repository-wide, hence invisible to
a status check and easy to miss — is copied verbatim. The materialiser writes no ignore file,
unlike the engine's own scaffolder, which writes one naming the build store — so the fixture is
the one project in the repository built by a second, divergent scaffolder. And the repository
initialisation adds everything *after* two steps have already populated the store. The module's
docstring shows the author knew the shape of the problem — it explains that the transcript
cannot live in the committed tree because the store is ignored repository-wide — and solved it
for the transcript only, by staging it elsewhere and replaying it, without noticing that the
replay target is itself then committed. The module's own standard is that nothing here
fabricates engine output and the fixture must not hold a shape the product does not produce; a
project whose build store is under version control is precisely such a shape. Adding an ignore
argument fixes the leak and leaves the pristine-clone half; adding the ignore file leaves the
token copied into the destination, untracked but present and readable as the live bearer.

**Fix.** Make the materialised fixture indistinguishable from a scaffolded project plus content:
ignore the build store, the repository directory and caches on copy; write the ignore file by
**importing the scaffolder's constant**, never restating it, so the two agree by construction;
and after the commit assert that no tracked path is inside the build store, raising by name if
one is — the same fail-by-name discipline the module already applies to the transcript. Leave
the developer's stale store alone, since it is gitignored and now ignored on copy, and note in
the fixture's README that the directory is not part of the fixture. Add one line to the fixture
description that the materialised project carries the scaffolder's ignore file and that its
baseline commit contains sources only. The tracked-file count drops, so re-run the workspace
gate and the browser specs — the event archive is keyed on session and ordinal rather than git
objects, so no golden should move, but re-check any dirty-marker assertion expecting a specific
count.

**Tests.** After materialising: the ignore file exists and equals the scaffolder's constant, no
tracked path is inside the build store, and no serve token exists; after one runtime open and
close, the git status is clean — the assertion that ties the fixture to the dirty-marker
clause; and a guard that the ignore string has exactly one definition in the repository.

### J-mirrors-and-dx-13 — six Hypothesis settings without a disabled deadline

**severity** low · **surface** tests · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Six property tests run under the per-example wall-clock deadline while every
other settings block in the repository disables it. A single slow example on a loaded runner
raises a deadline failure and reds the build for a reason unrelated to the property.

**Reproduction.** Six sites lack the disable — five in the addressing suite as reported,
**plus one in the render-palette suite at ten times the example count, which the audit missed
and which is the highest-risk site**; seven sites have it. **The flake did not reproduce**: at
four times CPU oversubscription the four addressing properties took 19.18 s against 8.66 s
unloaded, about 24 ms per example against a 200 ms deadline. So this is a real convention
violation and a latent one.

**Root cause.** The deadline is *per example*, so one descheduled example is enough, and the
drawn structures grow with the example, making the worst case well above the mean. These are
among the earliest property tests in the tree and the disable appears in every later one, so
the six are pre-convention rather than deliberate. `CONTRIBUTING.md` requires property tests
for kernel services and states no deadline policy, so the specification is silent and the code
is inconsistent — the fix therefore includes writing down the convention the repository clearly
has in practice. Adding the disable to six decorators leaves the seventh author to guess again.

**Fix.** Register a repository profile in a root configuration file so the default stops
mattering — there is no profile registered anywhere today, which is why every author must
remember — and also add the disable explicitly at the six sites, so the intent survives a
profile change. State the convention beside the property-testing requirement: a per-test
settings block never re-enables the wall-clock deadline, which measures the runner rather than
the property. Disabling a deadline can only turn a red into a green. The honest limit: it also
disables the only signal for a property that has become pathologically slow — the right trade,
because the repository already made it seven times.

**Tests.** A meta-assertion walking the test modules and failing on any settings block that
omits the deadline keyword — the same census idea applied to test hygiene, cheap and
self-defending.

### J-mirrors-and-dx-16 — the liveness helper forks a process per poll

**severity** low · **surface** tests · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** About thirty orphan and liveness assertions across nine test files depend on a
helper that forks a subprocess on every call, including inside tight polling loops.

**Reproduction.** **The audit's mechanism is wrong.** A missing executable raises a
file-not-found error regardless of the check flag — verified — so a missing process tool makes
every one of those assertions *error loudly*, not pass vacuously. Second correction: the two
jobs that run inside the pinned image run suites that call the helper **not at all**; every
caller runs on a stock runner where the tool is present. What is real: a sibling module
implements the same predicate in-process correctly, this one does not, and this one forks
inside loops in five suites.

**Root cause.** The process listing is used specifically to detect a zombie — the supervisor's
children are its own subprocesses and become zombies until reaped, so a bare signal probe would
report a dead sidecar as alive. That is a *correct* requirement the sibling does not have,
since it checks a foreign process from a record. The mistake is reaching for the process tool
rather than the kernel's own process file, which carries the same state character with no fork
and no PATH dependency on the only platform the sandbox suites support. Single commit, never
revisited; the better sibling came later and did not back-port. No clause governs it, so this is
a robustness and cost finding, not a correctness one. Adding the process tool to the image would
address a problem that does not exist and leave both the per-poll fork and the two
implementations of one predicate.

**Fix.** Reimplement the helper in-process against the kernel's process file, preserving the
zombie distinction that motivated the fork, and keep the subprocess path behind an availability
check as the portable fallback. Document why a zombie counts as dead here and why a bare signal
probe is insufficient, so the next reader does not simplify it away. Optionally consolidate with
the sibling by parameterising the zombie treatment. Behaviour is identical on the supported
platform and an undeclared runtime dependency leaves the test surface.

**Tests.** Spawn a child, kill it without reaping, and assert the helper reports it dead while
the zombie exists — the assertion that has no test at all today.

### J-mirrors-and-dx-21 — four independent free-port helpers

**severity** low · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Four copies of the same helper bind port zero, read the assigned port, close the
socket and hand the number to a server started moments later. Between the close and the bind
the port can be taken — rarely, and then as an unexplained bind failure in a suite that has
nothing to do with ports.

**Reproduction.** Four byte-identical bodies across the server tests, a stage harness and the
browser fixture; three named at module scope and the fourth importing its module inside the
function, which is the signature of a copy made in a hurry. No reuse option, no retry, and no
verification that the server came up on the port claimed. Not observed failing in this session
— the window is small.

**Root cause.** The pattern is inherently racy and there is no way to make the bind and the
later bind atomic. What is fixable is the duplication — four copies means four places to add a
retry — and the absence of any retry, which makes the race unrecoverable rather than merely
rare. Each copy arrived with the suite that needed it; no single commit introduced all four. The
repository has a shared test-support package that is the obvious home. Consolidating without
adding the retry keeps the same failure probability in one file; the value is the retry, and
consolidation is what makes it cheap.

**Fix.** One helper in the shared testing package that picks a free port, calls the caller's
start function and retries on a bind failure, so the retry actually covers the window; callers
pass their own start closure. Keep a plain port picker for the one or two sites that genuinely
need only a number. Wrap the browser fixture's serve start in the retrying form — it is the
longest-lived of the four and the one whose failure is most expensive.

**Tests.** The helper retries past a deliberately occupied port and succeeds on the second
attempt.

### J-mirrors-and-dx-23 — one wall-clock budget with provenance, one without

**severity** low · **surface** tests · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Two suites assert against elapsed seconds. One is an undefended magic number; the
other is a well-engineered derived ceiling the audit lumps in with it.

**Reproduction.** `core/tests/test_fixtures_build.py:48` is a bare per-part budget whose only
comment names a brief — no measurement behind it and no headroom factor, so on a slow runner it
is a flake with a misleading name. `tests/stage12a/test_g12a_boundary_cli_and_ceilings.py:77`
is a rounded product of a headroom multiplier and a pinned measurement taken inside the image
by a recording script, re-measured on every run by its own CI lane, with a provenance comment
naming the date, the value, the triangle count and the container. **That one is exemplary, not
a defect.**

**Root cause.** The repository evolved a good pattern for time budgets — the workflow file
states it: a performance budget is a ceiling whose constant is derived from the image's own
archived measurement, so re-measurement is taken rather than owed — after the older site was
written, and the old site was never migrated. Raising the bare budget to silence a flake is the
classic wrong move: it makes the assertion meaningless without saying so.

**Fix.** Either migrate the bare budget into the recorded-measurement pattern, or — cheaper and
probably right for a fixture smoke test — demote it from a performance assertion to a printed
timing plus a very generous ceiling whose comment says it detects a **hang**, not a regression.
Choose deliberately and write down which; print the measured seconds as the pinned lane does,
since a gate that only says "under the ceiling" cannot set a constant from its own measurement.
Leave the derived ceiling alone. State the rule once in the quality bars: a time-based
assertion is either a derived ceiling with recorded provenance or an explicitly labelled hang
detector, and there is no third kind.

**Tests.** The reshaped assertion, whichever form is chosen.

### J-mirrors-and-dx-24 — fixed sleeps used as negative assertions

**severity** low · **surface** tests · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Four places sleep a fixed interval and then assert that something did *not*
happen. A negative asserted after a fixed wait is only as strong as the wait, and on a slow
runner the event it denies may simply not have arrived yet.

**Reproduction.** Two supervisor tests sleep half a second and then assert a spawn count and a
respawn count — asserting an absence of respawns; a bridge-bounds test sleeps briefly to let
straggling progress deltas arrive and then asserts no overflow; and a lease test sleeps to let
a real-clock expiry elapse, which is a *positive* wait for a clock and a different, more
defensible case. Notably, the same bridge-bounds file uses the correct bounded-poll helper on
the line immediately before its fixed sleep.

**Root cause.** There is no observable "nothing more will happen" event, so the author reached
for a sleep. In three of the four a suitable positive edge does exist: the supervisor's respawn
backoff is configurable in the test, so the assertion can poll rather than sample once; and the
progress case can drain and count instead of sleeping. Each arrived with its own suite; no
single commit. Nothing is wrong against a clause — it is weaker than the repository's own
bounded-poll idiom used two lines away. Lengthening the sleeps makes the tests slower and no
stronger.

**Fix.** Per site, replace the sleep with a positive edge where one exists, and where none
does, state the sleep's role honestly. The two supervisor sites become bounded "stays false"
polls, which catch a *late* respawn instead of racing it; the progress site drops the sleep and
asserts over the drained event list, which is already computed two lines below; the lease site
keeps its wait with a corrected comment, or injects the clock, which is the durable fix. Add
one sentence to the quality bars: a negative assertion waits on a positive edge, not on a fixed
sleep. The bounded-poll form is slightly slower when passing and much more informative when
failing.

**Tests.** The four reshaped assertions are the tests.

### J-mirrors-and-dx-26 — CI type-checks a narrower target than the configuration declares

**severity** low · **surface** build-system · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** CI type-checks three of the five directories the configuration declares. **The
audit's headline — a 497-error backlog in the bench package — is not reproducible**; the actual
state is zero debt and an unenforced claim.

**Reproduction.** A bare type-check over the configured include reports **zero errors and zero
warnings**, and the bench source reports zero errors over all of its files. The narrow command
reports the same. What remains true: the workflow step and the documented command both spell the
narrow form, while `CONTRIBUTING.md` claims strict type-checking everywhere the root
configuration covers — a claim nothing enforces even though it currently holds.

**Root cause.** The workflow step was written with an explicit path list before two packages
were added to the configuration's include, and the two were never reconciled; because the extra
directories happen to be clean, nothing surfaced the divergence, so the gap is silent by
construction. The widening happened in the same refactor that produced J-mirrors-and-dx-27 and
J-mirrors-and-dx-30 — a commit that moved code into new packages and updated exactly one of the
three tool configurations each time. This is the cheapest item in the ledger: the fix is
deleting three words.

**Fix.** Drop the explicit paths from the workflow step and the documented command so the
configuration is the sole declaration, and add a structural assertion that the type-check step
takes no path arguments — and the lint step likewise — so the two cannot diverge again.
Verified green before and after, so it lands with no new failures.

**Tests.** The structural assertion that the lint-and-type job checks the configured include.

### J-mirrors-and-dx-34 — the pnpm pin is copied into six places

**severity** low · **surface** build-system · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** One version number in six files. The seventh — the pinned image — deliberately
disagrees, and that disagreement is documented at length, so the finding is narrower than it
looks.

**Reproduction.** The pin appears in both package manifests, three workflow files and the
image's README, and is referenced four times in `CONTRIBUTING.md`; the image bakes an older
version. **The image divergence is deliberate and thoroughly documented**: its README explains
the whole mechanism, that the manifest field does not by itself change what corepack runs, that
the pinned lane therefore activates the pin explicitly first, and that rebaking on the pin would
remove both the extra step and the download. The workflow file records the incident that
produced the exact pin — a floating major let the stock runners drift while the image stayed
behind, and the two versions disagree about whether a build refusal is fatal. So only the
six-way duplication of the pin string is the defect.

**Root cause.** Workflow environment values cannot reference a file, so each workflow restates
the number, while `docs/install.md` already names the intended precedence — the pin is read,
never copied, from the sidecar's manifest first and the workflow variable second — and the
bootstrap implements exactly that read. The workflows are the one consumer that copies. One
release workflow's comment even asserts agreement with another's, unenforced.

**Fix.** Two layers. **Enforce**: a structural assertion that both manifests and the three
workflow variables carry the same string — the repository already parses the workflow file for
its prior-gate assertion, so the idiom exists — with the image explicitly excluded and the
exclusion's reason quoted from its README. **Derive where possible**: a first step in each
workflow reading the pin out of the sidecar's manifest into the job environment, so the variable
becomes derived rather than declared, keeping the literal only as a commented fallback. The
image's divergence stays as documented; once it is rebaked on the pin, the extra activation step
and the whole divergence disappear. Values are identical today, so the assertion is green on
landing.

**Tests.** The pin-agreement assertion.

### J-mirrors-and-dx-35 — one package lacks the upper Python bound its siblings declare

**severity** low · **surface** build-system · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** Six of seven package manifests bound Python to a closed range; the durability
package's is open-ended. A resolver could take it onto a Python the rest of the workspace
refuses.

**Reproduction.** `opstore/pyproject.toml:5` declares only a lower bound where the root and the
five sibling manifests declare both; CI always resolves one pinned version, so nothing surfaces
it today.

**Root cause.** That package is the oldest — created in the first scaffolding commit — and
predates the decision to add an upper bound, which was applied to the packages created afterwards
and never back-filled. It declares no dependencies at all, which is probably why it felt exempt,
but a resolver bound is about the consumer's environment rather than the package's dependencies.
Code inconsistency, no clause violated.

**Fix.** Add the bound, and extend the existing version-coherence assertions to cover the
requirement across every workspace member, so the class is closed rather than the instance. Add
one sentence to `PACKAGING.md` stating that workspace members share the root's requirement, so
the test has a clause behind it. Narrowing a published package's requirement is technically a
metadata tightening; no release has shipped on the excluded version and CI pins an included one,
so the practical impact is nil — one release-note line.

**Tests.** Every workspace member declares the same requirement as the root.

### J-mirrors-and-dx-36 — both lint configurations use the untyped preset

**severity** low · **surface** build-system · **verdict** confirmed · **effort** M ·
**risk** medium · **depends on** J-mirrors-and-dx-28

**Symptom.** Lint runs without type information on both TypeScript packages, so the rules that
need it — floating promises, misused promises, unnecessary conditions, unsafe assignments — are
unavailable. In a codebase whose entry module is full of deliberate void-operator calls, that is
the class of rule most worth having.

**Reproduction.** Neither `agent/eslint.config.js` nor `web/eslint.config.js` enables the
project service or a type-checked preset. The repository's own custom rules are syntactic.
Concretely unavailable: the floating-promise rule, relevant at two sites in the sidecar's entry
module where the void operator is the manual stand-in for it.

**Root cause.** The default scaffold: the untyped preset is what the getting-started output
produces and neither configuration was upgraded as the packages grew. There is no evidence of a
deliberate decision — no comment in either file mentions the trade, which is real: type-aware
linting is several times slower. `CONTRIBUTING.md`'s "strict" refers to the type-checker and no
clause states a lint tier, so nothing is violated: this is an unexercised opportunity, and the
honest framing is that the repository has never decided. Switching blind would surface an
unknown number of findings across two packages and slow the lane by a large factor.

**Fix.** Measure first, then choose — the same discipline the repository applies to its
performance ceilings. Run the type-checked preset with the project service over each package in
a scratch configuration and record findings and wall time; if the count is small, which the
zero-error type-check result makes plausible, adopt it, and if it is large adopt only the two or
three highest-value rules rather than the whole preset, with a written reason. Record the
measurement and the decision in a comment, and name the lint tier in `CONTRIBUTING.md` so
"strict" stops being ambiguous. **Depends on J-mirrors-and-dx-28**: type-aware linting needs the
type configuration to cover every linted file, and the sidecar's tests are outside any include
today, so the project service would either fail or silently skip them.

**Tests.** The existing lint steps under the new configuration.

## Docs

### J-cli-robustness-18 — `docs/cli.md` promises a build-all mode the CLI refuses

**severity** medium · **surface** docs · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** B-4 · **root cause** RC-10

**Symptom.** The reference page documents a mode that does not exist: with no argument,
build every part in the project. A user following it gets a usage refusal on the project's
central verb.

**Reproduction.** `heph build` →
`heph: build: a part name or script path is required (or --stale)`, exit 2.

**Root cause.** RC-10. `core/src/hephaestus/core/cli.py:336-397` has exactly two entry
paths — a named target and a stale rebuild over the parts the projection marks stale — and
no iteration over the project's parts anywhere; the no-argument form is refused explicitly.
The module's own docstring states the actual behaviour, so the code and its docstring agree
and only the reference page diverges: the sentence describes an intent that either predated
the stale flag or was aspirational. The documentation-coverage gate asserts that a verb
*appears* in the documentation set, which it does, so a parity test cannot catch a wrong
claim about a verb that exists — and its own docstring declines to run the examples. Editing
the sentence fixes this instance and not the class: three more documented invocations in this
ledger are wrong for the same reason.

**Fix.** Correct the sentence to name the stale flag as what rebuilds more than one part, add
a worked example so a runner covers it, and add the docs-example runner that closes the class:
extract the console invocations from the reference page and run the read-only subset against a
built fixture, asserting the exit code the block shows. Optionally implement a build-all flag
if the team wants it — but not as the no-argument default, because an accidental bare
invocation in a large project is expensive.

**Tests.** The runner, which fails today on this line, on the quickstart from the broken
ledger and on the reference example in J-cli-robustness-1 — which is the point. Keep the
existing refusal test.

### J-cli-robustness-19 — four further reference-page facts do not match the shipped behaviour

**severity** low · **surface** docs · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** J-cli-robustness-18 · **root cause** RC-10

**Symptom.** The explode range is narrower in the page than in the engine; the joints and
motion empty-state transcripts are stale; an alignment mode the page says is refused *by name*
is refused generically by the argument parser; and the copied fixture the page opens with
cannot reproduce the transcripts later in the page.

**Reproduction.** The joints and motion verbs print different empty-state sentences than the
page shows; the scan verb's rejected alignment produces a bare invalid-choice error rather
than the named refusal both the page and the flag's own help promise; and
`core/src/hephaestus/core/render/inspect.py:258-261` refuses only a non-finite or negative
explode factor, so a factor of five is accepted while the page says the range is closed at one.

**Root cause.** RC-10. Each is documentation written against a behaviour that later moved:
the empty-state strings were reworded in the joints and motion work without re-recording the
transcripts; the alignment set is passed to the argument parser as a choice list, which cannot
carry a reason, so the *named* refusal both the help text and the page describe was designed
and then implemented as a generic rejection — and the sibling diff verb accepts the same token,
so a user reasonably expects it to be handled rather than unknown; the explode help and the
page both overstate a bound the engine does not enforce; and the copied fixture has no build
store, because it is gitignored, so the later transcripts describe state the reader cannot
produce. None could be caught, because the coverage gate pins verb presence only. For the
alignment mode **both** are wrong — the page and the help promise a refusal the code does not
implement; for the others the page is wrong.

**Fix.** Fix the alignment mode in code, since it is a real refusal-quality defect: drop the
choice list and validate in the handler, refusing the specific token with the named message
already written in the help and any other value with the generic list, exit 2 either way. Fix
the other three in the page: pick one explode contract and make the help agree, re-record the
two empty-state transcripts from a real run, and say that the later transcripts assume
declarations made through the tool surface, which live in the gitignored build store, so a
fresh fixture copy shows the empty states instead. Add the docs-example runner from
J-cli-robustness-18 so the class is closed.

**Tests.** The rejected alignment exits 2 with the named message and an unknown value gets the
generic list; whichever explode contract is chosen is pinned; and the two empty-state examples
run through the docs runner.

### J-http-envelope-17 — the error table contradicts itself on an unknown part

**severity** medium · **surface** docs · **verdict** confirmed · **effort** S ·
**risk** none · **depends on** —

**Symptom.** Two adjacent rows of the same table give an unknown part two different statuses.
An implementer can satisfy the section with either answer, and the implementation has satisfied
it with both plus a third.

**Reproduction.** One row lists a malformed-part reason at 400 and the next lists an unknown
part at 404. The error module implements both, which is coherent only if the two name different
conditions — and the table never says they do.

**Root cause.** The two rows were written to name different things — a malformed identifier and
a well-formed name the project lacks — and the table never states the distinction, so the first
reads as covering the unknown case too. The code took the ambiguity literally: the dispatcher
answers the first for an addressing miss, the context module answers the second for the same
class of miss, and both cite the same section. The two status rows coexist with no comment
relating them, unlike almost every other pair in that file. Both rows landed together in the
interface draft, so the ambiguity is original and has never been reconciled, unlike several
neighbouring rows which carry dated correction notes. **The specification is wrong; the code is
wrong downstream of it** — it could not be right while the governing clause admits both answers.
Fixing the code without fixing the table leaves the next implementer free to reintroduce the
other answer, citing the same table.

**Fix.** State the three-way distinction the code already half-implements, in the table, with
the raise sites named — the grounding discipline the error module's comments already use. A
part identifier that is not a legal name is the malformed reason at 400, grounded in the
project layout's pattern; a legal name the open project does not have is the unknown reason at
404 with the part and the known list; and a selector *inside* a part — focus, tag, anchor — is
the addressing reason at 400 with candidates. Add the cross-referencing comments that every
other related pair in the error module carries. This item is the **prerequisite** for
J-http-envelope-3 and J-http-envelope-4, both of which need to know which reason is correct
before they can converge.

**Tests.** A three-way parametrised assertion — an illegal name, a legal unknown name and an
unresolvable focus on a real part — which is the executable form of the specification change and
should land with it. The documentation-binding test from J-http-envelope-16 could be extended to
assert every reason named in the table has a status row with a matching status, which would have
caught this and J-http-envelope-14 together.

### J-agent-results-S4 — the Stage 2 digest still excludes four tools that shipped

**severity** low · **surface** docs · **verdict** confirmed · **effort** S ·
**risk** none · **depends on** —

**Symptom.** `agent/STAGE2_DIGEST.md:125` states the Stage 2 tool-surface scope as the full
tool schema *except* four named tools and a layout. All four named exclusions are declared and
working today, and a reader landing on that line — the file's most operationally consequential
paragraph — is told the shipped surface is smaller than it is.

**Reproduction.** The sidecar's generated tool-name list includes three of the four, and the
export operations module accepts and dispatches the fourth as a layout. The auditor drove two
of them to success end to end and the third under a probed backend.

**Root cause.** The line is a faithful record of the Stage 2 mission scope and was true when
written; Stage 6 shipped all four **one day** after Stage 2B, and the historical digest was not
revisited. The file does carry a general disclaimer — it is a historical implementation
contract, not normative today, and where it and a root document disagree the root document wins
— which covers the case in principle, but its known-drift list enumerates exactly one drift,
which invites a reader to assume the rest is current. The file has been touched four times
since, including by the commit that added that known-drift note for a different item.

**Fix.** Correct the line in place with a dated supersession rather than rewriting history:
mark the scope as of Stage 2 and append that the four shipped in Stage 6, naming the commit and
pointing at the root tool document as current. Extend the header's known-drift list with the
tool-surface entry, so the drift list is the single place a reader checks. Optionally add a
check that every tool named as excluded in a historical digest is either absent from the
generated tool-name list or followed by a supersession note — the only thing that stops this
recurring.

**Tests.** No runtime test; the optional supersession check if it is written.

### J-mirrors-and-dx-33 — the docs checker covers 29 documents and cannot see a package-relative path

**severity** medium · **surface** docs · **verdict** confirmed · **effort** M ·
**risk** low · **depends on** —

**Symptom.** The link and path checker skips the largest specification in the repository and
every package README. And even if it read them, its path rule could not catch the reported dead
reference, because the rule only validates paths whose first segment is a repository top-level
entry.

**Reproduction.** The checker reports 29 documents, all references resolving: the hand-listed
root set plus the documentation directory plus one registry guide. Four root documents are
outside that list, including INTERFACE.md, and so are nineteen READMEs and the sidecar's two
design documents. Running the same check over sixteen uncovered documents yields **15
problems**, which split cleanly: **five real rot in INTERFACE.md** and ten forward references
in two documents that are deliberately ahead of the code. And the reported dead reference in
`web/README.md:41` does **not** flag even with the file in the set, because the path check skips
any token whose first segment is not a top-level entry — confirmed: the cited stylesheet does
not exist and the real file is one directory deeper.

**Root cause.** Two independent gaps that compound. The root set is hand-maintained, so a new
root document is uncovered by default and the largest specification was never added. And the
path check's top-level anchor exists to avoid false positives on prose containing a slash, and
achieves that by refusing to resolve anything not rooted at the repository root — the right
instinct with the wrong fallback, since it should try the document's own directory first, which
the link check and a sibling branch already do for document names. The workflow file's claim is
that the docs build is the reference check and that every link, repository path and section
reference resolves, with no warning level on purpose — so the claim covers "the docs" and the
code checks 29 of about fifty documents and, within those, skips every package-relative path.
Fixing the one dead link fixes one link; adding the specification to the list catches five more
and leaves the hand-maintained list as the mechanism; and neither addresses the fallback, so the
reported defect would still slip through a widened set.

**Fix.** Three changes. **Discovery instead of a list**: glob the root and documentation
markdown plus the tracked READMEs and design documents, minus an explicit forward-looking set
whose entries carry a written reason — the repository's own documented-exclusion standard.
**Package-relative resolution**: when the first segment is not a top-level entry, try the
document's own directory before skipping. And fix the five real references plus the dead
stylesheet path. The widening is bounded and measured: five edits plus two documented
exclusions. This is also the prerequisite for the route-table binding test in
J-http-envelope-16 and for the command-form check in J-mirrors-and-dx-29.

**Tests.** The widened run is itself the test, since the checker runs in CI; plus a unit
assertion that a package-relative backticked path is resolved against its own document's
directory, asserting the current dead reference would be flagged.

### J-mirrors-and-dx-29 — four documents teach the command form two others call broken

**severity** medium · **surface** docs · **verdict** partially confirmed · **effort** S ·
**risk** low · **depends on** J-mirrors-and-dx-33

**Symptom.** A contributor who opens a package README gets the package-manager invocation form
that the two authoritative install documents each spend a paragraph explaining will not carry
the version pin.

**Reproduction.** `CONTRIBUTING.md` and `docs/install.md` are unambiguous: corepack resolves the
manager field by walking up from the current directory, the directory flag does not move that
search, there is deliberately no root manifest, so the flag form run from the clone root finds
no field and uses whatever is activated — which is why every documented step is run from inside
the package directory. Against that: `agent/README.md`, `web/README.md`, `web/e2e/README.md` and
— most authoritatively, and missed by the audit — `repo_conventions.md:167` all teach the flag
form. **Correction on CI:** the workflow's use of the flag is *not* a defect, because the stock
lanes use a direct install action that honours the manifest field, and the one corepack lane
activates the pin explicitly first, which is exactly the workaround the documentation prescribes.

**Root cause.** The package READMEs and the conventions document were written when the flag form
was the house form; the two install documents were later rewritten with the corepack analysis
and switched, and the other four were not updated **because the docs checker does not read any
of them** (J-mirrors-and-dx-33) — package READMEs, the conventions document's command blocks and
the browser README are outside its set, so nothing could have flagged the divergence. This is
documentation-refresh fallout rather than old rot: the analysis is recent and the READMEs
predate it.

**Fix.** Rewrite the command blocks in the four documents to the from-inside form the two
install documents use, each with one sentence pointing at the corepack note for the reason;
`repo_conventions.md:167` is the primary edit, since it is a conventions line prescribing the
broken form. Leave the workflow alone, with one comment noting the flag is safe there because of
the activation on the line above. Then add the mechanical check to the widened docs checker: a
console block in a governed document may not contain the flag form unless the same block or its
preceding lines mention the activation — the only thing that stops this recurring.

**Tests.** The command-form check.

### J-mirrors-and-dx-37 — the unfinished register names landed work as outstanding

**severity** medium · **surface** docs · **verdict** confirmed · **effort** S ·
**risk** low · **depends on** —

**Symptom.** The specification's register of known-unfinished work names, as outstanding,
presentation work that has since landed in full — including the alignment rules it calls out by
name. A reader planning work from that register would redo it.

**Reproduction.** The register's paragraph says the elements the markdown renderer can emit have
**no stylesheet at all**, so a table renders as unbordered text and a quotation as a bare browser
indent, and that this is presentation work including the alignment rules.
`web/src/components/stream/Transcript.module.css:89-186` delivers every one of them — spacing,
both list styles, preformatted blocks, quotations, rules, a table whose block display makes a wide
table its own scroll container, cells, **and both alignment rules**. One nuance: the styles are
scoped to a class rather than the attribute selector the specification names, so the register is
wrong about the *state* and the specification is imprecise about the *selector*.

**Root cause.** The register is prose maintained by hand and there is no mechanism tying an entry
to the code that would close it. The work landed across the three recent web refinement changes
and the register was not revisited — the same class of rot as a CLI section this audit checked
and found *accurate*, which shows the repository can keep such a register true when someone
checks. The file's own convention — named so it is not mistaken for done — is the standard it
fails. Deleting the paragraph fixes one entry; every other entry in every unfinished register has
the same failure mode, including two this audit flagged elsewhere.

**Fix.** Delete or rewrite the entry — if anything genuinely remains, the selector mismatch is the
only candidate, and it should be stated precisely and nothing more — and note in the markdown item
that presentation landed, so the history is legible. Then make the class non-recurring: give each
register entry a marker carrying a test id, and a test that runs a small predicate per id and
fails when the predicate stops holding — that is, when the work has landed and the register is
stale. An unfinished register that cannot go stale is worth more than one that is merely correct
today. Read the renderer before deciding whether the selector difference is a real remainder or an
imprecision in the wording.

**Tests.** The register-freshness mechanism, seeded with this entry's replacement or with the next
entry if this one is simply deleted.

## Not defects

Ten items were investigated and are not defects. Each is recorded with the evidence, so
that "unresolved" keeps meaning "broken" and nobody re-chases them. Where a small
documentation or hygiene improvement would have prevented the misreading, it is named — but
none of these is a behaviour change, and three of them would be regressions if "fixed".

### J-cli-robustness-19b — undocumented flags

**verdict** by design. The audit lists seven flags as undocumented. One of them,
`heph registry components`, **is** documented, with a worked example and a machine-form
example, in `docs/registry-pinning.md:56-77` — the auditor checked `docs/cli.md` alone. The
remaining four genuinely appear nowhere in the documentation set, and that is a written
policy rather than drift: `tests/stage7h/test_docs_set.py:24-27` states it in the test's own
docstring — it does not check option flags, because flag-level drift is what the help output
is for and mirroring every flag into prose creates a second, staler help text. The gate
enforces *verb* coverage over the whole documentation tree, deriving every verb and
sub-verb from the parser and asserting each appears somewhere, and the commit that added it
says the packaging invariants require every registered sub-verb to appear as a copyable
invocation. The flags are discoverable through the per-verb help, which renders for every
verb. **Optional editorial**, as a deliberate choice rather than drift repair: add a posed
render example, since posed rendering is arguably a separate mode rather than a modifier, and
cross-link the reference page to the pinning guide's components section so a reader of the
former finds the latter.

### J-agent-wiring-10 — cancelling an already-terminal delegation

**verdict** by design. The audit reports that cancelling a finished delegation returns the
completed status, "indistinguishable from *I cancelled it*". It is not indistinguishable and
the behaviour is normative. Driving both arms against a real delegation service: an
already-terminal delegation returns the completed status with its part session, child run and
delegation reference; a live one returns the cancelled status with a cancellation error, and a
repeat cancel returns cancelled again. The two carry **different status tokens**, both declared
in the tool's result union, and the model branches on status as it does for every other tool.
The tool documentation is explicit: cancellation idempotently removes a queued child or aborts
a running one and waits for its one durable cancelled terminal, and **an already-terminal child
returns its unchanged terminal state**. The service checks the child terminal first — an
existing terminal wins — before any compare-and-set, which is its documented precedence.
Reporting cancellation for work that actually completed would be the defect: it would tell the
orchestrator to discard a finished part's artifact. **Optional**: append one clause to the
tool's summary so a model reading only the tool list has the rule, and add a test pinning both
arms so a future "fix" of this non-defect is caught.

### J-agent-wiring-12 — out-of-profile tools answer "not found"

**verdict** by design. A part session that emits an orchestrator-only tool reads the model
vendor's own "tool not found" prose rather than the engine's scope refusal, and the audit filed
the difference as a defect. There are two intended enforcement layers and the specification
names them separately: tool **visibility** in the sidecar, where the per-session allowlist is
derived from the generated per-tool profile flags — never a hand-maintained list, so a tool's
per-profile availability has exactly one source of truth — and, in addition, object scope plus a
second profile check in the dispatcher. The evidence splits exactly along that line: an
out-of-scope *object* is refused by name, while an out-of-profile *tool* is never offered. The
digest says part and quick-edit sessions **do not receive the tool**, and the tool documentation
says the proxies enforce object scope *in addition to* tool visibility. Not offering a tool is a
stronger guarantee than offering and refusing it, and it costs the model no context. The
dispatcher's profile check is not dead — it is defence in depth, reachable from the MCP surface
and any future non-sidecar caller, and the module says so about the reviewer profile. The one
genuinely inaccurate thing is the dispatcher's module docstring, which describes the profile
check as what a part session *sees* without noting that the visibility filter fires first on the
sidecar surface. **Optional**: correct that docstring, and add one sentence to the part and
quick-edit system prompts naming what the session is not scoped to, so the model has the rule up
front and never emits the call — a prompt addition, not a tool-surface change, and any prompt
golden must be updated with it.

### J-agent-results-S6 — `record_requirements` does not prepend an entry

**verdict** not a defect. The audit reports that the tool silently prepends a requirement the
caller never sent. Reproduced against production code in a fresh project with no harness
helpers: the ledger is empty before, and after recording one entry it contains exactly that
entry — no other. The entry the auditor saw was seeded by the **audit harness itself**: every
audit script scaffolds with ledger seeding enabled, which defaults to true and records a minimal
entry, and `server/src/hephaestus/testing/ledger.py:1-15` documents why it exists — the
clarification gate refuses to build while the ledger is empty, so the harness supplies that
precondition and nothing more, after a measured bench run in which nothing compelled the ledger
to exist. A grep for the seeded identifier across the engine, server and sidecar sources returns
exactly one hit, in the testing package; no production path — the scaffolder, the bridge runtime,
the workspace runtime, the create tool — seeds a ledger. Code and specification agree.
**Optional hygiene**, in the auditing surface rather than the product: the seeded identifier
reads like the first entry a model would write, and the testing package is importable from a
shipped distribution, so a harness author can seed state without it being obvious in a
transcript. Renaming it to something unmistakably harness-owned costs one line plus a handful of
fixture assertions and would have prevented this misreading. Worth adding either way: an explicit
assertion that recording produces exactly the supplied entries and no others — the assertion
whose absence let the reading stand.

### J-web-viewport-6 — appearance and visibility toggles reset on reload

**verdict** by design. Toggling the viewport's appearance controls or a per-solid visibility
toggle changes nothing in the URL and is discarded by a reload, and the audit filed it as
inconsistency with everything else. Measured: before and after toggling, the hash is
byte-identical, local storage is empty and session storage holds only the workspace token; after
a reload the toggle returns to its authored default. That is the contract. §5.5 says the cluster
is **not** workspace state and that §4.5 stays closed, and both stores say why in their own
source: putting a wireframe or a hidden floor in the URL would widen a closed vocabulary, and a
link that silently hid the floor would be a link that showed a different instrument than the one
it names — the visibility store adds the sharper form, that a link which silently hid a solid
would show a different model than it names, and calls this the honest reading rather than a
shortcut. The audit's premise — that these belong with the serialised fields — is what the
closed record denies: view, explode, section and the tabs are members of it; appearance and
visibility are not, by name. Recorded so a future pass does not "fix" it. **Optional**: state
the contract to the operator once, where the cluster is disclosed, so it does not read as a bug;
and pin the closure with a test that toggling writes nothing to storage and does not change the
serialised state, plus a key-set assertion in both directions, so no appearance key can be added
without failing a test. A per-viewer convenience *outside* the URL would preserve the closure and
is a product decision, to be argued against the honest-reading paragraph rather than around it.

### J-web-viewport-8 — the Geometry tab serialises as `results`

**verdict** by design. The stage tab labelled "Geometry" writes a different token to the URL and
to its data attribute, and a reader matching the visible word to the hash finds no matching key.
The token is §4.5's closed vocabulary — the state values are enumerated there and serialised in
that form — and the client transcribes it faithfully; only the visible **label** was changed, and
the reason is recorded at the copy site: the inspector's own Results tab keeps that word, and two
visible tabs a few hundred pixels apart both reading "Results" is the operator confusion the
commit that made the change set out to fix, whose message names it alongside three others.
Renaming the state value would alter a closed vocabulary, break every bookmark carrying it and
require an amendment for a cosmetic gain; renaming the label back reopens the confusion. The
specification is silent on labels, which is why the mismatch reads as drift. **Optional**: add
one clause to §4.5 stating the rule the code already follows — the closed vocabulary is the URL
and DOM value, visible labels come from the copy module and may differ where two surfaces would
otherwise draw the same word, and the state value is normative while the label is not — with this
case named as its instance; the precedent already exists for a pin key that is deliberately never
drawn as a word. Worth adding: an assertion that the serialised tab values equal the declared
set, so a future rename of the *value* fails a test rather than breaking bookmarks, and one that
no two simultaneously visible tab bars render the same label.

### J-web-viewport-10 — the selection-resolve route is not served

**verdict** by design. The provenance panel says selection resolution is a server operation whose
route this build does not serve, so a selection cannot be made; the DFM panel says the same about
resolving a finding's topology; clicking geometry does nothing. This is unfinished, gated and
**disclosed** — not drift. The route is a Stage 5 deliverable: the plan lists selection as a
Stage 5 item and gates it, §17 assigns the route to a G5 clause and assigns a concrete resolver
in the engine to another as new work, and the interface's own risk register names the crop
renderer as the largest piece of new engine work in that stage and the only one with no existing
caller to imitate. G4 is closed; G5 is not. The client refuses honestly in §4.4's own idiom — a
limited surface states its limit — rather than rendering an inert affordance or inferring a
selection, which §1 and §12.3 both forbid. The route has never existed and the served route table
is deliberately closed, with a comment saying it is kept as data so the boundary test can assert
the served surface *is* that list. **The one real problem is a documentation asymmetry**, and it
is what made the audit read this as drift: §2.3 lists the route with a plain description while
its immediate neighbour carries an explicit new-work marker, so a reader of §2.3 alone cannot
tell which rows are served today. Fix that by marking the row and stating the rule at the head of
the table — §2.3 is the designed surface, the code's route table is the served one — and audit
every remaining row against it, since at least one other row **is** served and the table needs
checking rather than assuming. The durable version is the binding test in J-http-envelope-16.

### J-web-viewport-11 — the script editor is read-only

**verdict** by design. The Script tab renders an editor that cannot be typed into, with a visible
read-only chip, and the write route is served but exercised by no client path. Read-only is a
**deliverable**, and the component says so in its own header: Stage 4 is the read-only workspace
and editing is Stage 5's write route, which §9.1 makes a store mutation rather than a file write,
so the editor is constructed read-only and the panel says so in words — §4.4's discipline
generalised. It also disables the caret deliberately, because a read-only viewer that still shows
one invites a keystroke that does nothing. The plan lists a read-only editor as a Stage 4
deliverable and script editing with rebuild-on-save as a Stage 5 one, gated. The server shipping
the route ahead of the client is the ordinary order here: §9.1's contract — the required expected
hash, the journalled preimage, the compare-and-set — is what makes the route safe to land early,
and the client half needs the conflict experience the gate specifies, which is real work rather
than a flag flip. Flipping the flag would produce an editor that can be typed into and cannot
save, and would drop the expected-hash discipline; wiring a naive save would violate the
no-autosave rule and the concurrency clause. **The improvement is documentary**: §9.1 reads as a
live contract, so add a status line saying the server half is served and covered while the client
half is gated and not built, and the same for the parameter sliders' write route; optionally
extend the plan's existing honesty note — a green gate is not a claim that the workspace is
finished — with the two half-built routes, so the stage status is readable in one place. Note for
planning that the deferred client work is not small.

### J-mirrors-and-dx-12 — the scan facade restates the scan record

**verdict** by design. Fifteen field names appear on two dataclasses and the audit read this as
duplication; it is a layer facade with different failure semantics. The predicate-facing type is
**not** a copy: it adds two mapping fields the geometry record has no business carrying, widens a
closed alignment type to a string at the predicate boundary, and — the whole point — changes the
*failure* semantics, which its docstring states: reading one field raises a named refusal rather
than an attribute error, and three others refuse a named unmeasurable rather than defaulting to
zero, because a zero silently satisfies a tolerance comparison and a predicate would report a pass
for a record that measured nothing. Correct layering: the geometry package produces a measurement
record and the checks layer exposes it to sandboxed predicate authors with named refusals. Merging
the two — which is what "remove the duplication" would mean — would destroy those semantics and
leak a closed alignment type into the sandboxed namespace; any fix that treats this as duplication
is a regression. **The residual, narrower defect** is that the exclusion list — two fields, justified
at length in *both* docstrings, which is the only genuinely duplicated content — is prose on both
sides, so a third field added to the record is neither surfaced nor deliberately excluded; it just
does not appear. Add a small census assertion that the facade's field set equals the record's minus
an explicitly declared exclusion set plus an explicitly declared addition set, with the governing
citation declared once in the test, and shorten the duplicated rationale to a pointer at the test
that then enforces it. A new record field then fails the census until an author either surfaces it
or excludes it with a reason — which is the decision the two docstrings are currently making
informally.

### J-mirrors-and-dx-38 — the permanently skipped quick-edit key-policy case

**verdict** by design. One parametrisation of an idempotency-key policy test skips permanently,
naming the route as work that is not served yet. The skip is deliberate, named and explained, and
the test's docstring makes the argument: together with its counterpart over the key-required routes
the policy is asserted in both directions and cannot rot into whatever the implementation happens
to check, and **a route not yet served is skipped by name rather than silently counted as passing**.
The session-control route table declares five rows including the unserved one, because the *policy*
is decided for it even though the route is unbuilt — which is a defensible way to write a policy
table, and the router's own refusal names the unbuilt route as the one that will create such a
session. Deleting the skip would delete a policy row deliberately ahead of the implementation, which
is the opposite of what the docstring argues for; un-parametrising it would hide the row. **The
narrow improvement** is that the skip is computed from a hand-written served set rather than from
the router's own table — which is the authority, and is drift-checked against the real routes at
application build. Derive the served set from it, and add a companion assertion that a route in a
policy table but absent from the route table is a **known** deferral, from an explicit list carrying
its section reference. The day the route lands it appears in the route table, the skip stops firing,
and the deferral entry becomes stale in a way a second test catches.
