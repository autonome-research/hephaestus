"""Regenerate the STEP ingest fixtures (INGEST.md §1).

Run from the repo root: ``uv run python core/tests/fixtures/step/generate.py``.

The outputs are COMMITTED rather than generated per test run: OCCT stamps a
timestamp into the STEP header, so a regenerated file would have different
bytes — and the whole point of these fixtures is that identical bytes hash
identically across processes and machines.

- ``plate.step``       — a 40 x 20 x 5 mm plate (the happy-path import).
- ``plate_taller.step``— the same plate at 8 mm: a REPLACEMENT whose top face
                         has moved, for the §5.3 drift-fingerprint test.
- ``boss.step``        — a Ø10 x 10 mm cylinder, for mixed imported+native and
                         multi-import builds.
"""

from pathlib import Path

from build123d import Box, Cylinder
from hephaestus.geom.step_io import write_step

HERE = Path(__file__).resolve().parent


def main() -> None:
    write_step(Box(40, 20, 5), HERE / "plate.step")
    write_step(Box(40, 20, 8), HERE / "plate_taller.step")
    write_step(Cylinder(5, 10), HERE / "boss.step")


if __name__ == "__main__":
    main()
