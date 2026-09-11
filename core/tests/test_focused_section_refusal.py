"""Unsupported focus+section must refuse before loading or publishing geometry."""

from typing import cast
from unittest.mock import patch

import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.render.inspect import RenderProject, inspect_part


def test_focused_section_refuses_before_rendering() -> None:
    with (
        patch("hephaestus.core.render.inspect.resolve_render_source") as resolve,
        patch("hephaestus.core.render.inspect.load_brep_shape") as load,
        patch("hephaestus.core.render.inspect._render_channel") as render,
    ):
        with pytest.raises(ValidationError, match=r"focus.*section"):
            inspect_part(
                cast(RenderProject, object()),
                "p",
                channel="section",
                section_plane="XY@0",
                focus="solid:0",
            )
        resolve.assert_not_called()
        load.assert_not_called()
        render.assert_not_called()
