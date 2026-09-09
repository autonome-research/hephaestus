# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``BuildResult`` persists the params DECLARATION, not just its hash (RC-6).

``core/src/hephaestus/core/types.py``'s ``BuildResult`` keeps
``input_hashes.part_params`` — the *hash* of the ``PARAMS`` declaration — and
drops the declaration itself, so no reader can answer "what are this part's
bounds?" from the current build record; ``probe_part_params``
(``server/src/hephaestus/agent_bridge/cad_ops/_params.py``) re-runs a full
sandboxed build every time just to recover the same
``{name: {default, min, max, doc, step}}`` shape the worker already computed
and handed back as ``worker_result["params_declaration"]`` — the RC-7 3.35s
sandbox floor, paid to read a literal.

This mirrors the exact shape :func:`hephaestus.agent_bridge.cad_ops._params.
_params_from_declaration` rebuilds from the worker's JSON, and the field names
this test pins (``params_declaration``, ``check_names``) are RC-6's own words:
"the latent ``check_names`` case" is named in the root-cause paragraph
verbatim. Both are additive fields on the §8 record, following the exact
precedent ``metadata`` and ``checkpoints`` already set on this same
dataclass — "the record used to drop it... {} / () is the honest reading" —
so a record written before this field existed still loads.
"""

from __future__ import annotations

from typing import Any

from hephaestus.core.params import Param
from hephaestus.core.types import AuditHashes, BuildResult, InputHashes

_H = "sha256:" + "ab" * 32


def _input_hashes() -> InputHashes:
    return InputHashes(
        script=_H,
        hc_dependencies=_H,
        part_params=_H,
        effective_params=_H,
        toolchain=_H,
    )


def _audit_hashes() -> AuditHashes:
    return AuditHashes(globals_source=_H, project_param_state=_H)


def _base_kwargs() -> dict[str, Any]:
    return dict(
        part="widget",
        status="ok",
        current=True,
        artifact_ref="artifact:build:" + _H,
        project_snapshot_ref=None,
        input_hashes=_input_hashes(),
        audit_hashes=_audit_hashes(),
        metrics=None,
        checks={},
        geometries=(),
        params={"width": 40.0},
        source_map_ref=None,
        warnings=(),
        error=None,
    )


class TestParamsDeclaration:
    def test_build_result_carries_the_declaration_not_just_its_hash(self) -> None:
        declaration = {"width": Param(default=40.0, min=10.0, max=80.0, doc="overall width")}
        result = BuildResult(**_base_kwargs(), params_declaration=declaration)
        assert result.params_declaration == declaration

    def test_declaration_serializes_to_the_worker_probe_shape(self) -> None:
        """``Param.to_json()``'s own canonical form
        (``core/params.py:params_declaration_json``), so a reader gets ONE
        JSON shape for a param declaration everywhere it appears, rather than
        the record inventing a second one.
        """
        declaration = {"width": Param(default=40.0, min=10.0, max=80.0)}
        result = BuildResult(**_base_kwargs(), params_declaration=declaration)
        data = result.to_json()
        assert data["params_declaration"] == {
            "width": {"default": 40.0, "min": 10.0, "max": 80.0, "type": "float"}
        }

    def test_round_trip(self) -> None:
        declaration = {
            "width": Param(default=40.0, min=10.0, max=80.0),
            "wall": Param(default=2.0, min=1.0, max=6.0, step=0.5),
        }
        result = BuildResult(**_base_kwargs(), params_declaration=declaration)
        assert BuildResult.from_json(result.to_json()) == result

    def test_absent_from_a_legacy_record_reads_as_empty(self) -> None:
        """A record written before this field existed carries no
        ``params_declaration`` key at all; reading it must not refuse — the
        same ``"metadata"`` / ``"checkpoints"`` precedent on this dataclass.
        """
        result = BuildResult(**_base_kwargs())
        data = result.to_json()
        data.pop("params_declaration", None)
        loaded = BuildResult.from_json(data)
        assert loaded.params_declaration == {}

    def test_default_is_empty_when_not_supplied(self) -> None:
        result = BuildResult(**_base_kwargs())
        assert result.params_declaration == {}


class TestCheckNames:
    """RC-6's "latent ``check_names`` case": the declared check names are
    computed by the worker and dropped at publication, so an empty
    ``checks`` map is ambiguous between "this part declares no checks" and
    "it declared some that failed to register" (J-cli-startup-9).
    """

    def test_build_result_carries_the_declared_check_names(self) -> None:
        result = BuildResult(**_base_kwargs(), check_names=("wide_enough", "sealed"))
        assert result.check_names == ("wide_enough", "sealed")

    def test_round_trip(self) -> None:
        result = BuildResult(**_base_kwargs(), check_names=("wide_enough",))
        assert BuildResult.from_json(result.to_json()) == result

    def test_absent_from_a_legacy_record_reads_as_empty_tuple(self) -> None:
        result = BuildResult(**_base_kwargs())
        data = result.to_json()
        data.pop("check_names", None)
        loaded = BuildResult.from_json(data)
        assert loaded.check_names == ()

    def test_default_is_empty_when_not_supplied(self) -> None:
        result = BuildResult(**_base_kwargs())
        assert result.check_names == ()

    def test_empty_check_names_is_distinct_from_a_part_that_declares_some(self) -> None:
        """The disambiguation this field exists for: an empty ``checks`` map
        beside a non-empty ``check_names`` means "declared some, none produced
        a recorded result yet" — never conflated with "declares none".
        """
        declared_none = BuildResult(**_base_kwargs(), check_names=())
        declared_some = BuildResult(**_base_kwargs(), check_names=("wide_enough",))
        assert declared_none.checks == declared_some.checks == {}
        assert declared_none.check_names != declared_some.check_names


class TestParamsDeclarationSchemaSanity:
    """Guards against a partial fix: both new fields land on ``to_json`` and
    ``from_json`` together, or a document written under the new code cannot be
    read back by the same code.
    """

    def test_a_record_with_both_new_fields_round_trips(self) -> None:
        result = BuildResult(
            **_base_kwargs(),
            params_declaration={"width": Param(default=40.0, min=10.0, max=80.0)},
            check_names=("wide_enough",),
        )
        assert BuildResult.from_json(result.to_json()) == result
