"""Whole EGL lifetimes, not individual render calls, own the shared display."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.render import offscreen


def test_competing_real_sessions_render_and_delete_on_owner_threads(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, __file__, "--real"],
        capture_output=True,
        text=True,
        timeout=90,  # named subprocess hang detector, not a performance budget
        check=False,
    )
    (tmp_path / "lifetime.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_LIFETIMES_OK" in result.stdout


def _real_lifetimes() -> None:
    import hashlib

    import numpy as np
    import trimesh
    from hephaestus.core.render.cameras import camera_framing, parse_view

    # The contender's acquisition attempt is a positive edge. On the old code
    # (no lifetime lock), signal after its validation instead: both contexts
    # are live, A terminates their display, B's real delete fails with 12289.
    attempted = threading.Event()
    closed = threading.Event()
    first_ready = threading.Event()
    errors: list[BaseException] = []
    hashes: list[str] = []
    events: list[str] = []
    # Scheduling seam delegates unchanged software validation in this child.
    real_validate = offscreen.OffscreenSession._validate_software  # pyright: ignore[reportPrivateUsage]
    patch = pytest.MonkeyPatch()
    lock = getattr(offscreen, "_session_lock", None)
    if lock is not None:

        class ObservedLock:
            def acquire(self) -> None:
                if threading.current_thread().name == "B":
                    attempted.set()
                lock.acquire()

            def release(self) -> None:
                lock.release()

        patch.setattr(offscreen, "_session_lock", ObservedLock())

    def validate(session: offscreen.OffscreenSession) -> None:
        real_validate(session)
        name = threading.current_thread().name
        events.append(f"{name}:created")
        if name == "B" and lock is None:
            attempted.set()
            assert closed.wait(30), "A did not close its real context"

    patch.setattr(offscreen.OffscreenSession, "_validate_software", validate)
    mesh = trimesh.creation.box(extents=[20, 10, 6])
    framing = camera_framing(mesh.bounds[0], mesh.bounds[1], parse_view("iso"), width=64, height=48)

    def run(name: str) -> None:
        try:
            if name == "B":
                assert first_ready.wait(30), "A did not create its context"
            with offscreen.OffscreenSession(64, 48) as session:
                assert "llvmpipe" in session.gl_renderer.lower()
                image = session.render_flat([offscreen.ColoredMesh(mesh, (1, 2, 3))], framing)
                assert image.shape == (48, 64, 3)
                assert int(image.any(axis=2).sum()) > 0
                assert set(map(tuple, np.unique(image.reshape(-1, 3), axis=0))) == {
                    (0, 0, 0),
                    (1, 2, 3),
                }
                hashes.append(hashlib.sha256(image.tobytes()).hexdigest())
                if name == "A":
                    first_ready.set()
                    assert attempted.wait(30), "B never attempted session acquisition"
            events.append(f"{name}:closed")
        except BaseException as exc:
            errors.append(exc)
        finally:
            if name == "A":
                closed.set()

    threads = [threading.Thread(target=run, args=(name,), name=name) for name in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(45)
        assert not thread.is_alive(), "real session worker did not finish"
    if errors:
        raise BaseExceptionGroup("real EGL lifetime failures", errors)
    # Record after delete but before release via validation ordering is tested
    # below with fault-controlled handles; thread scheduling may reorder these
    # post-close Python events, so only native success/identity is asserted here.
    assert len(hashes) == 2 and hashes[0] == hashes[1]
    print("REAL_LIFETIMES_OK", hashes, events)


@pytest.fixture
def fake_renderer(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    import pyrender

    handles: list[Any] = []

    class Renderer:
        def __init__(self, *_: object) -> None:
            self.deletes = 0
            self.failure: BaseException | None = None
            handles.append(self)

        def delete(self) -> None:
            self.deletes += 1
            if self.failure is not None:
                raise self.failure

    monkeypatch.setattr(pyrender, "OffscreenRenderer", Renderer)
    monkeypatch.setattr(offscreen, "software_egl_device", lambda: 0)

    def validated(self: offscreen.OffscreenSession) -> None:
        pass

    monkeypatch.setattr(offscreen.OffscreenSession, "_validate_software", validated)
    # This fixture owns fake handles only; real post-close state/faults are
    # exercised without this seam in test_render_native_release.py.
    monkeypatch.setattr(offscreen.OffscreenSession, "_release_native_thread", validated)
    # Fault cases poison only fake GL state; restore the module after each test.
    monkeypatch.setattr(offscreen, "_session_failure", None, raising=False)
    return handles


def test_nested_session_rejected_but_same_session_reuse_allowed(fake_renderer: list[Any]) -> None:
    with offscreen.OffscreenSession() as session:
        assert session.__enter__() is session
        with pytest.raises(offscreen.RenderUnavailableError, match="nested"):
            offscreen.OffscreenSession()
    session.close()
    assert fake_renderer[0].deletes == 1
    with offscreen.OffscreenSession():
        pass
    assert len(fake_renderer) == 2


@pytest.mark.parametrize("operation", ["close", "enter", "flat", "lines", "shaded"])
def test_cross_thread_operations_refused_before_gl(
    fake_renderer: list[Any], operation: str
) -> None:
    with offscreen.OffscreenSession() as session:
        errors: list[BaseException] = []

        def wrong_thread() -> None:
            try:
                if operation == "close":
                    session.close()
                elif operation == "enter":
                    session.__enter__()
                else:
                    method = {
                        "flat": session.render_flat,
                        "lines": session.render_flat_lines,
                        "shaded": session.render_shaded,
                    }[operation]
                    method([], None)  # type: ignore[arg-type]
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=wrong_thread)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "wrong-thread operation hung"
        assert len(errors) == 1
        assert isinstance(errors[0], offscreen.RenderUnavailableError)
        assert "owner thread" in str(errors[0])
        assert fake_renderer[0].deletes == 0
    assert fake_renderer[0].deletes == 1


def test_validation_failure_deletes_and_releases(
    fake_renderer: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(self: offscreen.OffscreenSession) -> None:
        raise ValueError("validation failed")

    with monkeypatch.context() as patch:
        patch.setattr(offscreen.OffscreenSession, "_validate_software", invalid)
        with pytest.raises(ValueError, match="validation failed"):
            offscreen.OffscreenSession()
    assert fake_renderer[0].deletes == 1
    with offscreen.OffscreenSession():
        pass


def test_body_failure_closes_and_releases(fake_renderer: list[Any]) -> None:
    with pytest.raises(ValueError, match="body"), offscreen.OffscreenSession():
        raise ValueError("body")
    assert fake_renderer[0].deletes == 1
    with offscreen.OffscreenSession():
        pass


def test_cleanup_failure_preserved_without_retry_and_future_admission_refused(
    fake_renderer: list[Any],
) -> None:
    failure = RuntimeError("delete failed")
    session = offscreen.OffscreenSession()
    with pytest.raises(RuntimeError, match="delete failed") as caught, session:
        fake_renderer[0].failure = failure
        raise ValueError("body also failed")
    assert caught.value is failure
    assert isinstance(failure.__context__, ValueError)
    with pytest.raises(offscreen.RenderUnavailableError, match="cleanup"):
        session.close()
    with pytest.raises(offscreen.RenderUnavailableError, match="previous"):
        offscreen.OffscreenSession()
    assert fake_renderer[0].deletes == 1
    assert len(fake_renderer) == 1


def test_closed_session_rejects_use(fake_renderer: list[Any]) -> None:
    session = offscreen.OffscreenSession()
    session.close()
    with pytest.raises(offscreen.RenderUnavailableError, match="closed"):
        session.__enter__()
    with pytest.raises(offscreen.RenderUnavailableError, match="closed"):
        session.render_flat([], None)  # type: ignore[arg-type]


def test_device_failure_releases_without_poisoning(
    fake_renderer: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> int:
        raise ValueError("device scan")

    with monkeypatch.context() as patch:
        patch.setattr(offscreen, "software_egl_device", fail)
        with pytest.raises(ValueError, match="device scan"):
            offscreen.OffscreenSession()
    with offscreen.OffscreenSession():
        pass
    assert len(fake_renderer) == 1


@pytest.mark.parametrize("failure", [RuntimeError("partial context"), KeyboardInterrupt()])
def test_constructor_failure_blocks_peers_without_lock_leak(
    fake_renderer: list[Any], monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    import pyrender

    def fail(*_: object) -> None:
        raise failure

    monkeypatch.setattr(pyrender, "OffscreenRenderer", fail)
    expected = offscreen.RenderUnavailableError if isinstance(failure, Exception) else type(failure)
    with pytest.raises(expected):
        offscreen.OffscreenSession()
    errors: list[BaseException] = []

    def peer() -> None:
        try:
            offscreen.OffscreenSession()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=peer)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), "failed constructor leaked lifetime lock"
    assert len(errors) == 1 and isinstance(errors[0], offscreen.RenderUnavailableError)
    assert "previous" in str(errors[0])
    assert errors[0].__cause__ is failure
    assert not fake_renderer


def test_validation_and_cleanup_failures_both_retained(
    fake_renderer: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(self: offscreen.OffscreenSession) -> None:
        fake_renderer[0].failure = RuntimeError("cleanup")
        raise ValueError("validation")

    monkeypatch.setattr(offscreen.OffscreenSession, "_validate_software", invalid)
    with pytest.raises(RuntimeError, match="cleanup") as caught:
        offscreen.OffscreenSession()
    assert isinstance(caught.value.__context__, ValueError)
    assert str(caught.value.__context__) == "validation"
    assert fake_renderer[0].deletes == 1
    with pytest.raises(offscreen.RenderUnavailableError, match="previous"):
        offscreen.OffscreenSession()


if __name__ == "__main__":
    _real_lifetimes()
