# Publishing a Hephaestus registry

A registry is a versioned directory of content that a Hephaestus project pins
**by a Merkle digest over the whole tree**. Publishing is the producer half of
that contract: you validate the tree end to end, state its digest, and hand
consumers something they can check. Consuming is the other half: a tree whose
bytes no longer hash to the pin refuses to load at all.

This guide is about the mechanics. What the four registry kinds *are* is
`architecture.md` §3.6; the trust model behind them is §7.2.

## 1. The format

Every kind shares one shape:

```
<registry>/
  registry.toml        # identity + the content index
  <content...>
```

```toml
[registry]
name = "acme-dfm"          # required, stable; the identity a record carries
kind = "dfm"               # skills | parts | materials | dfm
version = "1.2.0"          # required; bump when content changes
license = "Apache-2.0"     # state one — publishing checks it is present
description = """
One paragraph. It reaches a model as reference material, not as instructions.
"""
```

Then the kind's own index:

| kind | index table | content per entry |
| --- | --- | --- |
| `skills` | `[[skills]]` `name`, `file`, `summary` | one markdown page |
| `parts` | `[[parts]]` `id`, `dir` | `part.json` + `generator.py` |
| `materials` | `[[materials]]` `id`, `file` | one JSON record (numeric `density` required) |
| `dfm` | `[[packs]]` `process`, `dir` | `pack.toml` + one predicate per rule |

Nothing outside the tree is content, and everything inside it is: dotfiles and
`__pycache__` are skipped, symlinks are not followed, and `registry.toml` is
hashed like any other file, so editing the manifest changes the digest too.

## 2. DFM rule packs specifically

A `dfm` registry holds one directory per manufacturing process:

```toml
# laser_cut/pack.toml
[pack]
process = "laser_cut"          # must match the [[packs]] entry
name = "Laser cutting (sheet)"
version = "0.1.0"
description = "What this pack knows and what it does not."

[params.kerf_mm]               # a bare number is also accepted
value = 0.2
unit = "mm"
description = "Width of material the beam removes on a straight cut."

[[rules]]
id = "laser_cut.min_feature_vs_kerf"   # must be <process>.<name>, unique
title = "Cut features must be wider than the kerf can produce"
severity = "error"                     # error | warning | info
predicate = "min_feature_vs_kerf.py"
reads = ["kerf_mm", "min_feature_mm"]  # every name must exist in [params]
description = "What it measures and why the limit is where it is."
```

A rule sees **exactly** the parameters it lists in `reads` — reading anything
else is a contract error at evaluation, and naming a parameter the pack never
declared is a contract error at load. Re-tuning a pack for your machine is a
data change (`[params]`), not a code change.

### Predicates are sandboxed registry content

A predicate is a Python module that defines `evaluate(ctx)`. It runs under the
**same** OS sandbox and the same injected namespace as a part script
(`script_contract.md` §2) — `build123d`, `math`, `approx`, restricted builtins,
and nothing else. `open`, `__import__`, `exec`/`eval` and the filesystem are
absent; attempting one raises `sandbox_denied` and fails that rule (never the
run, and never the build). The `--unsafe-local-executor` backend refuses DFM
jobs outright, exactly as it refuses parts-store generators.

`ctx` is the evaluation context. It offers the part's facts —
`ctx.params`/`ctx.param(name)`, `ctx.metadata` (§5.2 fields), `ctx.material`
(the resolved materials-registry record, or `None`), `ctx.bbox()`,
`ctx.sheet_thickness()`, `ctx.tag_names()`/`ctx.tag(name)` — and the geometry,
enumerated so every measurement can be pointed at:

| primitive | gives you |
| --- | --- |
| `ctx.solids()`, `ctx.faces()`, `ctx.edges()` | handles in artifact order |
| `ctx.planar_faces()` | centre, outward normal, area |
| `ctx.cylinders()` | radius, axis, sweep, `internal`, `full` |
| `ctx.holes()` | closed internal bores |
| `ctx.internal_rounds()` | concave corner rounds |
| `ctx.opposing_faces()` | facing planes and the wall thickness between them |
| `ctx.overhangs()` | angle from vertical, build-plate faces marked supported |

Report a violation with:

```python
def evaluate(ctx):
    bound = max(ctx.param("min_feature_mm"), ctx.param("kerf_mm") * 3.0)
    for hole in ctx.holes():
        diameter = 2.0 * hole.radius
        if diameter < bound:
            ctx.report(
                f"bore of {diameter:.3f} mm is below the {bound:.3f} mm minimum",
                refs=[hole.ref],                       # -> topology descriptors
                measured={"diameter_mm": diameter},    # -> the evidence
                suggested_bound=bound,
            )
```

`rule_id`, `title` and `severity` are attached from the **declaration**, not
from the predicate, so a pack cannot understate its own severity. Each `refs`
handle becomes an artifact-bound descriptor `{kind, solid_id, topology_index,
tag?}`, and any tag it carries is added to the finding's offending-tag list
automatically.

Write rules that measure. A rule that cannot measure its limit on the geometry
it is given should say so in its `description` rather than approximate it
silently.

## 2b. Cut-file layer conventions (what an exported DXF/SVG means)

A DXF handed to a laser or router is a machine program, not a drawing:
controllers map **layer name or colour** to a power/speed pair. `export_part`
therefore separates geometry onto four conventional layers with standard ACI
colours, and the assignment is a **rule over the part's own semantics** — never
a guess about geometry.

| layer | ACI | carries |
| --- | --- | --- |
| `CUT` | 1 (red) | through-cuts: each profile's outer ring and its holes |
| `ENGRAVE` | 5 (blue) | marking geometry that must not penetrate the stock |
| `SCORE` | 3 (green) | shallow score lines (folds, register marks) |
| `BLANK` | 8 (grey) | the nested-sheet stock rectangle — reference, never cut |

A contour reaches `ENGRAVE` or `SCORE` **only** because the part script tagged
that topology (`script_contract.md` §5.3) with a name carrying the documented
prefix:

```python
tag(lid.faces().sort_by(Axis.Z)[-1], "engrave_logo")   # -> ENGRAVE
tag(panel.edges().group_by(Axis.X)[0][0], "score_fold")  # -> SCORE
```

Everything else is a through-cut. Nothing is inferred from a feature's depth,
size or position: a heuristic that silently promotes a pocket to a marking pass
is exactly how a sheet gets scrapped, so an untagged contour is always cut.

Three consequences worth stating plainly:

- a tagged **face** contributes its outer boundary as a closed contour; a tagged
  **edge** contributes an **open** polyline, because a controller that closes a
  fold line cuts a slot the design does not have;
- a closed mark that lands inside an inner boundary **reclassifies** it — the
  part's own tag says that opening is a marking, so it is not also cut;
- a layer is written **only when it carries geometry**. A part that tagged
  nothing emits no `ENGRAVE`/`SCORE` layer at all, because an empty layer in a
  controller's job list invites a power setting that fires on nothing.

Marks are resolved against the **nominal** artifact, so kerf compensation moves
the cut path and never the marking — a marking pass removes no material. The
rule lives in one place, `hephaestus.core.cutfile`, and both the nested-sheet
writer and the as-built DXF writer consume it, so the two files cannot disagree.

## 3. Publish

From inside a Hephaestus project:

```console
$ heph registry publish acme-dfm --path ../acme-dfm --record acme-dfm.publication.json
acme-dfm: published sha256:6f1c…
  path:   /home/you/acme-dfm
  kind:   dfm v1.2.0
  leaves: 9
  content: packs=2, rules=6
  record: /home/you/proj/acme-dfm.publication.json
```

`publish` does four things, in order, and stops at the first failure:

1. **validates the tree end to end** — the manifest parses *and* every content
   index for the kind builds: skill files exist, store parts have both a
   `part.json` and a `generator.py`, materials records carry a numeric density,
   DFM packs bind every rule to a predicate file and every `reads` name to a
   declared parameter. A tree that does not fully read is not published;
2. **computes the Merkle digest** over the validated bytes;
3. **writes the pin** into `hephaestus.toml`;
4. **writes the publication record** when you pass `--record`.

It refuses to *change* an existing pin. Accepting new bytes stays one deliberate
command:

```console
$ heph registry update acme-dfm
```

## 4. The publication record

```json
{
  "record_version": 1,
  "name": "acme-dfm",
  "kind": "dfm",
  "version": "1.2.0",
  "license": "Apache-2.0",
  "digest": "sha256:6f1c…",
  "leaf_count": 9,
  "counts": {"packs": 2, "rules": 6},
  "published_at": "2026-07-26T09:14:03+00:00",
  "leaves": [{"path": "laser_cut/pack.toml", "digest": "…"}, …]
}
```

Distribute it beside the tree (a release asset, a tag, a file in the parent
repo). It carries the root digest *and* every leaf, so a consumer who sees a
mismatch is told **which** files were added, removed or edited — not merely
that the hash changed.

## 5. Consume

```console
$ heph registry publish acme-dfm --path vendor/acme-dfm   # pins it
$ heph registry verify acme-dfm --record acme-dfm.publication.json
acme-dfm: ok
```

`verify` fails with exit 1 when a tree drifted from its pin, when it is not
pinned at all, or when it disagrees with the record. Serving runtimes go
further: `RegistrySet.open(project, require_pinned=True)` refuses to start on an
unpinned registry, and `load_registry` hashes the tree *before* reading any
content for use, so a tampered tree never reaches a model or an executor.

In Python:

```python
from hephaestus.core.registry import (
    PublicationRecord, publish_registry, verify_publication,
)

record = publish_registry(root)                  # validates + digests
verify_publication(root, record)                 # raises registry_integrity
PublicationRecord.from_json(json.loads(text))    # parse a distributed record
```

## 6. Checklist before you publish

- `version` bumped, `license` set, `description` written for a reader.
- `heph registry publish` exits 0 (it is your content validator).
- Every DFM rule has a stable `rule_id` you are willing to keep: ids appear in
  findings, in stored reports, and in other people's suppression lists.
- Predicates measure geometry and use only `ctx`; no rule depends on a
  parameter it did not declare.
- Skills and materials notes read as reference material. They reach a model
  inside provenance delimiters and are explicitly not instructions — do not
  write them as if they were.
- Content is licensed for redistribution, and no reference names a bench corpus
  task (`repo_conventions.md`).
