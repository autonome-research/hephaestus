"""Spike A: build a parametric box (fillet + hole) with build123d, export STEP/STL,
and emit deterministic hashes of geometry metrics and artifact bytes.

Usage: python box_build.py <out_subdir>
Writes <out_subdir>/box.step, <out_subdir>/box.stl, <out_subdir>/report.json
"""

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from build123d import (
    Axis,
    BuildPart,
    Box,
    Hole,
    export_step,
    export_stl,
    fillet,
)

L, W, H = 80.0, 60.0, 30.0
FILLET_R = 4.0
HOLE_D = 12.0


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def normalize_step(text: str) -> str:
    """Strip volatile fields from a STEP file: the FILE_NAME timestamp (and any
    embedded path), so only the geometric body is compared."""
    # FILE_NAME('name','2026-07-24T09:00:00',(...),...);  -> neutralize ts
    text = re.sub(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?",
        "TIMESTAMP",
        text,
    )
    # Neutralize the FILE_NAME first argument (may embed an absolute path)
    text = re.sub(r"FILE_NAME\('[^']*'", "FILE_NAME('NAME'", text)
    return text


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    with BuildPart() as bp:
        Box(L, W, H)
        fillet(bp.edges().filter_by(Axis.Z), radius=FILLET_R)
        Hole(radius=HOLE_D / 2)
    part = bp.part
    build_s = time.perf_counter() - t0

    bb = part.bounding_box()
    metrics = {
        "volume": f"{part.volume:.9f}",
        "area": f"{part.area:.9f}",
        "bbox_min": [f"{v:.9f}" for v in (bb.min.X, bb.min.Y, bb.min.Z)],
        "bbox_max": [f"{v:.9f}" for v in (bb.max.X, bb.max.Y, bb.max.Z)],
        "solids": len(part.solids()),
        "faces": len(part.faces()),
        "edges": len(part.edges()),
    }
    metrics_canon = json.dumps(metrics, sort_keys=True, separators=(",", ":"))
    metrics_hash = sha256_bytes(metrics_canon.encode())

    step_path = out / "box.step"
    stl_path = out / "box.stl"
    t1 = time.perf_counter()
    export_step(part, str(step_path))
    step_s = time.perf_counter() - t1
    t2 = time.perf_counter()
    export_stl(part, str(stl_path), tolerance=1e-3, angular_tolerance=0.1)
    stl_s = time.perf_counter() - t2

    step_bytes = step_path.read_bytes()
    stl_bytes = stl_path.read_bytes()
    report = {
        "metrics": metrics,
        "metrics_sha256": metrics_hash,
        "step_sha256_raw": sha256_bytes(step_bytes),
        "step_sha256_normalized": sha256_bytes(
            normalize_step(step_bytes.decode("utf-8", errors="replace")).encode()
        ),
        "stl_sha256": sha256_bytes(stl_bytes),
        "step_size": len(step_bytes),
        "stl_size": len(stl_bytes),
        "timings_s": {
            "build": round(build_s, 3),
            "export_step": round(step_s, 3),
            "export_stl": round(stl_s, 3),
        },
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
