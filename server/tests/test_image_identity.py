"""The bridge's render identity is measured, never merely copied into a caption."""

import hashlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from hephaestus.agent_bridge.cad_ops._base import CadOpError
from hephaestus.agent_bridge.cad_ops._build import BuildOps
from hephaestus.core.render.inspect import InspectImage, InspectResult


def result() -> InspectResult:
    images: list[InspectImage] = []
    for index, view in enumerate(("iso", "+X")):
        # Header fixture: this unit checks header budgets/identity, not PNG decode.
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 4 + b"IHDR"
        png += (index + 2).to_bytes(4, "big") + (2).to_bytes(4, "big")
        ref = f"artifact:render:sha256:{hashlib.sha256(png).hexdigest()}"
        images.append(InspectImage(view, "rgb", ref, png, False))
    return InspectResult(
        "ok",
        f"artifact:build:sha256:{'a' * 64}",
        "rgb",
        "solid",
        tuple(images),
        tuple(image.render_ref for image in images),
        False,
    )


def test_bridge_stamps_grounded_ordered_identity() -> None:
    rendered = result()
    with patch("hephaestus.agent_bridge.cad_ops._build.inspect_part", return_value=rendered):
        payload = BuildOps.inspect_part(
            cast(BuildOps, SimpleNamespace(_render_project=lambda: None)), "p"
        )
    for actual, image in zip(payload["images"], rendered.images, strict=True):
        assert actual["part"] == "p"
        assert actual["view"] == image.view
        assert actual["channel"] == "rgb"
        assert actual["source_artifact_ref"] == rendered.source_artifact_ref
        assert actual["render_artifact_ref"] == image.render_ref


@pytest.mark.parametrize("fault", ["hash", "order", "count"])
def test_bridge_refuses_uncorrelated_image(fault: str) -> None:
    from dataclasses import replace

    rendered = result()
    if fault == "hash":
        rendered = replace(
            rendered,
            images=(replace(rendered.images[0], png=rendered.images[1].png), rendered.images[1]),
        )
    elif fault == "order":
        rendered = replace(
            rendered, render_artifact_refs=tuple(reversed(rendered.render_artifact_refs))
        )
    else:
        rendered = replace(rendered, render_artifact_refs=rendered.render_artifact_refs[:1])
    with (
        patch("hephaestus.agent_bridge.cad_ops._build.inspect_part", return_value=rendered),
        pytest.raises(CadOpError, match="render"),
    ):
        BuildOps.inspect_part(cast(BuildOps, SimpleNamespace(_render_project=lambda: None)), "p")
