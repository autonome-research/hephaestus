#!/usr/bin/env bash
# Render the box twice in separate processes with each viable backend and
# compare PNG bytes + SSIM.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
mkdir -p out

# egl        : default EGL device (may be a GPU on a workstation)
# egl_sw     : EGL device forced to the Mesa llvmpipe software rasterizer
#              (EGL_DEVICE_ID picks it; on GPU-less CI it is device 0)
# mpl        : matplotlib Agg 3D fallback, pure CPU
for backend in egl egl_sw mpl; do
  echo "=== backend: $backend ==="
  extra_env=""
  mode=$backend
  if [ "$backend" = "egl_sw" ]; then mode=egl; extra_env="EGL_DEVICE_ID=${EGL_SW_DEVICE_ID:-1}"; fi
  env $extra_env RENDER_BACKEND=$mode $PY render_box.py out/run1/box.stl out/render_${backend}_1.png \
    > out/render_${backend}_1.log 2>&1 || { echo "$backend render1 FAILED"; cat out/render_${backend}_1.log; continue; }
  env $extra_env RENDER_BACKEND=$mode $PY render_box.py out/run1/box.stl out/render_${backend}_2.png \
    > out/render_${backend}_2.log 2>&1 || { echo "$backend render2 FAILED"; continue; }
  $PY - "$backend" <<'EOF'
import hashlib, json, sys
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
b = sys.argv[1]
p1, p2 = f"out/render_{b}_1.png", f"out/render_{b}_2.png"
b1, b2 = open(p1, "rb").read(), open(p2, "rb").read()
i1 = np.asarray(Image.open(p1).convert("RGB"), dtype=float)
i2 = np.asarray(Image.open(p2).convert("RGB"), dtype=float)
s = ssim(i1, i2, channel_axis=2, data_range=255)
info1 = json.load(open(f"out/render_{b}_1.log")) if False else None
print(f"backend={b} bytes_identical={b1 == b2} ssim={s:.6f} "
      f"sha1={hashlib.sha256(b1).hexdigest()[:16]} sha2={hashlib.sha256(b2).hexdigest()[:16]}")
EOF
done
