"""The bridge's render identity is measured, never merely copied into a caption."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from hephaestus.agent_bridge.cad_ops._base import CadOpError
from hephaestus.agent_bridge.cad_ops._build import BuildOps
from hephaestus.core.render.bundle import PassRefs
from hephaestus.core.render.inspect import InspectImage, InspectResult, SelectionBundleView


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


def selection_result() -> InspectResult:
    rendered = result()
    images = tuple(
        replace(
            image,
            channel="mask",
            render_ref=image.render_ref.replace(":render:", ":selection-preview:"),
        )
        for image in rendered.images
    )
    bundles = tuple(
        SelectionBundleView(
            image.view,
            f"artifact:selection-bundle:sha256:{str(index) * 64}",
            PassRefs(
                *(f"artifact:selection-pass:sha256:{str(index * 3 + n) * 64}" for n in range(3))
            ),
        )
        for index, image in enumerate(images)
    )
    return replace(
        rendered,
        channel="mask",
        mask_mode="selection",
        images=images,
        selection_bundles=bundles,
        render_artifact_refs=tuple(
            ref
            for image, bundle in zip(images, bundles, strict=True)
            for ref in (
                image.render_ref,
                bundle.pass_refs.solid,
                bundle.pass_refs.face,
                bundle.pass_refs.edge,
            )
        ),
    )


def test_bridge_accepts_only_grounded_selection_preview_bytes() -> None:
    rendered = selection_result()
    with patch("hephaestus.agent_bridge.cad_ops._build.inspect_part", return_value=rendered):
        payload = BuildOps.inspect_part(
            cast(BuildOps, SimpleNamespace(_render_project=lambda: None)),
            "p",
            channel="mask",
            mask_mode="selection",
        )
    assert len(payload["images"]) == 2
    assert payload["render_artifact_refs"] == list(rendered.render_artifact_refs)
    for actual, image in zip(payload["images"], rendered.images, strict=True):
        assert actual["render_artifact_ref"] == image.render_ref
        assert actual["channel"] == "mask"
        assert actual["source_artifact_ref"] == rendered.source_artifact_ref
        assert actual["palette_decodable"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "render",
        "selection-pass",
        "posed-render",
        "unknown",
        "hash",
        "pass-kind",
        "bundle-kind",
        "mode",
        "missing-bundles",
        "channel",
        "source",
    ],
)
def test_bridge_refuses_wrong_selection_identity(fault: str) -> None:
    rendered = selection_result()
    if fault in ("render", "selection-pass", "posed-render", "unknown"):
        first = replace(
            rendered.images[0],
            render_ref=rendered.images[0].render_ref.replace(":selection-preview:", f":{fault}:"),
        )
        rendered = replace(
            rendered,
            images=(first, rendered.images[1]),
            render_artifact_refs=(first.render_ref, *rendered.render_artifact_refs[1:]),
        )
    elif fault == "hash":
        rendered = replace(
            rendered,
            images=(replace(rendered.images[0], png=rendered.images[1].png), rendered.images[1]),
        )
    elif fault in ("pass-kind", "bundle-kind"):
        bundles = rendered.selection_bundles
        assert bundles is not None
        first = bundles[0]
        if fault == "pass-kind":
            first = replace(
                first,
                pass_refs=replace(
                    first.pass_refs,
                    solid=first.pass_refs.solid.replace(":selection-pass:", ":render:"),
                ),
            )
            rendered = replace(
                rendered,
                render_artifact_refs=(
                    rendered.render_artifact_refs[0],
                    first.pass_refs.solid,
                    *rendered.render_artifact_refs[2:],
                ),
            )
        else:
            first = replace(
                first, bundle_ref=first.bundle_ref.replace(":selection-bundle:", ":render:")
            )
        rendered = replace(rendered, selection_bundles=(first, bundles[1]))
    elif fault == "missing-bundles":
        rendered = replace(
            rendered,
            selection_bundles=None,
            render_artifact_refs=tuple(i.render_ref for i in rendered.images),
        )
    elif fault == "channel":
        rendered = replace(
            rendered, images=(replace(rendered.images[0], channel="rgb"), rendered.images[1])
        )
    with (
        patch("hephaestus.agent_bridge.cad_ops._build.inspect_part", return_value=rendered),
        pytest.raises(CadOpError, match="render"),
    ):
        BuildOps.inspect_part(
            cast(BuildOps, SimpleNamespace(_render_project=lambda: None)),
            "p",
            channel="mask",
            mask_mode="solid" if fault == "mode" else "selection",
            artifact_ref=f"artifact:build:sha256:{'b' * 64}" if fault == "source" else None,
        )
