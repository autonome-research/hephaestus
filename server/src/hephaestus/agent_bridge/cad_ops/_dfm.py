"""``run_dfm``: resolve an artifact, load its process pack, report findings.

Three resolutions happen before a single predicate runs, and each one is
reported back so a finding can be re-derived later:

*artifact* — the default is the part's **current** successful build; an explicit
``artifact_ref`` is honoured verbatim, which is how a *transient preview* (a
build published under transient params, never current) gets checked; a
``project_snapshot_ref`` resolves the part's entry in that immutable manifest.
Whatever is chosen, its ref rides on the result and on every finding, so a DFM
report is never a claim about "the part" — it is a claim about those bytes.

*process* — the explicit ``process`` argument, else ``part.process`` from the
part's §5.2 manufacturing metadata. The metadata is read statically from the
part script (a literal ``part.process = "laser_cut"`` assignment): recovering it
would otherwise cost a full sandboxed rebuild, and the fields are design intent,
not geometry. A part that declares no process and gets no override is refused —
guessing a process would silently apply the wrong limits.

*tags* — the build's stored source map is the only place a published artifact's
tag names survive (BRep bytes carry no labels), so it is looked up from the
build record that published the artifact and handed to the evaluation. Findings
then read as tag names where the design has them and as artifact-bound
``{kind, solid_id, topology_index}`` descriptors everywhere else.

Predicates are untrusted registry content: they run only through
:func:`hephaestus.core.dfm.runner.evaluate_pack`, which ships them to the same
sandboxed executor a part script runs in under ``origin: "registry"`` — the
unsafe local backend refuses them outright, and no backend at all is a typed
``capability_not_available`` refusal rather than a quiet unsandboxed run.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.dfm import TopologyDescriptor, descriptors_from_source_map
from hephaestus.core.dfm.runner import DfmRequest, evaluate_pack
from hephaestus.core.dfm.types import DfmEvaluation
from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.namespace import METADATA_FIELDS
from hephaestus.core.project_store.projections import PROJECT_SNAPSHOT_REF_PREFIX
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.registry import DfmPack, RegistrySet
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["GEOMETRY_ARTIFACT_KINDS", "DfmOps", "DfmTarget", "script_metadata"]

#: Artifact kinds whose bytes are a BRep a DFM run can measure. An explicit
#: ``artifact_ref`` naming anything else (a render, a source map) is refused
#: rather than handed to the worker as if it were geometry.
GEOMETRY_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset({"build", "build-checkpoint"})


def script_metadata(script: str) -> dict[str, str]:
    """§5.2 metadata literals assigned in a part script (``part.<field> = "…"``).

    Only string *literals* are recovered: a computed metadata expression has no
    value until the script runs, and this read deliberately does not run it.
    """
    try:
        module = ast.parse(script)
    except SyntaxError:
        return {}
    found: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "part"
                and target.attr in METADATA_FIELDS
            ):
                found.setdefault(target.attr, value.value)
    return found


@dataclass(frozen=True)
class DfmTarget:
    """The resolved inputs of one DFM run: which bytes, which pack, which tags."""

    part: str
    process: str
    pack: DfmPack
    source_artifact_ref: str
    resolved_from: str  # "current" | "artifact_ref" | "project_snapshot"
    brep: bytes
    metadata: Mapping[str, str]
    material: Mapping[str, JSONValue] | None
    tags: Mapping[str, TopologyDescriptor]

    def request(self) -> DfmRequest:
        return DfmRequest(
            part=self.part,
            process=self.process,
            brep=self.brep,
            source_artifact_ref=self.source_artifact_ref,
            metadata=self.metadata,
            material=self.material,
            tags=self.tags,
        )


class DfmOps(CadOpsState):
    """``run_dfm`` and the artifact/process/tag resolution it stands on."""

    _registry_set: RegistrySet | None = None

    def registries(self) -> RegistrySet:
        """The project's verified registry set (loaded once per ops object)."""
        if self._registry_set is None:
            self._registry_set = RegistrySet.open(self._layout.root)
        return self._registry_set

    # -- the tool ----------------------------------------------------------

    def run_dfm(
        self,
        name: str,
        *,
        process: str | None = None,
        artifact_ref: str | None = None,
        project_snapshot_ref: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate the process rule pack against the resolved artifact."""
        target = self.dfm_target(
            name,
            process=process,
            artifact_ref=artifact_ref,
            project_snapshot_ref=project_snapshot_ref,
        )
        evaluation = self.evaluate_target(target)
        payload: dict[str, Any] = {"status": "ok", **evaluation.to_json()}
        payload["resolved_from"] = target.resolved_from
        payload["material"] = target.material
        return payload

    # -- resolution --------------------------------------------------------

    def dfm_target(
        self,
        name: str,
        *,
        process: str | None = None,
        artifact_ref: str | None = None,
        project_snapshot_ref: str | None = None,
    ) -> DfmTarget:
        """Resolve artifact bytes, rule pack, metadata, material and tags."""
        if artifact_ref is not None and project_snapshot_ref is not None:
            raise CadOpError(
                "invalid_params", "artifact_ref and project_snapshot_ref are mutually exclusive"
            )
        resolved_ref, resolved_from = self._resolve_artifact(
            name, artifact_ref=artifact_ref, project_snapshot_ref=project_snapshot_ref
        )
        metadata = self.part_metadata(name)
        chosen = (process or metadata.get("process", "")).strip()
        if not chosen:
            raise CadOpError(
                "invalid_params",
                f"part {name!r} declares no part.process and no process override was given; "
                "DFM limits are process-specific and are never guessed",
                data={"candidates": list(self.registries().dfm.processes())},
            )
        pack = self.registries().dfm.get(chosen)
        return DfmTarget(
            part=name,
            process=chosen,
            pack=pack,
            source_artifact_ref=resolved_ref,
            resolved_from=resolved_from,
            brep=self._artifact_bytes(resolved_ref),
            metadata=metadata,
            material=self._material_record(metadata),
            tags=self._tags_for(name, resolved_ref),
        )

    def evaluate_target(self, target: DfmTarget) -> DfmEvaluation:
        """Run every rule of the target's pack under the secure backend."""
        with self._scratch("heph-dfm-") as scratch:
            return evaluate_pack(
                target.request(),
                target.pack,
                backend=self._backend,
                scratch_root=Path(scratch),
            )

    def part_metadata(self, name: str) -> dict[str, str]:
        """The part's §5.2 metadata literals, read from its current script."""
        snapshot = self._publisher().parts.read_part(name)
        return script_metadata(snapshot.content)

    def _resolve_artifact(
        self, name: str, *, artifact_ref: str | None, project_snapshot_ref: str | None
    ) -> tuple[str, str]:
        if artifact_ref is not None:
            # Honoured verbatim — this is how a transient preview is checked.
            return artifact_ref, "artifact_ref"
        if project_snapshot_ref is not None:
            return self._snapshot_artifact(name, project_snapshot_ref), "project_snapshot"
        result = self._publisher().current_result(name)
        if result is None or result.artifact_ref is None:
            raise AddressingError(
                f"part {name!r} has no current successful build to check",
                selector=name,
                candidates=self._layout.part_names(),
            )
        return result.artifact_ref, "current"

    def _snapshot_artifact(self, name: str, snapshot_ref: str) -> str:
        if not snapshot_ref.startswith(PROJECT_SNAPSHOT_REF_PREFIX):
            raise CadOpError("invalid_params", f"{snapshot_ref} is not a project-snapshot ref")
        manifest = self._json_blob(snapshot_ref)
        parts_raw = manifest.get("parts")
        if not isinstance(parts_raw, dict):
            raise CadOpError("invalid_params", f"project snapshot {snapshot_ref} is malformed")
        entry = cast("Mapping[str, JSONValue]", parts_raw).get(name)
        ref = entry.get("artifact_ref") if isinstance(entry, dict) else None
        if not isinstance(ref, str):
            raise CadOpError(
                "invalid_params", f"project snapshot {snapshot_ref} carries no part {name!r}"
            )
        return ref

    def _artifact_bytes(self, ref: str) -> bytes:
        kind = ref.split(":")[1] if ref.count(":") == 3 and ref.startswith("artifact:") else ""
        if kind not in GEOMETRY_ARTIFACT_KINDS:
            raise CadOpError(
                "invalid_params",
                f"{ref!r} does not name build geometry "
                f"(expected one of {', '.join(sorted(GEOMETRY_ARTIFACT_KINDS))})",
            )
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_params", f"artifact {ref} is not durably stored")
        return self._store.blobs.get(blob)

    def _json_blob(self, ref: str) -> Mapping[str, JSONValue]:
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_params", f"artifact {ref} is not durably stored")
        raw: object = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):
            raise CadOpError("invalid_params", f"artifact {ref} is not a JSON object")
        return cast("Mapping[str, JSONValue]", raw)

    def _material_record(self, metadata: Mapping[str, str]) -> dict[str, JSONValue] | None:
        """The materials-registry record ``part.material_spec`` resolves to."""
        spec = metadata.get("material_spec", "")
        if not spec:
            return None
        material = self.registries().materials.match(spec)
        return None if material is None else dict(material.to_json())

    # -- tags: the build record that published these bytes ------------------

    def _tags_for(self, name: str, artifact_ref: str) -> dict[str, TopologyDescriptor]:
        """Tag descriptors of the build that produced ``artifact_ref`` (or none).

        Tag recovery is best-effort by construction: an artifact whose build
        record has aged out still gets checked, its findings simply address
        topology by index instead of by name.
        """
        source_map_ref = self._source_map_ref(name, artifact_ref)
        if source_map_ref is None:
            return {}
        blob = blob_hash_of_ref(source_map_ref)
        if not self._store.blobs.has(blob):
            return {}
        try:
            return descriptors_from_source_map(self._json_blob(source_map_ref))
        except (CadOpError, ValueError):  # pragma: no cover - stored maps are our own JSON
            return {}

    def _source_map_ref(self, name: str, artifact_ref: str) -> str | None:
        current = self._publisher().current_result(name)
        if current is not None and current.artifact_ref == artifact_ref:
            return current.source_map_ref
        # Not the current build: find the record blob that published these bytes.
        # ``publish_build`` links every build record to each evidence blob it
        # installed, so the artifact blob names its own build record — which is
        # what makes a *preview* artifact recover its tags durably.
        artifact_blob = blob_hash_of_ref(artifact_ref)
        for from_ref, to_ref in sorted(self._store.gc.links()):
            if to_ref != artifact_blob or not self._store.blobs.has(from_ref):
                continue
            try:
                record: object = json.loads(self._store.blobs.get(from_ref).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            fields = cast("Mapping[str, JSONValue]", record)
            if fields.get("part") != name or fields.get("artifact_ref") != artifact_ref:
                continue
            ref = fields.get("source_map_ref")
            if isinstance(ref, str):
                return ref
        return None
