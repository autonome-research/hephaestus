"""Offscreen renderer: llvmpipe render, cross-process determinism, fail-closed."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
from hephaestus.core.render.cameras import CameraFraming, camera_framing, parse_view
from hephaestus.core.render.offscreen import (
    ColoredMesh,
    OffscreenSession,
    RenderUnavailableError,
    software_egl_device,
)
from hephaestus.core.render.palette import id_to_rgb
from hephaestus.core.render.tessellate import face_trimesh, tessellate

_WORKER = textwrap.dedent(
    """
    import hashlib, sys
    from build123d import Box, Pos, Compound
    from hephaestus.core.render.tessellate import tessellate, face_trimesh
    from hephaestus.core.render.palette import id_to_rgb
    from hephaestus.core.render.cameras import parse_view, camera_framing
    from hephaestus.core.render.offscreen import (
        OffscreenSession, ColoredMesh, RenderUnavailableError,
    )

    try:
        comp = Compound(children=[Box(20, 10, 6), Pos(30, 0, 0) * Box(8, 8, 8)])
        tess = tessellate(comp)
        items = []
        sid = 1
        for solid in tess.solids:
            for face in solid.faces:
                items.append(ColoredMesh(mesh=face_trimesh(face), rgb=id_to_rgb(sid)))
                sid += 1
        framing = camera_framing(*tess.bounds(), parse_view("iso"), width=320, height=240)
        with OffscreenSession(320, 240) as sess:
            img = sess.render_flat(items, framing)
        sys.stdout.write("SHA " + hashlib.sha256(img.tobytes()).hexdigest() + "\\n")
        sys.stdout.write("NONBG " + str(int(img.any(axis=2).sum())) + "\\n")
        sys.stdout.write("GL " + sess.gl_renderer + "\\n")
    except RenderUnavailableError as exc:
        sys.stdout.write("UNAVAILABLE " + type(exc).__name__ + "\\n")
        sys.exit(3)
    """
)


def _run_worker(tmp_path: Path, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "render_worker.py"
    script.write_text(_WORKER)
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _sha_of(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("SHA "):
            return line[4:]
    raise AssertionError(f"no SHA in worker output:\n{output}")


def test_software_device_detected() -> None:
    # On this platform tier a software (llvmpipe) EGL device must exist.
    device = software_egl_device(refresh=True)
    assert device >= 0


def test_renders_on_this_machine_via_llvmpipe() -> None:
    comp_items, framing = _scene()
    with OffscreenSession(320, 240) as sess:
        assert "llvmpipe" in sess.gl_renderer.lower()
        img = sess.render_flat(comp_items, framing)
    assert img.shape == (240, 320, 3)
    assert img.dtype == np.uint8
    # Something was drawn (not an all-background frame).
    assert int(img.any(axis=2).sum()) > 0


def _scene() -> tuple[list[ColoredMesh], CameraFraming]:
    from build123d import Box, Compound, Pos

    comp = Compound(children=[Box(20, 10, 6), Pos(30, 0, 0) * Box(8, 8, 8)])
    tess = tessellate(comp)
    items: list[ColoredMesh] = []
    sid = 1
    for solid in tess.solids:
        for face in solid.faces:
            items.append(ColoredMesh(mesh=face_trimesh(face), rgb=id_to_rgb(sid)))
            sid += 1
    framing = camera_framing(*tess.bounds(), parse_view("iso"), width=320, height=240)
    return items, framing


def test_byte_identical_across_two_processes(tmp_path: Path) -> None:
    first = _run_worker(tmp_path / "a", {})
    second = _run_worker(tmp_path / "b", {})
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    sha_a = _sha_of(first.stdout)
    sha_b = _sha_of(second.stdout)
    assert sha_a == sha_b, f"non-deterministic render: {sha_a} != {sha_b}"
    assert "llvmpipe" in first.stdout.lower()


def test_fail_closed_when_device_forced_invalid(tmp_path: Path) -> None:
    result = _run_worker(tmp_path / "bad", {"HEPH_EGL_DEVICE": "99"})
    assert result.returncode == 3, f"expected fail-closed, got:\n{result.stdout}\n{result.stderr}"
    assert "UNAVAILABLE" in result.stdout


def test_fail_closed_on_non_integer_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEPH_EGL_DEVICE", "not-an-index")
    with pytest.raises(RenderUnavailableError):
        software_egl_device(refresh=True)


def test_zero_dimensions_rejected() -> None:
    with pytest.raises(RenderUnavailableError):
        OffscreenSession(0, 100)
