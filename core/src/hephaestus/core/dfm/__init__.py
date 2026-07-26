"""hephaestus.core.dfm: running registry DFM rule packs against build artifacts.

Three layers, one direction of dependency:

* :mod:`.types` — the result vocabulary (:class:`~.types.TopologyDescriptor`,
  :class:`~.types.DfmFinding`, :class:`~.types.DfmRuleOutcome`,
  :class:`~.types.DfmEvaluation`). Everything is artifact-bound: findings carry
  the ``source_artifact_ref`` they were measured against and descriptors that
  address topology inside those exact bytes, never a mutable mask id.
* :mod:`.context` — :class:`~.context.DfmContext`, the typed evaluation context
  a predicate receives: enumerated topology, derived primitives (holes, internal
  rounds, opposing-face walls, overhangs), the part's §5.2 metadata, the
  resolved material record, and exactly the pack parameters the rule declared.
* :mod:`.runner` / :mod:`.worker` — the sandboxed execution path. Predicates are
  untrusted registry content and run under the same backend and the same §2
  injected namespace as part scripts (architecture §3.6, §7.2), with
  ``origin: "registry"`` so the unsafe local backend refuses them.

This facade deliberately re-exports **only** the first two layers. The DFM
worker runs as ``python -m hephaestus.core.dfm.worker`` *inside* the sandbox,
which executes this ``__init__`` first; pulling the parent-side orchestration
(and through it the registry tool surface, which reads ``schemas/`` from the
source tree) into that import would make the worker depend on files the sandbox
does not bind. Import the orchestration explicitly::

    from hephaestus.core.dfm.runner import DfmRequest, evaluate_pack

The rule *packs* themselves live in the registry layer
(:class:`hephaestus.core.registry.DfmPack`); this package executes them.
"""

from hephaestus.core.dfm.context import (
    OVERHANG_SAMPLES,
    WALL_FACE_LIMIT,
    CylindricalFace,
    DfmContext,
    OpposingFaces,
    Overhang,
    PlanarFace,
    RawFinding,
    TopologyHandle,
    build_context,
)
from hephaestus.core.dfm.types import (
    TOPOLOGY_KINDS,
    DfmEvaluation,
    DfmFinding,
    DfmRuleOutcome,
    TopologyDescriptor,
    descriptors_from_source_map,
    findings_by_severity,
)

__all__ = [
    "OVERHANG_SAMPLES",
    "TOPOLOGY_KINDS",
    "WALL_FACE_LIMIT",
    "CylindricalFace",
    "DfmContext",
    "DfmEvaluation",
    "DfmFinding",
    "DfmRuleOutcome",
    "OpposingFaces",
    "Overhang",
    "PlanarFace",
    "RawFinding",
    "TopologyDescriptor",
    "TopologyHandle",
    "build_context",
    "descriptors_from_source_map",
    "findings_by_severity",
]
