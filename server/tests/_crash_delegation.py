"""Subprocess payload for the delegation terminal crash-injection test.

Run as ``python _crash_delegation.py <store_root>`` with ``OPSTORE_CRASH_POINT``
set to ``admission.after_terminal_insert``. It admits a parent, delegates a
follow-up child, dispatches it, and ingests the COMPLETED terminal. The opstore
crash hook fires *after* the terminal+delegation-row transaction commits, so the
process exits 42 with exactly one durable terminal already persisted. If the
crash point is not armed it prints ``NO_CRASH`` and exits 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.delegation import DelegationService, Delivery, Rejected
from opstore.types import EnvCrashHook, SystemClock, TerminalState

from opstore import OpStore

INVOCATION = "inv-crash"


def main() -> None:
    root = Path(sys.argv[1])
    store = OpStore.create(root, bridge_store_config(), crash_hook=EnvCrashHook())
    try:
        store.admission.admit("orch")
        svc = DelegationService(store.admission, store.db, clock=SystemClock())
        out = svc.delegate(
            "orch", "partA", "build", delivery=Delivery.FOLLOW_UP, invocation=INVOCATION
        )
        assert not isinstance(out, Rejected)
        ref = out.delegation_ref
        svc.dispatch(ref)
        # Crash hook fires after this transaction commits (if armed).
        svc.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref="art-crash")
    finally:
        store.close()
    print("NO_CRASH")


if __name__ == "__main__":
    main()
