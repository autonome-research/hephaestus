# Release and package

> **Verified against** `16f9613` on 2026-09-12.
> Build sequence from `PACKAGING.md` and `scripts/stage_sidecar.py`; lanes and
> rules from `.github/workflows/release.yml`; distribution metadata from
> `packaging/pyproject.toml`.

`PACKAGING.md` at the repository root records the mechanics normatively and wins
where this page disagrees. This page is the working procedure and the reasoning.

## Nothing is published yet

There is **no published wheel and no GitHub Release**. Users install from a
clone. The tables below describe what a successful local `uv build` produces, not
what anyone can `pip install` today.

A `git+…#subdirectory=…` install **cannot** build `hephaestus-server`: the
sidecar is gitignored and `server/hatch_build.py` refuses a non-editable wheel
without it. That path should be documented only once wheels carrying `_sidecar/`
exist.

## The build, end to end

```console
$ cd agent && pnpm install --frozen-lockfile   # exact pins from pnpm-lock.yaml
$ cd agent && pnpm run bundle                  # → agent/build/sidecar/  (~14 MB, 43 files)
$ uv run python scripts/stage_sidecar.py       # → server/src/…/agent_bridge/_sidecar/
$ uv run python -m hephaestus.testing.sidecar  # record the source digest
$ uv build --all-packages --out-dir dist       # → dist/*.whl, dist/*.tar.gz
```

Wrap the build in `keepawake`.

### What comes out

| Wheel | Size | Contents |
| --- | --- | --- |
| `hephaestus_cad` | ~2 KB | **metadata only** — the aggregate users install |
| `hephaestus_server` | ~2.8 MB | bridge, MCP, **the packaged sidecar** |
| `hephaestus_core` | ~333 KB | the engine and the `heph` entry point |
| `hephaestus_contract` | ~24 KB | the tool contract and its schemas |
| `opstore` | ~38 KB | the durability substrate |
| `hephaestus_bench` | ~94 KB | evaluation only, behind the `bench` extra |

`hephaestus-cad` carries **no code**. The `hephaestus` import namespace is split
across four distributions and `opstore` is a fifth; re-homing them into one would
mean vendoring source (four copies to keep in sync) or flattening the workspace
(losing the per-package test and typecheck boundaries the whole tree is organised
around). A dependency-only aggregate gives the single `pip install
hephaestus-cad` the mission asks for while the components stay exactly where they
are tested.

### Why the sidecar ships in `hephaestus-server`

Because the only code that resolves and spawns it is `hephaestus.agent_bridge`.
Co-locating them means `pip install hephaestus-server` is self-consistent, and
**there is no way to assemble an installation whose bridge and sidecar come from
different releases.**

Staging also writes:

- `MANIFEST.json` — SHA-256 per file, verified **bidirectionally** before every
  spawn: every entry present and matching, *and* no file in the tree that the
  manifest does not list. A one-directional check would let an attacker add a
  module the bundle's chunk graph then imports.
- `AUDIT.json` — the esbuild metafile distilled, so the shipped wheel is
  self-describing for the native-addon audit. Walking a 14 MB bundle for import
  edges at test time would be guesswork; the build knows the module graph
  exactly.

## The release matrix

Runs on `workflow_dispatch` and on a pushed `v*` tag.

It holds **no write permission** on the repository: it does not cut the tag, it
**verifies that a pushed tag is coherent with the version the wheels declare.**
There is no `pull_request_target`, so it never runs untrusted PR code.

| Job | What it proves |
| --- | --- |
| `wheelhouse` | builds the wheels and uploads them as one artifact |
| lane (a), per OS | `pipx install` → `heph --version` → import/lint/schema smoke, **no script execution and no Node** |
| lane (b), secure linux x86_64 | build and check through the secure executor → packaged-sidecar integrity and native-addon audit → Python-backed JobStore init → `heph agent` against a fake model → MCP smoke → the secure-executor escape suite |
| lane (d), fail-closed | agent/server script execution on lanes **without** a passing secure backend; macOS refuses script execution by design in v0.1 |
| `prior gates` | the prior gates are green on the release SHA |
| `G7H gate` | the aggregate |

Lane (c) does not exist. It was **removed, not conditioned**.

### The two rules that make the matrix mean something

**1. Every lane installs the built wheel**, downloaded from the `wheelhouse`
artifact. No lane installs from the source tree — an in-tree install resolves the
*development* sidecar at `agent/build/sidecar`, and the gate's central claim
("the wheel uses its packaged sidecar") becomes untestable.
`HEPHAESTUS_WHEELHOUSE` points the packaging suites at the same artifact so they
too measure the released bytes.

**2. A lane never passes by absence.** Lane (a) *asserts* Node is gone rather than
hoping. Lane (d) *asserts the named refusal* rather than skipping. A lane that
would have to skip does not exist at all — which is why (c) was deleted rather
than made conditional. No green check can stand in for one that did not run.

## Running the packaging suites locally

They are marked `slow` and deselected by default, but they **must** run locally —
marked, not skipped:

```console
$ keepawake uv run pytest -m slow
$ keepawake uv run pytest tests/stage7h -q
```

`tests/stage7h/` also holds the configuration's own invariants: what is linted,
what is type-checked, where the pnpm pin comes from, and which directories a bare
`pytest` reaches.

## The leaderboard

`docs/leaderboard.md` is a release deliverable, generated from archived bench
artifacts at `bench/results/<model>/<date>.json`.

```console
$ uv run heph bench leaderboard          # regenerate
$ uv run heph bench leaderboard --check  # what CI runs
```

Two properties make `--check` mean something:

- **It reads, it never scores.** Every number is copied out of an artifact
  `heph bench score` already wrote. It computes no pass rate, no Wilson bound, no
  gate verdict. A leaderboard that re-derived statistics would be a second
  scorer, and a second scorer eventually differs from the first.
- **It is deterministic.** Same artifacts in, byte-identical page out. Rows sort
  by model then date, and nothing about the wall clock, the filesystem order or
  the host reaches the output.

## Release checklist

- [ ] the tree is clean and the prior gates are green on the release SHA
- [ ] `agent/` re-bundled, re-staged, and the source digest re-recorded
- [ ] `uv build --all-packages` produces all six distributions
- [ ] `uv run pytest -m slow` green locally
- [ ] `uv run heph bench leaderboard --check` green
- [ ] `uv run python scripts/docs_check.py` green
- [ ] `uv run python scripts/license_headers.py --check` green
- [ ] `scripts/bootstrap.sh --check` green on a bare checkout
- [ ] the documentation set re-verified against the release commit — see
      [documentation maintenance](../06-operations/documentation-maintenance.md)
- [ ] the tag's version matches what the wheels declare

## Related

- [Deployment view](../05-architecture/deployment-view.md).
- [Work on the sidecar](work-on-the-sidecar.md).
- [Run the tests](run-the-tests.md).
