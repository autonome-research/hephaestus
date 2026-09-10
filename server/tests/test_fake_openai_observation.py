"""Provider-side evidence must include tool-less HTTP requests, not only scripted turns."""

from __future__ import annotations

import json
import urllib.request

from hephaestus.testing.fake_openai import RequestInfo, start_fake_openai


def test_observer_records_every_model_http_request_including_compaction() -> None:
    models: list[str] = []

    def observe(info: RequestInfo) -> None:
        models.append(str(json.loads(info.body_text)["model"]))

    fake = start_fake_openai(on_request=observe)
    try:
        for model, tools in [("text", [{"function": {"name": "probe"}}]), ("vision", [])]:
            request = urllib.request.Request(
                f"{fake.base_url}/chat/completions",
                data=json.dumps({"model": model, "tools": tools, "messages": []}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
                assert b"[DONE]" in response.read()
        assert models == ["text", "vision"]
        assert len(fake.requests) == 2
    finally:
        fake.close()
