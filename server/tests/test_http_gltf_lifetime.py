"""Real secure builds + concurrent HTTP GLTF/inspection, including native cleanup."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import importlib
import io
import json
import threading
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render import offscreen
from hephaestus.core.render.bundle import resolve_selection
from hephaestus.core.render.gltf import validate_gltf
from hephaestus.http.app import build_app
from hephaestus.http.runtime import WorkspaceRuntime
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.tools_fixture import scaffold
from hephaestus.testing.workspace import uuid7
from PIL import Image


@pytest.mark.parametrize("peer", ["same-ref", "different-ref", "inspect"])
def test_concurrent_geometry_lifetimes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, peer: str
) -> None:
    asyncio.run(_concurrent_geometry(tmp_path, monkeypatch, peer))


async def _concurrent_geometry(root: Path, patch: pytest.MonkeyPatch, peer: str) -> None:
    role: contextvars.ContextVar[str] = contextvars.ContextVar("render_role", default="setup")
    first_rendered, attempted, closed = (threading.Event() for _ in range(3))
    events: list[tuple[str, str, int]] = []
    original_close = offscreen.OffscreenSession.close
    original_init = offscreen.OffscreenSession.__init__
    lock = getattr(offscreen, "_session_lock", None)

    if lock is not None:

        class ObservedLock:
            def acquire(self) -> None:
                if role.get() == "B":
                    attempted.set()  # positive boundary edge, never a timed absence
                lock.acquire()

            def release(self) -> None:
                lock.release()

        patch.setattr(offscreen, "_session_lock", ObservedLock())

    def init(session: offscreen.OffscreenSession, *args: Any, **kwargs: Any) -> None:
        original_init(session, *args, **kwargs)
        assert "llvmpipe" in session.gl_renderer.lower()
        if role.get() == "B" and lock is None:
            attempted.set()  # old implementation: force two overlapping live contexts

    def close(session: offscreen.OffscreenSession) -> None:
        if role.get() == "A":
            first_rendered.set()
            assert attempted.wait(40), "peer never attempted its renderer lifetime"
        elif lock is None:
            assert closed.wait(40), "first lifetime never closed"
        try:
            original_close(session)
        finally:
            if role.get() == "A":
                closed.set()

    # Match the application's import ordering. Trace and delegate actual native
    # calls, never replace EGL, geometry, rasterization or a cleanup exception.
    importlib.import_module("pyrender")
    from OpenGL import EGL

    for name in ("eglCreateContext", "eglDestroyContext", "eglTerminate"):
        real = getattr(EGL, name)

        def traced(*args: Any, _real: Any = real, _name: str = name) -> Any:
            result = _real(*args)
            events.append((role.get(), _name, threading.get_ident()))
            return result

        patch.setattr(EGL, name, traced)

    runtime = WorkspaceRuntime.open(
        scaffold(root / "workspace"), token="synthetic-only", serve_mode=True
    )
    try:
        assert type(runtime.backend).__name__ == "BwrapBackend"
        assert not getattr(runtime.backend, "unsafe", False)
        seed_minimal_ledger(runtime.cad)
        transport = httpx.ASGITransport(app=build_app(runtime), raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer synthetic-only"},
        ) as client:
            refs: dict[str, str] = {}
            for part in ("widget", "bracket"):
                built = await client.post(
                    f"/api/v1/parts/{part}/build", json={}, headers={"Idempotency-Key": uuid7()}
                )
                assert built.status_code == 200 and built.json()["status"] == "ok", built.text
                refs[part] = (await client.get(f"/api/v1/parts/{part}/build")).json()[
                    "artifact_ref"
                ]
            patch.setattr(offscreen.OffscreenSession, "__init__", init)
            patch.setattr(offscreen.OffscreenSession, "close", close)

            async def request(name: str) -> httpx.Response:
                role.set(name)
                if name == "B":
                    assert await asyncio.to_thread(first_rendered.wait, 40), "A did not render"
                if name == "B" and peer == "inspect":
                    return await client.post(
                        "/api/v1/parts/bracket/inspect",
                        json={"views": ["iso"], "channel": "rgb", "artifact_ref": refs["bracket"]},
                    )
                part = "bracket" if name == "B" and peer == "different-ref" else "widget"
                return await client.get(f"/api/v1/artifacts/{refs[part]}/gltf")

            responses = await asyncio.gather(request("A"), request("B"), return_exceptions=True)
            # Join BOTH requests before asserting/closing runtime, even on failure.
            for name, response in zip(("A", "B"), responses, strict=True):
                assert isinstance(response, httpx.Response), repr(response)
                (root / f"{name}.response").write_bytes(response.content)
                assert response.status_code == 200, response.text
                if name == "B" and peer == "inspect":
                    body = response.json()
                    assert body["status"] == "ok", body
                    assert body["source_artifact_ref"] == refs["bracket"]
                    for index, ref in enumerate(body["render_artifact_refs"]):
                        _png(runtime, ref, root / f"B-rgb-{index}.png")
                    assert body["render_artifact_refs"]
                    continue
                source = (
                    refs["bracket"] if name == "B" and peer == "different-ref" else refs["widget"]
                )
                glb = response.content
                validation = validate_gltf(glb, expected_solid_count=1)
                assert validation.primitive_count > 0 and validation.buffer_length > 0
                assert (
                    validation.source_artifact_ref
                    == source
                    == response.headers["X-Hephaestus-Source-Artifact"]
                )
                assert (
                    response.headers["ETag"]
                    == "artifact:gltf:sha256:" + hashlib.sha256(glb).hexdigest()
                )
                bundle = resolve_selection(
                    runtime.store,
                    response.headers["X-Hephaestus-Selection-Bundle"],
                    expected_source_artifact_ref=source,
                )
                assert bundle.bundle_ref == validation.bundle_ref and bundle.entries
                (root / f"{name}.glb").write_bytes(glb)
                for channel, ref in bundle.pass_refs.to_json().items():
                    assert isinstance(ref, str)
                    _png(runtime, ref, root / f"{name}-{channel}.png")
            assert [(name, call) for name, call, _ in events] == [
                (name, call)
                for name in ("A", "B")
                for call in ("eglCreateContext", "eglDestroyContext", "eglTerminate")
            ], events
            for name in ("A", "B"):
                assert len({tid for who, _, tid in events if who == name}) == 1
            if peer == "same-ref":
                assert isinstance(responses[0], httpx.Response) and isinstance(
                    responses[1], httpx.Response
                )
                assert responses[0].content == responses[1].content
    finally:
        (root / "native-lifetimes.json").write_text(json.dumps(events, indent=2))
        runtime.detach_agent()
        runtime.close()


def _png(runtime: WorkspaceRuntime, ref: str, path: Path) -> None:
    png = runtime.store.blobs.get(blob_hash_of_ref(ref))
    assert "sha256:" + hashlib.sha256(png).hexdigest() == blob_hash_of_ref(ref)
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        assert image.size == (960, 720)
        pixels = np.asarray(image)
        assert np.any(pixels[:, :, :3] != pixels[0, 0, :3]), "blank rendered geometry"
    path.write_bytes(png)
