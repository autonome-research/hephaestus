"""``heph agent``: verb registration, provider config, stream rendering, answers.

The verb is registered on the engine CLI through the ``cli_render`` dispatch
pattern, so the first test asserts it is reachable from ``heph`` itself. The rest
exercise the pieces a live session depends on — provider/credential resolution,
the normalized-event renderer (which must never see a bridge frame), image
save-to-file notices, and interactive ``ask_user`` answering — plus one run of
the renderer against the REAL sidecar so the console is proven on genuine events.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge import cli as agent_cli
from hephaestus.agent_bridge.app import PromptResult
from hephaestus.core.cli import build_parser
from test_e2e_fake_model import Harness, text, tool_call

pytest_plugins = ["test_e2e_fake_model"]


# --------------------------------------------------------------------------
# registration


def test_agent_verb_is_registered_on_the_engine_cli() -> None:
    parser = build_parser()
    args = parser.parse_args(["agent", "--project", "/tmp/x", "--session", "s1", "--resume"])
    assert args.func is agent_cli._cmd_agent  # pyright: ignore[reportPrivateUsage]
    assert args.project == "/tmp/x"
    assert args.session == "s1"
    assert args.resume is True
    assert args.profile == "orchestrator"


def test_engine_verbs_still_parse_after_the_agent_hook() -> None:
    parser = build_parser()
    assert parser.parse_args(["build", "widget"]).command == "build"
    assert parser.parse_args(["render", "widget"]).command == "render"


# --------------------------------------------------------------------------
# provider configuration


def test_provider_config_round_trip_and_credential_allowlist(tmp_path: Path) -> None:
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": [{"id": "p", "kind": "anthropic", "models": []}],
                "credential_allowlist": ["APPROVED_KEY"],
            }
        ),
        encoding="utf-8",
    )
    config = agent_cli.load_provider_config(path)
    assert config.providers[0]["id"] == "p"
    creds = config.credentials(
        {"APPROVED_KEY": "secret", "ANTHROPIC_API_KEY": "ambient-must-not-leak"}
    )
    # Only the allowlisted variable is forwarded; an ambient key is dropped.
    assert creds == {"APPROVED_KEY": "secret"}


@pytest.mark.parametrize(
    "body",
    ["{not json", json.dumps([1, 2]), json.dumps({"providers": []})],
)
def test_provider_config_rejects_unusable_files(tmp_path: Path, body: str) -> None:
    path = tmp_path / "providers.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(agent_cli.ConfigError):
        agent_cli.load_provider_config(path)


def test_missing_provider_config_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(agent_cli.ConfigError):
        agent_cli.load_provider_config(tmp_path / "absent.json")


# --------------------------------------------------------------------------
# rendering


def make_console(tmp_path: Path) -> tuple[agent_cli.AgentConsole, io.StringIO]:
    out = io.StringIO()
    return agent_cli.AgentConsole(image_dir=tmp_path / "img", out=out), out


def test_console_renders_text_tools_and_audit(tmp_path: Path) -> None:
    console, out = make_console(tmp_path)
    console.on_event({"run_id": "r", "seq": 0, "kind": "text_delta", "payload": {"text": "Hel"}})
    console.on_event({"run_id": "r", "seq": 1, "kind": "text_delta", "payload": {"text": "lo"}})
    console.on_event(
        {
            "run_id": "r",
            "seq": 2,
            "kind": "tool_call",
            "tool_call_id": "c0",
            "payload": {"name": "build_part", "arguments": {"name": "widget"}},
        }
    )
    console.on_event(
        {
            "run_id": "r",
            "seq": 3,
            "kind": "tool_result",
            "tool_call_id": "c0",
            "payload": {"toolName": "build_part", "text": '{"status":"ok"}', "isError": False},
        }
    )
    console.on_event({"run_id": "r", "seq": 4, "kind": "audit", "payload": {"event": "compaction"}})
    console.finish(PromptResult(run_id="r", status="completed", events=[], terminal=None))

    rendered = out.getvalue()
    assert "Hello" in rendered
    assert '[tool] build_part name="widget"' in rendered
    assert "[ok] build_part" in rendered
    assert "[audit] compaction" in rendered
    assert "[run completed]" in rendered
    # Streamed text is flushed onto its own line before the first chip.
    assert rendered.index("Hello") < rendered.index("[tool]")


def test_console_saves_images_and_reports_the_path(tmp_path: Path) -> None:
    console, out = make_console(tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"payload-bytes"
    import base64

    console.on_event(
        {
            "run_id": "run-1",
            "seq": 7,
            "kind": "image",
            "tool_call_id": "c1",
            "payload": {
                "mimeType": "image/png",
                "bytes": len(png),
                "data": base64.b64encode(png).decode("ascii"),
            },
        }
    )
    assert len(console.saved_images) == 1
    saved = console.saved_images[0]
    assert saved.read_bytes() == png
    assert saved.name == "run-1-7.png"
    assert f"[image] saved {saved}" in out.getvalue()


def test_console_discards_an_undecodable_image_without_writing(tmp_path: Path) -> None:
    console, out = make_console(tmp_path)
    console.on_event(
        {"run_id": "r", "seq": 1, "kind": "image", "payload": {"data": "!!not-base64!!"}}
    )
    assert console.saved_images == []
    assert "undecodable" in out.getvalue()


def test_console_never_prints_bridge_frames(tmp_path: Path) -> None:
    """A renderer fed a hostile payload still emits only its own vocabulary."""
    console, out = make_console(tmp_path)
    console.on_event(
        {
            "run_id": "r",
            "seq": 0,
            "kind": "tool_result",
            "payload": {"toolName": "read_part", "text": "x" * 5000},
        }
    )
    rendered = out.getvalue()
    assert "jsonrpc" not in rendered and '"hv"' not in rendered
    # Long tool text is summarized, never dumped.
    assert len(rendered) < 200


# --------------------------------------------------------------------------
# interactive ask_user answering


def answer_with(typed: str, params: dict[str, Any]) -> Any:
    out = io.StringIO()
    answerer = agent_cli.interactive_answerer(console_out=out, console_in=io.StringIO(typed))
    return answerer(params)


def test_answerer_maps_a_number_onto_an_option() -> None:
    selection = answer_with(
        "2\n", {"question": "Stock?", "options": ["6 mm", "12 mm"], "allow_free_text": False}
    )
    assert selection == "12 mm"


def test_answerer_accepts_free_text_when_permitted() -> None:
    selection = answer_with(
        "18 mm\n", {"question": "Stock?", "options": ["6 mm"], "allow_free_text": True}
    )
    assert selection == "18 mm"


def test_answerer_falls_back_to_an_option_when_free_text_is_denied() -> None:
    selection = answer_with(
        "nonsense\n", {"question": "Stock?", "options": ["6 mm"], "allow_free_text": False}
    )
    assert selection == "6 mm"


def test_answerer_returns_a_list_for_multi_select() -> None:
    selection = answer_with(
        "1,3\n",
        {
            "question": "Which?",
            "options": ["a", "b", "c"],
            "multi": True,
            "allow_free_text": False,
        },
    )
    assert selection == ["a", "c"]


def test_answerer_defaults_on_eof() -> None:
    selection = answer_with("", {"question": "Stock?", "options": ["6 mm", "12 mm"]})
    assert selection == "6 mm"


def test_answerer_prints_numbered_options() -> None:
    out = io.StringIO()
    answerer = agent_cli.interactive_answerer(console_out=out, console_in=io.StringIO("1\n"))
    answerer({"question": "Stock?", "options": ["6 mm", "12 mm"], "allow_free_text": False})
    printed = out.getvalue()
    assert "[question] Stock?" in printed
    assert "1) 6 mm" in printed and "2) 12 mm" in printed


# --------------------------------------------------------------------------
# the renderer against the real sidecar


def test_console_renders_a_real_run_end_to_end(harness: Harness, tmp_path: Path) -> None:
    console, out = make_console(tmp_path)
    harness.fake.set_script(
        [
            tool_call("create_part", {"name": "widget"}, "c0"),
            text("part ready"),
        ]
    )
    session_id = harness.runtime.create_session("orchestrator", session_id="cli-e2e")
    result = harness.runtime.prompt(
        session_id, "make a widget", on_event=console.on_event, timeout=300
    )
    console.finish(result)

    rendered = out.getvalue()
    assert "[tool] create_part" in rendered
    assert "[ok] create_part" in rendered
    assert "part ready" in rendered
    assert "[run completed]" in rendered
    assert "jsonrpc" not in rendered


# --------------------------------------------------------------------------
# the verb as a real subprocess


def test_heph_agent_subprocess_streams_and_answers(tmp_path: Path, sidecar_dist: Path) -> None:
    """Drive the actual verb: stdin prompts in, rendered stream + answers out."""
    from fake_openai import start_fake_openai
    from test_e2e_fake_model import scaffold_project

    project = scaffold_project(tmp_path / "proj", name="cli")
    fake = start_fake_openai(
        [
            tool_call("create_part", {"name": "widget"}, "c0"),
            text("widget created."),
            tool_call(
                "ask_user",
                {
                    "question": "Which stock?",
                    "options": ["6 mm", "12 mm"],
                    "allow_free_text": False,
                },
                "q0",
            ),
            text("noted."),
        ]
    )
    (project / ".heph").mkdir(exist_ok=True)
    (project / ".heph" / "providers.json").write_text(
        json.dumps({"providers": [fake.provider_spec()], "credential_allowlist": []}),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "hephaestus.agent_bridge.cli",
                "agent",
                "--project",
                str(project),
                "--session",
                "cli-1",
            ],
            input="make a widget\nwhat stock?\n2\n",
            text=True,
            capture_output=True,
            timeout=600,
            env=env,
            check=False,
        )
    finally:
        fake.close()

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "session cli-1 (orchestrator)" in out
    assert '[tool] create_part name="widget"' in out
    assert "widget created." in out
    assert "[question] Which stock?" in out
    assert "1) 6 mm" in out and "2) 12 mm" in out
    assert '"selection":"12 mm"' in out
    assert "noted." in out
    assert out.count("[run completed]") == 2
    # The private bridge is never surfaced by the verb.
    assert "jsonrpc" not in out and '"hv"' not in out
    assert (project / "parts" / "widget.py").exists()
