# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Private fixture directories; no inherited HOME/cache or symlink aliases.

The fixture is under sole harness control, not an adversarial concurrent host.
Existing ancestors are inspected; only fresh leaves are admitted as owned paths.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


def private_directory(path: Path, root: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    if (
        not path.is_relative_to(root)
        or path == root
        or ".." in path.parts
        or any(ord(c) < 32 for c in str(path))
    ):
        raise ValueError("owned directory must be a new descendant of the fixture root")
    for ancestor in reversed((path, *path.parents)):
        if ancestor.exists() or ancestor.is_symlink():
            info = ancestor.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("owned directory has a non-directory/symlink component")
            if ancestor.is_relative_to(root) and info.st_uid != os.getuid():
                raise ValueError("owned directory has a foreign owner")
        else:
            if not ancestor.is_relative_to(root):
                raise ValueError("fixture root must exist")
            ancestor.mkdir(mode=0o700)
            if ancestor == path:
                return path
    raise ValueError("owned directory must be new; existing paths are not adopted")
