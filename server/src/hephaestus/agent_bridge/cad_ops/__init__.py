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
``_compare``     ``COMPARE.md`` §2 ``compare_solids``: the editing loop's
                 convergence signal, over a part and a ``part:``/``import:``
                 target, attributed to the artifact refs and import hash used.
``_assembly``    the ``ASSEMBLY.md`` §3 constraint quartet: thin ops over the
                 project's generational constraint set and the engine evaluator,
                 keeping the tool surface's refusal vocabulary and nothing else.
``_requirements`` the ``VALIDATION.md`` §2 requirement ledger: immutable
                 generations under the project-config lock, and the typed
                 :func:`~._requirements.ledger_state` reader every later
                 validation rung keys on.
``_critique``    the ``VALIDATION.md`` §4 post-build critique every successful
                 ``build_part`` carries unasked: bounded pairwise interference,
                 manifold, the original request's numbers versus the built
                 dimensions, and — with the project's DFM mode on — the process
                 pack's findings on the artifact just published.
``_dfm``         ``run_dfm``: artifact resolution (current / explicit ref /
                 project snapshot), process and material resolution, and the
                 sandboxed rule-pack evaluation behind both the tool and the
                 auto-run critique rung.
``_findings``    the binding half of ``VALIDATION.md`` §4: the dimension findings
                 a successful build raises against the request's own numbers,
                 recorded by the runtime, cleared only by a rebuild that matches
                 or a user's dismissal, and blocking in §6.
``_gate``        the ``VALIDATION.md`` §3 clarification gate: which assumption is
                 material, what a clarification question must look like, and what
                 an answer does to the ledger — all by rule.
``_artifacts``   ``read_artifact`` byte-cursor paging.
``_references``  ``INGEST.md`` §2 ``list_references``/``read_reference``: the
                 model's READ-ONLY view of the operator-supplied ``references/``
                 registry (registration itself is not on this surface at all).
``_exports``     the §7 export contract (WAL, path confinement, pins, format
                 writers) as one reusable operation, plus ``export_part``.
``_drawing``     ``generate_drawing``: render-service views, artifact-measured
                 dimensions drawn as real text, metadata title block, PDF+SVG.
``_doc``         ``generate_doc``: BOM (labeled solids x materials registry),
                 assembly instructions and spec sheets as markdown + JSON.
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
from ._assembly import AssemblyOps
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
from ._compare import ALIGN_MODES, CompareOps
from ._critique import (
    DFM_WARNING_SEVERITIES,
    MAX_INTERFERENCE_PAIRS,
    RequestNumber,
    critique_block,
    dfm_report,
    intentional_overlap_declarations,
    interference_report,
    manifold_report,
    named_solids,
    prompt_number_diff,
    request_numbers,
    with_dimension_findings,
)
from ._dfm import DfmOps, DfmTarget, script_metadata
from ._doc import DOC_KINDS, BomRow, DocOps, assembly_steps, fabrication_verb
from ._drawing import (
    DRAWING_KINDS,
    SHEET_SIZES,
    TITLE_BLOCK_FIELDS,
    Dimension,
    DrawingOps,
    Sheet,
    dimension_text,
    principal_dimensions,
    solid_labels,
)
from ._exports import EXPORT_FORMATS, ExportOps, ExportOutput, ensure_exports_table
from ._findings import (
    BINDING_WARNING_KINDS,
    DIMENSION_FINDING_ARTIFACT_KIND,
    DIMENSION_FINDING_ID_PREFIX,
    DIMENSION_FINDINGS_POINTER,
    DimensionFinding,
    DimensionFindingOps,
    DimensionFindingState,
    dimension_finding_id,
    dimension_findings,
    finding_views,
)
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
    record_dimension_answer,
    requirement_ids,
)
from ._measure import MeasureOps
from ._params import SYNC_PART, ParamOps, ParamProbe
from ._references import REFERENCE_WRAPPER_REGISTRY, ReferenceOps
from ._requirements import (
    REQUIREMENT_ARTIFACT_KIND,
    REQUIREMENT_ID_PATTERN,
    REQUIREMENT_SOURCES,
    REQUIREMENTS_POINTER,
    LedgerState,
    RequirementCite,
    RequirementEntry,
    RequirementOps,
    entry_views,
    ledger_state,
)

__all__ = [
    "ALIGN_MODES",
    "BINARY_ARTIFACT_KINDS",
    "BINDING_WARNING_KINDS",
    "CHECK_DESCRIPTION_SENTINEL",
    "CHECK_TEMPLATE_HEADER",
    "CLARIFICATION_MAX_OPTIONS",
    "CLARIFICATION_MIN_OPTIONS",
    "DFM_WARNING_SEVERITIES",
    "DIMENSION_FINDINGS_POINTER",
    "DIMENSION_FINDING_ARTIFACT_KIND",
    "DIMENSION_FINDING_ID_PREFIX",
    "DOC_KINDS",
    "DRAWING_KINDS",
    "EXPORT_FORMATS",
    "INVALID_QUESTION_CODE",
    "MATERIAL_CLASSES",
    "MAX_INTERFERENCE_PAIRS",
    "PART_PARAMS_POINTER_PREFIX",
    "PROJECT_PARAMS_POINTER",
    "REFERENCE_WRAPPER_REGISTRY",
    "REQUIREMENTS_POINTER",
    "REQUIREMENT_ARTIFACT_KIND",
    "REQUIREMENT_ID_PATTERN",
    "REQUIREMENT_SOURCES",
    "SHEET_SIZES",
    "SYNC_PART",
    "TEXT_ARTIFACT_MIME",
    "TITLE_BLOCK_FIELDS",
    "AssemblyOps",
    "BomRow",
    "CadOpError",
    "CadOps",
    "ClarificationGate",
    "ClarificationOutcome",
    "CompareOps",
    "DfmOps",
    "DfmTarget",
    "Dimension",
    "DimensionFinding",
    "DimensionFindingOps",
    "DimensionFindingState",
    "DocOps",
    "DrawingOps",
    "ExportOutput",
    "LedgerState",
    "ParamConflict",
    "ParamProbe",
    "ParamState",
    "ParamStore",
    "ReferenceOps",
    "RequestNumber",
    "RequirementCite",
    "RequirementEntry",
    "Sheet",
    "answer_text",
    "assembly_steps",
    "check_template",
    "clarification_gate",
    "critique_block",
    "dfm_report",
    "dimension_finding_id",
    "dimension_findings",
    "dimension_text",
    "entry_views",
    "fabrication_verb",
    "finding_views",
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
    "principal_dimensions",
    "prompt_number_diff",
    "question_problems",
    "question_refusal",
    "record_answers",
    "record_clarification_answer",
    "record_dimension_answer",
    "request_numbers",
    "requirement_ids",
    "script_metadata",
    "solid_labels",
    "with_dimension_findings",
]


class CadOps(
    BuildOps,
    ParamOps,
    CheckOps,
    MeasureOps,
    CompareOps,
    ArtifactOps,
    DrawingOps,
    DocOps,
    ExportOps,
    RequirementOps,
    AssemblyOps,
    ReferenceOps,
    DimensionFindingOps,
    DfmOps,
):
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
