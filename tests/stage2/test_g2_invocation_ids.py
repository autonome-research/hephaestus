"""G2: trusted invocation ids stay unique when the provider reuses ``call_0``.

Gate clause: *"An event fixture repeats provider ID ``call_0`` across distinct
persisted assistant entries and proves trusted invocation IDs remain unique."*

The idempotency key is derived from four trusted facts — session UUID, persisted
assistant-entry id, tool-call ordinal, provider tool-call id — and lives only in
bridge metadata, never in model-visible arguments. This module proves the
property where it matters: through the **real** sidecar, with a provider that
emits the same ``call_0`` id in every assistant entry.

* Distinct entries with the same provider id produce distinct keys, and therefore
  distinct *effects*: the second ``create_part`` is refused as ``already_exists``
  instead of silently replaying the first one's recorded outcome.
* A key repeated deliberately (the lost-response retry the sidecar would send
  after a dropped reply) replays the recorded outcome with no second write.
* No key material ever appears in the arguments the model produced.
"""

from __future__ import annotations

from typing import Any, cast

from _g2 import G2Harness, Project, RequestInfo, text, tool_call
from hephaestus.agent_bridge.dispatch import Invocation


def test_repeated_provider_call_id_yields_unique_trusted_ids(harness: G2Harness) -> None:
    bodies: list[str] = []

    def step(name: str) -> Any:
        def turn(info: RequestInfo) -> dict[str, Any]:
            bodies.append(info.body_text)
            # Every entry deliberately reuses the SAME provider tool-call id.
            return tool_call("create_part", {"name": name, "template": "blank"}, "call_0")

        return turn

    harness.set_script(
        [
            step("alpha"),
            step("beta"),
            # Third entry: re-create 'alpha'. A distinct trusted key means this is
            # a genuine second attempt, so it must be refused, not replayed.
            step("alpha"),
            lambda info: (bodies.append(info.body_text), text("done"))[1],
        ]
    )
    session_id = harness.create_session("orchestrator", session_id="g2-invocation")
    result = harness.prompt(session_id, "create parts", timeout=600)
    assert result.status == "completed"

    records = harness.recorder.by_tool("create_part")
    assert len(records) == 3, harness.recorder.tools()

    # Every attempt really did carry provider id "call_0"…
    assert {record.invocation["provider_call_id"] for record in records} == {"call_0"}
    # …and every derived trusted key is still unique.
    keys = [record.invocation_id for record in records]
    assert len(set(keys)) == 3, keys
    assert len({record.invocation["entry_id"] for record in records}) == 3

    # The uniqueness is load-bearing: attempt 3 is a fresh key, so the store
    # refuses it instead of replaying attempt 1's committed outcome.
    assert records[2].ok is False
    assert records[2].reason == "already_exists", records[2].error
    assert (harness.project_root / "parts" / "alpha.py").exists()
    assert (harness.project_root / "parts" / "beta.py").exists()

    # No trusted key material leaked into model-visible arguments.
    for record in records:
        assert set(record.arguments) <= {"name", "template", "description"}
    for body in bodies:
        assert "invocation_id" not in body
        assert "entry_id" not in body


def test_new_run_in_the_same_session_reuses_call_0_without_colliding(
    harness: G2Harness,
) -> None:
    """A second prompt reusing ``call_0`` still derives a distinct trusted key."""
    session_id = harness.create_session("orchestrator", session_id="g2-invocation-runs")

    harness.set_script([tool_call("create_part", {"name": "first"}, "call_0"), text("ok")])
    first = harness.prompt(session_id, "create the first part", timeout=600)
    assert first.status == "completed"

    harness.set_script([tool_call("create_part", {"name": "second"}, "call_0"), text("ok")])
    second = harness.prompt(session_id, "create the second part", timeout=600)
    assert second.status == "completed"

    records = harness.recorder.by_tool("create_part")
    assert len(records) == 2
    assert {record.invocation["provider_call_id"] for record in records} == {"call_0"}
    assert records[0].invocation_id != records[1].invocation_id
    assert records[0].run_id != records[1].run_id
    assert (harness.project_root / "parts" / "first.py").exists()
    assert (harness.project_root / "parts" / "second.py").exists()


def test_same_trusted_key_replays_the_recorded_outcome(project: Project) -> None:
    """The retry path: an identical key replays, and writes nothing twice."""
    first = cast(
        "dict[str, Any]",
        project.call("create_part", {"name": "gadget"}, entry="entry-fixed"),
    )
    assert first["replayed"] is False
    path = project.root / "parts" / "gadget.py"
    stamp = path.stat().st_mtime_ns

    second = cast(
        "dict[str, Any]",
        project.call("create_part", {"name": "gadget"}, entry="entry-fixed"),
    )
    assert second["replayed"] is True
    assert second["content_hash"] == first["content_hash"]
    assert path.stat().st_mtime_ns == stamp, "a replay must not rewrite the file"


def test_invocation_key_is_injective_over_its_four_facts() -> None:
    """Distinct (session, entry, ordinal, provider id) tuples never collide."""
    base = Invocation(session_id="s", entry_id="e", ordinal=0, provider_call_id="call_0")
    variants = [
        base,
        Invocation(session_id="s2", entry_id="e", ordinal=0, provider_call_id="call_0"),
        Invocation(session_id="s", entry_id="e2", ordinal=0, provider_call_id="call_0"),
        Invocation(session_id="s", entry_id="e", ordinal=1, provider_call_id="call_0"),
        Invocation(session_id="s", entry_id="e", ordinal=0, provider_call_id="call_1"),
    ]
    keys = [variant.op_id for variant in variants]
    assert len(set(keys)) == len(keys)
    # Stable for the same tuple (a retry reconciles onto the same opkey).
    assert (
        base.op_id
        == Invocation(session_id="s", entry_id="e", ordinal=0, provider_call_id="call_0").op_id
    )
