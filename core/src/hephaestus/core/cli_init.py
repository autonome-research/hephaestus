"""``heph init [dir]`` — scaffold the four-file project convention.

``repo_conventions.md`` §"Repository conventions" records the user-facing
design-project convention: a Hephaestus project is an ordinary directory laid
out as ``hephaestus.toml``, ``globals.py``, ``parts/``, and a ``.gitignore``
ignoring ``.heph/``. This verb writes exactly that shape (plus ``checks/`` with
the safe cross-part template shared with the model-facing
``create_project_check`` tool), so a new project starts from the same files a
fixture or the docs describe — with one commented, buildable example part, so
``heph build example`` succeeds immediately after ``heph init``.

The verb refuses a non-empty target with the named ``init_target_not_empty``
error: scaffolding never overwrites, which also makes a second ``heph init`` of
the same directory a refusal rather than a silent no-op.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

from hephaestus.core.checks.template import check_template
from hephaestus.core.errors import HephaestusError


class InitTargetNotEmptyError(HephaestusError):
    """``heph init`` refused: the target directory already has entries.

    Scaffolding never overwrites — pointing ``heph init`` at a populated
    directory (including an already-initialized project) is refused by name,
    listing what is already there.
    """

    code = "init_target_not_empty"

    def __init__(self, message: str, *, target: Path, entries: tuple[str, ...]) -> None:
        super().__init__(message)
        self.target = target
        self.entries = entries


#: ``globals.py`` starts empty on purpose: project-shared values are §4 design
#: decisions, not boilerplate.
GLOBALS_STUB: Final[str] = (
    "# Project-shared values (hc namespace): declare PARAMS and helpers here.\n"
)

#: A commented, buildable example part — `heph build example` works untouched.
EXAMPLE_PART: Final[str] = """\
# Example part scaffolded by `heph init` — edit or replace it.
#
# A part script declares its tunables in PARAMS (read back as `p.<name>`),
# assigns geometry to `part.geometry`, and labels solids so checks and other
# parts can address them ("example/example_plate").
PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

plate = Box(p.width, 20.0, 6.0)
plate.label = "example_plate"
part.geometry = plate
part.description = "Example plate scaffolded by heph init"
part.process = "cnc_router"
"""

GITIGNORE: Final[str] = "# Hephaestus build store (content-addressed, rebuildable).\n.heph/\n"


def scaffold(target: Path) -> tuple[Path, str]:
    """Write the project skeleton into ``target``; returns ``(root, name)``.

    ``target`` may be absent (it is created) but must be empty if present —
    otherwise :class:`InitTargetNotEmptyError` is raised and nothing is
    written.
    """
    root = target.resolve()
    if root.exists():
        if not root.is_dir():
            raise InitTargetNotEmptyError(
                f"init target {root} exists and is not a directory",
                target=root,
                entries=(root.name,),
            )
        entries = tuple(sorted(entry.name for entry in root.iterdir()))
        if entries:
            listed = ", ".join(entries[:8]) + (", …" if len(entries) > 8 else "")
            raise InitTargetNotEmptyError(
                f"init target {root} is not empty ({listed}); "
                "heph init never overwrites — point it at a new or empty directory",
                target=root,
                entries=entries,
            )
    name = root.name
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_STUB, encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    parts = root / "parts"
    parts.mkdir()
    (parts / "example.py").write_text(EXAMPLE_PART, encoding="utf-8")
    checks = root / "checks"
    checks.mkdir()
    (checks / "project.py").write_text(check_template("scaffolded by heph init"), encoding="utf-8")
    return root, name


def _cmd_init(args: argparse.Namespace) -> int:
    root, name = scaffold(Path(str(args.directory)))
    print(f"initialized Hephaestus project '{name}' at {root}")
    scaffolded = (
        "hephaestus.toml",
        "globals.py",
        "parts/example.py",
        "checks/project.py",
        ".gitignore",
    )
    for rel in scaffolded:
        print(f"  {rel}")
    print("next: cd there and run `heph build example`")
    return 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    init = sub.add_parser("init", help="scaffold a new Hephaestus project directory")
    init.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="target directory (default: the current directory); must be empty or absent",
    )
    init.set_defaults(func=_cmd_init)
