"""Issue #120: closed, non-secret model wire projections and preconditions."""

from __future__ import annotations

from typing import Any, Literal, TypedDict, cast


class ModelRef(TypedDict):
    provider_id: str
    model_id: str


class ModelRevision(TypedDict):
    epoch: str
    version: int


class ResolvedModel(ModelRef):
    name: str
    input: list[Literal["text", "image"]]


class ModelOption(ModelRef):
    name: str
    input: list[Literal["text", "image"]] | None
    available: bool
    unavailable_reason: str | None


class ModelProvider(TypedDict):
    provider_id: str
    name: str
    models: list[ModelOption]


class ModelsDocument(TypedDict):
    status: Literal["ok"]
    providers: list[ModelProvider]
    proposed_default: ResolvedModel | None
    default_policy: Literal["first_available_declared"]


class SessionModelState(TypedDict):
    revision: ModelRevision
    current: ResolvedModel | None
    selected: ModelRef | None
    pending_selection: ModelRef | None
    state: Literal["ready", "changing", "unavailable", "uncertain"]
    reason: str | None


class ExecutionSnapshot(TypedDict):
    epoch: str
    version: int
    run_id: str | None
    active_run_id: str | None
    admission_available: bool
    terminal: dict[str, Any] | None


class SessionModelDocument(TypedDict):
    status: Literal["ok"]
    session_id: str
    model_state: SessionModelState
    execution: ExecutionSnapshot


class SelectModelRequest(TypedDict):
    model: ModelRef
    expected_model_revision: ModelRevision


MODEL_STATUSES = {
    "invalid_params": 400,
    "model_revision_required": 428,
    "provider_unknown": 404,
    "model_unknown": 404,
    "model_not_configured": 409,
    "model_unavailable": 409,
    "selection_required": 409,
    "model_changed": 409,
    "model_change_in_progress": 409,
    "model_selection_uncertain": 409,
    "model_selection_failed": 500,
    "run_in_flight": 409,
}


class ModelSelectionError(Exception):
    def __init__(self, reason: str, *, data: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.data = data or {}
        super().__init__(
            "The session model changed. Review it before sending."
            if reason == "model_changed"
            else reason.replace("_", " ")
        )


def fields(value: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelSelectionError("invalid_params")
    result = cast("dict[str, Any]", value)
    if set(result) != names:
        raise ModelSelectionError("invalid_params")
    return result


def text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelSelectionError("invalid_params")
    return value


def model_ref(value: Any) -> ModelRef:
    v = fields(value, {"provider_id", "model_id"})
    return {"provider_id": text(v["provider_id"]), "model_id": text(v["model_id"])}


def revision(value: Any) -> ModelRevision:
    v = fields(value, {"epoch", "version"})
    version = v["version"]
    if type(version) is not int or not 0 <= version <= 2**53 - 1:
        raise ModelSelectionError("invalid_params")
    return {"epoch": text(v["epoch"]), "version": version}


def expected_revision(body: dict[str, Any]) -> ModelRevision:
    if "expected_model_revision" not in body:
        raise ModelSelectionError("model_revision_required")
    return revision(body["expected_model_revision"])


def inputs(value: Any) -> list[Literal["text", "image"]]:
    if not isinstance(value, list):
        raise ModelSelectionError("invalid_params")
    values = cast("list[Any]", value)
    if any(v not in ("text", "image") for v in values):
        raise ModelSelectionError("invalid_params")
    return cast('list[Literal["text", "image"]]', list(values))


def resolved(value: Any) -> ResolvedModel:
    v = fields(value, {"provider_id", "model_id", "name", "input"})
    return {
        "provider_id": text(v["provider_id"]),
        "model_id": text(v["model_id"]),
        "name": text(v["name"]),
        "input": inputs(v["input"]),
    }


def nullable_text(value: Any) -> str | None:
    return None if value is None else text(value)


def model_state(value: Any) -> SessionModelState:
    v = fields(value, {"revision", "current", "selected", "pending_selection", "state", "reason"})
    if v["state"] not in ("ready", "changing", "unavailable", "uncertain"):
        raise ModelSelectionError("invalid_params")
    return {
        "revision": revision(v["revision"]),
        "current": None if v["current"] is None else resolved(v["current"]),
        "selected": None if v["selected"] is None else model_ref(v["selected"]),
        "pending_selection": None
        if v["pending_selection"] is None
        else model_ref(v["pending_selection"]),
        "state": v["state"],
        "reason": nullable_text(v["reason"]),
    }


def models_document(value: Any) -> ModelsDocument:
    v = fields(value, {"status", "providers", "proposed_default", "default_policy"})
    if (
        v["status"] != "ok"
        or v["default_policy"] != "first_available_declared"
        or not isinstance(v["providers"], list)
    ):
        raise ModelSelectionError("invalid_params")
    providers: list[ModelProvider] = []
    for raw in cast("list[Any]", v["providers"]):
        p = fields(raw, {"provider_id", "name", "models"})
        if not isinstance(p["models"], list):
            raise ModelSelectionError("invalid_params")
        options: list[ModelOption] = []
        for raw_model in cast("list[Any]", p["models"]):
            m = fields(
                raw_model,
                {"provider_id", "model_id", "name", "input", "available", "unavailable_reason"},
            )
            if type(m["available"]) is not bool:
                raise ModelSelectionError("invalid_params")
            options.append(
                {
                    "provider_id": text(m["provider_id"]),
                    "model_id": text(m["model_id"]),
                    "name": text(m["name"]),
                    "input": None if m["input"] is None else inputs(m["input"]),
                    "available": m["available"],
                    "unavailable_reason": nullable_text(m["unavailable_reason"]),
                }
            )
        providers.append(
            {"provider_id": text(p["provider_id"]), "name": text(p["name"]), "models": options}
        )
    return {
        "status": "ok",
        "providers": providers,
        "proposed_default": None
        if v["proposed_default"] is None
        else resolved(v["proposed_default"]),
        "default_policy": "first_available_declared",
    }


def require_ready(state: SessionModelState, expected: ModelRevision | None) -> None:
    if state["state"] == "changing":
        raise ModelSelectionError("model_change_in_progress")
    if expected is not None and state["revision"] != expected:
        raise ModelSelectionError("model_changed")
    if state["state"] != "ready" or state["current"] is None:
        raise ModelSelectionError(
            "model_selection_uncertain" if state["state"] == "uncertain" else "selection_required"
        )
