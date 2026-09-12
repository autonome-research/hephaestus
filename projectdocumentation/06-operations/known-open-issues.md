# Known open issues

> **Verified against** `3c3847c` on 2026-09-12.
> Each entry below was re-checked against the code or by running a command at
> this commit; the evidence is given with the entry. Items fixed since the audit
> that recorded them are not listed.

This is the register of things that are **true and not yet fixed**. It exists so
that a reader of the rest of this set knows where the documentation is describing
a system that still has a known gap.

Entries closed by a fix are removed, not marked. The repository's audit ledgers
(`docs/audit-2026-09-04-janky.md`, `docs/audit-2026-09-04-broken.md`) keep the
history; this page keeps the present.

---

## OPEN-1 — Two bounded operations conflate a ceiling with a death

**Severity: medium. Source: the wave-2/3 independent review, 2026-09-08.**

Five operations run a child under a wall clock through one shared supervision
helper, and each must distinguish "it ran out of time" from "it crashed" —
because more time cures the first and cures nothing about the second.

| Operation | Ceiling | Child died |
| --- | --- | --- |
| solid diff | `compare_timeout` | `compare_child_died` |
| motion sweep | `motion_timeout` | `motion_child_died` |
| solver verification | `solver_timeout` | `verification_process_died` |
| scan distance | `scan_timeout` | `scan_timeout` ← **conflated** |
| mesh sew | `mesh_sew_timeout` | `mesh_sew_timeout` ← **conflated** |

`scan_compare.bounded_scan_distance` and `mesh_solid.bounded_mesh_solid` run on
the shared helper and compute a differentiated *message*, but raise the same
*reason*. A machine reading `reason` cannot tell a crash from a ceiling there.

Scan was deliberately kept as the behaviour-preserving control while the helper
landed. The remaining work is the split: `scan_child_died`, `mesh_sew_child_died`,
the bench refund rows, and `compare_to_scan`'s reason map.

**Where it shows up in this set:** the table in
[the refusal vocabulary](../04-reference/refusal-vocabulary.md#bounded-operations-a-ceiling-is-not-a-death)
marks both rows as conflated.

---

## OPEN-2 — A sixth hand-copied supervision loop outside the engine tree

**Severity: medium. Source: the same review.**

`_bounded_floor` in `bench/src/hephaestus/bench/cadgenbench/_score.py` is a sixth
subprocess-supervision loop, hand-copied rather than using the shared helper, and
**with no death drain**. The structural guard that finds the others cannot see it,
because the guard scopes to the engine tree.

Consequence: a child that dies under the bench scorer is not distinguished from
one that timed out, and the loop does not drain the child's output on death.

---

## OPEN-3 — The stage-13B `bench` fixture pollutes a session-scoped project

**Severity: low, but order-dependent. Source: the same review.**

The stage-13B `bench` fixture is a session-scoped project, and proposals recorded
through it pollute it for later `bench_copy` counts.

**CI's alphabetical ordering hides this. A reordered run does not.** That is the
worst shape for a test defect: green until someone changes something unrelated.

---

## OPEN-4 — L8 (`J-mirrors-and-dx-1..10`) is deferred by decision

**Severity: low. Status: deliberate.**

A lane of the janky audit remains deferred. It is recorded here so that "not
done" is visible rather than inferred from silence.

---

## OPEN-6 — Three specified HTTP routes are not served

**Severity: low. Status: recorded in code as `UNSERVED_SPEC_ROUTES`.**

```
POST /parts/{part}/selection/resolve
POST /parts/{part}/render/section
POST /parts/{part}/quick_edit
```

All three answer `unknown_route` today.

The first two are specified in detail and the engine functions they would bind
exist (`core/render/bundle.py::resolve_selection`,
`core/render/gltf.py::resolve_gltf_pick`), so this is unlanded **binding**, not
specification debris. Landing it needs a `CadOps` seam for the GLTF-pick shape,
because `server/http` may not import `core.render` at all — asserted at import
level — so the existing `describe_selection` seam is the shape to extend.

The third, `quick_edit`, was found only when the set was re-derived mechanically
from the specification's own tables. **It had never been counted.** That is the
whole argument for binding the two tables rather than transcribing one into the
other.

---

## OPEN-7 — Artifact kinds are unverifiable for pre-existing blobs

**Severity: low. Status: bounded and reported honestly.**

A blob published before `tp_artifact_kinds` existed, or by a path not yet
instrumented, has **no rows**. That is reported as the empty set, and a reader
must treat it as *unverified*.

The two convenient answers are both refused: "no kind matches" would make every
pre-existing artifact unreadable, and "any kind matches" would be the module
lying. The caller decides what an unverified blob may do.

---

## Documentation defects in the repository's own specs

These are wrong statements in committed documents, verified at this commit. They
are listed separately because fixing them is an editorial change, not a code
change.

### DOC-3 — `RELEASE_FACTS.md` is a dated survey presented as fact

Its own header says what it is: *"Stage 7H recon (read-only survey, 2026-08-01).
Facts established by reading the tree at `341da20`."*

It carries a full `heph` verb inventory from that commit. The tree has moved a
long way since; the document is a **historical record**, and its title invites it
to be read as current.

The verb inventory readers should use is `uv run heph --help`, and
[the CLI reference](../04-reference/cli.md) in this set, which was checked
against it.

### DOC-4 — `docs/README.md` indexes 10 of the repository's markdown documents

There are 34 markdown documents at the repository root and under `docs/`.
`docs/README.md` links 10 of them.

An index that covers under a third of its subject is worse than no index,
because a reader takes an absence from it as an absence from the repository.

---

## How to use this page

**Adding an entry.** Verify it at the current commit, give the evidence, and say
the severity. An entry without evidence is a rumour.

**Closing an entry.** Delete it in the same commit as the fix, and say so in the
commit message. Do not leave a struck-through entry: the register is the present,
not the history.

**Reviewing.** The quarterly documentation pass re-reads this page and tries to
close entries — see
[documentation maintenance](documentation-maintenance.md#quarterly-the-deeper-pass).
