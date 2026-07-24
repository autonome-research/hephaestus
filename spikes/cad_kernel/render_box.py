"""Spike A rendering determinism: offscreen software render of the box mesh.

Backend: pyrender + EGL, forced to Mesa software rasterization
(LIBGL_ALWAYS_SOFTWARE=1) so no GPU is required — this is the CI-viable path.
Fallback (if pyrender/EGL unavailable): matplotlib 3D projection (Agg).

Usage: python render_box.py <stl_path> <out_png>
Prints JSON: {backend, gl_renderer, png_sha256}
"""

import hashlib
import json
import os
import sys

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")  # force llvmpipe, no GPU

import numpy as np


def render_pyrender_egl(stl_path: str, out_png: str) -> dict:
    import trimesh
    import pyrender
    from PIL import Image

    m = trimesh.load(stl_path)
    scene = pyrender.Scene(bg_color=[255, 255, 255, 255], ambient_light=[0.3, 0.3, 0.3])
    scene.add(pyrender.Mesh.from_trimesh(m))
    cam = pyrender.PerspectiveCamera(yfov=1.0)
    pose = np.array(
        [
            [0.7071, -0.5, 0.5, 100.0],
            [0.7071, 0.5, -0.5, -100.0],
            [0.0, 0.7071, 0.7071, 140.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    scene.add(cam, pose=pose)
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
    scene.add(light, pose=pose)
    r = pyrender.OffscreenRenderer(640, 480)
    color, _depth = r.render(scene)

    # Capture the actual GL renderer string (proves software rasterization)
    from OpenGL import GL

    gl_renderer = GL.glGetString(GL.GL_RENDERER).decode()
    r.delete()
    Image.fromarray(color).save(out_png)
    return {"backend": "pyrender+egl", "gl_renderer": gl_renderer}


def render_matplotlib(stl_path: str, out_png: str) -> dict:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import trimesh

    m = trimesh.load(stl_path)
    fig = plt.figure(figsize=(6.4, 4.8), dpi=100)
    ax = fig.add_subplot(projection="3d")
    tri = m.vertices[m.faces]
    ax.add_collection3d(Poly3DCollection(tri, facecolor="tab:blue", edgecolor="k", lw=0.1))
    lim = np.abs(m.vertices).max()
    ax.set_xlim(-lim, lim), ax.set_ylim(-lim, lim), ax.set_zlim(-lim, lim)
    fig.savefig(out_png, metadata={"Software": None})
    plt.close(fig)
    return {"backend": "matplotlib-agg-3d", "gl_renderer": "n/a (CPU rasterizer)"}


def main() -> int:
    stl_path, out_png = sys.argv[1], sys.argv[2]
    forced = os.environ.get("RENDER_BACKEND")  # "egl" | "mpl" | unset
    if forced == "mpl":
        info = render_matplotlib(stl_path, out_png)
    else:
        try:
            info = render_pyrender_egl(stl_path, out_png)
        except Exception as e:
            if forced == "egl":
                raise
            info = render_matplotlib(stl_path, out_png)
            info["egl_fallback_reason"] = f"{type(e).__name__}: {e}"
    with open(out_png, "rb") as f:
        info["png_sha256"] = hashlib.sha256(f.read()).hexdigest()
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
