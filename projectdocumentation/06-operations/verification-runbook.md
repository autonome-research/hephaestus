# Verification runbook

> **Verified against** `49a90c6` on 2026-09-12.

How a claim becomes something this documentation is allowed to state. This is
the procedure behind the house rule in [the set's README](../README.md).

## Why the rule exists

Three examples from this repository, all found by running something rather than
by reading:

| Claim | Where it lived | What was true |
| --- | --- | --- |
| "reads the kernel's process file" | the helper's own docstring, and a commit message repeating it | it forked `ps` on every call, inside polling loops |
| "the repair cap occasionally repairs both parts" (a workflow bug) | an audit ledger, recorded as an open design question | a delegation was failing underneath it; the workflow was correct |
| "exports 57 names" | a subsystem summary written from the source | `len(opstore.__all__)` is 61 |

A document that repeats a plausible claim is worse than a missing document,
because it is believed. The cost of checking is minutes; the cost of a false
document is however long it takes someone to discover it the hard way.

## The five kinds of claim, and what each needs

**1. A number.** A limit, a count, a timeout, a size.
Name the file that defines it, or print it.

```console
$ python3 -c "import json; print(json.load(open('schemas/bridge_limits.json'))['timeouts'])"
{'tool_seconds': 120, 'turn_seconds': 600, 'cad_build_seconds': 300, 'delegation': {...}}
```

Never copy a number out of prose. Numbers are the first thing to drift, and a
number with no source cannot be re-checked later.

**2. A behaviour.** "X refuses when Y", "the pill unmounts", "a crash is not a
timeout".
Exercise it. A targeted test is best, because it stays true; a one-off command
is acceptable when you record the command and its output.

```console
$ uv run pytest server/tests/test_supervisor.py -q -p no:randomly
24 passed in 27.57s
```

If the behaviour has no test, that is itself a finding worth writing down.

**3. A structure.** A route table, a schema, an export list, a file layout.
Enumerate it from the source of truth, not from an older document.

```console
$ uv run python -c "import opstore; print(len(opstore.__all__))"
61
```

**4. An absence.** "nothing else writes here", "this is the only implementation".
Absence needs a search, and the search belongs in the document or its commit.
`grep -rn` across the tree, with the pattern shown, is the evidence.

**5. A rationale.** "this exists because X".
Rationale is the one class that cannot be verified by running something. Cite
where the reasoning is recorded — a spec section, an ADR, a commit message —
or mark it as the writer's inference. Never present inference as history.

## The procedure

1. **Write the claim down as a question.** "Does `heph build` refuse without a
   sandbox?" is checkable. "The build is sandboxed" is not.
2. **Find the source of truth.** Code beats a docstring; a docstring beats a
   design note; a design note beats memory. When they disagree, the code is the
   fact and the disagreement is a finding.
3. **Run the check.** Keep it small and repeatable.
4. **Record the evidence.** The command and its real output, or `path:line`.
5. **Write only what the check supports.** If the check proved something
   narrower than the claim, write the narrower thing.
6. **Record what you could not check.** Every document in this set may end with
   an **Unverified** section. That section is a feature: it tells the next
   reader where the floor is thin.

## Running things in this repository

Long jobs must survive the lid closing:

```console
$ keepawake uv run pytest server/tests -q
```

Sidecar-backed tests need the staged sidecar to match `agent/src`. After any
change under `agent/`, re-stage before trusting a green run:

```console
$ (cd agent && pnpm install --frozen-lockfile && pnpm run bundle)
$ uv run python scripts/stage_sidecar.py
$ uv run python -m hephaestus.testing.sidecar
```

The last command records the source digest. With
`HEPHAESTUS_SKIP_SIDECAR_BUILD=1` set, a stale stage then fails by name instead
of silently testing yesterday's bundle. That guard is the reason a stale bundle
after a `git pull` is caught rather than reported as a product bug.

The full command set is in [Run the tests](../03-how-to/run-the-tests.md).

## When a check fails

A failing check is the most valuable outcome of this procedure, and it has three
possible meanings. Decide which before doing anything:

1. **The claim is wrong.** Fix the document, and look for the same claim
   elsewhere — false claims travel.
2. **The code is wrong.** Then the documentation task has found a defect. Write
   a test that fails, fix the defect, and document the fixed behaviour.
3. **The environment is wrong.** A stale artifact, a missing package, a
   throttled CPU. Fix the environment and re-run; do not weaken the claim to fit
   a bad run.

The third is the one that fools people. Two examples from this repository: a
suite that failed only on battery power, because the CPU dropped to roughly a
gigahertz and a solve exceeded a ceiling; and a browser suite that failed only
against a staged sidecar older than the source tree. Neither was a product
defect, and neither was flake — both were the environment, and both were
diagnosable.
