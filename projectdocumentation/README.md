# Hephaestus project documentation

> **Verified against** `49a90c6` on 2026-09-12.
> Every factual claim in this set was checked against the code or a command that
> was run. See [the verification rule](#the-house-rule-nothing-is-written-that-was-not-checked).

This is the complete documentation set for Hephaestus: what it is, how to use
it, how it is built, and how to work on it. It covers the engine, the HTTP
server, the agent bridge, the TypeScript sidecar, the operator web client, the
benchmark and the engineering system around them.

## Who this is for

| You are | Start at |
| --- | --- |
| New to the project | [What Hephaestus is](01-orientation/what-hephaestus-is.md), then [Your first part](02-tutorial/your-first-part.md) |
| Setting up a machine | [Install and run](03-how-to/install-and-run.md) |
| Looking up a fact | [Reference](04-reference/) — CLI, HTTP, tools, limits, refusals, data model |
| Changing the system | [Architecture](05-architecture/) and the how-to guides |
| Keeping this set true | [Documentation maintenance](06-operations/documentation-maintenance.md) |

## How this set is organised

The shape follows **[Diátaxis](https://diataxis.fr/)**, which splits
documentation by what the reader is doing rather than by subject. Four modes,
four directories:

| Mode | Directory | Serves | Written as |
| --- | --- | --- | --- |
| Learning | [`02-tutorial/`](02-tutorial/) | someone who has never used it | a lesson that works end to end |
| Doing | [`03-how-to/`](03-how-to/) | someone with a task in hand | steps to a goal |
| Looking up | [`04-reference/`](04-reference/) | someone who needs a fact | tables and vocabularies, no narrative |
| Understanding | [`01-orientation/`](01-orientation/), [`05-architecture/`](05-architecture/) | someone who needs the why | prose that explains decisions |

Mixing the modes is the usual way documentation becomes unusable: a tutorial
that stops to explain a design decision loses the beginner, and a reference that
tells a story cannot be scanned. Each file here stays in one mode.

The architecture section follows **[arc42](https://arc42.org/overview/)**, the
standard twelve-section template for architecture documentation, and uses the
**[C4 model](https://c4model.com/)**'s levels — context, container, component —
for its diagrams. Decisions are recorded as ADRs in
[`05-architecture/decisions.md`](05-architecture/decisions.md).

The whole set is **docs-as-code**: it lives in the repository, changes in the
same commits as the code it describes, and is checked by the same CI that
checks the code. `scripts/docs_check.py` resolves every link, repository path
and section reference in these files, and fails the build on a dangling one.

## The house rule: nothing is written that was not checked

**Every claim in this set is verified before it is written.** Not "believed",
not "read in an older document" — checked against the code, or against the
output of a command that was actually run.

This rule is not decoration. While this set was being written, three separate
claims that everyone believed turned out to be false: a helper's own docstring
said it read the kernel's process file when it forked a process listing, a
commit message repeated that claim, and a subsystem summary said an API exported
57 names when it exports 61. Each was caught by running something.

What that means in practice:

- A number in these docs comes with the file that defines it, or the command
  that printed it.
- A behaviour is described after it was exercised, not after its name was read.
- Where something could not be verified, the document says so rather than
  guessing. Look for **Unverified** sections.
- Each document carries a `Verified against <commit>` stamp at the top saying
  which revision it was checked against.

The procedure is written down in
[the verification runbook](06-operations/verification-runbook.md), and the
routine that keeps the set from drifting is in
[documentation maintenance](06-operations/documentation-maintenance.md).

## This set and the repository's specifications

Hephaestus already carries normative specifications at the repository root —
`INTERFACE.md`, `SOLVER.md`, `tool_schema.md`, `architecture.md`, `VALIDATION.md`
and others. Those documents are **authority**: tests cite them, in places by
line number, and the build fails when a citation stops pointing at what it
claimed.

This set does not replace them and does not copy them.

- A normative rule lives in the spec. These documents **point at it**.
- Where a number or a vocabulary appears here, it is because it was read out of
  the code, and the source is named.
- Restating a spec would create a second copy to drift, and drift in a document
  that looks authoritative is worse than no document.

So: read this set to understand and to work. Read the specs when you need the
normative wording, and treat them as the tiebreaker.

## The map

### 01 Orientation
- [What Hephaestus is](01-orientation/what-hephaestus-is.md) — the problem, the
  product, the shape of the system.
- [Glossary](01-orientation/glossary.md) — the vocabulary, defined once.

### 02 Tutorial
- [Your first part](02-tutorial/your-first-part.md) — install to built geometry,
  start to finish.

### 03 How-to
- [Install and run](03-how-to/install-and-run.md)
- [Run the tests](03-how-to/run-the-tests.md)
- [Work on the sidecar](03-how-to/work-on-the-sidecar.md)
- [Add or change an agent tool](03-how-to/add-or-change-a-tool.md)
- [Release and package](03-how-to/release-and-package.md)

### 04 Reference
- [Command line](04-reference/cli.md)
- [HTTP API](04-reference/http-api.md)
- [Agent tools](04-reference/agent-tools.md)
- [Bridge protocol](04-reference/bridge-protocol.md)
- [Limits and configuration](04-reference/limits-and-configuration.md)
- [Refusal vocabulary](04-reference/refusal-vocabulary.md)
- [Data model](04-reference/data-model.md)
- [Web client](04-reference/web-client.md)

### 05 Architecture (arc42)
- [Introduction, constraints, context, strategy](05-architecture/README.md)
- [Building blocks](05-architecture/building-blocks.md)
- [Runtime view](05-architecture/runtime-view.md)
- [Deployment view](05-architecture/deployment-view.md)
- [Crosscutting concepts](05-architecture/crosscutting-concepts.md)
- [Decisions](05-architecture/decisions.md)
- [Quality and risks](05-architecture/quality-and-risks.md)

### 06 Operations
- [Verification runbook](06-operations/verification-runbook.md)
- [Documentation maintenance](06-operations/documentation-maintenance.md)
- [Known open issues](06-operations/known-open-issues.md)

## Sources for the documentation standard

- Diátaxis, the four-mode framework: <https://diataxis.fr/>
- arc42, the architecture template: <https://arc42.org/overview/>
- C4 model, diagram levels: <https://c4model.com/>
- Architecture decision records: <https://adr.github.io/>
