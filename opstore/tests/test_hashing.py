"""Tests for opstore.hashing: format, known vectors, canonical JSON properties."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from opstore.hashing import (
    HASH_PREFIX,
    canonical_json,
    hex_of,
    is_hash,
    sha256_bytes,
    sha256_canonical_json,
    sha256_file,
)
from opstore.types import JSONValue

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_bytes_known_vector() -> None:
    assert sha256_bytes(b"") == HASH_PREFIX + EMPTY_SHA256
    assert (
        sha256_bytes(b"abc")
        == "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


@given(st.binary(max_size=4096))
def test_sha256_bytes_matches_hashlib(data: bytes) -> None:
    assert sha256_bytes(data) == HASH_PREFIX + hashlib.sha256(data).hexdigest()


@given(st.binary(max_size=1 << 16))
def test_sha256_file_matches_bytes(tmp_path_factory: pytest.TempPathFactory, data: bytes) -> None:
    path = tmp_path_factory.mktemp("hashing") / "blob.bin"
    path.write_bytes(data)
    assert sha256_file(path) == sha256_bytes(data)


def test_sha256_file_streams_large_file(tmp_path: Path) -> None:
    data = b"x" * (3 * (1 << 20) + 17)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    assert sha256_file(path) == sha256_bytes(data)


def test_canonical_json_sorted_compact_unicode() -> None:
    text = canonical_json({"b": 1, "a": [True, None, "é"]})
    assert text == '{"a":[true,null,"é"],"b":1}'
    assert " " not in text


def test_canonical_json_no_ascii_escaping() -> None:
    assert canonical_json("π") == '"π"'


json_values: st.SearchStrategy[JSONValue] = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=40),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=20,
)


@given(json_values)
def test_canonical_json_key_order_invariance(value: JSONValue) -> None:
    reparsed: JSONValue = json.loads(canonical_json(value))
    assert canonical_json(reparsed) == canonical_json(value)
    assert sha256_canonical_json(reparsed) == sha256_canonical_json(value)


def test_canonical_hash_is_order_independent() -> None:
    assert sha256_canonical_json({"a": 1, "b": 2}) == sha256_canonical_json({"b": 2, "a": 1})
    assert sha256_canonical_json({"a": 1}) != sha256_canonical_json({"a": 2})


def test_is_hash_and_hex_of() -> None:
    good = sha256_bytes(b"x")
    assert is_hash(good)
    assert hex_of(good) == hashlib.sha256(b"x").hexdigest()
    for bad in ("", "sha256:", "sha256:zz", "md5:" + EMPTY_SHA256, HASH_PREFIX + EMPTY_SHA256[:-1]):
        assert not is_hash(bad)
        with pytest.raises(ValueError):
            hex_of(bad)
    assert not is_hash(HASH_PREFIX + EMPTY_SHA256.upper())
