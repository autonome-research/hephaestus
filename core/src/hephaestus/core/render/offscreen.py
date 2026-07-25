"""Headless offscreen renderer, hard-pinned to surfaceless EGL + Mesa llvmpipe.

Determinism (arch §3.3, Stage S disposition 2) requires the software rasterizer:
``LIBGL_ALWAYS_SOFTWARE`` alone does not stop a GPU EGL driver being chosen, so
this module **enumerates EGL devices and selects the llvmpipe (software) one by
its GL_RENDERER string**, exporting its index as ``EGL_DEVICE_ID`` before
pyrender creates the context (pyrender reads that variable). ``HEPH_EGL_DEVICE``
overrides the scan. If no software EGL device exists, or the created context is
not software, rendering fails closed with :class:`RenderUnavailableError`.

Two render paths:

- :meth:`OffscreenSession.render_flat` uses pyrender's segmentation pass — MSAA
  disabled, one flat colour per scene node, no lighting — giving the exact,
  non-antialiased palette colours the mask/selection passes require.
- :meth:`OffscreenSession.render_shaded` is the ordinary lit ``rgb`` channel.

Renders are byte-identical across processes on this platform tier.
"""

# The EGL/pyrender/OpenGL stacks ship no type stubs; the reportUnknown*
# relaxations are declared for this package in root pyproject
# executionEnvironments (see interface notes), mirroring kernel/executor.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

import numpy as np
from hephaestus.core.render.cameras import CameraFraming
from numpy.typing import NDArray

__all__ = [
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "DEVICE_ENV_VAR",
    "ColoredMesh",
    "OffscreenSession",
    "RenderUnavailableError",
    "software_egl_device",
]

DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 720

#: Environment override for the EGL device index (skips the software scan).
DEVICE_ENV_VAR = "HEPH_EGL_DEVICE"

#: GL_RENDERER substrings that identify a Mesa software rasterizer.
_SOFTWARE_MARKERS = ("llvmpipe", "softpipe", "swrast")

_EGL_PLATFORM_DEVICE_EXT = 0x313F


class RenderUnavailableError(RuntimeError):
    """No usable software EGL device / context (fail-closed rendering)."""


def _egl_proc(name: str, restype: Any, argtypes: list[Any]) -> Any:
    lib = ctypes.CDLL("libEGL.so.1")
    lib.eglGetProcAddress.restype = ctypes.c_void_p
    lib.eglGetProcAddress.argtypes = [ctypes.c_char_p]
    address = lib.eglGetProcAddress(name.encode("ascii"))
    if not address:
        return None
    return ctypes.CFUNCTYPE(restype, *argtypes)(address)


def _scan_egl_renderers_here() -> list[str]:
    """GL_RENDERER string per EGL device, indexed like pyrender's enumeration.

    Enumerating devices creates and tears down throwaway EGL contexts, which
    leaves PyOpenGL's global GL-extension querier in a state that breaks a
    subsequent pyrender context in the **same** process. It is therefore only
    ever run inside the throwaway child spawned by :func:`_scan_egl_renderers`,
    never in a process that will go on to render.

    Returns an empty list when the device-enumeration extension is unavailable
    (e.g. a minimal CI image where llvmpipe is simply device 0); callers then
    fall back to device 0 and verify the created context is software.
    """
    from OpenGL import EGL, GL

    device_t = ctypes.c_void_p
    query_devices = _egl_proc(
        "eglQueryDevicesEXT",
        EGL.EGLBoolean,
        [EGL.EGLint, ctypes.POINTER(device_t), ctypes.POINTER(EGL.EGLint)],
    )
    get_platform_display = _egl_proc(
        "eglGetPlatformDisplayEXT",
        EGL.EGLDisplay,
        [ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(EGL.EGLint)],
    )
    if query_devices is None or get_platform_display is None:
        return []

    max_devices = 16
    devices = (device_t * max_devices)()
    count = EGL.EGLint(0)
    if not query_devices(max_devices, devices, ctypes.byref(count)):
        return []

    renderers: list[str] = []
    for index in range(count.value):
        display = get_platform_display(_EGL_PLATFORM_DEVICE_EXT, devices[index], None)
        renderer = ""
        if display:
            major, minor = EGL.EGLint(), EGL.EGLint()
            if EGL.eglInitialize(display, major, minor):
                EGL.eglBindAPI(EGL.EGL_OPENGL_API)
                attributes = [
                    EGL.EGL_SURFACE_TYPE,
                    EGL.EGL_PBUFFER_BIT,
                    EGL.EGL_RENDERABLE_TYPE,
                    EGL.EGL_OPENGL_BIT,
                    EGL.EGL_RED_SIZE,
                    8,
                    EGL.EGL_GREEN_SIZE,
                    8,
                    EGL.EGL_BLUE_SIZE,
                    8,
                    EGL.EGL_NONE,
                ]
                attribute_array = (EGL.EGLint * len(attributes))(*attributes)
                configs = (EGL.EGLConfig * 1)()
                num_config = (EGL.EGLint * 1)()
                if EGL.eglChooseConfig(display, attribute_array, configs, 1, num_config) and (
                    num_config[0] >= 1
                ):
                    context = EGL.eglCreateContext(display, configs[0], EGL.EGL_NO_CONTEXT, None)
                    if context and EGL.eglMakeCurrent(
                        display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, context
                    ):
                        raw = GL.glGetString(GL.GL_RENDERER)
                        if raw is not None:
                            renderer = bytes(raw).decode("ascii", "replace")
                        EGL.eglMakeCurrent(
                            display,
                            EGL.EGL_NO_SURFACE,
                            EGL.EGL_NO_SURFACE,
                            EGL.EGL_NO_CONTEXT,
                        )
                EGL.eglTerminate(display)
        renderers.append(renderer)
    return renderers


def _is_software(renderer: str) -> bool:
    lowered = renderer.lower()
    return any(marker in lowered for marker in _SOFTWARE_MARKERS)


_SCAN_MARKER = "EGLDEV"


def _emit_scan() -> None:
    """Child entry point: print one ``EGLDEV\\t<index>\\t<renderer>`` line/device."""
    for index, renderer in enumerate(_scan_egl_renderers_here()):
        sys.stdout.write(f"{_SCAN_MARKER}\t{index}\t{renderer}\n")


def _scan_egl_renderers() -> list[str]:
    """Enumerate EGL renderers in a throwaway child (keeps this process clean).

    Returns an empty list when enumeration is unavailable or the child fails,
    so callers fall back to device 0 and rely on context-creation verification.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "hephaestus.core.render.offscreen"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    renderers: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0] == _SCAN_MARKER:
            renderers.append(parts[2])
    return renderers


_cached_device: int | None = None


def software_egl_device(*, refresh: bool = False) -> int:
    """The EGL device index of the software rasterizer (llvmpipe).

    Honours ``HEPH_EGL_DEVICE`` verbatim (validated as an int). Otherwise scans
    the EGL devices for a software renderer; when enumeration is unavailable it
    returns ``0`` (the software device on GPU-less images) and leaves final
    verification to context creation. Raises :class:`RenderUnavailableError`
    when a scan finds only hardware devices.
    """
    global _cached_device
    override = os.environ.get(DEVICE_ENV_VAR)
    if override is not None:
        try:
            return int(override)
        except ValueError as exc:
            raise RenderUnavailableError(
                f"{DEVICE_ENV_VAR}={override!r} is not an integer device index"
            ) from exc
    if _cached_device is not None and not refresh:
        return _cached_device
    renderers = _scan_egl_renderers()
    if not renderers:
        _cached_device = 0
        return 0
    for index, renderer in enumerate(renderers):
        if _is_software(renderer):
            _cached_device = index
            return index
    raise RenderUnavailableError(
        "no software (llvmpipe) EGL device found; available renderers: "
        + "; ".join(f"[{i}] {r or '?'}" for i, r in enumerate(renderers))
    )


@dataclass(frozen=True)
class ColoredMesh:
    """A trimesh geometry plus the flat RGB colour of its selection pass."""

    mesh: Any  # trimesh.Trimesh
    rgb: tuple[int, int, int]


class OffscreenSession:
    """A pyrender ``OffscreenRenderer`` pinned to the software EGL device.

    Construction selects and validates the device (fail-closed) and creates the
    GL context. Reuse one session for many renders; call :meth:`close` when done
    (also usable as a context manager).
    """

    def __init__(self, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> None:
        if width <= 0 or height <= 0:
            raise RenderUnavailableError("viewport dimensions must be positive")
        self.width = width
        self.height = height
        device = software_egl_device()
        os.environ["EGL_DEVICE_ID"] = str(device)
        import pyrender

        # pyrender is untyped; keep the handle as Any so ``close()`` may null it.
        self._renderer: Any = None
        self.gl_renderer: str = ""
        try:
            self._renderer = pyrender.OffscreenRenderer(width, height)
        except Exception as exc:  # pragma: no cover - device-specific
            raise RenderUnavailableError(f"could not create offscreen renderer: {exc}") from exc
        self._validate_software()

    def _validate_software(self) -> None:
        """Force context creation and reject a non-software renderer."""
        import pyrender

        probe = pyrender.Scene(bg_color=[0, 0, 0, 0], ambient_light=[0, 0, 0])
        camera = pyrender.OrthographicCamera(xmag=1.0, ymag=1.0)
        probe.add(camera, pose=np.eye(4))
        try:
            self._renderer.render(probe, flags=_seg_flags())
        except Exception as exc:
            self.close()
            raise RenderUnavailableError(
                f"software EGL device {os.environ.get('EGL_DEVICE_ID')!r} unusable: {exc}"
            ) from exc
        from OpenGL import GL

        raw = GL.glGetString(GL.GL_RENDERER)
        renderer = bytes(raw).decode("ascii", "replace") if raw is not None else ""
        if not _is_software(renderer):
            self.close()
            raise RenderUnavailableError(
                f"EGL device {os.environ.get('EGL_DEVICE_ID')!r} is not a software "
                f"rasterizer (GL_RENDERER={renderer!r}); renders would be non-deterministic"
            )
        self.gl_renderer = renderer

    def render_flat(
        self,
        items: list[ColoredMesh],
        framing: CameraFraming,
    ) -> NDArray[np.uint8]:
        """Non-antialiased flat ID pass: each item painted its exact RGB colour.

        Returns an ``(H, W, 3)`` uint8 array; the background is ``(0, 0, 0)``.
        """
        import pyrender

        scene = pyrender.Scene(bg_color=[0, 0, 0, 0], ambient_light=[0, 0, 0])
        seg_node_map: dict[Any, NDArray[np.uint8]] = {}
        for item in items:
            mesh = pyrender.Mesh.from_trimesh(item.mesh, smooth=False)
            node = scene.add(mesh)
            seg_node_map[node] = np.array(item.rgb, dtype=np.uint8)
        self._add_camera(scene, framing)
        color, _depth = self._renderer.render(scene, flags=_seg_flags(), seg_node_map=seg_node_map)
        return np.ascontiguousarray(color[:, :, :3], dtype=np.uint8)

    def render_flat_lines(
        self,
        items: list[ColoredMesh],
        framing: CameraFraming,
    ) -> NDArray[np.uint8]:
        """Flat ID pass for edge polylines (a separate, faces-free layer)."""
        import pyrender

        scene = pyrender.Scene(bg_color=[0, 0, 0, 0], ambient_light=[0, 0, 0])
        seg_node_map: dict[Any, NDArray[np.uint8]] = {}
        for item in items:
            node = scene.add(item.mesh)
            seg_node_map[node] = np.array(item.rgb, dtype=np.uint8)
        self._add_camera(scene, framing)
        color, _depth = self._renderer.render(scene, flags=_seg_flags(), seg_node_map=seg_node_map)
        return np.ascontiguousarray(color[:, :, :3], dtype=np.uint8)

    def render_shaded(
        self,
        meshes: list[Any],
        framing: CameraFraming,
        *,
        background: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    ) -> NDArray[np.uint8]:
        """Ordinary lit ``rgb`` channel: returns an ``(H, W, 4)`` RGBA array."""
        import pyrender
        from pyrender.constants import RenderFlags

        scene = pyrender.Scene(bg_color=list(background), ambient_light=[0.35, 0.35, 0.35])
        for mesh in meshes:
            scene.add(pyrender.Mesh.from_trimesh(mesh, smooth=False))
        camera_pose = self._add_camera(scene, framing)
        light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
        scene.add(light, pose=camera_pose)
        color, _depth = self._renderer.render(scene, flags=RenderFlags.RGBA)
        return np.ascontiguousarray(color, dtype=np.uint8)

    def _add_camera(self, scene: Any, framing: CameraFraming) -> NDArray[np.float64]:
        import pyrender

        camera = pyrender.OrthographicCamera(
            xmag=framing.xmag, ymag=framing.ymag, znear=framing.znear, zfar=framing.zfar
        )
        scene.add(camera, pose=framing.pose)
        return framing.pose

    def close(self) -> None:
        renderer = getattr(self, "_renderer", None)
        if renderer is not None:
            renderer.delete()
            self._renderer = None

    def __enter__(self) -> OffscreenSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _seg_flags() -> Any:
    from pyrender.constants import RenderFlags

    return RenderFlags.SEG


def line_mesh(points: NDArray[np.float64]) -> Any:
    """A pyrender line-strip ``Mesh`` for one edge polyline (SEG-coloured)."""
    import pyrender
    from pyrender.constants import GLTF

    segments: list[NDArray[np.float64]] = []
    for i in range(len(points) - 1):
        segments.append(points[i])
        segments.append(points[i + 1])
    positions = np.array(segments, dtype=np.float64) if segments else points
    primitive = pyrender.Primitive(positions=positions, mode=GLTF.LINES)
    return pyrender.Mesh(primitives=[primitive])


if __name__ == "__main__":  # throwaway EGL-enumeration child (see _scan_egl_renderers)
    _emit_scan()
