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
from typing import Any, cast

import pytest
from hephaestus.agent_bridge import cli as agent_cli
from hephaestus.agent_bridge.app import AuthLinkError, PromptResult, link_auth_source
from hephaestus.agent_bridge.client_mode import ClientModeError
from hephaestus.core.cli import build_parser
from hephaestus.testing.stream_assertions import text, tool_call
from test_e2e_fake_model import Harness

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


def test_agent_project_that_is_not_a_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mistyped or file-shaped ``--project`` must not walk up into another project.

    ``find_project_root`` resolves non-strictly and then climbs, so both a
    missing directory *inside* a project and the project's own
    ``hephaestus.toml`` would resolve to that project and run against it — a
    different root than the operator named, with a different transcript and
    different leases. ``heph serve --web`` refuses these by name; docs/cli.md
    promises the two verbs resolve ``--project`` identically, so this verb must
    refuse them the same way and with the same exit status.
    """
    (tmp_path / "hephaestus.toml").write_text("", encoding="utf-8")

    for target in (tmp_path / "typoo", tmp_path / "hephaestus.toml"):
        args = build_parser().parse_args(["agent", "--project", str(target), "--session", "s1"])
        assert args.func(args) == 2
        assert f"heph: agent: --project {target}: not a directory" in capsys.readouterr().err


def test_agent_project_that_is_a_directory_still_walks_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard refuses non-directories only; a real subdirectory still resolves."""
    (tmp_path / "hephaestus.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "parts"
    nested.mkdir()
    seen: dict[str, object] = {}

    def _attach(project_root: Path, **_kwargs: object) -> None:
        seen["root"] = project_root
        raise ClientModeError("server_unreachable", "stop here")

    monkeypatch.setattr(agent_cli, "attach_client", _attach)

    args = build_parser().parse_args(["agent", "--project", str(nested), "--session", "s1"])
    assert args.func(args) == 1
    assert seen["root"] == tmp_path
    assert "not a directory" not in capsys.readouterr().err


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
# pi_native providers: the opt-in auth_source link


def _synthetic_pi_auth(tmp_path: Path) -> Path:
    """A throwaway Pi auth.json — never the operator's real credential."""
    source = tmp_path / "pi" / "auth.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps(
            {
                "openai-codex": {
                    "type": "oauth",
                    "access": "synthetic-access-token",
                    "refresh": "synthetic-refresh-token",
                    "expires": 4102444800000,
                    "accountId": "synthetic-account",
                }
            }
        ),
        encoding="utf-8",
    )
    return source


def test_provider_config_defaults_to_no_auth_source(tmp_path: Path) -> None:
    """Isolation default: nothing outside the project is linked unless asked."""
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps({"providers": [{"id": "p", "kind": "anthropic", "models": []}]}),
        encoding="utf-8",
    )
    assert agent_cli.load_provider_config(path).auth_source is None


def test_provider_config_parses_auth_source(tmp_path: Path) -> None:
    source = _synthetic_pi_auth(tmp_path)
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai-codex",
                        "kind": "pi_native",
                        "models": [{"id": "gpt-5.6-sol"}],
                    }
                ],
                "auth_source": str(source),
            }
        ),
        encoding="utf-8",
    )
    config = agent_cli.load_provider_config(path)
    assert config.auth_source == source
    assert config.credential_allowlist == ()


def test_link_auth_source_creates_a_symlink_not_a_copy(tmp_path: Path) -> None:
    source = _synthetic_pi_auth(tmp_path)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    link = link_auth_source(agent_dir, source)
    assert link == agent_dir / "auth.json"
    assert link.is_symlink()
    assert link.resolve() == source.resolve()
    # A rotated token on the Pi side is visible through the link — the whole
    # point of not copying: one file, one refresh, no invalidated login.
    source.write_text(json.dumps({"openai-codex": {"access": "rotated"}}), encoding="utf-8")
    assert json.loads(link.read_text(encoding="utf-8"))["openai-codex"]["access"] == "rotated"


def test_link_auth_source_reports_a_missing_target(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    absent = tmp_path / "nowhere" / "auth.json"
    with pytest.raises(AuthLinkError) as exc:
        link_auth_source(agent_dir, absent)
    assert str(absent) in str(exc.value)
    assert not (agent_dir / "auth.json").exists()


def test_link_auth_source_refuses_to_clobber_real_credentials(tmp_path: Path) -> None:
    source = _synthetic_pi_auth(tmp_path)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    existing = agent_dir / "auth.json"
    existing.write_text(json.dumps({"anthropic": {"type": "api"}}), encoding="utf-8")
    with pytest.raises(AuthLinkError):
        link_auth_source(agent_dir, source)
    assert not existing.is_symlink()
    assert "anthropic" in existing.read_text(encoding="utf-8")


def test_link_auth_source_replaces_pis_empty_placeholder(tmp_path: Path) -> None:
    """The sidecar writes `{}` on first run; that is not a credential."""
    source = _synthetic_pi_auth(tmp_path)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "auth.json").write_text("{}", encoding="utf-8")
    assert link_auth_source(agent_dir, source).is_symlink()
    # Re-linking is idempotent: an existing link is ours to re-point.
    assert link_auth_source(agent_dir, source).resolve() == source.resolve()


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
# INTERFACE.md §7A.7 / §19.29 — one question, one answer value, two surfaces

#: The shared subject. ``web/test/stream/ask.test.ts`` reads the same file and
#: asserts the browser's ``answerValue`` against the same ``selection``, so a
#: surface that drifts fails the *other* surface's suite.
ANSWER_NAMESPACE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "stage4"
    / "goldens"
    / "ask"
    / "answer_namespace.json"
)


def answer_namespace_cases() -> list[dict[str, Any]]:
    document = json.loads(ANSWER_NAMESPACE.read_text(encoding="utf-8"))
    return [dict(case) for case in cast("list[Any]", document["cases"])]


@pytest.mark.parametrize("case", answer_namespace_cases(), ids=lambda c: str(c["name"]))
def test_the_cli_answers_with_the_option_label_the_web_widget_sends(
    case: dict[str, Any],
) -> None:
    """§7A.7: the answer value is the option's ``label``, on every surface.

    Before §19.29 this surface flattened options with ``str(o)``, so an object
    option — the ``{label, consequence}`` form ``_CLARIFICATION_OPTION`` requires
    — reached the model as a Python **dict repr** while the browser sent the
    label. Two clients answering one question handed the model two different
    values, and a value like ``"{'label': 'Go to 3 mm walls', …}"`` is not one
    ``ask_user``'s own schema admits.
    """
    out = io.StringIO()
    answerer = agent_cli.interactive_answerer(
        console_out=out, console_in=io.StringIO(f"{case['cli_input']}\n")
    )
    selection = answerer(dict(cast("dict[str, Any]", case["params"])))
    assert selection == case["selection"]

    rendered = out.getvalue()
    assert "{'label'" not in rendered, "a Python repr must never be shown as an option either"
    for line in cast("list[str]", case["cli_display"]):
        assert line in rendered, "§7.3: an option is shown with its geometric consequence"


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
    from hephaestus.testing.fake_openai import start_fake_openai
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
