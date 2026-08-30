# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The sew, under a ceiling (``MESH_INGEST.md`` §4.1, ``COMPARE.md`` §5).

``BRepBuilderAPI_Sewing`` is the first genuinely unbounded thing this stage
adds. Measured on the pinned kernel: 2004 triangles → 0.32 s, 4002 → 0.78 s,
19952 → 4.41 s — **196 → 221 µs per triangle, mildly superlinear**. A
100k-triangle limb scan is therefore 20-30 s of kernel work on its own, which
already exceeds the 30 s full-build budget at ``verification.md``'s Tier 1
performance list, and nothing about a scan bounds its triangle count from below
30 s.

So the sew runs where every other unbounded kernel operation in this project
runs: in a **killable spawned subprocess under a wall-clock ceiling**, the
``COMPARE.md`` §5 pattern reused rather than reinvented
(:func:`hephaestus.core.project_compare.bounded_solid_diff` is the sibling). A
ceiling kill is the named refusal :class:`MeshSewTimeout` — ``mesh_sew_timeout``
— and it is not empty-handed: it carries the §3 quality record and the bbox,
the facts the parent already had before the sew started, and names what was
lost. The caller gets signal it can act on, and the grind is not still burning a
core behind the refusal.

**Why a subprocess even inside the build worker.** ``COMPARE.md`` §5's own note
says the sandboxed worker does not bound its diffs, because the worker already
runs under ``RLIMIT_CPU`` and a parent wall-clock kill. That argument does not
carry here: the worker's CPU limit is 120 s and its wall clock 300 s, both far
*above* the budget a sew must fit inside, so they do not bound the sew usefully
— they bound the build. And the premise was measured rather than assumed:
``multiprocessing`` with the ``spawn`` start method was verified to work inside
the bubblewrap sandbox this project's builds run in (``--unshare-pid``,
``--tmpfs /tmp``, ``RLIMIT_NPROC`` 4096), so ``mesh_to_solid`` in a part script
gets the same ceiling a tool call would.

The geometry itself stays pure: :mod:`hephaestus.geom.mesh_solid` sews and
measures, unbounded, and knows nothing about processes. Process management is an
engine concern (``COMPARE.md``:121-123).
"""

from __future__ import annotations

import multiprocessing
import os
import time
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from hephaestus.core.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from multiprocessing.connection import Connection

    from hephaestus.geom.mesh import MeshQuality
    from hephaestus.geom.mesh_solid import SewReport
    from opstore.types import JSONValue

__all__ = [
    "LOST_SEW",
    "LOST_VALIDITY",
    "MESH_SEW_TIMEOUT_ENV",
    "MESH_SEW_TIMEOUT_S",
    "MeshSewTimeout",
    "bounded_sew_to_solid",
    "image_digest",
    "mesh_sew_timeout_s",
    "occt_version",
    "sew_provenance",
]

#: Wall-clock ceiling for ONE sew, process-killed with no retry. Chosen against
#: the §4.1 measurement rather than picked: 221 µs/triangle puts the
#: ``MESH_MAX_TRIANGLES`` worst case far beyond any ceiling worth waiting for,
#: so what this number actually buys is that a scan too heavy to sew says so on
#: a clock the operator controls instead of holding the build until the
#: sandbox's own 300 s wall kill takes the whole build with it. Env-overridable
#: via :data:`MESH_SEW_TIMEOUT_ENV` under the ``COMPARE.md`` §5 local-floor
#: pattern — an operator with a heavy scan and patience may raise it.
MESH_SEW_TIMEOUT_S: Final[float] = 120.0

#: Environment override for :data:`MESH_SEW_TIMEOUT_S` (seconds, float).
MESH_SEW_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_MESH_SEW_TIMEOUT_S"

#: The two halves a ceiling kill can lose, by cost order. The quality record and
#: the bbox are NOT here: the parent computed them during canonicalization, long
#: before the sew, which is exactly why the refusal can carry them.
LOST_SEW: Final[str] = "sew"
LOST_VALIDITY: Final[str] = "validity_gate"


def mesh_sew_timeout_s() -> float:
    """The effective sew ceiling: :data:`MESH_SEW_TIMEOUT_ENV` else the default."""
    raw = os.environ.get(MESH_SEW_TIMEOUT_ENV)
    if raw is None:
        return MESH_SEW_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return MESH_SEW_TIMEOUT_S


class MeshSewTimeout(ValidationError):
    """The sew subprocess hit its ceiling or died (``MESH_INGEST.md`` §4.1).

    Never empty-handed. ``partial`` carries the facts the parent held *before*
    the sew — the §3 quality record and the canonical bbox — and ``lost`` names
    what the kill cut off. A caller holding this knows its scan is admitted,
    knows every defect the canonicalizer measured in it, and knows that what it
    does not have is a solid; that is a different and far more actionable
    position than a dead session.
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_s: float,
        partial: dict[str, JSONValue],
        lost: tuple[str, ...],
    ) -> None:
        # The ``[code]`` suffix is derived from the reason, not written into the
        # raise site's prose — the ``MeshReadError`` /``MeshOperationError`` rule
        # applied to the one §10 operations code that is raised outside
        # ``geom``, so a search for the derived form finds every member of the
        # vocabulary and none of them can drift from its own message.
        reason = "mesh_sew_timeout"
        super().__init__(f"{message} [{reason}]", kind="contract")
        self.reason: str = reason
        self.timeout_s = timeout_s
        self.partial: dict[str, JSONValue] = partial
        self.lost: tuple[str, ...] = lost

    def to_json(self) -> dict[str, JSONValue]:
        """The refusal shape every surface carries (build error data, CLI ``--json``)."""
        return {
            "status": "mesh_sew_timeout",
            "reason": "mesh_sew_timeout",
            "message": self.message,
            "timeout_s": self.timeout_s,
            "partial": cast("JSONValue", self.partial),
            "lost": cast("JSONValue", list(self.lost)),
        }


def _sew_child(conn: Connection, blob_path: str, brep_path: str, source: str) -> None:
    """The spawned half: deserialize, sew, write the BRep, report the counts.

    The solid crosses back as OCCT's own lossless BRep text, so a completed sew
    is bit-for-bit the direct :func:`hephaestus.geom.mesh_solid.sew_to_solid`
    call's result — the ceiling changes when the caller gives up, never what it
    receives.
    """
    from hephaestus.geom.mesh import deserialize_mesh
    from hephaestus.geom.mesh_solid import sew_to_solid
    from hephaestus.geom.step_io import shape_to_brep

    try:
        vertices, faces, _factor = deserialize_mesh(Path(blob_path).read_bytes(), source=source)
        solid, report = sew_to_solid(vertices, faces, source=source)
    except BaseException as exc:
        conn.send(("refusal", f"{type(exc).__name__}: {exc}"))
        conn.close()
        return
    Path(brep_path).write_bytes(shape_to_brep(solid))
    conn.send(("report", report.to_json()))
    conn.close()


def bounded_sew_to_solid(
    blob: bytes,
    *,
    source: str,
    quality: MeshQuality,
    bbox_mm: Sequence[float],
    timeout_s: float | None = None,
    scratch: Path | None = None,
) -> tuple[Any, SewReport]:
    """Sew ``blob`` in a killable subprocess; ``(MeshDerivedSolid, SewReport)``.

    The validity gate is deliberately NOT applied here. This function answers
    "did the sew finish inside its ceiling"; :func:`~hephaestus.geom.mesh_solid.gate_sewn_solid`
    answers "is what it produced a solid this harness will hand out", and the
    two are different questions with different refusals — a sew that timed out
    tells the operator to raise a ceiling or decimate a scan, and one that
    produced an invalid solid tells them to stop trying to convert it at all.
    """
    import tempfile

    from hephaestus.geom.mesh_solid import MeshDerivedSolid, SewReport
    from hephaestus.geom.step_io import shape_from_brep

    if timeout_s is None:
        timeout_s = mesh_sew_timeout_s()
    partial: dict[str, JSONValue] = {
        "quality": cast("JSONValue", quality.to_json()),
        "bbox_mm": cast("JSONValue", [float(v) for v in bbox_mm]),
        "source_path": source,
    }
    with tempfile.TemporaryDirectory(prefix="heph-sew-", dir=scratch) as tmp:
        blob_path = Path(tmp) / "mesh.hmesh"
        brep_path = Path(tmp) / "sewn.brep"
        blob_path.write_bytes(blob)

        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_sew_child, args=(child, str(blob_path), str(brep_path), source))
        proc.start()
        child.close()

        outcome: tuple[str, Any] | None = None
        died = False
        cut_short = f"did not finish within {timeout_s:g}s and was killed"
        deadline = time.monotonic() + timeout_s
        try:
            while outcome is None and time.monotonic() < deadline:
                try:
                    if parent.poll(0.05):
                        kind, payload = parent.recv()
                        outcome = (str(kind), payload)
                    elif not proc.is_alive():
                        # Death, not a deadline — drain first, so a report that
                        # raced the exit is never misread as a crash.
                        if parent.poll(0.2):
                            kind, payload = parent.recv()
                            outcome = (str(kind), payload)
                        died = outcome is None
                        break
                except EOFError:
                    proc.join(5.0)
                    died = True
                    break
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join()
            parent.close()
        if died:
            cut_short = f"subprocess died (exit code {proc.exitcode})"
        if outcome is not None and outcome[0] == "report":
            report = SewReport(
                **cast("dict[str, Any]", _report_kwargs(outcome[1])),
            )
            shape = cast("Any", shape_from_brep(brep_path.read_bytes(), source=source))
            solid = MeshDerivedSolid(shape.wrapped)
            solid.mesh_source = source
            solid.mesh_sew_report = report
            return solid, report

    if outcome is not None:
        from hephaestus.geom.mesh import MeshOperationError

        raise MeshOperationError(
            f"sewing {source!r} failed in the sew subprocess: {outcome[1]}",
            reason="mesh_solid_invalid",
        )
    lost = (LOST_SEW, LOST_VALIDITY)
    raise MeshSewTimeout(
        f"the sew of {source!r} {cut_short} (MESH_INGEST.md §4.1, "
        f"COMPARE.md §5; ceiling {timeout_s:g}s via {MESH_SEW_TIMEOUT_ENV}); "
        f"lost: {', '.join(lost)}. The mesh is admitted and every fact the "
        "canonicalizer measured about it is attached — what is missing is the solid.",
        timeout_s=timeout_s,
        partial=partial,
        lost=lost,
    )


def _report_kwargs(payload: object) -> dict[str, object]:
    """Rebuild :class:`SewReport` kwargs from the child's JSON projection."""
    data = cast("dict[str, Any]", payload)
    return {
        "triangle_count": int(data["triangle_count"]),
        "face_count": int(data["face_count"]),
        "vertex_count": int(data["vertex_count"]),
        "shell_count": int(data["shell_count"]),
        "is_valid": bool(data["is_valid"]),
        "analyzer_statuses": tuple(str(s) for s in data["analyzer_statuses"]),
        "sew_seconds": float(data["sew_seconds"]),
    }


# --------------------------------------------------------------------------
# §8 Tier 3 provenance: a sew golden is valid for exactly one (image, OCCT) pair

#: Where a pinned-image run declares its own digest. Absent on a stock runner
#: and on a developer's machine, which is a fact rather than a gap — see
#: :func:`image_digest`.
IMAGE_DIGEST_ENV: Final[str] = "HEPHAESTUS_CI_IMAGE_DIGEST"

#: The literal recorded when no pinned image declared itself. Named rather than
#: left empty so a sidecar always states which world it was recorded in, and so
#: "recorded outside the image" and "recorded in an image that forgot to say
#: which" can never collapse into the same string.
UNPINNED_IMAGE: Final[str] = "unpinned"

#: Distributions that ship OCCT under this project's pinned wheel set, in the
#: order they are consulted.
_OCCT_DISTRIBUTIONS: Final[tuple[str, ...]] = (
    "cadquery-ocp-novtk",
    "cadquery-ocp",
    "cadquery-ocp-proxy",
)


def occt_version() -> str:
    """The installed OCCT version, MEASURED from distribution metadata.

    ``OCP.Standard`` exports no ``Standard_Version`` in this binding, so the
    honest source is the wheel that shipped the kernel. Returns ``"unknown"``
    rather than guessing when no known distribution is installed — a golden
    whose provenance says ``unknown`` is one that cannot be revalidated, which
    is the correct thing for it to say.
    """
    for name in _OCCT_DISTRIBUTIONS:
        try:
            return f"{name} {metadata.version(name)}"
        except metadata.PackageNotFoundError:
            continue
    return "unknown"


def image_digest() -> str:
    """The pinned container image this process runs in, or :data:`UNPINNED_IMAGE`."""
    return os.environ.get(IMAGE_DIGEST_ENV) or UNPINNED_IMAGE


def sew_provenance() -> dict[str, str]:
    """The ``(container image digest, OCCT version)`` pair a sew golden is valid for.

    ``verification.md``'s golden-provenance rule extended from the renderer to
    the kernel (``MESH_INGEST.md`` §8 Tier 3): OCCT's sewing is a
    tolerance-driven merge whose output topology this project does not claim is
    stable across builds, so a sew-derived golden is valid for exactly one pair
    and an OCCT bump is a re-baseline PR, exactly as a renderer digest bump is
    (``repo_conventions.md``:186-194).
    """
    return {"image_digest": image_digest(), "occt_version": occt_version()}
