"""Gate G3 client-side toolkit: stock MCP only, zero Hephaestus imports.

Everything a G3 scripted client needs lives here, and *nothing* in this module
(or in the three flow modules that use it) may import ``hephaestus``: the gate's
claim is that a client with no Hephaestus code on its side drives the server.
``test_stdio_flow.test_stdio_client_modules_import_no_hephaestus`` enforces that
structurally, by parsing those modules' imports.

Three client shapes are provided:

* :func:`stdio_parameters` / :func:`http_server` — the server under test,
  launched exactly the way a user launches it (``heph serve --mcp`` as a
  subprocess);
* :func:`run_flow` — the G3 create -> edit -> build -> inspect -> measure ->
  export STEP flow, written once against the official ``mcp`` SDK's
  :class:`~mcp.ClientSession` so both transports run the *same* client code;
* :class:`RawStdioClient` — a hand-rolled JSON-RPC-over-stdio client (not even
  the SDK) for the tests that must control the JSON-RPC request id, which the
  SDK deliberately allocates itself.

STEP re-import assertions go through OCP directly, so the geometry check is
independent of every Hephaestus code path that produced the file.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

__all__ = [
    "FIXTURE_PROJECT",
    "LEDGER_ENTRY",
    "PLATE_SCRIPT",
    "REPO_ROOT",
    "FlowOutcome",
    "RawStdioClient",
    "ask_user_round_trip",
    "elicitation_answerer",
    "fixture_project",
    "free_port",
    "http_server",
    "raw_structured",
    "run_flow",
    "stdio_client_for",
    "stdio_parameters",
    "step_solid_count_and_volume",
    "structured",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The public clean-room fixture the gate names.
FIXTURE_PROJECT = REPO_ROOT / "corpus" / "public_fixtures" / "assembly"

#: The part script the flow edits into place (engine namespace, see script_contract.md).
PLATE_SCRIPT = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, 6.0)
body.label = "plate_body"
part.geometry = body
part.description = "G3 scripted-client plate"
"""

#: Volume of ``PLATE_SCRIPT`` at its default params, in mm^3.
PLATE_VOLUME_MM3 = 40.0 * 20.0 * 6.0

#: The one requirement the flow records before it builds (``VALIDATION.md`` §2).
#: Spelled out literally rather than imported, because this module may not import
#: Hephaestus at all — the gate's claim is a client with no Hephaestus code.
LEDGER_ENTRY: dict[str, Any] = {
    "id": "R1",
    "text": "the plate is 40 mm wide",
    "source": "specified",
    "quote": "40 mm",
    "value": 40.0,
    "unit": "mm",
}

_READY_TIMEOUT_S = 120.0


def fixture_project(destination: Path) -> Path:
    """Copy the public fixture project to a writable location (never mutate the repo)."""
    root = destination / "assembly"
    shutil.copytree(FIXTURE_PROJECT, root)
    return root


def _serve_argv(http: str | None) -> list[str]:
    argv = ["uv", "run", "heph", "serve", "--mcp"]
    if http is not None:
        argv += ["--http", http]
    return argv


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def http_server(port: int) -> Iterator[str]:
    """``heph serve --mcp --http`` as a subprocess; yields the ``/mcp`` URL."""
    proc = subprocess.Popen(
        _serve_argv(f"127.0.0.1:{port}"),
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + _READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"heph serve --http exited early: {proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:  # pragma: no cover - server never came up
            raise RuntimeError("heph serve --http did not start")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=30)


def _stdio_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=_serve_argv(None)[0],
        args=_serve_argv(None)[1:],
        cwd=str(REPO_ROOT),
        env=dict(os.environ),
    )


def structured(result: Any) -> dict[str, Any]:
    """The structured content of a ``tools/call`` result (SDK shape)."""
    content: Any = result.structuredContent
    if content is None:
        block = result.content[0]
        return dict(json.loads(block.text))
    return dict(content)


@dataclass(frozen=True)
class FlowOutcome:
    """What the G3 flow observed, for the transport-independent assertions."""

    part: str
    build_artifact_ref: str
    image_count: int
    image_mime_types: tuple[str, ...]
    render_artifact_refs: tuple[str, ...]
    measured_volume: float
    measured_units: str
    export_paths: tuple[str, ...]
    export_hashes: dict[str, Any]
    listed_parts: tuple[str, ...]


async def run_flow(session: ClientSession, root: Path, part: str = "g3_plate") -> FlowOutcome:
    """The gate flow, driven with the stock SDK only: identical on both transports.

    open_project -> list_parts -> create -> edit -> build -> inspect (images)
    -> measure -> export STEP.
    """
    await session.initialize()

    listing = await session.list_tools()
    names = {tool.name for tool in listing.tools}
    for required in ("open_project", "list_parts", "create_part", "export_part"):
        assert required in names, f"{required} missing from the tool listing"

    opened = structured(await _call(session, "open_project", {"path": str(root)}))
    assert opened["status"] == "ok", opened
    assert opened["root"] == str(root)

    parts = structured(await _call(session, "list_parts", {}))
    listed = tuple(str(row["name"]) for row in parts["parts"])
    assert "bracket" in listed and "primary" in listed, listed

    # VALIDATION.md §2: geometry may not precede requirements — build_part is
    # refused while the ledger is empty. A stock client records it through the
    # ordinary tool surface, which is exactly what this flow is here to exercise.
    ledger = structured(await _call(session, "record_requirements", {"entries": [LEDGER_ENTRY]}))
    assert ledger["status"] == "ok", ledger

    created = structured(await _call(session, "create_part", {"name": part, "template": "blank"}))
    edited = structured(
        await _call(
            session,
            "edit_part",
            {
                "name": part,
                "expected_hash": created["content_hash"],
                "old_str": created["initial_script"],
                "new_str": PLATE_SCRIPT,
            },
        )
    )
    assert edited["applied"] is True, edited

    built = structured(await _call(session, "build_part", {"name": part}))
    assert built["status"] == "ok", built

    inspected = await _call(session, "inspect_part", {"name": part, "views": ["iso", "+X"]})
    inspect_payload = structured(inspected)
    assert inspect_payload["status"] == "ok", inspect_payload
    images = [block for block in inspected.content if isinstance(block, types.ImageContent)]
    assert images, "inspect_part returned no MCP image content"

    measured = structured(
        await _call(session, "measure", {"kind": "volume", "a": "part", "part": part})
    )

    exported = structured(await _call(session, "export_part", {"name": part, "format": "step"}))
    assert exported["paths"], exported

    return FlowOutcome(
        part=part,
        build_artifact_ref=str(built["artifact_ref"]),
        image_count=len(images),
        image_mime_types=tuple(str(block.mimeType) for block in images),
        render_artifact_refs=tuple(str(r) for r in inspect_payload["render_artifact_refs"]),
        measured_volume=float(measured["value"]),
        measured_units=str(measured["units"]),
        export_paths=tuple(str(p) for p in exported["paths"]),
        export_hashes=dict(exported.get("export_hashes") or {}),
        listed_parts=listed,
    )


async def _call(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    result = await session.call_tool(name, arguments)
    assert not result.isError, f"{name} failed: {result.content}"
    return result


def elicitation_answerer(answer: str, seen: dict[str, Any]) -> Any:
    """A stock-SDK elicitation callback that accepts with ``answer``."""

    async def callback(context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        schema: Any = params.requestedSchema
        if schema is not None and not isinstance(schema, dict):
            schema = schema.model_dump()
        seen["message"] = params.message
        seen["schema"] = schema
        properties = dict(schema.get("properties") or {}) if schema else {}
        seen["properties"] = sorted(properties)
        field = "value" if "value" in properties else (sorted(properties)[0] if properties else "")
        return types.ElicitResult(action="accept", content={field: answer})

    return callback


async def ask_user_round_trip(session: ClientSession, seen: dict[str, Any]) -> dict[str, Any]:
    """Call ``ask_user`` and return its structured result (elicitation answered)."""
    await session.initialize()
    result = await session.call_tool(
        "ask_user",
        {"question": "fillet or chamfer?", "options": ["fillet", "chamfer"]},
    )
    assert not result.isError, result.content
    assert seen.get("message"), "the server never elicited"
    return structured(result)


def step_solid_count_and_volume(path: Path) -> tuple[int, float]:
    """Re-import a STEP file with OCP; return ``(solid count, total volume)``.

    Deliberately independent of Hephaestus: OCCT reads the file the exporter
    wrote and measures it again, so a matching volume is evidence about the
    bytes on disk rather than about the producing code path.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    assert status == IFSelect_ReturnStatus.IFSelect_RetDone, f"STEP unreadable: {status}"
    reader.TransferRoots()
    shape = reader.OneShape()

    solids = 0
    total = 0.0
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), props)
        total += float(props.Mass())
        solids += 1
        explorer.Next()
    return solids, total


class RawStdioClient:
    """A hand-rolled JSON-RPC-over-stdio MCP client with explicit request ids.

    The SDK allocates request ids internally, but the gate's idempotency clause
    is *about* those ids ("a same-id replay returns the recorded result"), so
    these tests speak the wire protocol directly: newline-delimited JSON on the
    server's stdin/stdout, exactly what ``mcp.client.stdio`` writes.

    It advertises **no** capabilities — in particular no elicitation — so it is
    also the client that exercises the documented ``ask_user`` fallback.
    """

    def __init__(self, *, capabilities: dict[str, Any] | None = None) -> None:
        self._capabilities = capabilities or {}
        self._proc = subprocess.Popen(
            _serve_argv(None),
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> RawStdioClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        proc = self._proc
        if proc.poll() is None:
            if proc.stdin is not None:
                with suppress(OSError):  # pragma: no cover - defensive
                    proc.stdin.close()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                proc.kill()
                proc.wait(timeout=30)

    def _pump(self) -> None:
        stdout = self._proc.stdout
        assert stdout is not None
        for line in stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:  # pragma: no cover - stdout is JSON-RPC only
                print(f"[raw-client] non-JSON on stdout: {text!r}", file=sys.stderr)
                continue
            if isinstance(message, dict):
                self._inbox.put(dict(message))

    # -- protocol ----------------------------------------------------------

    def send(self, message: dict[str, Any]) -> None:
        stdin = self._proc.stdin
        assert stdin is not None
        stdin.write(json.dumps(message) + "\n")
        stdin.flush()

    def await_response(self, request_id: int | str, timeout: float = 180.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:  # pragma: no cover - only on a hung server
                raise TimeoutError(f"no response to request id {request_id!r}")
            try:
                message = self._inbox.get(timeout=remaining)
            except queue.Empty:  # pragma: no cover - loop re-checks the deadline
                continue
            if message.get("id") == request_id and ("result" in message or "error" in message):
                return message

    def request(
        self,
        method: str,
        params: dict[str, Any],
        request_id: int | str,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self.await_response(request_id, timeout=timeout)

    def initialize(self, request_id: int | str = 1) -> dict[str, Any]:
        response = self.request(
            "initialize",
            {
                "protocolVersion": types.LATEST_PROTOCOL_VERSION,
                "capabilities": self._capabilities,
                "clientInfo": {"name": "g3-raw-client", "version": "0"},
            },
            request_id,
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        request_id: int | str,
        *,
        meta: dict[str, Any] | None = None,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """One ``tools/call`` at an id the caller chose; returns the JSON-RPC result."""
        params: dict[str, Any] = {"name": name, "arguments": arguments}
        if meta is not None:
            params["_meta"] = meta
        response = self.request("tools/call", params, request_id, timeout=timeout)
        assert "error" not in response, response
        return dict(response["result"])


def raw_structured(result: dict[str, Any]) -> dict[str, Any]:
    """Structured content of a raw JSON-RPC ``tools/call`` result."""
    content = result.get("structuredContent")
    if content is None:
        blocks = list(result.get("content") or [])
        return dict(json.loads(str(blocks[0]["text"])))
    return dict(content)


def stdio_parameters() -> StdioServerParameters:
    """The SDK's launch parameters for ``heph serve --mcp`` over stdio."""
    return _stdio_parameters()


def stdio_client_for(elicitation_callback: Any = None) -> Any:
    """``stdio_client(...)`` + ``ClientSession(...)`` as one async context manager."""

    class _Ctx:
        async def __aenter__(self) -> ClientSession:
            self._transport = stdio_client(_stdio_parameters())
            read, write = await self._transport.__aenter__()
            self._session = ClientSession(read, write, elicitation_callback=elicitation_callback)
            return await self._session.__aenter__()

        async def __aexit__(self, *exc: Any) -> None:
            await self._session.__aexit__(*exc)
            await self._transport.__aexit__(*exc)

    return _Ctx()
