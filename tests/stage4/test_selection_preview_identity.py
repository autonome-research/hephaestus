# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Real selection previews: HTTP bytes -> same-run bridge/model -> archive.

Only the provider is fake. No synthetic render descriptors or decoder stubs.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.testing.fake_openai import RequestInfo, start_fake_openai
from PIL import Image


def runtime_blob(workspace: Any, ref: str) -> bytes:
    return workspace.runtime.store.blobs.get(blob_hash_of_ref(ref))


def test_selection_preview_http_and_same_run_model_identity(
    workspace: Any, sidecar_dist: Path, tmp_path: Path
) -> None:
    build = workspace.get("/parts/tread/build")
    source = build["artifact_ref"]
    args = {
        "name": "tread",
        "views": ["iso", "+X"],
        "channel": "mask",
        "mask_mode": "selection",
        "artifact_ref": source,
    }
    # Keep the actual HTTP envelope in a failure, not just raise_for_status.
    response = workspace.client.post(
        "/api/v1/parts/tread/inspect",
        json={k: v for k, v in args.items() if k != "name"},
        headers=workspace.headers,
    )
    (tmp_path / "http.json").write_text(response.text)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["source_artifact_ref"] == source
    assert len(document["images"]) == 2
    assert len(document["render_artifact_refs"]) == 8
    for index, image in enumerate(document["images"]):
        png = base64.b64decode(image["data"], validate=True)
        digest = hashlib.sha256(png).hexdigest()
        assert image["render_artifact_ref"] == f"artifact:selection-preview:sha256:{digest}"
        assert workspace.bytes(image["render_artifact_ref"]) == png
        assert image["palette_decodable"] is False
        with Image.open(io.BytesIO(png)) as decoded:
            decoded.load()
            assert decoded.size == (960, 720)
            assert len(decoded.getcolors(maxcolors=960 * 720) or []) > 1
        bundle = document["selection_bundles"][index]
        # HTTP /bytes serves previews, not bundle JSON or selection-pass
        # (the latter is a documented route-enumeration gap in artifacts.py).
        # Verify those retained artifacts at their real immutable store instead.
        stored_bundle = json.loads(runtime_blob(workspace, bundle["bundle_ref"]))
        assert stored_bundle["source_artifact_ref"] == source
        assert stored_bundle["preview_ref"] == image["render_artifact_ref"]
        assert stored_bundle["view"] == image["view"] == args["views"][index]
        for offset, kind in enumerate(("solid", "face", "edge"), 1):
            ref = bundle["pass_refs"][kind]
            assert ref == document["render_artifact_refs"][index * 4 + offset]
            pass_hash = hashlib.sha256(runtime_blob(workspace, ref)).hexdigest()
            assert ref == f"artifact:selection-pass:sha256:{pass_hash}"

    captured: list[dict[str, Any]] = []

    def report(info: RequestInfo) -> dict[str, Any]:
        body = json.loads(info.body_text)
        (tmp_path / "model-request.json").write_text(info.body_text)
        captured.append(body)
        return {"kind": "text", "chunks": ["TRANSPORT_ONLY_NOT_VISUAL_REVIEW"]}

    fake = start_fake_openai(
        [
            {
                "kind": "tool_calls",
                "calls": [{"name": "inspect_part", "arguments": args, "id": "selection-proof"}],
            },
            report,
        ]
    )
    runtime = workspace.runtime
    bridge = BridgeRuntime(
        project_root=runtime.root,
        providers=[fake.provider_spec()],
        dist_main=sidecar_dist,
        store=runtime.store,
        project_store=runtime.project_store,
        cad=runtime.cad,
        dispatcher=runtime.dispatcher,
    )
    dispatched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    dispatch = runtime.dispatcher.dispatch

    def record_dispatch(principal: Any, params: dict[str, Any]) -> Any:
        # Observe, never synthesize or alter, the real same-run Python result.
        result = dispatch(principal, params)
        dispatched.append((params, result))
        return result

    try:
        bridge.start()
        session = bridge.create_session("part", part="tread")
        with patch.object(runtime.dispatcher, "dispatch", side_effect=record_dispatch):
            outcome = bridge.prompt(session, "Inspect the pinned selection previews.", timeout=300)
        assert outcome.status == "completed", outcome
        assert len(captured) == len(dispatched) == 1
        params, document = dispatched[0]
        assert params["run_id"] == outcome.run_id
        assert params["session_id"] == session
        assert params["tool"] == "inspect_part"
        assert params["arguments"] == args
        # HTTP above and the model call are separate renders. Their source is
        # pinned, but edge raster bytes need not be identical across calls.
        # Transport identity must match THIS dispatch, not a nearby render.
        assert document["source_artifact_ref"] == source
        (tmp_path / "bridge-result.json").write_text(json.dumps(document))
        messages = captured[0]["messages"]
        tool = json.loads(next(m["content"] for m in messages if m["role"] == "tool"))
        assert tool["source_artifact_ref"] == source
        assert tool["render_artifact_refs"] == document["render_artifact_refs"]
        assert tool["selection_bundles"] == document["selection_bundles"]
        urls = [
            block["image_url"]["url"]
            for m in messages
            if isinstance(m.get("content"), list)
            for block in m["content"]
            if block.get("type") == "image_url"
        ]
        assert len(urls) == 2
        live = [e for e in outcome.events if e["kind"] == "image"]
        history = [e for e in bridge.history_page(session)["events"] if e["kind"] == "image"]
        assert len(live) == len(history) == 2
        for index, image in enumerate(document["images"]):
            identity = {
                key: image[key]
                for key in ("part", "view", "channel", "source_artifact_ref", "render_artifact_ref")
            }
            png = base64.b64decode(image["data"], validate=True)
            digest = hashlib.sha256(png).hexdigest()
            assert image["render_artifact_ref"] == f"artifact:selection-preview:sha256:{digest}"
            assert workspace.bytes(image["render_artifact_ref"]) == png
            with Image.open(io.BytesIO(png)) as decoded:
                decoded.load()
                assert decoded.size == (960, 720)
                assert len(decoded.getcolors(maxcolors=960 * 720) or []) > 1
            bundle = document["selection_bundles"][index]
            stored_bundle = json.loads(runtime_blob(workspace, bundle["bundle_ref"]))
            assert stored_bundle["source_artifact_ref"] == source
            assert stored_bundle["preview_ref"] == image["render_artifact_ref"]
            for kind in ("solid", "face", "edge"):
                ref = bundle["pass_refs"][kind]
                assert stored_bundle["pass_refs"][kind] == ref
                pass_hash = hashlib.sha256(runtime_blob(workspace, ref)).hexdigest()
                assert ref == f"artifact:selection-pass:sha256:{pass_hash}"
            assert urls[index] == "data:image/png;base64," + image["data"]
            assert all(tool["images"][index][key] == value for key, value in identity.items())
            assert "data" not in tool["images"][index]
            assert live[index]["run_id"] == outcome.run_id
            assert live[index]["payload"]["identity"] == identity
            assert history[index]["payload"]["identity"] == identity
            assert "data" not in history[index]["payload"]
        (tmp_path / "identity-proof.json").write_text(
            json.dumps(
                {
                    "run_id": outcome.run_id,
                    "source": source,
                    "images": tool["images"],
                    "history": history,
                },
                indent=2,
            )
        )
    finally:
        bridge.close()
        fake.close()
