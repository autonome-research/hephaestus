#!/usr/bin/env bash
# Spike A determinism harness: run box_build.py twice in separate processes,
# assert metric hashes identical, report byte-identity of STEP/STL.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
mkdir -p out
$PY box_build.py out/run1 > out/box_run1.log 2>&1 || { echo "run1 FAILED"; exit 1; }
$PY box_build.py out/run2 > out/box_run2.log 2>&1 || { echo "run2 FAILED"; exit 1; }

$PY - <<'EOF'
import json, sys
r1 = json.load(open("out/run1/report.json"))
r2 = json.load(open("out/run2/report.json"))
def cmp(k):
    same = r1[k] == r2[k]
    print(f"{k}: run1={r1[k][:16]}... run2={r2[k][:16]}... identical={same}")
    return same
ok_metrics = cmp("metrics_sha256")
step_raw = cmp("step_sha256_raw")
step_norm = cmp("step_sha256_normalized")
stl = cmp("stl_sha256")
assert ok_metrics, "METRIC HASHES DIFFER — determinism FAILED"
print("RESULT: metrics deterministic =", ok_metrics,
      "| STEP raw byte-identical =", step_raw,
      "| STEP normalized-body identical =", step_norm,
      "| STL byte-identical =", stl)
EOF
