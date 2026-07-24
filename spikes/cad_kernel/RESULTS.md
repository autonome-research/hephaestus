# Spike A+C — CAD kernel determinism and OCCT sanity

Run date: 2026-07-24 · Host: Arch Linux (kernel 7.0.9), 24 cores, RTX 5070 Laptop GPU present but **not** required.
Reproduce with `./run_all.sh` (logs in `out/`, gitignored). Exact pins: `requirements.lock.txt`.

## Versions

| Component | Version |
|---|---|
| Python | 3.13.12 (CPython, uv-managed) |
| build123d | 0.11.1 |
| cadquery-ocp-novtk / cadquery-ocp-proxy | 7.9.3.1.1 (build123d 0.11.1 depends on the proxy/novtk split of `cadquery-ocp`; same OCP bindings, VTK-free) |
| OCCT (wrapped) | 7.9.3 (`OCP.__version__ == "7.9.3.1"`, STEP header says "Open CASCADE STEP processor 7.9") |
| trimesh / pyrender / PyOpenGL | 4.12.2 / 0.1.45 / 3.1.0 |
| matplotlib / scikit-image / numpy | 3.11.1 / 0.26.0 / 2.5.1 |
| Software GL | Mesa llvmpipe (LLVM 22.1.5, 256 bits) via EGL surfaceless |

## A. Build/export determinism (`box_build.py`, `run_determinism.sh`)

Parametric box 80×60×30, R4 vertical-edge fillets, Ø12 through hole. Two separate processes:

- **Metrics hash** (volume, area, bbox at 9 decimals + solid/face/edge counts): sha256 **identical**.
- **STL bytes**: sha256 **identical** (binary STL, tol 1e-3 / 0.1 rad).
- **STEP bytes**: **NOT byte-identical raw** — the only diff is the `FILE_NAME` header timestamp (`2026-07-24T09:07:53` vs `...:55`; see `out/step_diff.log`). After normalizing the timestamp + `FILE_NAME` first arg, the **body is byte-identical**.
- Finding for CI: hash STL raw; hash STEP through the header normalizer in `box_build.py::normalize_step` (or diff from line 5 down).

## B. Rendering determinism (`render_box.py`, `run_render_determinism.sh`)

Offscreen, windowless, via pyrender `OffscreenRenderer` 640×480 of the exported STL:

| Backend | Works headless | Two-process result |
|---|---|---|
| pyrender + EGL, default device (NVIDIA GPU here) | yes | SSIM 1.000000 but **not reliably byte-identical** (one run pair had 2 pixels off by 1) |
| **pyrender + EGL, llvmpipe software device** (`PYOPENGL_PLATFORM=egl` + `EGL_DEVICE_ID=<llvmpipe idx>`) | yes | **byte-identical PNGs**, SSIM 1.0 — chosen CI renderer |
| pyrender + osmesa | no (libOSMesa not installed; would need the OSMesa shared lib in the CI image) | n/a |
| matplotlib Agg 3D fallback | yes | byte-identical PNGs, SSIM 1.0 |

**CI renderer choice: pyrender+EGL on Mesa llvmpipe.** On a GPU-less CI image llvmpipe is EGL device 0 (no `EGL_DEVICE_ID` needed); on developer machines with a GPU, set `EGL_DEVICE_ID` to the llvmpipe device (index 1 here). `LIBGL_ALWAYS_SOFTWARE=1` alone does **not** stop the NVIDIA EGL driver from being picked — device selection is the reliable mechanism. matplotlib-Agg is a proven deterministic fallback.

## C. OCCT sanity (`occt_sanity.py`) — 10-min budget, actual total ≈ 0.9 s compute / 3.2 s process

| Check | Result | Wall time |
|---|---|---|
| (a) oversized fillet (R1000 on 10 mm box) | fails as required. build123d raises `ValueError("Failed creating a fillet with radius of 1000.0, try a smaller value or use max_fillet()...")`; raw OCP raises `OCP.StdFail.StdFail_NotDone: "BRep_API: command not done"` | 0.01 s |
| (b) boolean union, 30 overlapping boxes (sequential fuse, worst case) | 1 result solid, volume 17176.0 | 0.77 s fuse (+0.04 s build) |
| (c) STEP round-trip, nontrivial part (filleted plate + 3×2 hole grid + boss + top fillet) | 1 solid out = 1 solid in; volume rel diff 4.8e-15 (≪ 1e-3) | export 0.010 s, import 0.017 s |

Against `verification.md` budgets (shelf full build ≤ 30 s class): every operation here is 1–3 orders of magnitude inside budget; the whole sanity suite fits in ~3 s of a 600 s budget. Exit code 0.

## Caveats

- OSMesa backend untested (shared lib absent); EGL/llvmpipe removes the need for it, but the CI image must ship Mesa with the surfaceless EGL platform.
- GPU determinism (byte-level) should be considered unreliable; always pin the software device in CI.
- `cadquery-ocp` proper was not installed; build123d 0.11.1 resolves to `cadquery-ocp-proxy`→`cadquery-ocp-novtk` 7.9.3.1.1, which is the same OCP binding distribution without VTK.
