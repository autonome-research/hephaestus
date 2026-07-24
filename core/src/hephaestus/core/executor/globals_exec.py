"""globals.py execution: the project-shared ``hc`` namespace (§4).

``globals.py`` executes under the injected namespace minus ``part`` (it
declares values, not geometry): build123d, ``math``, ``Param``/``PARAMS``/
``p`` at project scope. Its public names become the ``hc`` attributes every
part sees — project parameters (effective values after project-scope
overrides) plus derived constants. Also hosts the §4 lint-error hook: a part
``PARAMS`` name shadowing an ``hc`` name is an error, so every tunable has
exactly one home.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    HcNamespace,
    ParamState,
    build_namespace,
    jsonify,
)
from hephaestus.core.executor.splitter import (
    GLOBALS_FILENAME,
    compile_statement,
    parse_module,
)
from hephaestus.core.params import Param
from opstore.types import JSONValue


@dataclass(frozen=True)
class GlobalsResult:
    """Outcome of executing globals.py.

    ``hc_values`` is the full public namespace parts read through ``hc``
    (project params at effective values first, then derived constants, in
    declaration order). ``project_params`` / ``effective_project_params``
    mirror the §3 declaration and merged values.
    """

    hc_values: Mapping[str, object] = field(default_factory=dict[str, object])
    project_params: Mapping[str, Param] = field(default_factory=dict[str, Param])
    effective_project_params: Mapping[str, int | float] = field(
        default_factory=dict[str, "int | float"]
    )

    def hc_namespace(self) -> HcNamespace:
        """A fresh read-tracking ``hc`` object over these values (one per part)."""
        return HcNamespace(self.hc_values)

    def hc_state_json(self) -> dict[str, JSONValue]:
        """JSON projection of the full public namespace (audit hashing)."""
        return {name: jsonify(value) for name, value in self.hc_values.items()}


def execute_globals(
    source: str | None,
    *,
    overrides: Mapping[str, int | float | str] | None = None,
) -> GlobalsResult:
    """Execute globals.py source and return the project-shared namespace.

    ``None``/empty source yields an empty namespace (a project may have no
    globals.py). Exceptions from the source propagate to the caller (the
    worker converts them to a §8 error record); an out-of-bounds project
    override raises ``param_out_of_bounds`` naming the parameters.
    """
    if source is None or not source.strip():
        if overrides:
            names = ", ".join(sorted(overrides))
            raise ValidationError(
                f"project parameter overrides given ({names}) but globals.py declares no PARAMS",
                kind="contract",
            )
        return GlobalsResult()
    param_state = ParamState(scope="project", overrides=overrides or {})
    namespace = build_namespace(
        param_state=param_state,
        hc=None,
        part=None,
        tag_registry=None,
        check_registry=CheckRegistry(),
    )
    injected = frozenset(namespace)
    module = parse_module(source, filename=GLOBALS_FILENAME)
    for node in module.body:
        code = compile_statement(node, filename=GLOBALS_FILENAME)
        exec(code, namespace)
        if not param_state.published and "PARAMS" in namespace:
            param_state.publish(namespace)
    param_state.finalize()
    declared = param_state.declared or {}
    effective = param_state.effective or {}
    hc_values: dict[str, object] = dict(effective)
    for name, value in namespace.items():
        if name in injected or name == "PARAMS" or name.startswith("_"):
            continue
        if name in effective:
            continue
        hc_values[name] = value
    return GlobalsResult(
        hc_values=hc_values,
        project_params=dict(declared),
        effective_project_params=dict(effective),
    )


def shadowed_params(part_params: Iterable[str], hc_names: Iterable[str]) -> tuple[str, ...]:
    """§4 lint-error hook: part PARAMS names that shadow an ``hc`` name (sorted)."""
    hc_set = frozenset(hc_names)
    return tuple(sorted(name for name in part_params if name in hc_set))


def ensure_no_shadowing(part_params: Iterable[str], hc_names: Iterable[str]) -> None:
    """Raise ``validation_error`` (contract) when part PARAMS shadow ``hc`` names."""
    shadowed = shadowed_params(part_params, hc_names)
    if shadowed:
        names = ", ".join(shadowed)
        raise ValidationError(
            f"part PARAMS must not shadow hc names (every tunable has exactly one "
            f"home, script contract §4): {names}",
            kind="contract",
        )
