# Documentation maintenance

> **Verified against** `3af69da` on 2026-09-12.

How this set stays true as the code changes. Documentation rots by default; the
only thing that prevents it is a routine somebody actually runs.

## The rule

**Documentation changes in the same commit as the behaviour it describes.**

If that is not possible, it changes in the next documentation pass, and the pass
runs while the change is still fresh. A document that describes last month's
system is not "slightly out of date" — it is wrong, and it is believed.

## The daily pass

Run when there is new work on `main`. Roughly fifteen minutes when the day was
quiet; longer when a subsystem moved.

### 1. Find what changed

```console
$ uv run python scripts/docs_pass.py
```

That is the whole of steps 1 and 2. It reads the `Verified against <commit>`
stamp every document carries, finds the **oldest** one, diffs the tree from
there, and maps the changed paths to the documents that describe them. It also
prints the enumeration commands to re-derive, and names any changed path that
matched no route — an unmapped path is either a new subsystem or a gap in the
table, and both want a person.

```console
$ uv run python scripts/docs_pass.py --stamps          # just the stamps
$ uv run python scripts/docs_pass.py --since HEAD~20   # an explicit range
```

Exit `0` means every document is stamped at `HEAD`; exit `1` means a pass is due.

**It reports; it never edits.** Moving a stamp without re-verifying would
manufacture exactly the false confidence the stamp exists to prevent.

**It is deliberately not a CI gate.** A code change would then fail the build
until someone ran a documentation pass, which turns a maintenance routine into a
merge blocker and gets the routine disabled. `docs_check.py` is the gate;
this is the planner.

By hand, if you prefer:

```console
$ git log --oneline <oldest-stamp>..HEAD
$ git diff --stat <oldest-stamp>..HEAD
```

### 2. Decide what the change touched

The script's routing table, which is the same mapping in code:

First match wins, so the specific prefixes come before the general ones.

| Changed path | Documents to re-check |
| --- | --- |
| `core/src/hephaestus/core/cli*` | [CLI](../04-reference/cli.md), [tutorial](../02-tutorial/your-first-part.md) |
| `core/…/executor` | [building blocks](../05-architecture/building-blocks.md) |
| `core/…/checks` | [runtime view](../05-architecture/runtime-view.md) |
| `core/…/project_store` | [data model](../04-reference/data-model.md) |
| `core/src` (anything else) | [building blocks](../05-architecture/building-blocks.md) |
| `opstore/src` | [data model](../04-reference/data-model.md) |
| `server/…/http` | [HTTP API](../04-reference/http-api.md) |
| `server/…/agent_bridge` | [bridge protocol](../04-reference/bridge-protocol.md), [agent tools](../04-reference/agent-tools.md) |
| `server/…/mcp` | [agent tools](../04-reference/agent-tools.md) |
| `contract/src` | [agent tools](../04-reference/agent-tools.md) |
| `agent/src` | [bridge protocol](../04-reference/bridge-protocol.md), [work on the sidecar](../03-how-to/work-on-the-sidecar.md) |
| `web/src` | [web client](../04-reference/web-client.md) |
| `bench/src` | [quality and risks](../05-architecture/quality-and-risks.md) |
| `schemas/` | [limits](../04-reference/limits-and-configuration.md), [agent tools](../04-reference/agent-tools.md) |
| `.github/workflows` | [deployment view](../05-architecture/deployment-view.md), [run the tests](../03-how-to/run-the-tests.md) |
| `scripts/` | [run the tests](../03-how-to/run-the-tests.md), this page |
| `packaging/` | [release and package](../03-how-to/release-and-package.md) |
| `pyproject.toml` | [run the tests](../03-how-to/run-the-tests.md) |
| anything else | reported as **unmapped**; decide by hand |

A change to a root specification (`INTERFACE.md`, `SOLVER.md`, `tool_schema.md`
and the rest) lands in the unmapped list on purpose. This set *points at* those
documents rather than describing them, so which pages a spec change touches is a
judgement — usually none, sometimes [the glossary](../01-orientation/glossary.md)
or [known open issues](known-open-issues.md).

A change to a refusal name, a limit, a route or a tool signature always touches
[the reference section](../04-reference/), because those are enumerations. So does
anything that changes a structural rule — then read
[crosscutting concepts](../05-architecture/crosscutting-concepts.md) and
[decisions](../05-architecture/decisions.md) too.

**Keep the table and the script in step.** They are the same mapping, and if you
add a subsystem, add its route to `scripts/docs_pass.py` as well — otherwise its
changes land in the unmapped list forever.

### 3. Re-verify, then edit

For each affected document, re-run the checks that produced its claims, using
[the verification runbook](verification-runbook.md). Do not edit from the diff
alone: a diff shows what changed, not what is now true.

The enumerations have a mechanical check each — `docs_pass.py` prints these, and
each one should be run and compared against the document:

```console
$ uv run heph --help                                    # 25 CLI verbs
$ ls schemas/tools/ | wc -l                             # 57 declared agent tools
$ cat schemas/bridge_limits.json                        # 27 numeric leaves
$ uv run python -c 'from hephaestus.http.app import ROUTE_TABLE;print(len(ROUTE_TABLE))'
$ uv run python -c 'from hephaestus.http.errors import REASON_STATUS;print(len(REASON_STATUS))'
$ uv run python scripts/docs_check.py                   # links, paths, section refs
```

A number that moved is a document to edit. A number that did **not** move is a
stamp you may advance for that document — and nothing more.

### 4. Update the stamps

Every document you re-verified gets its stamp moved to the commit you verified
against. A document you did not re-check keeps its old stamp — that is the
honest signal, and the oldest stamp is where the next pass starts.

### 5. Record what you could not verify

Anything you could not check goes in that document's **Unverified** section, and
anything you found broken goes in
[known open issues](known-open-issues.md) with the evidence.

### 6. Commit

One commit for the documentation pass, subject `docs: …`, body naming the range
of code commits it covers.

## What the gate already enforces

`scripts/docs_check.py` runs in CI and resolves, across the governed set:

- every relative link and its anchor,
- every backticked repository path,
- every document and numbered-section reference,
- console blocks that would teach a command form without the version pin.

It fails the build on a dangling reference; there is no warning level. That
catches the cheapest class of rot — a file that moved, a section that was
renumbered — and nothing else. **It cannot catch a sentence that is merely
false**, which is why steps 1 to 5 exist.

## The repository's own document set

Besides this set, the repository carries 68 tracked markdown documents:
normative specifications at the root, working records under `docs/`, per-package
design and readme files, spike results under `spikes/`, and the agent skills
under `registries/skills/`.

**Audited 2026-09-12: none of them is an orphan, and none is a duplicate.**

```console
$ git ls-files '*.md' | grep -v node_modules | wc -l
68
$ # byte-identical pairs:
$ git ls-files '*.md' | xargs -I{} sh -c 'echo "$(sha256sum < {}) {}"' \
    | sort | awk '{print $1}' | uniq -d
   (none)
```

Every document has at least one inbound citation from a specification, from
code, or from a test. The five with exactly one — the files under
`registries/skills/` — are not documentation at all: they are **registry
content** the agent loads at runtime, pinned by `registries/skills/registry.toml`
and asserted by `core/tests/test_registry_content.py` and
`server/tests/test_dispatch_registry.py`.

So there is nothing safe to delete, and `docs_check.py` would fail the build if
anything were removed anyway — which is the mechanism working.

What the audit *did* find is three documents that are **true but easy to
misread**, recorded in [known open issues](known-open-issues.md): a dated survey
whose title reads as current (`RELEASE_FACTS.md`), two forward specifications
that do not say at the top that they specify unbuilt work (`CAM.md`,
`PHYSICS.md`), and an index covering under a third of its subject
(`docs/README.md`). Those want an editorial pass, not deletion.

**The lesson for pruning:** check the citation graph before deleting, not after.
In this repository a working record from July is cited by a sandbox module's
docstring, and a "proposal" is cited by two normative specs.

## Quarterly: the deeper pass

Once a quarter, or after a large merge, do what the first pass of this set did:

1. Re-read each subsystem against its reference document, not the other way
   round.
2. Re-check the **absences** — "this is the only implementation", "nothing else
   writes here". Absences are the claims that quietly stop being true, because
   nothing fails when a second implementation appears.
3. Re-read the **Unverified** sections and try to close them.
4. Prune. A document nobody has needed in a quarter and that no test cites is a
   candidate for deletion; say so in the commit rather than leaving it to rot.

## Anti-patterns

- **Documenting the plan instead of the system.** If it is not built, it does
  not belong in the reference. Put it in a decision record with its status.
- **Copying a number out of a spec.** Cite the spec instead. Two copies drift,
  and the copy in the friendlier document is the one people believe.
- **"Should" and "will".** This set describes what the code does today. Intent
  belongs in [decisions](../05-architecture/decisions.md).
- **Updating prose without re-running the check.** The most common way a
  verified document becomes an unverified one.
