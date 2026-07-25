"""Scaffolding for the minimal-but-real project every bridge harness starts from.

A Hephaestus project is a directory, not an object: a ``hephaestus.toml``
manifest, a ``globals.py`` project namespace, and ``parts/`` + ``checks/``
directories. :func:`scaffold_project` writes that shape and nothing else, so a
test that needs an *empty* project gets one the real loader accepts. Fixtures
that need populated parts use :mod:`hephaestus.testing.tools_fixture` instead.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["scaffold_project"]


def scaffold_project(
    root: Path,
    *,
    name: str = "heph",
    globals_src: str = "PARAMS = {}\n",
) -> Path:
    """A minimal but real Hephaestus project: manifest + globals + parts/checks."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    (root / "globals.py").write_text(globals_src, encoding="utf-8")
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    return root
