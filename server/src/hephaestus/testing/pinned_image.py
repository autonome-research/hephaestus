# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Recorded pinned-image measurements, and what "the pinned image" means.

``MESH_INGEST.md`` §8 Tier 3 and mission rule 4 (``mission_plan.md``): four
Stage 12 clauses (G12A.19, G12B.25, G12B.33, G12C.45) say their numbers are
measured **in the pinned image**, and the constants those clauses enforce are to
be *set from* that measurement. A measurement is only evidence if it says which
world it was taken in, so it is archived beside the suite that reads it with a
stamp naming that world, and this module is the one place that writes the stamp
and the one place that refuses a record without one.

**Why a record rather than "the CI lane will do it".** A gate is a command
(mission rule 1). A constant justified by a lane that has not run is a constant
justified by a promise, and the repair pass before this one shipped exactly
that. What ships now is a committed measurement plus an assertion that the
constant stands in a stated relation to it, so moving the constant away from the
image's own number fails the gate, and re-taking the measurement in CI
(``scripts/stage12_pinned_measure.py --check``) fails the lane if the recorded
number no longer holds.

**What counts as "the pinned image", stated exactly.** ``ci.yml`` consumes
``ghcr.io/…/hephaestus-ci`` by digest, and that digest is the pin. It is not
resolvable from every machine that must be able to reproduce a measurement — a
private GHCR package answers ``403`` without ``read:packages`` — so a record may
also be taken in a container built from the repository's own unchanged
``docker/ci/Dockerfile``, whose ``FROM`` is itself digest-pinned. That is the
route ``docker/ci/README.md`` documents ("the base is digest-pinned, so this
reproduces the CI renderer") and the route commit ``f3a4d42`` took to re-record
the G1/G4 goldens "inside the pinned CI image". Either way the record carries:

* ``image_digest`` — measured from ``HEPHAESTUS_CI_IMAGE_DIGEST``, so a record
  taken on a developer host says ``unpinned`` and is REFUSED here rather than
  quietly passing for an image measurement;
* ``image_ref`` — the human name of the image, so a reader can tell the GHCR
  pull from the local build;
* ``base_image`` — the ``FROM`` line's own digest, which :func:`load_pinned`
  re-reads from ``docker/ci/Dockerfile`` at test time and compares. This is what
  makes the local-build route checkable on a machine that cannot reach GHCR: the
  record is tied to the image *definition*, and a base bump invalidates every
  record that did not move with it.

Not product API. It lives in ``hephaestus.testing`` for the reason that package
exists: three suites need the same loader, and reaching across test directories
with ``sys.path`` tricks is worse.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

__all__ = [
    "CLOCK_HEADROOM",
    "PINNED_RECORD_NAME",
    "PinnedMeasurementError",
    "PinnedRecord",
    "base_image_digest",
    "load_pinned",
    "pinned_stamp",
    "write_pinned",
]

#: How much slower than the recorded image measurement a wall clock may run
#: before it stops being "a loaded runner" and starts being a regression.
#:
#: One number, used in two places on purpose: a *ceiling* is derived from the
#: recorded measurement with this headroom (the budget a gate clause enforces),
#: and ``scripts/stage12_pinned_measure.py --check`` re-measures against the same
#: band. Two independently chosen factors would eventually disagree about what a
#: regression is. Three is the band that separates a shared CI runner from an
#: implementation that went quadratic in the input: the first costs a small
#: multiple, the second costs orders of magnitude — and mission rule 4's own
#: reason for making performance a gate is the second, not the first. It is also
#: the largest band that keeps every ceiling derived from it **below** the
#: ceiling that stood before the image measured anything (``tests/stage12a``'s
#: ``PRE_MEASUREMENT_CEILING_S``): budgets tighten, never loosen, and a
#: re-measurement that raised one would be a regression wearing a measurement's
#: clothes.
CLOCK_HEADROOM: Final[float] = 3.0

#: The file name a suite's recorded pinned-image measurement takes, inside that
#: suite's own ``evidence/`` directory. One per suite, because a suite is a gate
#: command and a gate that reads another gate's directory is coupling.
PINNED_RECORD_NAME: Final[str] = "pinned_measurements.json"

_FROM_LINE = re.compile(r"^FROM\s+(\S+)\s*$", re.MULTILINE)


class PinnedMeasurementError(AssertionError):
    """A pinned-image measurement is missing, unstamped, or from another world.

    An ``AssertionError`` on purpose, like
    ``_g12b_goldens.SewGoldenProvenanceError``: the correct response is to
    re-take the measurement in the image and commit it, and the failure should
    read like a demand for that rather than like a missing file.
    """


@dataclass(frozen=True)
class PinnedRecord:
    """One suite's archived pinned-image measurements plus the world's stamp."""

    image_digest: str
    image_ref: str
    base_image: str
    occt_version: str
    python: str
    spec: str
    measurements: dict[str, Any]

    def number(self, key: str) -> float:
        """One recorded figure, or a refusal naming the key that is missing.

        Never a default. The whole point of the record is that a constant is set
        from a number somebody measured; a defaulting reader would let a
        constant be justified by a key that was never recorded.
        """
        value = self.measurements.get(key)
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise PinnedMeasurementError(
                f"the pinned-image record has no numeric {key!r} (it is {value!r}). "
                "Re-take it with `scripts/stage12_pinned_measure.py --write` inside "
                "the pinned image and commit the result."
            )
        return float(value)


def base_image_digest(repo: Path) -> str:
    """The ``FROM`` digest of ``docker/ci/Dockerfile``, READ rather than copied.

    A record that named the base image as a string somebody kept up to date
    would drift the first time the base moved. Reading it here means a base bump
    invalidates every record that did not move with it, which is
    ``verification.md``'s golden-provenance rule applied to a measurement.
    """
    dockerfile = repo / "docker" / "ci" / "Dockerfile"
    match = _FROM_LINE.search(dockerfile.read_text(encoding="utf-8"))
    if match is None:
        raise PinnedMeasurementError(f"{dockerfile} declares no FROM line to pin against")
    return match.group(1)


def pinned_stamp(repo: Path, *, image_ref: str | None = None) -> dict[str, str]:
    """The world this process is running in, MEASURED — or a refusal.

    Refuses outright when no pinned image declared itself, which is the guard
    that stops a developer-host run from being archived as an image measurement.
    """
    from hephaestus.core.mesh_solid import UNPINNED_IMAGE, image_digest, occt_version

    digest = image_digest()
    if digest == UNPINNED_IMAGE:
        raise PinnedMeasurementError(
            "this process is not running in a pinned image: "
            "HEPHAESTUS_CI_IMAGE_DIGEST is unset, so image_digest() reads "
            f"{UNPINNED_IMAGE!r}. A measurement taken here is a developer-host "
            "measurement and may not be archived as an image one (MESH_INGEST.md §8, "
            "mission rule 4). Run it in the pinned image — `ci.yml` job "
            "`stage12 measurements (pinned image)`, or the local build "
            "`docker/ci/README.md` documents — and export the digest."
        )
    return {
        "image_digest": digest,
        "image_ref": image_ref or os.environ.get("HEPHAESTUS_CI_IMAGE_REF", "(unnamed)"),
        "base_image": base_image_digest(repo),
        "occt_version": occt_version(),
        "python": sys.version.split()[0],
    }


def write_pinned(
    evidence_dir: Path,
    repo: Path,
    *,
    spec: str,
    measurements: dict[str, Any],
    image_ref: str | None = None,
) -> Path:
    """Archive one suite's pinned-image measurements, stamped with its world."""
    stamp = pinned_stamp(repo, image_ref=image_ref)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / PINNED_RECORD_NAME
    path.write_text(
        json.dumps({**stamp, "spec": spec, "measurements": measurements}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def load_pinned(evidence_dir: Path, repo: Path) -> PinnedRecord:
    """The archived record, or a refusal naming which half of the pin failed."""
    from hephaestus.core.mesh_solid import UNPINNED_IMAGE

    path = evidence_dir / PINNED_RECORD_NAME
    if not path.exists():
        raise PinnedMeasurementError(
            f"no pinned-image measurement is archived at {path}. The clause that reads "
            "it says its constant is set from the image's own measurement, and there "
            "is none. Take it with `scripts/stage12_pinned_measure.py --write` inside "
            "the pinned image."
        )
    raw = cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
    missing = {"image_digest", "image_ref", "base_image", "occt_version", "python", "spec"} - set(
        raw
    )
    if missing:
        raise PinnedMeasurementError(
            f"{path} is missing {sorted(missing)}: a measurement that cannot say which "
            "world it was taken in is not evidence for a clause about that world."
        )
    if raw["image_digest"] == UNPINNED_IMAGE:
        raise PinnedMeasurementError(
            f"{path} records image_digest={UNPINNED_IMAGE!r} — it was taken outside a "
            "pinned image and cannot satisfy a clause that says 'in the pinned image'."
        )
    expected_base = base_image_digest(repo)
    if raw["base_image"] != expected_base:
        raise PinnedMeasurementError(
            f"{path} was recorded against base image {raw['base_image']!r} and "
            f"docker/ci/Dockerfile now declares {expected_base!r}. The image definition "
            "moved under the record: re-take the measurement in the rebuilt image and "
            "commit it with the bump (MESH_INGEST.md §8 Tier 3, verification.md)."
        )
    measurements = raw.get("measurements")
    if not isinstance(measurements, dict):
        raise PinnedMeasurementError(f"{path} carries no measurements mapping")
    return PinnedRecord(
        image_digest=str(raw["image_digest"]),
        image_ref=str(raw["image_ref"]),
        base_image=str(raw["base_image"]),
        occt_version=str(raw["occt_version"]),
        python=str(raw["python"]),
        spec=str(raw["spec"]),
        measurements=cast("dict[str, Any]", measurements),
    )
