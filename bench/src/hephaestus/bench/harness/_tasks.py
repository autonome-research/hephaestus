"""The corpus task model: what one ``corpus/tasks/<id>/`` declares.

A task is a prompt, a tool-call budget, the CHECKS grading installs, the exports,
renders, DFM verdicts and drawing sheets grading must be able to produce, and the
seeded files a run may not edit its way past. Loading is strict — a task whose
id, spec or required check source is wrong fails here rather than mid-run.

``VALIDATION.md`` §1: every public task ships in **two spec variants**, and they
are never collapsed.

``prose`` (the default, and what every committed ``task.json`` declares)
    seeds without ``checks/``; the agent must infer the spec from the request.
    Measures *interpretation*.
``seeded`` (``<id>@seeded``, derived here — no duplicated task directory)
    installs the task's own acceptance checks into ``checks/`` at seed time as
    an independent spec, and lists them as protected paths so a run cannot edit
    its way to green. Measures *iterate-to-green*.

Deriving the seeded variant rather than committing a second task directory is
deliberate: the prompt, budget and acceptance checks have exactly one home, so
the two splits can never drift apart into different tasks — the only difference
between them is whether the spec was handed over.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS
from hephaestus.core.executor.namespace import METADATA_FIELDS
from hephaestus.geom.mesh import MESH_UNITS

__all__ = [
    "PROMPT_SUFFIXES",
    "SCAN_CHECK_KINDS",
    "SEEDED_SUFFIX",
    "SPECS",
    "SPEC_PROSE",
    "SPEC_SEEDED",
    "BenchTask",
    "ConstraintRequirement",
    "DfmRequirement",
    "DrawingRequirement",
    "ExportRequirement",
    "JointRequirement",
    "MetadataRequirement",
    "MotionCheckRequirement",
    "PoseRequirement",
    "RenderRequirement",
    "ScanRequirement",
    "base_task_id",
    "corpus_solutions_dir",
    "corpus_tasks_dir",
    "load_tasks",
    "seeded_prompt",
    "seeded_variant",
    "seeded_variant_id",
    "solution_dir",
    "task_ids",
]

#: ``task.json`` ``spec`` values (VALIDATION.md §1). Existing files omit the
#: field and are therefore ``prose`` — the historically baselined split.
SPEC_PROSE: str = "prose"
SPEC_SEEDED: str = "seeded"
SPECS: tuple[str, ...] = (SPEC_PROSE, SPEC_SEEDED)

#: Id suffix of the seeded variant of a public task (``bracket-101@seeded``).
SEEDED_SUFFIX: str = "@seeded"


def seeded_variant_id(task_id: str) -> str:
    """The seeded variant's id for a prose task id (idempotent)."""
    return task_id if task_id.endswith(SEEDED_SUFFIX) else task_id + SEEDED_SUFFIX


def base_task_id(task_id: str) -> str:
    """The prose id behind any variant id (``bracket-101@seeded`` -> ``bracket-101``)."""
    return task_id.split(SEEDED_SUFFIX, 1)[0]


#: Deterministic per-seed prompt suffixes. The seed varies *only* the closing
#: instruction, never the task requirements, so seeds measure run-to-run
#: variance rather than different tasks.
PROMPT_SUFFIXES: tuple[str, ...] = (
    "Work in millimetres. When you are done, summarise what you built and the "
    "checks you relied on.",
    "All dimensions are millimetres. Build the geometry before you report, and "
    "say which measurements you verified.",
    "Units are millimetres throughout. Verify your work with the tools before "
    "you finish, then summarise the result.",
    "Millimetres everywhere. Finish by stating the final dimensions you measured.",
)


def corpus_tasks_dir(root: Path | None = None) -> Path:
    """``corpus/tasks`` (the public split's task specs)."""
    return (root or repo_root()) / "corpus" / "tasks"


def corpus_solutions_dir(root: Path | None = None) -> Path:
    """``corpus/solutions`` (one reference implementation per task)."""
    return (root or repo_root()) / "corpus" / "solutions"


def solution_dir(task_id: str, *, solutions_dir: Path | None = None) -> Path:
    return (solutions_dir or corpus_solutions_dir()) / task_id


@dataclass(frozen=True)
class ExportRequirement:
    """One required export: format, layout and the byte-level acceptance test."""

    part: str
    fmt: str
    layout: str = "as_built"
    #: Required count of outermost closed profiles (DXF/SVG cut layouts only).
    profile_count: int | None = None
    min_bytes: int = 64
    #: DXF layer the profiles are counted on. A ``nested_sheet`` layout draws the
    #: stock rectangle too, and it encloses every profile — counting outermost
    #: components across all layers would report *one*. Set for nested layouts.
    profile_layer: str | None = None
    #: Stock the grader nests onto, as ``(width_mm, height_mm)``. It is passed to
    #: ``export_part``, so the layout is built on the blank the *task* declares
    #: and never on whatever the run happened to declare — then read back off the
    #: exported bytes (the ``BLANK`` rectangle) and used as the fit window for
    #: every profile. Whether the run declared this stock is a separate,
    #: separately named requirement (:class:`MetadataRequirement.blank_mm`);
    #: making it a precondition here failed correct runs as ``export_failed``
    #: (``nest-gusset``, gpt-5.6-sol 2026-07-26).
    blank_mm: tuple[float, float] | None = None
    blank_layer: str = "BLANK"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ExportRequirement:
        fmt = str(data["format"])
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"unknown export format {fmt!r}")
        raw_count = data.get("profile_count")
        raw_blank = data.get("blank_mm")
        blank: tuple[float, float] | None = None
        if raw_blank is not None:
            pair = [float(cast("float", v)) for v in cast("Sequence[Any]", raw_blank)]
            if len(pair) != 2:
                raise ValueError(f"blank_mm must be [width, height], got {raw_blank!r}")
            blank = (pair[0], pair[1])
        layer = data.get("profile_layer")
        if blank is not None and layer is None:
            raise ValueError(
                "blank_mm needs profile_layer: without it the blank rectangle is "
                "counted as a profile and the fit test is vacuous"
            )
        layout = str(data.get("layout", "as_built"))
        if blank is not None and layout != "nested_sheet":
            # ``export_part`` ignores ``blank`` unless it is nesting, so a blank
            # on any other layout would gate nothing while reading as though it
            # did — and the BLANK layer it then looks for is never drawn.
            raise ValueError(
                f"blank_mm is only meaningful on a nested_sheet layout, not {layout!r}"
            )
        return cls(
            part=str(data["part"]),
            fmt=fmt,
            layout=layout,
            profile_count=None if raw_count is None else int(cast("int", raw_count)),
            min_bytes=int(cast("int", data.get("min_bytes", 64))),
            profile_layer=None if layer is None else str(layer),
            blank_mm=blank,
            blank_layer=str(data.get("blank_layer", "BLANK")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "format": self.fmt,
            "layout": self.layout,
            "profile_count": self.profile_count,
            "min_bytes": self.min_bytes,
            "profile_layer": self.profile_layer,
            "blank_mm": None if self.blank_mm is None else list(self.blank_mm),
            "blank_layer": self.blank_layer,
        }


@dataclass(frozen=True)
class DfmRequirement:
    """One required DFM verdict: named rules must find nothing on the built part.

    The grader runs ``run_dfm`` itself, on a probed secure backend, against the
    part's current build — so the verdict is measured on the graded geometry and
    never on the run's own report of it. ``clean_rules`` is the acceptance test:
    a listed rule that produces a finding (or that fails to evaluate at all)
    fails the task. Rules outside the list are recorded, not gated: the point of
    a repair task is the violations it names, not the whole pack.

    ``process`` is **required, and is the task's declaration — never the run's**
    (2026-07-26 bench defect). It used to be an optional override falling back to
    the part's ``part.process``, which made the whole verdict conditional on the
    run remembering to author that field: ``run_dfm`` refuses to guess a process,
    correctly, so a run that omitted it failed as ``dfm_failed:<part>`` and the
    DFM rules — the actual subject of the task — never evaluated at all. Measured
    on ``print-bracket`` (``gpt-5.6-sol``, which authored the field in seed 1 and
    not in seed 2): the same model, the same geometry, graded on different
    properties. Naming the process here makes the pack run on every submission.
    Whether the part *declares* its own process is a separate, legitimate
    requirement, and where a task asks for it it is gated as its own
    :class:`MetadataRequirement`, failing under a name that says so.
    """

    part: str
    #: Rule ids that must produce zero findings (and must have evaluated).
    clean_rules: tuple[str, ...]
    #: The process pack to evaluate. Declared by the task, never inferred.
    process: str

    def __post_init__(self) -> None:
        if not self.process:
            raise ValueError(
                f"DFM requirement for part {self.part!r} declares no process: name the "
                "rule pack on the requirement, so the rules evaluate on every run "
                "instead of only on runs that authored part.process"
            )

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DfmRequirement:
        rules = tuple(str(r) for r in cast("Sequence[Any]", data.get("clean_rules", [])))
        if not rules:
            raise ValueError("a DFM requirement with no clean_rules gates nothing")
        return cls(
            part=str(data["part"]),
            clean_rules=rules,
            process=str(data.get("process", "")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "clean_rules": list(self.clean_rules),
            "process": self.process,
        }


@dataclass(frozen=True)
class DrawingRequirement:
    """One required drawing sheet and the strings its PDF text layer must carry.

    ``required_texts`` are exact strings — dimension texts as
    :func:`hephaestus.agent_bridge.cad_ops.dimension_text` prints them, and
    title-block values as the part's §5.2 metadata declares them. They are
    extracted from the PDF the grader generates from the graded geometry, so a
    sheet that "says" the right numbers only passes when the numbers are really
    in its text layer and really came out of the run's own model.
    """

    part: str
    kind: str = "dimensioned"
    sheet: str = "A4"
    required_texts: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DrawingRequirement:
        texts = tuple(str(t) for t in cast("Sequence[Any]", data.get("required_texts", [])))
        if not texts:
            raise ValueError("a drawing requirement with no required_texts gates nothing")
        return cls(
            part=str(data["part"]),
            kind=str(data.get("kind", "dimensioned")),
            sheet=str(data.get("sheet", "A4")),
            required_texts=texts,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "kind": self.kind,
            "sheet": self.sheet,
            "required_texts": list(self.required_texts),
        }


@dataclass(frozen=True)
class ConstraintRequirement:
    """One declared cross-part constraint the graded assembly must satisfy.

    ``ASSEMBLY.md`` §3: an assembly task scores on **declared fits holding**, not
    on a volume window. The entry is the task's own — it is declared into the
    graded project's constraint set and evaluated through the same engine path
    the ``check_assembly`` tool uses, exactly as the task's CHECKS are installed
    over whatever the run authored. Nothing in the verdict comes from what the
    run said about its own mates; a run that declared the same id gets the task's
    version of it.

    ``expect`` is the state the graded geometry must produce. It defaults to
    ``satisfied`` and is spelled out rather than assumed, because ``unresolvable``
    is a real third state: a task may legitimately require that a mate be
    *checkable*, and a grader that treated "could not measure" as "measured fine"
    would be scoring the absence of evidence.
    """

    #: The ``ASSEMBLY.md`` §1 entry, minus provenance (supplied below).
    entry: Mapping[str, Any]
    expect: str = "satisfied"

    @property
    def id(self) -> str:
        return str(self.entry["id"])

    def declaration(self) -> dict[str, Any]:
        """The entry as declared into the graded project.

        Provenance is the task's: the constraint is part of the acceptance spec,
        so it is an assumption *of the task* with a reason naming that. Inventing
        a requirement citation the project does not carry would be the dishonest
        alternative.
        """
        declared = dict(self.entry)
        declared.setdefault(
            "provenance",
            {"assumed": True, "reason": "declared by the bench task's acceptance spec"},
        )
        return declared

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ConstraintRequirement:
        raw = data.get("entry")
        if not isinstance(raw, dict):
            raise ValueError("a constraint requirement needs an 'entry' object (ASSEMBLY.md §1)")
        entry = cast("Mapping[str, Any]", raw)
        for field in ("id", "kind", "a", "b"):
            if not entry.get(field):
                raise ValueError(f"constraint requirement entry is missing {field!r}")
        expect = str(data.get("expect", "satisfied"))
        if expect not in ("satisfied", "violated", "unresolvable"):
            raise ValueError(
                f"constraint requirement expect must be a constraint state, got {expect!r}"
            )
        return cls(entry=dict(entry), expect=expect)

    def to_json(self) -> dict[str, Any]:
        return {"entry": dict(self.entry), "expect": self.expect}


#: What the acceptance spec's provenance says on every kinematic entry it owns
#: (the :meth:`ConstraintRequirement.declaration` rule: the entry is part of
#: the task, so it is an assumption *of the task*, honestly recorded as one).
_TASK_PROVENANCE: Mapping[str, Any] = {
    "assumed": True,
    "reason": "declared by the bench task's acceptance spec",
}

#: ``KINEMATICS.md`` §4's closed sweep-verdict vocabulary, restated here so a
#: task cannot expect a state the engine can never report (and so ``expect``
#: typos fail at load, not as an eternally red grade).
SWEEP_VERDICTS: tuple[str, ...] = (
    "holds_at_samples",
    "satisfied",
    "not_reached_at_samples",
    "violated",
    "unresolvable",
)


@dataclass(frozen=True)
class JointRequirement:
    """One joint the task's acceptance declares over the graded geometry.

    ``KINEMATICS.md`` §6 (bench): mechanism tasks are graded through the same
    engine path ``check_motion`` uses, and — exactly as with
    :class:`ConstraintRequirement` — the entries are the TASK's own, installed
    over whatever the run declared, so a run cannot pass by declaring a
    shorter travel (or none). The joint's anchors name the run's parts and
    tags, so what is graded is still the run's geometry: a run that never
    tags its interfaces fails as unresolvable, honestly.
    """

    #: The ``KINEMATICS.md`` §1 entry, minus provenance (supplied below).
    entry: Mapping[str, Any]

    @property
    def id(self) -> str:
        return str(self.entry["id"])

    def declaration(self) -> dict[str, Any]:
        """The entry as declared into the graded project (task provenance)."""
        declared = dict(self.entry)
        declared.setdefault("provenance", dict(_TASK_PROVENANCE))
        return declared

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> JointRequirement:
        raw = data.get("entry")
        if not isinstance(raw, dict):
            raise ValueError("a joint requirement needs an 'entry' object (KINEMATICS.md §1)")
        entry = cast("Mapping[str, Any]", raw)
        for field in ("id", "kind", "parent", "child"):
            if not entry.get(field):
                raise ValueError(f"joint requirement entry is missing {field!r}")
        return cls(entry=dict(entry))

    def to_json(self) -> dict[str, Any]:
        return {"entry": dict(self.entry)}


@dataclass(frozen=True)
class PoseRequirement:
    """One named pose the task's acceptance declares (``KINEMATICS.md`` §3).

    The pose must come back ``resolved`` from the engine evaluation: a pose a
    run's geometry cannot take (a derived or bound value outside the joint's
    travel) is that mechanism failing its travel requirement, under the
    engine's own named reason. Pose-bound constraints then reference these
    ids, so the closure-fit vocabulary ("engages within 0.1 mm at p-closed")
    grades through :class:`ConstraintRequirement` unchanged.
    """

    #: The ``KINEMATICS.md`` §3 entry, minus provenance (supplied below).
    entry: Mapping[str, Any]

    @property
    def id(self) -> str:
        return str(self.entry["id"])

    def declaration(self) -> dict[str, Any]:
        """The entry as declared into the graded project (task provenance)."""
        declared = dict(self.entry)
        declared.setdefault("provenance", dict(_TASK_PROVENANCE))
        return declared

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> PoseRequirement:
        raw = data.get("entry")
        if not isinstance(raw, dict):
            raise ValueError("a pose requirement needs an 'entry' object (KINEMATICS.md §3)")
        entry = cast("Mapping[str, Any]", raw)
        if not entry.get("id"):
            raise ValueError("pose requirement entry is missing 'id'")
        if not isinstance(entry.get("joints"), dict):
            # An empty binding is legal §3 ("everything as built") but a task
            # pose exists to pin a configuration; requiring the field spelled
            # out keeps the acceptance readable and typo-proof.
            raise ValueError("pose requirement entry needs a 'joints' object (KINEMATICS.md §3)")
        return cls(entry=dict(entry))

    def to_json(self) -> dict[str, Any]:
        return {"entry": dict(self.entry)}


@dataclass(frozen=True)
class MotionCheckRequirement:
    """One motion check the task's acceptance declares and grades on.

    ``expect`` names the verdict the graded geometry must produce, from §4's
    closed set. It defaults per kind to the SUCCESS spelling — the universal
    kinds succeed as ``holds_at_samples`` (never "holds": samples are
    evidence, not a continuous guarantee), ``reach`` as ``satisfied`` (one
    achieving sample is proof) — and is validated against the whole set, so a
    task may also legitimately require a violation (a fixture that must
    interfere) without the grader conflating that with success.
    """

    #: The ``KINEMATICS.md`` §4 entry, minus provenance (supplied below).
    entry: Mapping[str, Any]
    expect: str = "holds_at_samples"

    @property
    def id(self) -> str:
        return str(self.entry["id"])

    def declaration(self) -> dict[str, Any]:
        """The entry as declared into the graded project (task provenance)."""
        declared = dict(self.entry)
        declared.setdefault("provenance", dict(_TASK_PROVENANCE))
        return declared

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> MotionCheckRequirement:
        raw = data.get("entry")
        if not isinstance(raw, dict):
            raise ValueError(
                "a motion-check requirement needs an 'entry' object (KINEMATICS.md §4)"
            )
        entry = cast("Mapping[str, Any]", raw)
        for field in ("id", "kind", "sweep"):
            if not entry.get(field):
                raise ValueError(f"motion-check requirement entry is missing {field!r}")
        default = "satisfied" if str(entry["kind"]) == "reach" else "holds_at_samples"
        expect = str(data.get("expect", default))
        if expect not in SWEEP_VERDICTS:
            raise ValueError(
                f"motion-check requirement expect must be one of {list(SWEEP_VERDICTS)}, "
                f"got {expect!r} (KINEMATICS.md §4: the verdict vocabulary is closed)"
            )
        return cls(entry=dict(entry), expect=expect)

    def to_json(self) -> dict[str, Any]:
        return {"entry": dict(self.entry), "expect": self.expect}


#: The closed ``scan_requirements`` check vocabulary (``MESH_INGEST.md`` §7.5).
#: Two kinds, and both are FUNCTIONAL: they measure the delivered part against
#: the scan the task seeded, never against the reference solution's geometry.
#: A third kind is an amendment, not a keyword argument.
SCAN_CHECK_KINDS: Final[tuple[str, ...]] = ("clearance_min", "deviation_max")


@dataclass(frozen=True)
class ScanRequirement:
    """One scan-fit property the graded part must have (``MESH_INGEST.md`` §7.5).

    Graded **through the engine path** — the same ``compare_to_scan`` the model
    calls, over the same confined read and the same §1.5 canonicalization a
    build would run — never from anything the run reported about its own fit.

    Every field the check needs is required and none is defaulted, which is the
    whole point of :meth:`from_json`'s validation: a ``clearance_min`` with no
    ``min_mm`` is a requirement that cannot fail, and a requirement that cannot
    fail is worse than no requirement at all (``VALIDATION.md`` §1's functional-
    check rule, and §82-98's named-tolerance rule).

    ``units`` is required for the same reason it is required everywhere else in
    Stage 12: STL/PLY/OBJ/OFF/XYZ carry no unit, and a default here would be the
    acceptance guessing a scale (``MESH_INGEST.md`` §1.3).

    What this vocabulary deliberately CANNOT express is a fit: a clearance is a
    geometric distance at named samples, and no entry here may be read as
    evidence that a socket fits a limb (§11.3).
    """

    part: str
    scan: str
    units: str
    kind: str
    #: ``clearance_min``: the closest any sampled scan vertex may come to the
    #: part. Read from ``scan_to_part_min_mm``, which is exact.
    min_mm: float | None = None
    #: ``deviation_max``: the furthest any sampled scan vertex may be from it.
    max_mm: float | None = None
    align: str = "as_posed"
    note: str = ""

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ScanRequirement:
        for field_name in ("part", "scan", "units", "kind"):
            if not data.get(field_name):
                raise ValueError(f"a scan requirement needs {field_name!r} (MESH_INGEST.md §7.5)")
        kind = str(data["kind"])
        if kind not in SCAN_CHECK_KINDS:
            raise ValueError(
                f"scan requirement kind must be one of {list(SCAN_CHECK_KINDS)}, got "
                f"{kind!r} (MESH_INGEST.md §7.5: the vocabulary is closed)"
            )
        units = str(data["units"])
        if units not in MESH_UNITS:
            raise ValueError(
                f"scan requirement units must be one of {list(MESH_UNITS)}, got {units!r} "
                "— a scan carries none and the engine is millimetres throughout "
                "(MESH_INGEST.md §1.3)"
            )
        align = str(data.get("align", "as_posed"))
        if align not in ("as_posed", "declared"):
            raise ValueError(
                f"scan requirement align must be 'as_posed' or 'declared', got {align!r}; "
                "'principal' is refused against a scan by name (MESH_INGEST.md §6.5)"
            )
        needed = "min_mm" if kind == "clearance_min" else "max_mm"
        if data.get(needed) is None:
            raise ValueError(
                f"a {kind!r} scan requirement needs {needed!r}: a check without its "
                "named tolerance cannot fail, which is worse than no check "
                "(VALIDATION.md §1, MESH_INGEST.md §7.5)"
            )
        return cls(
            part=str(data["part"]),
            scan=str(data["scan"]),
            units=units,
            kind=kind,
            min_mm=None if data.get("min_mm") is None else float(cast("float", data["min_mm"])),
            max_mm=None if data.get("max_mm") is None else float(cast("float", data["max_mm"])),
            align=align,
            note=str(data.get("note", "")),
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "part": self.part,
            "scan": self.scan,
            "units": self.units,
            "kind": self.kind,
            "align": self.align,
        }
        if self.min_mm is not None:
            out["min_mm"] = self.min_mm
        if self.max_mm is not None:
            out["max_mm"] = self.max_mm
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class MetadataRequirement:
    """§5.2 manufacturing metadata the graded part must really carry.

    Authored metadata is what a shop is handed — the material to buy, the
    process to run it on, the tolerance to hold — so a task whose deliverable is
    a drawing has to gate it. It is gated **structurally**, never as prose: a
    listed field must be non-empty, ``process`` must equal the process token the
    registry packs are keyed by, and ``material_id`` must be the materials
    registry record the free-text ``material_spec`` resolves to. Any wording
    that names the right material passes; matching an author's exact sentence
    is not an engineering property and is not asked for. (The audit of
    2026-07-26 introduced this to replace a verbatim title-block string match in
    ``drawing-shelf``, which failed correct runs for punctuation.)

    This is also where "the part must declare its process" belongs, and the only
    place it belongs: a :class:`DfmRequirement` names its own process, so the
    rule pack is never hostage to the run having authored ``part.process``. A
    task that asks for the declaration gates it here, where the failure reads
    ``metadata_process:<part>:unstated!=fdm`` — which says what is missing —
    rather than as an unresolvable-process refusal inside the DFM check.

    ``blank_mm`` gates the declared stock size the same way: the free-text
    ``part.blank_size`` must *name* that ``W x H`` blank, whatever else the
    sentence says. It exists for the same reason: "the part declares its stock"
    used to be an unnamed precondition of nested-sheet grading and surfaced as
    ``export_failed`` on a run whose own nested export had succeeded
    (``VALIDATION.md`` §1 — a check fails for the reason it is named after).
    """

    part: str
    #: Metadata fields that must be present and non-empty.
    required_fields: tuple[str, ...] = ()
    #: Required ``part.process`` token (registry pack id), if any.
    process: str | None = None
    #: Materials-registry id ``part.material_spec`` must resolve to, if any.
    material_id: str | None = None
    #: Stock blank ``part.blank_size`` must name, as ``(width_mm, height_mm)``.
    blank_mm: tuple[float, float] | None = None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> MetadataRequirement:
        fields = tuple(str(f) for f in cast("Sequence[Any]", data.get("required_fields", [])))
        unknown = [field for field in fields if field not in METADATA_FIELDS]
        if unknown:
            raise ValueError(f"unknown metadata fields {unknown} (script contract §5.2)")
        process = data.get("process")
        material = data.get("material_id")
        raw_blank = data.get("blank_mm")
        blank: tuple[float, float] | None = None
        if raw_blank is not None:
            pair = [float(cast("float", v)) for v in cast("Sequence[Any]", raw_blank)]
            if len(pair) != 2:
                raise ValueError(f"blank_mm must be [width, height], got {raw_blank!r}")
            blank = (pair[0], pair[1])
            if "blank_size" not in fields:
                # Absent and wrong are two failures and get two names; the
                # "absent" half is what ``required_fields`` is for.
                raise ValueError("blank_mm needs 'blank_size' in required_fields")
        if not fields and process is None and material is None:
            raise ValueError("a metadata requirement with nothing required gates nothing")
        return cls(
            part=str(data["part"]),
            required_fields=fields,
            process=None if process is None else str(process),
            material_id=None if material is None else str(material),
            blank_mm=blank,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "required_fields": list(self.required_fields),
            "process": self.process,
            "material_id": self.material_id,
            "blank_mm": None if self.blank_mm is None else list(self.blank_mm),
        }


@dataclass(frozen=True)
class RenderRequirement:
    """One required render (e.g. the ``+Z`` midplane section of an enclosure)."""

    part: str
    channel: str = "rgb"
    section_plane: str | None = None
    views: tuple[str, ...] = ("iso",)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> RenderRequirement:
        raw_views = data.get("views")
        views = (
            tuple(str(v) for v in cast("Sequence[Any]", raw_views))
            if isinstance(raw_views, list)
            else ("iso",)
        )
        plane = data.get("section_plane")
        return cls(
            part=str(data["part"]),
            channel=str(data.get("channel", "rgb")),
            section_plane=None if plane is None else str(plane),
            views=views,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "channel": self.channel,
            "section_plane": self.section_plane,
            "views": list(self.views),
        }


@dataclass(frozen=True)
class BenchTask:
    """One ``corpus/tasks/<id>/`` specification."""

    id: str
    directory: Path
    prompt: str
    budget_tool_calls: int
    required_checks: tuple[str, ...] = ()
    exports: tuple[ExportRequirement, ...] = ()
    renders: tuple[RenderRequirement, ...] = ()
    #: Stage 6 manufacturing acceptance: DFM verdicts and drawing sheets the
    #: grader produces itself from the graded geometry.
    dfm: tuple[DfmRequirement, ...] = ()
    drawings: tuple[DrawingRequirement, ...] = ()
    #: §5.2 manufacturing metadata the graded parts must carry (structural: a
    #: registry-resolvable material and a process token, never authored prose).
    metadata: tuple[MetadataRequirement, ...] = ()
    #: ``ASSEMBLY.md`` §3: declared mates the grader evaluates through the engine.
    constraints: tuple[ConstraintRequirement, ...] = ()
    #: ``KINEMATICS.md`` §6 (Stage 9C, corpus v3): the declared mechanism the
    #: grader installs and evaluates through the same engine path
    #: ``check_motion`` uses — joints, named poses (which the task's
    #: pose-bound constraints reference), and sampled motion checks.
    joints: tuple[JointRequirement, ...] = ()
    poses: tuple[PoseRequirement, ...] = ()
    motion_checks: tuple[MotionCheckRequirement, ...] = ()
    #: ``MESH_INGEST.md`` §7.5 (Stage 12C, corpus v5): scan-fit properties the
    #: grader measures through ``compare_to_scan`` against the scan the task
    #: seeded into ``imports/``.
    scans: tuple[ScanRequirement, ...] = ()
    #: Seeded, task-owned files (inspection gauges, broken fixtures) restored
    #: from ``seed/`` before grading, so a run cannot pass by editing them.
    protected_paths: tuple[str, ...] = ()
    #: Free-text note kept in the archive (never shown to the model).
    notes: str = ""
    #: ``EXTERNAL_EVAL.md`` §5: the single part this task is graded on. When
    #: set (converted CADGenBench tasks name their ``candidate``), the grader
    #: fails only on THIS part's build; other parts' failures are recorded as
    #: facts, never fail reasons — a model probing geometry with scratch parts
    #: is doing good work. Corpus tasks leave it unset: there, the multi-part
    #: project is the deliverable and every part's build is graded.
    deliverable: str | None = None
    #: ``VALIDATION.md`` §1 spec variant: ``prose`` (infer it) or ``seeded``
    #: (the acceptance checks are installed as an independent spec).
    spec: str = SPEC_PROSE

    def declared_parts(self) -> frozenset[str]:
        """Every part the task's own acceptance names.

        The union of the ``part`` fields across export/render/DFM/drawing/
        metadata requirements plus the part component of every constraint
        anchor. This IS the task's deliverable set: grading fails on these
        parts' builds, while an undeclared scratch part's failure is a
        recorded fact (2026-08-02 corpus autopsy — models probe geometry
        with throwaway parts, and 2 of 12 nest-gusset/print-bracket failures
        were probe-part casualties on otherwise-correct deliverables).
        """
        names: set[str] = set()
        for req in (*self.exports, *self.renders, *self.dfm, *self.drawings, *self.metadata):
            names.add(req.part)
        for constraint in self.constraints:
            for side in ("a", "b"):
                anchor = str(constraint.entry.get(side, ""))
                if anchor:
                    names.add(anchor.split(":", 1)[0])
        # Kinematic acceptance names parts through joint anchors and motion
        # check anchors, exactly as constraints do: the graded mechanism's
        # parts are deliverables the grader must build.
        for joint in self.joints:
            for side in ("parent", "child"):
                anchor = str(joint.entry.get(side, ""))
                if anchor:
                    names.add(anchor.split(":", 1)[0])
        for scan in self.scans:
            names.add(scan.part)
        for check in self.motion_checks:
            for field_name in ("a", "b", "anchor"):
                anchor = str(check.entry.get(field_name, "") or "")
                if anchor:
                    names.add(anchor.split(":", 1)[0])
        # Parts the task's OWN check sources address ("<part>/<selector>"
        # string literals) are declared too: gauge parts like bracket-101's
        # hole_gauge exist only inside the acceptance checks, and a snapshot
        # scoped without them would fail the checks that measure through them.
        # Check sources are task-authored (trusted), so a lexical scan is an
        # honest reading of what they measure.
        for source in self.check_sources().values():
            for head in re.findall(r'["\']([A-Za-z0-9_-]+)/', source):
                names.add(head)
        return frozenset(name for name in names if name)

    @property
    def seed_dir(self) -> Path:
        return self.directory / "seed"

    @property
    def checks_dir(self) -> Path:
        return self.directory / "checks"

    @property
    def base_id(self) -> str:
        """The prose id this task is a variant of (its own id when prose)."""
        return base_task_id(self.id)

    @property
    def is_seeded(self) -> bool:
        return self.spec == SPEC_SEEDED

    @property
    def seeded_check_paths(self) -> tuple[str, ...]:
        """Project-relative paths of the acceptance checks seeded as the spec."""
        if not self.is_seeded:
            return ()
        return tuple(f"checks/{name}.py" for name in self.required_checks)

    def check_sources(self) -> dict[str, str]:
        """``{check file stem: source}`` for every required CHECKS file."""
        sources: dict[str, str] = {}
        for name in self.required_checks:
            path = self.checks_dir / f"{name}.py"
            if not path.is_file():
                raise FileNotFoundError(f"task {self.id}: required check source {path} is missing")
            sources[name] = path.read_text(encoding="utf-8")
        return sources

    def protected_sources(self) -> dict[str, bytes]:
        """``{project-relative path: canonical bytes}`` for every protected path.

        Ordinary protected paths (gauges, broken fixtures) come from ``seed/``.
        A seeded variant's acceptance checks come from the task's own
        ``checks/`` tree — the same bytes grading installs — so the restore path
        is one mechanism for both, and the spec a seeded run was given is the
        spec it is graded against.
        """
        seeded_checks = set(self.seeded_check_paths)
        sources: dict[str, bytes] = {}
        check_sources = self.check_sources() if seeded_checks else {}
        for rel in self.protected_paths:
            if rel in seeded_checks:
                sources[rel] = check_sources[Path(rel).stem].encode("utf-8")
                continue
            path = self.seed_dir / rel
            if not path.is_file():
                raise FileNotFoundError(
                    f"task {self.id}: protected path {rel!r} is not in {self.seed_dir}"
                )
            sources[rel] = path.read_bytes()
        return sources

    @classmethod
    def load(cls, directory: Path) -> BenchTask:
        spec_path = directory / "task.json"
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{spec_path}: task spec must be a JSON object")
        data = cast("dict[str, Any]", raw)
        task_id = str(data["id"])
        if task_id != directory.name:
            raise ValueError(
                f"{spec_path}: id {task_id!r} does not match directory {directory.name!r}"
            )
        spec = str(data.get("spec", SPEC_PROSE))
        if spec not in SPECS:
            raise ValueError(f"{spec_path}: spec must be one of {list(SPECS)}, got {spec!r}")
        checks_raw = data.get("required_checks", [])
        exports_raw = data.get("export_requirements", [])
        renders_raw = data.get("render_requirements", [])
        dfm_raw = data.get("dfm_requirements", [])
        drawings_raw = data.get("drawing_requirements", [])
        metadata_raw = data.get("metadata_requirements", [])
        constraints_raw = data.get("constraint_requirements", [])
        joints_raw = data.get("joint_requirements", [])
        poses_raw = data.get("pose_requirements", [])
        motion_checks_raw = data.get("motion_check_requirements", [])
        scans_raw = data.get("scan_requirements", [])
        task = cls(
            id=task_id,
            directory=directory,
            prompt=str(data["prompt"]),
            budget_tool_calls=int(cast("int", data["budget_tool_calls"])),
            required_checks=tuple(str(name) for name in cast("Sequence[Any]", checks_raw)),
            exports=tuple(
                ExportRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", exports_raw)
            ),
            renders=tuple(
                RenderRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", renders_raw)
            ),
            dfm=tuple(
                DfmRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", dfm_raw)
            ),
            drawings=tuple(
                DrawingRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", drawings_raw)
            ),
            metadata=tuple(
                MetadataRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", metadata_raw)
            ),
            constraints=tuple(
                ConstraintRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", constraints_raw)
            ),
            joints=tuple(
                JointRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", joints_raw)
            ),
            poses=tuple(
                PoseRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", poses_raw)
            ),
            motion_checks=tuple(
                MotionCheckRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", motion_checks_raw)
            ),
            scans=tuple(
                ScanRequirement.from_json(cast("Mapping[str, Any]", item))
                for item in cast("Sequence[Any]", scans_raw)
            ),
            protected_paths=tuple(
                str(item) for item in cast("Sequence[Any]", data.get("protected_paths", []))
            ),
            notes=str(data.get("notes", "")),
            spec=spec,
            deliverable=(None if data.get("deliverable") is None else str(data["deliverable"])),
        )
        task.check_sources()  # fail fast on a task whose check source is missing
        return task

    def to_json(self) -> dict[str, Any]:
        # ``deliverable`` is omitted when unset so a corpus task's serialized
        # spec is byte-identical to what it was before EXTERNAL_EVAL.md §5.
        extra = {} if self.deliverable is None else {"deliverable": self.deliverable}
        return {
            **extra,
            "id": self.id,
            "spec": self.spec,
            "prompt": self.prompt,
            "budget_tool_calls": self.budget_tool_calls,
            "required_checks": list(self.required_checks),
            "export_requirements": [e.to_json() for e in self.exports],
            "render_requirements": [r.to_json() for r in self.renders],
            "dfm_requirements": [d.to_json() for d in self.dfm],
            "drawing_requirements": [d.to_json() for d in self.drawings],
            "metadata_requirements": [m.to_json() for m in self.metadata],
            "constraint_requirements": [c.to_json() for c in self.constraints],
            "joint_requirements": [j.to_json() for j in self.joints],
            "pose_requirements": [p.to_json() for p in self.poses],
            "motion_check_requirements": [m.to_json() for m in self.motion_checks],
            "scan_requirements": [s.to_json() for s in self.scans],
            "protected_paths": list(self.protected_paths),
        }


def seeded_variant(task: BenchTask) -> BenchTask:
    """The ``<id>@seeded`` variant of a prose task (VALIDATION.md §1).

    Same directory, same prompt, same budget and the same acceptance checks —
    the only difference is that the checks are installed into ``checks/`` at
    seed time (see :func:`~._seed.seed_project`) and are protected, so the run
    iterates against an independent spec instead of inventing one.
    """
    if task.is_seeded:
        return task
    if not task.required_checks:
        raise ValueError(f"task {task.id}: a seeded variant needs acceptance checks to install")
    task.check_sources()  # fail fast: the spec a seeded run is given must exist
    checks = tuple(f"checks/{name}.py" for name in task.required_checks)
    return replace(
        task,
        id=seeded_variant_id(task.id),
        spec=SPEC_SEEDED,
        protected_paths=task.protected_paths + checks,
    )


def task_ids(*, tasks_dir: Path | None = None, specs: Sequence[str] = SPECS) -> tuple[str, ...]:
    """Corpus task ids in lexical order, for the requested spec variants.

    Defaults to **both** splits: ``VALIDATION.md`` §1 ships every public task as
    prose *and* seeded. Pass ``specs=("prose",)`` for the historically
    baselined split alone (the corpus-v0 aggregate gate names that one).
    """
    directory = tasks_dir or corpus_tasks_dir()
    prose = sorted(p.name for p in directory.iterdir() if (p / "task.json").is_file())
    ids: list[str] = []
    if SPEC_PROSE in specs:
        ids.extend(prose)
    if SPEC_SEEDED in specs:
        ids.extend(seeded_variant_id(task_id) for task_id in prose)
    return tuple(ids)


def load_tasks(
    ids: Sequence[str] | None = None,
    *,
    tasks_dir: Path | None = None,
    specs: Sequence[str] = SPECS,
) -> tuple[BenchTask, ...]:
    """Load the named tasks (default: the whole corpus, both spec variants).

    Ids are stable: ``bracket-101`` is the prose task it has always been, and
    ``bracket-101@seeded`` is its seeded variant, derived from the same
    directory.
    """
    directory = tasks_dir or corpus_tasks_dir()
    wanted = list(ids) if ids else list(task_ids(tasks_dir=directory, specs=specs))
    tasks: list[BenchTask] = []
    for task_id in wanted:
        base = base_task_id(task_id)
        task_dir = directory / base
        if not (task_dir / "task.json").is_file():
            raise FileNotFoundError(f"no corpus task {task_id!r} under {directory}")
        task = BenchTask.load(task_dir)
        tasks.append(seeded_variant(task) if task_id.endswith(SEEDED_SUFFIX) else task)
    return tuple(tasks)


def budget_disclosure(task: BenchTask) -> str:
    """The tool-call budget, stated to the model.

    A run is cancelled once the budget is spent, so an agent that cannot see the
    number cannot ration it — every observed overrun was verification spending
    past a correct result. Disclosing the ceiling (never the pass criteria)
    makes the stop/verify tradeoff decidable. Not a gate relaxation: the budget
    value and the pass criteria are unchanged.
    """
    return (
        f"Tool-call budget: {task.budget_tool_calls} calls for this task. "
        "The run is cancelled when the budget is spent, so spend calls on "
        "building the geometry correctly, not on re-verifying it: one final "
        "run_checks is enough confirmation, and build results already report "
        "bbox/volume/sealed. Stop and summarise as soon as the work is done "
        "and its checks pass."
    )


def seeded_prompt(task: BenchTask, seed: int) -> str:
    """The task prompt plus the budget disclosure and a per-seed suffix."""
    digest = hashlib.sha256(f"{task.id}:{seed}".encode()).digest()
    suffix = PROMPT_SUFFIXES[digest[0] % len(PROMPT_SUFFIXES)]
    return f"{task.prompt.rstrip()}\n\n{budget_disclosure(task)}\n\n{suffix}"
