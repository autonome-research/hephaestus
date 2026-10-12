# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Prepare retained local image artifacts for the explicit development launcher.

No CAD workload or server is started; no image is published. Retention is explicit
and recorded, unlike the smoke which removes its temporary tags. Every launch
still requires real fresh probes of both immutable references.
"""

from __future__ import annotations

import argparse
import signal
from pathlib import Path

from macos_milestone_smoke import ROOT, report_path
from macos_renderer_check import RendererSmoke
from macos_workspace import document
from macos_workspace_dependencies import preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    args = parser.parse_args()
    wheels = args.wheelhouse.resolve(strict=True)
    if not wheels.is_relative_to(ROOT) or not wheels.is_dir():
        parser.error("wheelhouse must be inside this checkout")
    smoke = RendererSmoke(report_path(args.report_dir), wheels)
    renderer = RendererSmoke(smoke.directory / "renderer", wheels)
    retain = False

    def interrupted(signum, frame):
        del frame
        raise KeyboardInterrupt(f"received {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        smoke.preflight()
        preflight(smoke)
        from macos_prepare_executor import prepare as executor_image
        from macos_prepare_renderer import prepare as renderer_image
        from macos_probe_executor import resolve_image

        smoke.native_dependencies()
        executor = resolve_image(smoke, executor_image(smoke))
        renderer.docker = smoke.docker
        renderer.native_dependencies()
        render = resolve_image(renderer, renderer_image(renderer), role="renderer")
        document(smoke.directory / "images.json", {"executor": executor, "renderer": render})
        retain = True
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        try:
            renderer.cleanup(retain_images=retain)
        finally:
            smoke.cleanup(retain_images=retain)
    if any(s.report["checks"]["cleanup"]["status"] != "passed" for s in (smoke, renderer)):
        return 1
    print("Local image artifacts: " + str(smoke.directory / "images.json"))
    print(
        "Not acceptance. Launch performs fresh probes; "
        "remove only listed retained tags when finished."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
