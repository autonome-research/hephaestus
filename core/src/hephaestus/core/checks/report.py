# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The ``heph check --json`` body, as one shared function with two callers.

``INTERFACE.md`` §6.3 and §19 item 5: ``GET /parts/{part}/checks`` and
``GET /checks`` serialize the :class:`~hephaestus.core.types.CheckReport`
through **the same function** ``heph check --json`` uses, so the e2e can compare
browser DOM badges against a subprocess ``heph check --json`` and assert
byte-parity on the canonical JSON. One serializer, two callers, no second
implementation (mission rule 6).

The CLI held two things the HTTP route also needs and neither was standalone:
the *assembly* of the lock-free per-part geometry sources each check measures
against, and the serialization. Both move here. Neither performs an
authorization check — ``heph check`` is an operator on the filesystem and the
route is a ``WorkspacePrincipal`` bearer — so each caller applies its own.

Badge vocabulary (``INTERFACE.md`` §6.3, closed): ``pass``, ``fail``, ``error``,
``not_run``. :func:`badge` is the only place the mapping from a
:class:`~hephaestus.core.types.CheckResult` to that vocabulary is made, and
``not_run`` is a state of its own — silence never reads as a pass.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Final

from hephaestus.core.checks.engine import CheckSet
from hephaestus.core.checks.facade import GeometrySource
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.types import CheckReport, CheckResult
from opstore.types import JSONValue

from opstore import OpStore

__all__ = ["BADGES", "badge", "project_check_report", "report_json"]

#: ``INTERFACE.md`` §6.3 — the closed badge vocabulary.
BADGES: Final[tuple[str, ...]] = ("pass", "fail", "error", "not_run")


def project_check_report(
    layout: ProjectLayout, store: OpStore, *, project: bool = False
) -> CheckReport:
    """Run the project's ``checks/*.py`` set against each part's current artifact.

    Exactly what ``heph check`` does: lock-free reads of every part's last
    ``current`` artifact (``architecture.md`` §3.5), a scratch dir for the
    kernel-side geometry sources, and — when ``project`` is set — a recorded
    coherent project snapshot, whose refusal raises
    :class:`~hephaestus.core.project_store.projections.SnapshotRejectedError`
    for the caller to render in its own idiom.
    """
    from hephaestus.core.executor.artifact_geometry import artifact_source

    publisher = Publisher(layout, store)
    layout.store_root.mkdir(parents=True, exist_ok=True)
    sources: dict[str, GeometrySource] = {}
    with tempfile.TemporaryDirectory(prefix="heph-check-", dir=layout.store_root) as scratch:
        for part in layout.part_names():
            current = publisher.current_result(part)
            if current is None or current.artifact_ref is None:
                continue
            data = store.blobs.get(blob_hash_of_ref(current.artifact_ref))
            sources[part] = artifact_source(data, scratch_dir=Path(scratch))

        snapshot_ref: str | None = None
        if project:
            snapshot = publisher.projections.assemble_snapshot(layout.part_names())
            snapshot_ref = snapshot.ref

        check_set = CheckSet(layout.checks_dir, store)
        return check_set.run(sources, part=layout.manifest.name, project_snapshot_ref=snapshot_ref)


def report_json(report: CheckReport) -> dict[str, JSONValue]:
    """The exact document ``heph check --json`` prints.

    A one-line delegation on purpose: the serialization already lives on the
    record, and a second rendering of it — however small — is the duplication
    mission rule 6 forbids. This function exists to be the *named* joint the
    HTTP route and the CLI both call, so a future divergence has to be a
    deliberate edit here rather than a quiet drift there.
    """
    return report.to_json()


def badge(result: CheckResult | None) -> str:
    """The §6.3 badge for one check outcome; ``None`` is ``not_run``.

    ``not_run`` is a first-class state, never collapsed into a pass: a check the
    run did not reach is not a check that passed. ``error`` outranks ``fail``
    because a check that could not be *evaluated* has no verdict to report — and
    :func:`hephaestus.core.checks.engine.run_checks` records exactly that as a
    ``measured.error`` (a predicate that raised) or a ``measured.unverifiable``
    (a bounded measurement the wall-clock ceiling cut short, ``COMPARE.md`` §5 /
    ``KINEMATICS.md`` §4). Both are ``error``: the badge vocabulary is closed at
    four values (§6.3) and neither may read as a ``fail``, which would assert a
    verdict the engine explicitly declined to give.
    """
    if result is None:
        return "not_run"
    measured = result.measured
    if isinstance(measured, dict) and ("error" in measured or "unverifiable" in measured):
        return "error"
    return "pass" if result.passed else "fail"
