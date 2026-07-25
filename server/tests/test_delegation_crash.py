"""Crash-injection: a kill at terminal insertion leaves exactly one child + terminal."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.delegation import DelegationPhase, DelegationService
from opstore.types import CRASH_EXIT_CODE, TerminalState

from opstore import OpStore

_HELPER = Path(__file__).with_name("_crash_delegation.py")
_INVOCATION = "inv-crash"


def _ref(prefix: str) -> str:
    return prefix + hashlib.sha256(_INVOCATION.encode("utf-8")).hexdigest()[:24]


def test_crash_after_terminal_insert_one_terminal(tmp_path: Path) -> None:
    root = tmp_path / "heph"
    env = dict(os.environ)
    env["OPSTORE_CRASH_POINT"] = "admission.after_terminal_insert"
    proc = subprocess.run(
        [sys.executable, str(_HELPER), str(root)],
        env=env,
        capture_output=True,
        text=True,
    )
    # The owner process died at the armed crash point, not cleanly.
    assert proc.returncode == CRASH_EXIT_CODE, proc.stderr
    assert "NO_CRASH" not in proc.stdout

    # Reopen the store from the survivor: exactly one child, exactly one terminal.
    delegation_ref = _ref("dg-")
    child_run_id = _ref("cr-")
    store = OpStore.open(root, bridge_store_config())
    try:
        svc = DelegationService(store.admission, store.db)
        row = svc.get(delegation_ref)
        assert row.phase is DelegationPhase.TERMINAL
        assert row.terminal_state is TerminalState.COMPLETED
        assert row.result_artifact_ref == "art-crash"

        terminal = store.admission.get_terminal(child_run_id)
        assert terminal is not None
        assert terminal.state is TerminalState.COMPLETED

        # Re-ingesting the same terminal is idempotent — no second terminal.
        again = svc.ingest_terminal(
            delegation_ref, TerminalState.COMPLETED, result_artifact_ref="art-crash"
        )
        assert again.terminal_state is TerminalState.COMPLETED

        # Recovery synthesizes nothing new (the existing terminal wins).
        recovered = svc.recover(delegation_ref)
        assert recovered.terminal_state is TerminalState.COMPLETED
        assert store.admission.get(child_run_id).state is not None
    finally:
        store.close()
