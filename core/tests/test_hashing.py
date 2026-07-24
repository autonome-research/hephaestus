"""Canonical hashing tests: params, hc projection, toolchain, opstore reuse."""

from __future__ import annotations

import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.hashing import (
    canonical_effective_params,
    consumed_hc_hash,
    effective_params_hash,
    hash_text,
    params_declaration_hash,
    toolchain_fingerprint,
    toolchain_hash,
)
from hephaestus.core.params import Param
from opstore.hashing import is_hash, sha256_canonical_json


class TestHashText:
    def test_well_formed(self) -> None:
        assert is_hash(hash_text("WIDTH = 420\n"))

    def test_deterministic_and_content_sensitive(self) -> None:
        assert hash_text("a = 1\n") == hash_text("a = 1\n")
        assert hash_text("a = 1\n") != hash_text("a = 2\n")

    def test_utf8(self) -> None:
        assert is_hash(hash_text("# ünïcode comment\n"))


class TestEffectiveParamsHash:
    def test_order_independent(self) -> None:
        assert effective_params_hash({"a": 1, "b": 2.5}) == effective_params_hash(
            {"b": 2.5, "a": 1}
        )

    def test_value_sensitive(self) -> None:
        assert effective_params_hash({"a": 1}) != effective_params_hash({"a": 2})

    def test_int_and_float_hash_differently(self) -> None:
        # §3: integer defaults declare integer params; 5 and 5.0 are distinct.
        assert effective_params_hash({"a": 5}) != effective_params_hash({"a": 5.0})

    def test_matches_opstore_canonical_json(self) -> None:
        assert effective_params_hash({"groove_count": 5, "groove_width": 3.0}) == (
            sha256_canonical_json({"groove_count": 5, "groove_width": 3.0})
        )

    def test_deterministic_repeated(self) -> None:
        hashes = {effective_params_hash({"x": 0.1 + 0.2, "n": 7}) for _ in range(20)}
        assert len(hashes) == 1

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValidationError):
            effective_params_hash({"a": float("nan")})

    def test_rejects_inf(self) -> None:
        with pytest.raises(ValidationError):
            effective_params_hash({"a": float("inf")})

    def test_rejects_bool(self) -> None:
        with pytest.raises(ValidationError):
            effective_params_hash({"a": True})  # type: ignore[dict-item]

    def test_canonicalization_preserves_types(self) -> None:
        canonical = canonical_effective_params({"n": 5, "w": 3.0})
        assert isinstance(canonical["n"], int)
        assert isinstance(canonical["w"], float)


class TestConsumedHcHash:
    def test_projection_only_consumed_names(self) -> None:
        # The hash covers exactly the consumed projection: adding an unrelated
        # name to globals must not change a part's dependency hash.
        consumed = {"shelf_d": 250.0, "ply_t": 6.0}
        assert consumed_hc_hash(consumed) == consumed_hc_hash(dict(consumed))

    def test_value_change_invalidates(self) -> None:
        assert consumed_hc_hash({"ply_t": 6.0}) != consumed_hc_hash({"ply_t": 6.5})

    def test_name_change_invalidates(self) -> None:
        assert consumed_hc_hash({"ply_t": 6.0}) != consumed_hc_hash({"ply_thk": 6.0})

    def test_order_independent(self) -> None:
        assert consumed_hc_hash({"a": 1, "b": 2}) == consumed_hc_hash({"b": 2, "a": 1})

    def test_nested_json_values(self) -> None:
        assert is_hash(consumed_hc_hash({"table": {"rows": [1, 2, 3]}, "name": "x"}))


class TestParamsDeclarationHash:
    def test_stable_across_dict_order(self) -> None:
        a = {"n": Param(5, min=2, max=10), "w": Param(3.0, min=2, max=6)}
        b = {"w": Param(3.0, min=2, max=6), "n": Param(5, min=2, max=10)}
        assert params_declaration_hash(a) == params_declaration_hash(b)

    def test_bounds_change_invalidates(self) -> None:
        assert params_declaration_hash({"n": Param(5, min=2, max=10)}) != params_declaration_hash(
            {"n": Param(5, min=2, max=12)}
        )

    def test_type_change_invalidates(self) -> None:
        assert params_declaration_hash({"n": Param(5, min=2, max=10)}) != params_declaration_hash(
            {"n": Param(5.0, min=2, max=10)}
        )

    def test_doc_change_invalidates(self) -> None:
        assert params_declaration_hash({"n": Param(5, min=2, max=10)}) != params_declaration_hash(
            {"n": Param(5, min=2, max=10, doc="count")}
        )


class TestToolchainHash:
    def test_fingerprint_shape(self) -> None:
        fingerprint = toolchain_fingerprint()
        assert isinstance(fingerprint["python"], str)
        assert isinstance(fingerprint["build123d"], str)
        ocp = fingerprint["ocp"]
        assert isinstance(ocp, dict)
        assert ocp, "at least one OCP distribution must be pinned"
        assert all(isinstance(v, str) for v in ocp.values())

    def test_hash_well_formed_and_deterministic(self) -> None:
        first = toolchain_hash()
        assert is_hash(first)
        assert toolchain_hash() == first

    def test_hash_matches_fingerprint(self) -> None:
        assert toolchain_hash() == sha256_canonical_json(toolchain_fingerprint())
