# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The per-file license header check.

Stage 7H ships "Apache-2.0 headers" (`mission_plan.md`). The root `LICENSE`
already licenses the repository and Apache-2.0 itself requires nothing per file,
so the question this tool answers is narrower than "is everything labelled":
**which files get read detached from the tree, with no `LICENSE` beside them to
answer the question for them?** Those files, and only those, must say it
themselves. `CONTRIBUTING.md` §"Licensing and file headers" is the normative
statement of the rule; this script is its executable form.

Required — read or shipped away from the repository:

- standalone documents: ``*.md`` at the repository root, and everything under
  ``docs/``;
- build, packaging and release machinery: ``scripts/*.py``,
  ``*/hatch_build.py``, ``packaging/pyproject.toml``.

Not required on source modules. They ship inside wheels whose metadata carries
the license, and the repository's existing modules do not carry headers — a
convention that made itself retroactively false would be a claim about a
repository we do not have. A header on a source module is welcome and this tool
will never ask for one, nor strip one.

Nothing else is scanned at all. That is deliberate: `registries/**` is pinned by
a Merkle digest over its bytes, so a comment there is a version bump that breaks
every consumer's pin; `corpus/**`, `spikes/**`, recorded fixtures and
`bench/results/**` are evidence, and reformatting evidence edits it. Because the
required set is an explicit enumeration rather than a walk-with-exclusions, a new
evidence directory cannot be swept in by forgetting to exempt it.

Usage::

    uv run python scripts/license_headers.py --check   # exit 1 on a missing header
    uv run python scripts/license_headers.py --apply   # insert the missing ones
    uv run python scripts/license_headers.py --list    # which files are governed
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: The two lines, in the order they must appear.
COPYRIGHT_LINE: Final[str] = "Copyright 2026 The Hephaestus Authors"
SPDX_LINE: Final[str] = "SPDX-License-Identifier: Apache-2.0"

#: A header must appear at the top of the file, not buried in it. Two lines of
#: slack absorb a shebang and a blank line; more than that is not a header.
_HEADER_WINDOW: Final[int] = 6

_HASH_HEADER: Final[str] = f"# {COPYRIGHT_LINE}\n# {SPDX_LINE}\n"
_MARKDOWN_HEADER: Final[str] = f"<!--\n{COPYRIGHT_LINE}\n{SPDX_LINE}\n-->\n"


def governed_files(root: Path) -> list[Path]:
    """Every file the header rule applies to, sorted, as absolute paths.

    An explicit enumeration — see the module docstring for why this is not a
    walk with an exclusion list.
    """
    found: set[Path] = set()

    # Standalone documents: root-level Markdown and the whole docs/ set.
    found.update(p for p in root.glob("*.md") if p.is_file())
    found.update(p for p in root.glob("docs/**/*.md") if p.is_file())

    # Build, packaging and release machinery.
    found.update(p for p in root.glob("scripts/*.py") if p.is_file())
    found.update(p for p in root.glob("*/hatch_build.py") if p.is_file())
    packaging_pyproject = root / "packaging" / "pyproject.toml"
    if packaging_pyproject.is_file():
        found.add(packaging_pyproject)

    return sorted(found)


def has_header(text: str) -> bool:
    """True if both header lines appear, in order, near the top of ``text``.

    Comment syntax is not matched: the check is that the file *says* it, so a
    Markdown ``<!-- -->`` block, a ``#`` comment and a docstring all satisfy it.
    Requiring an exact rendering would fail files whose generator emits its own
    equally valid wrapper.
    """
    head = text.splitlines()[:_HEADER_WINDOW]
    for index, line in enumerate(head):
        if COPYRIGHT_LINE in line:
            return any(SPDX_LINE in later for later in head[index:])
    return False


def _header_for(path: Path) -> str:
    return _MARKDOWN_HEADER if path.suffix == ".md" else _HASH_HEADER


def apply_header(path: Path) -> bool:
    """Insert the header into ``path`` if it lacks one. True if the file changed.

    A shebang keeps the first line; everything else is pushed down. An existing
    header is left exactly as it is, including a differently worded one — this
    tool adds a missing statement, it does not rewrite an author's.
    """
    text = path.read_text(encoding="utf-8")
    if has_header(text):
        return False
    header = _header_for(path)
    if text.startswith("#!"):
        shebang, _, rest = text.partition("\n")
        path.write_text(f"{shebang}\n{header}\n{rest}", encoding="utf-8")
    else:
        path.write_text(f"{header}\n{text}", encoding="utf-8")
    return True


def missing(files: list[Path]) -> Iterator[Path]:
    """The governed files that carry no header, in the order given."""
    for path in files:
        if not has_header(path.read_text(encoding="utf-8")):
            yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="license_headers", description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 if a header is missing")
    mode.add_argument("--apply", action="store_true", help="insert missing headers in place")
    mode.add_argument("--list", action="store_true", help="list the governed files")
    args = parser.parse_args(argv)

    files = governed_files(REPO_ROOT)

    if args.list:
        for path in files:
            print(path.relative_to(REPO_ROOT))
        return 0

    if args.apply:
        changed = [path for path in files if apply_header(path)]
        for path in changed:
            print(f"license_headers: added header to {path.relative_to(REPO_ROOT)}")
        print(f"license_headers: {len(changed)} file(s) updated, {len(files)} governed")
        return 0

    absent = list(missing(files))
    for path in absent:
        print(f"{path.relative_to(REPO_ROOT)}: missing Apache-2.0 header", file=sys.stderr)
    if absent:
        print(
            f"\nlicense_headers: {len(absent)} of {len(files)} governed file(s) "
            "lack a header; run `uv run python scripts/license_headers.py --apply`",
            file=sys.stderr,
        )
        return 1
    print(f"license_headers: {len(files)} governed files, all carry the header")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
