"""Declared direct refusal vocabularies stay equal to their producing sites."""

from __future__ import annotations

import ast
from pathlib import Path

from hephaestus.agent_bridge.cad_ops import CAD_OP_REFUSAL_REASONS
from hephaestus.agent_bridge.dispatch import DISPATCH_REFUSAL_REASONS

SERVER_SRC = Path(__file__).parents[1] / "src" / "hephaestus" / "agent_bridge"


def _literal_error_reasons(paths: list[Path], constructor: str) -> frozenset[str]:
    reasons: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            first = node.args[0]
            if (
                name == constructor
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
            ):
                reasons.add(first.value)
    return frozenset(reasons)


def test_dispatch_direct_refusal_vocabulary_matches_its_raise_sites() -> None:
    produced = _literal_error_reasons([SERVER_SRC / "dispatch.py"], "DispatchError")
    assert produced == DISPATCH_REFUSAL_REASONS


def test_cad_op_direct_refusal_vocabulary_matches_its_raise_sites() -> None:
    paths = sorted((SERVER_SRC / "cad_ops").glob("*.py"))
    produced = _literal_error_reasons(paths, "CadOpError")
    assert produced == CAD_OP_REFUSAL_REASONS
