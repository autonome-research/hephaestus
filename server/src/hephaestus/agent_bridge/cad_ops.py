"""CAD geometry operations for ``py.tool_dispatch``: build_part + inspect_part.

The dispatcher (:mod:`hephaestus.agent_bridge.dispatch`) authorizes a tool and,
for the file-CRUD family, routes it through the project store. The *geometry*
tools — ``build_part`` and ``inspect_part`` — need the Stage 0B build pipeline
and the Stage 1 render service, so they are factored here behind a small
:class:`CadOps` seam the dispatcher holds optionally. When absent the dispatcher
reports the tools as ``not_implemented`` (its prior behaviour); when present the
runtime core drives the real engine.

``build_part`` mirrors the engine CLI's freeze → build → sync → publish path
(``hephaestus.core.cli._build_and_publish``) with an **unsafe local backend**
(``unsafe=True``) for test speed — the same backend the CLI exposes behind
``--unsafe-local-executor``. Production wiring can pass a probed secure backend.
``inspect_part`` renders the part's published current build and returns the PNGs
as base64 image blocks (mime + dimensions), which the sidecar proxy validates
against the §5 image budgets and hands to the model inline.
"""

from __future__ import annotations

import base64
import shutil
import uuid
from typing import Any

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.render.inspect import RenderProject, inspect_part

from opstore import OpStore

__all__ = ["CadOps"]


class CadOps:
    """Build + render operations over one project's layout and opstore."""

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        backend: ExecBackend | None = None,
    ) -> None:
        self._layout = layout
        self._store = store
        # Default to the unsafe local backend (no OS sandbox) for fast tests.
        self._backend: ExecBackend = backend or UnsafeLocalBackend()

    # -- build -------------------------------------------------------------

    def build_part(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build + publish ``name``; return the BuildResult projection.

        Transient ``params`` overrides make the build a preview (never current),
        matching the engine's request-local override semantics.
        """
        overrides = {k: str(v) for k, v in (params or {}).items()}
        preview = bool(overrides)
        publisher = Publisher(self._layout, self._store)
        inputs = publisher.freeze_inputs(name)
        baseline = publisher.baseline_for(name)
        request = BuildRequest(
            part=name,
            script=inputs.script,
            globals_source=inputs.globals_source,
            part_overrides=dict(overrides),
            project_overrides=dict(inputs.manifest_params),
            origin="local",
        )
        out_dir = self._layout.store_root / "builds" / f"{name}-{uuid.uuid4().hex[:12]}"
        try:
            build = run_build(request, backend=self._backend, out_dir=out_dir, baseline=baseline)
            outcome = publisher.publish_build(
                build, op_id=f"heph-build-{uuid.uuid4().hex}", preview=preview
            )
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        result = outcome.result
        # Optional string members are OMITTED when absent rather than sent as
        # null: the generated result schema types them as strings, and the
        # sidecar proxy fails a result closed if it does not validate.
        payload: dict[str, Any] = {
            "status": "ok" if result.status == "ok" else "error",
            "current": result.current,
            "effective_params": {},
        }
        if result.artifact_ref is not None:
            payload["artifact_ref"] = result.artifact_ref
        if result.project_snapshot_ref is not None:
            payload["project_snapshot_ref"] = result.project_snapshot_ref
        if result.error is not None:
            # The canonical §8 error record (line/col/type/message/frame/
            # built_through/last_good/hint) — the repair loop reads exactly this.
            payload["error"] = result.error.to_json()
        return payload

    # -- inspect -----------------------------------------------------------

    def inspect_part(
        self,
        name: str,
        *,
        views: list[str] | None = None,
        channel: str = "rgb",
        mask_mode: str = "solid",
        section_plane: str | None = None,
        explode: float = 0.0,
        last_good: bool = False,
        artifact_ref: str | None = None,
        focus: str | None = None,
    ) -> dict[str, Any]:
        """Render the part's current build; return base64 image blocks + refs."""
        project = RenderProject(layout=self._layout, store=self._store)
        result = inspect_part(
            project,
            name,
            views=views or ["iso"],
            channel=channel,
            mask_mode=mask_mode,
            section_plane=section_plane,
            explode=explode,
            last_good=last_good,
            artifact_ref=artifact_ref,
            focus=focus,
        )
        images: list[dict[str, Any]] = []
        render_refs: list[str] = []
        for image in result.images:
            images.append(
                {
                    "data": base64.b64encode(image.png).decode("ascii"),
                    "mime_type": "image/png",
                    "view": image.view,
                    "channel": image.channel,
                    "render_artifact_ref": image.render_ref,
                }
            )
            render_refs.append(image.render_ref)
        return {
            "status": "ok",
            "source_artifact_ref": result.source_artifact_ref,
            "render_artifact_refs": render_refs,
            "images": images,
        }
