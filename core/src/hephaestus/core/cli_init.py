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
the same directory a refusal rather than a silent no-op. A target that cannot
be created at all is refused with exit 2 and, like every other refusal here,
writes nothing: the scaffold is staged in a sibling directory and moved into
place, so a partial project is not representable (ledger B-10).
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Final

from hephaestus.core.checks.template import check_template
from hephaestus.core.cli_errors import guard, usage_from_oserror
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


def _write_tree(root: Path, name: str) -> None:
    """Write the six scaffolded files into an existing, empty ``root``."""
    (root / "hephaestus.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_STUB, encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    parts = root / "parts"
    parts.mkdir()
    (parts / "example.py").write_text(EXAMPLE_PART, encoding="utf-8")
    checks = root / "checks"
    checks.mkdir()
    (checks / "project.py").write_text(check_template("scaffolded by heph init"), encoding="utf-8")


def _staging_dir(root: Path) -> Path | None:
    """A sibling temporary directory to build the scaffold in, or ``None``.

    ``None`` means the sibling could not be made — ``heph init`` with no
    argument targets the working directory, whose *parent* may well not be
    writable — and the caller falls back to guarded in-place writes.

    Missing intermediate directories are created first (``heph init a/b/c`` has
    always worked), so the staging path is available there too and only the
    *target* has to be all-or-nothing; the parents are ``mkdir -p`` semantics
    and stay behind either way.
    """
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f".{root.name}.", suffix=".heph-init", dir=root.parent))
    except OSError:
        return None


def scaffold(target: Path) -> tuple[Path, str]:
    """Write the project skeleton into ``target``; returns ``(root, name)``.

    ``target`` may be absent (it is created) but must be empty if present —
    otherwise :class:`InitTargetNotEmptyError` is raised and nothing is
    written.

    "Nothing is written" holds for OS failures too (ledger B-10). The scaffold
    is six writes; before this, a failure on the fourth left a *partial*
    project on disk — three files that look like a Hephaestus project and are
    not one, which the next ``heph init`` then refuses as "not empty", so the
    operator cannot even retry. The files are therefore written into a sibling
    temporary directory and moved into place once all six exist; an ``OSError``
    at any point removes the staging directory and propagates unchanged, so the
    caller can name the target in its refusal.
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
    staging = _staging_dir(root)
    if staging is None:
        # Fallback: no writable parent, so stage-and-rename is not available.
        # Still all-or-nothing where we can be — a directory this call created
        # is removed again on failure.
        created = not root.exists()
        try:
            root.mkdir(parents=True, exist_ok=True)
            _write_tree(root, name)
        except OSError:
            if created:
                shutil.rmtree(root, ignore_errors=True)
            raise
        return root, name
    try:
        _write_tree(staging, name)
        if root.exists():
            # The target is present and empty (the ladder above proved it):
            # move the contents in rather than replacing the directory, so an
            # existing inode, mount point or permission set is preserved.
            for entry in sorted(staging.iterdir()):
                entry.rename(root / entry.name)
            staging.rmdir()
        else:
            staging.rename(root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return root, name


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(str(args.directory))
    try:
        root, name = scaffold(target)
    except OSError as exc:
        # An unwritable or non-existent parent is bad usage, not a failed run:
        # exit 2 (docs/cli.md exit codes). The named ``init_target_not_empty``
        # refusal above stays exit 1 — that one ran and answered "no".
        raise usage_from_oserror(exc, subject=f"cannot create init target {target}") from exc
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
    init.set_defaults(func=guard(_cmd_init))
