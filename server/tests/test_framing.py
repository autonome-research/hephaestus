"""Python framing tests, mirroring agent/test/framing.test.ts."""

from __future__ import annotations

import json

import pytest
from hephaestus.agent_bridge.framing import (
    FrameDecoder,
    FrameTooLargeError,
    canonical_json,
    encode_frame,
)
from hephaestus.agent_bridge.limits import MAX_FRAME_BYTES


def test_canonical_json_sorts_keys_and_is_compact() -> None:
    assert canonical_json({"z": 1, "a": 2, "m": {"y": 1, "x": 2}}) == (
        '{"a":2,"m":{"x":2,"y":1},"z":1}'
    )


def test_canonical_json_keeps_raw_unicode() -> None:
    assert canonical_json({"t": "café ☕"}) == '{"t":"café ☕"}'


def test_encode_frame_appends_single_newline() -> None:
    payload = encode_frame({"hv": 1, "jsonrpc": "2.0", "id": 1})
    assert payload[-1:] == b"\n"
    assert payload[:-1] == b'{"hv":1,"id":1,"jsonrpc":"2.0"}'


def test_encode_frame_outbound_guard() -> None:
    with pytest.raises(FrameTooLargeError):
        encode_frame({"big": "x" * MAX_FRAME_BYTES})


def test_decoder_splits_multiple_frames() -> None:
    dec = FrameDecoder()
    frames = dec.push(b'{"a":1}\n{"b":2}\n')
    assert [json.loads(f) for f in frames] == [{"a": 1}, {"b": 2}]


def test_decoder_reassembles_across_chunks() -> None:
    dec = FrameDecoder()
    assert dec.push(b'{"a":') == []
    assert dec.push(b"1}") == []
    frames = dec.push(b"\n")
    assert [json.loads(f) for f in frames] == [{"a": 1}]


def test_decoder_skips_blank_lines() -> None:
    dec = FrameDecoder()
    frames = dec.push(b'\n\n{"a":1}\n\n')
    assert [json.loads(f) for f in frames] == [{"a": 1}]


def test_decoder_incremental_abort_before_newline() -> None:
    dec = FrameDecoder()
    # A full-cap chunk with no newline is accepted (buffered == cap)...
    assert dec.push(b"a" * MAX_FRAME_BYTES) == []
    assert dec.buffered == MAX_FRAME_BYTES
    # ...one more byte, still no newline, fails closed incrementally.
    with pytest.raises(FrameTooLargeError):
        dec.push(b"a")


def test_decoder_aborts_single_oversized_chunk() -> None:
    dec = FrameDecoder()
    with pytest.raises(FrameTooLargeError):
        dec.push(b"a" * (MAX_FRAME_BYTES + 1))
