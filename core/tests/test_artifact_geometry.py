"""Reloaded-BRep measurement source: ``"part"`` only, addressing intact (§7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.addressing import resolve
from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.artifact_geometry import (
    artifact_source,
    load_brep_shape,
    part_only_source,
)


def box_brep_bytes(tmp_path: Path) -> bytes:
    # OCP ships no stubs; this is the same untyped writer the worker uses.
    from build123d import Box
    from OCP.BRepTools import (  # pyright: ignore[reportMissingTypeStubs]
        BRepTools,  # pyright: ignore[reportUnknownVariableType, reportAttributeAccessIssue]
    )

    shape = Box(10.0, 5.0, 2.0)
    path = tmp_path / "box.brep"
    assert BRepTools.Write_s(shape.wrapped, str(path))  # pyright: ignore[reportUnknownMemberType]
    return path.read_bytes()


class TestArtifactSource:
    def test_roundtrip_preserves_geometry(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        volume = getattr(shape, "volume", None)
        assert volume == pytest.approx(100.0, abs=1e-6)

    def test_part_selector_resolves_to_the_loaded_shape(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        source = artifact_source(data, scratch_dir=tmp_path / "scratch")
        resolution = resolve("part", source.index)
        assert resolution.kind == "part"
        picked = source.shape(resolution)
        assert getattr(picked, "volume", None) == pytest.approx(100.0, abs=1e-6)

    def test_non_part_selectors_raise_addressing_error(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        source = artifact_source(data, scratch_dir=tmp_path)
        with pytest.raises(AddressingError):
            resolve("top_face", source.index)

    def test_part_only_index_is_empty(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        source = part_only_source(load_brep_shape(data))
        assert source.index.labels == ()
        assert dict(source.index.bindings) == {}
        assert source.index.tags == frozenset()
