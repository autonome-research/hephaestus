"""Compatibility facade: this module moved to :mod:`hephaestus.geom.kerf`.

Kerf resolution and compensation are now a geometry service usable without
the executor; see :mod:`hephaestus.geom`.

Compatibility only — re-exports the moved public surface unchanged so existing
``hephaestus.core.kerf`` imports keep working. New code should import from
:mod:`hephaestus.geom.kerf`.
"""

from hephaestus.geom.kerf import (
    KERF_UNCOMPENSATED,
    KerfDecision,
    KerfRefusal,
    KerfSource,
    kerf_compensated_shape,
    resolve_kerf,
)

__all__ = [
    "KERF_UNCOMPENSATED",
    "KerfDecision",
    "KerfRefusal",
    "KerfSource",
    "kerf_compensated_shape",
    "resolve_kerf",
]
