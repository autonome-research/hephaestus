"""Fixed PID1 renderer: frozen BREP + closed metadata/options, never executable input."""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.executor.sandbox.oci_transfer import encode, open_directory, open_regular
from hephaestus.core.executor.sandbox.oci_worker_io import worker_io
from hephaestus.core.render.oci_protocol import (
    MAX_BREP,
    MAX_GLB,
    MAX_REQUEST,
    MAX_RESULT,
    MAX_TOPOLOGY,
    RENDER_VERSION,
    RENDER_WORKER,
    Entry,
    Image,
    Request,
    Response,
    Topology,
    read_request,
    request_hash,
    validate_response,
)

if TYPE_CHECKING:
    import numpy as np
    from hephaestus.core.render.palette import SelectionEntry
    from numpy.typing import NDArray


def _entry(value: SelectionEntry) -> Entry:
    result: Entry = {
        "kind": value.kind,
        "solid_index": value.solid_index,
        "topology_index": value.topology_index,
    }
    if value.label is not None:
        result["label"] = value.label
    if value.tag is not None:
        result["tag"] = value.tag
    return result


def _image(array: NDArray[np.uint8]) -> Image:
    raw = array.tobytes(order="C")
    return {
        "channels": array.shape[2],
        "pixels": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def render(request: Request, brep: bytes | None) -> Response:
    from hephaestus.core.render.offscreen import OffscreenSession

    result: Response = {
        "version": RENDER_VERSION,
        "operation": request["operation"],
        "request_sha256": request_hash(request),
        "source_ref": request["source_ref"] if request["operation"] != "probe" else None,
        "gl_renderer": "",
        "topology": [],
        "entries": {},
        "images": {},
        "section": None,
        "glb": None,
    }
    if request["operation"] == "probe":
        with OffscreenSession(32, 32) as session:
            result["gl_renderer"] = session.gl_renderer
        return result
    if (
        brep is None
        or not 0 < len(brep) <= MAX_BREP
        or hashlib.sha256(brep).hexdigest() != request["brep_sha256"]
    ):
        raise ValueError("frozen BREP identity mismatch")
    from build123d import Shape
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.core.executor.tags import TagPlacement
    from hephaestus.core.render.cameras import camera_framing, parse_view
    from hephaestus.core.render.channels import (
        RenderOptions,
        parse_section_plane,
        render_channel,
        scene_from_shape,
    )
    from hephaestus.core.render.palette import legend_to_entries
    from hephaestus.core.render.selection import build_selection_catalog, render_selection_view
    from hephaestus.core.render.tessellate import Tessellation

    shape = load_brep_shape(brep)
    if not isinstance(shape, Shape):
        raise ValueError("BREP did not decode to a shape")
    solids = list(shape.solids())
    if len(solids) != len(request["solids"]):
        raise ValueError("BREP solid count mismatch")
    topology: list[Topology] = [{"faces": len(s.faces()), "edges": len(s.edges())} for s in solids]
    if sum(1 + t["faces"] + t["edges"] for t in topology) > MAX_TOPOLOGY:
        raise ValueError("BREP topology admission bound")
    # Bounds before tessellation; kernel parsing/meshing still runs entirely
    # under tmpfs/cgroup/rlimit/wall controls (a small BREP can be expensive).
    for p in request["placements"]:
        count = topology[p["solid_index"]].get(p["kind"] + "s", len(solids))
        if p["topology_index"] >= count:
            raise ValueError("placement outside actual topology")
    scene = scene_from_shape(shape)
    scene = replace(
        scene,
        solids=tuple(
            replace(
                s,
                label=meta["label"],
                color=(meta["color"][0], meta["color"][1], meta["color"][2], meta["color"][3])
                if meta["color"] is not None
                else s.color,
                color_explicit=meta["color"] is not None,
            )
            for s, meta in zip(scene.solids, request["solids"], strict=True)
        ),
    )
    tess = Tessellation(solids=tuple(s.tessellation for s in scene.solids))
    result["topology"] = topology
    width, height = request["width"], request["height"]
    if request["operation"] in ("selection", "gltf"):
        placements = {
            p["tag"]: TagPlacement(p["kind"], p["solid_index"], p["topology_index"], 0, 0)
            for p in request["placements"]
        }
        labels = {
            s: label for s, m in enumerate(request["solids"]) if (label := m["label"]) is not None
        }
        catalog = build_selection_catalog(tess, placements=placements, labels=labels)
        result["entries"] = {str(k): _entry(v) for k, v in catalog.entries.items()}
        if request["operation"] == "gltf":
            from hephaestus.core.render.gltf import export_gltf

            links = request["links"]
            if links is None:
                raise ValueError("renderer GLB links missing")
            data = export_gltf(
                shape,
                catalog,
                source_artifact_ref=request["source_ref"],
                tess=tess,
                labels=labels,
                scene=scene,
                **links,
            )
            if len(data) > MAX_GLB:
                raise ValueError("GLB output bound")
            result["glb"] = {
                "data": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            # This operation also observes the actual software context, not a label.
            with OffscreenSession(32, 32) as session:
                result["gl_renderer"] = session.gl_renderer
            return result
        framing = camera_framing(
            *tess.bounds(), parse_view(request["view"]), width=width, height=height
        )
        with OffscreenSession(width, height) as session:
            arrays = render_selection_view(session, tess, catalog, framing, include_preview=True)
            result["gl_renderer"] = session.gl_renderer
        result["entries"] = {str(k): _entry(v) for k, v in catalog.entries.items()}
        result["images"] = {
            k: _image(getattr(arrays, k)) for k in ("solid", "face", "edge", "preview")
        }
    else:
        section_spec = None
        if request["operation"] == "section":
            from hephaestus.geom.measure import section

            p = request["section"]
            if p is None:
                raise ValueError("renderer section missing")
            section_spec = ("+" if p["sign"] == 1 else "-") + p["axis"] + "@" + str(p["offset"])
            plane = parse_section_plane(section_spec, scene.bbox_min, scene.bbox_max)
            faces = section(shape, plane.bd_plane())
            result["section"] = {"faces": len(faces), "area_mm2": sum(float(f.area) for f in faces)}
        view = render_channel(
            scene,
            [request["view"]],
            request["operation"],
            RenderOptions(width=width, height=height, section=section_spec),
        )[request["view"]]
        result["gl_renderer"] = view.gl_renderer
        result["images"] = {request["operation"]: _image(view.rgba)}
        if view.legend is not None:
            result["entries"] = {
                str(k): _entry(v) for k, v in legend_to_entries(view.legend).items()
            }
    return result


def main() -> int:
    try:
        io = worker_io()
        if io is None:
            raise ValueError("renderer requires fixed transport")
        request = read_request(sys.stdin.buffer.read(MAX_REQUEST + 1))
        brep = None
        if request["operation"] != "probe":
            fd = open_directory(Path("/inputs"))
            try:
                stream, info = open_regular(fd, "source.brep", MAX_BREP)
                with stream:
                    brep = stream.read(MAX_BREP + 1)
                if len(brep) != info.st_size:
                    raise ValueError("BREP changed")
            finally:
                os.close(fd)
        result = render(request, brep)
        validate_response(encode(result, MAX_RESULT), request)
        io.send(result, RENDER_WORKER)
        return 0
    except Exception as exc:
        # Fixed native worker only: bounded diagnostics aid loader/kernel debugging.
        # They are never trusted as a result or included in accepted provenance.
        import traceback

        frames = traceback.extract_tb(exc.__traceback__, limit=8)
        diagnostic = {
            "error": type(exc).__name__,
            "detail": str(exc)[:512],
            "frames": [[Path(f.filename).name, f.name, f.lineno] for f in frames],
        }
        sys.stderr.buffer.write(encode(diagnostic, 4096))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
