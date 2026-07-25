"""Gate G2 — image and schema bounds enforced inside the REAL sidecar.

The §5 image budgets are checked with a **bounded header parser before any full
decode**, and the four-view cap is a *schema* cap on ``inspect_part.views``. Both
live on the TypeScript side of the bridge, so the only way to prove them at gate
level is to drive ``node agent/dist/main.js`` and watch what does — and does not
— cross the wire:

* a decompression bomb returned *by Python* is refused from its 24-byte header;
  the proxy fails closed and the base64 payload never reaches the model;
* more than ``image.max_images_per_result`` images in one result is refused;
* five views are rejected by the generated TypeBox **before** any
  ``py.tool_dispatch`` request is built, four views are accepted.

``server/tests/test_limits.py`` covers the Python header parser; this file covers
its TypeScript twin and the schema cap, in the running sidecar.
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g2b import build_agent_dist, scaffold_project
from hephaestus.agent_bridge.limits import MAX_IMAGES_PER_RESULT
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
from hephaestus.agent_bridge.supervisor import Supervisor, SupervisorConfig, pid_alive
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai

ARTIFACT = "artifact:render:sha256:" + "e" * 64


def png_header(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )


def image(width: int, height: int) -> dict[str, Any]:
    return {
        "data": base64.b64encode(png_header(width, height)).decode("ascii"),
        "mime_type": "image/png",
        "view": "iso",
    }


class Sidecar:
    """The packaged sidecar with a scripted ``py.tool_dispatch`` responder."""

    def __init__(self, root: Path, dist_main: Path, node: str) -> None:
        self.root = scaffold_project(root, name="bounds-sidecar")
        self.fake: FakeOpenAI = start_fake_openai([])
        self.result: dict[str, Any] = {}
        self.dispatched: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        agent_dir = self.root / ".heph" / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        self.sup = Supervisor(
            SupervisorConfig(
                argv=[node, str(dist_main)],
                extra_env={"HEPHAESTUS_AGENT_DIR": str(agent_dir)},
                cwd=str(self.root),
                default_timeout_s=300.0,
            ),
            py_handler=self._on_py,
        )
        self.sup.start()
        self.pid = self.sup.child_pid
        self.sup.call(
            "runtime.configure", {"providers": [self.fake.provider_spec()], "credentials": {}}
        )

    def _on_py(self, method: str, params: dict[str, Any]) -> Any:
        if method == "py.tool_dispatch":
            with self._lock:
                self.dispatched.append(dict(params))
                return dict(self.result)
        if method == "py.admission_capacity":
            return {"capacity": 16}
        raise ProtocolError(ErrorCode.METHOD_NOT_FOUND, f"unhandled py request: {method}")

    def set_result(self, result: dict[str, Any]) -> None:
        with self._lock:
            self.result = result

    def tools(self) -> list[str]:
        with self._lock:
            return [str(entry.get("tool")) for entry in self.dispatched]

    def close(self) -> None:
        try:
            self.sup.close()
        finally:
            self.fake.close()


@pytest.fixture(scope="module")
def sidecar_main() -> tuple[Path, str]:
    from hephaestus.testing.sidecar import node_executable

    built = build_agent_dist()
    node = node_executable()
    if built is None or node is None:
        pytest.skip("node/pnpm are required to drive the packaged sidecar")
    return built[0], node


@pytest.fixture
def sidecar(tmp_path: Path, sidecar_main: tuple[Path, str]) -> Iterator[Sidecar]:
    dist_main, node = sidecar_main
    s = Sidecar(tmp_path / "proj", dist_main, node)
    try:
        yield s
    finally:
        s.close()
        assert not pid_alive(s.pid), "sidecar outlived its supervisor"


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def last_tool_message(info: RequestInfo) -> str:
    body = cast("dict[str, Any]", json.loads(info.body_text))
    for message in reversed(cast("list[Any]", body.get("messages", []))):
        if isinstance(message, dict) and message.get("role") == "tool":
            content = cast("dict[str, Any]", message).get("content")
            return content if isinstance(content, str) else json.dumps(content)
    return ""


def run_inspect(sidecar: Sidecar, arguments: dict[str, Any], *, session: str) -> tuple[str, str]:
    """Drive one ``inspect_part`` call; return (tool text, full final request body)."""
    seen: dict[str, str] = {}

    def report(info: RequestInfo) -> dict[str, Any]:
        seen["tool"] = last_tool_message(info)
        seen["body"] = info.body_text
        return {"kind": "text", "chunks": ["reported"]}

    sidecar.fake.set_script([tool_call("inspect_part", arguments, "i0"), report])
    created = sidecar.sup.call(
        "session.create",
        {"profile": "part", "part": "widget", "project_root": str(sidecar.root)},
    )
    session_id = str(cast("dict[str, Any]", created)["session_id"])
    sidecar.sup.call(
        "session.prompt",
        {"session_id": session_id, "run_id": f"run-{session}", "prompt": "inspect the widget"},
        timeout=300,
    )
    return seen.get("tool", ""), seen.get("body", "")


def test_bridge_bounds_a_valid_render_reaches_the_model_inline(sidecar: Sidecar) -> None:
    payload = image(64, 64)
    sidecar.set_result(
        {
            "status": "ok",
            "source_artifact_ref": ARTIFACT,
            "render_artifact_refs": [ARTIFACT],
            "images": [payload],
        }
    )
    _tool_text, body = run_inspect(sidecar, {"name": "widget", "views": ["iso"]}, session="ok")
    assert sidecar.tools() == ["inspect_part"]
    # The image rode inline as an image block, not as base64 inside the text.
    assert "image_url" in body or "image" in body
    assert str(payload["data"]) in body


def test_bridge_bounds_an_image_bomb_is_refused_from_its_header(sidecar: Sidecar) -> None:
    bomb = image(60_000, 60_000)
    assert len(base64.b64decode(str(bomb["data"]))) < 64, "a header alone must be enough"
    sidecar.set_result(
        {
            "status": "ok",
            "source_artifact_ref": ARTIFACT,
            "render_artifact_refs": [ARTIFACT],
            "images": [bomb],
        }
    )
    tool_text, body = run_inspect(sidecar, {"name": "widget", "views": ["iso"]}, session="bomb")

    # Python was asked for the render (the bomb came from *inside* the bridge)…
    assert sidecar.tools() == ["inspect_part"]
    # …and the proxy failed closed: the model got an error, never the payload.
    assert "reject" in tool_text.lower() or "image" in tool_text.lower(), tool_text
    assert str(bomb["data"]) not in body, "the bomb payload leaked into model context"
    assert "60000x60000" in tool_text or "60000" in tool_text, tool_text


def test_bridge_bounds_more_than_four_images_in_one_result_is_refused(sidecar: Sidecar) -> None:
    images = [image(32, 32) for _ in range(MAX_IMAGES_PER_RESULT + 1)]
    sidecar.set_result(
        {
            "status": "ok",
            "source_artifact_ref": ARTIFACT,
            "render_artifact_refs": [ARTIFACT],
            "images": images,
        }
    )
    tool_text, body = run_inspect(sidecar, {"name": "widget", "views": ["iso"]}, session="many")
    assert sidecar.tools() == ["inspect_part"]
    assert str(MAX_IMAGES_PER_RESULT) in tool_text, tool_text
    assert str(MAX_IMAGES_PER_RESULT + 1) in tool_text, tool_text
    # Fail closed: not one of the five images was rendered into model context.
    assert str(images[0]["data"]) not in body


def test_bridge_bounds_view_count_cap_is_enforced_before_the_bridge(sidecar: Sidecar) -> None:
    sidecar.set_result(
        {"status": "ok", "source_artifact_ref": ARTIFACT, "render_artifact_refs": [ARTIFACT]}
    )
    views = ["iso"] * (MAX_IMAGES_PER_RESULT + 1)
    tool_text, _body = run_inspect(sidecar, {"name": "widget", "views": views}, session="views")
    # The generated TypeBox rejected the arguments: no bridge request was built.
    assert sidecar.tools() == [], sidecar.tools()
    lowered = tool_text.lower()
    assert "validation failed" in lowered and "views" in lowered, tool_text
    assert str(MAX_IMAGES_PER_RESULT) in tool_text, tool_text

    # Exactly four views is the accepted boundary.
    ok_views = ["iso"] * MAX_IMAGES_PER_RESULT
    run_inspect(sidecar, {"name": "widget", "views": ok_views}, session="views-ok")
    assert sidecar.tools() == ["inspect_part"]
