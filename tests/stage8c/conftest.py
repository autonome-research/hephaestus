"""Fixtures for the Gate G8C (assemblies and constraints) evidence suite.

One fixture shape, two sizes. ``assembly`` carries the whole cast (every 8C kind
needs a partner of the right class); ``pair`` is the ``base``/``lid`` register
fit alone, used by the clauses that drive a termination review — the reviewer
renders every part in the project by rule, and rendering three parts nobody
constrains would buy nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _g8c import build_all, make_assembly_project
from hephaestus.testing.tools_fixture import Project


@pytest.fixture
def assembly(tmp_path: Path) -> Iterator[Project]:
    """The whole cast, scripts on disk, nothing built yet."""
    project = make_assembly_project(tmp_path / "proj")
    try:
        yield project
    finally:
        project.close()


@pytest.fixture
def built(assembly: Project) -> Project:
    """The same, with every buildable part published (``never_built`` is not)."""
    build_all(assembly, "base", "lid", "bracket", "plug", "pin")
    return assembly


@pytest.fixture
def empty(tmp_path: Path) -> Iterator[Project]:
    """A project with the shared interface constants and no parts at all.

    For the scripted-run clauses, where authoring the two parts through
    ``create_part``/``write_part`` is part of what is being asserted.
    """
    project = make_assembly_project(tmp_path / "proj", parts=())
    try:
        yield project
    finally:
        project.close()


@pytest.fixture
def pair(tmp_path: Path) -> Iterator[Project]:
    """Just the mating pair: ``base`` + ``lid``, both built."""
    project = make_assembly_project(tmp_path / "proj", parts=("base", "lid"))
    try:
        build_all(project, "base", "lid")
        yield project
    finally:
        project.close()
