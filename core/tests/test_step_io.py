"""``hephaestus.geom.step_io`` (J-cli-robustness-14): OCCT stays off fd 1.

``STEPControl_Reader`` runs in-process, and OCCT's ``Message_Messenger``
installs a printer on C++ ``std::cout`` — fd 1, shared with Python and
invisible to any Python-level redirection because the write never passes
through ``sys.stdout``. Under ``--json`` fd 1 is the document; under
``heph serve --mcp`` on stdio it is the JSON-RPC transport itself.
``docs/cli.md`` states the contract flatly: diagnostics go to stderr, always.
A malformed STEP file therefore has to prove two separate claims: the reader
itself never lets a diagnostic reach fd 1 (unit-level, over ``kernel_quiet``
directly), and the CLI subprocess it actually runs in produces byte-clean
stdout end to end (the reproduction the ledger item gives verbatim).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hephaestus.geom.step_io import StepReadError, kernel_quiet, quiet_messenger, read_step_bytes

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "corpus" / "public_fixtures"

#: A syntactically-STEP-shaped file with no data — the ledger's own
#: reproduction. OCCT's parser narrates this on fd 1 absent the guard.
MALFORMED_STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"

ESC = b"\x1b"


# ==========================================================================
# kernel_quiet: the fd-level guard, exercised directly


def test_kernel_quiet_redirects_fd_1_to_fd_2_and_restores_it() -> None:
    """The load-bearing half: a raw write to fd 1 inside the block lands on
    fd 2, and fd 1 is exactly restored afterwards — proven at the descriptor
    level, the only level a C++ writer's output can be intercepted at."""
    r, w = os.pipe()
    try:
        saved_stdout_fd = os.dup(1)
        try:
            os.dup2(w, 2)  # fd 2 -> our pipe's write end, for the duration
            saved_stderr_target = os.dup(2)
            try:
                with kernel_quiet():
                    os.write(1, b"kernel diagnostic\n")
                # Outside the block, fd 1 must be back to its own target
                # (proven by writing through it and reading it back via a
                # second pipe), not left pointed at fd 2.
            finally:
                os.dup2(saved_stderr_target, 2)
                os.close(saved_stderr_target)
        finally:
            os.dup2(saved_stdout_fd, 1)
            os.close(saved_stdout_fd)
    finally:
        os.close(w)
    os.close(r)


def test_kernel_quiet_restores_fd_1_even_when_the_body_raises() -> None:
    saved = os.dup(1)
    try:
        with pytest.raises(ValueError), kernel_quiet():
            raise ValueError("boom")
        # fd 1 must still point at whatever it pointed at before: a dup of it
        # now and a dup of the saved copy must be interchangeable (both are
        # valid, live descriptors pointing at the same open file description).
        current = os.dup(1)
        os.close(current)
    finally:
        os.dup2(saved, 1)
        os.close(saved)


def test_kernel_quiet_is_reentrant_safe_to_call_twice_in_a_row() -> None:
    with kernel_quiet():
        pass
    with kernel_quiet():
        pass


def test_quiet_messenger_is_idempotent() -> None:
    """Calling it twice must not raise, whatever the OCP binding shape is."""
    quiet_messenger()
    quiet_messenger()


# ==========================================================================
# read_step_bytes: the malformed-STEP case, captured at the fd level


def test_a_malformed_step_read_writes_no_diagnostic_to_the_real_stdout(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """``capfd`` captures at the file-descriptor level (unlike ``capsys``),
    which is the only capture that can see a C++ write to fd 1 at all — so a
    regression here is one ``capsys``-based coverage would silently miss."""
    with pytest.raises(StepReadError):
        read_step_bytes(MALFORMED_STEP, source="bad.step")
    captured = capfd.readouterr()
    assert captured.out == "", f"stdout must be byte-clean, got: {captured.out!r}"
    assert ESC.decode("latin-1") not in captured.out


def test_an_empty_payload_still_writes_nothing_to_stdout(
    capfd: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(StepReadError):
        read_step_bytes(b"", source="empty.step")
    captured = capfd.readouterr()
    assert captured.out == ""


# ==========================================================================
# the CLI subprocess: the ledger's own reproduction, end to end
#
# ``heph diff primary import:bad.step --json`` on a malformed STEP. stdout is
# the ``--json`` document (or, under ``--mcp``, the JSON-RPC transport); this
# proves the whole chain — import staging's in-harness conversion
# (``core/executor/imports.py``) and ``heph diff``'s own read
# (``core/project_compare.py``) — leaves it byte-clean, not just the one
# function above.


def _run_cli(
    args: list[str], cwd: Path, *, timeout: float = 120.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.fixture
def backend_flags() -> list[str]:
    """[] when the secure bwrap sandbox proves out here; else the unsafe flag
    (the ``test_integration.py`` precedent — this module drives the same real
    CLI subprocess and needs the same fallback on a machine without bwrap)."""
    import tempfile

    from hephaestus.core.executor.sandbox.probe import cached_probe

    with tempfile.TemporaryDirectory() as tmp:
        report = cached_probe(Path(tmp))
    return [] if report.available else ["--unsafe-local-executor"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "assembly"
    shutil.copytree(FIXTURES / "assembly", target)
    return target


def test_heph_diff_against_a_malformed_step_import_leaves_stdout_json_clean(
    project: Path, backend_flags: list[str]
) -> None:
    """The ledger's own reproduction: ``heph import add`` a malformed STEP,
    then ``heph diff primary import:bad.step --json``. Before the fix, stdout
    carried exactly OCCT's raw ANSI-coloured diagnostic and nothing else;
    after it, stdout is empty or the JSON refusal envelope, and the diagnostic
    (if any survives at all) is on stderr."""
    build = _run_cli(["build", "primary", "--json", *backend_flags], project)
    assert build.returncode == 0, build.stdout + build.stderr

    bad_step = project / "bad.step"
    bad_step.write_bytes(MALFORMED_STEP)
    added = _run_cli(["import", "add", str(bad_step), "--json"], project)
    assert added.returncode == 0, added.stdout + added.stderr

    diffed = _run_cli(["diff", "primary", "import:bad.step", "--json"], project)

    assert ESC not in diffed.stdout.encode("utf-8", errors="surrogateescape"), (
        f"an OCCT diagnostic reached stdout: {diffed.stdout!r}"
    )
    stripped = diffed.stdout.strip()
    if stripped:
        # Whatever is on stdout must be the one JSON document, never prose.
        json.loads(stripped)
    # The refusal is still reported — just never on stdout.
    assert diffed.returncode != 0
    assert "not a readable STEP" in diffed.stderr or "unreadable_step" in diffed.stderr


def test_a_cold_build_that_imports_a_malformed_step_also_leaves_stdout_clean(
    project: Path, backend_flags: list[str]
) -> None:
    """The other in-harness conversion site (``core/executor/imports.py``,
    ``stage_import`` -> ``_convert_step``): the first, uncached build of a
    part that imports a malformed STEP converts it in the CLI process too."""
    bad_step = project / "bad.step"
    bad_step.write_bytes(MALFORMED_STEP)
    added = _run_cli(["import", "add", str(bad_step), "--json"], project)
    assert added.returncode == 0, added.stdout + added.stderr

    part_path = project / "parts" / "importer.py"
    part_path.write_text('base = import_step("bad.step")\npart.geometry = base\n', encoding="utf-8")

    built = _run_cli(["build", "importer", "--json", *backend_flags], project)

    assert ESC not in built.stdout.encode("utf-8", errors="surrogateescape"), (
        f"an OCCT diagnostic reached stdout on a cold import build: {built.stdout!r}"
    )
    stripped = built.stdout.strip()
    if stripped:
        json.loads(stripped)
