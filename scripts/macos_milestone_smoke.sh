#!/bin/sh
# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# Experimental acceptance entry point; never activates the production backend.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"
exec /opt/homebrew/opt/python@3.13/bin/python3.13 "$ROOT/scripts/macos_milestone_smoke.py" "$@"
