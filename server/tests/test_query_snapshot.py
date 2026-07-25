"""query_snapshot tests: bounds enforced Python-side, no images to parent, budget charged."""

from __future__ import annotations

import asyncio

import pytest
from hephaestus.agent_bridge.query_snapshot import (
    QUERY_SNAPSHOT_MAX_IMAGES,
    QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS,
    QuerySnapshotError,
    QuerySnapshotService,
    RenderBundle,
    SnapshotRequest,
    SnapshotResult,
    SnapshotUsage,
)


class FakePreparer:
    def __init__(self, n_images: int = 2) -> None:
        self._n = n_images
        self.calls: list[str] = []

    def prepare(self, run_id: str, question: str, image_refs: tuple[str, ...]) -> RenderBundle:
        self.calls.append(run_id)
        return RenderBundle(image_refs=tuple(f"img-{i}" for i in range(self._n)))


class FakeCaller:
    def __init__(self, result: SnapshotResult, *, delay: float = 0.0) -> None:
        self._result = result
        self._delay = delay
        self.last_request: SnapshotRequest | None = None

    async def call(self, request: SnapshotRequest) -> SnapshotResult:
        self.last_request = request
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._result


class FakeLedger:
    def __init__(self) -> None:
        self.charges: list[tuple[str, SnapshotUsage]] = []

    def charge(self, run_id: str, usage: SnapshotUsage) -> None:
        self.charges.append((run_id, usage))


def test_happy_path_returns_text_and_refs_only() -> None:
    usage = SnapshotUsage(output_tokens=100, input_tokens=50, turns=1)
    caller = FakeCaller(SnapshotResult(text="a shelf", refs=("art-1",), usage=usage))
    ledger = FakeLedger()
    svc = QuerySnapshotService(FakePreparer(), caller, ledger)
    result = asyncio.run(svc.run("parent-1", "child-1", "what is this?"))
    assert result.text == "a shelf"
    assert result.refs == ("art-1",)
    # The parent budget was charged with the child's usage.
    assert ledger.charges == [("parent-1", usage)]
    # The child was called with the single-turn / token / time bounds.
    assert caller.last_request is not None
    assert caller.last_request.max_output_tokens == QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS
    assert caller.last_request.max_turns == 1


def test_bad_question_prompt_too_large() -> None:
    caller = FakeCaller(SnapshotResult(text="x"))
    svc = QuerySnapshotService(FakePreparer(), caller, FakeLedger())
    big = "q" * (32768 + 1)
    with pytest.raises(QuerySnapshotError) as exc:
        asyncio.run(svc.run("p", "c", big))
    assert exc.value.code == "prompt_too_large"
    assert caller.last_request is None  # never dispatched


def test_too_many_input_images() -> None:
    caller = FakeCaller(SnapshotResult(text="x"))
    svc = QuerySnapshotService(FakePreparer(), caller, FakeLedger())
    refs = tuple(f"r{i}" for i in range(QUERY_SNAPSHOT_MAX_IMAGES + 1))
    with pytest.raises(QuerySnapshotError) as exc:
        asyncio.run(svc.run("p", "c", "q", refs))
    assert exc.value.code == "too_many_images"


def test_render_bundle_over_image_cap() -> None:
    caller = FakeCaller(SnapshotResult(text="x"))
    svc = QuerySnapshotService(
        FakePreparer(n_images=QUERY_SNAPSHOT_MAX_IMAGES + 1), caller, FakeLedger()
    )
    with pytest.raises(QuerySnapshotError) as exc:
        asyncio.run(svc.run("p", "c", "q"))
    assert exc.value.code == "too_many_images"


def test_token_budget_reenforced_python_side() -> None:
    # The child claims more output tokens than allowed: reject even though it returned.
    over = SnapshotUsage(output_tokens=QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS + 1)
    caller = FakeCaller(SnapshotResult(text="too long", usage=over))
    ledger = FakeLedger()
    svc = QuerySnapshotService(FakePreparer(), caller, ledger)
    with pytest.raises(QuerySnapshotError) as exc:
        asyncio.run(svc.run("p", "c", "q"))
    assert exc.value.code == "token_budget_exceeded"
    assert ledger.charges == []  # not charged on a bound violation


def test_multi_turn_reenforced_python_side() -> None:
    two_turns = SnapshotUsage(output_tokens=10, turns=2)
    caller = FakeCaller(SnapshotResult(text="x", usage=two_turns))
    svc = QuerySnapshotService(FakePreparer(), caller, FakeLedger())
    with pytest.raises(QuerySnapshotError) as exc:
        asyncio.run(svc.run("p", "c", "q"))
    assert exc.value.code == "too_many_turns"


def test_timeout_enforced_python_side(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shrink the hard timeout so the test is fast, then make the child overrun it.
    import hephaestus.agent_bridge.query_snapshot as qs

    monkeypatch.setattr(qs, "QUERY_SNAPSHOT_TIMEOUT_S", 0.05)
    caller = FakeCaller(SnapshotResult(text="late"), delay=1.0)
    svc = QuerySnapshotService(FakePreparer(), caller, FakeLedger())
    with pytest.raises(QuerySnapshotError) as exc:
        asyncio.run(svc.run("p", "c", "q"))
    assert exc.value.code == "timed_out"
