<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# The shipped six as they were before Stage 11 touched them

FROZEN. These are the six `registries/parts/*/part.json` **and** the six
`registries/parts/*/generator.py` files exactly as they stood immediately before
Stage 11 ran — before item 19 promoted `origin` and `simplifications` into the
validated `component` block, folded `envelope` into the generator that already
owns those numbers, and deleted `mating_features`, and before item 31 appended an
`interface` region (`PARTS_STORE.md` §2.1) to each generator.

They are here because **item 19's stated deliverable is a Merkle-root change**
(`PARTS_STORE.md` §1, G11A clause 3). A gate that asserts "the root moved, the
new root republishes, `publication_drift` names exactly the edited files, and
every fragment *body* is unchanged under the elided digest line" needs the
pre-edit bytes to compare against. Reconstructing them by re-adding the retired
keys in the test would be the test asserting its own arithmetic; recording them
is evidence.

**Corrected 2026-08-29.** An earlier form of this fixture recorded only
`part.json` and this README said so: "Only `part.json` files differ from the
shipped tree." That was true when it was written and stopped being true inside
the same stage — item 31 edited all six generators — and the test reconstructing
the tree read `generator.py` from the *current* shipped tree, so what it built
was a hybrid rather than the tree that existed. The consequence was not cosmetic:
`test_every_shipped_fragment_body_survived_item19_unchanged` compared the same
generator against itself and so could not have detected a generator edit, and one
had been made. The six `generator.py` files are now recorded here too, the
reconstruction reads both from this directory, and the "these really are the
before bytes" property is asserted in
`test_the_recorded_pre_tree_is_recorded_and_not_a_hybrid` rather than asserted in
prose here, where nothing can fail.

`registry.toml` is included unchanged so the reconstructed tree hashes as the
pre-edit tree really did. `README.md` is not part of the reconstruction.

Nothing edits this directory. A later stage that changes a shipped `part.json` or
`generator.py` again records its own "before" fixture; it does not update this
one.
