<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Contributing to Hephaestus

Hephaestus is an Autonome Research Labs project, licensed Apache-2.0. Code,
docs, registry content, and benchmark tasks are all welcome. So are bug reports
that come with a part script that reproduces the problem.

Before anything else, please read the [clean-room
boundary](#the-clean-room-boundary). It is the one rule that can make a
contribution unmergeable no matter how good it is.

## Getting set up

Public v0.1 is the engine-first CLI (`heph`). `web/` exists on `main`;
`heph serve --web` is the optional operator workspace. MCP is optional and not
required.

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ uv sync --dev                              # Python workspace — this is the install
$ uv run heph --version
```

The TypeScript agent and the web operator chrome are separate packages with
separate lockfiles, not members of one root workspace (`repo_conventions.md`,
"Stage 4 `web/` accepted versions"). Install them when you are changing those
trees or running their checks. Running the engine tests needs bubblewrap on
Linux x86_64 — see [docs/install.md](docs/install.md) for what each capability
requires and what fails closed without it.

```console
$ pnpm --dir agent install --frozen-lockfile # the TypeScript agent
```

Python is driven with `uv run …`; the two Node packages with
`pnpm --dir agent …` and `pnpm --dir web …`.

Default local checks (engine / CLI; no `web/` required). The root pytest
configuration intentionally discovers the stage gates and `opstore/tests`; the
second pytest command covers the package-local core, server, and contract suites:

```console
$ uv run ruff check . && uv run ruff format --check .
$ uv run pyright opstore core server
$ uv run pytest -m "not slow"                # root stage gates + opstore tests
$ uv run pytest core/tests server/tests contract/tests
$ pnpm --dir agent typecheck && pnpm --dir agent test
$ uv run python scripts/docs_check.py        # links, paths, and §refs
$ uv run python scripts/license_headers.py --check
```

### Optional: operator workspace (`heph serve --web`)

`web/` is in-tree on `main`. It is optional operator chrome, not the agent
core. Install and test it when you are changing that tree, running Gate G4, or
serving the workspace client (`heph serve --web` serves `web/dist` at `/`).

```console
$ pnpm --dir web install --frozen-lockfile   # the web workspace client
$ pnpm --dir web exec playwright install chromium
$ pnpm --dir web build     # `heph serve --web` serves web/dist at /
$ pnpm --dir web typecheck && pnpm --dir web lint && pnpm --dir web test
$ pnpm --dir web test:e2e  # the Gate G4 command; see web/e2e/README.md
```

## The clean-room boundary

This project derives from **observed behavior** of a commercial product — screen
recordings, on-screen scripts, and error text captured by a user of that
product — plus public build123d documentation. That is the entire provenance,
and it has to stay that way.

**Not accepted, under any framing:**

- decompiled or disassembled code from any product;
- scraped non-public assets;
- proprietary model weights or prompts;
- verbatim message text or UX copy from the reference product. Acceptance tests
  assert on error/result **fields and information content**, never on someone
  else's wording;
- **third-party component data vendored into a registry.** The operator's
  2026-08-29 decision is *reference, do not vendor* (`PARTS_STORE.md` §7): a
  parts store may carry your own generator source and the nominal dimensions of
  a published standard, and may *reference* a datasheet by URL and content hash
  with its terms declared. It may not carry vendor CAD, vendor PDFs, drawing
  images, artwork, or a vendor's dimension table copied wholesale. Publishing
  refuses any file in a `parts` tree that is not `registry.toml`, `part.json`,
  `generator.py` or `*.md`. If a component pack cannot be authored without
  vendoring something, it does not ship — say so in the PR rather than
  vendoring it.

**Trademark hygiene:** no "Smith" or "Arche" naming in code identifiers,
packages, or file names. The reference product is named only in prose, factually,
where naming it is the honest thing to do. The same rule covers component ids in
a parts registry: generic or standard-derived (`bearing_608`), never
`<vendor>_<sku>`. A vendor name and part number are factual reference and belong
in a record's `datasheet` block, which redistributes nothing.

If you have seen a commercial CAD product's source, say so in your PR. It does
not necessarily disqualify a contribution, but it has to be a known fact rather
than a discovered one.

CI license-checks dependencies. A new dependency under a copyleft or
source-available license will fail the check, and the fix is a different
dependency, not an exception.

## The benchmark corpus is off limits as reference material

`corpus/` defines the benchmark. It is split into a **public** half (in this
repository, for the leaderboard and community reproduction) and a **private**
gate half (a separate restricted repository, fetched only by the gate workflow),
so that stage gates cannot be passed by training-data leakage or by overfitting
skills to published tasks.

Therefore, in registry content — skills packs especially:

- **never reference a corpus task by name.** This is grepped in CI.
- **never reproduce a task's target geometry.** This is checked by a reviewer.

A skills pack that teaches "how to build the `nest-gusset` part" is not a skills
pack; it is an answer key, and it silently destroys the measurement everyone
else relies on.

## What a change has to clear

- **Conventional commits**, PR-only `main`. Required checks are `ci.yml` plus
  the current stage's gate workflows.
- **Never weaken an existing behavioral test.** A test that fails because
  behavior legitimately changed gets an updated assertion *and* an explanation
  in the PR. A test that fails because it is inconvenient gets neither.
- **Quality bars** (`repo_conventions.md`): ruff + pyright strict everywhere the
  root config covers; 90% line coverage on `opstore/` and `core/`; eslint + tsc
  strict for `agent/`. Property-based tests for kernel services; crash-injection
  tests for the durable store.
- **No test may pass by resolving a global `pi` or `thread-phase`
  installation.** The packaged sidecar is the only sidecar.
- **Public tool/event schemas are a contract.** Changing one requires an
  explicit contract amendment; CI diffs the Python declaration, the committed
  schema, the generated TypeBox definitions, the MCP declarations, and the
  documentation against each other.

Two changes have their own PR types because they move numbers rather than code:

- **Re-baseline PR** — a kernel or renderer upgrade. May touch the lockfile and
  the CI image tag and regenerate render goldens with `heph goldens --update`
  (which refuses on a dirty tree). It relaxes **no** thresholds; CI attaches
  before/after golden archives for review.
- **Agent-runtime upgrade PR** — a Pi or thread-phase version bump. Re-runs the
  full bridge, session-resume, event-shape, cancellation, and isolation suites,
  and may not alter public tool or event schemas.

## Licensing and file headers

| What | License |
|---|---|
| Code and docs | Apache-2.0 |
| Registry skills and docs content | CC-BY-4.0 |
| Registry part generators and DFM rules | Apache-2.0 |

By contributing you agree your contribution is licensed under those terms.

The root `LICENSE` licenses the repository; Apache-2.0 requires nothing further.
The per-file header rule this repository actually applies — checked by
`uv run python scripts/license_headers.py --check` — is deliberately narrow:

**Required** on files that are read or shipped detached from the tree, where
there is no `LICENSE` next to them to answer the question:

- standalone documents — `*.md` at the repository root and everything under
  `docs/`;
- the build, packaging and release machinery — `scripts/*.py`,
  `*/hatch_build.py`, `packaging/pyproject.toml`.

**Not required** on source modules. They ship inside wheels that carry the
license in their metadata, and the repository's existing modules do not carry
headers — a rule that made the convention retroactively false would be a
statement about a repository we do not have. A header on a source file is
welcome; it is simply not mandated, and adding them wholesale is its own
mechanical PR, not a rider on a feature change.

**Exempt by nature**, and the checker will not ask for a header here:

- `registries/**` tree content — a registry is pinned by a Merkle digest over
  its bytes, so adding a header *changes the digest* and breaks every consumer's
  pin. A comment is not free here; it is a version bump.
- `corpus/**`, `spikes/**`, and recorded fixtures under `tests/**/fixtures/` and
  `server/tests/fixtures/` — those bytes are evidence. Reformatting evidence
  edits it.
- `bench/results/**` and `bench/archive/**` — archived measurements, written by
  the harness, never by hand.
- generated files (they carry whatever their generator emits) and formats with
  no comment syntax (JSON, lockfiles).

The header itself is two lines:

```python
# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
```

```markdown
<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->
```

`scripts/license_headers.py --apply` inserts a missing one in the right comment
syntax and leaves an existing one alone.

## Contributing registry content

Adding a DFM pack, a material, a part generator, or a skill has its own guide,
because pinning and review work differently there:
[docs/registry-contributions.md](docs/registry-contributions.md).

## Contributing a benchmark task

Public-split tasks live in `corpus/tasks/` with a reference implementation in
`corpus/solutions/`. Two rules make a task real:

1. **A reference solution must pass the task's own checks in CI.** A task no
   reference solution passes is a broken task, not a hard task.
2. **The checks must measure, not assert prose.** "The bracket should be
   strong" is not a check; a mass budget, an envelope, and a clearance are.

Tasks rotate: when a private gate task is promoted to the public leaderboard, a
new private task replaces it. If you have a good task and would rather it gate
than publish, say so in the PR and it can go to the private split instead.

## Reporting a bug

The best bug report is a minimal project: `hephaestus.toml`, `globals.py`, and
one part script, plus the `heph build --json` output. Build results are
content-addressed and carry their own metrics, so that JSON usually contains the
answer already.

Please do **not** attach reference geometry or scripts you obtained from a
commercial product. See [the clean-room boundary](#the-clean-room-boundary).
