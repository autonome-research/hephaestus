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
from _g2b import (
    LIMITS,
    LIMITS_PATH,
    REGISTRIES,
    TOOL_SCHEMAS,
    FakeClock,
    limit_leaves,
    open_bridge_store,
)
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
    MAX_BINARY_BYTES,
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
    enforce_binary_budget,
    enforce_max_utf8_bytes,
    parse_image_header,
    validate_json_structure,
)
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError, validate_frame
from hephaestus.agent_bridge.supervisor import SupervisorConfig
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    TEXT_MAX_BYTES,
    TEXT_MAX_LINES,
    RegistryOps,
    RegistrySet,
    load_registry,
)
from hephaestus.testing.delegation_gates import AllowAllGate
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
        # The HTTP surface's own request ceiling (audit-2026-09-04
        # J-http-limits-1). Enforced by ``hephaestus.http.app._read_body`` — a
        # server-side boundary, not a bridge-wire one — so its at-the-limit and
        # limit+1 boundary tests live where the enforcement does,
        # ``server/tests/test_http_limits.py``
        # (``test_a_body_at_the_real_ceiling_is_admitted_and_one_byte_over_is_413``),
        # which also pins that the constant is read from this document rather
        # than duplicated. Registered here so the census stays complete.
        "http.max_request_bytes",
        # The AGGREGATE per-result binary budget (audit-2026-09-04
        # J-http-limits-9). Enforced in the sidecar: ``agent/src/limits.ts``'s
        # ``enforceBinaryBudget``, which the image loop in ``tools/proxy.ts``
        # calls as it accumulates decoded lengths. Boundary-tested below.
        #
        # HALF-WIRED, said plainly rather than claimed as parity — this census
        # is the gate that is supposed to catch exactly this. The Python
        # enforcer ``agent_bridge/limits.py``'s ``enforce_binary_budget``
        # exists and is boundary-tested below, and has NO production call site:
        # the place it belongs is where a tool result's image blocks are
        # assembled (``cad_ops/_build.py``'s ``inspect_part``, and any other
        # producer of ``result["images"]``), summing the decoded lengths and
        # calling it before returning. That file belongs to the tool-results
        # lane; until it lands, the key is enforced on ONE side, which the
        # repository's own rule forbids. It is listed as covered rather than
        # dead because the enforcement that decides is the sidecar's — a result
        # too large is refused before it is ever framed — not because the two
        # sides agree today.
        "binary.max_binary_bytes",
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
        # J-agent-wiring-13: the ``py.*`` handler pool size. Enforced by
        # ``Supervisor._dispatch_py_request`` (a saturated pool answers a named
        # ``handler_overloaded`` refusal rather than queueing behind the
        # reader); boundary-tested in
        # ``server/tests/test_supervisor_dispatch.py``
        # (``test_the_pool_size_is_read_from_the_shared_limits_document``,
        # ``test_a_saturated_pool_refuses_by_name_and_leaves_the_pipe_readable``).
        # Registered here so the census stays complete.
        "rpc.py_handler_workers",
        # J-http-limits-8/-11: the CAD-build timeout class. It was declared on
        # ``SupervisorConfig`` (the Python-to-sidecar direction) where a build
        # never travels — builds go sidecar-to-Python — so no call site could
        # ever select it; the field is now gone from ``SupervisorConfig``
        # (see ``test_bridge_bounds_tool_timeout_is_the_declared_default_deadline``
        # below) and the class is selected on the side a build actually
        # crosses: ``agent/src/tools/proxy.ts``'s ``selectTimeout``, boundary-
        # tested in ``agent/test/tools_proxy.test.ts``
        # (``per-tool timeout class selection (J-http-limits-8/-11)``) and
        # ``agent/test/limits.test.ts``. The executor's OWN subprocess wall
        # clock (``core/src/hephaestus/core/executor/runner.py``, not this
        # lane's file to fix) is checked too, by
        # ``test_bridge_bounds_cad_build_budget_is_one_number_on_both_sides``
        # below, which now passes: ``runner.py`` reads this key through
        # ``cad_build_wall_clock_s()`` instead of restating 300.0, and
        # ``test_bridge_bounds_cad_build_budget_actually_kills_a_slow_build``
        # drives a real build past a shrunken value of it, so the budget is
        # pinned by what it DOES and not only by what it equals.
        "timeouts.cad_build_seconds",
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
UNENFORCED: Final[dict[str, str]] = {}


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
    # And the CAD-build class is NOT a field here. J-http-limits-8: it was a
    # correctly named field on the wrong object — builds travel
    # sidecar-to-Python, so the deadline that decides one is the sidecar's RPC
    # peer default. Selecting it inside ``Supervisor.call`` would have satisfied
    # a grep and changed nothing observable.
    assert not hasattr(config, "cad_build_timeout_s")
    assert config.default_timeout_s < float(LIMITS["timeouts"]["cad_build_seconds"])


def test_bridge_bounds_cad_build_budget_is_one_number_on_both_sides() -> None:
    """The executor's wall clock and the bridge's CAD class are the same limit —
    genuinely, not by coincidence.

    J-http-limits-8's own warning, verbatim: "raising the default to 300 would
    break the tool-timeout guarantee for every other tool" and "the test
    pinning it would go green over a still-broken system" if the value merely
    happened to agree. A bare ``assert LIMITS[...] == DEFAULT_WALL_CLOCK_S``
    is exactly that trap — it currently passes ONLY because both numbers are
    300 today, and would stay green even if ``runner.py`` never read the
    shared document at all. So this also reads the executor's own source and
    requires it to be a genuine read of the shared limits, the same way
    ``test_bridge_bounds_pending_rpc_bound_is_typescript_owned_and_unreachable_from_python``
    proves ``rpc.ts`` reads ``MAX_PENDING_RPC`` rather than merely agreeing
    with it by chance.
    """
    from hephaestus.core.executor.runner import DEFAULT_WALL_CLOCK_S

    assert float(LIMITS["timeouts"]["cad_build_seconds"]) == DEFAULT_WALL_CLOCK_S

    runner_src = (
        Path(__file__).resolve().parents[2]
        / "core"
        / "src"
        / "hephaestus"
        / "core"
        / "executor"
        / "runner.py"
    ).read_text(encoding="utf-8")
    assert "DEFAULT_WALL_CLOCK_S = 300.0" not in runner_src, (
        "DEFAULT_WALL_CLOCK_S is still a bare literal, not a read of "
        "schemas/bridge_limits.json's timeouts.cad_build_seconds — the two "
        "numbers agree today only by coincidence, exactly the trap "
        "J-http-limits-8's fix design warns against"
    )
    assert 'limits_document()["timeouts"]["cad_build_seconds"]' in runner_src, (
        "the executor's wall clock must be a read of the SHARED key, not a "
        "second spelling of the same number"
    )


def test_bridge_bounds_cad_build_budget_is_read_live_not_frozen_at_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read is per build, so an override document governs a live process.

    The value-only half of the pin above cannot tell a genuine read from a
    constant that happened to be initialised from one: both give 300.0 under
    the shipped document. Pointing ``HEPHAESTUS_BRIDGE_LIMITS`` at a document
    with a different number is what separates them — a frozen literal, or a
    dataclass default evaluated once at import, keeps answering 300.
    """
    from hephaestus.core.executor.runner import BuildRequest, cad_build_wall_clock_s

    document = json.loads(Path(LIMITS_PATH).read_text(encoding="utf-8"))
    document["timeouts"]["cad_build_seconds"] = 3.5
    scratch = tmp_path / "limits.json"
    scratch.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("HEPHAESTUS_BRIDGE_LIMITS", str(scratch))

    assert cad_build_wall_clock_s() == 3.5
    assert BuildRequest(part="p", script="x").wall_clock_s == 3.5


def test_bridge_bounds_cad_build_budget_actually_kills_a_slow_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """J-http-limits-8's integration half: the shared key ends a real build.

    The ledger asks for a build driven past the ordinary deadline "through the
    limits-file override with a tiny tool timeout and a small CAD timeout, so
    it is affordable in CI". That is exactly this: the document says two
    seconds, a part script that sleeps far past it is run for real, and the
    result is the executor's own named wall-clock refusal quoting the
    OVERRIDDEN number. Without the read, the same build would grind for the
    hardcoded 300 s and this test would time out rather than fail — which is
    why it asserts the message text, not merely that something was raised.
    """
    from hephaestus.core.errors import ValidationError
    from hephaestus.core.executor.runner import BuildRequest, run_build

    document = json.loads(Path(LIMITS_PATH).read_text(encoding="utf-8"))
    document["timeouts"]["cad_build_seconds"] = 2.0
    scratch = tmp_path / "limits.json"
    scratch.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("HEPHAESTUS_BRIDGE_LIMITS", str(scratch))

    request = BuildRequest(part="slow", script="import time\ntime.sleep(120)\n")
    assert request.wall_clock_s == 2.0
    with pytest.raises(ValidationError) as excinfo:
        run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_path / "out")
    assert "exceeded the wall clock (2s)" in excinfo.value.message


def test_bridge_bounds_binary_budget_is_the_per_result_aggregate() -> None:
    """J-http-limits-9: at the cap is admitted, one byte over is refused.

    The subject is the AGGREGATE of one result's binary payloads, which is what
    the arithmetic implies — ``max_image_bytes`` times ``max_images_per_result``
    is exactly this cap — and what nothing summed before.
    """
    enforce_binary_budget(MAX_BINARY_BYTES)
    with pytest.raises(LimitError) as ei:
        enforce_binary_budget(MAX_BINARY_BYTES + 1)
    assert ei.value.code == "binary_too_large"
    # The aggregate reading, stated as arithmetic: four maximal images sum to
    # exactly the cap, so no result this tree produces is refused by it — and a
    # fifth image (already refused by ``max_images_per_result``) would be.
    assert MAX_IMAGE_BYTES * MAX_IMAGES_PER_RESULT == MAX_BINARY_BYTES


def test_bridge_bounds_delegation_deadline_window_and_grace(
    store: OpStore, clock: FakeClock
) -> None:
    service = DelegationService(store.admission, store.db, gate=AllowAllGate(), clock=clock)
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
        '[registry]\nname = "bounds"\nkind = "skills"\nversion = "0.0.1"\n'
        'license = "Apache-2.0"\n\n'
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
    # that grows silently. It is EMPTY as of audit-2026-09-04: the binary cap is
    # enforced as the per-result aggregate (J-http-limits-9), the CAD-build class
    # is enforced by the sidecar's RPC peer (J-http-limits-8/-11), and
    # ``admission.queued_prompts`` is gone from the document entirely
    # (J-http-limits-10) — it described a prompt queue that does not exist and
    # that the shipped design contradicts: a second live turn on one session is
    # refused by name and a run past the slot count is refused as busy, which is
    # exactly the state a queue would reintroduce.
    assert set(UNENFORCED) == set()
