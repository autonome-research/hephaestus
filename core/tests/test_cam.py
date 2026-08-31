# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""2D CAM: laser/waterjet toolpath + DXF from existing geometry.

The claim under test is a manufacturing one and it is measurable: a fixture
plate cut along the nominal boundary loses half a kerf per edge, so the
emitted toolpath and the DXF must measure **nominal + one kerf** on the
outer ring and **nominal minus one kerf** on a hole. The kernel is the one
already in-tree (kerf + flat_profiles + layout_to_dxf); this module only
orders the contours and refuses processes that are not a 2D cut.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from build123d import Box, Cylinder, Sphere
from hephaestus.core.cam import (
    CUT2D_PROCESSES,
    CamRefusal,
    derived_blank,
    emit_cut2d,
    pack_kerf_of,
)
from hephaestus.core.cutfile import CUT_LAYER
from hephaestus.geom.kerf import KERF_UNCOMPENSATED
from hephaestus.geom.nesting import PROFILE_LAYER

LASER_KERF: float = 0.2
WATERJET_KERF: float = 0.8


def _plate(width: float = 60.0, height: float = 40.0, *, bore: float | None = 6.0) -> Any:
    body = Box(width, height, 6.0)
    if bore is None:
        return body
    return body - Cylinder(bore, 20.0)


def _rings(data: bytes, path: Path, layer: str = PROFILE_LAYER) -> list[list[tuple[float, float]]]:
    path.write_bytes(data)
    ezdxf: Any = importlib.import_module("ezdxf")
    document: Any = ezdxf.readfile(str(path))
    rings: list[list[tuple[float, float]]] = []
    for entity in document.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'):
        rings.append([(float(p[0]), float(p[1])) for p in entity.get_points()])
    return rings


def _span(ring: list[tuple[float, float]] | tuple[tuple[float, float], ...]) -> tuple[float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (max(xs) - min(xs), max(ys) - min(ys))


def test_cut2d_processes_are_laser_and_waterjet_only() -> None:
    assert CUT2D_PROCESSES == ("laser_cut", "waterjet")


def test_a_laser_plate_emits_a_kerf_compensated_toolpath_and_dxf(tmp_path: Path) -> None:
    """Half a kerf per side: 60 x 40 nominal cuts to 60 x 40 on a 0.2 mm beam."""
    program = emit_cut2d(
        _plate(),
        process="laser_cut",
        part="plate",
        pack_kerf_mm=LASER_KERF,
    )
    assert program.kerf.to_json() == {
        "applied_mm": LASER_KERF,
        "source": "dfm",
        "process": "laser_cut",
    }
    assert [contour.ring for contour in program.toolpath] == ["hole_1", "outer"]
    assert all(contour.layer == CUT_LAYER for contour in program.toolpath)

    outer = next(contour for contour in program.toolpath if contour.ring == "outer")
    hole = next(contour for contour in program.toolpath if contour.ring == "hole_1")
    assert _span(outer.points) == (
        pytest.approx(60.0 + LASER_KERF, abs=1e-6),
        pytest.approx(40.0 + LASER_KERF, abs=1e-6),
    )
    assert _span(hole.points)[0] == pytest.approx(12.0 - LASER_KERF, abs=0.01)

    rings = _rings(program.dxf, tmp_path / "laser.dxf")
    spans = sorted((_span(ring) for ring in rings), key=lambda item: item[0])
    assert len(spans) == 2
    assert spans[1][0] == pytest.approx(60.0 + LASER_KERF, abs=1e-6)
    assert spans[0][0] == pytest.approx(12.0 - LASER_KERF, abs=0.01)
    record = program.to_json()
    assert record["kind"] == "cut2d"
    assert record["dxf_bytes"] == len(program.dxf)
    assert isinstance(record["dxf_sha256"], str) and record["dxf_sha256"].startswith("sha256:")


def test_waterjet_uses_its_pack_kerf_when_present() -> None:
    program = emit_cut2d(
        _plate(bore=None),
        process="waterjet",
        part="plate",
        pack_kerf_mm=WATERJET_KERF,
    )
    assert program.kerf.source == "dfm"
    assert program.kerf.applied_mm == pytest.approx(WATERJET_KERF)
    assert program.profiles[0].width_mm == pytest.approx(60.0 + WATERJET_KERF, abs=1e-6)
    assert program.profiles[0].height_mm == pytest.approx(40.0 + WATERJET_KERF, abs=1e-6)
    assert [contour.ring for contour in program.toolpath] == ["outer"]


def test_an_explicit_kerf_overrides_the_pack() -> None:
    program = emit_cut2d(
        _plate(bore=None),
        process="laser_cut",
        part="plate",
        explicit_kerf_mm=1.0,
        pack_kerf_mm=LASER_KERF,
    )
    assert program.kerf.to_json() == {
        "applied_mm": 1.0,
        "source": "explicit",
        "process": "laser_cut",
    }
    assert program.profiles[0].width_mm == pytest.approx(61.0, abs=1e-6)


def test_waterjet_without_a_pack_kerf_is_uncompensated_and_says_so() -> None:
    program = emit_cut2d(
        _plate(bore=None),
        process="waterjet",
        part="plate",
        unavailable="no_dfm_pack",
    )
    assert program.kerf.applied_mm is None
    assert program.kerf.source == "none"
    assert program.kerf.note == KERF_UNCOMPENSATED
    assert program.kerf.reason == "no_dfm_pack"
    assert program.profiles[0].width_mm == pytest.approx(60.0, abs=1e-6)


def test_a_router_process_is_refused_by_name() -> None:
    with pytest.raises(CamRefusal) as ei:
        emit_cut2d(_plate(bore=None), process="cnc_router", part="plate")
    assert ei.value.reason == "not_a_cut2d_process"
    assert ei.value.code == "cam_refused"
    candidates = ei.value.data["candidates"]
    assert candidates == list(CUT2D_PROCESSES)
    assert "cnc_router" not in candidates


def test_a_solid_with_no_flat_pattern_is_a_named_refusal() -> None:
    with pytest.raises(CamRefusal) as ei:
        emit_cut2d(Sphere(5.0), process="laser_cut", part="ball", pack_kerf_mm=LASER_KERF)
    assert ei.value.reason == "not_a_sheet_profile"


def test_a_hole_narrower_than_the_kerf_is_a_named_refusal() -> None:
    with pytest.raises(CamRefusal) as ei:
        emit_cut2d(_plate(bore=0.05), process="laser_cut", part="vent", pack_kerf_mm=LASER_KERF)
    assert ei.value.reason == "kerf_offset_failed"
    assert ei.value.data["ring"] == "hole_1"


def test_pack_kerf_of_reads_the_shipped_laser_and_waterjet_packs() -> None:
    from hephaestus.core.registry import DfmIndex, load_registry

    dfm = DfmIndex(load_registry(Path(__file__).resolve().parents[2] / "registries" / "dfm"))
    laser, laser_why = pack_kerf_of("laser_cut", dfm)
    water, water_why = pack_kerf_of("waterjet", dfm)
    router, router_why = pack_kerf_of("cnc_router", dfm)
    missing, missing_why = pack_kerf_of("plasma", dfm)
    assert (laser, laser_why) == (pytest.approx(LASER_KERF), None)
    assert (water, water_why) == (pytest.approx(WATERJET_KERF), None)
    assert (router, router_why) == (None, "pack_declares_no_kerf")
    assert (missing, missing_why) == (None, "no_dfm_pack")


def test_derived_blank_fits_the_compensated_plate() -> None:
    program = emit_cut2d(
        _plate(bore=None),
        process="laser_cut",
        part="plate",
        pack_kerf_mm=LASER_KERF,
    )
    blank = derived_blank(program.profiles)
    assert blank.width_mm == pytest.approx(program.profiles[0].width_mm + 2 * blank.margin_mm)
    assert blank.height_mm == pytest.approx(program.profiles[0].height_mm + 2 * blank.margin_mm)
