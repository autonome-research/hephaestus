# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph registry`` CLI verbs — the bundled-registry symbolic path (J-cli-robustness-3).

``heph registry pin`` used to write ``bundled_registries_root()``'s answer —
an absolute path that, under an editable install, is the developer's clone —
straight into ``hephaestus.toml``, a file the documentation says to commit. A
pin is a reviewable claim about which bytes a design was verified against, not
a note to yourself about one machine's checkout. These tests pin the fix: a
bundled registry's pin is the symbolic ``bundled:<kind>`` form, an absolute
host path is refused unless the operator passed ``--path`` explicitly, and a
``bundled:`` pin resolves through the *reading* machine's own installation
(refusing by name when it ships none) rather than the pinning machine's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import main
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import MANIFEST_FILENAME
from hephaestus.core.registry._pins import (
    BUNDLED_SCHEME,
    RegistryPin,
    bundled_pins,
    bundled_registries_root,
)


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    return root


def test_bundled_pins_are_the_symbolic_scheme_not_an_absolute_path() -> None:
    """The real, installed bundled registries — every pin ``bundled_pins()``
    returns must be ``bundled:<kind>``, never a resolved filesystem path."""
    pins = bundled_pins()
    assert pins, "this checkout must ship at least one bundled registry"
    for kind, pin in pins.items():
        assert pin.path == f"{BUNDLED_SCHEME}{kind}", pin
        assert pin.is_bundled is True


def test_registry_pin_resolve_round_trips_the_bundled_scheme(tmp_path: Path) -> None:
    """``RegistryPin.resolve`` maps ``bundled:<kind>`` through the *reading*
    machine's own installation at read time, not at write time."""
    pin = RegistryPin(name="dfm", path=f"{BUNDLED_SCHEME}dfm")
    resolved = pin.resolve(tmp_path)
    root = bundled_registries_root()
    assert root is not None
    assert resolved == root / "dfm"
    assert (resolved / MANIFEST_FILENAME).is_file()


def test_registry_pin_resolve_refuses_by_name_with_no_bundled_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel install that ships no ``registries/`` tree must refuse the
    bundled scheme by name rather than resolving to a path that is not there."""
    monkeypatch.setattr("hephaestus.core.registry._pins.bundled_registries_root", lambda: None)
    pin = RegistryPin(name="dfm", path=f"{BUNDLED_SCHEME}dfm")
    with pytest.raises(ValidationError) as excinfo:
        pin.resolve(tmp_path)
    assert "dfm" in str(excinfo.value)
    assert "--path DIR" in str(excinfo.value)


def test_heph_registry_pin_writes_the_symbolic_form_with_no_absolute_path(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``heph registry pin dfm`` in a fresh project, no ``--path`` given: the
    manifest must gain a ``bundled:dfm`` path, never the resolved absolute
    directory this checkout happens to keep it in."""
    assert run(project, monkeypatch, "registry", "pin", "dfm", "--json") == 0
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    # `heph registry pin --json` reports the *resolved* path (an operator wants
    # to know where the bytes actually are, same as `list` below); it is the
    # persisted manifest that must carry the symbolic form.
    assert payload["name"] == "dfm", payload

    manifest_text = (project / "hephaestus.toml").read_text(encoding="utf-8")
    assert f'path = "{BUNDLED_SCHEME}dfm"' in manifest_text
    root = bundled_registries_root()
    assert root is not None
    assert str(root) not in manifest_text, (
        "the resolved absolute path must never land in the committed manifest"
    )


def test_heph_registry_list_still_prints_the_resolved_path(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An operator asking ``heph registry list`` wants to know where the bytes
    actually are on this machine, even though the manifest holds the symbol."""
    run(project, monkeypatch, "registry", "pin", "dfm")
    capsys.readouterr()
    assert run(project, monkeypatch, "registry", "list") == 0
    out = capsys.readouterr().out
    root = bundled_registries_root()
    assert root is not None
    assert str(root / "dfm") in out


def test_pinning_with_an_absolute_host_path_and_no_explicit_flag_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-pinning a registry whose *recorded* path is already an absolute,
    non-project, non-bundled string (the pre-fix shape) must not silently
    persist that path again — it is refused unless the operator names it with
    an explicit ``--path``."""
    stray = Path("/nonexistent/host/only/path")
    manifest = project / "hephaestus.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + f'\n[registries.stray]\npath = "{stray}"\ndigest = "sha256:{"a" * 64}"\n',
        encoding="utf-8",
    )
    code = run(project, monkeypatch, "registry", "pin", "stray")
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--path DIR" in err


def test_registry_list_json_is_one_envelope_not_a_bare_array(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``heph registry list --json`` used to ``json.dumps`` a bare list — no
    ``status``, nowhere for a future cursor (ledger J-cli-robustness-7). Every
    ``--json`` listing must share one envelope shape: an object carrying
    ``status`` and one plural array key."""
    assert run(project, monkeypatch, "registry", "list", "--json") == 0
    payload = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert payload["status"] == "ok", payload
    assert isinstance(payload["registries"], list), payload


def test_pinning_with_an_explicit_path_is_always_recorded_verbatim(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An explicit ``--path`` is the operator's own word, deliberate absolute
    paths included, and is recorded exactly as given — refusing it would take
    away the escape hatch the fix itself relies on."""
    root = bundled_registries_root()
    assert root is not None
    target = root / "dfm"
    assert run(project, monkeypatch, "registry", "pin", "dfm", "--path", str(target)) == 0
    manifest_text = (project / "hephaestus.toml").read_text(encoding="utf-8")
    assert f'path = "{target}"' in manifest_text
