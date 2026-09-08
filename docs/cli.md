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

**Startup is cheap, and that is a promise.** Building the parser registers every
verb, and no registration loads the CAD kernel, the mesh or raster stacks, the
solver's numerics, or the MCP and web servers — a verb reaches for what it needs
when it *runs*, not when it is listed. So `heph --help`, a `--help` on any verb and a
usage error all cost a Python start plus argparse (measured 2026-09-07: about
0.3 s on a 14-core Linux host), whatever else is installed. The promise is pinned as a module-name assertion rather than a clock,
in `tests/stage0a/test_cli_startup_budget.py`; the same file holds byte-identical
help goldens, because the cheap way to break the budget is a deferred import that
silently drops a flag.

---

Every verb, with one worked example each. The transcripts below were produced
against `corpus/public_fixtures/assembly` — the public clean-room fixture that
ships with the repository — so you can reproduce all of them:

```console
$ cp -r corpus/public_fixtures/assembly /tmp/demo && cd /tmp/demo
```

**What a fresh copy does and does not carry.** The fixture is sources: the
manifest, `globals.py`, the part scripts and the checks. Everything the *tool
surface* declares — joints, poses, motion checks, imports, references,
requirements — lives in the build store under `.heph/`, which is gitignored and
therefore not in the copy. So the verbs that read declarations print their empty
state on a fresh copy, and the populated transcripts further down assume you
have made those declarations first (through `heph agent`, or the equivalent
tool calls). The empty-state transcripts below are recorded against exactly this
fresh copy, so both halves are reproducible; which one you get depends on
whether you have declared anything yet.

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

An exit-1 refusal the verb actually *ran* to reach still carries its result
document on stdout (`{"part":"…","status":"already_exists"}`). An exit-2 usage
error has no result to report, so it goes to stderr and stdout stays empty.

**Refusals under `--json`.** One boundary maps every engine refusal
(`hephaestus/core/cli_errors.py`), so with `--json` requested a refusal is a
JSON object on **stderr** rather than a prose line — stdout stays reserved for
the result document and stays empty, so a caller never has to tell two shapes
apart on one stream:

```console
$ heph script write spacer --file spacer.py --expected-hash bogus --json; echo $?
{"code": "usage", "message": "--expected-hash must be 'sha256:<64 hex>' (got 'bogus')", "status": "refused"}
2
```

`status` is always `refused`; `code` is `usage` for misuse, otherwise the
engine's own code (`addressing_error`, `validation_error`, `sandbox_denied`, …).
An addressing refusal adds `candidates` — names you might have meant — unless
the name resolved and something *else* about it failed, when there is no
alternative to offer. A verb whose refusal has a bespoke JSON shape (`part
create`'s `already_exists`, a solve's document) keeps it; this is the fallback.

**`--json` listings** are objects, never bare arrays: one `status` and one
plural array key (`parts`, `imports`, `references`, `registries`, `findings`,
`goldens`, `exports`), so a wrapper can treat every list verb alike and a future
cursor has somewhere to live.

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
(exit 1) and nothing is written. A target that cannot be created at all — an
unwritable or missing parent — is refused with exit 2, and nothing is written
there either: the scaffold is staged in a sibling directory and moved into
place, so a half-written project is not a state `heph init` can leave behind.
The project name is the target directory's name; with no argument the current
(empty) directory is initialized.

Every other verb runs **inside** a project: it walks up from the working
directory (or from `--project DIR`, where a verb has one) looking for
`hephaestus.toml`, and refuses rather than guessing when there is none. A
Hephaestus clone is not a project, which is the usual way to meet this:

```
heph: no hephaestus.toml found at or above /home/you/hephaestus: a Hephaestus project is a
directory holding hephaestus.toml (plus globals.py, parts/ and checks/). Create one with
`heph init DIR`, then run from inside it (or pass `--project DIR` to `heph agent` /
`heph serve --web`)
```

Every verb answers this one condition identically — exit **2**, that message,
and under `--json` the object `{"status":"refused","code":"usage","message":"…"}`
— because they all resolve the root through one helper. The fix is in the
message: `heph init DIR`, then `cd` there — or point `--project` at a project
you already have.

### `heph part list` / `heph part create` / `heph part show`

The agent-shaped part verbs. Listing and showing compute nothing; creating
writes through the same `create_part` store contract the tool surface uses
(`base_hash=None`, refuse without mutation if the file exists).

```console
$ heph part list
bracket	parts/bracket.py	sha256:…
primary	parts/primary.py	sha256:…

$ heph part create spacer --template blank --json
{"content_hash":"sha256:f4e48dcac5f8e945d73b6c254b2217447c60db609031e6c3bc59b490d56b65b1","initial_script":"# Scaffolded by `heph part create --template blank`. Edit or replace it.\n#\n# Nothing is brought in from elsewhere: build123d, math, Param, p, hc, part and\n# tag are already in scope — the injected namespace is the whole API surface\n# (script contract §2). Declare tunables in PARAMS and read them back as\n# `p.<name>`; publish by assigning to `part.geometry` (§5).\nPARAMS = {}\n\npart.geometry = Box(10.0, 10.0, 10.0)\n\n# `heph lint` asks for these two (§5.2); fill them in when the shape is real.\n# part.description = \"\"\n# part.process = \"\"\n","path":"parts/spacer.py","replayed":false,"snapshot_ref":"artifact:part-snapshot:sha256:f4e48dcac5f8e945d73b6c254b2217447c60db609031e6c3bc59b490d56b65b1","status":"ok"}

$ heph part create spacer --json
{"part":"spacer","status":"already_exists"}

$ heph build spacer
spacer: ok (current) artifact=artifact:build:sha256:1f0a7b7fc496088fab…
```

**Every template builds unmodified.** `blank`, `solid`, `sheet` and
`from_store` are written against the part-script contract — no imports (§1:
build123d is pre-injected, and `__import__` is absent, so an import line is a
build error), and geometry published by assigning to `part.geometry` (§5)
rather than by shadowing that handle with a `BuildPart()` context.
`core/tests/test_cli_authoring.py::test_every_template_builds` runs
`create` + `build` for each name, so a scaffold that does not build is a test
failure rather than a first-run surprise.

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

Build a part and publish the result. There are exactly two entry paths: a named
target, and `--stale`, which rebuilds every part the projection marks stale.
**There is no build-everything form** — a bare `heph build` is a usage refusal,
because an accidental bare invocation in a large project is expensive.

```console
$ heph build primary
primary: ok (current) artifact=artifact:build:sha256:8be53e4b2d66a336…
  checks: 4/4 passed
```

`--stale` is what rebuilds more than one part:

```console
$ heph build --stale
```

```console
$ heph build
heph: build: a part name or script path is required (or --stale)
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

The badge vocabulary is the four values `INTERFACE.md` §6.3 fixes — `pass`,
`fail`, `error`, `not_run` — and the CLI prints the same classifier the HTTP
route and the web badges use. A check that could not be *evaluated* is `error`,
never `FAIL`: it has no verdict to report, and it prints the reason rather than
the raw measured envelope.

```console
$ heph check
fit:bracket_clears_frame: pass (measured: 0.0)
fit:raises: error — addressing_error: part 'nosuch' does not exist under parts/
```

Exit code 1 whenever anything is not `pass` — an unevaluated check is not a
green run.

`--snapshot` requires and records a coherent project snapshot (every part built
from the same globals) rather than checking against whatever is lying around.
It was spelled `--project` (still accepted), which collided with the
`--project DIR` of `heph agent` and `heph serve --web`; this verb's flag takes
no value. `--json` emits the `CheckReport`.

### `heph lint PATH`

Lint a part script against the `script_contract.md` §9 style rules and the `hc`
shadowing rules.

```console
$ heph lint parts/bracket.py
parts/bracket.py: clean
```

`--requirements FILE` and `--request FILE` turn on the requirement-ledger rules
from `VALIDATION.md` §2. **They are required together**: `unsourced_requirement`
is a join between the ledger's entries and the original request text, so
`--request` alone has one operand and is refused with exit 2 rather than
reporting "clean" about a rule that never ran.

```console
$ heph lint parts/bracket.py --requirements ledger.json --request .heph/request.txt
parts/bracket.py:12:5: error unsourced_requirement: 4.5 mm is not supported by the request [wall]
```

`--request` is a path to the original request text (the file `heph prompt`
writes is `.heph/request.txt`). Given both, `lint` flags an
`unsourced_requirement` — a dimension in the script that nothing in the request
asked for. That is the rule that catches a model inventing a spec.
`--json` emits `{"status": "ok"|"error", "findings": [...]}`.

`lint` takes exactly one part script. A directory is refused as a directory,
not as a missing file.

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
| `--explode T` | Explode factor: any finite value `>= 0`. `0` is assembled and `1` is the reference exploded view; values above `1` exaggerate it further and are accepted. |
| `--focus LABEL_OR_TAG` | Centre and zoom on a labelled solid or a tag. |
| `--last-good` | Render the last-good checkpoint of the most recent **failed** build. |
| `--artifact-ref REF` | Render an explicit immutable build/checkpoint artifact. |
| `--out DIR`, `--json` | Output directory; render metadata as JSON. |

Every render records the artifact it came from. A picture that cannot name its
build is not evidence.

`--out` is validated before the first view is rendered: a directory that cannot
be created or written is refused with exit 2, naming the flag, rather than
discovered after every image already exists in memory. The default `render/` is
created if absent, as it always has been. The same precondition covers
`heph render --pose`.

### `heph goldens`

Verify the golden render corpus, or regenerate it.

```console
$ heph goldens
assembly_primary_rgb_iso_rgb: ok
assembly_primary_rgb_pX_rgb: ok
…

$ heph goldens --update
```

With no flag the verb **verifies**: for every declared golden it checks that the
committed PNG hashes to what the sidecar records, that the sidecar was written
by this `goldens.py`, and that the GL renderer matches. Exit 1 on drift, naming
the drifted golden; exit 0 otherwise. `renderer_mismatch` is reported but does
not fail — the corpus is pinned to the render container's rasterizer, so a
different `GL_RENDERER` says *this machine* cannot re-render those bytes, not
that the committed bytes are wrong. `--json` emits
`{"status": …, "goldens": [...]}`.

`--update` **refuses on a dirty tree**, by design: a golden regenerated alongside
uncommitted changes cannot be attributed to anything. Goldens carry provenance
(script hash + renderer version), and `verification.md` makes this the only
sanctioned path to change them. `--dir DIR` points at a different golden
directory (default `tests/render/goldens`).

The golden corpus is repository content: the clean-room fixtures live in the
Hephaestus checkout under `corpus/public_fixtures`, so this verb runs **there**,
not in a design project. Outside a checkout it is refused by name with exit 2 —
a capability that cannot work here, not a run that answered "no".
`--fixtures-dir DIR` points it at another corpus of the same shape, which is how
a fork regenerates goldens for its own fixtures. Note that the two roots are
independent: `--fixtures-dir` moves the corpus, never the tree whose
cleanliness is checked.

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
inspect is exactly what a build would admit, refusals included. Admit the
file first with `heph import add` (`--part` seeds the Stage 12 script);
`heph scan` does not copy, drop, or reconstruct.

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
no joints or poses declared
```

Joints and poses are **declared by the agent**, through the `declare_joint` /
`declare_pose` tools — there is no per-script joint syntax and no solver **in
this surface**: `heph solve` (Stage 13, `SOLVER.md`) proposes and writes
nothing; scripts position geometry, poses exist only inside an evaluation
(`KINEMATICS.md` §1). `--json` emits the machine form.

### `heph motion` / `heph motion check`

Show the motion status, the latest sweep results (worst-sample parameter
values and measured value for every check), and the coupling table; `check`
re-evaluates now against current builds — pass ids to re-evaluate a subset.

```console
$ heph motion
no motion checks declared, motion state never evaluated
$ heph motion check
joints 0 resolved, 0 unresolvable; poses 0 resolved, 0 unresolvable
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
`waterjet` is refused by name. `--out` is validated before the kerf, nesting
and DXF work runs — an unwritable path is exit 2 naming the flag, not a
`PermissionError` thrown after the whole program has been computed and
discarded.

### `heph solve pose`

Solve declared free joint parameters for declared targets — a constraint id, a
point an anchor must reach, or both — and print the solve record: the verdict,
every returned assignment, and the residuals an independent process re-measured
(`SOLVER.md` §2A).

```console
$ heph solve pose --constraint c-align --joint j-elbow \
    --tol 1e-4 --weighting unit_scaled_v1 \
    --regularization min_norm_from_start --requirement R-7
verdict: pose_converged_at_tolerance
every objective constraint re-measures satisfied through the ordinary engine
path, every residual is inside the declared tolerance, and the Jacobian has
full column rank at the solution. Evidence about this iterate from this start;
it claims nothing about uniqueness beyond the local basin
  [0] from as_built: j-elbow=30
  c-align (parallel): satisfied, measured 8.5e-07 deg

nothing was written: applying this is an authoring act (declare_pose)
```

**The solver proposes; nothing applies it.** There is no `--apply`, no
`--declare-pose` and no `--write`: this verb creates no artifact, declares no
pose, advances no generation and republishes nothing. Turning a solved
assignment into project state is an explicit authoring act through
`declare_pose`, so it arrives in git as a diff a reviewer can read. **Writeback
is refused**: no inverse from a solved value to a script expression is
computed, offered or guessed.

`--weighting` and `--regularization` are required and echoed, never defaulted —
a residual vector mixing mm and deg has no canonical norm, and which member of
a positive-dimensional solution set comes back is a design decision. Provenance
is compulsory (`--requirement ID`, or `--assumed --reason TEXT`). Repeat
`--start ID=JOINT:VALUE,...` to declare more starts; there are no random
restarts, and two starts that converge apart return
`multiple_poses_from_starts` with **both** answers and neither chosen. A start
spec needs both its separators: `--start nonsense` is a refusal, not a second
`as_built` start under a name nobody declared.

Exit 0 only for `pose_found` and `pose_converged_at_tolerance`; 1 for every
other verdict — an under-determined answer and a multiplicity are facts to
read, not passes — and for a named refusal (`iteration_ceiling`,
`solver_timeout`, `verification_process_died`, `rank_undecidable`, `solver_residual_disagreement`), which is
never printed as a verdict because a refused solve decided nothing. `--json`
emits the machine form.

### `heph solve placement`

Propose a rigid transform per declared free part, so that declared constraints
would measure satisfied, and record it as an immutable proposal artifact
(`SOLVER.md` §2B).

```console
$ heph solve placement --constraint c-seat --constraint c-bore \
    --constraint c-face --free lug --tol 1e-4 \
    --weighting unit_scaled_v1 --regularization min_norm_from_start \
    --requirement R-7
verdict: converged_at_tolerance
every objective constraint re-measures satisfied through the ordinary engine
path, every residual is inside the declared tolerance, and the Jacobian has
full column rank at the solution. Evidence about this iterate from this start;
it claims nothing about uniqueness beyond the local basin
proposal: p-3f21c8b4d0e7 (artifact:placement-proposal:sha256:3f21c8b4…)
  [0] from as_built:
      lug: move (+10, +10, -30) mm, turn 0 deg about [0, 0, 1]
  c-seat (coincident): satisfied, measured 1.04e-05 mm
  c-bore (concentric): satisfied, measured 6.67e-06 mm
  (not an objective term) c-clear (no_interference): violated

nothing was applied: this is a measurement. Authoring the edit
(edit_part / set_params) is how a placement becomes geometry
```

**The solver proposes; nothing applies it.** There is no `--apply`, no
`--write` and no `--accept`: this verb writes exactly one thing, an immutable
proposal document, and that document is a *measurement*. No script is edited,
no parameter set, no artifact republished, no build made current, and the
constraint's own `AssemblyStatus` row keeps saying `violated` until a rebuilt
script measures otherwise. **Writeback is refused**: there is no inverse from a
transform to a script expression — the +10 mm above can be authored as an `hc`
name, a `Param`, a literal or a new expression, three of which change other
parts — so none is computed, offered or guessed.

Every part the named constraints anchor that is not `--free` is **ground**, and
at least one must be. A part that rides a declared joint may not be free (its
placement is forward kinematics'; solve it with `heph solve pose`), and a
pose-bound constraint is not an objective term here. Kinds whose residual
carries no gradient in this space are refused **by name with their reason** —
`no_interference` and `clearance_min` are flat plateaus, `distance` is a kernel
extremum, `fit` is pose-invariant — and are nevertheless *evaluated* at the
returned solution and reported, which is why the example above shows an
interference beside four satisfied mates.

`--bound VAR=MIN:MAX` bounds one free variable (`<part>.tx|ty|tz|rx|ry|rz`);
transform space is otherwise unbounded, and a bound is never clamped in
silence — a variable that reaches one comes back in the record's active list.
Both separators are required: `MIN` or `MAX` may be empty for a half-open
window, but `--bound bogus` is a refusal, not an unbounded window on a variable
nobody declared, and a `--bound` naming a variable outside the `--free` set is
refused by name.

**Argument-shape errors are reported before the project is opened**, and all of
them at once: provenance, weighting, a non-empty `--constraint`/`--free`, the
bounds and the starts are all checked ahead of the solve request, so several bad
flags produce one refusal listing every one of them rather than a full solve
setup per mistake. "Every one" includes several bad specs of the *same*
repeatable flag — three malformed `--bound`s are three lines of one refusal, not
three runs. The same ordering holds for `heph solve pose` and
`heph solve params`.

Exit 0 only for `converged_at_tolerance`; 1 for every other verdict and for
every named refusal.

### `heph solve params`

Propose a value per declared free `Param`, so that declared constraints would
measure satisfied, and record it as an immutable proposal artifact
(`SOLVER.md` §2C).

```console
$ heph solve params --constraint shelf_seats --constraint shelf_stands \
    --free hc.shelf_z --free post.post_h --tol 1e-3 \
    --weighting unit_scaled_v1 --regularization min_norm_from_start \
    --requirement R-4
verdict: converged_at_tolerance
every objective constraint re-measures satisfied through the ordinary engine
path, every residual is inside the declared tolerance, and the Jacobian has
full column rank at the solution. Evidence about this iterate from this start;
it claims nothing about uniqueness beyond the local basin
proposal: p-9c04ab71fe32 (artifact:placement-proposal:sha256:9c04ab71…)
  [0] from as_built:
      hc.shelf_z = 40.0000  [declared 0 .. 60]
      post.post_h = 40.0000  [declared 5 .. 60]
  shelf_seats (coincident): satisfied, measured 2.5e-05 mm
  shelf_stands (distance): satisfied, measured 46.0000 mm
  nonsmooth terms: shelf_stands
  (a `distance` term is a LOCAL model - SOLVER.md §3.2)
  preview builds issued: 25 (none of them current, none persisted)

nothing was applied: this is a measurement. Authoring the change
(set_params / edit_part) is how a proposed value becomes geometry
```

A free variable is spelled the way a script already reads it: `<part>.<param>`
for a part's own `PARAMS`, `hc.<param>` for `globals.py`'s. A name that is not
a declared `Param` is refused `unknown_param`; a `globals.py` **derived
constant** — a real `hc` name with no `min`/`max` — is refused
`unbounded_param` rather than given an invented range.

**Every candidate is a preview build**, which is how a candidate is evaluated
at all, and a preview is never current and never persists an override: the
project's geometry and parameters are exactly where they were when the verb
started. That also makes this the one solve verb that spends kernel time per
iterate, so `--build-budget N` caps the iteration's total preview builds;
exhausting it is a named refusal carrying the best iterate and its verified
residuals, never a verdict.

`fit` and `distance` are objective terms here and nowhere else — a `Param`
change moves both, where a rigid motion moves neither smoothly — and a
`distance` term is reported in `nonsmooth_terms` with the local-model caveat,
because a descent over a function with a kink in it is valid in a
neighbourhood and claims nothing beyond one. A constraint no free parameter
moves, and that does not already hold, is `unresolvable(no_free_variable_affects)`
naming that constraint: parameter space can only reach placements the author
parameterised, and that limitation is reported rather than routed around.

**Nothing applies it, here either.** There is no `--apply` and no `--set`:
turning a proposed value into project state is an authoring act through
`set_params` or an edit to the declaration, and which of those the author
meant is not this verb's to guess.

### `heph proposals`

List recorded placement proposals with their read-time staleness — withdrawn
ones included, with their reasons.

```console
$ heph proposals
generation: 2
  p-3f21c8b4d0e7  converged_at_tolerance  transform  parts: lug
  p-9c04ab117e52  underdetermined_at_tolerance  transform  parts: lug  [stale (base)]
```

Reading never measures and never re-solves. `stale` is a **fact, not a
refusal**: a proposal that was valid when written and whose bound artifact refs
have since moved stays readable, and the changed parts are named so a reader
knows what to re-run. `--json` emits the machine form.

### `heph registry {list,publish,pin,update,verify}`

See [registry-pinning.md](registry-pinning.md) — it is a topic, not a flag list.

```console
$ heph registry list
dfm: unpinned (dfm)
  pin:    bundled:dfm
  path:   /home/you/hephaestus/registries/dfm
  digest: sha256:891ca6c88c661a8f…
…
```

`pin:` is what `hephaestus.toml` carries; `path:` is where those bytes are on
*this* machine. The registries shipped with an installation are pinned as
`bundled:<kind>` and resolved per machine at read time, because
`hephaestus.toml` is committed and an absolute path into one developer's clone
makes the project unusable everywhere else. The digest still pins the bytes: a
machine whose installation ships different ones fails `heph registry verify` by
design. `heph registry pin NAME` refuses to persist an absolute path outside the
project unless you named it with `--path DIR`; an installation that ships no
bundled registries refuses a `bundled:` pin by name, naming `--path DIR` as the
remedy. `--json` on `list`, `update` and `verify` emits
`{"status": …, "registries": [...]}`.

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
filename). The kind and mime type come from the *source file's* extension, so
`--name` may be any plain filename — `--name bearing-datasheet`, with no
suffix, is the documented form and registers the PDF as a document. An
unsupported **source** extension is still refused whatever `--name` says. The
original is untouched and the project stays self-contained. `remove`
deregisters and deletes the copy. `--json` emits the registry entry; `list
--json` emits `{"status": "ok", "references": [...]}`.

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
{"kind":"step","name":"vendor_plate.step","path":"imports/vendor_plate.step","recorded":true,"sha256":"sha256:…","units":null}

$ heph import add ~/Downloads/limb-l.stl --units mm --part socket
copied limb-l.stl (mesh, units=mm) sha256:… -> imports/limb-l.stl
created parts/socket.py
scan-to-part: heph build socket; heph scan check socket limb-l.stl --units mm (Stage 12; no reconstruction)
```

STEP (`.step` / `.stp`, AP203/AP214) takes no `--units`. STL, PLY, OBJ, OFF
and XYZ **require** `--units {mm,cm,m,in}` — those formats carry none, and a
unit is never inferred. An unknown suffix is a named refusal. The original
file is untouched; the copy under `imports/` is a regular file (no symlink
escape). `--part NAME` writes `part.geometry = import_step("copied-name")` for
STEP, or `import_mesh` plus `mesh_to_solid` with the declared unit for a mesh,
and refuses `already_exists` without force if the part is already there.
`--json` on `add` emits `{name, kind: step|mesh|points, sha256, path, units,
recorded}`; `list --json` emits `{"status": "ok", "imports": [...]}` of the same
rows.

**The declared unit is recorded with the admission.** `--units` is compulsory on
a mesh precisely because the file carries none (`MESH_INGEST.md`), so discarding
it after the copy would make it unrecoverable; `heph import add` writes a
`{name, kind, sha256, units}` admission into project state and `heph import list`
reports it. A file copied into `imports/` by hand is still listed — with
`units: null` and `recorded: false`, rather than hidden.

Re-admitting a name has three outcomes. Identical bytes under an identical unit
is an idempotent success naming the prior admission. The same name with
different bytes is refused `import_bytes_conflict`; with a different unit,
`import_unit_conflict` — both naming the two declarations, and neither touching
`imports/`. `--redeclare` is the explicit escape: it replaces the admission and,
when the bytes changed, marks the importing parts stale.

Scan-to-part is this verb plus Stage 12: `heph import add scan.stl --units mm
--part socket`, then `heph build socket`, then `heph scan` / `heph scan check
socket scan.stl --units mm`. A point cloud with `--part` is
`point_cloud_has_no_solid`. `mesh_to_solid` may refuse `mesh_solid_invalid` —
most real scans do (`MESH_INGEST.md` §4.3). Poisson, ICP, feature recognition,
and viewport STL drop are not in this path.

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
geometry kernel. The filter is validated against the project's parts first: a
name that does not exist is the same addressing refusal `heph part show` gives —
exit 2, with candidates — not "no exports recorded", which is what a real part
with no exports says. A typo must not read as a clean answer. `--json` emits
`{"status": "ok", "part": …, "exports": [...]}`.

The `pin` column has three values and they are three different
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
| `--unsafe-local-executor` | Run the build worker with **no OS sandboxing**. Local debugging only; refused for registry content. |

**Executor posture: sandboxed by default, like `heph build`.** The scripts this
verb builds are written by a *model*, so it takes the same posture the engine's
own build verb has taken since Stage 0. With no flag, the verb probes bubblewrap
before it starts anything and refuses by name if the probe fails:

```console
$ heph agent
heph: sandbox_unavailable: secure sandbox probe failed: bwrap not found on PATH
heph: install bubblewrap (bwrap) to run the agent sandboxed, or pass
      --unsafe-local-executor to run model-authored scripts WITHOUT OS sandboxing
      (see docs/install.md)
```

That is a **change**: before, `heph agent` ran model-authored scripts as ordinary
child processes with your environment and filesystem view, with no flag and no
way to ask for anything else. If bubblewrap is not available to you, pass
`--unsafe-local-executor` deliberately; it prints a warning on every build and
still refuses to execute registry content (parts-store generators and DFM rule
packs), which may only ever run under a probed sandbox. With the flag,
`instance_store_part` therefore reports `capability_not_available` rather than
running a generator unsandboxed — the same answer the tool gives on a host with
no sandbox at all.

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

`--unsafe-local-executor` is also inert in client mode, and quietly so, because
it can only ever make the posture *safer* than you asked for: the builds run in
the server's process, and `heph serve` refuses the unsafe backend outright. The
flag never widens what a server does.

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
local/self-hosted lane), `local` (endpoint only), or `pi_native` to use Pi's
own model catalog. The `pi_native` lane is how an existing Codex/Pi login
becomes a model here, and it carries no credential of its own — an id, its
models, and `auth_source`:

```json
{
  "providers": [
    {
      "id": "openai-codex",
      "kind": "pi_native",
      "models": [{"id": "gpt-5.6-sol"}]
    }
  ],
  "credential_allowlist": [],
  "auth_source": "/home/you/.pi/agent/auth.json"
}
```

`id` is the catalog provider's own id, and `models[].id` must be an id that
provider publishes — for `openai-codex` those are `gpt-5.3-codex-spark`,
`gpt-5.4`, `gpt-5.4-mini`, `gpt-5.5`, `gpt-5.6-luna`, `gpt-5.6-sol` and
`gpt-5.6-terra`. `credential_allowlist` stays empty: this lane reads no
environment variable, so naming one would only widen what the sidecar can see.

`auth_source` is an absolute path to an **existing** Pi `auth.json` and is
required by `pi_native` alone. The supervisor **symlinks** it into the
project's agent directory — never copies it. That is not a convenience: OAuth
records rotate, and a copy would either go stale or refresh independently and
revoke your own Codex login out from under you. One file, one rotation, two
readers. An existing real `auth.json` in the agent directory is never clobbered;
only Pi's empty placeholder is replaced, and anything else refuses by name.
Without `auth_source`, nothing outside the project is visible to the sidecar.

`heph serve --web` reports what it made of all this at `GET /api/v1/providers`:
`auth_source` and `auth_source_linked` (is the symlink in place), `file_mode`
and `file_mode_private`, and each provider's `available` with its
`unavailable_reason`. No credential material crosses that boundary — the report
is the fastest way to find out why a configured model is not offered. Write the
file `0600`; the report says so when it is wider.

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

This transport resolves the project from the working directory, per request, so
run it from inside one. `--project` belongs to `--web` and is refused by name
here (exit 2) rather than accepted and ignored.

### `heph serve --web`

Serve the **operator workspace** (`INTERFACE.md` §2) on loopback — optional
chrome, not the agent core. Orthogonal to `--mcp`: neither flag requires the
other, and both force the same serve-mode executor policy, so the web never
has an unsandboxed path either. MCP is not required to use this workspace.

```console
$ heph serve --web                                  # 127.0.0.1:8760
$ heph serve --web --web-address 127.0.0.1:9000
$ heph serve --web --project ~/designs/bracket      # from any directory
```

| Flag | Effect |
|---|---|
| `--web` | Serve the operator workspace. |
| `--web-address HOST:PORT` | Bind address, loopback only (default `127.0.0.1:8760`). |
| `--project DIR` | Where the search for the project starts (default: cwd). |

`--project DIR` resolves exactly as it does for [`heph agent`](#heph-agent) —
through the same helper, not through two implementations that agree by
convention: the nearest ancestor of `DIR` holding `hephaestus.toml` is the
project served, so `--project parts/` and `--project .` name the same one. It
exists so the workspace can be started without a `cd`, and everything the serve
derives moves with it — `.heph/serve.token`, `.heph/serve.json`, the provider
config, and the agent runtime's working directory. Because both verbs resolve a
directory the same way, `heph agent --project DIR` finds the `serve.json` that
`heph serve --web --project DIR` wrote and runs in client mode against it. The
resolve happens before the server starts, so a `DIR` that is not inside a
project is refused with exit 2 and the same one-line message `heph agent
--project DIR` prints, and a `DIR` that is not a directory at all is refused
one step earlier still. The flag applies to `--web` only: passing it with
`--mcp` is a usage error (exit 2) rather than a silently ignored flag, because
the MCP transport resolves the project per request from the working directory.

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
`pnpm build` in `web/` writes. That lookup is relative to the installation, not
to the project, so it does not move with `--project`. With no bundle built the
command says so on stderr and serves the API alone — a workspace API without its
client is still a usable API, and Vite's dev server can proxy `/api` to it.

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
