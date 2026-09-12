# Run the tests

> **Verified against** `16f9613` on 2026-09-12.
> `testpaths`, `addopts`, markers and the timeout settings read from
> `pyproject.toml`; CI job names from `.github/workflows/ci.yml`; suite sizes
> from `find … -name 'test_*.py' | wc -l`.

## The whole gate

```console
$ uv run ruff check . && uv run ruff format --check .
$ uv run pyright
$ uv run pytest                                  # every suite; HOURS
$ (cd agent && pnpm typecheck && pnpm test)
$ (cd web   && pnpm typecheck && pnpm test && pnpm lint)
$ uv run python scripts/docs_check.py
$ uv run python scripts/license_headers.py --check
```

Wrap anything long in `keepawake` so a closed lid does not suspend the run.

## There is one pytest command, and it is slow

`testpaths` names all five suite directories, so a bare `pytest` is **the whole
suite** rather than a subset that looks green:

```
opstore/tests   core/tests   server/tests   contract/tests   tests/
```

`bench` is deliberately absent until it has tests, and
`tests/stage7h/test_test_hygiene.py` fails if any directory holding tests falls
outside that list. That test is what makes `testpaths` a guarantee rather than a
hope.

**Budget it in hours.** Around 6000 tests are selected by default and a great
many start a real subprocess — a `heph` verb, a Node sidecar, a `heph serve`, a
kernel build. Measured 2026-09-07 on a 14-core Linux host with a staged sidecar:
roughly **1000 tests in 90 minutes**, so a full pass lands in the 5–7 hour range.

That is a gate you run before a release or overnight, not an inner loop.

**CI is not faster; it is wider and parallel.** Each of the 19 jobs runs one
slice of the same suite.

## The inner loop

Name the directory or file you are working in:

```console
$ uv run pytest server/tests -q
$ uv run pytest tests/stage7h -q
$ uv run pytest core/tests/test_executor_worker.py -q
```

The default marker selection still applies, so a narrowed run is narrowed the
same way CI's stock lanes are.

## The suites

| Suite | Files | What it is |
| --- | --- | --- |
| `opstore/tests` | 11 | durability, with crash injection at 21 named points |
| `core/tests` | 85 | the CAD engine |
| `server/tests` | 88 | HTTP, MCP, bridge, dispatch — **sharded 3 ways in CI** |
| `contract/tests` | 2 | the tool declaration and its generated artifacts |
| `tests/stage*` | 183 | the staged gate clauses, across 25 stage directories |

A **gate clause is a testable sentence**, which is why the stage suites are
organised by gate rather than by module: the question they answer usually crosses
three modules.

### Two structural lanes worth knowing by name

Both assert something no functional test can see.

`tests/stage0a/test_cli_startup_budget.py` pins the CLI's **import closure**:
registering a verb may not pull the CAD kernel, the mesh or raster stacks, the
solver's numerics, or the MCP and web servers. The assertion is on **module names
in a subprocess, never on wall time** — wall time measures the runner, not the
boundary.

`tests/stage7h/` holds the configuration's own invariants: what is linted, what
is type-checked, where the pnpm pin comes from, and which directories a bare
`pytest` reaches.

## Markers: two groups deselected by default

```
addopts = -ra -m "not slow and not pinned_image" …
```

| Marker | What it is | Where it runs |
| --- | --- | --- |
| `slow` | wheel lanes: build every wheel, provision a venv | the release matrix, on the built artifact |
| `pinned_image` | renderer-pinned goldens | the `render goldens (pinned image)` CI job |

```console
$ uv run pytest -m slow              # the wheel lanes; minutes
$ uv run pytest -m pinned_image      # only inside the pinned CI image
```

**A `pinned_image` test fails by name off the pinned image rather than
skipping.** A golden is valid only for the (container image, renderer) pair it was
baselined on, and a suite that quietly passed on the wrong rasterizer would be
asserting nothing. `docker/ci/README.md` has the recipe for running them locally.

They are marked rather than skipped by default because they **must** be runnable
locally. Deselection is a default, not a prohibition.

## The timeout is a safety net, not a bound

```toml
timeout = 900
timeout_method = "signal"
```

This is **coarse on purpose**. A test that waits on another thread or process
bounds the wait *itself* and fails by name, naming the lock it was waiting on.
This ceiling exists only so that a wait nobody bounded dies with a **test name
attached** instead of as a job timeout.

`signal` fires SIGALRM in the test's own thread: it fails one test and lets the
run continue to its summary. The `thread` method dumps every stack and then
`os._exit(1)`s the whole pytest process, which would lose the summary and the
coverage data of every test after the hang.

900 s is generous on purpose: the longest legitimate single test in the tree is
a ~31 s kernel call.

## Linters take no path

Neither ruff nor pyright is given a path. `pyproject.toml` is the **only**
declaration of what they cover — a workflow step that spelled its own list is
exactly how the two drift.

## The Node suites

```console
$ cd agent && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test
$ cd web   && pnpm install && pnpm typecheck && pnpm test && pnpm lint
$ cd web   && pnpm test:e2e
```

Run pnpm from **inside** `agent/` or `web/`, never with `--dir`. Corepack resolves
`packageManager` by walking up from the current directory, so `--dir` finds no
field at the repository root and uses whatever corepack has activated.

`web`'s lint includes the five custom rules (`heph/no-derived-fact` plus four
design-system rules); `pnpm build` runs `tsc --noEmit` before `vite build`, so a
type error fails the build.

The bridge suites need a **staged** sidecar, not a built one. See
[work on the sidecar](work-on-the-sidecar.md).

## When something is red

Chase it to a root cause **before** retrying. In this repository, a concentrated
pass through nine reds that all looked like flakes found **nine real defects** —
a watchdog killing the whole sidecar over a mis-scoped budget, an admission slot
leak, fifteen unguarded shared-connection reads, a scroll handler misreading its
own programmatic scrolls.

The three readings of a failed check, in order of what to check first:

1. **The claim is wrong** — the test asserts something that was never true.
2. **The code is wrong** — the usual case, and the one worth the time.
3. **The environment is wrong** — see below.

### Environment failures that are not defects

| Symptom | Cause |
| --- | --- |
| stage-13C determinism times out (~244 s against a 60 s ceiling) | the machine is on battery; the CPU drops to ~1 GHz |
| `session.model.get: method not found` in an e2e run | the staged sidecar is older than `agent/` |
| a `pinned_image` test fails off the image | expected — it fails by name rather than skipping |

The 60 s solve ceiling is a **production** bound, and a suite that needs longer
declares its own budget rather than inheriting it. The ceiling is not what that
suite is testing.

## Related

- [Work on the sidecar](work-on-the-sidecar.md).
- [Release and package](release-and-package.md) — the `slow` lanes in anger.
- [Quality and risks](../05-architecture/quality-and-risks.md) — what the suites are for.
