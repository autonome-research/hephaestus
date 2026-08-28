# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for the Stage-4 gate suite (``INTERFACE.md`` §14, mission Gate G4).

Two session-scoped costs are paid once: materializing and building the public
workspace fixture, and building the packaged Node sidecar. Everything else in
this suite is a read over those.

**This suite is the Tier-1 half of Gate G4.** ``pnpm --dir web test:e2e`` is the
gate command and the browser is where G4's clauses are *stated*; the assertions
here are the ones §16 explicitly maps to a server-side pytest — the three-number
geometry invariant (G4.2), the projection-versus-contract direction of the
properties set equality (G4.3), the serializer parity behind the badges (G4.4),
and the event archive's restart stability (G4.11). Neither half substitutes for
the other, and both must pass.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """The packaged sidecar every bridge test drives; skip cleanly without Node."""
    from hephaestus.testing.sidecar import build_agent_dist

    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; the Stage 4 transcript lanes need the sidecar")
    return built[0]


@pytest.fixture(scope="session")
def fixture_project(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """The materialized workspace fixture, built, shared by the whole suite."""
    from hephaestus.testing.workspace_fixture import (
        GATE_PARTS,
        materialize_workspace_fixture,
    )

    root = tmp_path_factory.mktemp("g4") / "workspace"
    materialize_workspace_fixture(root)
    _build(root, GATE_PARTS)
    try:
        yield root
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)


def _build(root: Path, parts: tuple[str, ...]) -> None:
    """Build the gate's parts through ``CadOps`` — the product's own path."""
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.http.runtime import _backend_for  # pyright: ignore[reportPrivateUsage]

    layout = load_project(root)
    store = open_store(layout)
    try:
        cad = CadOps(layout, store, backend=_backend_for(layout, True))
        for part in parts:
            result = cad.build_part(part, op_id=f"g4-build-{part}")
            if result.get("status") != "ok":
                raise AssertionError(f"fixture part {part!r} did not build: {result}")
    finally:
        store.close()


@pytest.fixture
def workspace(fixture_project: Path) -> Iterator[Any]:
    """A ``TestClient`` over the real workspace app on the built fixture."""
    from hephaestus.http.app import build_app
    from hephaestus.http.runtime import WorkspaceRuntime
    from starlette.testclient import TestClient

    runtime = WorkspaceRuntime.open(fixture_project, token="g4", serve_mode=True)
    client = TestClient(build_app(runtime))
    try:
        yield _Api(client, runtime)
    finally:
        client.close()
        runtime.close()


class _Api:
    """The two verbs the suite needs, with the bearer already attached."""

    def __init__(self, client: Any, runtime: Any) -> None:
        self.client = client
        self.runtime = runtime
        self.headers = {"Authorization": "Bearer g4"}

    def get(self, path: str, **params: str) -> dict[str, Any]:
        response = self.client.get(f"/api/v1{path}", headers=self.headers, params=params)
        response.raise_for_status()
        return dict(response.json())

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        import os
        import time
        import uuid

        millis = int(time.time() * 1000)
        raw = bytearray(millis.to_bytes(6, "big") + os.urandom(10))
        raw[6] = (raw[6] & 0x0F) | 0x70
        raw[8] = (raw[8] & 0x3F) | 0x80
        response = self.client.post(
            f"/api/v1{path}",
            json=body,
            headers={**self.headers, "Idempotency-Key": str(uuid.UUID(bytes=bytes(raw)))},
        )
        response.raise_for_status()
        return dict(response.json())

    def bytes(self, ref: str) -> bytes:
        from urllib.parse import quote

        response = self.client.get(
            f"/api/v1/artifacts/{quote(ref, safe='')}/bytes", headers=self.headers
        )
        response.raise_for_status()
        return bytes(response.content)
