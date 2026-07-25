"""Ephemeral ``query_snapshot`` vision-child orchestration (digest §2, arch §4.1).

The multimodal snapshot child answers a single visual question about the current
build with **no tools, no extensions, no recursion, no persistence**, a single
turn, ≤ 1024 output tokens, and a 60 s hard timeout. It bypasses thread-phase.
This orchestrator:

1. prepares the render bundle for the question via Stage 1
   ``prepare_render_bundle`` (injected as :class:`RenderBundlePreparer`), bounding
   the image count by ``image.max_images_per_result`` from the limits file;
2. issues the ``query.snapshot`` bridge request (injected as
   :class:`SnapshotCaller`) with the single-turn / token / time bounds, and
   **re-enforces every bound Python-side** (defence in depth: the timeout via
   ``asyncio.wait_for``, the token budget and turn count against the returned
   usage);
3. charges the measured usage to the **parent** run's budget record (injected
   :class:`BudgetLedger`);
4. returns **text and artifact refs only** — image blocks never enter the parent
   context (the immutable render artifacts stay on disk, referenced by ref).

The 1024-token / 60 s / single-turn values are the normative ``query_snapshot``
profile defaults (they are profile config, not bridge wire limits, so they are
named here rather than in ``bridge_limits.json``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .limits import LIMITS, LimitError, enforce_max_utf8_bytes

__all__ = [
    "QUERY_SNAPSHOT_MAX_IMAGES",
    "QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS",
    "QUERY_SNAPSHOT_MAX_TURNS",
    "QUERY_SNAPSHOT_TIMEOUT_S",
    "BudgetLedger",
    "QuerySnapshotError",
    "QuerySnapshotResult",
    "QuerySnapshotService",
    "RenderBundle",
    "RenderBundlePreparer",
    "SnapshotCaller",
    "SnapshotRequest",
    "SnapshotResult",
    "SnapshotUsage",
]

# Normative query_snapshot profile bounds (digest §2). The image cap alone is a
# wire limit, so it is read from the limits file (no literal duplicated).
QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS: int = 1024
QUERY_SNAPSHOT_TIMEOUT_S: float = 60.0
QUERY_SNAPSHOT_MAX_TURNS: int = 1
QUERY_SNAPSHOT_MAX_IMAGES: int = int(LIMITS["image"]["max_images_per_result"])

# The question shares the prompt UTF-8 budget.
_PROMPT_MAX_UTF8_BYTES: int = int(LIMITS["prompt"]["max_utf8_bytes"])


class QuerySnapshotError(Exception):
    """A snapshot run violated a bound or failed. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class RenderBundle:
    """A prepared render bundle: image refs (and optional inline bytes) for the child."""

    image_refs: tuple[str, ...]
    images: tuple[bytes, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotUsage:
    """Usage the vision child reported (charged to the parent budget)."""

    output_tokens: int
    input_tokens: int = 0
    turns: int = 1
    cost: float = 0.0


@dataclass(frozen=True, slots=True)
class SnapshotRequest:
    """The bounded ``query.snapshot`` request handed to the sidecar."""

    run_id: str
    question: str
    image_refs: tuple[str, ...]
    max_output_tokens: int
    max_turns: int
    timeout_s: float


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """The sidecar's snapshot answer: text + refs + usage (images stay on disk)."""

    text: str
    refs: tuple[str, ...] = ()
    usage: SnapshotUsage = field(default_factory=lambda: SnapshotUsage(output_tokens=0))


@dataclass(frozen=True, slots=True)
class QuerySnapshotResult:
    """What the parent sees: text and artifact refs only — never image blocks."""

    text: str
    refs: tuple[str, ...]
    usage: SnapshotUsage


@runtime_checkable
class RenderBundlePreparer(Protocol):
    """Stage-1 ``prepare_render_bundle`` (injected; real impl in core.render)."""

    def prepare(self, run_id: str, question: str, image_refs: tuple[str, ...]) -> RenderBundle: ...


@runtime_checkable
class SnapshotCaller(Protocol):
    """Issues the ``query.snapshot`` bridge request to the ephemeral vision child."""

    async def call(self, request: SnapshotRequest) -> SnapshotResult: ...


@runtime_checkable
class BudgetLedger(Protocol):
    """Charges usage to a run's budget record (the parent's, for snapshots)."""

    def charge(self, run_id: str, usage: SnapshotUsage) -> None: ...


class QuerySnapshotService:
    """Orchestrates one ephemeral vision child, enforcing every bound twice."""

    def __init__(
        self,
        preparer: RenderBundlePreparer,
        caller: SnapshotCaller,
        ledger: BudgetLedger,
    ) -> None:
        self._preparer = preparer
        self._caller = caller
        self._ledger = ledger

    async def run(
        self,
        parent_run_id: str,
        child_run_id: str,
        question: str,
        image_refs: tuple[str, ...] = (),
    ) -> QuerySnapshotResult:
        """Run the snapshot child and return text + refs, charging the parent budget.

        Raises :class:`QuerySnapshotError` with code ``prompt_too_large`` /
        ``invalid_unicode_scalar`` (bad question), ``too_many_images``,
        ``timed_out``, ``token_budget_exceeded``, or ``too_many_turns``.
        """
        try:
            enforce_max_utf8_bytes(question, _PROMPT_MAX_UTF8_BYTES, field="question")
        except LimitError as exc:
            raise QuerySnapshotError(exc.code, exc.message) from exc

        if len(image_refs) > QUERY_SNAPSHOT_MAX_IMAGES:
            raise QuerySnapshotError(
                "too_many_images",
                f"{len(image_refs)} image refs exceeds {QUERY_SNAPSHOT_MAX_IMAGES}",
            )

        bundle = self._preparer.prepare(child_run_id, question, image_refs)
        if len(bundle.image_refs) > QUERY_SNAPSHOT_MAX_IMAGES:
            raise QuerySnapshotError(
                "too_many_images",
                f"render bundle produced {len(bundle.image_refs)} images "
                f"(max {QUERY_SNAPSHOT_MAX_IMAGES})",
            )

        request = SnapshotRequest(
            run_id=child_run_id,
            question=question,
            image_refs=bundle.image_refs,
            max_output_tokens=QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS,
            max_turns=QUERY_SNAPSHOT_MAX_TURNS,
            timeout_s=QUERY_SNAPSHOT_TIMEOUT_S,
        )
        try:
            result = await asyncio.wait_for(
                self._caller.call(request), timeout=QUERY_SNAPSHOT_TIMEOUT_S
            )
        except TimeoutError as exc:
            raise QuerySnapshotError(
                "timed_out", f"query_snapshot exceeded {QUERY_SNAPSHOT_TIMEOUT_S}s"
            ) from exc

        # Re-enforce the bounds Python-side, regardless of what the child claims.
        if result.usage.output_tokens > QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS:
            raise QuerySnapshotError(
                "token_budget_exceeded",
                f"{result.usage.output_tokens} output tokens exceeds "
                f"{QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS}",
            )
        if result.usage.turns > QUERY_SNAPSHOT_MAX_TURNS:
            raise QuerySnapshotError(
                "too_many_turns",
                f"{result.usage.turns} turns exceeds {QUERY_SNAPSHOT_MAX_TURNS}",
            )

        # Charge the PARENT budget with the child's usage.
        self._ledger.charge(parent_run_id, result.usage)

        # Text and refs only — image blocks never propagate into the parent.
        return QuerySnapshotResult(text=result.text, refs=result.refs, usage=result.usage)
