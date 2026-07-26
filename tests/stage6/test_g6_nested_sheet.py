# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G6: the nesting clause — three profiles that fit the declared blank.

Gate clause: *"nested DXF for the gusset contains 3 profiles fitting the
declared 210x125 blanks (ezdxf assertions)"*.

The fixture is a gusset-class part: three flat laminations of one 6 mm sheet
(a triangular web, a spacer and a cleat) whose ``part.blank_size`` declares the
210 x 125 mm blank. The export goes through the real ``export_part`` tool and
the evidence is read back out of the produced bytes with **ezdxf** — closed
LWPOLYLINEs, their areas, their containment in the blank rectangle, and their
pairwise disjointness — never out of the layout the writer believed in.

The refusal/determinism/SVG coverage lives in
``server/tests/test_nested_sheet.py``; this module is the gate evidence.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g6 import G6Project, make_g6_project
from hephaestus.agent_bridge.cad_ops import script_metadata
from hephaestus.bench.harness import dxf_layer_extents, dxf_profile_count
from hephaestus.core.nesting import BLANK_LAYER, PROFILE_LAYER, blank_from_metadata

#: The blank ``part.blank_size`` declares, in millimetres.
BLANK_W, BLANK_H = 210.0, 125.0

#: Flat-pattern areas of the three laminations, mm^2: triangle, spacer, cleat.
EXPECTED_AREAS: tuple[float, ...] = (0.5 * 100.0 * 60.0, 60.0 * 40.0, 90.0 * 25.0)

Ring = list[tuple[float, float]]


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Iterator[G6Project]:
    scaffolded = make_g6_project(
        tmp_path_factory.mktemp("g6-nest") / "proj", ("gusset",), secure=False
    )
    try:
        assert scaffolded.build("gusset").startswith("artifact:")
        yield scaffolded
    finally:
        scaffolded.close()


@pytest.fixture(scope="module")
def export(project: G6Project) -> dict[str, Any]:
    """The one nested export the whole module reads (exports are create-only)."""
    return dict(
        project.call("export_part", {"name": "gusset", "format": "dxf", "layout": "nested_sheet"})
    )


@pytest.fixture(scope="module")
def nested(project: G6Project, export: dict[str, Any]) -> bytes:
    paths = cast("list[str]", export["paths"])
    assert len(paths) == 1, paths
    return project.read(paths[0])


def _document(data: bytes, path: Path) -> Any:
    """Re-parse the exported bytes with ezdxf (untyped: confined to an ``Any``)."""
    path.write_bytes(data)
    ezdxf: Any = importlib.import_module("ezdxf")
    return ezdxf.readfile(str(path))


def _rings(data: bytes, path: Path, layer: str) -> list[Ring]:
    rings: list[Ring] = []
    for entity in _document(data, path).modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'):
        assert entity.closed, f"a {layer} outline must be a CLOSED polyline"
        rings.append([(float(p[0]), float(p[1])) for p in entity.get_points()])
    return rings


def _area(ring: Ring) -> float:
    total = 0.0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _bbox(ring: Ring) -> tuple[float, float, float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] < b[2] - 1e-9 and b[0] < a[2] - 1e-9 and a[1] < b[3] - 1e-9 and b[1] < a[3] - 1e-9


def test_the_nested_dxf_holds_three_closed_profiles(nested: bytes, tmp_path: Path) -> None:
    rings = _rings(nested, tmp_path / "nested.dxf", PROFILE_LAYER)
    assert len(rings) == 3, "the gusset is three laminations, so three cut profiles"
    # They are the fixture's own flat patterns, not decorative rectangles.
    assert sorted(_area(ring) for ring in rings) == pytest.approx(sorted(EXPECTED_AREAS), rel=1e-3)
    # The grader's own reader agrees with ezdxf on the count.
    assert dxf_profile_count(nested, layer=PROFILE_LAYER) == 3


def test_every_profile_fits_inside_the_declared_blank(nested: bytes, tmp_path: Path) -> None:
    blank = _rings(nested, tmp_path / "blank.dxf", BLANK_LAYER)
    assert len(blank) == 1, "the blank is drawn once, on its own layer"
    bx0, by0, bx1, by1 = _bbox(blank[0])
    assert (bx1 - bx0, by1 - by0) == (pytest.approx(BLANK_W), pytest.approx(BLANK_H))

    for ring in _rings(nested, tmp_path / "profiles.dxf", PROFILE_LAYER):
        x0, y0, x1, y1 = _bbox(ring)
        assert bx0 - 1e-6 <= x0 and x1 <= bx1 + 1e-6, "a profile hangs off the blank in X"
        assert by0 - 1e-6 <= y0 and y1 <= by1 + 1e-6, "a profile hangs off the blank in Y"

    # The same claim through the grader's extent reader, on the whole layer.
    profiles = dxf_layer_extents(nested, PROFILE_LAYER)
    assert profiles is not None
    assert profiles[0] >= bx0 - 1e-6 and profiles[2] <= bx1 + 1e-6
    assert profiles[1] >= by0 - 1e-6 and profiles[3] <= by1 + 1e-6


def test_no_two_placed_profiles_overlap(nested: bytes, tmp_path: Path) -> None:
    """Fitting on the blank is worthless if two parts are cut out of each other."""
    boxes = [_bbox(ring) for ring in _rings(nested, tmp_path / "overlap.dxf", PROFILE_LAYER)]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _overlap(boxes[i], boxes[j]), f"profiles {i} and {j} overlap"


def test_the_blank_comes_from_the_parts_own_declaration(
    project: G6Project, export: dict[str, Any]
) -> None:
    """210 x 125 is the fixture's ``part.blank_size``, not an export argument.

    The export above passed no ``blank``: the size on the sheet is the one the
    script declares, recovered from §5.2 metadata without running it.
    """
    source = (project.root / "parts" / "gusset.py").read_text(encoding="utf-8")
    declared = blank_from_metadata(script_metadata(source)["blank_size"])
    assert declared is not None
    assert (declared.width_mm, declared.height_mm) == (
        pytest.approx(BLANK_W),
        pytest.approx(BLANK_H),
    )
    # …and that is the rectangle the exported bytes carry.
    assert (
        export["source_artifact_ref"]
        == cast("Any", project.cad.current_build("gusset")).artifact_ref
    )
