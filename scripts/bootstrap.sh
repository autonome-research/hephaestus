#!/usr/bin/env bash
# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
#
# One idempotent command that takes a fresh clone to a fully built checkout:
# the Python workspace (`uv sync --dev`), the bundled Node sidecar staged into
# `hephaestus-server`, and — unless `--no-web` — the operator web client.
#
# It is safe to re-run. Every step is the same command `docs/install.md` and
# `CONTRIBUTING.md` tell you to run by hand; this script only finds the tools,
# reports *all* missing prerequisites at once, and runs the steps in order.
#
# Usage:
#   scripts/bootstrap.sh            # full build (Python + sidecar + web)
#   scripts/bootstrap.sh --no-web   # skip the optional operator web client
#   scripts/bootstrap.sh --check    # prerequisites only; changes nothing

set -euo pipefail

# ---------------------------------------------------------------- location --

# Resolve this script's directory through any symlinks without `readlink -f`,
# which is GNU-only. `heph` is often symlinked onto PATH, so this matters.
resolve_dir() {
	local source=$1 dir
	while [ -L "$source" ]; do
		dir=$(cd -P -- "$(dirname -- "$source")" && pwd -P)
		source=$(readlink -- "$source")
		case $source in
		/*) ;;
		*) source=$dir/$source ;;
		esac
	done
	cd -P -- "$(dirname -- "$source")" && pwd -P
}

SCRIPT_DIR=$(resolve_dir "${BASH_SOURCE[0]}")
REPO_ROOT=$(cd -P -- "$SCRIPT_DIR/.." && pwd -P)

# ------------------------------------------------------------------- output --

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
	C_BOLD=$(printf '\033[1m')
	C_DIM=$(printf '\033[2m')
	C_RED=$(printf '\033[31m')
	C_YELLOW=$(printf '\033[33m')
	C_OFF=$(printf '\033[0m')
else
	C_BOLD='' C_DIM='' C_RED='' C_YELLOW='' C_OFF=''
fi

say() { printf '%s\n' "$*"; }
info() { printf '%s==>%s %s\n' "$C_BOLD" "$C_OFF" "$*"; }
warn() { printf '%swarning:%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
die() {
	printf '%serror:%s %s\n' "$C_RED" "$C_OFF" "$*" >&2
	exit 1
}

# --------------------------------------------------------------------- args --

CHECK_ONLY=0
WITH_WEB=1

usage() {
	cat <<'USAGE'
bootstrap.sh — take a fresh Hephaestus clone to a fully built checkout.

  --check     Check prerequisites and report what is missing. Changes nothing.
  --no-web    Skip the optional operator web client (web/ install + build).
  -h, --help  This message.

Steps (all idempotent, all re-runnable):
  1. uv sync --dev                              the Python workspace
  2. (cd agent && pnpm install --frozen-lockfile)
  3. (cd agent && pnpm run bundle)              the bounded sidecar artifact
  4. uv run python scripts/stage_sidecar.py     stage it into hephaestus-server
  5. (cd web && pnpm install --frozen-lockfile) (both skipped by --no-web)
  6. (cd web && pnpm build)                     web/dist, for `heph serve --web`

The pnpm steps run from inside the package directory rather than with
`--dir`: `--dir` moves the install but not the version resolution, and corepack
picks the pinned `packageManager` by walking up from the current directory.
USAGE
}

while [ $# -gt 0 ]; do
	case $1 in
	--check) CHECK_ONLY=1 ;;
	--no-web) WITH_WEB=0 ;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		printf '%serror:%s unknown option: %s\n\n' "$C_RED" "$C_OFF" "$1" >&2
		usage >&2
		exit 2
		;;
	esac
	shift
done

# CI=true keeps pnpm non-interactive: without it, pnpm aborts rather than
# purging a stale node_modules and prompts about ignored build scripts. Both
# are exported here, before anything can invoke a package manager, rather than
# next to the build steps — `--check` must be as non-interactive as a full run.
export CI=true
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

# ------------------------------------------------------------- the pnpm pin --

# The pin has one home. `agent/package.json`'s `packageManager` field is the
# preferred one (it is what corepack reads); the CI workflow's `PNPM_VERSION` is
# the fallback, because that is where this repository currently states it. Read,
# never hardcoded here — a second copy of a version is a second thing to drift.
read_pnpm_pin() {
	local pin=''
	if [ -f "$REPO_ROOT/agent/package.json" ]; then
		pin=$(sed -n \
			's/.*"packageManager"[[:space:]]*:[[:space:]]*"pnpm@\([0-9][^"+]*\).*/\1/p' \
			"$REPO_ROOT/agent/package.json" | head -n 1)
	fi
	if [ -z "$pin" ] && [ -f "$REPO_ROOT/.github/workflows/ci.yml" ]; then
		pin=$(sed -n \
			's/^[[:space:]]*PNPM_VERSION:[[:space:]]*"\{0,1\}\([0-9][0-9.]*\)"\{0,1\}[[:space:]]*$/\1/p' \
			"$REPO_ROOT/.github/workflows/ci.yml" | head -n 1)
	fi
	printf '%s' "$pin"
}

PNPM_PIN=$(read_pnpm_pin)
[ -n "$PNPM_PIN" ] || die "could not read the pnpm pin from agent/package.json \
(\"packageManager\") or .github/workflows/ci.yml (PNPM_VERSION)"
PNPM_MAJOR=${PNPM_PIN%%.*}

# ------------------------------------------------------------ prerequisites --

MISSING=''
missing() { MISSING="${MISSING}  - $1"$'\n'; }

have() { command -v "$1" >/dev/null 2>&1; }

# Node >= 22.19 (repo_conventions.md; agent/ and web/ both declare it).
node_ok() {
	local raw major minor
	raw=$(node --version 2>/dev/null) || return 1
	raw=${raw#v}
	major=${raw%%.*}
	minor=${raw#*.}
	minor=${minor%%.*}
	case $major in *[!0-9]* | '') return 1 ;; esac
	case $minor in *[!0-9]* | '') return 1 ;; esac
	[ "$major" -gt 22 ] && return 0
	[ "$major" -eq 22 ] && [ "$minor" -ge 19 ]
}

info "checking prerequisites"

if have git; then
	say "    git       $(git --version 2>/dev/null | head -n 1)"
else
	missing "git — install it from your platform's usual source (https://git-scm.com/downloads)"
fi

if have uv; then
	say "    uv        $(uv --version 2>/dev/null | head -n 1)"
else
	missing "uv — install with: curl -LsSf https://astral.sh/uv/install.sh | sh   (https://docs.astral.sh/uv/)"
fi

# A Python uv can use. uv will not silently pick a 3.15+ or a 3.10; the
# workspace declares requires-python >=3.11,<3.15.
if have uv; then
	if PYTHON_FOUND=$(uv python find '>=3.11,<3.15' 2>/dev/null); then
		say "    python    $PYTHON_FOUND"
	else
		missing "a Python 3.11-3.14 that uv can use — install one with: uv python install 3.13"
	fi
fi

if node_ok; then
	say "    node      $(node --version)"
else
	if have node; then
		missing "Node >= 22.19 on PATH (found $(node --version 2>/dev/null)) — install 22.19+ from https://nodejs.org (or via mise/nvm/fnm)"
	else
		missing "Node >= 22.19 on PATH — install it from https://nodejs.org (or via mise/nvm/fnm)"
	fi
fi

# corepack ships a `pnpm` shim, so a `pnpm` on PATH is not necessarily a pnpm.
# The distinction matters, because pnpm deliberately does *not* self-switch to
# the pinned version when it is running under corepack (pnpm.cjs guards
# `switchCliVersion` on `COREPACK_ROOT == null`) — corepack must resolve the
# right version itself, from the nearest `packageManager` field.
#
# Reading the shim is free; running it is not. `pnpm --version` under corepack
# downloads a package manager before it can answer, which `--check` must not do.
pnpm_is_corepack_shim() {
	local path
	path=$(command -v pnpm 2>/dev/null) || return 1
	[ -n "$path" ] || return 1
	# corepack's shim is a four-line stub that requires corepack's own runtime;
	# a real pnpm's launcher never mentions it.
	grep -q corepack "$path" 2>/dev/null
}

# pnpm, in the documented order of preference. Resolved even under --check so
# the report says which one a real run would use. Nothing here downloads: the
# exact pnpm is settled per package by the `packageManager` field, on first use.
PNPM=()
PNPM_HOW=''
PNPM_PATH_VERSION=''
resolve_pnpm() {
	local major
	if have pnpm; then
		if pnpm_is_corepack_shim; then
			PNPM=(pnpm)
			PNPM_HOW="pnpm on PATH (corepack's shim; runs pnpm $PNPM_PIN per package)"
			return 0
		fi
		PNPM_PATH_VERSION=$(pnpm --version 2>/dev/null || true)
		major=${PNPM_PATH_VERSION%%.*}
		case $major in
		'' | *[!0-9]*) ;;
		*)
			# A pnpm at or above the pin's major re-execs the pinned version
			# itself, from the `packageManager` field of whichever package it is
			# run in — pnpm 10.18.3 and pnpm 11.25.0 both do, verified. Below
			# the pin's major it does not, and pnpm 9 does not even parse this
			# repository's `pnpm-workspace.yaml` ("packages field missing or
			# empty"), so an older pnpm falls through to corepack or npx.
			if [ "$major" -ge "$PNPM_MAJOR" ]; then
				PNPM=(pnpm)
				if [ "$PNPM_PATH_VERSION" = "$PNPM_PIN" ]; then
					PNPM_HOW="pnpm on PATH ($PNPM_PATH_VERSION, the pinned version)"
				else
					PNPM_HOW="pnpm on PATH ($PNPM_PATH_VERSION, re-execs pnpm $PNPM_PIN per package)"
				fi
				return 0
			fi
			;;
		esac
	fi
	if have corepack; then
		PNPM=(corepack pnpm)
		PNPM_HOW="corepack pnpm (fetches pnpm $PNPM_PIN on first use)"
		return 0
	fi
	if have npx; then
		PNPM=(npx --yes "pnpm@$PNPM_PIN")
		PNPM_HOW="npx --yes pnpm@$PNPM_PIN (downloaded on demand)"
		return 0
	fi
	return 1
}

if resolve_pnpm; then
	say "    pnpm      $PNPM_HOW"
	if [ -n "$PNPM_PATH_VERSION" ] && [ "${PNPM[0]}" != "pnpm" ]; then
		warn "the pnpm on PATH is $PNPM_PATH_VERSION, older than this repository's pin ($PNPM_PIN), and cannot re-exec it; using $PNPM_HOW instead"
	fi
else
	missing "pnpm $PNPM_PIN, or corepack, or npx — any Node >= 22.19 install ships npx; otherwise: npm install -g pnpm@$PNPM_PIN"
fi

# bubblewrap is not needed to build, but `heph build` refuses without it, so a
# checkout without it bootstraps fine and then fails at the first part script.
# It exists only on Linux; saying "install your distribution's package" on a
# Mac would be advice that cannot be followed.
case $(uname -s 2>/dev/null) in
Linux)
	if have bwrap; then
		say "    bwrap     $(bwrap --version 2>/dev/null | head -n 1)"
	else
		warn "bubblewrap (bwrap) not found. The build below will still succeed, but \`heph build\` refuses to run part scripts without an OS sandbox (sandbox_unavailable) — see docs/install.md. Install your distribution's 'bubblewrap' package when you need script execution."
	fi
	;;
*)
	say "    bwrap     n/a — sandboxed part scripts are Linux-only (docs/install.md); everything this script builds works here"
	;;
esac

if [ -n "$MISSING" ]; then
	printf '\n%serror:%s missing prerequisites:\n%s\n' "$C_RED" "$C_OFF" "$MISSING" >&2
	printf 'Install the above, then re-run: %s\n' "$SCRIPT_DIR/bootstrap.sh" >&2
	exit 1
fi

say ""
say "    repo      $REPO_ROOT"
if [ "$WITH_WEB" -eq 1 ]; then
	say "    web       yes"
else
	say "    web       skipped (--no-web)"
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
	say ""
	info "prerequisites OK (--check: nothing was built, nothing was downloaded)"
	exit 0
fi

# -------------------------------------------------------------------- build --

STEP_TOTAL=4
if [ "$WITH_WEB" -eq 1 ]; then
	STEP_TOTAL=6
fi
STEP_NUMBER=0

# Every step names its working directory. The pnpm steps run *in* `agent/` and
# `web/` rather than passing `--dir`, because `--dir` moves the install but not
# the version resolution: corepack picks the `packageManager` field by walking
# up from the current directory, so `corepack pnpm --dir agent install` from the
# repository root selects corepack's default pnpm and then dies with "This
# project is configured to use <pin> of pnpm ... pnpm does not switch versions
# when running under corepack". From inside `agent/` every lane — corepack, a
# corepack shim, a newer pnpm on PATH — converges on the pinned version.
run_step() {
	local name=$1 dir=$2
	shift 2
	STEP_NUMBER=$((STEP_NUMBER + 1))
	printf '\n%s==> [%d/%d] %s%s\n' "$C_BOLD" "$STEP_NUMBER" "$STEP_TOTAL" "$name" "$C_OFF"
	if [ "$dir" = "." ]; then
		printf '%s    $ %s%s\n' "$C_DIM" "$*" "$C_OFF"
	else
		printf '%s    $ (cd %s && %s)%s\n' "$C_DIM" "$dir" "$*" "$C_OFF"
	fi
	if ! (cd "$REPO_ROOT/$dir" && "$@"); then
		die "bootstrap failed at step $STEP_NUMBER/$STEP_TOTAL: $name"
	fi
}

cd "$REPO_ROOT"

run_step "the Python workspace" . uv sync --dev
run_step "the agent's Node dependencies" agent "${PNPM[@]}" install --frozen-lockfile
run_step "the bundled sidecar" agent "${PNPM[@]}" run bundle
run_step "staging the sidecar into hephaestus-server" . uv run python scripts/stage_sidecar.py

if [ "$WITH_WEB" -eq 1 ]; then
	run_step "the web client's dependencies" web "${PNPM[@]}" install --frozen-lockfile
	run_step "the web client bundle" web "${PNPM[@]}" build
fi

# --------------------------------------------------------------------- done --

HEPH_BIN="$REPO_ROOT/.venv/bin/heph"

cat <<DONE

$C_BOLD==> done$C_OFF

Run heph from anywhere, either way:

    $HEPH_BIN
    uv run --directory $REPO_ROOT heph

(\`uv run heph\` also works, but only from inside the clone. To put heph on
PATH, symlink the launcher: ln -s $SCRIPT_DIR/heph ~/bin/heph)

Next:

    heph init DIR                     # create a design project
    cd DIR && heph serve --web        # the operator workspace, from that project
    heph serve --web --project DIR    # the same, without the cd
DONE
