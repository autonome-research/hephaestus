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

A `parts` tree is additionally restricted at publish time to `registry.toml`,
`part.json`, `generator.py` and `*.md`. Anything else — a `.pdf`, a `.step`, a
`.png` — is refused as `vendored_third_party_payload`, naming every offending
file. The rule is blunt on purpose: a store tree has no legitimate reason to
hold a binary, the Merkle digest hashes every file it finds, and a smuggled
vendor payload would otherwise be pinned and redistributed with the pack. Vendor
datasheets and vendor CAD are referenced by URL and content hash from a
component record's `datasheet` block, never copied here (`PARTS_STORE.md` §7).

Two further `parts` rules bite at publish, both because publishing builds the
content index:

- a `part.json`'s `params` keys must equal the generator's `PARAMS` keys, or
  publishing refuses with `param_schema_drift` naming the parameter. The
  generator's list is what the build path actually enforces, so a record that
  advertises a knob the generator lacks is advertising something a model cannot
  set; and
- a `part.json` may carry a validated `component` block, which makes the part a
  *component* — a richer record with declared mounting interfaces, provenance
  and licensing. Every rule that block obeys is stated in `PARTS_STORE.md` §1,
  and every violation is a named refusal at index time. A part without the block
  is a legacy store part and is unaffected.

### A component's mounting interfaces

A component's declared interfaces are **tagged geometry**, not prose: the
generator gains a fourth marker region after `body`, and each statement in it
names one declared interface on the shape the body published.

```python
# --- hephaestus-store: interface ---
tag(_root.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")
tag(_root.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "shaft")
```

The region is optional, appears at most once, and comes last. Publishing
refuses a generator whose emitted names are not **exactly** the record's
`component.interfaces[].name` set — a surplus is `undeclared_interface`, a
shortfall `unimplemented_interface`, each naming the interface. A declared
interface nothing emits is the `mating_features` mistake: metadata a consumer
has to retype.

Three authoring rules, in the order they bite:

1. **Root every selector at the name the body publishes.** Anything else is
   `interface_root_violation`, and a selector that also *loads* another
   generator local is `interface_body_local_reference` — the fragment rewrite
   retargets the root to the placed instance, and a local still names
   pre-placement geometry, so mixing them measures the placed shape in the
   unplaced frame and picks a real face that is silently the wrong one.
2. **Order by a measure, never by a world axis.** `sort_by(SortBy.AREA)`,
   `sort_by(SortBy.RADIUS)` and `sort_by_distance(...)` survive the `Pos`/`Rot`
   a consumer applies; `sort_by(Axis.Z)[-1]` does not. This one is an authoring
   rule because it is not decidable by a parser: `interface_placement_drift`
   catches a selector that picks topology of a *different measure* under the
   caller's placement, but two faces of equal measure are indistinguishable
   that way, so the check is necessary, not sufficient.
3. **Declare the class the topology actually is.** `planar_face`,
   `cylindrical_face`, `circular_edge`, `linear_edge`, `solid` — verified on
   every instantiation against the geometry that built, at the caller's
   parameters and at the caller's placement, as `interface_class_mismatch`. A
   torus, cone or B-spline face matches no class and is refused: this stage's
   consumers cannot use one.

The emitted tag literal is `<instance>__<name>`, so two pasted instances cannot
overwrite each other's tags. A consumer anchors an ordinary 8C constraint or
Stage 9 joint on that name; the anchor grammar is unchanged.

### A component's provenance, and what may not be vendored

The operator's 2026-08-29 decision is **reference, do not vendor**
(`PARTS_STORE.md` §7): third-party datasheets and vendor CAD are referenced by
URL and content hash with their terms declared, never copied into a registry.
That splits cleanly into three lists.

**What a pack may carry.** Independently authored generator source, Apache-2.0.
Nominal dimensions from a published standard — a DIN 912 head diameter, an
ISO 15 bearing bore/OD/width, a NEMA ICS 16 frame square and bolt circle —
cited in `component.series.standard`. And the minimum set of derived numeric
facts the geometry and its declared interfaces require, and no more.

**What it may not.** Vendor CAD payloads (STEP, IGES, SLDPRT or any converted
derivative), vendor PDFs, drawing images, artwork, logos and marketing renders.
Bulk transcriptions of vendor tables: a number a declared interface or a
declared claim requires is admissible, a table copied wholesale is not — the
line is drawn at necessity because the harness cannot tell a fact from a
compilation. Anything under terms you have not read. And a vendor trademark as
a component id: ids are generic or standard-derived (`bearing_608`,
`stepper_nema17_frame`), never `<vendor>_<sku>`.

Two of those are mechanical, and both bite at publish. Any file in a `parts`
tree that is not `registry.toml`, `part.json`, `generator.py` or `*.md` is
`vendored_third_party_payload`, naming every offending file — blunt on purpose,
because a store tree has no legitimate reason to contain a binary and the Merkle
digest would otherwise pin and redistribute it. A component id matching the
maintained trademark deny-list is `trademark_in_component_id`. **Neither check
is the real control.** A deny-list is imperfect by construction and a scanner
cannot read a licence; the human review of `docs/registry-contributions.md` —
a reviewer other than the author — is what actually decides, and publication of
a component pack is additionally blocked until `LEGAL-REVIEW.md`'s fifth scope
field (third-party component data provenance and terms) is signed off.

**The `datasheet` block is a pointer that redistributes nothing.** All six
fields are required when it is present — `publisher`, `document_title`,
`revision`, `url`, `sha256`, `retrieved` — and `sha256` is the digest of *the
exact document the numbers were transcribed from*, in the `sha256:…` form. The
URL is provenance, **not a fetch target**: nothing in Hephaestus retrieves it,
the sandbox denies network by construction, and a registry that fetched at load
would break the offline determinism the trust model rests on. A reader obtains
the document themselves. If you cannot state that digest honestly, do not write
the block — and if a pack cannot be authored without one you do not have, that
pack does not ship, said loudly rather than resolved by inventing a hash.

### Declared data: mass and claims

`component.mass` is `{value_g, source, com_mm?}` with `source` from
`datasheet` | `standard` | `computed`.

- `datasheet` requires the `datasheet` block; `standard` requires a
  `series.standard`. Absent, either is `unsourced_component_datum` — a record
  whose numbers are recalled is a rumour with units on it.
- `computed` is for a **homogeneous** component only (a fastener, an insert, a
  gear blank). It requires a materials-registry id and a positive
  `tolerance_pct`, and the value is then checked on *every instantiation*
  against the built envelope's `volume x density`. A disagreement is
  `computed_mass_disagreement` and is never reconciled or averaged: the record
  is wrong or the envelope is, and both are yours to fix. Because the check runs
  against the geometry that actually built, a component with a parameter that
  moves its volume cannot carry a single computed mass.
- Declaring both a datasheet mass and a computed material is
  `mass_source_conflict`. An inertia tensor is `inertia_out_of_scope` — nothing
  consumes one, and silently storing a field with no consumer is how
  `mating_features` happened.

`component.claims` is declared, provenance-bearing datasheet data, each entry
`{id, kind, unit_x, unit_y, samples, cite}`. Read the vocabulary literally:
**nothing in Hephaestus can evaluate a torque-speed curve**, so a claim is
reference material and reaches a model wrapped in the same provenance
delimiters skill text does, with a footer saying so. A non-empty `claims` list
requires the `datasheet` block and each `cite` must name a page and quote in it;
`claims[].id` is unique within a record. A `torque_speed_curve` is validated at
load for at least two samples, finite pairs, strictly increasing in x,
non-negative and non-increasing y, and units from the closed set — any violation
is `malformed_performance_curve`, naming the sample index. That is the whole
honest benefit available: a transcription error becomes a load-time contract
error instead of a plausible-looking number.

A number from a claim becomes a *commitment* only through the ledger: record it
as a requirement citing `{reference, page, quote, component, claim}` after the
operator has registered the document with `heph reference add`. `heph lint` then
reports a `CHECKS` threshold that matches a claim value with no citation as
`uncited_component_datum`, and a citation whose registered reference is not the
bytes your `datasheet` pointer names as `datasheet_digest_mismatch`.

### Several packs side by side

Registries of kind `parts` **index together**. A part id unique across the
resolved trees is addressed bare, exactly as before; an id two trees both carry
is addressed `<registry>/<id>`, and addressing it bare is
`ambiguous_component_id` naming both candidates — never resolved by pin order,
because which pack the operator meant is not derivable from table order. Every
search row carries its own `registry` and `registry_digest`, so a component
always names the tree it came from. Registries of every *other* kind still index
one per kind, and a second is `duplicate_registry_kind`.

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
- For a **component** pack (`PARTS_STORE.md` §7): no vendor payload of any kind
  is in the tree; no id names a vendor product; every number is standard-derived
  or required by a declared interface or claim; every `datasheet` pointer's
  `sha256` is the digest of a document you really obtained, and its terms permit
  reference-by-citation; every declared interface is emitted by the generator
  and ordered by a measure rather than by a world axis; a `computed` mass agrees
  with the built envelope. Publication is additionally blocked until
  `LEGAL-REVIEW.md`'s third-party-component-data scope field is signed off.
