# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The composer's context envelope (``INTERFACE.md`` §7A.3, §19.19/§19.20).

**The client sends references; the server renders them into words.** That
sentence is the whole of this module, and §1 decides it before the UI question
is asked: the browser may compute screen-space quantities and may not compute,
synthesize, reconcile or infer any value that appears in a result, a badge, a
readout, a provenance answer or a selection. A prompt is none of those five —
but a prompt reaches a model that then *builds*, so §7A.3 applies §1 in its
strictest form and this is where that strictness lives.

Three properties are load-bearing and each is enforced here rather than trusted:

* **The envelope's member set is CLOSED** (:data:`ENVELOPE_MEMBERS`). Every
  member is either a closed-vocabulary token the client already owns as §4.5
  workspace state, or an opaque server-minted identifier the client is echoing
  back unmodified. There is no free-form field, no number the client computed,
  and no string the client authored — an unexpected key is
  ``400 invalid_params`` naming it, never a key quietly ignored.
* **A lying client is caught, not believed.** Resolution is server-side: an
  unknown ``part`` is ``unknown_part``, an ``artifact_ref`` outside this
  project's opstore is ``unknown_artifact``, a ``selection`` that does not
  resolve against the pinned ref is ``stale_selection`` — never a fallback to
  current geometry (§15.3) — and a malformed ``section_plane`` is
  ``invalid_params``. The envelope is a set of claims the server verifies
  against its own state, which is the only structural difference between
  *carrying context* and *letting the browser write the brief*.
* **Every fact in the block comes from an existing projection** — the
  serializers behind ``GET /parts/{part}/build``, ``/properties``, ``/checks``,
  ``/dfm`` and ``/artifacts/{ref}/meta``. Nothing here re-serializes what one of
  those already serializes (mission rule 6), and :data:`CONTEXT_SOURCE_ROUTES`
  is the closed list of reads a block may be composed from, reported to the
  client as ``sources`` so the operator can see which reads answered.

**Three members need their WHY stated**, because each is where a careless
implementation would smuggle in a fact (§7A.3):

* ``explode_t`` is a **parameter, not a displacement**. The GLTF ships each
  solid's ``explode_offset`` and the client applies ``offset · t``; the envelope
  carries ``t``, never a distance, and the block never says how far anything
  moved.
* ``hidden_labels`` reports **the toggles, not what is visible**. The namespace
  is the geometry-entry label from ``GET /parts/{part}/build``, the only
  namespace the client has. The block therefore says *"the operator has hidden
  the geometry labelled ``cleat_left``"* and **never** *"the operator can see 2
  solids"*: camera framing and occlusion are not knowable server-side, not
  knowable client-side without computing over geometry, and are claimed by
  neither.
* ``selection`` is **submitted, not described**. The envelope carries the ids;
  they are resolved against the pinned ref through
  :meth:`~hephaestus.agent_bridge.cad_ops.CadOps.describe_selection` — the
  engine seam, because ``server/http`` may not import the renderer at all
  (``test_http_boundary.py`` asserts that at import level) — and this module
  renders the *server's* answer into words.

**Truncation is marked, never silent** (§2.9's precedent, which
``git_projection._bounded_text`` set): the block is bounded by the shared
``text_result`` caps and a shortened block says so in its own last line as well
as in the ``truncated`` field, because the model reads the block and the panel
reads the field.

**Determinism.** The output is a pure function of ``(envelope, project state)``.
Sections appear in a fixed order, maps are rendered in sorted key order, and no
timestamp, path or process identity enters it — which is what makes
``tests/stage4/goldens/context/<case>.txt`` a review diff rather than a
coin flip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, cast

from hephaestus.agent_bridge.cad_ops import CadOpError
from hephaestus.agent_bridge.limits import LIMITS

from .errors import HttpRefusal, status_for_reason
from .projections import build_projection, checks_projection

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .runtime import WorkspaceRuntime

__all__ = [
    "BLOCK_MAX_BYTES",
    "BLOCK_MAX_LINES",
    "CONTEXT_SOURCE_ROUTES",
    "ENVELOPE_MEMBERS",
    "ComposedContext",
    "ContextEnvelope",
    "compose_context",
    "parse_envelope",
]

#: The envelope's **closed** member set (§7A.3). Every name here is §4.5
#: workspace state or a server-minted id echoed back; a body carrying anything
#: else is refused by name rather than having the extra key ignored, because a
#: silently dropped member is a context the operator saw in the chip row and the
#: model never received.
ENVELOPE_MEMBERS: Final[frozenset[str]] = frozenset(
    {
        "part",
        "artifact_ref",
        "pin_mode",
        "stage_tab",
        "inspector_tab",
        "view",
        "explode_t",
        "section_plane",
        "hidden_labels",
        "selection",
        "focus",
    }
)

#: The **only** reads a context block may be composed from, as route templates
#: (§7A.3: "reads only through the existing projections … and re-serializes
#: nothing"). ``sources`` in the response is the subset actually read, resolved,
#: in this order — so a reviewer can see that a block naming a check verdict got
#: it from the check report and not from somewhere new.
CONTEXT_SOURCE_ROUTES: Final[tuple[str, ...]] = (
    "/parts/{part}/build",
    "/parts/{part}/properties",
    "/parts/{part}/checks",
    "/parts/{part}/dfm",
    "/artifacts/{ref}/meta",
)

#: The shared ``text_result`` caps — the same numbers ``GET /git/diff`` and the
#: MCP text surface use, read from ``schemas/bridge_limits.json`` rather than
#: retyped as a second pair of literals.
BLOCK_MAX_BYTES: Final[int] = int(LIMITS["text_result"]["max_bytes"])
BLOCK_MAX_LINES: Final[int] = int(LIMITS["text_result"]["max_lines"])

#: §12.4/§5.3's only section-plane spelling, mirrored from `state/workspace.ts`
#: so a malformed plane is refused here rather than reaching a renderer.
_SECTION_PLANE: Final[re.Pattern[str]] = re.compile(r"^[+-][XYZ]@-?\d+(?:\.\d+)?$")

#: §4.5's closed vocabularies, restated as the guards this route validates
#: against. They are *the client's own* navigation tokens; a value outside them
#: is a client bug and is refused rather than normalized.
_PIN_MODES: Final[frozenset[str]] = frozenset({"current", "pinned"})
_STAGE_TABS: Final[frozenset[str]] = frozenset(
    {"viewport", "script", "timeline", "results", "diff"}
)
#: Tracks ``web/src/state/workspace.ts::INSPECTOR_TABS``. §22.7 added
#: ``export``; issue #12 added ``sourcing`` (BOM from declared manufacturing
#: fields). The envelope's tab tokens are *the client's own* navigation
#: vocabulary — a tab the client can open and this route refuses would be a
#: composer that stops working when the operator changes panel.
_INSPECTOR_TABS: Final[frozenset[str]] = frozenset(
    {"results", "properties", "provenance", "checks", "dfm", "export", "sourcing"}
)

#: The marker a shortened block carries **in its own text**. The model cannot
#: read the ``truncated`` field, so a block that was cut says so where the model
#: will see it; the field says the same thing to the panel.
TRUNCATION_MARKER: Final[str] = "[context truncated: the workspace state above is incomplete]"


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    """One validated envelope. Every field is a reference, never a fact."""

    part: str | None = None
    artifact_ref: str | None = None
    pin_mode: str | None = None
    stage_tab: str | None = None
    inspector_tab: str | None = None
    view: str | None = None
    explode_t: float | None = None
    section_plane: str | None = None
    hidden_labels: tuple[str, ...] = ()
    selection_id: str | None = None
    selection_bundle_ref: str | None = None
    focus: str | None = None

    @property
    def is_empty(self) -> bool:
        """§7A.3: "an empty or absent envelope is not an error".

        ``view`` names a reference once the operator adds it (issue #13).
        Navigation tabs alone are still the blank canvas; a camera token
        that the operator explicitly sent is not.
        """
        return (
            self.part is None
            and self.artifact_ref is None
            and self.selection_bundle_ref is None
            and not self.hidden_labels
            and self.section_plane is None
            and self.focus is None
            and self.view is None
        )


@dataclass(frozen=True, slots=True)
class ComposedContext:
    """What ``compose_context`` produced: the block, and how it was produced."""

    block: str
    truncated: bool
    sources: tuple[str, ...] = ()

    def projection(self) -> dict[str, Any]:
        """``POST /context/preview``'s body, and the prompt route's echo."""
        return {
            "status": "ok",
            "block": self.block,
            "truncated": self.truncated,
            "sources": list(self.sources),
        }


def _invalid(message: str, **data: Any) -> HttpRefusal:
    return HttpRefusal(400, "invalid_params", message, data=data)


def _token(body: dict[str, Any], key: str, allowed: frozenset[str]) -> str | None:
    """One closed-vocabulary token, or a refusal naming the vocabulary."""
    raw = body.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or raw not in allowed:
        raise _invalid(f"{key} must be one of {sorted(allowed)}", **{key: raw})
    return raw


def parse_envelope(body: Any) -> ContextEnvelope:
    """Validate one ``context`` member into a :class:`ContextEnvelope`.

    ``None`` is the blank canvas and composes nothing (§7A.3). Anything that is
    not a JSON object, or that carries a member outside
    :data:`ENVELOPE_MEMBERS`, is ``400 invalid_params`` **naming what was
    wrong** — the vocabulary is closed and nothing is silently skipped.
    """
    if body is None:
        return ContextEnvelope()
    if not isinstance(body, dict):
        raise _invalid("context must be an object or null")
    raw = cast("dict[Any, Any]", body)
    envelope: dict[str, Any] = {str(key): value for key, value in raw.items()}
    unexpected = sorted(set(envelope) - ENVELOPE_MEMBERS)
    if unexpected:
        raise _invalid(
            "context carries members this envelope does not admit; "
            "every member is §4.5 workspace state or a server-minted id",
            unexpected=unexpected,
            admitted=sorted(ENVELOPE_MEMBERS),
        )

    part = envelope.get("part")
    if part is not None and not isinstance(part, str):
        raise _invalid("part must be a string or null")
    artifact_ref = envelope.get("artifact_ref")
    if artifact_ref is not None and not isinstance(artifact_ref, str):
        raise _invalid("artifact_ref must be a string or null")
    view = envelope.get("view")
    if view is not None and not isinstance(view, str):
        raise _invalid("view must be a string or null")
    focus = envelope.get("focus")
    if focus is not None and not isinstance(focus, str):
        raise _invalid("focus must be a string or null")

    plane = envelope.get("section_plane")
    if plane is not None and (not isinstance(plane, str) or not _SECTION_PLANE.match(plane)):
        raise _invalid("section_plane must be spelled [+-]AXIS@OFFSET (§12.4)", section_plane=plane)

    explode_raw = envelope.get("explode_t")
    explode: float | None = None
    if explode_raw is not None:
        if isinstance(explode_raw, bool) or not isinstance(explode_raw, (int, float)):
            raise _invalid("explode_t must be a number in 0..1", explode_t=explode_raw)
        explode = float(explode_raw)
        if not 0.0 <= explode <= 1.0:
            raise _invalid("explode_t must be a number in 0..1", explode_t=explode_raw)

    hidden_raw: Any = envelope.get("hidden_labels", [])
    if hidden_raw is None:
        hidden_raw = []
    if not isinstance(hidden_raw, list):
        raise _invalid("hidden_labels must be an array of geometry-entry labels")
    hidden_items = cast("list[Any]", hidden_raw)
    if any(not isinstance(item, str) for item in hidden_items):
        raise _invalid("hidden_labels must be an array of geometry-entry labels")
    hidden = tuple(str(item) for item in hidden_items)

    selection_id: str | None = None
    bundle_ref: str | None = None
    selection_raw: Any = envelope.get("selection")
    if selection_raw is not None:
        if not isinstance(selection_raw, dict):
            raise _invalid("selection must be an object or null")
        selection: dict[str, Any] = {
            str(key): value for key, value in cast("dict[Any, Any]", selection_raw).items()
        }
        extra = sorted(set(selection) - {"selection_id", "bundle_ref", "kind"})
        if extra:
            raise _invalid("selection carries members it does not admit", unexpected=extra)
        raw_id: Any = selection.get("selection_id")
        raw_bundle: Any = selection.get("bundle_ref")
        if not isinstance(raw_bundle, str) or not raw_bundle:
            raise _invalid("selection.bundle_ref is required and must be a string")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
            raise _invalid("selection.selection_id is required")
        selection_id = str(raw_id)
        bundle_ref = raw_bundle

    return ContextEnvelope(
        part=part,
        artifact_ref=artifact_ref,
        pin_mode=_token(envelope, "pin_mode", _PIN_MODES),
        stage_tab=_token(envelope, "stage_tab", _STAGE_TABS),
        inspector_tab=_token(envelope, "inspector_tab", _INSPECTOR_TABS),
        view=view,
        explode_t=explode,
        section_plane=plane,
        hidden_labels=hidden,
        selection_id=selection_id,
        selection_bundle_ref=bundle_ref,
        focus=focus,
    )


@dataclass
class _Block:
    """A block under construction: lines, and the sources they came from."""

    lines: list[str] = field(default_factory=list[str])
    sources: list[str] = field(default_factory=list[str])

    def say(self, line: str = "") -> None:
        self.lines.append(line)

    def heading(self, title: str) -> None:
        if self.lines:
            self.say()
        self.say(f"## {title}")

    def read(self, route: str) -> None:
        if route not in self.sources:
            self.sources.append(route)


def compose_context(runtime: WorkspaceRuntime, envelope: ContextEnvelope) -> ComposedContext:
    """Render one validated envelope into the block the model is handed.

    Deterministic in ``(envelope, project state)`` and composed **only** from
    the projections :data:`CONTEXT_SOURCE_ROUTES` names. The result is what
    ``POST /context/preview`` shows and what ``POST /sessions/{id}/prompt``
    sends; the preview is advisory and the prompt composes again from this same
    function, because saying the preview were authoritative would be a claim the
    two calls cannot make good on (§7A.3).
    """
    block = _Block()
    if envelope.is_empty:
        # The blank canvas. §7A.3: "`context: null` is the blank canvas and the
        # server composes nothing." An envelope that names no reference is the
        # same fact arriving with the navigation fields still set, so it gets the
        # same empty block rather than a paragraph about tab positions.
        return ComposedContext(block="", truncated=False, sources=())

    block.say("# Workspace context")
    block.say()
    block.say(
        "The operator is looking at this workspace. Everything below is this "
        "server's own projection of the state their client named; it is not "
        "part of their request."
    )

    part = _verified_part(runtime, envelope)
    if part is not None:
        _say_part(runtime, block, part, envelope)
    if envelope.artifact_ref is not None:
        _say_artifact(runtime, block, envelope)
    if envelope.selection_bundle_ref is not None:
        _say_selection(runtime, block, envelope)
    _say_viewport(block, envelope)
    _say_panels(block, envelope)

    return _bounded("\n".join(block.lines) + "\n", tuple(block.sources))


def _verified_part(runtime: WorkspaceRuntime, envelope: ContextEnvelope) -> str | None:
    """The named part, **checked against the project store**, or a refusal.

    §7A.3's "a lying client is caught, not believed": a part the project does
    not have is ``404 unknown_part`` rather than a block that names it anyway.
    """
    if envelope.part is None:
        return None
    known = set(runtime.project_store.list_parts())
    if envelope.part not in known:
        raise HttpRefusal(
            404,
            "unknown_part",
            f"this project has no part {envelope.part!r}",
            data={"part": envelope.part, "parts": sorted(known)},
        )
    return envelope.part


def _say_part(
    runtime: WorkspaceRuntime, block: _Block, part: str, envelope: ContextEnvelope
) -> None:
    """The part's own four projections, in route order."""
    from .app import part_properties, project_checks

    # Imported at call time, not at module import: `http.app` imports this
    # module for the route, so a module-level import would be a cycle. The two
    # helpers are the *route handlers' own* reads — importing them is what makes
    # "the same projection the panel renders" literally true rather than a
    # second read that agrees today (mission rule 6).
    block.heading(f"Part: {part}")

    block.read(f"/parts/{part}/build")
    build = build_projection(runtime.cad.current_build(part))
    status = str(build["status"])
    if status == "not_built":
        block.say("This part has no current build.")
    else:
        block.say(f"build status: {status}")
        block.say(f"build artifact: {build['artifact_ref']}")
        block.say(f"geometry entries: {build['geometry_count']}")
        entries = cast("list[dict[str, Any]]", build["geometries"])
        labels = [str(entry["label"]) for entry in entries if entry.get("label") is not None]
        if labels:
            block.say(f"geometry labels: {', '.join(labels)}")
        params = cast("dict[str, Any]", build["effective_params"])
        if params:
            rendered = ", ".join(f"{name}={value}" for name, value in sorted(params.items()))
            block.say(f"effective parameters: {rendered}")

    block.read(f"/parts/{part}/properties")
    properties = part_properties(runtime, part)
    declared = cast("dict[str, str]", properties["properties"])
    if declared:
        block.say(f"declared properties (from {properties['source']}):")
        for name, value in sorted(declared.items()):
            block.say(f"  part.{name} = {value}")
    else:
        block.say("this part declares no part.* metadata")

    block.read(f"/parts/{part}/checks")
    badges = cast("dict[str, str]", checks_projection(project_checks(runtime))["badges"])
    if badges:
        block.say("project checks:")
        for name, verdict in sorted(badges.items()):
            block.say(f"  {name}: {verdict}")
    else:
        block.say("this project declares no checks")

    block.read(f"/parts/{part}/dfm")
    last = runtime.last_dfm(part)
    if last is None:
        block.say("no DFM run has been recorded for this part")
    else:
        findings = last.get("findings")
        count = len(cast("list[Any]", findings)) if isinstance(findings, list) else 0
        block.say(f"last DFM run: {count} findings")

    if envelope.hidden_labels:
        # THE HONESTY LIMIT, in the block's own words. §7A.3: this reports the
        # toggles, never what is visible. "Hidden" is a statement about a control
        # the operator moved; "visible" would be a claim about pixels neither
        # side can check.
        block.say(
            "the operator has hidden the geometry labelled "
            + ", ".join(sorted(envelope.hidden_labels))
        )
        block.say(
            "(that is a statement about their visibility toggles, not about "
            "what is on their screen)"
        )


def _say_artifact(runtime: WorkspaceRuntime, block: _Block, envelope: ContextEnvelope) -> None:
    """The pinned artifact, through ``GET /artifacts/{ref}/meta``'s serializer."""
    from .artifacts import artifact_meta  # (cycle; see `_say_part`)

    ref = envelope.artifact_ref
    assert ref is not None
    block.heading("Pinned artifact")
    block.read("/artifacts/{ref}/meta")
    # A ref outside this project's opstore refuses here, with the artifact
    # route's own reason — §2.2's project-scoped check, reached through the
    # projection rather than re-implemented (§7A.3's "a lying client is caught").
    meta = artifact_meta(runtime.store, ref)
    block.say(f"ref: {ref}")
    block.say(f"kind: {meta['kind']}")
    block.say(f"stored bytes: {meta['total_bytes']}")
    if envelope.pin_mode == "pinned":
        block.say("the operator has pinned this artifact; it is not necessarily the current build")
    else:
        block.say("the workspace is following the current build")


def _say_selection(runtime: WorkspaceRuntime, block: _Block, envelope: ContextEnvelope) -> None:
    """The submitted selection, **resolved server-side** (§12.3, §15.3).

    A selection that does not resolve against the pinned ref is
    ``409 stale_selection``. It is never a fallback to current geometry, and
    never a prompt that quietly drops the selection it claimed to carry.
    """
    bundle_ref = envelope.selection_bundle_ref
    assert bundle_ref is not None
    block.heading("Selection")
    # THROUGH THE ENGINE SEAM, not the renderer. `server/http` may not import
    # `core.render` at all — §1's closed list is unreachable from the web layer
    # *by construction* and `test_http_boundary.py` asserts it at import level —
    # and a resolved selection's kind, solid and tag are engine values. `CadOps`
    # is the seam the MCP server and the bridge already ride, so the workspace
    # rides the same one (mission rule 6). The route names ids; this renders the
    # server's answer into words.
    try:
        described = runtime.cad.describe_selection(
            bundle_ref,
            str(envelope.selection_id),
            expected_source_artifact_ref=envelope.artifact_ref,
        )
    except CadOpError as exc:
        # The same one mapping point `geometry.py` uses, for the same reason
        # (§2.4): the engine's reason string rides through unrewritten, its data
        # rides through whole — the five-value `stale_reason` vocabulary
        # included, which G5.15 enumerates — and the status comes from the
        # closed table rather than from a guess made here.
        raise HttpRefusal(
            status_for_reason(exc.reason), exc.reason, exc.message, data=dict(exc.data)
        ) from exc
    block.say(f"bundle: {described['bundle_ref']}")
    block.say(f"taken against: {described['source_artifact_ref']}")
    block.say(
        f"selection {described['selection_id']}: "
        f"a {described['kind']} on solid {described['solid_index']}"
    )
    if described["tag"] is not None:
        block.say(f"tagged {described['tag']}")
    if described["label"] is not None:
        block.say(f"on the geometry labelled {described['label']}")


def _say_viewport(block: _Block, envelope: ContextEnvelope) -> None:
    """§4.5 navigation state. Not a fact — a statement of where they are looking."""
    said: list[str] = []
    if envelope.view is not None:
        said.append(f"camera view: {envelope.view}")
    if envelope.explode_t is not None:
        # `explode_t` is the PARAMETER, never a displacement (§7A.3, §1). The
        # block says t; it never says how far anything moved, because the
        # distance is `offset · t` computed in the client's scene graph and a
        # server that restated it would be reporting a number it did not measure.
        said.append(f"exploded-view parameter t: {_number(envelope.explode_t)} (0 is assembled)")
    if envelope.section_plane is not None:
        said.append(f"section plane: {envelope.section_plane}")
    if not said:
        return
    block.heading("Viewport")
    for line in said:
        block.say(line)


def _say_panels(block: _Block, envelope: ContextEnvelope) -> None:
    said: list[str] = []
    if envelope.stage_tab is not None:
        said.append(f"stage tab: {envelope.stage_tab}")
    if envelope.inspector_tab is not None:
        said.append(f"inspector tab: {envelope.inspector_tab}")
    if envelope.focus is not None:
        said.append(f"focused on: {envelope.focus}")
    if not said:
        return
    block.heading("Panels the operator has open")
    for line in said:
        block.say(line)


def _number(value: float) -> str:
    """A float the block prints. Deterministic, and never in exponent form."""
    text = f"{value:.4f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def _bounded(text: str, sources: tuple[str, ...]) -> ComposedContext:
    """Bound the block to the ``text_result`` caps, **marking** any cut.

    ``git_projection._bounded_text`` set the precedent §2.9 names; this is the
    same shape with one addition — the marker goes into the *text* as well as
    into the field, because the model that reads the block cannot read the
    field, and a model told a partial workspace state is complete would reason
    from an absence it had no way to detect.
    """
    lines = text.splitlines(keepends=True)
    truncated = False
    if len(lines) > BLOCK_MAX_LINES:
        lines = lines[:BLOCK_MAX_LINES]
        truncated = True
    body = "".join(lines)
    if len(body.encode("utf-8")) > BLOCK_MAX_BYTES:
        kept: list[str] = []
        size = 0
        for line in lines:
            step = len(line.encode("utf-8"))
            if size + step > BLOCK_MAX_BYTES:
                break
            kept.append(line)
            size += step
        body = "".join(kept)
        truncated = True
    if truncated:
        body = body + TRUNCATION_MARKER + "\n"
    return ComposedContext(block=body, truncated=truncated, sources=sources)
