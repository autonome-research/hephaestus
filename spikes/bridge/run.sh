#!/usr/bin/env bash
# Spike E runner: executes the bridge test suite in the isolated uv project
# and captures logs under out/ (gitignored).
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p out

{
  echo "date: $(date -Is)"
  echo "node: $(node --version)"
  echo "uv:   $(uv --version)"
  echo "python: $(uv run python -VV 2>&1 | head -1)"
  uv run python -c 'import pytest; print("pytest:", pytest.__version__)'
} > out/versions.log 2>&1

uv run pytest -v test_bridge.py 2>&1 | tee out/pytest.log
exit_code=${PIPESTATUS[0]}
echo "pytest exit code: ${exit_code}" | tee -a out/pytest.log

# Post-suite orphan sweep (belt-and-braces beyond per-test checks).
if pgrep -f "$(pwd)/node_sidecar.mjs" > out/orphans.log 2>&1; then
  echo "ORPHANS FOUND" | tee -a out/orphans.log
  exit 1
else
  echo "no orphan sidecars (pgrep -f found nothing)" | tee out/orphans.log
fi
exit "${exit_code}"
