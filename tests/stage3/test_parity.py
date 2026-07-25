"""Gate G3 parity: the same operations through Pi->bridge->core and MCP->core.

Stage 3 adds a second front door to the *same* engine. The risk this suite
retires is that the two doors diverge — that a mutation replayed over MCP does
something the bridge would not, that a conflict reports different snapshot refs,
that a cursor means something else, or that a refusal comes back under a
different name. Schema equality would not catch any of that, so nothing here
compares schemas: every row **executes** an operation down both paths over two
byte-identically seeded projects and compares the outcomes themselves — result
payloads (modulo transport wrappers), content hashes and artifact refs, cursor
reconstruction, and error taxonomy.

The two paths are:

* **Pi path** — a real :class:`~hephaestus.agent_bridge.app.BridgeRuntime` whose
  own ``py.tool_dispatch`` handler is called with the trusted invocation
  metadata the sidecar sends. The Node sidecar is never spawned: this suite is
  about what the bridge does with a tool call, and the model loop that produces
  it is Gate G2's subject (``tests/stage2``). Everything below the handler —
  principal authz, :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher`,
  :class:`~hephaestus.agent_bridge.cad_ops.CadOps`, the opstore — is the real
  production object graph.
* **MCP path** — a stock ``fastmcp.Client`` against the real
  :mod:`hephaestus.mcp` app: ``open_project`` then ``call_tool``, with no
  Hephaestus code on the client side. A "lost response" is replayed the way a
  stock client's retry looks on the wire — the *same JSON-RPC request id* — not
  by sending custom idempotency metadata.

Both paths open the same store configuration over projects seeded from the same
bytes, so content-addressed values (content hashes, snapshot refs, build
artifact refs, paging cursors) are expected to be **equal**, not merely
well-formed. Absolute paths are the one thing that legitimately differs; they
are scrubbed to ``<project>`` before comparison.

Two rows are *documented divergences* rather than equalities, and each one is
pinned from both sides plus the invariants that must survive it, so a deliberate
design difference cannot rot into an accidental hole:

* **part object scope.** A part-scoped bridge session is denied; a local MCP
  client is orchestrator-equivalent by design (``hephaestus.mcp.app``: the client
  *is* the agent, and its object scope is the project ``open_project`` bound —
  which the other denial rows do cover).
* **``edit_part`` retry shape.** The bridge resolves a committed edit's retry to
  ``conflict`` (its CAS gate runs ahead of the WAL key); the MCP request-id
  ledger sits in front of that gate and replays ``applied``. Both perform the
  mutation exactly once and both return the live hash.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable, Coroutine, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
from fastmcp import Client
from hephaestus.agent_bridge.app import BridgeRuntime, default_dist_main
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.agent_bridge.protocol import ProtocolError
from hephaestus.core.errors import HephaestusError
from hephaestus.mcp import build_app
from mcp.types import TextContent

# --------------------------------------------------------------------------
# the seeded project (identical bytes for both paths)

GLOBALS_SRC = """PARAMS = {
    "wall": Param(2.0, min=1.0, max=6.0),
}

SHELF_W = 100.0
"""

WIDGET_SRC = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, hc.wall)
body.label = "widget_body"
part.geometry = body
"""

BRACKET_SRC = """body = Box(10.0, 10.0, hc.wall)
body.label = "bracket_body"
part.geometry = body
"""

#: A single line well over the 50 KiB text cap, deliberately mixing a multi-byte
#: code point (so page ends land mid-code-point and must be shortened) with a
#: JSON-escaped character (so the *encoded* text block also blows the cap).
OVERSIZED_LINE = "# " + ('é"' * 25_000) + "\n"


def seed_project(root: Path) -> Path:
    """A real Hephaestus project: manifest, globals, two parts, empty checks."""
    (root / "parts").mkdir(parents=True, exist_ok=True)
    (root / "checks").mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "parity"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    (root / "parts" / "widget.py").write_text(WIDGET_SRC, encoding="utf-8")
    (root / "parts" / "bracket.py").write_text(BRACKET_SRC, encoding="utf-8")
    return root.resolve()


# --------------------------------------------------------------------------
# transport-independent outcomes


@dataclass(frozen=True)
class Outcome:
    """One tool call's outcome, stripped of everything transport-specific."""

    ok: bool
    payload: dict[str, Any]
    reason: str | None = None
    message: str | None = None
    #: Did the transport signal "this is the recorded result of an earlier call"?
    replayed: bool = False

    def observed(self) -> dict[str, Any]:
        """The comparable projection (what a parity row records)."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "message": self.message,
            "payload": self.payload,
            "replayed": self.replayed,
        }


def _scrub(value: Any, root: Path) -> Any:
    """Replace the project root in any string so two roots compare equal."""
    if isinstance(value, str):
        return value.replace(str(root), "<project>")
    if isinstance(value, dict):
        return {k: _scrub(v, root) for k, v in cast("dict[str, Any]", value).items()}
    if isinstance(value, list):
        return [_scrub(v, root) for v in cast("list[Any]", value)]
    return value


#: Result keys that carry a path's *own* replay signalling rather than a value.
_REPLAY_KEYS = ("replayed",)


def _split_replay(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Lift in-payload replay markers out of the compared value."""
    replayed = bool(payload.get("replayed", False))
    return {k: v for k, v in payload.items() if k not in _REPLAY_KEYS}, replayed


class PathUnderTest(Protocol):
    """One front door, driven identically by every parity row."""

    label: str
    root: Path

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        key: str | None = None,
        as_part: str | None = None,
    ) -> Outcome:
        """Invoke ``tool``.

        ``key`` names a *retry identity*: two calls with the same key are the
        same operation as far as the transport's idempotency contract is
        concerned (the bridge's trusted ``entry_id``; the MCP session's JSON-RPC
        request id). ``as_part`` requests a part-scoped session where the
        transport has one.
        """
        ...


# --------------------------------------------------------------------------
# path (a): Pi proxy -> bridge -> core


class PiPath:
    """``py.tool_dispatch`` against a real, unstarted :class:`BridgeRuntime`.

    The runtime's own request handler is used, so principal resolution and
    routing are the production code paths; only the Node sidecar that would
    normally originate the request is absent (see the module docstring).
    """

    label = "pi"

    def __init__(self, root: Path) -> None:
        self.root = root
        if not (os.environ.get("HEPHAESTUS_NODE") or shutil.which("node")):
            # The sidecar is never spawned here; the supervisor only needs an
            # argv it can hold. Keeping this hermetic means the parity contract
            # is checkable on a Node-less machine.
            os.environ["HEPHAESTUS_NODE"] = str(root / ".heph" / "never-spawned-node")
        self.runtime = BridgeRuntime(project_root=root, providers=[], dist_main=default_dist_main())
        # Sessions the sidecar would have created through ``session.create``.
        self._register("orchestrator", "pi-orch", None)
        self._n = 0

    def _register(self, profile: str, session_id: str, part: str | None) -> None:
        self.runtime._principals[session_id] = Principal(  # pyright: ignore[reportPrivateUsage]
            session_id=session_id, profile=profile, part=part
        )

    def close(self) -> None:
        self.runtime.close()

    def _session_for(self, as_part: str | None) -> str:
        if as_part is None:
            return "pi-orch"
        session_id = f"pi-part-{as_part}"
        self._register("part", session_id, as_part)
        return session_id

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        key: str | None = None,
        as_part: str | None = None,
    ) -> Outcome:
        self._n += 1
        session_id = self._session_for(as_part)
        params = {
            "session_id": session_id,
            "run_id": "parity-run",
            "tool": tool,
            "arguments": arguments,
            "invocation": {
                "session_id": session_id,
                "entry_id": key or f"entry-{self._n}",
                "ordinal": 1,
                "provider_call_id": "call_0",
            },
        }
        try:
            raw = await asyncio.to_thread(
                self.runtime._handle_tool_dispatch,  # pyright: ignore[reportPrivateUsage]
                params,
            )
        except DispatchError as exc:
            data = {k: v for k, v in exc.data.items() if k != "reason"}
            return Outcome(
                ok=False,
                payload=_scrub(data, self.root),
                reason=exc.reason,
                message=_scrub(str(exc), self.root),
            )
        except HephaestusError as exc:
            return Outcome(
                ok=False,
                payload={},
                reason=exc.code,
                message=_scrub(exc.message, self.root),
            )
        except ProtocolError as exc:
            return Outcome(ok=False, payload={}, reason="protocol_error", message=str(exc))
        payload = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {"result": raw}
        body, replayed = _split_replay(payload)
        return Outcome(ok=True, payload=_scrub(body, self.root), replayed=replayed)


# --------------------------------------------------------------------------
# path (b): stock MCP client -> mcp app -> core


class McpPath:
    """A stock ``fastmcp.Client`` against the real Stage 3 app."""

    label = "mcp"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.app, self.runtime = build_app()
        self.client: Client[Any] = Client(self.app)
        self._request_ids: dict[str, int] = {}
        #: The MCP text blocks of every call, for transport-shaping assertions.
        self.text_blocks: list[str] = []

    async def __aenter__(self) -> McpPath:
        self._stack = AsyncExitStack()
        await self._stack.enter_async_context(self.client)
        opened = await self.client.call_tool("open_project", {"path": str(self.root)})
        assert cast("dict[str, Any]", opened.structured_content)["status"] == "ok"
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            await self._stack.aclose()
        finally:
            self.runtime.close()

    # A stock client has no idempotency metadata to send: its retry of a lost
    # response is literally the same JSON-RPC request id on the same session.
    def _rewind(self, key: str) -> None:
        session = cast("Any", self.client.session)
        recorded = self._request_ids.get(key)
        if recorded is None:
            self._request_ids[key] = int(session._request_id)
        else:
            session._request_id = recorded

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        key: str | None = None,
        as_part: str | None = None,
    ) -> Outcome:
        # ``as_part`` is deliberately ignored: an MCP session is orchestrator-
        # equivalent (see the object-scope row).
        if key is not None:
            self._rewind(key)
        result = await self.client.call_tool(tool, arguments, raise_on_error=False)
        payload: dict[str, Any] = result.structured_content or {}
        self.text_blocks.extend(b.text for b in result.content if isinstance(b, TextContent))
        meta: dict[str, Any] = result.meta or {}
        if result.is_error:
            reason = payload.get("reason")
            message = payload.get("message")
            data = {k: v for k, v in payload.items() if k not in ("status", "reason", "message")}
            return Outcome(
                ok=False,
                payload=_scrub(data, self.root),
                reason=None if reason is None else str(reason),
                message=None if message is None else _scrub(str(message), self.root),
            )
        body, in_payload_replay = _split_replay(payload)
        replayed = in_payload_replay or bool(meta.get("hephaestus.dev/replayed"))
        return Outcome(ok=True, payload=_scrub(body, self.root), replayed=replayed)


# --------------------------------------------------------------------------
# the rows

Scenario = Callable[[PathUnderTest], Coroutine[Any, Any, dict[str, Any]]]


@dataclass(frozen=True)
class Row:
    """One parity case: a scenario plus how the two paths must relate."""

    name: str
    run: Scenario
    #: ``"identical"`` — both paths must observe exactly the same thing.
    #: ``"documented_divergence"`` — each path must match its own ``expect[label]``
    #: on the keys that differ, and both must still agree on ``shared``.
    equivalence: str = "identical"
    expect: Mapping[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    #: Observation keys that must be equal even across a documented divergence.
    shared: tuple[str, ...] = ()


async def _mutation_replay(p: PathUnderTest) -> dict[str, Any]:
    """A mutation whose response is lost, then retried under the same identity."""
    args = {"name": "gadget", "template": "solid"}
    first = await p.call("create_part", args, key="create-gadget")
    replay = await p.call("create_part", args, key="create-gadget")
    after = await p.call("read_part", {"name": "gadget"})
    return {
        "first": first.observed(),
        "replay": replay.observed(),
        "replay_matches_first": replay.payload == first.payload,
        "replay_was_signalled": replay.replayed,
        "first_was_not_a_replay": not first.replayed,
        "content_hash": after.payload["content_hash"],
        "snapshot_ref": after.payload["snapshot_ref"],
        # The mutation happened exactly once: the retry did not re-create.
        "script": after.payload["script"],
    }


async def _edit_replay(p: PathUnderTest) -> dict[str, Any]:
    """An accepted CAS edit, retried on the same invocation identity.

    ``edit_part`` reads the live hash *before* claiming its WAL key (that is what
    makes an ambiguous edit detectable), so on the bridge a retry of a committed
    edit resolves to ``conflict`` carrying the hash the edit itself wrote — the
    behaviour ``dispatch``'s docstring pins. Over MCP the request-id ledger sits
    in *front* of that gate, so the same retry replays the recorded ``applied``
    result. Both refuse to mutate twice and both hand back the live hash; they
    disagree only on which of the two truthful shapes the client sees.
    """
    snapshot = await p.call("read_part", {"name": "widget"})
    args = {
        "name": "widget",
        "expected_hash": snapshot.payload["content_hash"],
        "old_str": "20.0",
        "new_str": "26.0",
    }
    first = await p.call("edit_part", args, key="edit-widget")
    replay = await p.call("edit_part", args, key="edit-widget")
    after = await p.call("read_part", {"name": "widget"})
    conflict = cast("dict[str, Any] | None", replay.payload.get("conflict"))
    return {
        "first_applied": bool(first.payload.get("applied")),
        "first_content_hash": first.payload.get("content_hash"),
        "replay_applied": bool(replay.payload.get("applied")),
        "replay_conflicted": conflict is not None,
        # Whatever shape the retry takes, it must name the live hash.
        "replay_reports_live_hash": (
            conflict["current_hash"] if conflict is not None else replay.payload.get("content_hash")
        ),
        "live_hash": after.payload["content_hash"],
        "live_script": after.payload["script"],
        # The decisive invariant: the edit was performed exactly once.
        "applied_once": after.payload["script"].count("26.0") == 1
        and "20.0" not in after.payload["script"],
    }


async def _stale_hash_edit_conflict(p: PathUnderTest) -> dict[str, Any]:
    """A stale ``expected_hash`` must be a discriminated conflict, not a write."""
    stale = "sha256:" + "0" * 64
    out = await p.call(
        "edit_part",
        {"name": "widget", "expected_hash": stale, "old_str": "20.0", "new_str": "99.0"},
        key="stale-edit",
    )
    after = await p.call("read_part", {"name": "widget"})
    return {
        "conflict": out.observed(),
        "unchanged": after.payload["content_hash"],
        "no_write": "99.0" not in after.payload["script"],
    }


async def _stale_hash_write_conflict(p: PathUnderTest) -> dict[str, Any]:
    """The CAS-refused write reports equivalent base/attempted snapshot refs.

    ``write_part`` hands the stale base straight to the opstore CAS, so the
    refusal is the one that carries ``base_snapshot_ref`` and
    ``attempted_snapshot_ref`` — the pair a client uses to reconcile. Both are
    content-addressed, so "equivalent" here means *equal*.
    """
    candidate = WIDGET_SRC.replace("20.0", "31.5")
    out = await p.call(
        "write_part",
        {
            "name": "widget",
            "expected_hash": "sha256:" + "1" * 64,
            "script": candidate,
        },
        key="stale-write",
    )
    after = await p.call("read_part", {"name": "widget"})
    conflict = cast("dict[str, Any]", out.payload["conflict"])
    return {
        "outcome": out.observed(),
        "attempted_snapshot_ref": conflict["attempted_snapshot_ref"],
        "base_snapshot_ref": conflict["base_snapshot_ref"],
        "current_snapshot_ref": conflict["current_snapshot_ref"],
        "unchanged": after.payload["content_hash"],
        "no_write": "31.5" not in after.payload["script"],
    }


async def _ordinary_paging(p: PathUnderTest) -> dict[str, Any]:
    """Ordinary cursor paging over a frozen index, including reconstruction."""
    for name in ("alpha", "beta", "gamma"):
        created = await p.call("create_project_check", {"name": name}, key=f"check-{name}")
        assert created.ok, created
    first = await p.call("list_project_checks", {"limit": 2})
    cursor = str(first.payload["next_cursor"])
    # A mutation between pages lands in a later generation; the cursor's frozen
    # index must be unaffected on both paths.
    await p.call("create_project_check", {"name": "delta"}, key="check-delta")
    second = await p.call("list_project_checks", {"cursor": cursor, "limit": 2})
    bad = await p.call("list_project_checks", {"cursor": "not-a-cursor"})
    return {
        "first": first.observed(),
        "cursor": cursor,
        "second": second.observed(),
        "malformed_cursor": bad.observed(),
        "names": [
            cast("dict[str, Any]", item)["name"]
            for page in (first.payload, second.payload)
            for item in cast("list[Any]", page["items"])
        ],
        "frozen_index_stable": second.payload["check_set_ref"] == first.payload["check_set_ref"],
    }


async def _oversized_line_paging(p: PathUnderTest) -> dict[str, Any]:
    """A single >50 KiB line, paged to completion through read_artifact cursors.

    The line is longer than the whole text-result cap, so it cannot be delivered
    in one page on either path; the only lossless continuation is the absolute,
    snapshot-bound byte cursor. The page ends land mid-code-point, so the
    server's UTF-8 shortening is exercised on every page.
    """
    created = await p.call("create_part", {"name": "wide"}, key="create-wide")
    assert created.ok, created
    written = await p.call(
        "write_part",
        {
            "name": "wide",
            "expected_hash": created.payload["content_hash"],
            "script": OVERSIZED_LINE,
        },
        key="write-wide",
    )
    ref = str(written.payload["snapshot_ref"])

    pages: list[dict[str, Any]] = []
    reconstructed = ""
    offset = 0
    while True:
        page = await p.call("read_artifact", {"ref": ref, "offset_bytes": offset})
        assert page.ok, page
        body = page.payload
        pages.append(
            {
                "offset_bytes": body["offset_bytes"],
                "total_bytes": body["total_bytes"],
                "truncated": body["truncated"],
                "mime_type": body["mime_type"],
                "next_offset_bytes": body.get("next_offset_bytes"),
                "page_bytes": len(str(body["content"]).encode("utf-8")),
            }
        )
        reconstructed += str(body["content"])
        if not body["truncated"]:
            break
        offset = int(body["next_offset_bytes"])
        assert len(pages) < 20, "byte cursor is not making progress"

    mid_codepoint = await p.call("read_artifact", {"ref": ref, "offset_bytes": 3})
    return {
        "snapshot_ref": ref,
        "pages": pages,
        "page_count": len(pages),
        "reconstructed_matches": reconstructed == OVERSIZED_LINE,
        "reconstructed_bytes": len(reconstructed.encode("utf-8")),
        "single_line_over_50_kib": len(OVERSIZED_LINE.encode("utf-8")) > 51_200
        and OVERSIZED_LINE.count("\n") == 1,
        "mid_codepoint_offset": mid_codepoint.observed(),
    }


async def _unknown_object_denial(p: PathUnderTest) -> dict[str, Any]:
    """Addressing an object outside the bound project is refused identically."""
    out = await p.call("read_part", {"name": "ghost"})
    return {"denial": out.observed()}


async def _export_confinement_denial(p: PathUnderTest) -> dict[str, Any]:
    """Export targets may not leave the project's export root, by any route."""
    build = await p.call("build_part", {"name": "widget"}, key="build-widget")
    assert build.ok, build

    outside = p.root.parent / f"{p.root.name}-outside"
    outside.mkdir(exist_ok=True)
    exports = p.root / ".heph" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    link = exports / "escape"
    if not link.exists():
        link.symlink_to(outside, target_is_directory=True)

    traversal = await p.call(
        "export_part",
        {"name": "widget", "format": "step", "target": "../up.step"},
        key="export-traversal",
    )
    symlinked = await p.call(
        "export_part",
        {"name": "widget", "format": "step", "target": "escape/widget.step"},
        key="export-symlink",
    )
    return {
        "build_status": build.payload["status"],
        "build_artifact_ref": build.payload["artifact_ref"],
        "traversal": traversal.observed(),
        "symlinked_parent": symlinked.observed(),
        "nothing_escaped": sorted(q.name for q in outside.iterdir()) == [],
    }


async def _part_object_scope(p: PathUnderTest) -> dict[str, Any]:
    """Object scope where the two front doors deliberately differ.

    A bridge session bound to ``widget`` may not address ``bracket``. A local MCP
    client has no part binding at all — it *is* the agent, and its object scope
    is the project ``open_project`` bound — so the same call is authorized. The
    row pins both halves so neither can drift silently.
    """
    denied = await p.call("read_part", {"name": "bracket"}, as_part="widget")
    return {
        "ok": denied.ok,
        "reason": denied.reason,
        "reached_another_part": denied.ok and "bracket_body" in str(denied.payload.get("script")),
    }


ROWS: tuple[Row, ...] = (
    Row("mutation_lost_response_replay", _mutation_replay),
    Row(
        "mutation_edit_replay",
        _edit_replay,
        equivalence="documented_divergence",
        expect={
            "pi": {"replay_applied": False, "replay_conflicted": True},
            "mcp": {"replay_applied": True, "replay_conflicted": False},
        },
        # The outcome that matters is identical: one mutation, one live hash,
        # and a retry that names it.
        shared=(
            "first_applied",
            "first_content_hash",
            "replay_reports_live_hash",
            "live_hash",
            "live_script",
            "applied_once",
        ),
    ),
    Row("stale_hash_edit_conflict", _stale_hash_edit_conflict),
    Row("stale_hash_write_conflict_refs", _stale_hash_write_conflict),
    Row("ordinary_paging", _ordinary_paging),
    Row("oversized_single_line_paging", _oversized_line_paging),
    Row("object_scope_unknown_object", _unknown_object_denial),
    Row("object_scope_export_confinement", _export_confinement_denial),
    Row(
        "object_scope_part_session",
        _part_object_scope,
        equivalence="documented_divergence",
        expect={
            "pi": {"ok": False, "reason": "scope_denied", "reached_another_part": False},
            "mcp": {"ok": True, "reason": None, "reached_another_part": True},
        },
    ),
)


# --------------------------------------------------------------------------
# drivers


def run_pi(row: Row, root: Path) -> dict[str, Any]:
    path = PiPath(root)
    try:
        return asyncio.run(row.run(path))
    finally:
        path.close()


def run_mcp(row: Row, root: Path, *, capture: list[str] | None = None) -> dict[str, Any]:
    async def scenario() -> dict[str, Any]:
        async with McpPath(root) as path:
            try:
                return await row.run(path)
            finally:
                if capture is not None:
                    capture.extend(path.text_blocks)

    return asyncio.run(scenario())


def _diff(pi: Any, mcp: Any, trail: str = "") -> str | None:
    """The first structural difference between two observations, if any."""
    if isinstance(pi, dict) and isinstance(mcp, dict):
        left = cast("dict[str, Any]", pi)
        right = cast("dict[str, Any]", mcp)
        for missing in sorted(set(left) ^ set(right)):
            return f"{trail}.{missing}: pi={left.get(missing)!r} mcp={right.get(missing)!r}"
        for k in sorted(left):
            found = _diff(left[k], right[k], f"{trail}.{k}")
            if found is not None:
                return found
        return None
    if isinstance(pi, list) and isinstance(mcp, list):
        left_l = cast("list[Any]", pi)
        right_l = cast("list[Any]", mcp)
        if len(left_l) != len(right_l):
            return f"{trail}: length pi={len(left_l)} mcp={len(right_l)}"
        for i, (a, b) in enumerate(zip(left_l, right_l, strict=True)):
            found = _diff(a, b, f"{trail}[{i}]")
            if found is not None:
                return found
        return None
    if pi != mcp:
        return f"{trail}: pi={pi!r} mcp={mcp!r}"
    return None


# --------------------------------------------------------------------------
# the suite


@pytest.mark.parametrize("row", ROWS, ids=[r.name for r in ROWS])
def test_parity(row: Row, tmp_path: Path) -> None:
    """The same operation, both front doors, over identically seeded projects."""
    pi_root = seed_project(tmp_path / "pi")
    mcp_root = seed_project(tmp_path / "mcp")
    assert _project_digest(pi_root) == _project_digest(mcp_root), "seeds must be identical"

    pi_observed = run_pi(row, pi_root)
    mcp_observed = run_mcp(row, mcp_root)

    if row.equivalence == "identical":
        difference = _diff(pi_observed, mcp_observed)
        assert difference is None, f"{row.name} diverged at {difference}"
        return

    # A documented divergence still has to be exactly the divergence documented:
    # each path matches its own expectation on the differing keys, and the two
    # agree on every shared invariant.
    for observed, label in ((pi_observed, "pi"), (mcp_observed, "mcp")):
        expected = row.expect[label]
        assert {k: observed[k] for k in expected} == expected, f"{row.name}/{label}"
    shared_difference = _diff(
        {k: pi_observed[k] for k in row.shared}, {k: mcp_observed[k] for k in row.shared}
    )
    assert shared_difference is None, f"{row.name} shared invariant at {shared_difference}"
    assert set(row.expect["pi"]).isdisjoint(row.shared), "a key cannot both differ and be shared"


def _project_digest(root: Path) -> dict[str, str]:
    import hashlib

    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# -- the specific G3 clauses, asserted on the parity observations -----------


def test_parity_mutation_replay_is_recorded_not_repeated(tmp_path: Path) -> None:
    """Both paths replay the recorded result; neither performs the write twice."""
    row = _row("mutation_lost_response_replay")
    for observed in (
        run_pi(row, seed_project(tmp_path / "pi")),
        run_mcp(row, seed_project(tmp_path / "mcp")),
    ):
        assert observed["first"]["ok"] is True
        assert observed["replay"]["ok"] is True
        assert observed["first_was_not_a_replay"] is True
        assert observed["replay_was_signalled"] is True, "a replay must be distinguishable"
        assert observed["replay_matches_first"] is True
        assert observed["content_hash"].startswith("sha256:")


def test_parity_edit_retry_never_mutates_twice_on_either_path(tmp_path: Path) -> None:
    """The documented CAS-vs-ledger divergence, pinned from both sides.

    ``edit_part``'s retry shape differs by front door (see :func:`_edit_replay`).
    What must NOT differ is the effect: exactly one mutation, and a retry that
    hands back the live hash rather than a stale or invented one.
    """
    row = _row("mutation_edit_replay")
    pi = run_pi(row, seed_project(tmp_path / "pi"))
    mcp = run_mcp(row, seed_project(tmp_path / "mcp"))
    for observed in (pi, mcp):
        assert observed["first_applied"] is True
        assert observed["applied_once"] is True
        assert observed["replay_reports_live_hash"] == observed["live_hash"]
    assert pi["live_hash"] == mcp["live_hash"]
    assert pi["live_script"] == mcp["live_script"]
    # ...and the shapes really are the two documented ones.
    assert (pi["replay_applied"], pi["replay_conflicted"]) == (False, True)
    assert (mcp["replay_applied"], mcp["replay_conflicted"]) == (True, False)


def test_parity_conflicts_agree_on_hashes_and_refs(tmp_path: Path) -> None:
    """The reconcilable values in a conflict are content-addressed and equal."""
    row = _row("stale_hash_write_conflict_refs")
    pi = run_pi(row, seed_project(tmp_path / "pi"))
    mcp = run_mcp(row, seed_project(tmp_path / "mcp"))
    for observed in (pi, mcp):
        assert observed["outcome"]["ok"] is True  # a discriminated result, not an error
        assert observed["outcome"]["payload"]["applied"] is False
        assert observed["no_write"] is True
    assert pi["attempted_snapshot_ref"] == mcp["attempted_snapshot_ref"]
    assert pi["base_snapshot_ref"] == mcp["base_snapshot_ref"]
    assert pi["current_snapshot_ref"] == mcp["current_snapshot_ref"]
    assert pi["attempted_snapshot_ref"] != pi["current_snapshot_ref"]


def test_parity_error_taxonomy_is_shared(tmp_path: Path) -> None:
    """Refusals arrive under the same machine token on both paths."""
    row = _row("object_scope_export_confinement")
    pi = run_pi(row, seed_project(tmp_path / "pi"))
    mcp = run_mcp(row, seed_project(tmp_path / "mcp"))
    for observed in (pi, mcp):
        assert observed["traversal"]["reason"] == "invalid_target"
        assert observed["symlinked_parent"]["reason"] == "path_confinement"
        assert observed["nothing_escaped"] is True
    # The refusals are errors, not silently-successful no-ops.
    assert pi["traversal"]["ok"] is False and mcp["traversal"]["ok"] is False
    # Identical inputs produced the identical immutable build on both paths.
    assert pi["build_artifact_ref"] == mcp["build_artifact_ref"]


def test_parity_cursors_are_reconstructible_across_paths(tmp_path: Path) -> None:
    """A cursor minted on one path names the same frozen page on the other."""
    row = _row("ordinary_paging")
    pi = run_pi(row, seed_project(tmp_path / "pi"))
    mcp = run_mcp(row, seed_project(tmp_path / "mcp"))
    assert pi["cursor"] == mcp["cursor"], "the opaque cursor is content-addressed"
    assert pi["names"] == mcp["names"] == ["alpha", "beta", "gamma"]
    assert pi["frozen_index_stable"] is True and mcp["frozen_index_stable"] is True
    assert pi["malformed_cursor"]["reason"] == mcp["malformed_cursor"]["reason"] == "invalid_cursor"


def test_parity_oversized_line_pages_losslessly_on_both_paths(tmp_path: Path) -> None:
    """A single >50 KiB line reconstructs byte-exactly through byte cursors."""
    row = _row("oversized_single_line_paging")
    blocks: list[str] = []
    pi = run_pi(row, seed_project(tmp_path / "pi"))
    mcp = run_mcp(row, seed_project(tmp_path / "mcp"), capture=blocks)
    for observed in (pi, mcp):
        assert observed["single_line_over_50_kib"] is True
        assert observed["page_count"] > 1, "one line larger than the cap must page"
        assert observed["reconstructed_matches"] is True
        assert observed["reconstructed_bytes"] == len(OVERSIZED_LINE.encode("utf-8"))
        assert observed["pages"][-1]["truncated"] is False
        assert observed["mid_codepoint_offset"]["payload"]["error"] == "invalid_utf8_offset"
        # Every page but the last stops short of the requested size on a
        # code-point boundary, and the cursor always advances.
        offsets = [page["offset_bytes"] for page in observed["pages"]]
        assert offsets == sorted(set(offsets))
    assert pi["snapshot_ref"] == mcp["snapshot_ref"]
    assert pi["pages"] == mcp["pages"]

    # Transport shaping is the *only* difference: the MCP text block degrades to
    # a machine-readable notice when a page's JSON exceeds the 50 KiB text cap,
    # while the structured content it accompanies stayed complete (asserted by
    # the byte-exact reconstruction above).
    notices = [json.loads(b) for b in blocks if '"text_result_truncated"' in b]
    assert notices, "an over-cap page should have degraded its text block"
    assert notices[0]["status"] == "text_result_truncated"
    assert "content" in notices[0]["keys"]


def test_parity_part_scope_divergence_is_deliberate(tmp_path: Path) -> None:
    """The one documented divergence, pinned from both sides."""
    row = _row("object_scope_part_session")
    pi = run_pi(row, seed_project(tmp_path / "pi"))
    mcp = run_mcp(row, seed_project(tmp_path / "mcp"))
    # The bridge enforces part object scope...
    assert pi == {"ok": False, "reason": "scope_denied", "reached_another_part": False}
    # ...and an MCP client is orchestrator-equivalent, bound instead by the
    # project it opened (which is the scope the other denial rows cover).
    assert mcp == {"ok": True, "reason": None, "reached_another_part": True}


def _row(name: str) -> Row:
    return next(row for row in ROWS if row.name == name)
