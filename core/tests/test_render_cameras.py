"""Camera view grammar, validation, and deterministic framing."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.render.cameras import (
    STANDARD_VIEWS,
    camera_framing,
    parse_view,
    standard_view_names,
)


def test_standard_view_names_present() -> None:
    for name in ("iso", "+X", "-X", "+Y", "-Y", "+Z", "-Z"):
        assert name in STANDARD_VIEWS
        assert parse_view(name).name == name


def test_axis_view_directions() -> None:
    assert np.allclose(parse_view("+X").eye_direction(), [1, 0, 0], atol=1e-9)
    assert np.allclose(parse_view("-X").eye_direction(), [-1, 0, 0], atol=1e-9)
    assert np.allclose(parse_view("+Y").eye_direction(), [0, 1, 0], atol=1e-9)
    assert np.allclose(parse_view("+Z").eye_direction(), [0, 0, 1], atol=1e-9)
    assert np.allclose(parse_view("-Z").eye_direction(), [0, 0, -1], atol=1e-9)


def test_iso_direction_unit_and_octant() -> None:
    d = parse_view("iso").eye_direction()
    assert abs(np.linalg.norm(d) - 1.0) < 1e-9
    # Classic iso: equal positive components (1,1,1)/sqrt(3).
    assert np.allclose(d, np.array([1, 1, 1]) / math.sqrt(3), atol=1e-6)


def test_grammar_parses() -> None:
    v = parse_view("az45_el30")
    assert v.azimuth_deg == 45.0
    assert v.elevation_deg == 30.0
    assert parse_view("az-90_el-15").azimuth_deg == -90.0
    assert parse_view("az12.5_el7.25").elevation_deg == 7.25


def test_unknown_view_lists_valid_names() -> None:
    with pytest.raises(ValidationError) as exc:
        parse_view("banana")
    message = str(exc.value)
    for name in standard_view_names():
        assert name in message
    assert "az" in message and "el" in message


def test_grammar_elevation_bounds() -> None:
    with pytest.raises(ValidationError):
        parse_view("az0_el120")


def test_framing_deterministic_and_pose_orthonormal() -> None:
    bbox_min, bbox_max = (-40.0, -30.0, -6.0), (40.0, 30.0, 6.0)
    view = parse_view("iso")
    a = camera_framing(bbox_min, bbox_max, view, width=960, height=720)
    b = camera_framing(bbox_min, bbox_max, view, width=960, height=720)
    assert np.array_equal(a.pose, b.pose)
    assert a.xmag == b.xmag and a.ymag == b.ymag
    rot = a.pose[:3, :3]
    assert np.allclose(rot.T @ rot, np.eye(3), atol=1e-9)
    assert abs(np.linalg.det(rot) - 1.0) < 1e-9


def test_framing_respects_aspect_ratio() -> None:
    view = parse_view("+Z")
    f = camera_framing((-10, -10, -1), (10, 10, 1), view, width=800, height=400)
    # xmag/ymag must match the viewport aspect so nothing is stretched.
    assert abs((f.xmag / f.ymag) - (800 / 400)) < 1e-9


def test_framing_fits_bbox_with_margin() -> None:
    from hephaestus.core.render.cameras import DEFAULT_MARGIN

    view = parse_view("+Z")
    # Looking down +Z, the projected silhouette half-extents are the X/Y radii.
    f = camera_framing((-10, -20, -1), (10, 20, 1), view, width=100, height=100)
    # Square viewport: both mags equal, fitting the larger radius (20) + margin.
    assert f.xmag == pytest.approx(20.0 * (1 + DEFAULT_MARGIN))
    assert f.ymag == pytest.approx(20.0 * (1 + DEFAULT_MARGIN))


def test_top_view_uses_non_degenerate_up() -> None:
    # +Z view axis is parallel to world up; framing must still be orthonormal.
    f = camera_framing((-5, -5, -5), (5, 5, 5), parse_view("+Z"), width=200, height=200)
    rot = f.pose[:3, :3]
    assert np.allclose(rot.T @ rot, np.eye(3), atol=1e-9)


def test_degenerate_bbox_is_framed() -> None:
    f = camera_framing((1, 1, 1), (1, 1, 1), parse_view("+X"), width=64, height=64)
    assert f.xmag > 0 and f.ymag > 0
