<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Running the renderer-pinned suites locally

Three suites are baselined against **this image's** renderer and refuse by name
on any other (`repo_conventions.md` Tier 2 disposition 2, `INTERFACE.md` §14):

| Suite | Where `ci.yml` runs it |
|---|---|
| `tests/render` | `render goldens (pinned image)` |
| `tests/stage4/test_g4_section_golden.py` | `render goldens (pinned image)` |
| `pnpm --dir web test:e2e` | `render goldens (pinned image)` |

The stock-runner jobs exclude all three **by name**. A developer host that
ships a different Mesa therefore *cannot* pass the first two, and that is the
design — see `tests/stage4/test_g4_section_golden.py`'s module docstring and
`web/e2e/README.md`. Reproduce a red locally by running it in this image, never
by re-baselining on the host; a digest bump is a renderer re-baseline PR.

## The one hazard: the container writes into your worktree

`docker run -v "$PWD:/w"` gives the container write access to the checkout, and
every toolchain in it will take that access unless told otherwise. Observed on
this repository:

- `uv run` without `UV_PROJECT_ENVIRONMENT` creates `/w/.venv` **as root**,
  replacing the host virtualenv; host `uv run` then dies with
  `failed to remove directory .venv/bin: Permission denied`.
- `pnpm` without a store dir writes a root-owned `.pnpm-store/` into the mount,
  and every `node_modules/` it creates is root-owned too.
- Python bytecode caches travel **both ways** through the mount, and either
  direction makes a traceback name a path that does not exist on the machine
  reading it. Measured 2026-08-28:
  - container → host: the container writes `__pycache__/*.pyc` whose
    `co_filename` is the **container** path. They stay mtime-valid after the
    container exits, so a *later host* run reuses them and a host
    `tests/stage4` failure reported `/w/tests/stage4/test_g4_section_golden.py`.
  - host → container: a `.pyc` the **host** compiled earlier is still
    mtime-valid inside the container, which reads it and reports
    `/home/you/.../conftest.py` from a run that never touched your home
    directory. `PYTHONDONTWRITEBYTECODE=1` does **not** prevent this — it
    suppresses writes only, and this is a read.

  `PYTHONPYCACHEPREFIX=/tmp/pycache` closes both: it moves the whole cache tree
  off the mount, so the container neither writes into your worktree nor reads
  what your host left there. Prefer it over `PYTHONDONTWRITEBYTECODE`, which
  covers one direction of the two.

`ci.yml` never hits any of this because it runs on a throwaway checkout and
sets `npm_config_store_dir: /tmp/pnpm-store`. A local run on your real worktree
must move that state out of the mount itself.

## The pnpm version the container actually runs

The image bakes `corepack prepare pnpm@10.18.3 --activate`
(`docker/ci/Dockerfile`), and that is what `pnpm` in this container *is* —
`agent/package.json` and `web/package.json` declaring
`"packageManager": "pnpm@10.34.5"` does not by itself change it. Two mechanisms
could raise it, and inside this container neither fires:

- **corepack resolves `packageManager` by walking up from the current
  directory**, not from `--dir`. The recipe runs `-w /w`, and the repository
  root deliberately has no `package.json` (there is no root pnpm workspace —
  `.github/workflows/ci.yml` records why), so `pnpm --dir agent install` gives
  corepack nothing to resolve and it falls back to the activated version.
  Measured 2026-09-03: from a directory with no manifest `corepack pnpm
  --version` printed corepack's activated default; from a directory whose
  `package.json` pins 10.34.5 it printed `10.34.5`.
- **pnpm does not switch versions when corepack invoked it.** The self-switch is
  gated on `!isExecutedByCorepack()` — that is `COREPACK_ROOT` being absent from
  the environment — in pnpm 10.34.5's `dist/pnpm.cjs`, and pnpm says so in its
  own words: *"Corepack invoked pnpm with this version, and pnpm does not switch
  versions when running under corepack."* A pnpm invoked **directly** does
  honour the field, including across `--dir` (measured with pnpm 11.25.0 against
  a package pinning 10.34.5: the install re-executed as `v10.34.5`). That is how
  the stock-runner jobs land on the pin. Nothing here invokes pnpm directly.

`ci.yml` escapes all of this only because it activates the pin explicitly, as
its own first step in this job, before any pnpm command:

```
- run: corepack prepare "pnpm@${PNPM_VERSION}" --activate
```

A local container run must do the same (or `cd agent`/`cd web` before each pnpm
command, so corepack has a manifest to read). Without it you get 10.18.3, which
has no `allowBuilds` support whatsoever — zero occurrences in its
`dist/pnpm.cjs` against 13 in 10.34.5's — so it reads no verdict from
`agent/pnpm-workspace.yaml` and skips esbuild's `postinstall` **silently**,
producing exactly the quietly under-built tree that `PNPM_VERSION`'s comment in
`ci.yml` records. Activating
the pin costs one download into the corepack cache under `HOME`, and the
recipe's `-e HOME=/tmp/h` is per-run, so that fetch repeats on every run.

`confirmModulesPurge: false` in `agent/pnpm-workspace.yaml` and
`web/pnpm-workspace.yaml` is read by both versions, so `pnpm install` stays
non-interactive either way; the recipe keeps `-e CI=true` because the rest of
the toolchain reads it.

Rebaking the image on 10.34.5 would remove both the extra step and the download.
It is a Dockerfile change and therefore a digest bump, so it belongs to a
re-baseline PR rather than to a local run.

## Recipe

Build once (the base is digest-pinned, so this reproduces the CI renderer):

```
docker build -t heph-ci-local -f docker/ci/Dockerfile .
```

Then run with every writable path pointed outside the mount, and with the same
security options the CI job declares — bubblewrap's escape probe errors without
them:

```
docker run --rm -v "$PWD:/w" -w /w \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined \
  --cap-add SYS_ADMIN \
  -e HOME=/tmp/h \
  -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  -e UV_LINK_MODE=copy \
  -e PYTHONPYCACHEPREFIX=/tmp/pycache \
  -e npm_config_store_dir=/tmp/pnpm-store \
  -e CI=true \
  heph-ci-local bash -lc '
    mkdir -p "$HOME" &&
    git config --global --add safe.directory /w &&
    uv sync --dev &&
    uv run pytest tests/stage4/test_g4_section_golden.py -q'
```

`PYTHONPYCACHEPREFIX` is what keeps bytecode from crossing the mount in either
direction; the other three keep the venv, the uv cache and the pnpm store off
it. The `mkdir -p "$HOME"` is not optional — the image has no
`/tmp/h`, and `git config --global` fails with `could not lock config file`
before anything else runs. Confirm the renderer matches the baseline before trusting
a green:

```
uv run python -c "from hephaestus.core.render.goldens import renderer_string; print(renderer_string())"
```

`llvmpipe (LLVM 20.1.2, 256 bits)` is the pin. Anything else and you have
rebuilt the image against a drifted base.

The recipe above runs no pnpm, so the version question does not touch it. The
e2e half does: it additionally needs a built sidecar and web bundle before it
will start (`heph serve --web` refuses without both). Follow the `render
goldens` job's step order in `.github/workflows/ci.yml` **including its first
step** — put

```
corepack prepare "pnpm@10.34.5" --activate &&
```

into the `bash -lc` block ahead of every pnpm command, or the container builds
the sidecar with 10.18.3 and its ignored install scripts. The version there is
`ci.yml`'s `PNPM_VERSION`, which is the same one the two `packageManager` fields
declare; if they have moved, that is the number to copy.

## Re-taking the Stage 12 pinned-image measurements

Four Stage 12 clauses (G12A.19, G12B.25, G12B.33, G12C.45) say their numbers are
measured **in the pinned image**, and their constants are derived from an
archived record rather than typed in (`MESH_INGEST.md` §Gates, "In the pinned
image, defined once"). This is the image that record must come from. Two
variables matter beyond the recipe above:

```
  -e HEPHAESTUS_CI_IMAGE_DIGEST=$(docker image inspect heph-ci-local --format '{{.Id}}')
  -e HEPHAESTUS_CI_IMAGE_REF='heph-ci-local — local build of docker/ci/Dockerfile'
```

Then `uv run python scripts/stage12_pinned_measure.py --write` (or `--check`,
which writes nothing and fails if the committed numbers no longer describe this
image). Without `HEPHAESTUS_CI_IMAGE_DIGEST` the script **refuses**: a
developer-host measurement may not be filed as an image one. The GHCR digest
`ci.yml` pins is the other route and is what the CI lane uses; a local build of
this **unchanged** Dockerfile is the route for a machine without
`read:packages`, and the record carries the Dockerfile's own `FROM` digest so a
base bump invalidates it.

The container writes those records as **root** through the mount — see the
hazard section above, and `chown` them back before committing.

## After any container run on a real worktree

```
find . -xdev \! -user "$(id -u)" -not -path './.git/*'
```

must print nothing. If it does not, `sudo chown` it back and delete the
offending build state (`.venv`, `.pnpm-store`, `**/__pycache__`) before
trusting a host run.
