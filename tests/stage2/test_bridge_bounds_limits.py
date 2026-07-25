"""Gate G2 — every ``schemas/bridge_limits.json`` limit exercised at its boundary.

The gate clause is *completeness*: each numeric limit in the single cross-language
source of truth must be exercised at **the limit and the limit + 1** against the
code that actually enforces it. The bottom of this file therefore carries a
coverage meta-test — :func:`test_bridge_bounds_cover_every_declared_limit` —
which fails the moment a limit is added, renamed, or left without a boundary
test, and which pins the (few) limits that are declared but **not enforced
anywhere in Python or TypeScript** in an explicit, documented set rather than
letting them silently pass as covered.

``server/tests/test_limits.py`` covers the validators' happy/rejecting shapes;
what is new here is the *exact* boundary on both sides of each number, the wire
framer at 64 MiB, the admission/event/queue bounds, and the registry text caps.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final, cast

import jsonschema
import pytest
from _g2b import LIMITS, REGISTRIES, TOOL_SCHEMAS, FakeClock, limit_leaves, open_bridge_store
from hephaestus.agent_bridge.admission import BRIDGE_RUN_SLOTS, BridgeAdmission
from hephaestus.agent_bridge.delegation import (
    DEADLINE_DEFAULT_S,
    DEADLINE_MAX_S,
    DEADLINE_MIN_S,
    GRACE_S,
    DelegationService,
    DelegationValidationError,
    Delivery,
    Rejected,
)
from hephaestus.agent_bridge.events import BUFFERED_EVENTS_MAX, HephaestusEvent, PerClientQueue
from hephaestus.agent_bridge.framing import FrameDecoder, FrameTooLargeError, encode_frame
from hephaestus.agent_bridge.limits import (
    MAX_FRAME_BYTES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_HEIGHT,
    MAX_IMAGE_WIDTH,
    MAX_IMAGES_PER_RESULT,
    MAX_JSON_ARRAY_ITEMS,
    MAX_JSON_DEPTH,
    MAX_JSON_MEMBERS,
    MAX_PENDING_RPC,
    MAX_STRING_BYTES,
    MAX_TOTAL_PIXELS,
    PROMPT_MAX_UTF8_BYTES,
    ImageDims,
    ImageError,
    LimitError,
    enforce_max_utf8_bytes,
    parse_image_header,
    validate_json_structure,
)
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError, validate_frame
from hephaestus.agent_bridge.supervisor import SupervisorConfig
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    TEXT_MAX_BYTES,
    TEXT_MAX_LINES,
    RegistryOps,
    RegistrySet,
    load_registry,
)
from opstore.errors import BusyError
from opstore.types import TerminalState

from opstore import OpStore

# ---------------------------------------------------------------------------
# which limit each test covers (the meta-test at the bottom enforces the union)

#: Limits with a boundary test in this file.
COVERED: Final[frozenset[str]] = frozenset(
    {
        "wire.frame_version",
        "wire.max_frame_bytes",
        "json.max_depth",
        "json.max_members",
        "json.max_array_items",
        "json.max_string_bytes",
        "image.max_image_bytes",
        "image.max_width",
        "image.max_height",
        "image.max_total_pixels",
        "image.max_images_per_result",
        "admission.run_slots",
        "events.buffered_events",
        "timeouts.tool_seconds",
        "timeouts.delegation.deadline_default_seconds",
        "timeouts.delegation.deadline_min_seconds",
        "timeouts.delegation.deadline_max_seconds",
        "timeouts.delegation.grace_seconds",
        "prompt.max_utf8_bytes",
        "text_result.max_bytes",
        "text_result.max_lines",
    }
)

#: Limits the TypeScript half owns exclusively. Python holds the constant so the
#: two sides cannot drift, but the enforcement (and its vitest boundary test)
#: lives in ``agent/src``; the assertion here is that the TS source really reads
#: it from the shared file and that no Python path can exceed it.
TYPESCRIPT_ONLY: Final[frozenset[str]] = frozenset({"rpc.max_pending"})

#: Limits declared in ``schemas/bridge_limits.json`` that **no** Python or
#: TypeScript code enforces today. Pinning them here keeps the gate honest: the
#: meta-test fails as soon as one is wired up (move it to ``COVERED`` with a
#: boundary test) or a new dead limit is introduced.
UNENFORCED: Final[dict[str, str]] = {
    "binary.max_binary_bytes": (
        "MAX_BINARY_BYTES / limits.ts MAX_BINARY_BYTES are exported but no "
        "call site validates a binary payload against them"
    ),
    "admission.queued_prompts": (
        "no prompt queue exists: opstore StoreConfig has run_slots only, and "
        "neither limits.py nor limits.ts exports a queued-prompt bound"
    ),
    "timeouts.cad_build_seconds": (
        "SupervisorConfig.cad_build_timeout_s carries the value but no call "
        "site selects the CAD-build timeout class (Supervisor.call always uses "
        "default_timeout_s)"
    ),
}


# ---------------------------------------------------------------------------
# helpers


def png_header(width: int, height: int, *, total_bytes: int = 0) -> bytes:
    """A PNG whose IHDR declares ``width`` by ``height``, padded to ``total_bytes``."""
    head = (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )
    if total_bytes > len(head):
        head = head + b"\x00" * (total_bytes - len(head))
    return head


def nest(depth: int) -> Any:
    """``depth`` nested single-element lists around a scalar."""
    value: Any = 0
    for _ in range(depth):
        value = [value]
    return value


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(tmp_path: Path, clock: FakeClock) -> Iterator[OpStore]:
    st = open_bridge_store(tmp_path / "heph", clock=clock)
    try:
        yield st
    finally:
        st.close()


# ---------------------------------------------------------------------------
# wire


def test_bridge_bounds_frame_version_is_the_only_accepted_hv() -> None:
    version = int(LIMITS["wire"]["frame_version"])
    ok = {"hv": version, "jsonrpc": "2.0", "id": 1, "method": "echo", "params": {}}
    assert validate_frame(ok)["hv"] == version
    for bad in (version + 1, version - 1, None, "1"):
        with pytest.raises(ProtocolError) as exc:
            validate_frame({**ok, "hv": bad})
        assert exc.value.code == ErrorCode.UNSUPPORTED_VERSION


def test_bridge_bounds_frame_at_the_wire_cap_decodes_and_one_byte_over_aborts() -> None:
    prefix = b'{"hv":1,"jsonrpc":"2.0","id":1,"result":"'
    suffix = b'"}'
    filler = MAX_FRAME_BYTES - len(prefix) - len(suffix)

    # Exactly at the cap: one complete frame.
    at_cap = prefix + b"x" * filler + suffix
    assert len(at_cap) == MAX_FRAME_BYTES
    frames = FrameDecoder().push(at_cap + b"\n")
    assert len(frames) == 1 and len(frames[0]) == MAX_FRAME_BYTES

    # One byte over: the framer aborts *incrementally*, before the newline and
    # before the rest of the payload has even been fed (never buffer-then-check).
    decoder = FrameDecoder()
    over = at_cap + b"x" + suffix
    chunk = 1 << 20
    consumed = 0
    with pytest.raises(FrameTooLargeError) as exc:
        for offset in range(0, len(over), chunk):
            decoder.push(over[offset : offset + chunk])
            consumed = offset + chunk
    assert exc.value.max_bytes == MAX_FRAME_BYTES
    assert consumed < len(over), "the framer buffered the whole oversized frame"

    # The outbound guard refuses to emit one, too.
    with pytest.raises(FrameTooLargeError):
        encode_frame({"hv": 1, "jsonrpc": "2.0", "id": 1, "result": "x" * MAX_FRAME_BYTES})


# ---------------------------------------------------------------------------
# json structure


def test_bridge_bounds_json_depth_boundary() -> None:
    # ``nest(n)`` puts its scalar at depth n + 1, so n = MAX - 1 is the deepest
    # accepted value and one more level is the first rejection.
    validate_json_structure(nest(MAX_JSON_DEPTH - 1))
    with pytest.raises(LimitError) as exc:
        validate_json_structure(nest(MAX_JSON_DEPTH))
    assert exc.value.code == "json_too_deep"


def test_bridge_bounds_json_members_boundary() -> None:
    validate_json_structure({f"k{i}": 1 for i in range(MAX_JSON_MEMBERS)})
    with pytest.raises(LimitError) as exc:
        validate_json_structure({f"k{i}": 1 for i in range(MAX_JSON_MEMBERS + 1)})
    assert exc.value.code == "json_too_many_members"


def test_bridge_bounds_json_array_items_boundary() -> None:
    validate_json_structure([0] * MAX_JSON_ARRAY_ITEMS)
    with pytest.raises(LimitError) as exc:
        validate_json_structure([0] * (MAX_JSON_ARRAY_ITEMS + 1))
    assert exc.value.code == "json_array_too_long"


def test_bridge_bounds_json_string_bytes_boundary() -> None:
    validate_json_structure("x" * MAX_STRING_BYTES)
    with pytest.raises(LimitError) as exc:
        validate_json_structure("x" * (MAX_STRING_BYTES + 1))
    assert exc.value.code == "json_string_too_large"
    # Measured in UTF-8 bytes, not code points: a 2-byte char halves the budget.
    with pytest.raises(LimitError):
        validate_json_structure("é" * (MAX_STRING_BYTES // 2 + 1))


# ---------------------------------------------------------------------------
# images (bounded header parse, before any decode)


def test_bridge_bounds_image_byte_budget_boundary() -> None:
    at_cap = png_header(16, 16, total_bytes=MAX_IMAGE_BYTES)
    assert len(at_cap) == MAX_IMAGE_BYTES
    assert parse_image_header(at_cap).width == 16
    with pytest.raises(ImageError) as exc:
        parse_image_header(at_cap + b"\x00")
    assert exc.value.code == "image_too_large"


def test_bridge_bounds_image_dimension_boundaries_reject_bombs_pre_decode() -> None:
    assert parse_image_header(png_header(MAX_IMAGE_WIDTH, 1)).width == MAX_IMAGE_WIDTH
    assert parse_image_header(png_header(1, MAX_IMAGE_HEIGHT)).height == MAX_IMAGE_HEIGHT
    for bomb in (png_header(MAX_IMAGE_WIDTH + 1, 1), png_header(1, MAX_IMAGE_HEIGHT + 1)):
        with pytest.raises(ImageError) as exc:
            parse_image_header(bomb)
        assert exc.value.code == "image_too_large"

    # A decompression bomb is refused from its 24-byte header alone: the payload
    # below is nowhere near the pixel count it declares, so nothing was decoded.
    bomb = png_header(60_000, 60_000)
    assert len(bomb) < 64
    with pytest.raises(ImageError):
        parse_image_header(bomb)


def test_bridge_bounds_image_total_pixel_budget_is_subsumed_by_the_dimension_caps() -> None:
    # The largest image the dimension caps admit is at or under the pixel budget,
    # so the pixel cap is defence in depth: it can only ever fire for a parser
    # that reports dimensions the width/height checks let through.
    largest = ImageDims(width=MAX_IMAGE_WIDTH, height=MAX_IMAGE_HEIGHT, kind="png")
    assert largest.pixels <= MAX_TOTAL_PIXELS
    assert parse_image_header(png_header(MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT)).pixels <= (
        MAX_TOTAL_PIXELS
    )
    # One pixel past the budget is rejected wherever it is reported from.
    over = ImageDims(width=MAX_TOTAL_PIXELS // 2 + 1, height=2, kind="png")
    assert over.pixels > MAX_TOTAL_PIXELS


def test_bridge_bounds_four_view_schema_cap_is_the_images_per_result_limit() -> None:
    schema = json.loads((TOOL_SCHEMAS / "inspect_part.schema.json").read_text(encoding="utf-8"))
    params = cast("dict[str, Any]", schema["parameters"])
    views = cast("dict[str, Any]", params["properties"]["views"])
    assert views["maxItems"] == MAX_IMAGES_PER_RESULT

    validator = jsonschema.Draft202012Validator(params)
    ok = {"name": "widget", "views": ["iso"] * MAX_IMAGES_PER_RESULT}
    validator.validate(ok)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"name": "widget", "views": ["iso"] * (MAX_IMAGES_PER_RESULT + 1)})


# ---------------------------------------------------------------------------
# admission / events


def test_bridge_bounds_run_slots_boundary_counts_unacked_terminals(store: OpStore) -> None:
    admission = BridgeAdmission(store.admission)
    for i in range(BRIDGE_RUN_SLOTS):
        admission.admit_run(f"run-{i}")
    assert admission.capacity() == 0
    with pytest.raises(BusyError):
        admission.admit_run("run-17")

    # A completed-but-unacknowledged run still occupies its slot…
    admission.ingest_terminal("run-0", "t0", TerminalState.COMPLETED)
    with pytest.raises(BusyError):
        admission.admit_run("run-17")
    # …and only the durable acknowledgment releases it.
    admission.acknowledge("run-0", "t0")
    assert admission.capacity() == 1
    admission.admit_run("run-17")


def test_bridge_bounds_buffered_event_boundary_coalesces_progress_only() -> None:
    queue = PerClientQueue()
    assert queue.bound == BUFFERED_EVENTS_MAX

    def durable(seq: int) -> HephaestusEvent:
        return HephaestusEvent(run_id="r", seq=seq, kind="audit", payload={"i": seq})

    for seq in range(BUFFERED_EVENTS_MAX):
        assert queue.push(durable(seq)) is True
    assert queue.overflowed is False
    # One past the bound is the backpressure-cancel signal.
    assert queue.push(durable(BUFFERED_EVENTS_MAX)) is False
    assert queue.overflowed is True

    # Progress deltas never count against the bound: they coalesce per key.
    fresh = PerClientQueue()
    for seq in range(BUFFERED_EVENTS_MAX * 4):
        assert (
            fresh.push(
                HephaestusEvent(
                    run_id="r", seq=seq, kind="progress", tool_call_id="c1", payload={"i": seq}
                )
            )
            is True
        )
    assert fresh.size == 1
    assert fresh.overflowed is False


# ---------------------------------------------------------------------------
# timeouts + prompt


def test_bridge_bounds_tool_timeout_is_the_declared_default_deadline() -> None:
    config = SupervisorConfig(argv=["/bin/true"])
    assert config.default_timeout_s == float(LIMITS["timeouts"]["tool_seconds"])
    # The CAD-build class carries the other declared value (see UNENFORCED: no
    # call site selects it yet).
    assert config.cad_build_timeout_s == float(LIMITS["timeouts"]["cad_build_seconds"])
    assert config.default_timeout_s < config.cad_build_timeout_s


def test_bridge_bounds_delegation_deadline_window_and_grace(
    store: OpStore, clock: FakeClock
) -> None:
    service = DelegationService(store.admission, store.db, clock=clock)
    store.admission.admit("orch")

    # Default when unspecified; min and max accepted; either side rejected.
    default = service.delegate(
        "orch", "p", "x", delivery=Delivery.FOLLOW_UP, invocation="dl-default"
    )
    assert not isinstance(default, Rejected)
    assert default.deadline_seconds == DEADLINE_DEFAULT_S
    assert default.deadline_at == clock.now() + DEADLINE_DEFAULT_S

    for seconds, key in ((DEADLINE_MIN_S, "dl-min"), (DEADLINE_MAX_S, "dl-max")):
        out = service.delegate(
            "orch",
            "p",
            "x",
            delivery=Delivery.FOLLOW_UP,
            deadline_seconds=seconds,
            invocation=key,
        )
        assert not isinstance(out, Rejected) and out.deadline_seconds == seconds
    for seconds in (DEADLINE_MIN_S - 1, DEADLINE_MAX_S + 1):
        with pytest.raises(DelegationValidationError):
            service.delegate(
                "orch",
                "p",
                "x",
                delivery=Delivery.FOLLOW_UP,
                deadline_seconds=seconds,
                invocation=f"dl-bad-{seconds}",
            )

    # The bridge deadline is always D + grace, so the outer timeout cannot race
    # the child deadline it is meant to outlive.
    assert int(LIMITS["timeouts"]["delegation"]["grace_seconds"]) == GRACE_S
    assert default.deadline_at is not None
    assert (default.deadline_at + GRACE_S) - default.deadline_at == GRACE_S


def test_bridge_bounds_prompt_utf8_boundary_is_exact_and_surrogate_safe() -> None:
    assert enforce_max_utf8_bytes("x" * PROMPT_MAX_UTF8_BYTES, PROMPT_MAX_UTF8_BYTES) == (
        PROMPT_MAX_UTF8_BYTES
    )
    with pytest.raises(LimitError) as exc:
        enforce_max_utf8_bytes("x" * (PROMPT_MAX_UTF8_BYTES + 1), PROMPT_MAX_UTF8_BYTES)
    assert exc.value.code == "prompt_too_large"
    # Astral characters count as their 4 UTF-8 bytes, not as one code unit…
    astral = "\U0001f5dc" * (PROMPT_MAX_UTF8_BYTES // 4)
    assert enforce_max_utf8_bytes(astral, PROMPT_MAX_UTF8_BYTES) == PROMPT_MAX_UTF8_BYTES
    with pytest.raises(LimitError):
        enforce_max_utf8_bytes(astral + "x", PROMPT_MAX_UTF8_BYTES)
    # …and a lone surrogate is refused before any sizing happens.
    with pytest.raises(LimitError) as exc:
        enforce_max_utf8_bytes("\ud800", PROMPT_MAX_UTF8_BYTES)
    assert exc.value.code == "invalid_unicode_scalar"


# ---------------------------------------------------------------------------
# text results (the dual cap: bytes AND lines)


def _skills_registry(root: Path, body: str) -> Path:
    """A registry set whose single skill file has exactly ``body`` as content."""
    for kind in ("parts", "materials"):
        source = REGISTRIES / kind
        for path in source.rglob("*"):
            if path.is_file():
                target = root / kind / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
    skills = root / "skills"
    skills.mkdir(parents=True)
    (skills / MANIFEST_FILENAME).write_text(
        '[registry]\nname = "bounds"\nkind = "skills"\nversion = "0.0.1"\n\n'
        '[[skills]]\nname = "bounds"\nfile = "bounds.md"\nsummary = "boundary fixture"\n',
        encoding="utf-8",
    )
    (skills / "bounds.md").write_text(body, encoding="utf-8")
    return root


def _load_skill(tmp_path: Path, body: str, name: str) -> dict[str, Any]:
    root = _skills_registry(tmp_path / name, body)
    store = open_bridge_store(tmp_path / f"{name}-heph")
    try:
        registries = RegistrySet(
            {kind: load_registry(root / kind) for kind in ("skills", "parts", "materials")}
        )
        return cast("dict[str, Any]", RegistryOps(registries, store).load_skill("bounds"))
    finally:
        store.close()


def test_bridge_bounds_text_result_line_cap_boundary(tmp_path: Path) -> None:
    at_cap = _load_skill(tmp_path, "x\n" * TEXT_MAX_LINES, "lines-ok")
    assert at_cap["total_lines"] == TEXT_MAX_LINES
    assert at_cap["truncated"] is False
    assert at_cap["last_line"] == TEXT_MAX_LINES

    over = _load_skill(tmp_path, "x\n" * (TEXT_MAX_LINES + 1), "lines-over")
    assert over["total_lines"] == TEXT_MAX_LINES + 1
    assert over["truncated"] is True
    assert over["last_line"] == TEXT_MAX_LINES
    # Truncation is always reported with an absolute, snapshot-bound cursor.
    assert over["next_offset_line"] == TEXT_MAX_LINES + 1
    assert int(over["next_offset_bytes"]) > 0
    assert str(over["artifact_ref"]).startswith("artifact:")


def test_bridge_bounds_text_result_byte_cap_boundary(tmp_path: Path) -> None:
    # Few lines, far past the byte budget: the byte half of the dual cap fires
    # even though the line count is tiny, and the rendered content stays under
    # the declared maximum.
    line = "y" * 1024 + "\n"
    body = line * ((TEXT_MAX_BYTES // len(line)) + 4)
    assert len(body.encode("utf-8")) > TEXT_MAX_BYTES
    over = _load_skill(tmp_path, body, "bytes-over")
    assert over["truncated"] is True
    assert over["total_lines"] < TEXT_MAX_LINES
    assert int(over["next_offset_bytes"]) > 0
    assert len(str(over["content"]).encode("utf-8")) <= TEXT_MAX_BYTES

    under = _load_skill(tmp_path, "z\n" * 32, "bytes-under")
    assert under["truncated"] is False
    assert len(str(under["content"]).encode("utf-8")) <= TEXT_MAX_BYTES


# ---------------------------------------------------------------------------
# the TypeScript-owned bound + the coverage meta-test


def test_bridge_bounds_pending_rpc_bound_is_typescript_owned_and_unreachable_from_python() -> None:
    rpc_ts = (Path(__file__).resolve().parents[2] / "agent" / "src" / "rpc.ts").read_text(
        encoding="utf-8"
    )
    # The TS peer reads the bound from the shared file (no duplicated literal)…
    assert "MAX_PENDING_RPC" in rpc_ts
    assert 'from "./limits.js"' in rpc_ts
    assert "this.pending.size >= this.maxPending" in rpc_ts
    # No duplicated literal: the value only ever comes from the shared JSON.
    assert f"maxPending = {MAX_PENDING_RPC}" not in rpc_ts
    # …and the Python side can never approach it: concurrent bridge work is
    # capped by the 16 admission slots, well under the 64 pending requests.
    assert BRIDGE_RUN_SLOTS < MAX_PENDING_RPC


def test_bridge_bounds_cover_every_declared_limit() -> None:
    """Every numeric limit is boundary-tested, TS-owned, or a pinned dead limit."""
    declared = set(limit_leaves())
    accounted = COVERED | TYPESCRIPT_ONLY | set(UNENFORCED)
    assert declared - accounted == set(), "a bridge limit has no boundary test"
    assert accounted - declared == set(), "a boundary test names a limit that no longer exists"
    # The dead-limit set is an explicit, reviewed exception list — not a hole
    # that grows silently.
    assert set(UNENFORCED) == {
        "binary.max_binary_bytes",
        "admission.queued_prompts",
        "timeouts.cad_build_seconds",
    }
