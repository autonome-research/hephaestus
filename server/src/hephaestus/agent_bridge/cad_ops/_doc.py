"""``generate_doc``: BOM, assembly instructions and spec sheets (markdown + JSON).

Three documents, one rule: every line is derived from something the project can
show you.

* **bom** — one row per labeled solid group of the frozen artifact. Labels come
  from the build result's ``geometries`` rows (a reloaded BRep has no labels of
  its own), sizes are measured on the artifact, and the material row is the
  materials-registry record the part's free-text ``material_spec`` resolves to,
  which is also where density — and therefore the estimated mass — comes from.
  A spec that resolves to nothing says so; it never borrows a plausible record.
* **assembly_instructions** — ordered steps derived from the §5.2 metadata:
  a fabrication step per BOM row (the verb comes from ``part.process``), then
  the joint preparation and assembly steps from ``part.assembly_method`` /
  ``part.joint``, then the cross-part mates (other parts of this project that
  the metadata names), then finishing. The order is a fixed phase sequence and
  every phase is sorted, so the same project always produces the same steps in
  the same order.
* **spec** — the metadata, effective parameters, kernel metrics and CHECKS
  outcomes of exactly the frozen build, as one page.

Both files (``.md`` and ``.json``) are one deliverable written through the §7
export contract, so a document is a pinned, provenance-hashed export like any
other — not a chat message that happens to contain a table.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.kernel.metrics import bbox_mm, shape_volume
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.registry import Material, RegistrySet
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from ._base import CadOpError
from ._drawing import UNSTATED, FrozenMetadataOps, solid_labels
from ._exports import ExportOps, ExportOutput

__all__ = ["DOC_KINDS", "BomRow", "DocOps", "assembly_steps", "fabrication_verb"]

#: The document kinds ``tool_schema`` declares.
DOC_KINDS: Final[tuple[str, ...]] = ("bom", "assembly_instructions", "spec")

#: Inline ``markdown`` cap in the tool result; the file on disk is never cut.
MARKDOWN_INLINE_LIMIT: Final[int] = 20_000

#: Process keyword -> the verb a fabrication step uses. Matched as a substring
#: of the free-text ``part.process`` so "laser_cut, 6 mm ply" still resolves.
PROCESS_VERBS: Final[tuple[tuple[str, str], ...]] = (
    ("laser", "Laser-cut"),
    ("water", "Waterjet-cut"),
    ("plasma", "Plasma-cut"),
    ("router", "Rout"),
    ("cnc", "Machine"),
    ("mill", "Machine"),
    ("turn", "Turn"),
    ("fdm", "3D-print"),
    ("sla", "3D-print"),
    ("print", "3D-print"),
    ("cast", "Cast"),
    ("sheet", "Cut"),
)
DEFAULT_VERB: Final[str] = "Fabricate"

#: §5.2 metadata fields a spec sheet lists, in reading order.
SPEC_FIELDS: Final[tuple[str, ...]] = (
    "description",
    "material_spec",
    "process",
    "stock_form",
    "blank_size",
    "general_tolerance",
    "finish",
    "assembly_method",
    "joint",
)


def fabrication_verb(process: str) -> str:
    """The verb a fabrication step uses for a free-text ``part.process``."""
    lowered = process.lower()
    for keyword, verb in PROCESS_VERBS:
        if keyword in lowered:
            return verb
    return DEFAULT_VERB


@dataclass(frozen=True)
class BomRow:
    """One bill-of-materials line: a group of identical labeled solids."""

    item: int
    label: str
    quantity: int
    size_mm: tuple[float, float, float]
    volume_mm3: float
    material_spec: str
    material: Material | None
    stock_form: str
    blank_size: str

    @property
    def mass_g(self) -> float | None:
        """Estimated mass from the registry density (kg/m^3 x mm^3 → g)."""
        if self.material is None:
            return None
        return self.material.density * self.volume_mm3 * 1e-6

    def size_text(self) -> str:
        return " x ".join(f"{value:.1f}" for value in self.size_mm) + " mm"

    def stock_text(self) -> str:
        """The stock/blank the row is cut from: declared first, registry second."""
        if self.blank_size:
            return self.blank_size
        if self.material is not None and self.material.thicknesses:
            nearest = min(self.material.thicknesses, key=lambda t: abs(t - min(self.size_mm)))
            form = self.stock_form or (self.material.forms[0] if self.material.forms else "stock")
            return f"{nearest:g} mm {form}"
        return self.stock_form or UNSTATED

    def material_text(self) -> str:
        if self.material is None:
            return f"{self.material_spec or UNSTATED} (no registry match)"
        return f"{self.material.name} [{self.material.id}]"

    def to_json(self) -> dict[str, JSONValue]:
        mass = self.mass_g
        return {
            "item": self.item,
            "label": self.label,
            "quantity": self.quantity,
            "size_mm": [round(value, 4) for value in self.size_mm],
            "volume_mm3": round(self.volume_mm3, 4),
            "material_spec": self.material_spec,
            "material_id": None if self.material is None else self.material.id,
            "material_name": None if self.material is None else self.material.name,
            "density_kg_m3": None if self.material is None else self.material.density,
            "registry": None if self.material is None else self.material.registry,
            "registry_digest": None if self.material is None else self.material.digest,
            "stock": self.stock_text(),
            "mass_g": None if mass is None else round(mass, 3),
        }


@dataclass(frozen=True)
class Step:
    """One ordered assembly step: its phase, its text, and what it refers to."""

    phase: str
    text: str
    refers_to: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {"phase": self.phase, "text": self.text, "refers_to": list(self.refers_to)}


#: Assembly phases, in the order they are performed.
PHASES: Final[tuple[str, ...]] = ("fabricate", "prepare", "assemble", "mate", "finish")


def assembly_steps(
    part: str,
    rows: Sequence[BomRow],
    metadata: Mapping[str, str],
    *,
    sibling_parts: Sequence[str] = (),
) -> tuple[Step, ...]:
    """The ordered steps for one part, by rule (no free invention).

    Phase order is fixed and each phase's contents follow the BOM order or a
    sorted name order, so the sequence is a function of the evidence rather
    than of iteration order.
    """
    process = metadata.get("process", "")
    verb = fabrication_verb(process)
    steps: list[Step] = [
        Step(
            "fabricate",
            f"{verb} {row.quantity} x {row.label} at {row.size_text()} from {row.stock_text()}.",
            (row.label,),
        )
        for row in rows
    ]
    tolerance = metadata.get("general_tolerance", "").strip()
    if tolerance:
        steps.append(
            Step("prepare", f"Verify cut parts against the general tolerance {tolerance}.")
        )
    joint = metadata.get("joint", "").strip()
    if joint:
        steps.append(Step("prepare", f"Prepare the {joint} joint features before assembly."))
    method = metadata.get("assembly_method", "").strip()
    if method:
        steps.append(Step("assemble", f"Assemble {part} using {method}."))
    elif len(rows) > 1:
        steps.append(
            Step("assemble", f"Assemble the {len(rows)} fabricated groups of {part} in BOM order.")
        )
    for sibling in _referenced_parts(metadata, part, sibling_parts):
        steps.append(
            Step("mate", f"Mate {part} with {sibling} as the metadata states.", (sibling,))
        )
    finish = metadata.get("finish", "").strip()
    if finish:
        steps.append(Step("finish", f"Apply the specified finish: {finish}."))
    order = {phase: index for index, phase in enumerate(PHASES)}
    return tuple(sorted(steps, key=lambda step: order.get(step.phase, len(PHASES))))


def _referenced_parts(
    metadata: Mapping[str, str], part: str, sibling_parts: Sequence[str]
) -> tuple[str, ...]:
    """Other project parts this part's metadata names (sorted, deduplicated).

    This is the whole of the cross-part relationship the document claims: a
    part's own metadata naming another part of the same project. Nothing is
    inferred from geometry proximity, which would be a guess dressed as a fact.
    """
    haystack = " ".join(metadata.values()).lower()
    return tuple(
        sorted(
            {
                sibling
                for sibling in sibling_parts
                if sibling != part and sibling.lower() in haystack
            }
        )
    )


# --------------------------------------------------------------------------
# rendering


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return out


def _provenance_lines(part: str, source_ref: str, script_hash: str) -> list[str]:
    return [
        "",
        "## Provenance",
        "",
        f"- part: `{part}`",
        f"- source artifact: `{source_ref}`",
        f"- script sha-256: `{script_hash}`",
        "",
    ]


@dataclass
class _Document:
    """One rendered document: its markdown, its JSON body, and its item count."""

    markdown: str
    body: dict[str, JSONValue]
    items: int
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


# --------------------------------------------------------------------------
# the operation


class DocOps(ExportOps, FrozenMetadataOps):
    """``generate_doc``: BOM / assembly instructions / spec over a frozen artifact."""

    #: Lazily-loaded verified registry set (materials records for the BOM). Held
    #: per ops object; loading verifies every pinned registry's content hash.
    _doc_registry_set: RegistrySet | None = None

    def generate_doc(
        self,
        name: str,
        kind: str,
        *,
        artifact_ref: str | None = None,
        target: str | None = None,
        op_id: str,
    ) -> dict[str, Any]:
        """Write one document as a pinned markdown + JSON export pair."""
        if kind not in DOC_KINDS:
            raise CadOpError(
                "invalid_params",
                f"unknown doc kind {kind!r} (expected {', '.join(DOC_KINDS)})",
            )

        def produce(
            source_ref: str, scratch: Path
        ) -> tuple[Sequence[ExportOutput], Mapping[str, Any]]:
            document = self._render(name, kind, source_ref, scratch)
            outputs = (
                ExportOutput("md", document.markdown.encode("utf-8")),
                ExportOutput(
                    "json",
                    (json.dumps(document.body, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                ),
            )
            truncated = len(document.markdown) > MARKDOWN_INLINE_LIMIT
            extra: dict[str, Any] = {
                "status": "ok",
                "kind": kind,
                "items": document.items,
                "markdown": document.markdown[:MARKDOWN_INLINE_LIMIT],
                "markdown_truncated": truncated,
                **document.extra,
            }
            return outputs, extra

        result = self.wal_export(
            op_id=op_id,
            part=name,
            operation="generate_doc",
            variant=kind,
            payload={},
            artifact_ref=artifact_ref,
            target=target,
            stem=f"{name}-{kind}",
            produce=produce,
        )
        paths = cast("list[str]", result.get("paths", []))
        for path in paths:
            result["doc" if path.endswith(".md") else "json"] = path
        return result

    # -- rendering ---------------------------------------------------------

    def _render(self, name: str, kind: str, source_ref: str, scratch: Path) -> _Document:
        result = self._doc_result(name, source_ref)
        metadata = self.frozen_script_metadata(name, source_ref)
        script_hash = result.input_hashes.script if result is not None else "unavailable"
        if kind == "spec":
            return self._spec(name, source_ref, script_hash, result, metadata)
        rows = self._bom_rows(name, source_ref, result, metadata, scratch)
        if kind == "bom":
            return self._bom(name, source_ref, script_hash, rows, metadata)
        return self._assembly(name, source_ref, script_hash, rows, metadata)

    def _bom(
        self,
        name: str,
        source_ref: str,
        script_hash: str,
        rows: Sequence[BomRow],
        metadata: Mapping[str, str],
    ) -> _Document:
        lines = [f"# Bill of materials — {name}", ""]
        description = metadata.get("description", "").strip()
        if description:
            lines += [description, ""]
        table_rows = [
            [
                str(row.item),
                row.label,
                str(row.quantity),
                row.size_text(),
                row.material_text(),
                row.stock_text(),
                "—" if row.mass_g is None else f"{row.mass_g:.1f} g",
            ]
            for row in rows
        ]
        lines += _table(
            ("Item", "Label", "Qty", "Size (X x Y x Z)", "Material", "Stock", "Mass"), table_rows
        )
        total = sum(row.mass_g or 0.0 for row in rows)
        if total:
            lines += ["", f"Estimated total mass: {total:.1f} g (registry densities)."]
        lines += _provenance_lines(name, source_ref, script_hash)
        body: dict[str, JSONValue] = {
            "kind": "bom",
            "part": name,
            "source_artifact_ref": source_ref,
            "script_sha256": script_hash,
            "rows": [row.to_json() for row in rows],
            "total_mass_g": round(total, 3) if total else None,
        }
        return _Document("\n".join(lines), body, len(rows))

    def _assembly(
        self,
        name: str,
        source_ref: str,
        script_hash: str,
        rows: Sequence[BomRow],
        metadata: Mapping[str, str],
    ) -> _Document:
        steps = assembly_steps(name, rows, metadata, sibling_parts=self._layout.part_names())
        lines = [f"# Assembly instructions — {name}", ""]
        for field_name in ("process", "assembly_method", "joint"):
            value = metadata.get(field_name, "").strip()
            if value:
                lines.append(f"- **{field_name.replace('_', ' ')}**: {value}")
        if lines[-1] != "":
            lines.append("")
        for index, step in enumerate(steps, start=1):
            lines.append(f"{index}. ({step.phase}) {step.text}")
        if not steps:
            lines.append("_No assembly step is derivable: the part declares no metadata._")
        lines += _provenance_lines(name, source_ref, script_hash)
        body: dict[str, JSONValue] = {
            "kind": "assembly_instructions",
            "part": name,
            "source_artifact_ref": source_ref,
            "script_sha256": script_hash,
            "steps": [step.to_json() for step in steps],
        }
        return _Document("\n".join(lines), body, len(steps))

    def _spec(
        self,
        name: str,
        source_ref: str,
        script_hash: str,
        result: BuildResult | None,
        metadata: Mapping[str, str],
    ) -> _Document:
        lines = [f"# Specification — {name}", "", "## Metadata", ""]
        lines += _table(
            ("Field", "Value"),
            [
                (field_name, metadata.get(field_name, "").strip() or UNSTATED)
                for field_name in SPEC_FIELDS
            ],
        )
        params = dict(result.params) if result is not None else {}
        lines += ["", "## Parameters", ""]
        lines += (
            _table(("Name", "Effective"), [(key, f"{params[key]:g}") for key in sorted(params)])
            if params
            else ["_The part declares no parameters._"]
        )
        metrics = result.metrics if result is not None else None
        lines += ["", "## Metrics", ""]
        if metrics is None:
            lines.append("_No metrics are recorded for this artifact._")
        else:
            lines += _table(
                ("Metric", "Value"),
                [
                    ("solids", str(metrics.solids)),
                    ("faces", str(metrics.faces)),
                    ("bbox mm", " x ".join(f"{v:.1f}" for v in metrics.bbox_mm)),
                    ("volume mm^3", f"{metrics.volume_mm3:.1f}"),
                    ("sealed", str(metrics.sealed).lower()),
                    ("genus", str(metrics.genus)),
                ],
            )
        checks = dict(result.checks) if result is not None else {}
        lines += ["", "## Checks", ""]
        lines += (
            _table(
                ("Check", "Result", "Measured"),
                [
                    (
                        key,
                        "pass" if checks[key].passed else "FAIL",
                        json.dumps(checks[key].measured),
                    )
                    for key in sorted(checks)
                ],
            )
            if checks
            else ["_The part declares no CHECKS._"]
        )
        lines += _provenance_lines(name, source_ref, script_hash)
        body: dict[str, JSONValue] = {
            "kind": "spec",
            "part": name,
            "source_artifact_ref": source_ref,
            "script_sha256": script_hash,
            "metadata": {key: metadata.get(key, "") for key in SPEC_FIELDS},
            "params": {key: params[key] for key in sorted(params)},
            "metrics": None if metrics is None else metrics.to_json(),
            "checks": {key: checks[key].to_json() for key in sorted(checks)},
        }
        return _Document("\n".join(lines), body, len(checks))

    # -- inputs ------------------------------------------------------------

    def _bom_rows(
        self,
        name: str,
        source_ref: str,
        result: BuildResult | None,
        metadata: Mapping[str, str],
        scratch: Path,
    ) -> tuple[BomRow, ...]:
        """One row per group of identically labeled, identically sized solids."""
        shape: Any = load_brep_shape(
            self._store.blobs.get(blob_hash_of_ref(source_ref)), scratch_dir=scratch
        )
        solids: list[Any] = list(shape.solids())
        labels = solid_labels(result, len(solids))
        spec = metadata.get("material_spec", "").strip()
        material = self._material(spec)
        grouped: dict[tuple[str, tuple[float, float, float]], list[Any]] = {}
        order: list[tuple[str, tuple[float, float, float]]] = []
        for position, solid in enumerate(solids):
            label = labels[position] if position < len(labels) else f"solid#{position + 1}"
            base = label.split("#", 1)[0].split("[", 1)[0]
            size = cast(
                "tuple[float, float, float]",
                tuple(round(v, 3) for v in bbox_mm(solid)),
            )
            key = (base, size)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(solid)
        rows: list[BomRow] = []
        for item, key in enumerate(order, start=1):
            members = grouped[key]
            rows.append(
                BomRow(
                    item=item,
                    label=key[0],
                    quantity=len(members),
                    size_mm=key[1],
                    volume_mm3=sum(shape_volume(solid) for solid in members),
                    material_spec=spec,
                    material=material,
                    stock_form=metadata.get("stock_form", "").strip(),
                    blank_size=metadata.get("blank_size", "").strip(),
                )
            )
        return tuple(rows)

    def _material(self, spec: str) -> Material | None:
        """The materials-registry record a free-text spec resolves to, or None."""
        if not spec:
            return None
        if self._doc_registry_set is None:
            self._doc_registry_set = RegistrySet.open(self._layout.root)
        return self._doc_registry_set.materials.match(spec)

    def _doc_result(self, name: str, source_ref: str) -> BuildResult | None:
        result = self._publisher().current_result(name)
        return result if result is not None and result.artifact_ref == source_ref else None
