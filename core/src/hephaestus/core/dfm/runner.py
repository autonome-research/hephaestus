"""Parent-side DFM orchestration: pack + artifact -> sandboxed run -> evaluation.

:func:`evaluate_pack` is the one entry point a tool implementation needs. It
stages the immutable source artifact into a fresh scratch out dir, ships the
pack's rule declarations and predicate sources to the DFM worker through an
:class:`~hephaestus.core.executor.sandbox.base.ExecBackend`, and parses the
worker's record into a typed :class:`~hephaestus.core.dfm.types.DfmEvaluation`.

Two fail-closed properties are load-bearing and are enforced here rather than
left to callers:

* the job carries ``origin: "registry"``, so the ``--unsafe-local-executor``
  backend refuses it outright (``unsafe_refused``) exactly as it refuses store
  generators — DFM predicates run under a probed secure sandbox or not at all;
* a backend whose probe fails, or no backend at all, is a typed
  ``capability_not_available``/``sandbox_denied`` refusal, never a quiet
  unsandboxed evaluation.

The caller supplies the artifact *bytes* and the artifact *ref* that names them;
this module never resolves "current" anything, so an automatic DFM run and a
historical one are the same code path with a different ref.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from hephaestus.core.dfm.types import DfmEvaluation, DfmRuleOutcome, TopologyDescriptor
from hephaestus.core.errors import HephaestusError, ValidationError
from hephaestus.core.executor.runner import DEFAULT_RLIMITS, worker_ro_binds
from hephaestus.core.executor.sandbox.base import ExecBackend, Rlimits, SandboxSpec
from hephaestus.core.registry import DfmPack, RegistryError
from opstore.types import JSONValue

__all__ = [
    "ARTIFACT_FILENAME",
    "DEFAULT_DFM_WALL_CLOCK_S",
    "DfmRequest",
    "dfm_worker_command",
    "evaluate_pack",
]

#: The staged artifact's filename inside the worker's out dir.
ARTIFACT_FILENAME = "source.brep"

#: Wall clock for one pack run (predicates are measurement, not modelling).
DEFAULT_DFM_WALL_CLOCK_S = 120.0


def dfm_worker_command() -> tuple[str, ...]:
    """argv of the DFM worker: this interpreter running the worker module."""
    return (sys.executable, "-m", "hephaestus.core.dfm.worker")


@dataclass(frozen=True)
class DfmRequest:
    """One DFM invocation's frozen inputs.

    ``brep`` are the bytes of the artifact named by ``source_artifact_ref`` —
    the caller resolves current/historical/preview and reports the ref it
    chose. ``tags`` come from that build's stored source map (see
    :func:`hephaestus.core.dfm.types.descriptors_from_source_map`); ``material``
    is the materials-registry record the part's ``material_spec`` resolved to,
    or None when it resolved to nothing.
    """

    part: str
    process: str
    brep: bytes
    source_artifact_ref: str
    metadata: Mapping[str, str] = field(default_factory=dict[str, str])
    material: Mapping[str, JSONValue] | None = None
    tags: Mapping[str, TopologyDescriptor] = field(default_factory=dict[str, TopologyDescriptor])
    wall_clock_s: float = DEFAULT_DFM_WALL_CLOCK_S

    def __post_init__(self) -> None:
        if not self.source_artifact_ref:
            raise ValidationError(
                "a DFM run must name the artifact it measured (source_artifact_ref)",
                kind="contract",
            )
        if not self.brep:
            raise ValidationError("a DFM run needs the source artifact's bytes", kind="contract")


def _job(request: DfmRequest, pack: DfmPack, out_dir: Path) -> dict[str, JSONValue]:
    rules: list[JSONValue] = [
        {
            "rule_id": rule.rule_id,
            "title": rule.title,
            "severity": rule.severity,
            "params": cast("dict[str, JSONValue]", dict(rule.values)),
            "source": rule.read_predicate(),
        }
        for rule in pack.rules
    ]
    return {
        "mode": "dfm",
        "origin": "registry",
        "part": request.part,
        "process": pack.process,
        "source_artifact_ref": request.source_artifact_ref,
        "brep": ARTIFACT_FILENAME,
        "out_dir": str(out_dir),
        "metadata": {name: value for name, value in sorted(request.metadata.items())},
        "material": (None if request.material is None else dict(request.material)),
        "tags": {name: descriptor.to_json() for name, descriptor in sorted(request.tags.items())},
        "rules": rules,
    }


def evaluate_pack(
    request: DfmRequest,
    pack: DfmPack,
    *,
    backend: ExecBackend | None,
    scratch_root: Path | None = None,
    rlimits: Rlimits = DEFAULT_RLIMITS,
) -> DfmEvaluation:
    """Run every rule of ``pack`` against ``request``'s artifact under ``backend``.

    Returns one outcome per pack rule, in pack order, whatever happened: a
    predicate that raises is reported as that rule's ``error`` and the remaining
    rules still run.
    """
    if pack.process != request.process:
        raise RegistryError(
            "unknown_dfm_pack",
            f"pack {pack.process!r} cannot evaluate a {request.process!r} request",
            data={"expected": request.process, "actual": pack.process},
        )
    if backend is None:
        raise RegistryError(
            "capability_not_available",
            "no secure execution backend is configured; DFM rule predicates are "
            "registry content and never run unsandboxed",
            data={"code": "capability_not_available"},
        )
    report = backend.probe()
    if not report.available:
        raise RegistryError(
            "sandbox_denied",
            f"execution backend {report.backend!r} unavailable: {report.reason}",
            data={"backend": report.backend},
        )

    scratch_parent = scratch_root or Path(tempfile.gettempdir())
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="heph-dfm-", dir=scratch_parent))
    out_dir = scratch / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / ARTIFACT_FILENAME).write_bytes(request.brep)
        payload = json.dumps(_job(request, pack, out_dir)).encode("utf-8")
        spec = SandboxSpec(
            worker_cmd=dfm_worker_command(),
            ro_binds=worker_ro_binds(),
            rw_out_dir=out_dir,
            rlimits=rlimits,
            wall_clock_s=request.wall_clock_s,
        )
        try:
            outcome = backend.execute(spec, payload)
        except HephaestusError as exc:
            raise RegistryError(exc.code, f"DFM pack {pack.process!r}: {exc.message}") from exc
        if outcome.timed_out:
            raise RegistryError(
                "dfm_timeout",
                f"DFM worker exceeded the wall clock ({request.wall_clock_s:g}s)",
            )
        if outcome.exit_code != 0:
            stderr = outcome.stderr.decode("utf-8", errors="replace").strip()
            raise RegistryError(
                "dfm_worker_failed",
                f"DFM worker exited with code {outcome.exit_code}: {stderr[-2000:]}",
            )
        return parse_evaluation(outcome.stdout, request=request, pack=pack)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def parse_evaluation(stdout: bytes, *, request: DfmRequest, pack: DfmPack) -> DfmEvaluation:
    """Turn the worker's stdout record into a typed evaluation."""
    try:
        parsed: object = json.loads(stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegistryError(
            "dfm_worker_failed", f"DFM worker produced invalid result JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RegistryError("dfm_worker_failed", "DFM worker result must be a JSON object")
    record = cast("Mapping[str, JSONValue]", parsed)
    if record.get("status") != "ok":
        detail = record.get("error")
        raise RegistryError(
            "dfm_worker_failed",
            f"DFM evaluation failed: {detail if isinstance(detail, str) else 'unknown failure'}",
        )
    rules_raw = record.get("rules")
    outcomes: list[DfmRuleOutcome] = []
    if isinstance(rules_raw, list):
        for item in cast("list[JSONValue]", rules_raw):
            if isinstance(item, dict):
                outcomes.append(DfmRuleOutcome.from_json(cast("Mapping[str, JSONValue]", item)))
    return DfmEvaluation(
        part=request.part,
        process=pack.process,
        source_artifact_ref=request.source_artifact_ref,
        pack_name=pack.name,
        pack_version=pack.version,
        registry=pack.registry,
        registry_digest=pack.digest,
        outcomes=tuple(outcomes),
        truncated=bool(record.get("truncated")),
    )
