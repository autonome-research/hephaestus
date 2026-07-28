# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared scaffolding for the Gate G8A (ingest) evidence suite.

Every G8A clause is asserted against a **real project driven through the real
tool dispatcher** — the surface a model actually calls — over a real opstore,
and the two bench clauses through the real bench loop with the packaged Node
sidecar and a scripted model. The exhaustive unit coverage of the mechanisms
lives elsewhere (``core/tests/test_import_step*.py``,
``server/tests/test_references.py``); this suite is the gate evidence, so what
it asserts is *product behaviour*: what the model can do, what it is refused,
and what the project's own state says afterwards.

The STEP fixtures are authored here rather than imported from ``core/tests`` or
``corpus/`` so a gate assertion cannot be satisfied by a change to somebody
else's fixture. They are written once per session (OCCT stamps a timestamp into
the STEP header, so the bytes must be produced once and reused) and handed round
as bytes.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.testing.tools_fixture import Project

__all__ = [
    "PLATE_VOLUME_MM3",
    "StepFixtures",
    "build_ok",
    "install_import",
    "make_step_fixtures",
    "pdf_bytes",
    "png_bytes",
    "source_map_of",
    "write_script",
]

#: The plate fixture's exact volume (40 x 20 x 5), to 1e-6.
PLATE_VOLUME_MM3 = 40.0 * 20.0 * 5.0


@dataclass(frozen=True)
class StepFixtures:
    """The session's STEP bytes: a plate, a taller replacement, and a boss."""

    plate: bytes
    plate_taller: bytes
    boss: bytes


def make_step_fixtures(scratch: Path) -> StepFixtures:
    """Author the three STEP fixtures once, through the product's own writer."""
    from build123d import Box, Cylinder
    from hephaestus.geom.step_io import write_step

    scratch.mkdir(parents=True, exist_ok=True)
    plate = scratch / "plate.step"
    taller = scratch / "plate_taller.step"
    boss = scratch / "boss.step"
    write_step(Box(40, 20, 5), plate)
    write_step(Box(40, 20, 8), taller)
    write_step(Cylinder(5, 10), boss)
    return StepFixtures(
        plate=plate.read_bytes(), plate_taller=taller.read_bytes(), boss=boss.read_bytes()
    )


def install_import(root: Path, name: str, data: bytes) -> Path:
    """Put a file in the project's ``imports/`` the way an operator would."""
    target = root / "imports" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def write_script(project: Project, name: str, script: str) -> None:
    """Author a part through the model's own tools (create_part + write_part)."""
    created = cast("dict[str, Any]", project.call("create_part", {"name": name}))
    applied = cast(
        "dict[str, Any]",
        project.call(
            "write_part",
            {"name": name, "expected_hash": created["content_hash"], "script": script},
        ),
    )
    assert applied["applied"] is True, applied


def build_ok(project: Project, name: str) -> dict[str, Any]:
    """``build_part`` that must have succeeded; returns the tool result."""
    result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
    assert result["status"] == "ok", result
    return result


def source_map_of(cad: CadOps, store: Any, part: str) -> Mapping[str, Any]:
    """The published source map of ``part``'s current build (§8 evidence)."""
    current = cad.current_build(part)
    assert current is not None and current.source_map_ref is not None
    blob = store.blobs.get(blob_hash_of_ref(current.source_map_ref))
    return cast("Mapping[str, Any]", json.loads(blob.decode("utf-8")))


def pdf_bytes(*pages: str) -> bytes:
    """A real PDF, so the extractor under test is the real one."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    sheet = canvas.Canvas(buf)
    for text in pages:
        sheet.drawString(72, 720, text)
        sheet.showPage()
    sheet.save()
    return buf.getvalue()


def png_bytes(width: int = 12, height: int = 12) -> bytes:
    """A real PNG, so the §5 image header gate is the real one."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()
