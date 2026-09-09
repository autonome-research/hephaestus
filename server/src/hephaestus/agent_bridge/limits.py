"""Bridge limits: the single source of truth loaded from ``schemas/bridge_limits.json``.

Every architecture §5 numeric limit lives in that JSON file; this module loads it
verbatim and exposes typed accessors plus the bounded validators the bridge runs
*before* trusting a payload:

* :func:`validate_json_structure` — depth / members / array / string budgets applied
  to an already-parsed value (defence against pathological but well-formed JSON).
* :func:`enforce_max_utf8_bytes` — exact UTF-8 sizing with unpaired-surrogate
  rejection (``invalid_unicode_scalar``), used for ``x-hephaestus-maxUtf8Bytes``.
* :func:`parse_image_header` — a bounded PNG/JPEG header parser that recovers the
  declared dimensions *before* any full decode, rejecting decompression bombs.

No limit literal is duplicated here — read them off :data:`LIMITS`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.limits import limits_path as core_limits_path

__all__ = [
    "LIMITS",
    "TURN_SECONDS",
    "ImageDims",
    "ImageError",
    "LimitError",
    "enforce_binary_budget",
    "enforce_max_utf8_bytes",
    "limits_path",
    "parse_image_header",
    "validate_json_structure",
]


def limits_path() -> Path:
    """Absolute path to the loaded limits file (for provenance/logging).

    Delegates to :func:`hephaestus.core.limits.limits_path`. This module used to
    carry its own copy of the walk-up search, which meant two resolvers for one
    file — and both were wrong in an installed wheel, where the walk climbs out
    of ``site-packages`` and finds nothing. ``hephaestus-server`` already depends
    on ``hephaestus-core``, so the core resolver (which knows about the packaged
    copy the wheel ships) is the one that should answer for both.
    """
    return core_limits_path()


def _load() -> dict[str, Any]:
    with limits_path().open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


LIMITS: Final[dict[str, Any]] = _load()

# Convenience typed views over the loaded document (no literal duplication).
_WIRE: Final[dict[str, Any]] = LIMITS["wire"]
_JSON: Final[dict[str, Any]] = LIMITS["json"]
_IMAGE: Final[dict[str, Any]] = LIMITS["image"]
_BINARY: Final[dict[str, Any]] = LIMITS["binary"]
_HTTP: Final[dict[str, Any]] = LIMITS["http"]

FRAME_VERSION: Final[int] = int(_WIRE["frame_version"])
MAX_FRAME_BYTES: Final[int] = int(_WIRE["max_frame_bytes"])

#: The ceiling on ONE HTTP request body, enforced by ``hephaestus.http.app``
#: from ``Content-Length`` and again while the body streams (``INTERFACE.md``
#: §2.4, audit-2026-09-04 J-http-limits-1). Exported beside the frame cap and
#: deliberately far below it: the frame cap bounds what the *bridge transport*
#: can carry between two trusted processes, while this bounds what an untrusted
#: client can make the serving process allocate. The largest legitimate body on
#: the HTTP surface is a part script; a prompt is capped an order of magnitude
#: smaller again (:data:`PROMPT_MAX_UTF8_BYTES`), so a megabyte leaves every
#: real body room and still refuses the 64 MiB one that used to be buffered
#: whole before anything looked at it.
MAX_REQUEST_BYTES: Final[int] = int(_HTTP["max_request_bytes"])
MAX_JSON_DEPTH: Final[int] = int(_JSON["max_depth"])
MAX_JSON_MEMBERS: Final[int] = int(_JSON["max_members"])
MAX_JSON_ARRAY_ITEMS: Final[int] = int(_JSON["max_array_items"])
MAX_STRING_BYTES: Final[int] = int(_JSON["max_string_bytes"])
MAX_BINARY_BYTES: Final[int] = int(_BINARY["max_binary_bytes"])

#: One model TURN's budget, in seconds — the bound on a ``session.prompt`` call.
#:
#: A turn is not a tool. ``timeouts.tool_seconds`` bounds ONE tool call, and a
#: turn runs a model round trip plus however many tools the model asks for, one
#: of which may be a build the sidecar itself allows ``cad_build_seconds``
#: (300 s). Defaulting the turn call to the tool bound therefore placed a
#: 120 s ceiling around a thing that legitimately takes longer, and the
#: watchdog's remedy for an overdue call is to kill the whole sidecar — every
#: session in the process — over latency that was never a fault. Set to the
#: delegated child's own default (``delegation.deadline_default_seconds``)
#: because a delegated child turn IS a turn: the two must not disagree about
#: how long one is allowed to take.
TURN_SECONDS: Final[float] = float(LIMITS["timeouts"]["turn_seconds"])
MAX_IMAGE_BYTES: Final[int] = int(_IMAGE["max_image_bytes"])
MAX_IMAGE_WIDTH: Final[int] = int(_IMAGE["max_width"])
MAX_IMAGE_HEIGHT: Final[int] = int(_IMAGE["max_height"])
MAX_TOTAL_PIXELS: Final[int] = int(_IMAGE["max_total_pixels"])
MAX_IMAGES_PER_RESULT: Final[int] = int(_IMAGE["max_images_per_result"])
MAX_PENDING_RPC: Final[int] = int(LIMITS["rpc"]["max_pending"])
PROMPT_MAX_UTF8_BYTES: Final[int] = int(LIMITS["prompt"]["max_utf8_bytes"])


class LimitError(ValueError):
    """A payload exceeded a structural or size limit. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImageError(LimitError):
    """An image header was malformed or its dimensions exceeded the budget."""


@dataclass(frozen=True)
class ImageDims:
    """Dimensions recovered from an image header before any full decode."""

    width: int
    height: int
    kind: str  # "png" | "jpeg"

    @property
    def pixels(self) -> int:
        return self.width * self.height


def validate_json_structure(value: object) -> None:
    """Reject well-formed-but-pathological JSON against the §5 structural caps.

    Applies, over the whole parsed value: nesting ``depth <= MAX_JSON_DEPTH``,
    per-object ``members <= MAX_JSON_MEMBERS``, per-array ``items <=
    MAX_JSON_ARRAY_ITEMS``, and per-string ``utf-8 bytes <= MAX_STRING_BYTES``.
    Raises :class:`LimitError` on the first violation.
    """

    # Iterative walk to avoid Python recursion limits on adversarial nesting.
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise LimitError("json_too_deep", f"nesting exceeds depth {MAX_JSON_DEPTH}")
        if isinstance(node, dict):
            node_dict = cast("dict[str, object]", node)
            if len(node_dict) > MAX_JSON_MEMBERS:
                raise LimitError(
                    "json_too_many_members",
                    f"object has {len(node_dict)} members (max {MAX_JSON_MEMBERS})",
                )
            for key, child in node_dict.items():
                _check_string(key)
                stack.append((child, depth + 1))
        elif isinstance(node, list):
            node_list = cast("list[object]", node)
            if len(node_list) > MAX_JSON_ARRAY_ITEMS:
                raise LimitError(
                    "json_array_too_long",
                    f"array has {len(node_list)} items (max {MAX_JSON_ARRAY_ITEMS})",
                )
            for child in node_list:
                stack.append((child, depth + 1))
        elif isinstance(node, str):
            _check_string(node)


def _check_string(s: str) -> None:
    # A surrogate-bearing string cannot be encoded as UTF-8; reject it as a
    # structural violation rather than letting encode() raise opaquely later.
    n = _utf8_len_strict(s)
    if n > MAX_STRING_BYTES:
        raise LimitError(
            "json_string_too_large",
            f"string is {n} bytes (max {MAX_STRING_BYTES})",
        )


def _utf8_len_strict(s: str) -> int:
    """UTF-8 byte length, rejecting any unpaired UTF-16 surrogate scalar.

    JSON permits ``\\uD800`` escapes that decode to lone surrogates in Python;
    the bridge treats those as ``invalid_unicode_scalar`` before sizing or
    hashing, matching the TypeScript/MCP rule (no replacement-character coercion).
    """
    for ch in s:
        o = ord(ch)
        if 0xD800 <= o <= 0xDFFF:
            raise LimitError(
                "invalid_unicode_scalar",
                f"unpaired UTF-16 surrogate U+{o:04X} is not a valid scalar",
            )
    return len(s.encode("utf-8"))


def enforce_binary_budget(total_bytes: int, *, field: str = "result") -> None:
    """Enforce the AGGREGATE binary budget of one tool result (J-http-limits-9).

    ``binary.max_binary_bytes`` was exported on both sides of the bridge and
    validated by nothing — a grep over the whole tree returned this export, the
    TypeScript export, and the test that pinned it as dead. It has exactly one
    defensible subject here: the only binary payloads that cross this bridge are
    the base64 image blocks of a tool result, and ``max_image_bytes`` (8 MiB)
    times ``max_images_per_result`` (4) is precisely this cap, so the intended
    meaning is the per-result *aggregate*. Nothing summed them, so a result with
    four maximal images passed four per-image checks and no aggregate one.

    The mirror is ``agent/src/limits.ts``'s ``enforceBinaryBudget``, called from
    the sidecar's image loop; this side is enforced where a result's image
    blocks are assembled, because a limit enforced on one side of this bridge is
    not enforced.
    """
    if total_bytes > MAX_BINARY_BYTES:
        raise LimitError(
            "binary_too_large",
            f"{field} carries {total_bytes} binary bytes (max {MAX_BINARY_BYTES})",
        )


def enforce_max_utf8_bytes(value: str, max_bytes: int, *, field: str = "value") -> int:
    """Enforce ``x-hephaestus-maxUtf8Bytes``; return the exact UTF-8 byte length.

    Rejects unpaired surrogates first (``invalid_unicode_scalar``), then sizes
    the exact UTF-8 encoding. Never truncates. Raises :class:`LimitError` with
    code ``prompt_too_large`` when ``max_bytes`` is exceeded.
    """
    n = _utf8_len_strict(value)
    if n > max_bytes:
        raise LimitError(
            "prompt_too_large",
            f"{field} is {n} UTF-8 bytes (max {max_bytes})",
        )
    return n


def parse_image_header(data: bytes) -> ImageDims:
    """Recover image dimensions from a PNG or JPEG header without full decode.

    Enforces the per-image byte budget, then reads only the header fields needed
    for width/height and checks them against the dimension and total-pixel
    budgets. Raises :class:`ImageError` on malformed data or a bomb; the full
    decoder still enforces its own allocation cap downstream.
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            "image_too_large",
            f"image is {len(data)} bytes (max {MAX_IMAGE_BYTES})",
        )
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        dims = _parse_png(data)
    elif data[:2] == b"\xff\xd8":
        dims = _parse_jpeg(data)
    else:
        raise ImageError("unsupported_image", "not a PNG or JPEG header")
    _check_dims(dims)
    return dims


def _check_dims(dims: ImageDims) -> None:
    if dims.width <= 0 or dims.height <= 0:
        raise ImageError("image_bad_dimensions", "non-positive image dimension")
    if dims.width > MAX_IMAGE_WIDTH or dims.height > MAX_IMAGE_HEIGHT:
        raise ImageError(
            "image_too_large",
            f"{dims.width}x{dims.height} exceeds {MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT}",
        )
    if dims.pixels > MAX_TOTAL_PIXELS:
        raise ImageError(
            "image_too_large",
            f"{dims.pixels} pixels exceeds total budget {MAX_TOTAL_PIXELS}",
        )


def _parse_png(data: bytes) -> ImageDims:
    # Signature (8) + IHDR length (4) + "IHDR" (4) + width (4 BE) + height (4 BE).
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise ImageError("image_malformed", "PNG missing IHDR chunk")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return ImageDims(width=width, height=height, kind="png")


# JPEG start-of-frame markers that carry dimensions (exclude DHT/JPG/DAC/RST/…).
_JPEG_SOF = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _parse_jpeg(data: bytes) -> ImageDims:
    # Walk marker segments from just after SOI (FF D8) until an SOF marker.
    i = 2
    n = len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            # Skip fill bytes / stray data until the next marker prefix.
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            # SOI/EOI/RSTn carry no length payload.
            continue
        if i + 2 > n:
            break
        seg_len = int.from_bytes(data[i : i + 2], "big")
        if seg_len < 2:
            raise ImageError("image_malformed", "JPEG segment length underflow")
        if marker in _JPEG_SOF:
            # length(2) + precision(1) + height(2) + width(2)
            if i + 7 > n:
                raise ImageError("image_malformed", "JPEG SOF truncated")
            height = int.from_bytes(data[i + 3 : i + 5], "big")
            width = int.from_bytes(data[i + 5 : i + 7], "big")
            return ImageDims(width=width, height=height, kind="jpeg")
        i += seg_len
    raise ImageError("image_malformed", "no JPEG SOF marker found")
