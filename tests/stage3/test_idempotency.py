"""Gate G3, idempotency: the stock client sends nothing, the protocol carries it.

    The stock client sends no custom idempotency metadata; the server derives
    mutation keys from MCP session + request id, and a same-id replay returns
    the recorded result. […] optional MCP ``_meta`` is tested separately.

The official SDK allocates JSON-RPC ids internally, so these tests speak the
wire protocol directly (:class:`_stock_client.RawStdioClient`: newline-delimited
JSON-RPC on the server's stdin/stdout) — the only way to *choose* the id whose
behaviour the gate specifies. That client is even more stock than the SDK: it
declares no capabilities and knows nothing about Hephaestus.

Covered here:

* same id + same payload -> the **recorded** result, flagged as a replay;
* same id + different payload -> refused, before any mutation happens;
* different ids -> different operations (the id is the key, not the payload);
* the optional ``_meta["hephaestus.dev/idempotency-key"]``, including its
  UUIDv7 first-sight freshness window — tested separately, as the gate says.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from _stock_client import RawStdioClient, fixture_project, raw_structured

IDEMPOTENCY_META_KEY = "hephaestus.dev/idempotency-key"
REPLAYED_META_KEY = "hephaestus.dev/replayed"


@pytest.fixture
def client() -> Iterator[RawStdioClient]:
    raw = RawStdioClient()
    try:
        raw.initialize()
        yield raw
    finally:
        raw.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return fixture_project(tmp_path)


def open_project(client: RawStdioClient, root: Path, request_id: int = 2) -> None:
    result = client.call_tool("open_project", {"path": str(root)}, request_id)
    assert raw_structured(result)["status"] == "ok", result


def replayed(result: dict[str, object]) -> bool:
    meta = result.get("_meta") or {}
    return bool(dict(meta).get(REPLAYED_META_KEY)) if isinstance(meta, dict) else False


def uuid7(at: float) -> str:
    """A UUIDv7 whose embedded timestamp is ``at`` (stdlib has no v7 generator)."""
    raw = bytearray(int(at * 1000).to_bytes(6, "big") + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def test_idempotency_same_request_id_returns_the_recorded_result(
    client: RawStdioClient, project: Path
) -> None:
    """No client metadata at all: the JSON-RPC id *is* the mutation key."""
    open_project(client, project)

    first = client.call_tool("create_part", {"name": "keyed", "template": "blank"}, 100)
    created = raw_structured(first)
    assert created["content_hash"], created
    assert not replayed(first)

    replay = client.call_tool("create_part", {"name": "keyed", "template": "blank"}, 100)
    assert raw_structured(replay) == created, "a same-id replay must return the recorded result"
    assert replayed(replay), "the replay was not flagged as one"

    # A *different* id is a different operation — and this one legitimately
    # fails, proving the replay above was the ledger and not a no-op create.
    fresh = client.call_tool("create_part", {"name": "keyed", "template": "blank"}, 101)
    assert fresh.get("isError") is True, fresh
    assert not replayed(fresh)


def test_idempotency_same_request_id_with_a_different_payload_is_rejected(
    client: RawStdioClient, project: Path
) -> None:
    """Reusing an id under another payload is an error, not a silent replay."""
    open_project(client, project)

    first = client.call_tool("create_part", {"name": "alpha", "template": "blank"}, 200)
    assert raw_structured(first)["content_hash"]

    clash = client.call_tool("create_part", {"name": "beta", "template": "blank"}, 200)
    assert clash.get("isError") is True, clash
    assert raw_structured(clash)["reason"] == "idempotency_key_reuse"

    # The refused call mutated nothing: `beta` still does not exist, so creating
    # it under a fresh id succeeds.
    recovered = client.call_tool("create_part", {"name": "beta", "template": "blank"}, 201)
    assert raw_structured(recovered)["content_hash"]
    assert not (project / "parts" / "gamma.py").exists()


def test_idempotency_request_id_type_is_part_of_the_key(
    client: RawStdioClient, project: Path
) -> None:
    """``7`` and ``"7"`` are different JSON-RPC ids, hence different keys."""
    open_project(client, project)

    numeric = client.call_tool("create_part", {"name": "typed", "template": "blank"}, 300)
    assert raw_structured(numeric)["content_hash"]

    stringly = client.call_tool("create_part", {"name": "typed", "template": "blank"}, "300")
    assert not replayed(stringly), "a string id must not replay an int id's record"
    assert stringly.get("isError") is True, stringly


def test_idempotency_optional_meta_key_overrides_the_derived_key(
    client: RawStdioClient, project: Path
) -> None:
    """The optional ``_meta`` key: same key + different ids still replays."""
    open_project(client, project)
    key = uuid7(time.time())

    first = client.call_tool(
        "create_part",
        {"name": "meta_keyed", "template": "blank"},
        400,
        meta={IDEMPOTENCY_META_KEY: key},
    )
    created = raw_structured(first)
    assert created["content_hash"], created

    replay = client.call_tool(
        "create_part",
        {"name": "meta_keyed", "template": "blank"},
        401,
        meta={IDEMPOTENCY_META_KEY: key},
    )
    assert raw_structured(replay) == created
    assert replayed(replay)


def test_idempotency_stale_uuid7_meta_key_is_refused_on_first_sight(
    client: RawStdioClient, project: Path
) -> None:
    """A UUIDv7 key outside the freshness window never claims a new operation."""
    open_project(client, project)
    stale = client.call_tool(
        "create_part",
        {"name": "stale_keyed", "template": "blank"},
        500,
        meta={IDEMPOTENCY_META_KEY: uuid7(time.time() - 3600.0)},
    )
    assert stale.get("isError") is True, stale
    assert raw_structured(stale)["reason"] == "key_timestamp_skew"
    assert not (project / "parts" / "stale_keyed.py").exists()
