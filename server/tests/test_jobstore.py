"""JobStore tests: KV CRUD, checkpoint round-trip, restart survival, bridge dispatch."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeClock
from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.jobstore import JobStore

from opstore import OpStore


def test_put_get_delete_roundtrip(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)
    assert js.get("jobs", "j1") is None
    js.put("jobs", "j1", {"status": "RUNNING", "n": 1})
    assert js.get("jobs", "j1") == {"status": "RUNNING", "n": 1}
    # Upsert is idempotent on (namespace, key).
    js.put("jobs", "j1", {"status": "COMPLETED", "n": 2})
    assert js.get("jobs", "j1") == {"status": "COMPLETED", "n": 2}
    assert js.delete("jobs", "j1") is True
    assert js.delete("jobs", "j1") is False
    assert js.get("jobs", "j1") is None


def test_list_prefix_and_order(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)
    js.put("events", "job1:e1", {"i": 1})
    js.put("events", "job1:e2", {"i": 2})
    js.put("events", "job2:e1", {"i": 3})
    all_events = js.list("events")
    assert [r.key for r in all_events] == ["job1:e1", "job1:e2", "job2:e1"]  # insertion order
    job1 = js.list("events", prefix="job1:")
    assert [r.key for r in job1] == ["job1:e1", "job1:e2"]
    assert [r.value for r in job1] == [{"i": 1}, {"i": 2}]
    assert len(js.list("events", limit=2)) == 2


def test_list_prefix_escapes_like_wildcards(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)
    js.put("ns", "a%b", {"x": 1})
    js.put("ns", "axb", {"x": 2})
    # '%' must be treated literally, not as a wildcard.
    hits = js.list("ns", prefix="a%")
    assert [r.key for r in hits] == ["a%b"]


def test_checkpoint_roundtrip_with_provenance(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)
    rec = js.checkpoint(
        "job-7",
        "phase-decompose",
        workflow_version="cad@3",
        input_hash="in-abc",
        output_hash="out-def",
        value={"parts": ["a", "b"]},
    )
    assert rec.workflow_version == "cad@3"
    got = js.get_checkpoint("job-7", "phase-decompose")
    assert got is not None
    assert got.input_hash == "in-abc"
    assert got.output_hash == "out-def"
    assert got.value == {"parts": ["a", "b"]}


def test_checkpoint_upsert_idempotent(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)
    js.checkpoint("j", "k", workflow_version="v1", input_hash="i1", output_hash="o1", value=1)
    js.checkpoint("j", "k", workflow_version="v2", input_hash="i2", output_hash="o2", value=2)
    got = js.get_checkpoint("j", "k")
    assert got is not None and got.workflow_version == "v2" and got.value == 2
    assert len(js.list_checkpoints("j")) == 1


def test_survives_restart(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)
    js.put("jobs", "j1", {"status": "RUNNING"})
    js.checkpoint(
        "j1", "cp1", workflow_version="v", input_hash="i", output_hash="o", value={"s": 5}
    )
    root = store.root
    store.close()
    reopened = OpStore.open(root, bridge_store_config())
    try:
        js2 = JobStore(reopened.db, clock=clock)
        assert js2.get("jobs", "j1") == {"status": "RUNNING"}
        cp = js2.get_checkpoint("j1", "cp1")
        assert cp is not None and cp.value == {"s": 5}
    finally:
        reopened.close()


def test_bridge_dispatch_methods(store: OpStore, clock: FakeClock) -> None:
    js = JobStore(store.db, clock=clock)

    async def scenario() -> None:
        assert await js.dispatch(
            "py.jobstore_put", {"namespace": "jobs", "key": "j", "value": {"n": 1}}
        )
        got = await js.dispatch("py.jobstore_get", {"namespace": "jobs", "key": "j"})
        assert got == {"value": {"n": 1}}
        listed = await js.dispatch("py.jobstore_list", {"namespace": "jobs"})
        assert listed == {"items": [{"key": "j", "value": {"n": 1}}]}
        cp = await js.dispatch(
            "py.jobstore_checkpoint",
            {
                "job_id": "j",
                "checkpoint_key": "k",
                "workflow_version": "v",
                "input_hash": "i",
                "output_hash": "o",
                "value": {"done": True},
            },
        )
        assert cp["ok"] is True
        deleted = await js.dispatch("py.jobstore_delete", {"namespace": "jobs", "key": "j"})
        assert deleted == {"deleted": True}

    asyncio.run(scenario())


def test_bridge_dispatch_unknown_method(store: OpStore, clock: FakeClock) -> None:
    from opstore.errors import NotFoundError

    js = JobStore(store.db, clock=clock)
    with pytest.raises(NotFoundError):
        asyncio.run(js.dispatch("py.jobstore_bogus", {}))
