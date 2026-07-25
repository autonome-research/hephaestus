"""The five registry tools, backed by one verified :class:`RegistrySet`.

This is the only module that *acts*: it pages skill markdown into provenance-
delimited results with snapshot-bound cursors, searches materials and store
parts, and executes a store generator through the ordinary build pipeline with
``origin="registry"`` — under a probed secure sandbox or not at all.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hephaestus.core.errors import HephaestusError
from hephaestus.core.executor.sandbox.base import ExecBackend
from opstore.types import JSONValue

from opstore import OpStore

from ._errors import RegistryError
from ._generator import GeneratorSource, parse_generator, render_fragment
from ._parts import StorePart
from ._reference import (
    TEXT_MAX_BYTES,
    TEXT_MAX_LINES,
    Page,
    paginate,
    wrap_reference,
    wrapper_overhead,
)
from ._set import RegistrySet
from ._skills import SKILL_ARTIFACT_KIND

if TYPE_CHECKING:
    from hephaestus.core.types import BuildResult

__all__ = ["RegistryOps"]


class RegistryOps:
    """Backs the five registry tools over a verified :class:`RegistrySet`.

    ``store`` supplies the CAS the skill-page snapshot is registered in, so a
    truncated ``load_skill`` continues through ``read_artifact(artifact_ref,
    next_offset_bytes)`` against immutable bytes. ``backend`` is the *secure*
    execution backend generators run under; without one ``instance_store_part``
    reports ``capability_not_available`` rather than degrading to an unsandboxed
    run.
    """

    def __init__(
        self,
        registries: RegistrySet,
        store: OpStore,
        *,
        backend: ExecBackend | None = None,
        scratch_root: Path | None = None,
        wall_clock_s: float = 120.0,
    ) -> None:
        self._registries = registries
        self._store = store
        self._backend = backend
        self._scratch_root = scratch_root
        self._wall_clock_s = wall_clock_s

    @property
    def registries(self) -> RegistrySet:
        return self._registries

    # -- contextual content ------------------------------------------------

    def list_skills(self) -> list[dict[str, JSONValue]]:
        """``[{name, summary, tokens, registry, registry_digest}]``, name-sorted."""
        return self._registries.skills.listing()

    def load_skill(
        self, name: str, offset_line: int = 1, limit_lines: int = TEXT_MAX_LINES
    ) -> dict[str, JSONValue]:
        """One bounded skill page inside provenance delimiters.

        The whole file is registered as an immutable artifact first, so every
        cursor this returns is absolute and snapshot-bound. Truncation — a full
        page, a byte-budget stop, or a single line too large to ever fit — is
        always reported, never silently swallowed.
        """
        entry = self._registries.skills.get(name)
        data = entry.read_bytes()
        blob = self._store.blobs.put(data)
        self._store.gc.pin(blob)
        artifact_ref = f"artifact:{SKILL_ARTIFACT_KIND}:{blob}"

        raw_lines = data.splitlines(keepends=True)
        starts: list[int] = []
        cursor = 0
        for line in raw_lines:
            starts.append(cursor)
            cursor += len(line)
        starts.append(len(data))

        total_lines = len(raw_lines)
        first = max(0, int(offset_line) - 1)
        limit = max(1, min(int(limit_lines), TEXT_MAX_LINES))
        if first >= total_lines:
            page = Page(
                body="",
                end_line=total_lines,
                truncated=False,
                oversized_line=False,
                next_offset_bytes=None,
                oversized_line_offset_bytes=None,
            )
        else:
            budget = TEXT_MAX_BYTES - wrapper_overhead(entry, total_lines)
            page = paginate(raw_lines, starts, first, limit, max(1, budget))
        lines_label = (
            f"{first + 1}-{page.end_line}/{total_lines}"
            if page.end_line > first
            else f"none-of-{total_lines}"
        )
        result: dict[str, JSONValue] = {
            "content": wrap_reference(
                page.body,
                kind="skill",
                name=entry.name,
                registry=entry.registry,
                digest=entry.digest,
                lines=lines_label,
            ),
            "artifact_ref": artifact_ref,
            "truncated": page.truncated,
            "oversized_line": page.oversized_line,
            "total_lines": total_lines,
            "total_bytes": len(data),
            "first_line": first + 1,
            "last_line": page.end_line,
        }
        if page.truncated:
            result["next_offset_line"] = page.end_line + 1
        if page.next_offset_bytes is not None:
            result["next_offset_bytes"] = page.next_offset_bytes
        if page.oversized_line_offset_bytes is not None:
            result["oversized_line_offset_bytes"] = page.oversized_line_offset_bytes
        return result

    def search_materials(self, query: str) -> list[dict[str, JSONValue]]:
        """``[{id, name, density, forms, thicknesses, notes}]`` best-match first."""
        return self._registries.materials.search(query)

    # -- executable content ------------------------------------------------

    def search_parts_store(self, query: str, max_results: int = 5) -> list[dict[str, JSONValue]]:
        """``[{id, name, params, preview}]`` for generators matching ``query``."""
        return self._registries.parts.search(query, max(1, int(max_results)))

    def instance_store_part(
        self,
        part_id: str,
        params: Mapping[str, Any],
        pos: Mapping[str, Any] | None = None,
    ) -> dict[str, JSONValue]:
        """Execute a generator under the secure sandbox and return a placed fragment.

        The generator runs as an ordinary part script with ``origin="registry"``:
        the injected-namespace whitelist is its API surface, the OS sandbox is
        its boundary, and the unsafe local backend refuses the job outright. Only
        after the geometry actually builds with the requested parameters is a
        fragment emitted — an instance the model pastes is one that works.
        """
        part = self._registries.parts.get(part_id)
        generator = parse_generator(part.read_script(), source=str(part.script_path))
        overrides = _coerce_overrides(params, generator.param_names)
        result = self._build_generator(part, generator, overrides)
        effective = dict(result.params)
        metrics = result.metrics
        return {
            "script_fragment": render_fragment(generator, part, effective, pos),
            "id": part.id,
            "params": cast("dict[str, JSONValue]", dict(effective)),
            "registry": part.registry,
            "registry_digest": part.digest,
            "metrics": {} if metrics is None else cast("JSONValue", metrics.to_json()),
        }

    def _build_generator(
        self,
        part: StorePart,
        generator: GeneratorSource,
        overrides: Mapping[str, int | float],
    ) -> BuildResult:
        from hephaestus.core.executor.runner import BuildRequest, run_build

        backend = self._backend
        if backend is None:
            raise RegistryError(
                "capability_not_available",
                "no secure execution backend is configured; registry generators never "
                "run unsandboxed",
                data={"code": "capability_not_available"},
            )
        request = BuildRequest(
            part=part.id,
            script=generator.script,
            globals_source=None,
            part_overrides=dict(overrides),
            origin="registry",
            wall_clock_s=self._wall_clock_s,
        )
        scratch_parent = self._scratch_root or Path(tempfile.gettempdir())
        scratch_parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="heph-store-", dir=scratch_parent))
        try:
            build = run_build(request, backend=backend, out_dir=scratch / "out")
        except RegistryError:
            raise
        except HephaestusError as exc:
            raise RegistryError(exc.code, f"store generator {part.id!r}: {exc.message}") from exc
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        result = build.result
        if result.status != "ok":
            error = result.error
            detail = "unknown failure" if error is None else f"{error.type}: {error.message}"
            reason = (
                "invalid_params"
                if error is not None and "arameter" in error.message
                else "generator_failed"
            )
            raise RegistryError(reason, f"store generator {part.id!r} failed to build — {detail}")
        return result


def _coerce_overrides(params: Mapping[str, Any], declared: Sequence[str]) -> dict[str, int | float]:
    """Validate tool-supplied generator parameters (bounds are the worker's job)."""
    unknown = sorted(name for name in params if name not in declared)
    if unknown:
        raise RegistryError(
            "invalid_params",
            f"unknown parameter(s) {', '.join(unknown)}; declared: "
            + (", ".join(declared) or "(none)"),
            data={"declared": list(declared)},
        )
    out: dict[str, int | float] = {}
    for name, value in params.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RegistryError("invalid_params", f"parameter {name!r} must be a number")
        if not math.isfinite(float(value)):
            raise RegistryError("invalid_params", f"parameter {name!r} must be finite")
        out[name] = value
    return out
