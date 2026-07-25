"""``build_part`` and the render-side reads (``inspect_part``, render bundles).

``build_part`` is freeze → sandboxed build → hc-projection sync → publish, the
same sequence the engine CLI runs: persisted overrides are ordinary build inputs
and only *transient* tool-argument overrides make a build a preview. The publish
is idempotent on the trusted invocation id.

``inspect_part`` returns the full tool-schema render result — channels/modes,
inline-or-ref mask legend paging, selection bundles — with every image checked
against the §5 image budgets by a bounded header parse before the payload is
handed on. ``render_bundle`` exposes the Stage 1 bundle the ``query_snapshot``
child consumes.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from hephaestus.core.render.inspect import inspect_part, prepare_render_bundle
from opstore.types import JSONValue

from opstore import LeaseHeldError

from ..limits import MAX_IMAGES_PER_RESULT, parse_image_header
from ._base import CadOpError, CadOpsState, json_map


class BuildOps(CadOpsState):
    """Build/publish a part and read back its renders."""

    def build_part(
        self,
        name: str,
        params: Mapping[str, Any] | None = None,
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        """Build + publish ``name``; return the BuildResult projection.

        Transient ``params`` overrides make the build a preview (never current),
        matching the engine's request-local override semantics. Persisted
        ``set_params`` overrides are ordinary inputs and never force a preview.

        ``op_id`` is the trusted invocation id: the current-pointer flip is
        idempotent on it, so a lost-response retry of the *same* build replays the
        recorded publication instead of re-flipping the pointer (``build_part`` is
        an idempotency-contract member). Omitted, each call publishes under a
        fresh id (the engine-CLI behaviour).
        """
        transient = {k: str(v) for k, v in (params or {}).items()}
        preview = bool(transient)
        publisher = self._publisher()
        try:
            inputs = publisher.freeze_inputs(name)
        except LeaseHeldError as exc:
            # Another build (possibly a just-cancelled run's worker still tearing
            # down) holds the part lock: surface the contractual busy refusal
            # instead of an internal crash. The caller may retry.
            raise CadOpError("part_busy", f"part {name!r} is being built: {exc}") from exc
        part_overrides: dict[str, int | float | str] = dict(self.params.read("part", name).values)
        part_overrides.update(transient)
        with self._build_dir(name) as out_dir:
            build = self._run(
                name,
                inputs.script,
                inputs.globals_source,
                out_dir=out_dir,
                part_overrides=part_overrides,
                project_overrides=self._project_overrides(),
                baseline=publisher.baseline_for(name),
            )
            if build.result.status == "ok":
                # Persist the live hc projection this build observed so consumers
                # of changed names go stale and publication revalidation sees the
                # current state (mirrors the engine CLI).
                self._sync_projections(publisher, json_map(build.worker_result.get("hc_state")))
            outcome = publisher.publish_build(
                build,
                op_id=op_id or f"heph-build-{uuid.uuid4().hex}",
                preview=preview,
            )
        result = outcome.result
        # Optional string members are OMITTED when absent rather than sent as
        # null: the generated result schema types them as strings, and the
        # sidecar proxy fails a result closed if it does not validate.
        payload: dict[str, Any] = {
            "status": "ok" if result.status == "ok" else "error",
            "current": result.current,
            "effective_params": dict(result.params),
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
        views: Sequence[str] | None = None,
        channel: str = "rgb",
        mask_mode: str = "solid",
        section_plane: str | None = None,
        explode: float = 0.0,
        last_good: bool = False,
        artifact_ref: str | None = None,
        focus: str | None = None,
    ) -> dict[str, Any]:
        """Render the part; return base64 image blocks, refs, legend and bundles."""
        result = inspect_part(
            self._render_project(),
            name,
            views=list(views) if views else ["iso"],
            channel=channel,
            mask_mode=mask_mode,
            section_plane=section_plane,
            explode=explode,
            last_good=last_good,
            artifact_ref=artifact_ref,
            focus=focus,
        )
        if len(result.images) > MAX_IMAGES_PER_RESULT:  # pragma: no cover - schema-capped
            raise CadOpError(
                "too_many_images",
                f"{len(result.images)} images exceeds the per-result budget "
                f"{MAX_IMAGES_PER_RESULT}",
            )
        images: list[dict[str, Any]] = []
        for image in result.images:
            # Bounded header parse BEFORE anything decodes the payload (§5).
            parse_image_header(image.png)
            images.append(
                {
                    "data": base64.b64encode(image.png).decode("ascii"),
                    "mime_type": "image/png",
                    "view": image.view,
                    "channel": image.channel,
                    "render_artifact_ref": image.render_ref,
                    "palette_decodable": image.palette_decodable,
                }
            )
        payload: dict[str, Any] = {
            "status": "ok",
            "source_artifact_ref": result.source_artifact_ref,
            "render_artifact_refs": list(result.render_artifact_refs),
            "images": images,
            "mask_legend_truncated": result.mask_legend_truncated,
        }
        if result.mask_legend is not None:
            payload["mask_legend"] = json.dumps(dict(result.mask_legend), sort_keys=True)
        if result.mask_legend_ref is not None:
            payload["mask_legend_ref"] = result.mask_legend_ref
        if result.selection_table_ref is not None:
            payload["selection_table_ref"] = result.selection_table_ref
        if result.selection_bundles is not None:
            payload["selection_bundles"] = [b.to_json() for b in result.selection_bundles]
        return payload

    def render_bundle(
        self, name: str, views: Sequence[str], artifact_ref: str | None
    ) -> dict[str, JSONValue]:
        """Stage 1 ``prepare_render_bundle`` for the ``query_snapshot`` child."""
        return prepare_render_bundle(
            self._render_project(),
            name,
            views=list(views) if views else ["iso"],
            artifact_ref=artifact_ref,
        )
