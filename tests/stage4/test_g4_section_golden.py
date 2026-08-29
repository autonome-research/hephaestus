# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G4.7's golden: the section plate reproduces committed **server** pixels.

Its own module because it is **renderer-pinned**, and this repository already
has a settled policy for renderer-pinned suites: ``.github/workflows/ci.yml``
excludes ``tests/render`` from every-PR CI by name, because "a stock
ubuntu-latest image ships a different Mesa than the one the goldens were
generated on, so the suite would fail on rasterizer drift rather than on a real
regression". This assertion is in exactly that class, so it is separated from
the rest of ``tests/stage4`` — which is not renderer-pinned and does run on
every PR — instead of dragging the whole Stage 4 suite into the deferral.

``INTERFACE.md`` §14 says the browser gate runs "inside the same pinned CI
container image as ``tests/render``". **That image landed 2026-08-28**
(``docker/ci/Dockerfile``, built and pushed by ``ci-image.yml``, consumed BY
DIGEST), so this module is no longer deferred to nowhere: ``ci.yml``'s
``render goldens (pinned image)`` job runs it by name, alongside
``tests/render`` and ``pnpm --dir web test:e2e``, on the one renderer its
sidecar was baselined against. The stock-runner job still excludes it by name.

Consequently this module **cannot pass on a developer host** whose Mesa differs
from the image's, and that is the design, not a defect: it fails **by name** on
a renderer it was not baselined against rather than skipping, because a suite
that quietly passed on the wrong rasterizer would be asserting nothing. Run it
where it belongs — inside the pinned image, per ``docker/ci/README.md``, whose
recipe keeps the container from writing build state into the mounted worktree —
or run the rest of Stage 4 with CI's own
``--ignore=tests/stage4/test_g4_section_golden.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from hephaestus.testing.workspace_fixture import (
    SECTION_GOLDEN_DIR,
    SECTION_GOLDEN_SPEC,
    SECTION_PLANE,
    SECTION_VIEW,
    SUBJECT_PART,
    stage4_goldens,
)


def test_the_section_plate_reproduces_the_committed_golden(workspace: Any) -> None:
    """§5.3: the gated section render is server pixels, matched against a golden.

    The browser cannot choose a render size, so the golden is baselined at the
    route's own size and this test asks the route for the same plane and view.
    A **renderer mismatch is reported by name** rather than skipped: a golden is
    valid only for its ``(container image, renderer version)`` pair
    (``verification.md`` Tier 2), and a suite that quietly passed on the wrong
    rasterizer would be asserting nothing.
    """
    from hephaestus.core.render.goldens import renderer_string

    golden_dir = stage4_goldens() / SECTION_GOLDEN_DIR
    stem = f"{SECTION_GOLDEN_SPEC.name}_{SECTION_VIEW}_section"
    sidecar = json.loads((golden_dir / f"{stem}.json").read_text(encoding="utf-8"))
    if sidecar["gl_renderer"] != renderer_string():
        pytest.fail(
            "the section golden was baselined on "
            f"{sidecar['gl_renderer']!r} and this machine renders with "
            f"{renderer_string()!r}. Re-baseline inside the pinned CI image with "
            "`uv run python scripts/record_workspace_transcript.py` (INTERFACE.md §14)."
        )

    build = workspace.get(f"/parts/{SUBJECT_PART}/build")
    document = workspace.post(
        f"/parts/{SUBJECT_PART}/inspect",
        {
            "views": [SECTION_VIEW],
            "channel": "section",
            "section_plane": SECTION_PLANE,
            "artifact_ref": build["artifact_ref"],
        },
    )
    assert document["status"] == "ok", document
    served = workspace.bytes(document["render_artifact_refs"][0])
    assert "sha256:" + hashlib.sha256(served).hexdigest() == sidecar["png_sha256"]
    assert served == (golden_dir / f"{stem}.png").read_bytes()
