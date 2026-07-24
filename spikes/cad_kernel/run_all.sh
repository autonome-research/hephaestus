#!/usr/bin/env bash
# Reproduce the entire cad_kernel spike from a clean checkout.
# Requires: uv, network (first run only). Logs land in out/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.13 .venv
  VIRTUAL_ENV=$PWD/.venv uv pip install -r requirements.lock.txt
fi

mkdir -p out
echo "== versions =="
.venv/bin/python -VV
VIRTUAL_ENV=$PWD/.venv uv pip list | grep -Ei "build123d|cadquery|trimesh|pyrender|matplotlib|scikit-image|numpy" | tee out/versions.log
.venv/bin/python -c "import OCP; print('OCP (OCCT) version:', OCP.__version__)" | tee -a out/versions.log

echo "== spike A: build/export determinism (two processes) =="
./run_determinism.sh | tee out/determinism_summary.log

echo "== spike A: render determinism (two processes per backend) =="
./run_render_determinism.sh | tee out/render_summary.log

echo "== spike C: OCCT sanity (10-min budget) =="
time .venv/bin/python occt_sanity.py | tee out/occt_sanity.log
echo "ALL DONE"
