"""Python limits tests, mirroring agent/test/limits.test.ts."""

from __future__ import annotations

import struct

import pytest
from hephaestus.agent_bridge.limits import (
    LIMITS,
    MAX_FRAME_BYTES,
    MAX_JSON_ARRAY_ITEMS,
    MAX_JSON_DEPTH,
    PROMPT_MAX_UTF8_BYTES,
    ImageError,
    LimitError,
    enforce_max_utf8_bytes,
    parse_image_header,
    validate_json_structure,
)


def test_limits_are_the_single_source_of_truth() -> None:
    assert MAX_FRAME_BYTES == 64 * 1024 * 1024
    assert PROMPT_MAX_UTF8_BYTES == 32768
    assert LIMITS["admission"]["run_slots"] == 16
    assert LIMITS["wire"]["frame_version"] == 1


def test_validate_json_structure_accepts_well_formed() -> None:
    validate_json_structure({"a": [1, 2, {"b": "c"}]})


def test_validate_json_structure_rejects_deep_nesting() -> None:
    node: object = 0
    for _ in range(MAX_JSON_DEPTH + 2):
        node = [node]
    with pytest.raises(LimitError) as exc:
        validate_json_structure(node)
    assert exc.value.code == "json_too_deep"


def test_validate_json_structure_rejects_long_array() -> None:
    with pytest.raises(LimitError) as exc:
        validate_json_structure([0] * (MAX_JSON_ARRAY_ITEMS + 1))
    assert exc.value.code == "json_array_too_long"


def test_enforce_max_utf8_bytes_measures_exact() -> None:
    assert enforce_max_utf8_bytes("café", 100) == 5  # é = 2 bytes
    assert enforce_max_utf8_bytes("☕", 100) == 3


def test_enforce_max_utf8_bytes_rejects_over_limit() -> None:
    with pytest.raises(LimitError) as exc:
        enforce_max_utf8_bytes("x" * 33, 32, field="prompt")
    assert exc.value.code == "prompt_too_large"


def test_enforce_rejects_unpaired_surrogate() -> None:
    lone = "a" + "\ud800" + "b"  # lone high surrogate; never coerced to U+FFFD
    with pytest.raises(LimitError) as exc:
        enforce_max_utf8_bytes(lone, PROMPT_MAX_UTF8_BYTES)
    assert exc.value.code == "invalid_unicode_scalar"


def test_enforce_accepts_astral_char() -> None:
    assert enforce_max_utf8_bytes("😀", 100) == 4


def _png_header(width: int, height: int) -> bytes:
    ihdr = b"IHDR" + struct.pack(">II", width, height)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr


def _jpeg_header(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">H", 2 + 1 + 2 + 2) + b"\x08"
    sof += struct.pack(">HH", height, width)
    return b"\xff\xd8" + sof


def test_parse_png_dimensions() -> None:
    dims = parse_image_header(_png_header(800, 600))
    assert (dims.width, dims.height, dims.kind) == (800, 600, "png")


def test_parse_jpeg_dimensions() -> None:
    dims = parse_image_header(_jpeg_header(1024, 768))
    assert (dims.width, dims.height, dims.kind) == (1024, 768, "jpeg")


def test_parse_image_rejects_dimension_bomb() -> None:
    with pytest.raises(ImageError) as exc:
        parse_image_header(_png_header(100000, 100000))
    assert exc.value.code == "image_too_large"


def test_parse_image_rejects_unsupported() -> None:
    with pytest.raises(ImageError) as exc:
        parse_image_header(b"GIF89a")
    assert exc.value.code == "unsupported_image"


def test_parse_image_rejects_oversized_bytes() -> None:
    oversize = b"\x89PNG\r\n\x1a\n" + b"\x00" * LIMITS["image"]["max_image_bytes"]
    with pytest.raises(ImageError) as exc:
        parse_image_header(oversize)
    assert exc.value.code == "image_too_large"
