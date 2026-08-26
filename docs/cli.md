<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# The `heph` CLI

Every verb, with one worked example each. The transcripts below were produced
against `corpus/public_fixtures/assembly` — the public clean-room fixture that
ships with the repository — so you can reproduce all of them:

```console
$ cp -r corpus/public_fixtures/assembly /tmp/demo && cd /tmp/demo
```

`heph` is engine-first: it talks to the CAD engine directly and starts no
server. Verbs are grouped below by what they need, not alphabetically, because
what they need is the thing that surprises people.

```console
$ heph --version
heph 0.1.0
```

Exit codes are uniform: **0** success, **1** the operation ran and the answer
was "no" (a failed check, an unmet gate, a drifted registry), **2** you asked
for something impossible (bad usage, a refused capability).

---

## Engine verbs — no Node, no network

### `heph init [DIR]`

Scaffold a new project: the four-file convention `repo_conventions.md` records
(`hephaestus.toml`, `globals.py`, `parts/`, a `.gitignore` ignoring `.heph/`)
plus `checks/` seeded with the same safe cross-part template the
`create_project_check` tool installs. The example part is real — it builds with
nothing edited:

```console
$ heph init /tmp/gadget
initialized Hephaestus project 'gadget' at /tmp/gadget
  hephaestus.toml
  globals.py
  parts/example.py
  checks/project.py
  .gitignore
next: cd there and run `heph build example`

$ cd /tmp/gadget && heph build example
example: ok (current) artifact=artifact:build:sha256:2f6e01c4a51b83d2…
```

`heph init` never overwrites: a non-empty target — including a directory it
already initialized — is refused with the named `init_target_not_empty` error
(exit 1) and nothing is written. The project name is the target directory's
name; with no argument the current (empty) directory is initialized.

### `heph build [PART]`

Build a part and publish the result. With no argument, builds every part in the
project.

```console
$ heph build primary
primary: ok (current) artifact=artifact:build:sha256:8be53e4b2d66a336…
  checks: 4/4 passed
```

The artifact reference is content-addressed and immutable: it names exactly
those bytes forever, which is what lets `heph render --artifact-ref` and the
diff/compare path refer to a build long after the script changed.

| Flag | Effect |
|---|---|
| `--param NAME=VALUE` | Transient part-parameter override. Makes the build a **preview**: it is not published as the part's current state. |
| `--global-param NAME=VALUE` | The same, for a project-scope parameter. |
| `--stale` | Rebuild every consumer part whose inputs moved. |
| `--json` | Emit the exact `BuildResult` JSON (`script_contract.md` §8) instead of the human summary. |
| `--unsafe-local-executor` | Run the worker with **no OS sandboxing**. Local debugging only; refused for registry content and under `heph serve`. |

A failed build is not a stack trace: it reports the failing statement, the last
statement that succeeded, and the metrics of the last valid geometry, so the
next thing you (or an agent) do can be `heph render --last-good`.

### `heph check`

Run the project's cross-part check set — the persistent geometric spec tests
that re-run on every build forever, not just in the turn someone measured.

```console
$ heph check
fit:bracket_clears_frame: pass (measured: 0.0)
fit:bracket_seats_at_joint_clearance: pass (measured: 0.29999999999999716)
```

Every check reports its **measured value**, passing or failing. A check that
cannot tell you what it measured cannot tell you how far off you are.

`--project` requires and records a coherent project snapshot (every part built
from the same globals) rather than checking against whatever is lying around.
`--json` emits the `CheckReport`. Exit code 1 if any check fails.

### `heph lint PATH`

Lint a part script against the `script_contract.md` §9 style rules and the `hc`
shadowing rules.

```console
$ heph lint parts/bracket.py
parts/bracket.py: clean
```

`--requirements FILE` and `--request TEXT` turn on the requirement-ledger rules
from `VALIDATION.md` §2: given the original request text, `lint` can flag an
`unsourced_requirement` — a dimension in the script that nothing in the request
asked for. That is the rule that catches a model inventing a spec.

### `heph render PART`

Render the part's current build to PNGs. This is the grounded-vision path: the
same images a model sees.

```console
$ heph render bracket --views iso
bracket: rendered 1 image(s) -> render
  iso [rgb] render/bracket_iso_rgb.png
  source_artifact_ref: artifact:build:sha256:140e8013913e74af3…
```

| Flag | Effect |
|---|---|
| `--views VIEW…` | Up to four named cameras, or `az<deg>_el<deg>` (e.g. `az45_el30`). |
| `--channel {rgb,mask,section}` | RGB, an ID mask, or a section cut. |
| `--mask-mode {solid,selection}` | Which ID domain the mask encodes (`selection` requires `--channel mask`). |
| `--section-plane PLANE` | `[+-]AXIS@OFFSET`, e.g. `+Z@30` or `+Z@c` for centred. |
| `--explode T` | Explode factor in `[0, 1]`. |
| `--focus LABEL_OR_TAG` | Centre and zoom on a labelled solid or a tag. |
| `--last-good` | Render the last-good checkpoint of the most recent **failed** build. |
| `--artifact-ref REF` | Render an explicit immutable build/checkpoint artifact. |
| `--out DIR`, `--json` | Output directory; render metadata as JSON. |

Every render records the artifact it came from. A picture that cannot name its
build is not evidence.

### `heph goldens`

Regenerate the golden render corpus.

```console
$ heph goldens --update
```

It **refuses on a dirty tree**, by design: a golden regenerated alongside
uncommitted changes cannot be attributed to anything. Goldens carry provenance
(script hash + renderer version), and `verification.md` makes this the only
sanctioned path to change them. `--dir DIR` points at a different golden
directory (default `tests/render/goldens`).

### `heph diff PART TARGET`

Compare a part's current build against another part or an imported solid
(`COMPARE.md`). `TARGET` is `part:<name>` or `import:<path under imports/>`.

```console
$ heph diff bracket part:primary
…
topology (delta = b - a)
  solids      +5
  faces       +24
  edges       +42
  genus       +0
  sealed      unchanged

a volume 24246.000000 mm^3   bbox 48.000 x 48.000 x 46.000 mm
b volume 375840.000000 mm^3   bbox 180.000 x 120.000 x 102.000 mm
```

`--align as_posed` (the default) treats a moved part as a different part, which
is what you want when checking an assembly. `--align principal` aligns principal
axes first, which is what you want when comparing shapes irrespective of pose.
`--json` emits the comparison document.

### `heph assembly` / `heph assembly check`

Show the declared cross-part constraints and their latest residuals; `check`
re-evaluates every one against current builds.

```console
$ heph assembly
no constraints declared
```

Constraints are **declared by the agent**, through the `declare_constraint`
tool — there is no per-script constraint syntax and no placement solver
(`ASSEMBLY.md`). `CHECKS` keeps owning single-part assertions; cross-part fits
belong in the constraint set. The CLI reads and re-evaluates. `--json` emits
`AssemblyStatus`.

### `heph registry {list,publish,pin,update,verify}`

See [registry-pinning.md](registry-pinning.md) — it is a topic, not a flag list.

```console
$ heph registry list
dfm: unpinned (dfm)
  path:   /home/you/hephaestus/registries/dfm
  digest: sha256:891ca6c88c661a8f…
…
```

### `heph reference {add,list,remove}`

Register operator-supplied reference documents and images — a datasheet, a
photo of the part it has to mate with, a scanned sketch (`INGEST.md`).

```console
$ heph reference list
no references registered

$ heph reference add ~/Downloads/bearing-6001.pdf --name bearing-datasheet

$ heph reference remove bearing-datasheet
```

`add` takes a `pdf`, `txt`, `md`, `png` or `jpg`, **copies** it into the
project's `references/` directory and registers it under `--name` (default: the
filename). The original is untouched and the project stays self-contained.
`remove` deregisters and deletes the copy. `--json` emits the registry entry.

---

## Agent verbs — Node ≥ 22.19 and a provider config

### `heph agent`

The interactive CAD agent session: one Pi session bound to the project, running
the packaged sidecar (see [install.md](install.md)).

```console
$ heph agent --project . --profile orchestrator
```

| Flag | Effect |
|---|---|
| `--project DIR` | Project directory (default: cwd). |
| `--session NAME` | Session id to create or resume. |
| `--resume` | Resume the named session's transcript. |
| `--profile {orchestrator,part,quick_edit}` | Session profile (default `orchestrator`). |
| `--part PART` | The bound part, for a `part` or `quick_edit` session. |
| `--providers FILE` | Provider config JSON. |

Provider configuration is explicit and app-owned. It is read from `--providers`,
else `$HEPHAESTUS_AGENT_PROVIDERS`, else `<project>/.heph/providers.json`:

```json
{
  "providers": [
    {
      "id": "anthropic",
      "kind": "anthropic",
      "credential": "ANTHROPIC_API_KEY",
      "models": [{"id": "claude-opus-4-5", "contextWindow": 200000}]
    }
  ],
  "credential_allowlist": ["ANTHROPIC_API_KEY"]
}
```

Only the variables named in `credential_allowlist` are read from your
environment and handed to the sidecar. An ambient key you did not name is never
forwarded — the allowlist is the whole mechanism, not a convenience filter.

`kind` may be `anthropic`, `openai_compatible` (supply `baseUrl` — this is the
local/self-hosted lane), or `pi_native` to use Pi's own model catalog. Only
`pi_native` needs `auth_source`, an absolute path to an existing Pi `auth.json`
which the supervisor **symlinks** into the project's agent directory. Without
it, nothing outside the project is visible to the sidecar.

In session: Ctrl-C cancels the in-flight run and only that run; a second Ctrl-C
at an idle prompt exits. Images returned by tools are written under
`.heph/agent_images/` and announced, rather than dumped into your terminal.

### `heph serve --mcp`

Serve the project's tool surface over MCP. `--mcp` is required. See
[mcp.md](mcp.md) for client configuration.

```console
$ heph serve --mcp                          # stdio: what a local MCP client launches
$ heph serve --mcp --http 127.0.0.1:8765    # streamable HTTP at /mcp
```

Serve mode is the executor policy boundary: builds run on a probed secure
backend and there is deliberately **no** `--unsafe-local-executor` flag on this
verb. Under `--mcp` on stdio, stdout is the transport — diagnostics go to
stderr, always.

---

## Evaluation verbs — the `bench` extra only

These appear only when `hephaestus-bench` is installed
(`pipx install 'hephaestus-cad[bench]'`). They are how the numbers in
[leaderboard.md](leaderboard.md) are produced.

### `heph bench run`

Run the public corpus against a configured model and archive every run under
`bench/results/<model>/<date>/`.

```console
$ heph bench run --provider providers.json --model gpt-5.6-sol --seeds 3 --dry-run
bracket-101 seed=1 budget=20
bracket-101 seed=2 budget=20
…
```

`--dry-run` lists the planned (task, seed) prompts and makes **no** model call —
use it to confirm the plan before spending anything. `--spec {prose,seeded,all}`
selects the corpus split; the two splits are reported and gated separately and
are never averaged (`VALIDATION.md` §1). `--tasks a,b` names task ids.
`--seeds N` defaults to 3, the minimum the gate accepts. `--parallel N` runs
isolated (task, seed) runs concurrently. `--no-review` skips the `VALIDATION.md`
§5 termination review, which leaves `requirement_coverage` and
`review_catch_rate` unmeasured — the review runs by default for that reason.

By default a run that exceeds its tool-call budget is **observed to completion**
rather than cancelled, so the true call count is measured; grading is identical
either way. `--enforce-budget` cancels at the budget instead.

### `heph bench score DIR`

Score an archived run directory into `bench/results/<model>/<date>.json`.

```console
$ heph bench score bench/results/gpt-5.6-sol/2026-07-29
model gpt-5.6-sol date 2026-07-29: 54/72 passed
split      n   passes  pass_rate  wilson_lower_90  threshold
prose      36     25      0.694            0.5894       0.70
seeded     36     29      0.806            0.7085       -
interpretation_gap (seeded - prose): 0.111
gate: prose split only (the historical baseline)
…
```

Exit code 1 when the gate is not met — the transcript above is a real run that
did not meet it.

### `heph bench leaderboard`

Regenerate [leaderboard.md](leaderboard.md) from the archived artifacts.

```console
$ heph bench leaderboard --out docs/leaderboard.md
wrote docs/leaderboard.md

$ heph bench leaderboard --check
docs/leaderboard.md: up to date
```

`--check` writes nothing and exits 1 on drift, which is how CI notices a scored
run whose page was never regenerated. The generator only ever copies numbers out
of the artifacts; it never recomputes a rate, a bound, or a verdict.

### `heph bench cadgenbench {fetch,convert,run,package,score}`

The external-evaluation adapter (`EXTERNAL_EVAL.md`): fetch and convert a
third-party CAD benchmark into corpus form, run it, package the outputs, and
score them. An external benchmark is a check on our own corpus, so it is run
through the same engine path rather than a bespoke one.

---

## Verbs that do not exist (and why)

- **`heph export`.** Exports are a *tool* surface (`export_part`), reachable
  from the agent and over MCP, not a CLI verb. `repo_conventions.md` names
  `heph export` in a list of Node-free capabilities; that clause is about the
  engine's independence from Node, which holds, and not about a verb that
  shipped.

It is recorded here rather than quietly omitted, because a docs set that
promises a verb the binary does not have is worse than one that admits the gap.
(`heph init` used to be listed here too; it shipped — see its section above.)
