# Your first part

> **Verified against** `16f9613` on 2026-09-12.
> Every command below was run start to finish in a scratch directory, and every
> output shown is the output that appeared. The artifact hashes are real and
> reproduced across runs.

By the end of this you will have built a real part, made a measurement, written a
check that proves something about the geometry, and seen the system refuse an
invalid request by name.

It takes about fifteen minutes. You need a working checkout — see
[install and run](../03-how-to/install-and-run.md) — and `bwrap` on your `PATH`.

## 1. Make a project

```console
$ heph init /tmp/gadget
initialized Hephaestus project 'gadget' at /tmp/gadget
  hephaestus.toml
  globals.py
  parts/example.py
  checks/project.py
  .gitignore
next: cd there and run `heph build example`

$ cd /tmp/gadget
```

Five files, and one hidden directory that appears on first use:

| Path | What it is |
| --- | --- |
| `hephaestus.toml` | the project manifest — just `name` to start with |
| `globals.py` | the shared `hc` namespace every part can read |
| `parts/example.py` | a part that builds with nothing edited |
| `checks/project.py` | a cross-part check stub |
| `.heph/` | the store: `state.db`, blobs, keys. Gitignored |

`heph init` refuses a non-empty directory and never overwrites.

## 2. Build it

```console
$ heph build example
example: ok (current) artifact=artifact:build:sha256:d266f257c390143eca85ca60eae63829a02cc0d3a3360daa3668e118132b69a5
```

That hash is the *content* of the built geometry. Run it again and you get the
same hash — that is the point of content addressing, and it is what lets a
measurement taken now be re-checked later against exactly the bytes it was taken
from.

It also ran in a bubblewrap sandbox with no network, no writable filesystem
outside one scratch directory, and a wall clock. If `bwrap` is missing you get a
refusal rather than an unsandboxed run:

```console
$ PATH=/no/bwrap heph build example --json
{"code": "sandbox_denied", "message": "sandbox_unavailable: secure sandbox probe failed: bwrap not on PATH", "status": "refused"}
```

## 3. Look at what it built

```console
$ heph part show example --json
```

Trimmed to the interesting parts:

```json
{
  "part": "example",
  "current": true,
  "artifact_ref": "artifact:build:sha256:d266f257…",
  "input_hashes": {
    "script": "sha256:14ee20b6…",
    "hc_dependencies": "sha256:44136fa3…",
    "part_params": "sha256:8a5b218c…",
    "effective_params": "sha256:d9f4c2f2…",
    "toolchain": "sha256:cdfb1aba…",
    "imports": {}
  },
  "metrics": {
    "solids": 1, "faces": 6, "edges": 12,
    "bbox_mm": [40.0, 20.0, 6.0],
    "volume_mm3": 4799.999999999999,
    "area_mm2": 2320.0,
    "sealed": true, "genus": 0
  },
  "geometries": [{"label": "example_plate", "solids": 1}],
  "stale": false, "stale_inputs": [],
  "checkpoints": [ … ]
}
```

Two things to notice.

**`input_hashes` is why staleness is a fact, not a guess.** Each is a hash of one
recorded input. `hc_dependencies` is the hash of *the `hc` names this part
actually read* — not all of `globals.py`, which would make every part stale
whenever anyone touched the shared namespace.

**`checkpoints` is one entry per top-level statement**, with its line, its
verbatim text, its span, and the names it bound:

```json
{"index": 1, "line": 10, "statement": "plate = Box(p.width, 20.0, 6.0)",
 "span": [10, 0, 10, 31], "bound": ["plate"], "shapes": ["plate"]}
```

The script is executed statement by statement, so when a build fails the system
knows exactly how far it got.

## 4. Make a preview

```console
$ heph params example --json
{"params": [{"name": "width", "default": 40.0, "min": 10.0, "max": 80.0,
             "value": 40.0, "scope": "part", "step": null, "doc": ""}],
 "part": "example", "status": "ok"}

$ heph build example --param width=50
example: ok (preview) artifact=artifact:build:sha256:11a5c13badda15ebad831ee3c1dc2f7343c4f180b76f46f5d4567ad2bce18b56
```

`preview`, not `current`. A build publishes as current only when it used the
project's own declared inputs. The preview is stored and addressable — you can
render it, measure it, compare it — but it does not become what the project says
this part *is*.

Ask for something outside the declared bounds and the answer is a refusal that
names every offender, with the source frame:

```console
$ heph build example --param width=500
example: FAILED — ParamOutOfBoundsError at line 1, col 0
  parameter(s) out of bounds: width=500.0 outside [10.0, 80.0]
  > 1 | PARAMS = {
  2 |     "width": Param(40.0, min=10.0, max=80.0),
  3 | }
  hint: no statement completed before the failure; fix the reported line and rebuild
$ echo $?
1
```

Nothing was applied. Exit code 1 means "it ran, and the answer was no".

## 5. Write a part of your own

Create it first, which gives you the hash you need to write to it:

```console
$ heph part create spacer --template blank --json
{"content_hash": "sha256:f4e48dca…", "path": "parts/spacer.py",
 "snapshot_ref": "artifact:part-snapshot:sha256:f4e48dca…", "status": "ok", …}
```

Put this in `parts/spacer.py`:

```python
PARAMS = {
    "thickness": Param(3.0, min=1.0, max=10.0),
}

body = Box(20.0, 20.0, p.thickness)
body.label = "spacer_body"
part.geometry = body

CHECKS = {
    "thickness_is_declared": lambda m: m.bbox("spacer_body")[2] == approx(p.thickness, abs=1e-6),
    "is_sealed": lambda m: m.sealed("spacer_body"),
}
```

Nothing is imported. `Box`, `Param`, `p`, `hc`, `part`, `tag`, `approx` and the
rest of build123d are already in scope — the injected namespace is the whole API
surface.

### Writes are compare-and-swap

```console
$ heph script write spacer --file parts/spacer.py \
      --expected-hash sha256:f4e48dca… --json
{"applied": true, "content_hash": "sha256:48efe686…", "path": "parts/spacer.py", …}
```

Pass a hash that is not the live one and **nothing is written**. You get a
discriminated result, not an error:

```console
$ heph script write spacer --file parts/spacer.py --expected-hash sha256:0000… --json
{"applied": false,
 "conflict": {"current_hash": "sha256:f4e48dca…",
              "current_script": "…the live content…",
              "current_snapshot_ref": "artifact:part-snapshot:sha256:f4e48dca…"}}
$ echo $?
0
```

Exit 0, because this is an *answer*: here is the live hash and the live content,
reconcile and try again. The agent's `write_part` and `edit_part` tools use
exactly this contract, because it is the same code.

## 6. Build it and read the checks

```console
$ heph build spacer
spacer: ok (current) artifact=artifact:build:sha256:6bcab5e73e548bb5dc5fbbede2c591abef06741a29322d407e2b5054d54d5998
  checks: 2/2 passed
```

```console
$ heph part show spacer --json | jq .checks
{
  "is_sealed":              {"pass": true, "measured": true},
  "thickness_is_declared":  {"pass": true, "measured": [20.0, 20.0, 3.0]}
}
```

**`measured` is the evidence, not a restatement of the verdict.** The check
recorded the actual bounding box it compared against. That is what makes a passing
check reviewable.

### What a broken check looks like

Get the facade wrong and you see the difference between *failed* and *could not
be measured*:

```console
$ heph part show spacer --json | jq .checks
{
  "thickness_is_declared": {
    "pass": false,
    "measured": {"error": {"type": "TypeError",
                           "message": "'Measurement' object is not callable"}}
  }
}
```

The error is recorded **inside `measured`**. The report layer badges this `error`,
never `fail` — a check that could not take its measurement has not disproved
anything, and it must not read as a pass either.

A failing or crashing check **never fails the build**. A build is a statement
about geometry; a check is a statement about whether that geometry satisfies a
requirement.

### The measurement facade

`m` is an object, not a function. The measurements available to a check:

| Call | Returns |
| --- | --- |
| `m.bbox(sel)` | the bounding box as a 3-tuple, mm |
| `m.volume(sel)` | mm³ |
| `m.mass(sel, density=None)` | mass; refuses `mass_density_unbound` with no density |
| `m.sealed(sel)` | whether the solid is closed |
| `m.genus(sel)` | topological genus |
| `m.distance(a, b)`, `m.clearance(a, b)`, `m.interference(a, b)` | between two addressed geometries |
| `m.diff(a, target)`, `m.scan_diff(…)` | comparisons |
| `m.at_pose(pose_id)`, `m.sweep(check_id)` | posed and swept measurement |

A selector is a label, a tag, a binding name, or a cross-part
`"<part>/<selector>"`. An addressing failure raises `addressing_error` **listing
the candidates** — it never guesses.

`approx` is a comparator, not a function call on two values:

```python
m.bbox("spacer_body")[2] == approx(p.thickness, abs=1e-6)
```

## 7. Project checks

`checks/project.py` holds checks that span parts. They run in a restricted
namespace — the measurement facade and `approx` only, no filesystem, no import,
no introspection.

```console
$ heph check --json
{"scope": "project", "project": "gadget", "check_set_generation": 0,
 "check_bundle_ref": "artifact:check-bundle:sha256:e72035b3…",
 "file_hashes": {"project.py": "sha256:60502851…"},
 "checks": {"project:placeholder": {"pass": true, "measured": null}}}
$ echo $?
0
```

Make one fail and the exit code changes:

```console
$ heph check
project:always_false: fail (measured: null)
$ echo $?
1
```

The check set is versioned: `check_set_generation` advances under a lease and a
write-ahead log, so a check set that changes mid-capture is caught rather than
silently mixed.

## 8. Render it

```console
$ heph render example
example: rendered 2 image(s) -> render
  iso [rgb] render/example_iso_rgb.png
  +X  [rgb] render/example_pX_rgb.png
  source_artifact_ref: artifact:build:sha256:d266f257…
```

The render names **the exact build artifact it rendered**. An image without that
line would be an image of something.

## 9. Use the shared namespace, and watch staleness

Put a shared value in `globals.py`:

```python
PARAMS = {
    "plate_thickness": Param(6.0, min=1.0, max=20.0),
}
```

and read it in `parts/example.py`:

```python
plate = Box(p.width, 20.0, hc.plate_thickness)
```

```console
$ heph build example
example: ok (current) artifact=artifact:build:sha256:d266f257…
```

The **same hash as before** — `hc.plate_thickness` is 6.0, and the literal was
6.0, so the geometry is identical. Content addressing does not care how you got
there.

Now change the shared value to `8.0` and rebuild only what it affected:

```console
$ heph build --stale
example: ok (current) artifact=artifact:build:sha256:bb878bf1ec285460313b28a6f60665fa585183f1597478e764a1a4a25e8482ba
```

`--stale` rebuilds every part whose current build no longer matches its live
inputs, including consumers of changed shared inputs and parts whose own script
changed. See [the CLI reference](../04-reference/cli.md#builds-previews-and-staleness).

## What you have seen

| Idea | Where it showed up |
| --- | --- |
| every result is content-addressed | identical hashes across runs and across two ways of writing the same thing |
| provenance is explicit | `source_artifact_ref`, `input_hashes`, `artifact_ref` |
| refusals are named, and nothing is applied | `sandbox_denied`, `ParamOutOfBoundsError` naming every offender |
| a conflict is an answer, not an error | `applied: false` with the live hash, exit 0 |
| evidence is recorded, not just the verdict | `measured` carrying the bounding box |
| could-not-measure is not failure | the error object inside `measured` |
| checks do not fail builds | `2/2 passed` printed beside a successful build |

## Next

- [Install and run](../03-how-to/install-and-run.md) — a proper setup.
- [The CLI reference](../04-reference/cli.md) — all 25 verbs.
- [What Hephaestus is](../01-orientation/what-hephaestus-is.md) — why it works this way.
