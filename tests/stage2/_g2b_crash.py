#!/usr/bin/env python3
"""Subprocess payload for the Gate G2 delegation crash-injection matrix.

Run as ``python _g2b_crash.py <store_root> <stage> <delivery>``. It admits a
parent run, delegates one child under the fixed trusted invocation
:data:`INVOCATION`, and dies at the requested ``stage`` of
``PREPARED → ADMITTED → DISPATCHED → TERMINAL → parent response``:

``before_enqueue``
    the ``PREPARED`` WAL row is committed and the process dies *before* any slot
    is reserved (``_reserve`` is replaced with an immediate ``_exit``);
``after_admission``
    the opstore crash hook fires inside ``admit`` / ``suspend``, i.e. once the
    child's slot is durably reserved but before the WAL row records ``ADMITTED``;
``after_dispatch``
    the child is CAS'd ``ADMITTED → DISPATCHED`` and then the process dies;
``after_child_terminal``
    the crash hook fires after the terminal + delegation-row transaction commits;
``before_parent_response``
    (``prompt`` delivery only) the child terminal is durable and acknowledged and
    the process dies before the parent is resumed.

The opstore crash point is passed in ``G2B_CRASH_POINT`` and only copied into
``OPSTORE_CRASH_POINT`` **after** the parent run is admitted, so an
``admission.after_admit`` injection lands on the child rather than the parent.

Exits with :data:`opstore.types.CRASH_EXIT_CODE` in every armed stage; prints
``NO_CRASH`` and exits 0 if it ever runs to completion, so a test can never pass
because the injection silently did nothing.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.delegation import (
    DelegationOutcome,
    DelegationService,
    Delivery,
    Rejected,
)
from opstore.types import CRASH_EXIT_CODE, EnvCrashHook, OwnerId, TerminalState, current_owner

from opstore import OpStore

#: The fixed trusted invocation every stage delegates under.
INVOCATION = "g2b-crash-inv"
PARENT_RUN = "orch"
PART = "widget"
PROMPT = "build the widget"
ARTIFACT = "artifact:build:sha256:" + "d" * 64

STAGES = (
    "before_enqueue",
    "after_admission",
    "after_dispatch",
    "after_child_terminal",
    "before_parent_response",
)


def expected_ref(prefix: str) -> str:
    """The delegation ref / child run id the invocation deterministically yields."""
    return prefix + hashlib.sha256(INVOCATION.encode("utf-8")).hexdigest()[:24]


class _ExitBeforeReserve(DelegationService):
    """A service that dies after committing ``PREPARED``, before reserving."""

    def _reserve(self, delegation_ref: str, child_owner: OwnerId | None) -> DelegationOutcome:
        sys.stdout.flush()
        os._exit(CRASH_EXIT_CODE)


def main() -> None:
    root = Path(sys.argv[1])
    stage = sys.argv[2]
    delivery = Delivery(sys.argv[3])
    if stage not in STAGES:
        raise SystemExit(f"unknown stage {stage!r}")

    store = OpStore.create(root, bridge_store_config(), crash_hook=EnvCrashHook())
    me = current_owner()
    try:
        store.admission.admit(PARENT_RUN, owner=me)
        # Arm the store crash hook only now: the parent admission must survive.
        point = os.environ.get("G2B_CRASH_POINT")
        if point:
            os.environ["OPSTORE_CRASH_POINT"] = point
        factory = _ExitBeforeReserve if stage == "before_enqueue" else DelegationService
        service = factory(store.admission, store.db)
        outcome = service.delegate(
            PARENT_RUN,
            PART,
            PROMPT,
            delivery=delivery,
            invocation=INVOCATION,
            child_owner=me,
        )
        if isinstance(outcome, Rejected):
            raise SystemExit(f"unexpected rejection: {outcome.reason}")
        ref = outcome.delegation_ref

        service.dispatch(ref)
        if stage == "after_dispatch":
            sys.stdout.flush()
            os._exit(CRASH_EXIT_CODE)

        service.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref=ARTIFACT)
        if stage == "before_parent_response":
            service.acknowledge(ref)
            sys.stdout.flush()
            os._exit(CRASH_EXIT_CODE)
    finally:
        store.close()
    print("NO_CRASH")


if __name__ == "__main__":
    main()
