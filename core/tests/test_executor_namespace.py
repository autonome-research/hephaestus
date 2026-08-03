"""Injected-namespace tests: §2 surface, denial, PARAMS/p, hc, part, approx."""

from __future__ import annotations

import pytest
from hephaestus.core.errors import (
    ParamOutOfBoundsError,
    SandboxDeniedError,
    ValidationError,
)
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    HcNamespace,
    ParamProxy,
    ParamState,
    PartOutput,
    approx,
    build_namespace,
    safe_builtins,
)
from hephaestus.core.executor.tags import TagRegistry


def fresh_namespace() -> dict[str, object]:
    return build_namespace(
        param_state=ParamState(scope="part", overrides={}),
        hc=HcNamespace({"sheet_t": 6.0}),
        part=PartOutput(),
        tag_registry=TagRegistry(),
        check_registry=CheckRegistry(),
    )


class TestDenial:
    def test_open_denied(self) -> None:
        namespace = fresh_namespace()
        with pytest.raises(SandboxDeniedError):
            exec("open('/etc/passwd')", namespace)

    def test_import_statement_denied(self) -> None:
        namespace = fresh_namespace()
        with pytest.raises(SandboxDeniedError):
            exec("import os", namespace)

    def test_dunder_import_denied(self) -> None:
        namespace = fresh_namespace()
        with pytest.raises(SandboxDeniedError):
            exec("__import__('socket')", namespace)

    def test_eval_exec_compile_denied(self) -> None:
        namespace = fresh_namespace()
        for attempt in ("eval('1')", "exec('x = 1')", "compile('1', '<s>', 'eval')"):
            with pytest.raises(SandboxDeniedError):
                exec(attempt, dict(namespace))

    def test_file_and_network_names_absent(self) -> None:
        namespace = fresh_namespace()
        builtins_map = namespace["__builtins__"]
        assert isinstance(builtins_map, dict)
        for name in ("file", "socket", "pathlib", "os", "sys", "subprocess"):
            assert name not in namespace
            assert name not in builtins_map

    def test_safe_builtins_keep_exceptions_and_basics(self) -> None:
        safe = safe_builtins()
        assert safe["len"] is len
        assert safe["ValueError"] is ValueError
        assert "open" in safe  # present as a denier
        with pytest.raises(SandboxDeniedError):
            denier = safe["open"]
            assert callable(denier)
            denier("x")


class TestSurface:
    def test_build123d_complete_and_math(self) -> None:
        namespace = fresh_namespace()
        for name in ("Box", "Compound", "Axis", "Pos", "fillet", "extrude", "Plane"):
            assert name in namespace
        assert namespace["math"] is not None
        assert "part" in namespace and "hc" in namespace and "tag" in namespace
        assert "approx" in namespace and "Param" in namespace and "p" in namespace

    def test_nothing_else(self) -> None:
        namespace = fresh_namespace()
        assert "open" not in namespace  # only inside restricted builtins as denier


class TestParams:
    def test_p_before_params_is_contract_error(self) -> None:
        state = ParamState(scope="part", overrides={})
        proxy = ParamProxy(state)
        with pytest.raises(ValidationError) as excinfo:
            _ = proxy.width
        assert excinfo.value.kind == "contract"

    def test_publish_then_read(self) -> None:
        from hephaestus.core.params import Param

        state = ParamState(scope="part", overrides={"width": 50})
        state.publish({"PARAMS": {"width": Param(40.0, min=10, max=100)}})
        proxy = ParamProxy(state)
        assert proxy.width == 50.0

    def test_out_of_bounds_override_names_param(self) -> None:
        from hephaestus.core.params import Param

        state = ParamState(scope="part", overrides={"width": 500})
        with pytest.raises(ParamOutOfBoundsError) as excinfo:
            state.publish({"PARAMS": {"width": Param(40.0, min=10, max=100)}})
        assert excinfo.value.param == "width"

    def test_unknown_p_attribute(self) -> None:
        from hephaestus.core.params import Param

        state = ParamState(scope="part", overrides={})
        state.publish({"PARAMS": {"width": Param(40.0, min=10, max=100)}})
        proxy = ParamProxy(state)
        with pytest.raises(ValidationError):
            _ = proxy.height

    def test_finalize_rejects_overrides_without_params(self) -> None:
        state = ParamState(scope="part", overrides={"width": 5})
        with pytest.raises(ValidationError) as excinfo:
            state.finalize()
        assert "PARAMS" in excinfo.value.message

    def test_p_is_read_only(self) -> None:
        state = ParamState(scope="part", overrides={})
        state.publish({})
        proxy = ParamProxy(state)
        with pytest.raises(ValidationError):
            proxy.width = 3


class TestHc:
    def test_reads_track_consumption(self) -> None:
        hc = HcNamespace({"sheet_t": 6.0, "clearance": 0.3})
        assert hc.sheet_t == 6.0
        assert hc.consumed_names() == ("sheet_t",)
        assert hc.consumed_projection() == {"sheet_t": 6.0}

    def test_unread_names_not_in_projection(self) -> None:
        hc = HcNamespace({"a": 1, "b": 2})
        _ = hc.b
        assert hc.consumed_projection() == {"b": 2}

    def test_read_only(self) -> None:
        hc = HcNamespace({"a": 1})
        with pytest.raises(ValidationError):
            hc.a = 2

    def test_missing_name_lists_available(self) -> None:
        hc = HcNamespace({"shelf_w": 80.0})
        with pytest.raises(AttributeError) as excinfo:
            _ = hc.shelf_x
        assert "shelf_w" in str(excinfo.value)


class TestPartOutput:
    def test_metadata_fields(self) -> None:
        part = PartOutput()
        part.description = "a part"
        part.process = "laser_cut"
        assert part.metadata() == {"description": "a part", "process": "laser_cut"}

    def test_feature_metadata(self) -> None:
        part = PartOutput()
        part.feature("tread_top").surface_finish = "anti-slip recesses"
        assert part.feature_metadata() == {"tread_top": {"surface_finish": "anti-slip recesses"}}

    def test_geometry_value(self) -> None:
        part = PartOutput()
        assert part.geometry_value is None
        part.geometry = "placeholder"
        assert part.geometry_value == "placeholder"

    def test_feature_requires_name(self) -> None:
        part = PartOutput()
        with pytest.raises(ValidationError):
            part.feature("")


class TestApprox:
    def test_within_tolerance(self) -> None:
        assert approx(0, abs=1e-6) == 0.0000005
        assert approx(0, abs=1e-6) == 0.0000005

    def test_outside_tolerance(self) -> None:
        assert approx(0, abs=1e-6) != 0.01

    def test_boundary_inclusive(self) -> None:
        assert approx(0, abs=1e-6) == 1e-6

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            approx(0, abs=-1.0)


class TestCheckRegistry:
    def test_register_and_collect(self) -> None:
        registry = CheckRegistry()

        def predicate(m: object) -> bool:
            del m
            return True

        registry.register("sealed", predicate)
        assert sorted(registry.collected()) == ["sealed"]

    def test_rejects_non_callable(self) -> None:
        registry = CheckRegistry()
        with pytest.raises(ValidationError):
            registry.register("bad", 42)


class TestUnknownPartAttributeRefused:
    """Unknown `part.*` assignment is a contract error naming the real fields.

    Regression (2026-07-29 corpus sweep): models wrote `part.metadata = {...}`
    — a reasonable reading of "give the part its manufacturing metadata" —
    the namespace swallowed it silently, and the grade later reported the
    metadata missing with no signal the model could act on.
    """

    def test_dict_style_metadata_is_refused_with_the_field_list(self) -> None:
        from hephaestus.core.executor.namespace import PartOutput

        part = PartOutput()
        with pytest.raises(ValidationError) as excinfo:
            part.metadata = {"process": "fdm"}  # type: ignore[attr-defined]
        message = str(excinfo.value)
        assert "part.metadata is not a part attribute" in message
        assert "material_spec" in message and "part.feature(name)" in message

    def test_misspelled_field_is_refused(self) -> None:
        from hephaestus.core.executor.namespace import PartOutput

        part = PartOutput()
        with pytest.raises(ValidationError):
            part.material = "PLA"  # type: ignore[attr-defined]

    def test_every_contract_field_still_assigns(self) -> None:
        from hephaestus.core.executor.namespace import METADATA_FIELDS, PartOutput

        part = PartOutput()
        part.geometry = "placeholder"
        for field in METADATA_FIELDS:
            setattr(part, field, "value")
        assert part.metadata() == dict.fromkeys(METADATA_FIELDS, "value")
