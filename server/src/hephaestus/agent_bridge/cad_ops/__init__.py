"""Core-backed CAD operations behind ``py.tool_dispatch`` (the whole tool surface).

The dispatcher (:mod:`hephaestus.agent_bridge.dispatch`) authorizes a tool and
routes the *file-CRUD* family through
:class:`~hephaestus.core.project_store.store.ProjectStore`. Everything that needs
geometry, parameters, checks, artifacts or exports is factored here behind one
:class:`CadOps` seam the dispatcher holds optionally: when absent those tools
report ``not_implemented`` (the Stage 2A behaviour), when present the real engine
runs.

:class:`CadOps` is a single object — the operations share one project layout,
opstore and execution backend (:class:`~._base.CadOpsState`) — assembled from one
mixin per domain so each domain reads independently:

``_build``       ``build_part`` (freeze → sandboxed build → hc-projection sync →
                 publish), ``inspect_part``, ``render_bundle``.
``_params``      the sandboxed ``PARAMS`` probes, ``set_params`` bounds
                 validation, and the ``edit_globals`` CAS write.
``_checks``      project-check CRUD over check-set generations, the safe
                 template, and both ``run_checks`` scopes.
``_measure``     ``measure`` and its single-part / coherent-snapshot /
                 explicit-ref geometry resolution.
``_requirements`` the ``VALIDATION.md`` §2 requirement ledger: immutable
                 generations under the project-config lock, and the typed
                 :func:`~._requirements.ledger_state` reader every later
                 validation rung keys on.
``_critique``    the ``VALIDATION.md`` §4 post-build critique every successful
                 ``build_part`` carries unasked: bounded pairwise interference,
                 manifold, and the original request's numbers versus the built
                 dimensions.
``_gate``        the ``VALIDATION.md`` §3 clarification gate: which assumption is
                 material, what a clarification question must look like, and what
                 an answer does to the ledger — all by rule.
``_artifacts``   ``read_artifact`` byte-cursor paging.
``_exports``     the §7 ``export_part`` contract (WAL, path confinement, pins,
                 format writers).
``_base``        the shared state, the persisted-override :class:`ParamStore`,
                 and the :class:`CadOpError` taxonomy every domain raises.

Every mutation is idempotent on the trusted invocation id through opstore
opkeys; a committed retry replays its recorded outcome and a same-id/
different-payload presentation is a hard mismatch.

This module is the public surface: import ``CadOps`` and the names below from
here, never from the private domain modules.
"""

from __future__ import annotations

from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.project_store.layout import ProjectLayout

from opstore import OpStore

from ._artifacts import BINARY_ARTIFACT_KINDS, TEXT_ARTIFACT_MIME, ArtifactOps
from ._base import (
    PART_PARAMS_POINTER_PREFIX,
    PROJECT_PARAMS_POINTER,
    CadOpError,
    ParamConflict,
    ParamState,
    ParamStore,
    params_pointer,
)
from ._build import BuildOps
from ._checks import (
    CHECK_DESCRIPTION_SENTINEL,
    CHECK_TEMPLATE_HEADER,
    CheckOps,
    check_template,
)
from ._critique import (
    MAX_INTERFERENCE_PAIRS,
    RequestNumber,
    critique_block,
    intentional_overlap_declarations,
    interference_report,
    manifold_report,
    named_solids,
    prompt_number_diff,
    request_numbers,
)
from ._exports import EXPORT_FORMATS, ExportOps, ensure_exports_table
from ._gate import (
    CLARIFICATION_MAX_OPTIONS,
    CLARIFICATION_MIN_OPTIONS,
    INVALID_QUESTION_CODE,
    MATERIAL_CLASSES,
    ClarificationGate,
    ClarificationOutcome,
    answer_text,
    clarification_gate,
    invalid_question_result,
    is_committal,
    material_class,
    option_consequence,
    option_label,
    question_problems,
    question_refusal,
    record_answers,
    record_clarification_answer,
    requirement_ids,
)
from ._measure import MeasureOps
from ._params import SYNC_PART, ParamOps, ParamProbe
from ._requirements import (
    REQUIREMENT_ARTIFACT_KIND,
    REQUIREMENT_ID_PATTERN,
    REQUIREMENT_SOURCES,
    REQUIREMENTS_POINTER,
    LedgerState,
    RequirementEntry,
    RequirementOps,
    entry_views,
    ledger_state,
)

__all__ = [
    "BINARY_ARTIFACT_KINDS",
    "CHECK_DESCRIPTION_SENTINEL",
    "CHECK_TEMPLATE_HEADER",
    "CLARIFICATION_MAX_OPTIONS",
    "CLARIFICATION_MIN_OPTIONS",
    "EXPORT_FORMATS",
    "INVALID_QUESTION_CODE",
    "MATERIAL_CLASSES",
    "MAX_INTERFERENCE_PAIRS",
    "PART_PARAMS_POINTER_PREFIX",
    "PROJECT_PARAMS_POINTER",
    "REQUIREMENTS_POINTER",
    "REQUIREMENT_ARTIFACT_KIND",
    "REQUIREMENT_ID_PATTERN",
    "REQUIREMENT_SOURCES",
    "SYNC_PART",
    "TEXT_ARTIFACT_MIME",
    "CadOpError",
    "CadOps",
    "ClarificationGate",
    "ClarificationOutcome",
    "LedgerState",
    "ParamConflict",
    "ParamProbe",
    "ParamState",
    "ParamStore",
    "RequestNumber",
    "RequirementEntry",
    "answer_text",
    "check_template",
    "clarification_gate",
    "critique_block",
    "entry_views",
    "intentional_overlap_declarations",
    "interference_report",
    "invalid_question_result",
    "is_committal",
    "ledger_state",
    "manifold_report",
    "material_class",
    "named_solids",
    "option_consequence",
    "option_label",
    "params_pointer",
    "prompt_number_diff",
    "question_problems",
    "question_refusal",
    "record_answers",
    "record_clarification_answer",
    "request_numbers",
    "requirement_ids",
]


class CadOps(BuildOps, ParamOps, CheckOps, MeasureOps, ArtifactOps, ExportOps, RequirementOps):
    """Core-backed operations for one project's layout, opstore and backend."""

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        backend: ExecBackend | None = None,
    ) -> None:
        super().__init__(layout, store, backend=backend)
        ensure_exports_table(store)
