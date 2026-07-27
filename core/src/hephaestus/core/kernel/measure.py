"""Compatibility facade: this module moved to :mod:`hephaestus.geom.measure`.

Measurement (interference, clearance, distance, mass, section) is now a
geometry service usable without the executor; see :mod:`hephaestus.geom`.

Compatibility only — re-exports the moved public surface unchanged so existing
``hephaestus.core.kernel.measure`` imports keep working. New code should import from
:mod:`hephaestus.geom.measure`.
"""

from hephaestus.geom.measure import (
    OVERLAP_EPS_MM3,
    clearance,
    distance,
    interference,
    interference_pairs,
    mass,
    section,
)

__all__ = [
    "OVERLAP_EPS_MM3",
    "clearance",
    "distance",
    "interference",
    "interference_pairs",
    "mass",
    "section",
]
