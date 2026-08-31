<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# The `heph` CLI

## For agents

You do not need the browser or MCP. After `uv sync --dev` in a clone, put
`.venv/bin` on `PATH` (or call that `heph` by path). Create, edit, inspect,
and build a part with the authoring verbs:

```console
$ heph init /tmp/gadget && cd /tmp/gadget
$ heph part list
$ heph part create spacer --template blank --json
$ heph script show spacer --json
$ heph script write spacer --file spacer.py --expected-hash sha256:… --json
$ heph params spacer --json
$ heph prompt set --file request.txt
$ heph prompt show --json
$ heph build spacer
$ heph part show spacer --json
$ heph lint parts/spacer.py --request .heph/request.txt
$ heph check --json
$ heph render spacer
```

`heph part create` is `create_part` (`base_hash=None`): an existing name is
`{"part":"…","status":"already_exists"}` and exit 1; nothing is written. `heph
script write` is `write_part`: CAS on `--expected-hash` (required; omitting it
is usage, exit 2). Take that hash from the `content_hash` `heph part create`
or `heph script show` just printed. A stale hash is a discriminated `conflict`
(exit 1). `heph prompt` stores operator request text at `.heph/request.txt` —
not a hosted chat and not a context envelope. `--json` is on `part`, `script`,
`params`, `prompt`, `build`, `check`, `lint`, and `render`. The rest of this
page is the verb reference. Optional MCP: [mcp.md](mcp.md).

---

Every verb, with one worked example each. The transcripts below were produced
against `corpus/public_fixtures/assembly` — the public clean-room fixture that
ships with the repository — so you can reproduce all of them:

```console
$ cp -r corpus/public_fixtures/assembly /tmp/demo && cd /tmp/demo
```

`heph` is engine-first: it talks to the CAD engine directly and starts no
server. From a clone, prefix every command with `uv run` (`uv run heph
--version`). Verbs are grouped below by what they need, not alphabetically,
because what they need is the thing that surprises people.

```console
$ uv run heph --version
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

### `heph part list` / `heph part create` / `heph part show`

The agent-shaped part verbs. Listing and showing compute nothing; creating
writes through the same `create_part` store contract the tool surface uses
(`base_hash=None`, refuse without mutation if the file exists).

```console
$ heph part list
bracket	parts/bracket.py	sha256:…
primary	parts/primary.py	sha256:…

$ heph part create spacer --template blank --json
{"content_hash":"sha256:…","initial_script":"from build123d import *\n\n\nwith BuildPart() as part:\n    pass\n","path":"parts/spacer.py","replayed":false,"snapshot_ref":"artifact:part-snapshot:sha256:…","status":"ok"}

$ heph part create spacer --json
{"part":"spacer","status":"already_exists"}

$ heph part show spacer --json
{"current":false,"part":"spacer","status":"not_built"}
```

| Flag / form | Effect |
|---|---|
| `list --json` | The `list_parts` projection — `{status, parts:[{name, path, content_hash, snapshot_ref}]}`. Same serializer as MCP `list_parts` and `GET /parts`. |
| `create NAME --template {blank,sheet,solid,from_store}` | Seed `parts/<name>.py` from the `create_part` template table (default `blank`). |
| `create NAME --file PATH` | Seed from a script file, or `--file -` for stdin. Replaces the template. |
| `create … --json` | The `create_part` result (`path`, `initial_script`, `content_hash`, `snapshot_ref`). An existing name is `{"part":"…","status":"already_exists"}` and exit 1; nothing is written. |
| `show NAME --json` | The last published `BuildResult` (the same document `heph build --json` emits), or the named absence `{status:"not_built"}`. Does not rebuild. |

`--description` is accepted for `create_part` parity; the engine does not apply
it. There is no force-create.

### `heph script show NAME` / `heph script write NAME`

Read or replace a part script. Write is `write_part`: optimistic CAS on
`--expected-hash`, no force overwrite.

```console
$ heph script show spacer --json
{"content_hash":"sha256:…","line_count":5,"name":"spacer","path":"parts/spacer.py","script":"…","snapshot_ref":"artifact:part-snapshot:sha256:…","status":"ok"}

$ heph script write spacer --file spacer.py --expected-hash sha256:… --json
{"applied":true,"content_hash":"sha256:…","path":"parts/spacer.py","replayed":false,"snapshot_ref":"artifact:part-snapshot:sha256:…"}

$ heph script write spacer --file spacer.py --expected-hash sha256:stale --json
{"applied":false,"conflict":{"attempted_snapshot_ref":"artifact:part-snapshot:sha256:…","base_snapshot_ref":"artifact:part-snapshot:sha256:…","current_hash":"sha256:…","current_script":"…","current_snapshot_ref":"artifact:part-snapshot:sha256:…"}}
```

A stale `--expected-hash` is a discriminated `conflict` (exit 1) carrying the
live hash and script, the same shape the `write_part` tool returns. `--file -`
(or a piped stdin when `--file` is omitted) writes from stdin. `--expected-hash`
is required; omitting it is usage (exit 2). There is no force overwrite.

### `heph params [PART]`

Show declared `PARAMS` and the last-build effective values. No sandbox and no
geometry kernel: literals are read from the script, effective numbers from the
published build when one exists.

```console
$ heph params primary --json
{"params":[{"default":15.0,"doc":"","max":30.0,"min":6.0,"name":"post_inset","scope":"part","step":null,"value":15.0}],"part":"primary","status":"ok"}

$ heph params --json
{"parts":{"primary":[…],"bracket":[…]},"project":[…],"status":"ok"}
```

With no part name the document is `{status, project, parts}` — project-scope
rows from `globals.py` / `hephaestus.toml` plus every part. `--json` is the
machine form an agent should read.

### `heph prompt` / `heph prompt show` / `heph prompt set`

Store or print the operator request text at `.heph/request.txt`. This is **not**
a hosted chat and **not** a context envelope (`INTERFACE.md` §7A.3): no model
runs, no session starts, and the file is not forwarded to `set_request_text`.
It is a place an external agent can keep the original request so a later
`heph lint --request FILE` can name the same words. Bare `heph prompt` is
`heph prompt show`.

```console
$ heph prompt show --json
{"path":".heph/request.txt","status":"empty","text":""}

$ heph prompt set --file request.txt
stored 24 byte(s) -> .heph/request.txt

$ heph prompt show --json
{"path":".heph/request.txt","status":"ok","text":"40 mm spacer, 6 mm plate\n"}
```

`--file -` (or a piped stdin) sets from stdin. An unset request is
`{"path":".heph/request.txt","status":"empty","text":""}`, not an error.
`heph lint` is unchanged: it still takes `--request FILE` explicitly.

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

`--requirements FILE` and `--request FILE` turn on the requirement-ledger rules
from `VALIDATION.md` §2: `--request` is a path to the original request text
(the file `heph prompt` writes is `.heph/request.txt`). Given that text, `lint`
can flag an `unsourced_requirement` — a dimension in the script that nothing
in the request asked for. That is the rule that catches a model inventing a
spec.

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

### `heph scan PATH --units` / `heph scan check PART PATH --units`

Read a mesh or point cloud under `imports/` and print what the harness can
honestly say about it (`MESH_INGEST.md` §7.3). The first form prints the file's
facts; the `check` form additionally measures a built part against it.

```console
$ heph scan limb-l.stl --units mm
scan limb-l.stl  units declared mm
  canonical hash           sha256:9f2c…
  vertices as read/welded  1027 / 1003
  triangles                2002
  bbox                     40.000000 x 30.000000 x 20.000000 mm
  tessellated volume       33273.571711 mm^3 (polyhedron, inscribed — low)
  watertight at weld tol   True
quality (measured and named; nothing was repaired):
  boundary edges / loops   0 / 0
  self-intersecting pairs  0  [uniform_grid_exact_pairs]
```

```console
$ heph scan check socket limb-l.stl --units mm
scan check socket against limb-l.stl  units mm  align as_posed
  scan -> part            mean 2.31 mm   max 4.02 mm
  part -> scan            mean 2.19 mm   max 3.88 mm
  part -> scan method      kdtree_bound_exact_triangle (bias exact)
```

`--units` is **required in both forms**: STL, PLY, OBJ, OFF and XYZ carry no
unit, the engine is millimetres throughout, and inferring one from the bounding
box would be a guess dressed as a measurement. The path is resolved under the
project's `imports/` through the same confined read a build uses, so what you
inspect is exactly what a build would admit, refusals included.

The facts are facts about the **file**: nothing was repaired, no surface was
reconstructed, and a defect the scanner left is reported rather than cleaned.
`--align declared --transform …` supplies a rigid 4×4 for the check form;
`principal` is refused by name, because a limb scan is always partial and the
sampled region's principal axes are not the object's. `--json` emits the record.

**Nothing here is a clinical claim** (`MESH_INGEST.md` §11.3). A distance is not
a fit: rectification is clinical judgement the harness cannot verify, and
structural adequacy is FEA, which this project defers by name.

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

### `heph joints`

Show the declared joint set (kind, parent/child anchors, travel limits,
provenance — withdrawn entries stay listed with their reasons) and the latest
per-joint and per-pose motion outcomes.

```console
$ heph joints
no joints declared
```

Joints and poses are **declared by the agent**, through the `declare_joint` /
`declare_pose` tools — there is no per-script joint syntax and no solver:
scripts position geometry, poses exist only inside an evaluation
(`KINEMATICS.md` §1). `--json` emits the machine form.

### `heph motion` / `heph motion check`

Show the motion status, the latest sweep results (worst-sample parameter
values and measured value for every check), and the coupling table; `check`
re-evaluates now against current builds — pass ids to re-evaluate a subset.

```console
$ heph motion
no joints declared
$ heph motion check
no motion checks declared
```

Sweep verdicts are the closed `KINEMATICS.md` §4 vocabulary —
`holds_at_samples`, never "holds": a sweep is sampled evidence, not a
continuous guarantee. `--json` emits `MotionStatus` plus the per-check
results.

### `heph cam emit`

Emit a laser-cut / waterjet cut-file from a part's current build: kerf-
compensated flat patterns as an ordered toolpath plus a DXF. This is **not**
`export_part` and not Stage 14 milling CAM. Kerf comes from `--kerf-mm` or
from the process DFM pack's `kerf_mm` (`laser_cut` 0.2 mm, `waterjet` 0.8 mm);
a default is never invented.

```console
$ heph cam emit plate --out plate.dxf --json
```

`--json` is the machine record (kerf source, contours, DXF hash). The DXF
is always written. A part whose `part.process` is not `laser_cut` or
`waterjet` is refused by name.

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

### `heph import {add,list}`

Admit a vendor STEP or a scan into the project's `imports/` so a part script
can name it (`import_step` / `import_mesh`). This is project ingress, not a
second geometry kernel: the file is copied, content-hashed, and optionally
used to seed `parts/<name>.py` through the same `create_part` contract as
`heph part create`. Browser import stays deferred (`INTERFACE.md` §15.37).

```console
$ heph import list
no imports

$ heph import add ~/Downloads/vendor_plate.step --json
{"kind":"step","name":"vendor_plate.step","path":"imports/vendor_plate.step","sha256":"sha256:…"}

$ heph import add ~/Downloads/limb-l.stl --units mm --part socket
copied limb-l.stl (mesh, units=mm) sha256:… -> imports/limb-l.stl
created parts/socket.py
```

STEP (`.step` / `.stp`, AP203/AP214) takes no `--units`. STL, PLY, OBJ, OFF
and XYZ **require** `--units {mm,cm,m,in}` — those formats carry none, and a
unit is never inferred. An unknown suffix is a named refusal. The original
file is untouched; the copy under `imports/` is a regular file (no symlink
escape). `--part NAME` writes `part.geometry = import_step("copied-name")` for
STEP, or `import_mesh` plus `mesh_to_solid` with the declared unit for a mesh,
and refuses `already_exists` without force if the part is already there.
`--json` on `add` emits `{name, kind: step|mesh|points, sha256, path, units?}`.

### `heph export {list,unpin}`

Show what this project has exported and release an exported file's retention
hold. Exports are produced by the `export_part`, `generate_drawing` and
`generate_doc` **tools** — from an agent session, over MCP, or from the
workspace's Export panel — and every output they write is pinned as a garbage
collection root that also protects the build it came from, permanently. These
two verbs are how that retention is inspected and given back.

```console
$ heph export list
part     format  layout    bytes  pin     blob                                                                     path
bracket  step    as_built  37056  pinned  sha256:7768d0fc357e4be96e72b767e7cbf018bac6d97af4be9333cb23db7f476a2111  .heph/exports/bracket-7768d0fc357e4be9.step

1 export(s), 1 file(s), 37056 bytes
store: 50563 protected of 10737418240 quota (52923 stored)
drop an export's GC root with 'heph export unpin BLOB' (deletes nothing)

$ heph export unpin sha256:7768d0fc357e4be96e72b767e7cbf018bac6d97af4be9333cb23db7f476a2111
unpinned sha256:7768d0fc357e4be96e72b767e7cbf018bac6d97af4be9333cb23db7f476a2111 (37056 bytes) — bracket bracket-7768d0fc357e4be9.step
now collectable: the blob and anything it alone protected are eligible for the next GC pass once past their retention horizon
store: 13507 protected of 10737418240 quota (52923 stored)
```

`list` takes an optional part name to filter, computes nothing, and loads no
geometry kernel. The `pin` column has three values and they are three different
facts: `pinned` is a garbage collection root in its own right, `reachable` is
unpinned but still protected by something else (so unpinning it reclaimed
nothing), and `collectable` is eligible for the next pass once past its
retention horizon.

`unpin` **deletes nothing**. It removes one pin; the bytes survive until they are
both unreachable and past their retention horizon, and the collection itself is
the store's own pass. It is idempotent, and it refuses a hash that is not the
output of a committed export in this project — including one that is genuinely
stored for another reason, because this is an export verb and not a general
unpin.

The `store:` line is the quota accounting, and it is actionable: when
*protected* bytes alone exceed the quota, new builds and new exports refuse with
`protected_quota_exceeded` before they run. Unpinning is one of the two remedies;
the other is a larger quota.

The workspace deliberately offers neither verb: there is no unpin and no delete
in the browser, which is why the Export panel says exports are kept until they
are unpinned from the command line. Both verbs need no Node and no network; they
ship with the server package, which owns the export record, so they are present
whenever `export_part` is.

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

**Client mode, when a server already owns the project.** One process owns a
project's session leases. If `heph serve --web` is already running here, this
verb does **not** open a second agent runtime: it reads `.heph/serve.json`,
reads the `0600` token that record names, and drives the running server's
sessions over loopback. The REPL is identical, and the session you start in the
terminal is the same session the browser attaches to — there is only ever one
runtime, so nothing is forwarded between two.

There is deliberately **no flag** for this. `serve.json` is discovery enough, and
a `--server URL` flag would invite pointing the CLI at a server that does not own
this project's locks. If a server is recorded but unreachable, the verb refuses
with `session_busy` rather than opening a bridge beside it — two agent runtimes
on one project would be two writers on one transcript. If no server is running,
nothing changes: the verb spawns its own sidecar exactly as it always has.

Two flags are unavailable in client mode and say so rather than being ignored:
`--session` and `--resume`. The owning server creates sessions; silently
dropping them would let you believe you had reopened a transcript you had not.

Provider configuration is explicit and app-owned. It is read from `--providers`,
else `$HEPHAESTUS_AGENT_PROVIDERS`, else `<project>/.heph/providers.json`
(client mode reads none of it — the server configured its sidecar when it
started):

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

Serve the project's tool surface over MCP. See [mcp.md](mcp.md) for client
configuration.

```console
$ heph serve --mcp                          # stdio: what a local MCP client launches
$ heph serve --mcp --http 127.0.0.1:8765    # streamable HTTP at /mcp
```

Serve mode is the executor policy boundary: builds run on a probed secure
backend and there is deliberately **no** `--unsafe-local-executor` flag on this
verb. Under `--mcp` on stdio, stdout is the transport — diagnostics go to
stderr, always.

### `heph serve --web`

Serve the **operator workspace** (`INTERFACE.md` §2) on loopback — optional
chrome, not the agent core. Orthogonal to `--mcp`: neither flag requires the
other, and both force the same serve-mode executor policy, so the web never
has an unsandboxed path either. MCP is not required to use this workspace.

```console
$ heph serve --web                                  # 127.0.0.1:8760
$ heph serve --web --web-address 127.0.0.1:9000
```

The command prints `http://127.0.0.1:PORT/#t=<token>` and, on a TTY, opens it.
The token rides in the URL **fragment**, never a query string, so it never
reaches an access log or a `Referer`; the browser moves it to `sessionStorage`
and sends `Authorization: Bearer …` on every request. There is no login, no
cookie, and no user model — the token is minted per serve into
`.heph/serve.token` (`0600`).

The serving process **owns the project's session leases** and records itself in
`.heph/serve.json` (`0600`). A second `heph serve --web` on the same project
refuses rather than racing, and `heph agent` reads that file to decide whether a
server already owns the project (see [client mode](#heph-agent) above).

If the project has a provider config, the server also starts **the one agent
runtime** and serves the session routes — `GET /events` (a WebSocket carrying the
normalized event stream), `GET /sessions`, `…/history`, `…/thread`, and the
session-control POSTs. Without one it still serves every read, mutation,
artifact and git route, and the session routes refuse by name with
`agent_unavailable`: a workspace with no model configured is a usable workspace,
not a failed serve.

The server also serves the **built web client** at `/`, with the API under
`/api/`, so the browser loads the app from the origin that answers its requests.
In a wheel that bundle is packaged; in a source checkout it is `web/dist`, which
`pnpm --dir web build` writes. With no bundle built the command says so on
stderr and serves the API alone — a workspace API without its client is still a
usable API, and Vite's dev server can proxy `/api` to it.

Loopback only, and deliberately: no TLS, no real authn, no multi-tenancy. This
is a local instrument, not a deployment.

---

## Evaluation verbs — the `bench` extra only

These appear when `hephaestus-bench` is installed. `uv sync --dev` includes
it. They are how the numbers in [leaderboard.md](leaderboard.md) are produced.

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
split            n   passes  pass_rate  wilson_lower_90  threshold  min_seeds
prose           36     25      0.694            0.5894       0.70       3
seeded          36     29      0.806            0.7085       -          3
interpretation_gap (seeded - prose): 0.111
gate: prose split only (the historical baseline)
…
```

Exit code 1 when the gate is not met — the transcript above is a real run that
did not meet it. (Its numbers are that run's; the column layout is the current
renderer's, which grew a `min_seeds` column and family rows with
`PARTS_STORE.md` G11C clause 12. **The two `min_seeds` values are the only
reconstructed cells** — they were derived from the recorded 36-run/12-task shape
rather than re-measured, because that archive has since grown and re-scoring the
directory today reports a larger, differently shaped run. Everything else is as
printed.)

**Corpus families.** A corpus *family* — currently just `component`, the Stage 11
component-bearing mechanism tasks — is its own split per spec
(`component-prose`, `component-seeded`), printed in the same table, carrying no
threshold, and **carved out of the gated prose number** so a growing corpus
cannot dilute the 0.70 bar it was baselined over. `score` also writes
`component_baseline.json` beside the result artifact: the family's *first*
measurement, never re-baselined, and never comparable to the v1/v2 baselines. A
first measurement below three distinct seeds per task is refused by name
(`insufficient_component_seeds`) and printed on stderr with nothing written,
because a thin first measurement would become the family's permanent reference
number.

An archive that ran **no** family task says so rather than saying nothing:

```console
component family: NOT MEASURED — no bearing-shaft, motor-plate runs in this
archive and no bench/results/<model>/component_baseline.json. PARTS_STORE.md
G11C clause 12's reference-model baseline is outstanding.
```

The line names both tasks and the file that would hold the answer, and it stops
once that file exists (the archive then reads "not measured in this archive;
baseline already recorded in …"). It is there because the family's *machinery*
is gated in CI while the family's *number* is a detached run: without the line,
a reader of a green gate matrix would reasonably infer a baseline that does not
exist.

The two split-scoring keys behave differently in the artifact on purpose:
`min_seeds_per_task` is written into `bench/results/<model>/<date>.json` for
family splits **only** — that is where its one reader, the ≥3-seed floor, looks
— so re-scoring an archive measured before Stage 11 reproduces its stored file
byte for byte. The table above prints the column for every split regardless; a
printed table is not archived evidence.

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

- **`heph export create`** (or any verb that *produces* an export). Producing an
  export is a *tool* surface — `export_part`, `generate_drawing`, `generate_doc`
  — reachable from the agent, over MCP and from the workspace's Export panel,
  and there is deliberately no fourth path to it: one write-ahead record, one set
  of confinement and pinning rules. What the CLI owns is the *retention* half,
  `heph export list` and `heph export unpin` — see their section above.
- **`heph export delete`.** `unpin` is reversible bookkeeping; a delete verb
  would make an irreversible removal a keystroke away from it, and the store's
  own collection pass already removes what is unreachable and past its horizon.

This section is kept rather than emptied, because a docs set that promises a verb
the binary does not have is worse than one that admits the gap. (`heph init` used
to be listed here; it shipped — see its section above. So did `heph export`,
which was listed here in full until its two retention verbs landed.)
