"""LF-delimited JSON-RPC 2.0 framing — Python mirror of ``agent/src/framing.ts``.

The two implementations share one wire contract so that a frame emitted by
either side is parsed identically by the other, and :func:`encode_frame` produces
**byte-for-byte identical output** to the TypeScript ``encodeFrame`` for the same
value (cross-language golden fixture). Byte parity relies on a canonical JSON
serialization: recursively sorted object keys, compact separators, and raw
(non-ASCII-escaped) UTF-8.

Framing rules (architecture §5):

* Frames are UTF-8 JSON objects terminated by a single ``\\n``; protocol stdout
  never carries anything else (logs go to stderr).
* The decoder is **incremental**: it aborts as soon as an in-progress frame
  exceeds :data:`MAX_FRAME_BYTES`, without buffering the whole oversized frame.
* :func:`encode_frame` refuses to emit an oversized frame (outbound guard).
"""

from __future__ import annotations

import json
from typing import Any

from .limits import MAX_FRAME_BYTES

__all__ = [
    "FrameDecoder",
    "FrameError",
    "FrameTooLargeError",
    "canonical_json",
    "encode_frame",
]

_NL = 0x0A


class FrameError(Exception):
    """A framing-layer violation. ``code`` is a stable machine token."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FrameTooLargeError(FrameError):
    """A single frame exceeded :data:`MAX_FRAME_BYTES` in either direction."""

    def __init__(self, observed_bytes: int, max_bytes: int) -> None:
        super().__init__(
            "frame_too_large",
            f"frame exceeds {max_bytes} bytes (observed at least {observed_bytes})",
        )
        self.observed_bytes = observed_bytes
        self.max_bytes = max_bytes


def canonical_json(value: Any) -> str:
    """Canonical, cross-language-stable JSON text.

    Sorted keys + compact separators + ``ensure_ascii=False`` match the
    TypeScript ``canonicalJson`` byte-for-byte for JSON values that avoid
    floating-point formatting differences (frames use only strings, integers,
    booleans, null, arrays, and objects).
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def encode_frame(frame: dict[str, Any]) -> bytes:
    """Serialize one frame to canonical JSON + ``\\n``; enforce the outbound cap."""
    payload = (canonical_json(frame) + "\n").encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameTooLargeError(len(payload), MAX_FRAME_BYTES)
    return payload


class FrameDecoder:
    """Incremental LF framer with a hard per-frame byte cap.

    Feed raw ``bytes`` via :meth:`push`; it returns the list of complete frame
    payloads (without the trailing newline) discovered so far, retaining any
    partial trailing line for the next call. Blank lines are skipped. As soon as
    an in-progress line exceeds the cap — even before its newline arrives — a
    :class:`FrameTooLargeError` is raised (fail closed); the caller tears the
    connection down rather than attempting to resynchronize.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def push(self, chunk: bytes) -> list[bytes]:
        frames: list[bytes] = []
        start = 0
        n = len(chunk)
        while start < n:
            nl = chunk.find(_NL, start)
            if nl == -1:
                self._buf += chunk[start:]
                if len(self._buf) > MAX_FRAME_BYTES:
                    raise FrameTooLargeError(len(self._buf), MAX_FRAME_BYTES)
                break
            self._buf += chunk[start:nl]
            if len(self._buf) > MAX_FRAME_BYTES:
                raise FrameTooLargeError(len(self._buf), MAX_FRAME_BYTES)
            line = bytes(self._buf)
            self._buf.clear()
            start = nl + 1
            if line.strip():
                frames.append(line)
        return frames

    @property
    def buffered(self) -> int:
        """Bytes of a partial (unterminated) frame currently held."""
        return len(self._buf)
