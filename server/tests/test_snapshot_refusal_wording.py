"""Missing image transport is authoritative; omitted catalog metadata is not."""

from typing import cast
from unittest.mock import Mock

import pytest
from hephaestus.agent_bridge.app import _BridgeSnapshotCaller  # pyright: ignore[reportPrivateUsage]
from hephaestus.agent_bridge.supervisor import Supervisor


def test_native_sol_snapshot_refusal_does_not_infer_catalog_absence() -> None:
    supervisor = Mock(spec=Supervisor)
    caller = _BridgeSnapshotCaller(
        cast(Supervisor, supervisor),
        [{"id": "openai-codex", "kind": "pi_native", "models": [{"id": "gpt-5.6-sol"}]}],
    )
    reason = caller.unavailable()
    assert reason is not None
    assert "no multimodal model is configured" not in reason
    assert "delivers none of the prepared renders" in reason
    supervisor.call.assert_not_called()


@pytest.mark.parametrize("inputs", [[], ["text"], ["text", "image"]])
def test_snapshot_always_refuses_unwired_image_delivery(inputs: list[str]) -> None:
    supervisor = Mock(spec=Supervisor)
    caller = _BridgeSnapshotCaller(
        cast(Supervisor, supervisor),
        [{"id": "fixture", "models": [{"id": "fixture-model", "input": inputs}]}],
    )
    reason = caller.unavailable()
    assert reason is not None
    assert "delivers none of the prepared renders" in reason
    supervisor.call.assert_not_called()
