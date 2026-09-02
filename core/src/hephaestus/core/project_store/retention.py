"""Default protected-roots retention policy (architecture §3.5).

The current successful artifact and one most-recent-failure last-good record
per part are protected from GC, together with the live project-state /
project-snapshot projections and the check-set state/intent records. Roots
are resolved live at each GC pass by reading the store's named pointers, so
a pointer flip immediately re-scopes protection; opstore ``gc.link`` edges
(bundle → result record → evidence blobs) make protection transitive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

__all__ = [
    "LAST_FAILURE_POINTER_PREFIX",
    "DefaultProtectedRoots",
    "last_failure_pointer",
    "protected_pointer_names",
]

#: CAS pointer prefix for per-part most-recent-failure evidence records.
LAST_FAILURE_POINTER_PREFIX = "part-last-failure:"


def last_failure_pointer(part: str) -> str:
    """The CAS pointer name holding ``part``'s most-recent-failure record."""
    return LAST_FAILURE_POINTER_PREFIX + part


def protected_pointer_names(layout: ProjectLayout) -> tuple[str, ...]:
    """Every named pointer whose target is a protected GC root (§3.5)."""
    # Imported lazily: publication/projections/checks all import project_store
    # modules, so a top-level import here would be circular.
    from hephaestus.core.checks.engine import INTENT_POINTER
    from hephaestus.core.checks.engine import STATE_POINTER as CHECK_STATE_POINTER
    from hephaestus.core.project_store.constraints import CONSTRAINTS_POINTER
    from hephaestus.core.project_store.kinematics import JOINTS_POINTER, POSES_POINTER
    from hephaestus.core.project_store.projections import SNAPSHOT_POINTER, STATE_POINTER
    from hephaestus.core.project_store.proposals import PROPOSALS_POINTER
    from hephaestus.core.project_store.publication import current_pointer
    from hephaestus.core.project_store.references import REFERENCES_POINTER

    names: list[str] = [
        STATE_POINTER,
        SNAPSHOT_POINTER,
        CHECK_STATE_POINTER,
        INTENT_POINTER,
        # Operator-supplied reference material is project state, not run output
        # (INGEST.md §2): the live registry generation is a protected root.
        REFERENCES_POINTER,
        # Declared constraints are project state too (ASSEMBLY.md §1): the live
        # generation is a protected root, and its parent chain is reachable
        # through the gc links each generation records.
        CONSTRAINTS_POINTER,
        # Declared joints and named poses are project state on the same ledger
        # pattern (KINEMATICS.md §1/§3): each live generation is a protected
        # root, with the parent chain reachable through its gc links.
        JOINTS_POINTER,
        POSES_POINTER,
        # Placement proposals (``SOLVER.md`` §8) are MEASUREMENTS rather than
        # design state - nothing applies one, and design state after Stage 13
        # is exactly what it was before: scripts, globals.py and persisted
        # params, in git. The live generation is a protected root anyway,
        # because §8 promises every generation stays readable and a promise a
        # GC pass can break is not one. Each generation and each proposal
        # document is additionally pinned where it is written, so this is the
        # second of two guarantees rather than the only one.
        PROPOSALS_POINTER,
    ]
    for part in layout.part_names():
        names.append(current_pointer(part))
        names.append(last_failure_pointer(part))
    return tuple(names)


class DefaultProtectedRoots:
    """Live protected-roots callback for one project store.

    Constructed before the :class:`opstore.OpStore` exists (the store needs
    the callback at open time) and bound to it afterwards; until bound it
    reports no roots, which is safe because GC can only run through the
    bound store.
    """

    def __init__(self, layout: ProjectLayout) -> None:
        self._layout = layout
        self._store: OpStore | None = None

    def bind(self, store: OpStore) -> None:
        self._store = store

    def __call__(self) -> tuple[str, ...]:
        store = self._store
        if store is None:  # pragma: no cover - GC cannot run before bind()
            return ()
        targets: list[str] = []
        for name in protected_pointer_names(self._layout):
            target = store.blobs.read_pointer(name)
            if target is not None:
                targets.append(target)
        return tuple(targets)
