"""Real EGL postconditions on persistent owners, not just destroy-call counts."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
from __future__ import annotations

import ctypes
import importlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.render import offscreen


@pytest.mark.parametrize("mode", ["success", "body", "validation", "false", "raise", "noop"])
def test_real_native_release(tmp_path: Path, mode: str) -> None:
    result = subprocess.run(
        [sys.executable, __file__, mode],
        capture_output=True,
        text=True,
        timeout=120,  # named child hang detector, not a performance budget
        check=False,
    )
    (tmp_path / f"native-{mode}.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_RELEASE_OK" in result.stdout


def _state() -> dict[str, int | None]:
    from OpenGL import EGL

    handles: dict[str, Any] = {
        "context": EGL.eglGetCurrentContext(),
        "display": EGL.eglGetCurrentDisplay(),
        "read": EGL.eglGetCurrentSurface(EGL.EGL_READ),
        "draw": EGL.eglGetCurrentSurface(EGL.EGL_DRAW),
    }
    return {name: ctypes.cast(value, ctypes.c_void_p).value for name, value in handles.items()}


def _render(session: offscreen.OffscreenSession) -> str:
    import hashlib

    import numpy as np
    import trimesh
    from hephaestus.core.render.cameras import camera_framing, parse_view

    mesh = trimesh.creation.box(extents=[20, 10, 6])
    framing = camera_framing(mesh.bounds[0], mesh.bounds[1], parse_view("iso"), width=64, height=48)
    image = session.render_flat([offscreen.ColoredMesh(mesh, (1, 2, 3))], framing)
    assert image.shape == (48, 64, 3) and int(image.any(axis=2).sum()) > 0
    assert set(map(tuple, np.unique(image.reshape(-1, 3), axis=0))) == {(0, 0, 0), (1, 2, 3)}
    assert "llvmpipe" in session.gl_renderer.lower()
    return hashlib.sha256(image.tobytes()).hexdigest()


def _persistent_owners(mode: str) -> None:
    import pyrender
    from OpenGL import EGL

    closed, peer_open, checked, peer_closed = (threading.Event() for _ in range(4))
    states: dict[str, dict[str, int | None]] = {}
    hashes: list[str] = []
    errors: list[BaseException] = []

    class InvalidAfterNativeValidation(offscreen.OffscreenSession):
        def _validate_software(self) -> None:
            super()._validate_software()
            hashes.append(_render(self))
            states["A-open"] = _state()
            raise ValueError("after real validation")

    def owner() -> None:
        try:
            if mode == "validation":
                with pytest.raises(ValueError, match="after real validation"):
                    InvalidAfterNativeValidation(64, 48)
            else:
                session = None
                try:
                    with offscreen.OffscreenSession(64, 48) as session:
                        states["A-open"] = _state()
                        hashes.append(_render(session))
                        if mode == "body":
                            # Actual pyrender render failure, no fake native handles.
                            session._renderer.render(pyrender.Scene())  # pyright: ignore[reportPrivateUsage]
                except ValueError as exc:
                    assert mode == "body" and "camera" in str(exc).lower()
                else:
                    assert mode == "success", "real body failure did not occur"
                assert session is not None
                session.close()  # successful explicit cleanup is idempotent
            states["A-closed"] = _state()
            closed.set()
            assert peer_open.wait(30), "peer failed to open"
            states["A-while-B-open"] = _state()
            # ReleaseThread resets the selected API. Also query the API that
            # owned our GL context, so a reset alone cannot hide its retention.
            assert EGL.eglBindAPI(EGL.EGL_OPENGL_API)
            states["A-GL-while-B-open"] = _state()
            checked.set()
            assert peer_closed.wait(30), "peer failed to close"
            with offscreen.OffscreenSession(64, 48) as reused:
                hashes.append(_render(reused))
            states["A-reused-closed"] = _state()
        except BaseException as exc:
            errors.append(exc)
        finally:
            closed.set()
            checked.set()

    def peer() -> None:
        try:
            assert closed.wait(30), "owner failed to close"
            with offscreen.OffscreenSession(64, 48) as session:
                states["B-open"] = _state()
                hashes.append(_render(session))
                peer_open.set()
                assert checked.wait(30), "owner failed to query post-close state"
            states["B-closed"] = _state()
        except BaseException as exc:
            errors.append(exc)
        finally:
            peer_open.set()
            peer_closed.set()

    threads = [threading.Thread(target=worker) for worker in (owner, peer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(50)
        assert not thread.is_alive(), "persistent native owner failed to join"
    print(json.dumps({"mode": mode, "states": states, "hashes": hashes}), flush=True)
    if errors:
        raise BaseExceptionGroup("native worker failures", errors)
    assert states["A-open"]["context"] and states["B-open"]["context"]
    assert states["A-open"]["display"] == states["B-open"]["display"]
    for name, state in states.items():
        if name not in {"A-open", "B-open"}:
            assert all(value is None for value in state.values()), (name, state)
    assert len(hashes) == 3 and len(set(hashes)) == 1


def _release_fault(mode: str) -> None:
    import gc

    importlib.import_module("pyrender")  # establish native import order
    from OpenGL import EGL

    calls: list[int] = []
    failure = RuntimeError("native release raised")

    def fail() -> bool:
        calls.append(threading.get_ident())
        if mode == "raise":
            raise failure
        return mode == "noop"  # true without release must fail the postcondition

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(EGL, "eglReleaseThread", fail)
        session = offscreen.OffscreenSession(64, 48)
        _render(session)
        with pytest.raises((RuntimeError, offscreen.RenderUnavailableError)) as caught, session:
            raise ValueError("body before failed release")
        assert isinstance(caught.value.__context__, ValueError)
        assert str(caught.value.__context__) == "body before failed release"
        if mode == "raise":
            assert caught.value is failure
        with pytest.raises(offscreen.RenderUnavailableError, match="cleanup"):
            session.close()
        errors: list[BaseException] = []

        def peer() -> None:
            try:
                offscreen.OffscreenSession(64, 48)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=peer)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "failed release leaked lifetime lock"
        assert len(errors) == 1 and isinstance(errors[0], offscreen.RenderUnavailableError)
        assert "previous" in str(errors[0]) and errors[0].__cause__ is caught.value
        del session
        gc.collect()
        assert calls == [threading.get_ident()], "release retried or ran off-owner"
        # The failed native ownership remains uncertain, never called clean.
        assert _state()["context"] is not None
        print(json.dumps({"mode": mode, "calls": calls, "state": _state()}), flush=True)


if __name__ == "__main__":
    selected = sys.argv[1]
    if selected in {"success", "body", "validation"}:
        _persistent_owners(selected)
    else:
        _release_fault(selected)
    print("NATIVE_RELEASE_OK", selected)
