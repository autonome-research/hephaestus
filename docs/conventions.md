<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Project conventions

A Hephaestus project is an ordinary git repository. There is no database, no
opaque version badge, and no format you cannot read: parts are Python files,
constants are a Python file, checks are Python files, and the manifest is TOML.
`git log`, `git blame` and pull requests work because there is nothing special
to make them work on.

This page distills `script_contract.md` (the part-script contract) and the
project half of `repo_conventions.md`. Where it is shorter than they are, they
win.

## Layout

```
myproject/
  hephaestus.toml     project manifest: name, [params], [registries] pins
  globals.py          the project-shared namespace, read from parts as `hc`
  parts/
    shelf.py          one part, one script
    bracket.py
  checks/
    fit.py            cross-part checks (any part addressable)
  references/         operator-supplied datasheets/photos (heph reference add)
  imports/            STEP files a script may import_step(...)
  .heph/              build store, artifacts, session state — gitignore this
```

The one thing to get right in `.gitignore` is `.heph/`: it is the build store,
it is large, and it is fully reproducible from the scripts.

`heph init <dir>` scaffolds exactly this shape (see [cli.md](cli.md) for the
worked example), refusing a non-empty target. Creating the four files by hand
works just as well; `corpus/public_fixtures/assembly` is a working two-part
project to copy.

### `hephaestus.toml`

```toml
[project]
name = "assembly"
description = "Open-frame shelf with a corner bracket"

# Project-scope parameter overrides:
# [params]
# sheet_t = 9.0

# Written only by `heph registry pin` / `heph registry update`:
# [registries.skills]
# path = "vendor/acme-skills"
# digest = "sha256:01428f65…"
```

The `[registries]` table is machine-owned. Every other byte of the manifest is
preserved verbatim when a pin is written, and the result is re-parsed before the
write commits, so a pin can never leave the manifest unparseable. See
[registry-pinning.md](registry-pinning.md).

## Part scripts

One part, one script, under `parts/`. A script is executed statement by
statement in an injected namespace — it is not imported as a module and it does
not `import` anything.

```python
# parts/bracket.py
PARAMS = {
    "wing": Param(48.0, min=30.0, max=60.0),
}

_t = hc.sheet_t
_slot_w = hc.post_side + hc.joint_clear

base_pad = Pos(0, 0, _t / 2.0) * Box(p.wing, p.wing, _t)
wall = Pos(0, -p.wing / 2.0 + _t / 2.0, _t + 20.0) * Box(p.wing, _t, 40.0)
body = (base_pad + wall) - Pos(0, -p.wing / 2.0 + _t / 2.0, _t + 35.0) * Box(
    _slot_w, _t, 10.0
)

body.label = "bracket_body"
part.geometry = body

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (p.wing + 0.5, p.wing + 0.5, 46.5),
    "sealed": lambda m: m.sealed("part") and m.genus("part") == 0,
}

tag(body.faces().sort_by(Axis.X)[0], "frame_face")

part.description = "Corner bracket seating against the shelf frame"
part.process = "cnc_router"
part.feature("frame_face").surface_finish = "Deburr; registers against the frame"
```

### The injected namespace

All of build123d (`Box`, `extrude`, `fillet`, `Pos`, `Axis`, selectors, boolean
operators — Hephaestus does not wrap or rename it), plus `math`, `Param`/`p`,
`hc`, `part`, `tag`, `check`/`CHECKS`/`approx`, and `import_step`.

**And nothing else.** `open`, `__import__`, `exec`, the filesystem and the
network are absent; reaching for one is a build error, not a warning. This is
not a lint rule you can turn off — it is the sandbox, and it is why running a
model-authored script is a reasonable thing to do. `import_step("target.step")`
takes a string *literal* relative to `imports/`, and the executor resolves,
hashes and stages that file before the worker starts, precisely so that reading
a reference solid does not require giving the script file access.

### `PARAMS` — bounded knobs

```python
PARAMS = {"groove_count": Param(5, min=2, max=10)}
```

`Param(default, min=…, max=…, doc="", step=None)`. Read effective values as
`p.<name>`; a build request may override them (`heph build --param`, the
`set_params` tool, a client slider) and the executor validates every override
against the declared bounds, rejecting an out-of-range value with a build error
that names the parameter. `PARAMS` must appear before the first use of `p`. An
integer default declares an integer parameter; a float default declares a float.

An override supplied on the command line makes the build a **preview** — it does
not become the part's published current state. Persist a value by editing the
script or the manifest.

### `globals.py` and `hc` — how parts agree

`globals.py` holds the project-shared namespace; every part sees its public
names as `hc.<name>`, read-only. This is the mechanism by which mating parts
agree on interface dimensions — sheet thickness, mortise positions, joint
clearance — without either one copying a number out of the other.

It holds two kinds of name:

- **Project parameters** — its own `PARAMS` dict, the same bounded `Param` form.
  These are the design-wide tunables. Override them in `hephaestus.toml`
  `[params]`, with `heph build --global-param`, or via
  `set_params(scope="project")`.
- **Derived constants** — plain assignments computed from those params and
  `math`. Not independently tunable; they move when their inputs move.

`globals.py` runs under the same injected namespace minus `part`: it declares
values, not geometry.

The executor records which `hc` names each part reads. Editing `globals.py` or
changing a project parameter marks exactly the consuming parts dirty, and
`heph build --stale` rebuilds them — not everything, and not nothing.

A part **must not** shadow an `hc` name in its own `PARAMS`. `heph lint` refuses
it, so every tunable has exactly one home.

### `part` — the output object

`part.geometry` is required: one shape or a `Compound`. Child `.label` strings
become the names you see in the geometry tree; `.color` shows up in RGB renders.

Manufacturing metadata is a set of optional string fields — `part.description`,
`material_spec`, `process`, `stock_form`, `blank_size`, `general_tolerance`,
`finish`, `assembly_method`, `joint`. They are free text with one exception that
matters: a `part.process` matching a DFM registry pack (`laser_cut`,
`cnc_router`, `fdm`, …) makes that pack's rules runnable against the part.

### Tags — naming topology so you can measure it

```python
tag(outer_panel.faces().sort_by(Axis.Z)[-1], "tread_top")
part.feature("tread_top").surface_finish = "…"
```

A tag is the join key between geometry and everything that talks about
geometry: per-feature metadata, `measure`, selection, DFM findings, checks.

Tags are **recomputed by re-running the tagging selector on every build**, not
persisted by topological id. That avoids the classical topological-naming
failure mode (dangling references) but inherits its soft one: after an edit,
`.faces().sort_by(Axis.Z)[-1]` still resolves — possibly to a *different* face —
and resolution alone cannot detect the drift.

So the executor fingerprints every tagged topology and emits a
`tag_descriptor_changed` **warning** with the measured deltas when a face moves
more than 1.0 mm, rotates more than 5.0°, or changes area by more than 2% (and
the analogous bounds for edges and solids). It is a heuristic, stated as one: it
has false positives on intended edits and false negatives on a swap to a
symmetric neighbour, and it never claims identity changed. Write selectors that
survive editing — filter by normal and a position window rather than indexing
bare sort order — and put a `CHECK` on anything you actually depend on.

### `CHECKS` — geometry gets TDD

```python
CHECKS = {
    "splines_clear_panels": lambda m: m.interference("splines", "top_panel")
        == approx(0, abs=1e-6),
    "envelope": lambda m: m.bbox("part") <= (380.5, 280.5, 250.5),
    "manifold": lambda m: m.sealed("part") and m.genus("part") == 0,
    "under_mass_budget": lambda m: m.mass("part") <= 6.0e3,  # grams
}
```

Predicates over a measurement facade `m` bound to the built geometry. They run
on **every** build of the part and project-wide on `heph check`, their results
are part of the build artifact, and they surface in CI and in the agent's
context.

This is the difference that matters. A verification the agent performs in-loop
evaporates when the turn ends; a `CHECK` is an artifact with history, and it
will still be failing next month if someone breaks it.

A failing check does **not** abort the build — it fails the report. You get the
geometry and the measured value, which is what you need to fix it.

Cross-part checks live in `checks/*.py`, same shape, with a facade that can
address any part. `m.diff("part", "import:target.step").iou >= 0.995` compares
against another part or a staged STEP (`COMPARE.md`); the threshold belongs to
your predicate, because `m.diff` reports and never decides.

## Geometry addressing

One selector grammar everywhere a string names geometry — in `CHECKS`, in
`measure`, in `inspect_part(focus=…)`, in cross-part checks, in DFM findings.
`"part"` is the whole compound; labels and tags name what is inside it. The
resolution rules and their precedence are `script_contract.md` §7.

## Style

`heph lint` enforces `script_contract.md` §9 — style conventions, `hc` shadowing,
and (given `--request`) the `unsourced_requirement` rule from `VALIDATION.md` §2,
which flags a dimension in the script that nothing in the request asked for.

Two habits worth more than the rest:

- **Name what you measure.** Label geometry and tag topology *before* you need
  to assert on it. An unnamed face is one you cannot check.
- **Turn every number you argued about into a `CHECK`.** The clearance you had
  to think about is exactly the one that will silently break.
