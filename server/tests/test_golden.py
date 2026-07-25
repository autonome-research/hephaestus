"""Cross-language golden: the Python half of the byte-for-byte framing parity.

The same fixture is asserted by agent/test/golden.test.ts. Both sides must emit
and parse the committed wire bytes identically; this proves framing.py and
framing.ts agree on the exact bytes on the wire.
"""

from __future__ import annotations

import json
from pathlib import Path

from hephaestus.agent_bridge.framing import FrameDecoder, encode_frame


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "schemas" / "bridge_limits.json").is_file():
            return parent
    raise FileNotFoundError("repo root not found")


_FIXTURES = _repo_root() / "agent" / "test" / "fixtures"
_VALUES = json.loads((_FIXTURES / "golden_frames.json").read_text(encoding="utf-8"))
_WIRE = (_FIXTURES / "golden_frames.wire").read_bytes()


def test_encode_reproduces_committed_wire_bytes() -> None:
    emitted = b"".join(encode_frame(v) for v in _VALUES)
    assert emitted == _WIRE


def test_decode_committed_wire_bytes_to_values() -> None:
    dec = FrameDecoder()
    frames = dec.push(_WIRE)
    assert len(frames) == len(_VALUES)
    assert [json.loads(f) for f in frames] == _VALUES


def test_decode_survives_arbitrary_chunk_boundaries() -> None:
    dec = FrameDecoder()
    out: list[bytes] = []
    for i in range(0, len(_WIRE), 7):
        out.extend(dec.push(_WIRE[i : i + 7]))
    assert [json.loads(f) for f in out] == _VALUES
