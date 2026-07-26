"""The ``dfm`` registry's rule-pack index (architecture §3.6).

A DFM registry is one directory per manufacturing process. Each pack directory
holds a ``pack.toml`` — process identity, the named parameters the process is
characterised by (kerf, nozzle, …), and the rule table — plus one predicate
file per rule.

A rule is a *declaration* (stable ``rule_id``, human ``title``, ``severity``,
the parameters it reads) bound to a *predicate*: untrusted executable registry
content that runs only under the same sandboxed executor and injected-namespace
whitelist as a part script (:mod:`hephaestus.core.dfm.runner`). This module
indexes and validates packs; it never executes anything.

Two invariants are enforced at load, so a malformed pack is a typed contract
error at index time rather than a surprise inside the sandbox:

* every ``rule_id`` is ``<process>.<name>`` and unique within the pack, and
* every parameter a rule declares in ``reads`` exists in the pack's ``[params]``
  table — a predicate can therefore never read an undeclared number.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast, get_args

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._errors import RegistryError
from ._fields import entries, opt_str, req_str, table
from ._layout import MANIFEST_FILENAME, Registry

__all__ = [
    "PACK_FILENAME",
    "SEVERITIES",
    "DfmIndex",
    "DfmPack",
    "DfmParam",
    "DfmRule",
    "DfmSeverity",
]

#: Per-pack manifest filename inside a pack directory.
PACK_FILENAME: Final[str] = "pack.toml"

DfmSeverity = Literal["error", "warning", "info"]

#: The severities a rule may declare, most severe first.
SEVERITIES: Final[tuple[DfmSeverity, ...]] = get_args(DfmSeverity)

_PROCESS_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RULE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class DfmParam:
    """One named process parameter a rule may read (always a finite number)."""

    name: str
    value: float
    unit: str = ""
    description: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass(frozen=True)
class DfmRule:
    """One DFM rule: its declaration plus the predicate that measures it.

    ``params`` is exactly the subset of the pack's parameters named in the
    rule's ``reads`` list — the numbers the predicate is given, and no others.
    ``predicate_path`` is registry content; read it with :meth:`read_predicate`
    and execute it only through :mod:`hephaestus.core.dfm.runner`.
    """

    rule_id: str
    title: str
    severity: DfmSeverity
    process: str
    description: str
    params: Mapping[str, DfmParam]
    predicate_path: Path
    registry: str = ""
    digest: str = ""

    @property
    def values(self) -> dict[str, float]:
        """``{param name: value}`` — what the predicate sees as ``ctx.params``."""
        return {name: param.value for name, param in sorted(self.params.items())}

    def read_predicate(self) -> str:
        """The predicate source (untrusted registry content; sandbox it)."""
        return self.predicate_path.read_text(encoding="utf-8")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "process": self.process,
            "description": self.description,
            "params": {name: param.to_json() for name, param in sorted(self.params.items())},
            "registry": self.registry,
            "registry_digest": self.digest,
        }


@dataclass(frozen=True)
class DfmPack:
    """Every rule for one manufacturing process, plus its process parameters."""

    process: str
    name: str
    version: str
    description: str
    params: Mapping[str, DfmParam]
    rules: tuple[DfmRule, ...]
    registry: str = ""
    digest: str = ""

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.rule_id for rule in self.rules)

    def rule(self, rule_id: str) -> DfmRule:
        """One rule by id; an unknown id lists the pack's ids."""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise RegistryError(
            "unknown_dfm_rule",
            f"no rule {rule_id!r} in the {self.process!r} pack; rules: "
            + (", ".join(self.rule_ids()) or "(none)"),
            data={"candidates": list(self.rule_ids())},
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "process": self.process,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "params": {name: param.to_json() for name, param in sorted(self.params.items())},
            "rules": [rule.to_json() for rule in self.rules],
            "registry": self.registry,
            "registry_digest": self.digest,
        }


def _param(name: str, raw: object, *, source: str) -> DfmParam:
    if isinstance(raw, bool):
        raise ValidationError(f"{source}: parameter {name!r} must be a number", kind="contract")
    if isinstance(raw, int | float):
        return DfmParam(name=name, value=float(raw))
    if isinstance(raw, dict):
        record = cast("Mapping[str, Any]", raw)
        value = record.get("value")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(
                f"{source}: parameter {name!r} needs a numeric 'value'", kind="contract"
            )
        return DfmParam(
            name=name,
            value=float(value),
            unit=opt_str(record, "unit"),
            description=opt_str(record, "description"),
        )
    raise ValidationError(
        f"{source}: parameter {name!r} must be a number or a {{value, unit, description}} table",
        kind="contract",
    )


@dataclass(frozen=True)
class _PackHeader:
    """``pack.toml`` before its rules are bound to predicate files."""

    process: str
    name: str
    version: str
    description: str
    params: Mapping[str, DfmParam]
    rules: tuple[Mapping[str, Any], ...]


def _parse_pack(text: str, *, source: str) -> _PackHeader:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"{source}: invalid TOML: {exc}", kind="contract") from exc
    data = cast("Mapping[str, Any]", raw)
    header = table(data, "pack", source=source)
    if not header:
        raise ValidationError(f"{source}: a [pack] table is required", kind="contract")
    process = req_str(header, "process", source=source)
    if not _PROCESS_RE.match(process):
        raise ValidationError(
            f"{source}: process {process!r} must match {_PROCESS_RE.pattern}", kind="contract"
        )
    params_raw = table(data, "params", source=source)
    params = {name: _param(name, value, source=source) for name, value in params_raw.items()}
    return _PackHeader(
        process=process,
        name=opt_str(header, "name", process),
        version=req_str(header, "version", source=source),
        description=opt_str(header, "description"),
        params=params,
        rules=entries(data, "rules", source=source),
    )


def load_pack(directory: Path, *, registry: str = "", digest: str = "") -> DfmPack:
    """Load and validate one pack directory (``pack.toml`` plus its predicates)."""
    manifest_path = directory / PACK_FILENAME
    if not manifest_path.is_file():
        raise ValidationError(f"{directory} has no {PACK_FILENAME}", kind="contract")
    source = str(manifest_path)
    header = _parse_pack(manifest_path.read_text(encoding="utf-8"), source=source)
    process = header.process
    params = header.params
    rules: list[DfmRule] = []
    seen: set[str] = set()
    for record in header.rules:
        rule_id = req_str(record, "id", source=f"{source} [[rules]]")
        if not _RULE_ID_RE.match(rule_id):
            raise ValidationError(
                f"{source}: rule id {rule_id!r} must match {_RULE_ID_RE.pattern}", kind="contract"
            )
        if not rule_id.startswith(f"{process}."):
            raise ValidationError(
                f"{source}: rule id {rule_id!r} must be prefixed with the pack process {process!r}",
                kind="contract",
            )
        if rule_id in seen:
            raise ValidationError(f"{source}: duplicate rule id {rule_id!r}", kind="contract")
        seen.add(rule_id)
        severity = opt_str(record, "severity", "error")
        if severity not in SEVERITIES:
            raise ValidationError(
                f"{source}: rule {rule_id!r} severity {severity!r} is not one of "
                + ", ".join(SEVERITIES),
                kind="contract",
            )
        predicate_path = directory / opt_str(record, "predicate", f"{rule_id.split('.', 1)[1]}.py")
        if not predicate_path.is_file():
            raise ValidationError(
                f"{source}: rule {rule_id!r} predicate {predicate_path} is missing",
                kind="contract",
            )
        reads: dict[str, DfmParam] = {}
        for read in _reads(record, source=f"{source} [[rules]] {rule_id}"):
            param = params.get(read)
            if param is None:
                available = ", ".join(sorted(params)) or "(none)"
                raise ValidationError(
                    f"{source}: rule {rule_id!r} reads undeclared parameter {read!r}; "
                    f"[params] declares: {available}",
                    kind="contract",
                )
            reads[read] = param
        rules.append(
            DfmRule(
                rule_id=rule_id,
                title=req_str(record, "title", source=f"{source} [[rules]] {rule_id}"),
                severity=severity,
                process=process,
                description=opt_str(record, "description"),
                params=reads,
                predicate_path=predicate_path,
                registry=registry,
                digest=digest,
            )
        )
    return DfmPack(
        process=process,
        name=header.name,
        version=header.version,
        description=header.description,
        params=params,
        rules=tuple(rules),
        registry=registry,
        digest=digest,
    )


def _reads(record: Mapping[str, Any], *, source: str) -> tuple[str, ...]:
    raw = record.get("reads")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError(
            f"{source}: 'reads' must be a list of parameter names", kind="contract"
        )
    out: list[str] = []
    for item in cast("list[Any]", raw):
        if not isinstance(item, str) or not item:
            raise ValidationError(
                f"{source}: 'reads' entries must be non-empty strings", kind="contract"
            )
        out.append(item)
    return tuple(out)


class DfmIndex:
    """The ``dfm`` registry's pack index, keyed by manufacturing process."""

    def __init__(self, registry: Registry | None) -> None:
        self._registry = registry
        self._packs: dict[str, DfmPack] = {}
        if registry is None:
            return
        source = f"{registry.root / MANIFEST_FILENAME} [[packs]]"
        for item in registry.manifest.packs:
            record = cast("Mapping[str, Any]", item)
            process = req_str(record, "process", source=source)
            directory = registry.root / opt_str(record, "dir", process)
            pack = load_pack(directory, registry=registry.name, digest=registry.digest)
            if pack.process != process:
                raise ValidationError(
                    f"{source}: {directory / PACK_FILENAME} declares process "
                    f"{pack.process!r} but the manifest lists it as {process!r}",
                    kind="contract",
                )
            if process in self._packs:
                raise ValidationError(f"{source}: duplicate process {process!r}", kind="contract")
            self._packs[process] = pack

    def processes(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))

    def has(self, process: str) -> bool:
        return process in self._packs

    def get(self, process: str) -> DfmPack:
        """The pack for ``process``; an unknown process lists the known ones."""
        pack = self._packs.get(process)
        if pack is None:
            raise RegistryError(
                "unknown_dfm_pack",
                f"no DFM rule pack for process {process!r}; packs: "
                + (", ".join(self.processes()) or "(none)"),
                data={"candidates": list(self.processes())},
            )
        return pack

    def listing(self) -> list[dict[str, JSONValue]]:
        """``[{process, name, version, description, rules, registry, …}]``."""
        return [
            {
                "process": pack.process,
                "name": pack.name,
                "version": pack.version,
                "description": pack.description,
                "rules": list(pack.rule_ids()),
                "registry": pack.registry,
                "registry_digest": pack.digest,
            }
            for pack in (self._packs[process] for process in self.processes())
        ]
