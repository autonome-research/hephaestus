<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Registry pinning

Registries are the open catalogs Hephaestus reads from: **skills** (markdown
reference packs a model can load), **parts** (parametric generators), **materials**
(density and property records), and **DFM** (per-process rule packs whose
predicates are executable code).

Two of those four are content a model reads, and two are code that runs. Both
kinds are pinned the same way and for the same reason.

## What a pin is

`hephaestus.toml` pins every registry by a **Merkle digest over the whole tree**
(`repo_conventions.md`):

```toml
[registries.skills]
path = "vendor/acme-skills"
digest = "sha256:01428f65d83bfe1859b1c205e7161cf8c0c58a35f88f7a2479ac294f4349555f"
```

A tree whose bytes no longer hash to that digest **refuses to load at all**.
Not "loads with a warning" — refuses. And the tree is hashed *before* any
content is read for use, so tampered bytes never reach a model or an executor
in the first place.

Everything inside the tree is content and nothing outside it is: dotfiles and
`__pycache__` are skipped, symlinks are not followed, and `registry.toml` is
hashed like any other file, so editing the manifest changes the digest too.

## The verbs

### `heph registry list`

What is resolved, where it lives, and what it currently hashes to.

```console
$ heph registry list
dfm: unpinned (dfm)
  path:   /home/you/hephaestus/registries/dfm
  digest: sha256:891ca6c88c661a8f03ff15cd53dac78acd40f377e8c274697b16755473f4bf01
materials: unpinned (materials)
  path:   /home/you/hephaestus/registries/materials
  digest: sha256:050d07e33eb1e396bc44ed97ec1aafad2cfa06bc8d33ffa8e20e02181638b911
```

`unpinned` means the digest shown is simply what the tree hashes to right now —
nothing is being checked against anything. The four registries bundled with the
installation start this way.

### `heph registry components`

The component records the pinned `parts` registry carries — the store parts whose
`part.json` holds a validated `component` block. Legacy store parts (no block)
are not listed at all; this verb answers "what components do I have", and a part
with no record is not one.

```console
$ heph registry components
heatset_insert_m3: insert (heatset_metric M3)
  registry:   hephaestus-parts @ sha256:8390e93ef496583e64b5c555689b9a49623b3261e67f1ffca534f172e9b2d450
  interfaces: top_face, bore, knurl
  datasheet:  no
```

`--json` emits the same records as one array, id-sorted with a stable key order,
so two runs over an unchanged tree are byte-identical.

```console
$ heph registry components --json
[{"id": "heatset_insert_m3", "name": "M3 heat-set insert (brass envelope)", "class": "insert", …}]
```

### `heph registry pin [NAME…]`

Record the current digest.

```console
$ heph registry pin skills
skills: pinned sha256:01428f65d83bfe1859b1c205e7161cf8c0c58a35f88f7a2479ac294f4349555f
  path: /home/you/hephaestus/registries/skills
```

`pin` **never changes an existing pin.** That is the whole design: accepting new
bytes has to be a separate, deliberate act, or "pinning" degrades into recording
whatever happens to be on disk.

### `heph registry update [NAME…]`

Re-pin to the current digest. This is the *only* path that changes a pin.

```console
$ heph registry update skills
```

Run it when you have reviewed the new content — the same way you would merge a
dependency bump, and for the same reason.

### `heph registry verify [NAME…]`

Verify every pinned tree against its pin.

```console
$ heph registry verify
skills: ok
```

Exit code 1 when a tree drifted from its pin, when it is not pinned at all, or
when it disagrees with a publication record supplied via `--record FILE`.
`--json` emits the records for scripting.

### `heph registry publish NAME --path DIR`

The producer half. It validates the tree end to end, states the digest, writes
the pin, and (with `--record`) writes a publication record. See
[registry-contributions.md](registry-contributions.md) and
`registries/PUBLISHING.md` for the full mechanics.

## Serving is stricter than building

`RegistrySet.open(project, require_pinned=True)` — the path a serving runtime
takes — **refuses to start on an unpinned registry**. An interactive local
session may tolerate an unpinned tree while you are authoring one; a server
handing registry content to a model, or running a DFM predicate on behalf of a
remote client, may not.

The same asymmetry appears in the executor: DFM predicates and parts-store
generators are registry content, so `--unsafe-local-executor` refuses them
outright (`unsafe_refused`) even though it will run your own part script. Your
script is code you wrote; a registry predicate is code someone else wrote.

## Suggested workflow

```console
$ heph registry publish acme-dfm --path vendor/acme-dfm --record acme-dfm.publication.json
$ heph registry verify acme-dfm --record acme-dfm.publication.json
acme-dfm: ok
$ git add hephaestus.toml acme-dfm.publication.json && git commit
```

Commit the pin. A pin in git is a reviewable claim about which bytes your design
was verified against; a pin only on your disk is a note to yourself.

When the upstream tree changes:

```console
$ heph registry verify acme-dfm          # exits 1 — the tree moved
$ git -C vendor/acme-dfm diff            # review what moved
$ heph registry update acme-dfm          # accept it, deliberately
```

## The publication record

A record carries the root digest **and every leaf digest**, so a consumer who
sees a mismatch is told *which* files were added, removed, or edited — not
merely that the hash changed. Distribute it beside the tree (a release asset, a
tag, a file in the parent repository). Its shape and the `PublicationRecord`
Python API are documented in `registries/PUBLISHING.md` §4.
