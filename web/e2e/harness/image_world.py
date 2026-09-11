"""Owned packaged image world. No shared fake script slots or operator projects."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import select
import shlex
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

from serve_fixture import await_ready, build, start_server, stop, write_provider_config


def image_proof(data_uri: str, descriptor: dict[str, Any]) -> dict[str, Any]:
    from hephaestus.agent_bridge.limits import MAX_IMAGE_BYTES, parse_image_header
    from PIL import Image

    assert data_uri.startswith("data:image/png;base64,")
    data = base64.b64decode(data_uri.split(",", 1)[1], validate=True)
    assert len(data) <= MAX_IMAGE_BYTES
    dims = parse_image_header(data)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (dims.width, dims.height) == (960, 720)
    digest = hashlib.sha256(data).hexdigest()
    assert descriptor["render_artifact_ref"] == f"artifact:render:sha256:{digest}"
    assert descriptor["mime_type"] == "image/png"
    assert descriptor["bytes"] == len(data)
    assert (descriptor["width"], descriptor["height"]) == (dims.width, dims.height)
    return {**descriptor, "sha256": digest}


def main(directory: str, sol_endpoint: str | None = None) -> None:
    from hephaestus.testing.fake_openai import RequestInfo, start_fake_openai
    from hephaestus.testing.workspace_fixture import materialize_workspace_fixture

    scratch = Path(directory).resolve()
    scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    project = scratch / "workspace"
    home = scratch / "home"
    home.mkdir()
    # Explicit disposable HOME prevents discovery of operator auth/catalog/config.
    os.environ["HOME"] = str(home)
    os.environ["XDG_CONFIG_HOME"] = str(home / "config")
    os.environ["PI_CODING_AGENT_DIR"] = str(home / "pi")
    for key in list(os.environ):
        if key.endswith(("_API_KEY", "_TOKEN")) or key in (
            "NODE_OPTIONS",
            "HEPHAESTUS_PROVIDER_CONFIG",
        ):
            os.environ.pop(key)
    materialize_workspace_fixture(project)
    build(project, ("tread",))
    observations = scratch / "observations.jsonl"
    observations.touch(mode=0o600)

    def resolve(info: RequestInfo) -> Any:
        body = json.loads(info.body_text)
        if any(message.get("role") == "tool" for message in body["messages"]):
            return {
                "kind": "text",
                "chunks": ["IMAGE_TRANSPORT_ONLY_DONE (not a visual assessment)"],
            }
        return {
            "kind": "tool_calls",
            "calls": [
                {
                    "name": "inspect_part",
                    "arguments": {"name": "tread", "views": ["iso", "+X"]},
                    "id": "image_call",
                }
            ],
        }

    def observe(info: RequestInfo) -> None:
        body = json.loads(info.body_text)
        descriptors = []
        urls = []
        refusal = None
        for message in body["messages"]:
            if message.get("role") == "tool":
                result = json.loads(message["content"])
                descriptors.extend(result.get("images", []))
                refusal = result.get("code")
            content = message.get("content")
            if isinstance(content, list):
                urls.extend(
                    block["image_url"]["url"]
                    for block in content
                    if block.get("type") == "image_url"
                )
        assert len(urls) == len(descriptors)
        proofs = [image_proof(url, desc) for url, desc in zip(urls, descriptors, strict=True)]
        with observations.open("a") as output:
            output.write(
                json.dumps(
                    {
                        "index": info.index,
                        "model": body["model"],
                        "images": proofs,
                        "refusal": refusal,
                    }
                )
                + "\n"
            )

    # Exactly two two-request runs: text-only refusal and capable transport.
    fake = start_fake_openai([resolve] * 4, on_request=observe)
    spec = fake.provider_spec()
    spec["models"].append({**spec["models"][0], "id": "image-text-only", "input": ["text"]})
    write_provider_config(project, spec)
    if sol_endpoint is not None:
        from urllib.parse import urlparse

        endpoint = urlparse(sol_endpoint)
        assert endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
        # Fresh fabricated credential only. The pinned Codex adapter requires a
        # JWT-shaped access string with this account claim; no login or refresh.
        payload = base64.b64encode(
            json.dumps(
                {"https://api.openai.com/auth": {"chatgpt_account_id": "owned-loopback-fixture"}}
            ).encode()
        ).decode()
        auth = scratch / "synthetic-auth.json"
        auth.write_text(
            json.dumps(
                {
                    "openai-codex": {
                        "type": "oauth",
                        "access": f"synthetic.{payload}.not-a-signature",
                        "refresh": "unused-synthetic-refresh",
                        "expires": int(time.time() * 1000) + 3600000,
                    }
                }
            )
        )
        auth.chmod(0o600)
        config = {
            "providers": [
                spec,
                {"id": "openai-codex", "kind": "pi_native", "models": [{"id": "gpt-5.6-sol"}]},
            ],
            "auth_source": str(auth),
        }
        (project / ".heph" / "providers.json").write_text(json.dumps(config))
    node = shutil.which("node")
    assert node is not None
    launcher = scratch / "node-loopback"
    guard = Path(__file__).with_name("image_loopback.mjs").resolve()
    network_journal = scratch / "network.jsonl"
    launcher.write_text(
        "#!/bin/sh\n"
        f"export HEPH_TEST_ENDPOINT={shlex.quote(sol_endpoint or fake.base_url)}\n"
        f"export HEPH_TEST_EXTRA_ENDPOINT={shlex.quote(fake.base_url)}\n"
        f"export HEPH_TEST_CODEX_REDIRECT={'1' if sol_endpoint else '0'}\n"
        f"export HEPH_TEST_NETWORK_JOURNAL={shlex.quote(str(network_journal))}\n"
        f'exec {shlex.quote(node)} --import {shlex.quote(str(guard))} "$@"\n'
    )
    launcher.chmod(0o700)
    os.environ["HEPHAESTUS_NODE"] = str(launcher)
    server = None

    def interrupted(_signal: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        server = start_server(project)
        assert server.stdout is not None
        deadline = time.monotonic() + 180
        base_url = token = ""
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("owned image server exited before handshake")
            if not select.select([server.stdout], [], [], 0.2)[0]:
                continue
            line = server.stdout.readline().strip()
            if "/#t=" in line:
                base_url, _, token = line.partition("/#t=")
                break
        assert base_url and token, "owned image server startup timeout"
        await_ready(base_url, token)
        (scratch / "ready.json").write_text(
            json.dumps(
                {
                    "base_url": base_url,
                    "token": token,
                    "project_root": str(project),
                    "observations": str(observations),
                    "provider": spec["id"],
                    "image_model": "gpt-5.6-sol" if sol_endpoint else spec["models"][0]["id"],
                    "image_provider": "openai-codex" if sol_endpoint else spec["id"],
                    "text_model": "image-text-only",
                }
            )
        )
        while server.poll() is None:
            time.sleep(0.1)
        raise RuntimeError("owned image server exited unexpectedly")
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            stop(server)
        fake.close()
        (scratch / "cleanup.json").write_text(
            json.dumps(
                {
                    "server_pid": server.pid if server else None,
                    "server_exit": server.poll() if server else None,
                    "fake_closed": True,
                }
            )
        )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
