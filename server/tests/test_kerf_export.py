"""``export_part`` kerf compensation, end to end through the real dispatcher.

The bug this pins is a fabrication one, not a software one: before compensation
every laser-cut profile left this exporter half a kerf undersized on each edge,
so a finger joint dimensioned from the model measured 0.2 mm loose per mating
face and did not assemble. What is asserted here is therefore measured out of
the **exported bytes** — ezdxf re-parses the file and the rings are measured —
and never out of the number the exporter was asked to apply:

* a part that declares ``process = "laser_cut"`` picks the kerf up from that
  process's DFM pack without being asked, and its profiles come out exactly one
  kerf larger on each axis while its bores come out one kerf smaller;
* an explicit ``kerf_mm`` overrides the pack, and ``kerf_mm = 0`` reproduces the
  pre-compensation bytes **exactly** — the same bytes an identical part with no
  resolvable process produces, which is the regression pin for "an
  uncompensated export did not change";
* every DXF/SVG result reports which kerf was applied and where it came from,
  and an uncompensated one says so rather than passing for a compensated file;
* a bore narrower than the kerf — which has no compensated path at all — is a
  structured refusal naming the profile and the ring, never a quiet nominal
  path.
"""

from __future__ import annotations

import importlib
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.cad_ops import CadOpError
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.geom.nesting import PROFILE_LAYER
from hephaestus.testing.tools_fixture import Project, make_project

#: The ``laser_cut`` pack's declared kerf (``registries/dfm/laser_cut``).
PACK_KERF: float = 0.2

#: One 60 x 40 plate with a 12 mm bore, cut on a laser. Its flat pattern is the
#: simplest thing whose compensation is measurable on both boundaries at once.
PLATE = """_plate = Box(60.0, 40.0, 6.0) - Cylinder(6.0, 20.0)
_plate.label = "plate"
part.geometry = _plate

part.description = "A bored plate whose cut path must be kerf compensated"
part.process = "{process}"
part.stock_form = "sheet"
part.blank_size = "One 120 x 90 x 6 mm blank"
"""

#: The same plate with a vent far narrower than any kerf: there is no path that
#: cuts it, and pretending otherwise ships scrap.
PIN_HOLE = """_plate = Box(60.0, 40.0, 6.0) - Cylinder(0.05, 20.0)
_plate.label = "plate"
part.geometry = _plate

part.description = "A plate whose vent is narrower than the beam"
part.process = "laser_cut"
part.blank_size = "One 120 x 90 x 6 mm blank"
"""


@pytest.fixture
def cut(tmp_path: Path) -> Iterator[Project]:
    """A project with ``laser`` (pack kerf), ``router`` (pack, no kerf), ``mill`` (no pack)."""
    project = make_project(tmp_path / "proj")
    parts = project.root / "parts"
    (parts / "laser.py").write_text(PLATE.format(process="laser_cut"), encoding="utf-8")
    # ``cnc_router`` has a DFM pack that does not declare kerf_mm: a router bit
    # removes its full diameter, so this is the "pack exists, no kerf" path.
    (parts / "router.py").write_text(PLATE.format(process="cnc_router"), encoding="utf-8")
    # ``cnc_mill`` is a real process with no published rule pack: a legitimate
    # design that simply declares no kerf, and the "nothing resolved" path.
    (parts / "mill.py").write_text(PLATE.format(process="cnc_mill"), encoding="utf-8")
    try:
        for name in ("laser", "router", "mill"):
            assert project.call("build_part", {"name": name})["status"] == "ok"
        yield project
    finally:
        project.close()


def _export(project: Project, **arguments: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"format": "dxf", "layout": "nested_sheet"}
    payload.update(arguments)
    entry = payload.pop("entry", None)
    return dict(project.call("export_part", payload, entry=entry))


def _bytes(project: Project, result: dict[str, Any]) -> bytes:
    assert len(result["paths"]) == 1
    return (project.root / str(result["paths"][0])).read_bytes()


def _rings(data: bytes, path: Path, layer: str = PROFILE_LAYER) -> list[list[tuple[float, float]]]:
    """The closed polylines of one layer of a DXF (untyped: confined here)."""
    path.write_bytes(data)
    ezdxf: Any = importlib.import_module("ezdxf")
    document: Any = ezdxf.readfile(str(path))
    rings: list[list[tuple[float, float]]] = []
    for entity in document.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'):
        rings.append([(float(p[0]), float(p[1])) for p in entity.get_points()])
    return rings


def _span(ring: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _outer_and_hole(data: bytes, path: Path) -> tuple[tuple[float, float], tuple[float, float]]:
    """``(outer span, hole span)`` of the single nested profile in ``data``."""
    spans = sorted((_span(ring) for ring in _rings(data, path)), key=lambda s: s[0])
    assert len(spans) == 2, spans
    return spans[1], spans[0]


# ==========================================================================
# the pack's kerf is picked up, and it lands on the geometry


def test_the_process_pack_supplies_the_kerf_without_being_asked(
    cut: Project, tmp_path: Path
) -> None:
    """``part.process = "laser_cut"`` is the whole declaration a part needs."""
    result = _export(cut, name="laser")
    assert result["kerf"] == {"applied_mm": PACK_KERF, "source": "dfm", "process": "laser_cut"}

    outer, hole = _outer_and_hole(_bytes(cut, result), tmp_path / "laser.dxf")
    # Half a kerf per side: the finished part lands on 60 x 40, not 59.8 x 39.8.
    assert outer[0] == pytest.approx(60.0 + PACK_KERF, abs=1e-6)
    assert outer[1] == pytest.approx(40.0 + PACK_KERF, abs=1e-6)
    # …and the bore the other way, so the finished opening lands on 12 mm.
    assert hole[0] == pytest.approx(12.0 - PACK_KERF, abs=0.01)


def test_an_explicit_kerf_overrides_the_pack(cut: Project, tmp_path: Path) -> None:
    result = _export(cut, name="laser", kerf_mm=1.0, entry="explicit")
    assert result["kerf"] == {"applied_mm": 1.0, "source": "explicit", "process": "laser_cut"}
    outer, _ = _outer_and_hole(_bytes(cut, result), tmp_path / "explicit.dxf")
    assert outer[0] == pytest.approx(61.0, abs=1e-6)


def test_a_process_with_no_pack_compensates_nothing_and_says_so(
    cut: Project, tmp_path: Path
) -> None:
    result = _export(cut, name="mill")
    assert result["kerf"] == {
        "applied_mm": None,
        "source": "none",
        "process": "cnc_mill",
        "note": "kerf_uncompensated",
        "reason": "no_dfm_pack",
    }
    outer, hole = _outer_and_hole(_bytes(cut, result), tmp_path / "mill.dxf")
    assert outer == (pytest.approx(60.0), pytest.approx(40.0))
    assert hole[0] == pytest.approx(12.0, abs=0.01)


def test_a_router_pack_without_kerf_compensates_nothing_and_says_so(
    cut: Project, tmp_path: Path
) -> None:
    """The cnc_router pack is real (#28) and still must not invent a laser kerf."""
    result = _export(cut, name="router")
    assert result["kerf"] == {
        "applied_mm": None,
        "source": "none",
        "process": "cnc_router",
        "note": "kerf_uncompensated",
        "reason": "pack_declares_no_kerf",
    }
    outer, hole = _outer_and_hole(_bytes(cut, result), tmp_path / "router.dxf")
    assert outer == (pytest.approx(60.0), pytest.approx(40.0))
    assert hole[0] == pytest.approx(12.0, abs=0.01)


def test_a_part_that_declares_no_process_names_that_as_the_reason(cut: Project) -> None:
    """``widget`` (the fixture's own part) declares no manufacturing metadata."""
    cut.call("build_part", {"name": "widget"})
    result = _export(
        cut,
        name="widget",
        layout="nested_sheet",
        blank={"width_mm": 300.0, "height_mm": 300.0},
        entry="widget",
    )
    assert result["kerf"]["applied_mm"] is None
    assert result["kerf"]["note"] == "kerf_uncompensated"
    assert result["kerf"]["reason"] == "no_process"


# ==========================================================================
# the uncompensated path is byte-for-byte what it always was


def test_kerf_zero_reproduces_the_uncompensated_bytes_exactly(cut: Project) -> None:
    """The regression pin: compensation changed nothing when it does not apply.

    ``laser`` with ``kerf_mm = 0`` and ``router`` (whose process resolves no
    kerf at all) are the same geometry, and a DXF carries no part name — so the
    two files must be identical byte for byte, not merely equivalent.
    """
    zeroed = _export(cut, name="laser", kerf_mm=0.0, target="zero.dxf", entry="zero")
    nominal = _export(cut, name="router", target="nominal.dxf", entry="nominal")
    assert _bytes(cut, zeroed) == _bytes(cut, nominal)
    assert zeroed["kerf"] == {
        "applied_mm": 0.0,
        "source": "explicit",
        "process": "laser_cut",
        "note": "kerf_uncompensated",
        "reason": "explicit_zero",
    }


def test_compensated_exports_are_still_deterministic(cut: Project) -> None:
    first = _export(cut, name="laser", target="det-a.dxf", entry="det-a")
    second = _export(cut, name="laser", target="det-b.dxf", entry="det-b")
    assert _bytes(cut, first) == _bytes(cut, second)


# ==========================================================================
# as_built, and the formats kerf must not touch


def test_the_as_built_cut_path_is_compensated_too(cut: Project) -> None:
    """An as-built DXF of a sheet part is a cut path and is compensated."""
    compensated = _export(cut, name="laser", layout="as_built", entry="ab")
    assert compensated["kerf"]["source"] == "dfm"
    assert compensated["kerf"]["applied_mm"] == pytest.approx(PACK_KERF)
    nominal = _export(cut, name="laser", layout="as_built", kerf_mm=0.0, entry="ab0")
    assert _bytes(cut, compensated) != _bytes(cut, nominal)


def test_the_svg_cut_file_is_compensated_and_reports_it_too(cut: Project) -> None:
    """SVG is a cut file as much as DXF is; both go to the same machines."""
    result = _export(cut, name="laser", format="svg", entry="svg")
    assert result["kerf"]["source"] == "dfm"
    text = _bytes(cut, result).decode("utf-8")
    root = ET.fromstring(text)
    polygons = root.findall("{http://www.w3.org/2000/svg}polygon")
    outer = [p for p in polygons if p.get("id") == "laser_1"]
    assert len(outer) == 1
    points = [
        (float(pair.split(",")[0]), float(pair.split(",")[1]))
        for pair in (outer[0].get("points") or "").split()
    ]
    assert _span(points)[0] == pytest.approx(60.0 + PACK_KERF, abs=1e-6)


def test_a_model_format_refuses_a_kerf_rather_than_ignoring_it(cut: Project) -> None:
    """A STEP must stay nominal: whatever consumes it applies its own allowance."""
    with pytest.raises((DispatchError, CadOpError)) as ei:
        cut.call(
            "export_part", {"name": "laser", "format": "step", "kerf_mm": 0.2}, entry="step-kerf"
        )
    assert ei.value.reason == "invalid_params"


def test_a_model_format_reports_no_kerf_block_at_all(cut: Project) -> None:
    result = dict(cut.call("export_part", {"name": "laser", "format": "step"}, entry="step"))
    assert "kerf" not in result


# ==========================================================================
# the refusal


def test_a_bore_narrower_than_the_kerf_refuses_naming_the_ring(tmp_path: Path) -> None:
    """No compensated path exists; emitting the nominal one would be scrap."""
    project = make_project(tmp_path / "pin")
    try:
        (project.root / "parts" / "vent.py").write_text(PIN_HOLE, encoding="utf-8")
        assert project.call("build_part", {"name": "vent"})["status"] == "ok"
        with pytest.raises(DispatchError) as ei:
            project.call("export_part", {"name": "vent", "format": "dxf", "layout": "nested_sheet"})
        assert ei.value.reason == "kerf_offset_failed"
        assert ei.value.data["profile"] == "vent_1"
        assert ei.value.data["ring"] == "hole_1"
        assert ei.value.data["kerf_mm"] == pytest.approx(PACK_KERF)
        # Nothing was written: a refused export leaves no half-correct file.
        exports = project.root / ".heph" / "exports"
        assert not exports.exists() or not list(exports.glob("*.dxf"))
    finally:
        project.close()


# ==========================================================================
# idempotency


def test_the_kerf_argument_is_part_of_the_invocation_payload(cut: Project) -> None:
    """Two presentations of one invocation id may not disagree about the kerf."""
    args = {"name": "laser", "format": "dxf", "layout": "nested_sheet", "kerf_mm": 0.3}
    first = dict(cut.call("export_part", args, entry="idem"))
    replay = dict(cut.call("export_part", args, entry="idem"))
    assert replay["paths"] == first["paths"]
    assert (
        replay["kerf"]
        == first["kerf"]
        == {
            "applied_mm": 0.3,
            "source": "explicit",
            "process": "laser_cut",
        }
    )
    with pytest.raises((DispatchError, CadOpError)) as ei:
        cut.call("export_part", {**args, "kerf_mm": 0.4}, entry="idem")
    assert ei.value.reason == "key_payload_mismatch"
