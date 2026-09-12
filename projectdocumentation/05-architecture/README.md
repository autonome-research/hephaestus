# Architecture: introduction, constraints, context, strategy

> **Verified against** `49a90c6` on 2026-09-12.
> Package boundaries from each `pyproject.toml` / `package.json`; import bans
> confirmed against the tests that assert them.

This section follows **[arc42](https://arc42.org/overview/)**. Its twelve
sections are grouped into seven documents:

| arc42 sections | Document |
| --- | --- |
| 1 Introduction and goals, 2 Constraints, 3 Context, 4 Solution strategy | this file |
| 5 Building block view | [building-blocks.md](building-blocks.md) |
| 6 Runtime view | [runtime-view.md](runtime-view.md) |
| 7 Deployment view | [deployment-view.md](deployment-view.md) |
| 8 Crosscutting concepts | [crosscutting-concepts.md](crosscutting-concepts.md) |
| 9 Architecture decisions | [decisions.md](decisions.md) |
| 10 Quality requirements, 11 Risks, 12 Glossary | [quality-and-risks.md](quality-and-risks.md) and [the glossary](../01-orientation/glossary.md) |

## 1. Introduction and goals

Hephaestus is parametric CAD that a language model can drive without the system
ever having to guess.

### The driving requirement

A person looking at a screen can see that a bracket is wrong. A model cannot. So
the system must be able to answer, for every claim it makes: **what measurement
produced this, and what did it measure?**

Everything else follows. The three top quality goals, in priority order:

| Priority | Goal | How it shows up |
| --- | --- | --- |
| 1 | **Evidential integrity** — never present an unmeasured value as a measurement | a large closed refusal vocabulary; verdicts and refusals disjoint; `unverifiable` inside `measured`; a `not_run` badge |
| 2 | **Durability** — a crash never loses or corrupts recorded work | a WAL with named crash points; recovery identical regardless of crash point; fail-closed keyring |
| 3 | **Reproducibility** — the same inputs give the same geometry | content-addressed everything; hashed build inputs; a sandbox with a fixed environment |

Performance is a constraint, not a goal. Where the two conflict — and they do,
in the on-demand renderer's synchronous frames and in `preserveDrawingBuffer` —
the evidential property wins and the cost is stated.

### Stakeholders

| Who | What they need |
| --- | --- |
| the operator | to build a part, see why a check failed, and trust the number |
| a driving model | named refusals it can dispatch on, and a declared tool surface |
| a contributor | to change one subsystem without learning all of them |
| a reviewer | to check a claim without rerunning the author's head |

## 2. Constraints

### Technical

| Constraint | Consequence |
| --- | --- |
| build123d / OCCT is the geometry kernel | the kernel is a large native dependency; it must not be needed to test durability or the tool contract |
| scripts are arbitrary Python | every build runs in an OS sandbox, never in-process |
| the sandbox is bubblewrap | secure builds are Linux-only; there is no silent fallback |
| the model provider lives in a Node ecosystem | a TypeScript sidecar, and therefore a cross-language wire contract |
| the browser cannot set a header on a WebSocket upgrade | the bearer rides a subprotocol |

### Organisational

- The repository carries **normative specifications** — `INTERFACE.md`,
  `SOLVER.md`, `tool_schema.md`, `architecture.md`, `VALIDATION.md` and others.
  Tests cite them, in places by line number, and the build fails when a citation
  stops pointing at what it claimed.
- Work is organised as **staged gates**. CI runs them by stage
  (`stage gates 1-6`, `8A-8D`, `9A-9C`, `11A-11C`, `12A-12C`, `13A-13C`), and a
  gate clause is a testable sentence, not a milestone.
- License headers are checked mechanically; Apache-2.0 throughout.

### Conventions that are enforced, not advisory

- **One implementation per behaviour.** Where two surfaces must agree, they call
  one function. `heph check --json` and `GET /parts/{part}/checks` serialize
  through the same serializer, so the e2e can assert byte-parity.
- **No limit literal is duplicated** across the language boundary; both sides
  read `schemas/bridge_limits.json`, and a census test enforces coverage in both
  directions.
- **Closed vocabularies.** A route table, a method set, an event-kind set, a
  control-frame set — each is data, and a drift test asserts the live surface
  *is* that data.

## 3. Context

### System context (C4 level 1)

```
   ┌──────────┐                      ┌────────────────────┐
   │ operator │──── heph CLI ───────▶│                    │
   └──────────┘                      │                    │
        │                            │                    │      ┌───────────┐
        └──── browser ──── HTTP ────▶│    HEPHAESTUS      │─────▶│ provider  │
                                     │                    │      │ (model)   │
   ┌──────────┐                      │                    │      └───────────┘
   │ MCP host │──── stdio/HTTP ─────▶│                    │
   └──────────┘                      └────────────────────┘
                                          │        │
                                          ▼        ▼
                                    ┌─────────┐ ┌──────────┐
                                    │ project │ │ pinned   │
                                    │ on disk │ │ registry │
                                    └─────────┘ └──────────┘
```

| Neighbour | Interface | Notes |
| --- | --- | --- |
| operator, terminal | `heph` CLI, 25 verbs | the whole engine; no server required |
| operator, browser | the workspace API over loopback | one bearer, minted per serve |
| an MCP host | Model Context Protocol, stdio or streamable HTTP | the same dispatcher |
| a model provider | through the TypeScript sidecar | credentials never in the ambient environment |
| the project | a directory with `hephaestus.toml` | see [the data model](../04-reference/data-model.md) |
| a registry | a hash-pinned directory tree | untrusted content; verify on load |

### Everything crosses one dispatcher

There is no second path to an operation. The CLI, the HTTP routes and the MCP
tools all reach `ToolDispatcher.dispatch`, and a boundary test asserts the
absence of a bypass mechanically.

That is what makes the refusal vocabulary meaningful: a refusal cannot be
avoided by picking a different surface.

## 4. Solution strategy

Five decisions shape everything else. Each is expanded in
[decisions.md](decisions.md).

### 4.1 Split durability from CAD

`opstore` is a **generic** durability substrate — WAL, idempotency keys,
content-addressed blobs, leases, run admission, GC — that knows nothing about
geometry and declares **no third-party dependencies**.

Why it matters: durability is the part that must be right under crash, and it can
now be tested exhaustively with injected crash points, a fake clock and a fake
liveness oracle, in a package that imports in milliseconds. A durability bug does
not need OCCT to reproduce.

`contract` is split out for the same reason: the tool catalogue is tested without
the kernel present.

### 4.2 Declare, then generate

The agent tool surface is declared once as data. JSON Schemas, the TypeScript
TypeBox module, the MCP declarations and the normative prose headings are all
checked against it in CI.

Why: three hand-maintained copies of 57 tool signatures across two languages
would be wrong within a month, and the failure mode is silent — a model calling a
tool with a parameter the server dropped.

### 4.3 Refuse by name, and keep the families apart

An operation that cannot produce evidence returns a **named reason**, never a
plausible number. Verdicts and refusals are **disjoint vocabularies**: a killed
solve decided nothing, so `solver_timeout` must not be spellable as an outcome.

Why: a caller — human or model — dispatches on the name. A reason that can be
read as a verdict eventually is.

### 4.4 Sandbox every execution, fail closed

A part script is arbitrary Python. Builds run in a bubblewrap sandbox whose
capability is **proven by running escape probes**, not by reading a version
string. A failing probe raises `sandbox_denied`; there is never a silent fallback
to an unsandboxed run.

Why: the unsafe backend exists only for local debugging, and every path that
could expose it to untrusted content — registry content, `serve` — refuses it
outright.

### 4.5 Content-address everything, and let GC follow reachability

Builds, renders, selection bundles, exports and bundles are blobs named by their
hash. Pins and links form a reachability graph; GC collects what is unreachable
and older than its retention class, under an exclusive lease with a **recheck
after the lease is taken**.

Why: it makes provenance addressable. A pinned artifact still resolves after a
newer build lands, which is the property the workspace's pin authority depends on.

## Where to next

- What the pieces are: [building blocks](building-blocks.md).
- What happens when something runs: [runtime view](runtime-view.md).
- How it is installed and shipped: [deployment view](deployment-view.md).
- The rules that cut across everything: [crosscutting concepts](crosscutting-concepts.md).
