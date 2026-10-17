# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Create a new independently authored local diagnostic project, never execute CAD."""

from __future__ import annotations

import argparse
from pathlib import Path

from macos_milestone_smoke import report_path
from macos_workspace import document
from macos_workspace_check import diagnostic_requirements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    root: Path = report_path(args.directory)
    from macos_executor_live import TWO_SOLIDS

    root.mkdir(parents=True, mode=0o700)
    (root / "parts").mkdir()
    (root / "hephaestus.toml").write_text('name = "experimental-mac-demo"\nunits = "mm"\n')
    (root / "parts/two_solids.py").write_text(TWO_SOLIDS)
    document(root / "requirements.json", diagnostic_requirements())
    print(str(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
