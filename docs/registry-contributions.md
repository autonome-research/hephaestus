<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Contributing registry content

Registries are the open half of Hephaestus: **skills** packs a model can load,
parametric **parts** generators, **materials** records, and per-process **DFM**
rule packs. Anyone can publish one, and a project consumes it by pinning it.

This guide is the contribution side. The format and publishing mechanics in
full are `registries/PUBLISHING.md`; the pinning rules are
`repo_conventions.md` §"Registry trust" and [registry-pinning.md](registry-pinning.md).
Read this first, then those.

## Before you write anything

Two rules govern all four kinds, and both come from `repo_conventions.md`.

**Never name a benchmark corpus task, and never reproduce one's target
geometry.** The naming half is grepped in CI; the geometry half is reviewed. A
skills pack that teaches the answer to `nest-gusset` does not make models better
at CAD, it makes the benchmark stop measuring — and everyone downstream loses
the only number they had.

**Contributions to org-hosted registries require review by a maintainer other
than the author.** Registry content is executed (parts generators, DFM
predicates) or fed to a model as reference (skills, materials). Neither is a
category where self-merge is appropriate.

Licensing: skills and documentation content are CC-BY-4.0; part generators and
DFM rules are Apache-2.0. State a `license` in `registry.toml` — publishing
checks that one is present.

## The shape of a registry

```
<registry>/
  registry.toml        # identity + the content index
  <content...>
```

```toml
[registry]
name = "acme-dfm"          # stable identity; a record carries it
kind = "dfm"               # skills | parts | materials | dfm
version = "1.2.0"          # bump whenever content changes
license = "Apache-2.0"
description = """
One paragraph. It reaches a model as reference material, not as instructions.
"""
```

then the kind's own index:

| kind | index table | content per entry |
|---|---|---|
| `skills` | `[[skills]]` — `name`, `file`, `summary` | one markdown page |
| `parts` | `[[parts]]` — `id`, `dir` | `part.json` + `generator.py` |
| `materials` | `[[materials]]` — `id`, `file` | one JSON record (numeric `density` required) |
| `dfm` | `[[packs]]` — `process`, `dir` | `pack.toml` + one predicate per rule |

Everything inside the tree is content and nothing outside it is. Dotfiles and
`__pycache__` are skipped, symlinks are not followed, and `registry.toml` is
hashed like any other file.

## Adding a DFM rule pack

A DFM registry holds one directory per manufacturing process. A pack declares
the parameters that characterise the process, and binds each rule to a predicate
that **measures geometry**.

```toml
# laser_cut/pack.toml
[pack]
process = "laser_cut"          # must match the [[packs]] entry
name = "Laser cutting (sheet)"
version = "0.1.0"
description = "What this pack knows and what it does not."

[params.kerf_mm]
value = 0.2
unit = "mm"
description = "Width of material the beam removes on a straight cut."

[[rules]]
id = "laser_cut.min_feature_vs_kerf"   # <process>.<name>, unique
title = "Cut features must be wider than the kerf can produce"
severity = "error"                     # error | warning | info
predicate = "min_feature_vs_kerf.py"
reads = ["kerf_mm", "min_feature_mm"]  # every name must exist in [params]
description = "What it measures and why the limit is where it is."
```

A rule sees **exactly** the parameters it lists in `reads`. Reading anything
else is a contract error at evaluation; naming a parameter the pack never
declared is a contract error at load. That is what makes re-tuning a pack for
your machine a data change (`[params]`) rather than a code change.

`rule_id`, `title` and `severity` are attached from the **declaration**, never
from the predicate, so a pack cannot understate its own severity at runtime.

### Predicates are sandboxed registry content

A predicate defines `evaluate(ctx)` and runs under the **same** OS sandbox and
the same injected namespace as a part script ([conventions.md](conventions.md)):
build123d, `math`, `approx`, restricted builtins, nothing else. `open`,
`__import__`, `exec`/`eval` and the filesystem are absent; attempting one raises
`sandbox_denied` and fails **that rule** — never the run, and never the build.
The `--unsafe-local-executor` backend refuses DFM jobs outright.

`ctx` gives you the part's facts (`ctx.params`, `ctx.metadata`, `ctx.material`,
`ctx.bbox()`, `ctx.sheet_thickness()`, `ctx.tag(name)`) and the geometry
enumerated so every measurement can be pointed at something:
`ctx.solids()`/`faces()`/`edges()`, `ctx.planar_faces()`, `ctx.cylinders()`,
`ctx.holes()`, `ctx.internal_rounds()`, `ctx.opposing_faces()`,
`ctx.overhangs()`.

```python
def evaluate(ctx):
    bound = max(ctx.param("min_feature_mm"), ctx.param("kerf_mm") * 3.0)
    for hole in ctx.holes():
        diameter = 2.0 * hole.radius
        if diameter < bound:
            ctx.report(
                f"bore of {diameter:.3f} mm is below the {bound:.3f} mm minimum",
                refs=[hole.ref],                    # -> topology descriptors
                measured={"diameter_mm": diameter}, # -> the evidence
                suggested_bound=bound,
            )
```

**Write rules that measure.** A rule that cannot measure its limit on the
geometry it is given should say so in its `description` rather than approximate
it silently. Findings are advisory engineering limits, not a certification: they
are the questions a shop would ask, made measurable.

## Adding a material

One JSON record per material, indexed by `[[materials]]`. A numeric `density` is
required — it is what turns `m.mass("part")` into a real number, and a mass
budget check is worthless if the density behind it was a guess.

Say where the numbers came from. A material record whose properties cite a
supplier datasheet is reference material; one whose properties are recalled is
a rumour with units on it.

## Adding a part generator

`part.json` plus `generator.py`, indexed by `[[parts]]`. Generators are
executable registry content under the same sandbox as DFM predicates and part
scripts. Prefer a generator parameterised over a standard (an M3 socket-head
screw across its length range) over one that emits a single frozen size.

## Adding a skill

One markdown page per skill, with a `summary` in the index that is honest about
scope — the summary is how a model decides whether to load the page at all.

Skills reach a model inside provenance delimiters and are **explicitly not
instructions**. Write them as reference material: "here is how fillet failures
usually present and what recovers them", not "you must always fillet last". A
page written as a command competes with the system prompt and loses in ways that
are hard to debug.

Teach selectors that survive edits — filter by normal and position window rather
than indexing bare sort order — because tags are recomputed on every build and a
brittle selector fails softly ([conventions.md](conventions.md)).

## Publish, pin, and hand it over

```console
$ heph registry publish acme-dfm --path ../acme-dfm --record acme-dfm.publication.json
acme-dfm: published sha256:6f1c…
  path:   /home/you/acme-dfm
  kind:   dfm v1.2.0
  leaves: 9
  content: packs=2, rules=6
  record: /home/you/proj/acme-dfm.publication.json
```

`publish` does four things and stops at the first failure: it **validates the
tree end to end** (every index entry resolves, every DFM rule binds to a
predicate file and every `reads` name to a declared parameter, every material
carries a numeric density), computes the Merkle digest, writes the pin, and
writes the publication record.

So `heph registry publish` **is your content validator**. Run it before you open
the PR; a tree that does not fully read is not published.

It refuses to *change* an existing pin — accepting new bytes stays one
deliberate `heph registry update`. Distribute the publication record beside the
tree: it carries the root digest *and* every leaf, so a consumer who sees a
mismatch is told which files moved rather than merely that the hash did.

## Checklist

- [ ] `version` bumped, `license` set, `description` written for a reader.
- [ ] `heph registry publish` exits 0.
- [ ] Every DFM rule has a stable `rule_id` you are willing to keep — ids appear
      in findings, in stored reports, and in other people's suppression lists.
- [ ] Predicates measure geometry and use only `ctx`; no rule reads a parameter
      it did not declare.
- [ ] Skills and materials read as reference material, not as instructions.
- [ ] Content is licensed for redistribution.
- [ ] Nothing names a bench corpus task or reproduces its target geometry.
- [ ] A maintainer other than you has reviewed it.
