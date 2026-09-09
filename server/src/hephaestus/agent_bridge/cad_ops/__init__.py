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
``_solve``       the ``SOLVER.md`` §11 solving tools: ``solve_pose`` (13A),
                 ``propose_placement`` and ``read_proposals`` (13B) — thin ops
                 over ``hephaestus.core.placement``. ``solve_pose`` writes
                 nothing at all; ``propose_placement`` writes exactly one
                 thing, an immutable proposal document, and NOTHING applies
                 it. Writeback is refused, structurally.
``_motion``      the ``KINEMATICS.md`` §6 Stage 9A kinematics tools: thin ops
                 over the generational joint and pose sets and the engine
                 motion evaluator, keeping the tool surface's refusal
                 vocabulary and nothing else (motion checks are 9B).
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
``_geometry``    ``INTERFACE.md`` §5.1's geometry wire: resolve-or-mint the
                 selection bundle for a build ref and publish the GLB bound to
                 it, and re-verify an already-published GLB's bundle link before
                 it is served. Never an unlinked GLB.
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

**Every name below resolves on first access, not on import** (ledger
J-cli-startup-2, root cause RC-2). Assembling that public surface eagerly meant
that *reaching any leaf of this package* — including
:mod:`~hephaestus.agent_bridge.cad_ops.export_history`, a pure-stdlib WAL reader
that is not even re-exported here — first imported all 21 domain mixins, three
of which pull the geometry package and with it build123d, OCP and scikit-learn.
That is what made registering ``heph export list`` cost 3498 ms on every
``heph`` invocation, and it is why the comment in :mod:`hephaestus.core.cli`
claiming those verbs load no geometry kernel was false. The ``__getattr__``
below fixes the mechanism rather than the one site: the public name list is
unchanged, every consumer keeps its import statement, and the first *use* of a
name costs exactly what the import always did.

:class:`CadOps` itself is the one name that cannot be re-exported from a
submodule — it is defined here, from the mixins — so it is built by
:func:`_assemble_cad_ops` on first access. Its declaration is stated once more
under ``TYPE_CHECKING`` so the type checker sees the real base list;
``core/tests/test_cli_startup.py`` pins the two against each other by asserting
that every ``*Ops`` mixin this package defines is a base of the assembled
class. Neither copy declares a constructor — that lives once on
:class:`~._base.CadOpsState` and both reach it through the same bases.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    # The type checker reads the real symbols from the real modules; only the
    # runtime defers. Nothing about the surface changes — see the class
    # declaration at the end of this block.
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
    from ._exports import EXPORT_FORMATS, ExportOps, ExportOutput
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
        option_display,
        option_label,
        question_problems,
        question_refusal,
        record_answers,
        record_clarification_answer,
        record_dimension_answer,
        requirement_ids,
    )
    from ._geometry import GeometryOps, PublishedGltf
    from ._measure import MeasureOps
    from ._motion import MotionOps
    from ._params import SYNC_PART, ParamOps, ParamProbe
    from ._references import REFERENCE_WRAPPER_REGISTRY, ReferenceOps
    from ._request import (
        RUN_REQUEST_BINDINGS_MAX,
        active_run,
        active_run_id,
        bind_run_request_text,
        inherit_run_request_text,
        release_run_request_text,
        run_request_text,
    )
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
    from ._solve import SolveOps

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
        MotionOps,
        SolveOps,
        ReferenceOps,
        DimensionFindingOps,
        DfmOps,
        GeometryOps,
    ):
        """Core-backed operations for one project's layout, opstore and backend.

        Deliberately declares NO ``__init__``: the constructor exists exactly
        once, on :class:`~._base.CadOpsState`, and both halves of this class
        read it from there — the type checker through this declaration's MRO,
        the runtime through the forwarding override in
        :func:`_assemble_cad_ops`. A second signature written out here would
        be one more copy to keep in step with the first.
        """


#: Public name -> the private domain module that defines it: the whole
#: re-export table, including the mixin classes and ``ensure_exports_table``
#: that ``__all__`` deliberately omits but consumers may still import.
_EXPORTS: Final[dict[str, str]] = {
    "BINARY_ARTIFACT_KINDS": "_artifacts",
    "TEXT_ARTIFACT_MIME": "_artifacts",
    "ArtifactOps": "_artifacts",
    "AssemblyOps": "_assembly",
    "PART_PARAMS_POINTER_PREFIX": "_base",
    "PROJECT_PARAMS_POINTER": "_base",
    "CadOpError": "_base",
    "ParamConflict": "_base",
    "ParamState": "_base",
    "ParamStore": "_base",
    "params_pointer": "_base",
    "BuildOps": "_build",
    "CHECK_DESCRIPTION_SENTINEL": "_checks",
    "CHECK_TEMPLATE_HEADER": "_checks",
    "CheckOps": "_checks",
    "check_template": "_checks",
    "ALIGN_MODES": "_compare",
    "CompareOps": "_compare",
    "DFM_WARNING_SEVERITIES": "_critique",
    "MAX_INTERFERENCE_PAIRS": "_critique",
    "RequestNumber": "_critique",
    "critique_block": "_critique",
    "dfm_report": "_critique",
    "intentional_overlap_declarations": "_critique",
    "interference_report": "_critique",
    "manifold_report": "_critique",
    "named_solids": "_critique",
    "prompt_number_diff": "_critique",
    "request_numbers": "_critique",
    "with_dimension_findings": "_critique",
    "DfmOps": "_dfm",
    "DfmTarget": "_dfm",
    "script_metadata": "_dfm",
    "DOC_KINDS": "_doc",
    "BomRow": "_doc",
    "DocOps": "_doc",
    "assembly_steps": "_doc",
    "fabrication_verb": "_doc",
    "DRAWING_KINDS": "_drawing",
    "SHEET_SIZES": "_drawing",
    "TITLE_BLOCK_FIELDS": "_drawing",
    "Dimension": "_drawing",
    "DrawingOps": "_drawing",
    "Sheet": "_drawing",
    "dimension_text": "_drawing",
    "principal_dimensions": "_drawing",
    "solid_labels": "_drawing",
    "EXPORT_FORMATS": "_exports",
    "ExportOps": "_exports",
    "ExportOutput": "_exports",
    "ensure_exports_table": "_exports",
    "BINDING_WARNING_KINDS": "_findings",
    "DIMENSION_FINDING_ARTIFACT_KIND": "_findings",
    "DIMENSION_FINDING_ID_PREFIX": "_findings",
    "DIMENSION_FINDINGS_POINTER": "_findings",
    "DimensionFinding": "_findings",
    "DimensionFindingOps": "_findings",
    "DimensionFindingState": "_findings",
    "dimension_finding_id": "_findings",
    "dimension_findings": "_findings",
    "finding_views": "_findings",
    "CLARIFICATION_MAX_OPTIONS": "_gate",
    "CLARIFICATION_MIN_OPTIONS": "_gate",
    "INVALID_QUESTION_CODE": "_gate",
    "MATERIAL_CLASSES": "_gate",
    "ClarificationGate": "_gate",
    "ClarificationOutcome": "_gate",
    "answer_text": "_gate",
    "clarification_gate": "_gate",
    "invalid_question_result": "_gate",
    "is_committal": "_gate",
    "material_class": "_gate",
    "option_consequence": "_gate",
    "option_display": "_gate",
    "option_label": "_gate",
    "question_problems": "_gate",
    "question_refusal": "_gate",
    "record_answers": "_gate",
    "record_clarification_answer": "_gate",
    "record_dimension_answer": "_gate",
    "requirement_ids": "_gate",
    "GeometryOps": "_geometry",
    "PublishedGltf": "_geometry",
    "MeasureOps": "_measure",
    "MotionOps": "_motion",
    "SYNC_PART": "_params",
    "ParamOps": "_params",
    "ParamProbe": "_params",
    "REFERENCE_WRAPPER_REGISTRY": "_references",
    "ReferenceOps": "_references",
    "RUN_REQUEST_BINDINGS_MAX": "_request",
    "active_run": "_request",
    "active_run_id": "_request",
    "bind_run_request_text": "_request",
    "inherit_run_request_text": "_request",
    "release_run_request_text": "_request",
    "run_request_text": "_request",
    "REQUIREMENT_ARTIFACT_KIND": "_requirements",
    "REQUIREMENT_ID_PATTERN": "_requirements",
    "REQUIREMENT_SOURCES": "_requirements",
    "REQUIREMENTS_POINTER": "_requirements",
    "LedgerState": "_requirements",
    "RequirementCite": "_requirements",
    "RequirementEntry": "_requirements",
    "RequirementOps": "_requirements",
    "entry_views": "_requirements",
    "ledger_state": "_requirements",
    "SolveOps": "_solve",
}

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
    "RUN_REQUEST_BINDINGS_MAX",
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
    "GeometryOps",
    "LedgerState",
    "MotionOps",
    "ParamConflict",
    "ParamProbe",
    "ParamState",
    "ParamStore",
    "PublishedGltf",
    "ReferenceOps",
    "RequestNumber",
    "RequirementCite",
    "RequirementEntry",
    "Sheet",
    "SolveOps",
    "active_run",
    "active_run_id",
    "answer_text",
    "assembly_steps",
    "bind_run_request_text",
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
    "inherit_run_request_text",
    "intentional_overlap_declarations",
    "interference_report",
    "invalid_question_result",
    "is_committal",
    "ledger_state",
    "manifold_report",
    "material_class",
    "named_solids",
    "option_consequence",
    "option_display",
    "option_label",
    "params_pointer",
    "principal_dimensions",
    "prompt_number_diff",
    "question_problems",
    "question_refusal",
    "record_answers",
    "record_clarification_answer",
    "record_dimension_answer",
    "release_run_request_text",
    "request_numbers",
    "requirement_ids",
    "run_request_text",
    "script_metadata",
    "solid_labels",
    "with_dimension_findings",
]


def _assemble_cad_ops() -> type[object]:
    """Import the 21 domain mixins and build :class:`CadOps` from them.

    Called once, from :func:`__getattr__`. This is the only place the whole
    aggregate is paid for, and it is paid by the first *use* of ``CadOps``
    rather than by every import of any module in this package.

    The return annotation is deliberately weak: the class this builds and the
    class declared under ``TYPE_CHECKING`` above are the same class to a reader
    and two different symbols to the type checker, so naming the declared one
    here would be a false claim about identity. The declaration above is the
    typed view every consumer sees; this function is the runtime one, and
    ``__getattr__`` binds the result into the module namespace under that name.
    """
    from ._artifacts import ArtifactOps
    from ._assembly import AssemblyOps
    from ._build import BuildOps
    from ._checks import CheckOps
    from ._compare import CompareOps
    from ._dfm import DfmOps
    from ._doc import DocOps
    from ._drawing import DrawingOps
    from ._exports import ExportOps, ensure_exports_table
    from ._findings import DimensionFindingOps
    from ._geometry import GeometryOps
    from ._measure import MeasureOps
    from ._motion import MotionOps
    from ._params import ParamOps
    from ._references import ReferenceOps
    from ._requirements import RequirementOps
    from ._solve import SolveOps

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
        MotionOps,
        SolveOps,
        ReferenceOps,
        DimensionFindingOps,
        DfmOps,
        GeometryOps,
    ):
        """Core-backed operations for one project's layout, opstore and backend."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # Signature-free on purpose. The aggregate adds one thing to
            # construction — the exports WAL table — and nothing else, so it
            # forwards whatever `CadOpsState.__init__` accepts instead of
            # restating it. Restating it would fork the constructor across two
            # files (`_base.py` and this one) and, because the declaration
            # above is what the type checker reads, a drift between them would
            # be invisible to pyright.
            super().__init__(*args, **kwargs)
            ensure_exports_table(self._store)

    # Defined inside a function, so Python would otherwise name it
    # `_assemble_cad_ops.<locals>.CadOps` in every repr and traceback. The
    # class is the package's, and says so.
    CadOps.__qualname__ = "CadOps"
    return CadOps


def __getattr__(name: str) -> object:
    """Resolve one re-exported name by importing the module that defines it."""
    if name == "CadOps":
        # `setdefault` rather than a plain assignment, because assembling the
        # class is the one step here that is not idempotent: two threads
        # first-touching `CadOps` at once would each run the class statement
        # and get two distinct classes, and `agent_bridge/review.py` does
        # `isinstance(cad, CadOps)`. A dict `setdefault` is atomic, so the
        # first one to land wins and every caller gets that same class; the
        # loser's copy is discarded unreferenced. No lock, and therefore no
        # lock held across an import.
        return globals().setdefault(name, _assemble_cad_ops())
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Every other name comes off a submodule, and `import_module` is idempotent
    # under the import system's own locking.
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value  # bind it, so the next access is a plain lookup
    return value


def __dir__() -> list[str]:
    return sorted({*__all__, *_EXPORTS})
