# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The repository's Hypothesis profile — a pytest plugin, loaded at startup.

J-mirrors-and-dx-13 has two halves, and the per-site half is the weaker one.
Hypothesis's stock ``deadline`` is 200 ms **per example**, and it measures the
runner rather than the property: a property that is correct on an idle laptop
reds the build on a loaded CI box, on a cold import, or when a sibling suite is
saturating the cores. Spelling ``deadline=None`` at each ``@settings`` site
fixes the sites that exist today and does nothing for the site somebody adds
tomorrow, which is why the ledger asks for a repository PROFILE: with one
registered and loaded, the stock default stops mattering and a ``@settings``
block that names only other keywords inherits ``deadline=None`` from here.

Wired up in ``pyproject.toml`` as ``-p hephaestus.testing.hypothesis_profile``,
so it is imported before the first test module is. The ``-p`` form is what makes
it repository-wide: a ``conftest.py`` is loaded only for the directory below it,
and the two directories that hold Hypothesis tests today (``core/tests`` and
``opstore/tests``) are two of five ``testpaths`` — a per-directory conftest would
have to be copied, which is the four-copies defect this same audit found in the
free-port helpers.

Living inside :mod:`hephaestus.testing` is why that package's re-exports are
lazy: a ``-p`` plugin is imported at startup, so an eager package body would
have charged every pytest session in the repository ~4.4 s for the CAD kernel.
The marginal cost of this module is zero — Hypothesis ships its own pytest
plugin via an entry point, so ``hypothesis`` is already imported by the time
pytest reads ``-p``.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings

#: Exported so a test can assert the profile is the LOADED one rather than
#: merely registered — registering without loading is the silent-no-op failure
#: this item is about.
PROFILE = "hephaestus"

settings.register_profile(
    PROFILE,
    # The wall clock is not evidence about a property. See the module docstring.
    deadline=None,
    # The same measurement at data-generation granularity: `too_slow` fires when
    # generating examples is slow, which on a loaded runner says nothing about
    # the strategy. Every other health check is real signal and stays on.
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(PROFILE)
