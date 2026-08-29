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
- `pnpm` without a store dir writes a root-owned `.pnpm-store/`, and the
  container's `corepack` will pull its own pnpm over the repo pin into
  `agent/node_modules`.
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

The e2e half additionally needs a built sidecar and web bundle before it will
start (`heph serve --web` refuses without both) — follow the `render goldens`
job's step order in `.github/workflows/ci.yml`.

## After any container run on a real worktree

```
find . -xdev \! -user "$(id -u)" -not -path './.git/*'
```

must print nothing. If it does not, `sudo chown` it back and delete the
offending build state (`.venv`, `.pnpm-store`, `**/__pycache__`) before
trusting a host run.
