"""``build_part`` and the render-side reads (``inspect_part``, render bundles).

``build_part`` is freeze → sandboxed build → hc-projection sync → publish, the
same sequence the engine CLI runs: persisted overrides are ordinary build inputs
and only *transient* tool-argument overrides make a build a preview. The publish
is idempotent on the trusted invocation id.

Every *successful* build then carries the ``VALIDATION.md`` §4 ``critique``
block nobody asked for — interference, manifold, and the original request's
numbers against the built dimensions (:mod:`._critique`). It is assembled here,
by rule, from what the build already produced; a critique failure never fails
the build (the geometry is published and the result is truthful about the gap).

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
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.addressing import PART_SELECTOR, Resolution
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.lint import checks_thresholds
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.inspect import inspect_part, prepare_render_bundle
from hephaestus.core.types import BuildResult, Metrics
from opstore.types import JSONValue

from opstore import LeaseHeldError

from ..limits import MAX_IMAGES_PER_RESULT, parse_image_header
from ._base import CadOpError, CadOpsState, json_map
from ._critique import (
    critique_block,
    dfm_report,
    intentional_overlap_declarations,
    interference_report,
    named_solids,
    prompt_number_diff,
    with_dimension_findings,
)
from ._dfm import DfmOps
from ._findings import DimensionFindingOps, DimensionFindingState
from ._requirements import RequirementOps, entry_views

#: A reloaded build artifact resolves exactly the ``"part"`` selector (§7 rule 1).
_PART_RESOLUTION: Final[Resolution] = Resolution(kind="part", name=PART_SELECTOR)


def _why(exc: BaseException) -> str:
    """A refusal's own message where it has one; its type otherwise."""
    message = getattr(exc, "message", None)
    return message if isinstance(message, str) and message else f"{type(exc).__name__}: {exc}"


def metrics_solids(metrics: Metrics | None) -> int:
    """Solid count of a build, or 0 when the build reported no metrics."""
    return 0 if metrics is None else metrics.solids


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
        # INGEST.md §1: refresh the live imports/ state first, so a file the
        # operator replaced between builds marks its importers stale and
        # publication revalidation sees the current tree (mirrors the CLI).
        publisher.sync_import_state()
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
                imports=inputs.imports,
                import_errors=inputs.import_errors,
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
        if result.status == "ok":
            # VALIDATION.md §4: unrequested, by rule, on every successful build.
            payload["critique"] = self._critique(
                build, inputs.script, result.artifact_ref, preview=preview
            )
        return payload

    # -- the §4 post-build critique ----------------------------------------

    def _critique(
        self,
        build: UnpublishedBuild,
        script: str,
        artifact_ref: str | None,
        *,
        preview: bool = False,
    ) -> dict[str, JSONValue]:
        """Assemble the §4 critique block for a successful build."""
        metrics = build.result.metrics
        declared = intentional_overlap_declarations(
            json_map(build.worker_result.get("feature_metadata")),
            entry_views(self.ledger_state().entries) if isinstance(self, RequirementOps) else (),
        )
        block = critique_block(
            metrics=metrics,
            interference=self._interference(metrics_solids(metrics), artifact_ref, declared),
            request=self.request_text,
            dimensions=self._critique_dimensions(build, script),
            dfm=self._auto_dfm(build.result.part, artifact_ref),
        )
        try:
            state = self._record_dimension_findings(build, metrics, preview=preview)
        except Exception as exc:
            # The geometry is already published; refusing the caller its result now
            # would lose the build over the bookkeeping about it. But a store that
            # did not record must not read as a clean sheet, so the block says so —
            # the same rule the interference and DFM rungs follow.
            return with_dimension_findings(block, None, unavailable=_why(exc))
        return with_dimension_findings(block, state)

    def _record_dimension_findings(
        self, build: UnpublishedBuild, metrics: Metrics | None, *, preview: bool
    ) -> DimensionFindingState | None:
        """Bind this build's §4 number diff (``VALIDATION.md`` §4/§6), or don't.

        Returns ``None`` when there is nothing to bind: a *preview* build (its
        geometry was never published, so it is not what the run delivered), a
        runtime with no request text, or a project whose ops predate the store.

        The binding diff is recomputed here rather than lifted out of the block
        above, and against **measured** dimensions only — the script's own
        ``CHECKS`` thresholds are excluded. A run that could clear a binding
        finding by asserting the number in its own acceptance test would be
        clearing it with the misreading that raised it (the §5 rule, one rung
        down).
        """
        request = self.request_text
        if preview or request is None or metrics is None:
            return None
        if not isinstance(self, DimensionFindingOps):  # pragma: no cover - CadOps always is
            return None
        binding = prompt_number_diff(
            request, bbox_mm=metrics.bbox_mm, dimensions=self._measured_dimensions(build)
        )
        raw = binding.get("warnings")
        warnings = (
            [item for item in cast("list[JSONValue]", raw) if isinstance(item, dict)]
            if isinstance(raw, list)
            else []
        )
        return self.record_dimension_findings(
            build.result.part, cast("list[Mapping[str, JSONValue]]", warnings)
        )

    def _auto_dfm(self, part: str, artifact_ref: str | None) -> dict[str, JSONValue] | None:
        """DFM mode (mission Stage 6): the pack's findings on this exact artifact.

        Off unless the project asks for it (``[dfm] auto_run``), and then never
        fatal: the geometry is published either way, so every failure path — no
        declared process, no secure sandbox, a pack that will not load, a worker
        that dies — becomes an ``unavailable`` note inside the block instead of
        an exception that would cost the caller its build result.

        The run receives the exact ``artifact_ref`` this build published, never
        a "current" lookup: a preview build's critique is about the preview.
        """
        if not self._layout.manifest.dfm_auto_run or not isinstance(self, DfmOps):
            return None
        if artifact_ref is None:  # pragma: no cover - a successful build has an artifact
            return dfm_report(None, unavailable="the build published no artifact")
        try:
            target = self.dfm_target(part, artifact_ref=artifact_ref)
        except Exception as exc:
            return dfm_report(None, unavailable=_why(exc))
        try:
            evaluation = self.evaluate_target(target)
        except Exception as exc:
            return dfm_report(None, process=target.process, unavailable=_why(exc))
        return dfm_report(evaluation)

    def _interference(
        self, solid_count: int, artifact_ref: str | None, declared: Sequence[str]
    ) -> dict[str, JSONValue]:
        """Pairwise solid overlap over the published artifact (bounded).

        A compound with fewer than two solids has no pair to measure, so its
        geometry is never reloaded — the common single-solid part costs nothing.
        """
        if solid_count < 2:
            return interference_report((), declared_intentional=declared, solid_count=solid_count)
        if artifact_ref is None or not self._store.blobs.has(blob_hash_of_ref(artifact_ref)):
            return interference_report(
                (),
                declared_intentional=declared,
                solid_count=solid_count,
                unavailable="the build artifact is not durably stored",
            )
        try:
            with self._scratch("heph-critique-") as scratch:
                source = self._artifact_geometry(artifact_ref, Path(scratch))
                solids = named_solids(source.shape(_PART_RESOLUTION))
                return interference_report(solids, declared_intentional=declared)
        except Exception as exc:
            return interference_report(
                (),
                declared_intentional=declared,
                solid_count=solid_count,
                unavailable=f"{type(exc).__name__}: {exc}",
            )

    def _critique_dimensions(self, build: UnpublishedBuild, script: str) -> dict[str, float]:
        """The axis-less dimensions §4 matches request numbers against.

        Tagged *edge* lengths (the only tag descriptor scalar that is a length —
        faces carry area and solids volume) and every ``CHECKS`` numeric
        threshold, which is a dimension the script itself claims. The advisory
        block matches against both; the *binding* record
        (:meth:`_record_dimension_findings`) deliberately drops the second half.
        """
        dimensions = self._measured_dimensions(build)
        for threshold in checks_thresholds(script):
            dimensions[f"checks_threshold:{threshold:g}"] = threshold
        return dimensions

    @staticmethod
    def _measured_dimensions(build: UnpublishedBuild) -> dict[str, float]:
        """Dimensions the *kernel* measured: tagged edge lengths, nothing claimed."""
        return {
            f"tag:{name}": float(descriptor.scalar)
            for name, descriptor in build.tag_fingerprints.items()
            if descriptor.kind == "edge"
        }

    def current_build(self, name: str) -> BuildResult | None:
        """The last published *current* build of ``name`` (lock-free, no rebuild).

        The read the validation layer needs: ``VALIDATION.md`` §5 assembles the
        reviewer's evidence from what was actually published, never from a fresh
        build, so the reviewer judges the same geometry the agent delivered.
        """
        return self._publisher().current_result(name)

    def last_failure_build(self, name: str) -> BuildResult | None:
        """The most-recent published *failed* build of ``name`` (lock-free).

        ``GET /parts/{part}/build`` reads this when there is no current
        successful build, so a first-fail part projects its checkpoints and
        last-good instead of a ``not_built`` silence. A later success still
        wins: this is never preferred over :meth:`current_build`.
        """
        return self._publisher().last_failure_result(name)

    def current_bundle(self, name: str) -> Mapping[str, JSONValue] | None:
        """The published *bundle* behind ``name``'s current pointer (lock-free).

        The route to what publication recorded ABOUT a build rather than to the
        §8 ``BuildResult`` inside it: ``MESH_INGEST.md`` §4.3's
        ``geometry_source`` and §1.4's ``mesh_canonical_hashes`` live here, not
        on the result, because putting them on the result would have been a
        schema change across every record ever written for facts that are
        explanatory rather than identifying.
        """
        return self._publisher().current_bundle(name)

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
