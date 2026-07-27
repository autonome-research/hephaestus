"""BwrapBackend tests: real build123d job inside the sandbox, escape denial,
wall-clock and memory kills, argv construction."""

from __future__ import annotations

import json
import os
import socket
import sys
import sysconfig
import textwrap
import time
from pathlib import Path

import pytest
from hephaestus.core.executor.sandbox.base import (
    ExecBackend,
    ExecOutcome,
    Rlimits,
    SandboxSpec,
)
from hephaestus.core.executor.sandbox.bwrap import (
    BwrapBackend,
    base_os_argv,
    build_bwrap_argv,
    describe_argv,
    find_bwrap,
    interpreter_ro_binds,
    prune_binds,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="bwrap sandbox requires Linux with bubblewrap installed",
)

GIB = 1 << 30


def make_spec(
    tmp_path: Path,
    code: str,
    *,
    extra_ro: tuple[Path, ...] = (),
    cpu_seconds: int = 60,
    address_space_bytes: int = 6 * GIB,
    nproc: int = 4096,
    wall_clock_s: float = 120.0,
) -> SandboxSpec:
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    return SandboxSpec(
        worker_cmd=(sys.executable, "-c", code),
        ro_binds=(*interpreter_ro_binds(), *extra_ro),
        rw_out_dir=out_dir,
        rlimits=Rlimits(
            cpu_seconds=cpu_seconds,
            address_space_bytes=address_space_bytes,
            nproc=nproc,
        ),
        wall_clock_s=wall_clock_s,
    )


def last_json(outcome: ExecOutcome) -> dict[str, object]:
    lines = outcome.stdout.decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("{"):
            parsed: object = json.loads(stripped)
            assert isinstance(parsed, dict)
            return {str(k): v for k, v in parsed.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    raise AssertionError(f"no JSON line in stdout: {outcome.stdout!r} / {outcome.stderr!r}")


class TestProtocolConformance:
    def test_backend_is_exec_backend(self) -> None:
        backend = BwrapBackend()
        assert isinstance(backend, ExecBackend)
        assert backend.name == "bwrap"


class TestBuild123dInsideSandbox:
    def test_real_geometry_job_runs_inside_bwrap(self, tmp_path: Path) -> None:
        """The critical proof: build123d imports and builds INSIDE bwrap with the
        venv ro-bound, the project dir ro-bound, and one rw out dir."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "data.txt").write_text("hello from project fixture\n")
        code = textwrap.dedent(
            f"""
            import json, sys
            request = json.loads(sys.stdin.read())
            from build123d import Box
            part = Box(*request["dims"])
            fixture = open({str(project / "data.txt")!r}).read()
            with open("proof.json", "w") as f:
                json.dump({{"volume": part.volume}}, f)
            print(json.dumps({{
                "volume": part.volume,
                "solids": len(part.solids()),
                "fixture": fixture,
                "echo": request["token"],
            }}))
            """
        )
        spec = make_spec(tmp_path, code, extra_ro=(project,))
        payload = json.dumps({"dims": [10, 5, 2.5], "token": "rt-42"}).encode()
        outcome = BwrapBackend().execute(spec, payload)
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
        assert not outcome.timed_out
        result = last_json(outcome)
        assert result["volume"] == pytest.approx(125.0, abs=1e-6)
        assert result["solids"] == 1
        assert result["fixture"] == "hello from project fixture\n"
        assert result["echo"] == "rt-42"
        # the worker's artifact landed in the rw out dir, visible to the host
        proof = json.loads((spec.rw_out_dir / "proof.json").read_text())
        assert proof["volume"] == pytest.approx(125.0, abs=1e-6)

    def test_deterministic_metrics_across_two_runs(self, tmp_path: Path) -> None:
        code = textwrap.dedent(
            """
            import json
            from build123d import Box, fillet
            part = Box(20, 10, 5)
            part = fillet(part.edges(), radius=1.0)
            print(json.dumps({
                "volume": part.volume,
                "area": part.area,
                "faces": len(part.faces()),
            }))
            """
        )
        results: list[dict[str, object]] = []
        for run_dir in ("a", "b"):
            sub = tmp_path / run_dir
            sub.mkdir()
            outcome = BwrapBackend().execute(make_spec(sub, code), b"")
            assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
            results.append(last_json(outcome))
        first, second = results
        assert first["faces"] == second["faces"]
        assert float(str(first["volume"])) == pytest.approx(float(str(second["volume"])), abs=1e-6)
        assert float(str(first["area"])) == pytest.approx(float(str(second["area"])), abs=1e-6)


ESCAPE_PROBE_CODE = textwrap.dedent(
    """
    import json, os, socket, subprocess, sys

    cfg = json.loads(sys.stdin.read())
    project = cfg["project_dir"]
    checks = {}

    def attempt(name, fn, expect_blocked):
        try:
            fn()
            blocked = False
        except Exception:
            blocked = True
        checks[name] = blocked is expect_blocked

    def _connect(host, port):
        s = socket.create_connection((host, port), timeout=3)
        s.close()

    attempt("read_etc_shadow", lambda: open("/etc/shadow", "rb").read(1), True)
    attempt("write_fs_root", lambda: open("/pwned.txt", "w"), True)
    attempt("write_etc", lambda: open("/etc/pwned.txt", "w"), True)
    attempt(
        "write_into_ro_project_bind",
        lambda: open(os.path.join(project, "pwned.txt"), "w"),
        True,
    )
    attempt(
        "write_into_ro_venv_bind",
        lambda: open(os.path.join(sys.prefix, "pwned.txt"), "w"),
        True,
    )
    attempt("write_home_skeleton", lambda: open("/home/pwned.txt", "w"), True)
    attempt(
        "read_host_secret_outside_binds",
        lambda: open(cfg["secret_file"], "rb").read(1),
        True,
    )
    attempt(
        "dotdot_traversal",
        lambda: open(os.path.join(project, "..", "..", "etc", "passwd"), "rb").read(1),
        True,
    )

    def _symlink_escape():
        link = "/tmp/esc"
        os.symlink(cfg["secret_dir"], link)
        return open(os.path.join(link, "secret.txt"), "rb").read(1)

    attempt("symlink_to_host_secret_escape", _symlink_escape, True)
    attempt("tcp_public_internet", lambda: _connect("1.1.1.1", 443), True)
    attempt(
        "tcp_host_loopback_listener",
        lambda: _connect("127.0.0.1", cfg["localhost_port"]),
        True,
    )
    attempt("kill_host_pid", lambda: os.kill(cfg["host_pid"], 0), True)

    def _env_leak():
        out = subprocess.run(
            ["/usr/bin/env"], capture_output=True, text=True, timeout=10, check=True
        ).stdout
        if cfg["sentinel_name"] in out or cfg["sentinel_name"] in os.environ:
            return "leaked"
        raise RuntimeError("sentinel absent")

    attempt("host_env_leak", _env_leak, True)
    attempt("tmp_write_allowed", lambda: open("/tmp/scratch.txt", "w").write("x"), False)
    attempt("out_dir_write_allowed", lambda: open("ok.txt", "w").write("x"), False)
    print(json.dumps(checks))
    """
)


class TestEscapeDenial:
    def test_all_escape_probes_denied_from_within_a_job(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / "data.txt").write_text("fixture\n")
        # a host file that is NOT in any bind: invisible inside the sandbox
        # (host /tmp is shadowed by the sandbox tmpfs), so reads must fail
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        (secret_dir / "secret.txt").write_text("host-only\n")
        sentinel = "HEPH_SANDBOX_SENTINEL"
        os.environ[sentinel] = "must-not-leak"
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            cfg = {
                "project_dir": str(project),
                "localhost_port": port,
                "host_pid": os.getpid(),
                "sentinel_name": sentinel,
                "secret_dir": str(secret_dir),
                "secret_file": str(secret_dir / "secret.txt"),
            }
            spec = make_spec(tmp_path, ESCAPE_PROBE_CODE, extra_ro=(project,))
            outcome = BwrapBackend().execute(spec, json.dumps(cfg).encode())
        finally:
            listener.close()
            del os.environ[sentinel]
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
        checks = last_json(outcome)
        failed = sorted(name for name, ok in checks.items() if ok is not True)
        assert failed == [], f"escape probes not contained: {failed}"
        # host-side: nothing leaked into the ro project bind, out-dir write landed
        assert not (project / "pwned.txt").exists()
        assert (spec.rw_out_dir / "ok.txt").is_file()


class TestResourceLimits:
    def test_wall_clock_kill_on_infinite_loop(self, tmp_path: Path) -> None:
        spec = make_spec(
            tmp_path,
            "while True:\n    pass\n",
            cpu_seconds=600,
            wall_clock_s=2.0,
        )
        start = time.monotonic()
        outcome = BwrapBackend().execute(spec, b"")
        elapsed = time.monotonic() - start
        assert outcome.timed_out
        assert outcome.exit_code != 0
        assert elapsed < 30.0

    def test_memory_rlimit_kills_oversized_allocation(self, tmp_path: Path) -> None:
        code = textwrap.dedent(
            """
            import json
            try:
                buf = bytearray(2 * 1024 ** 3)
                buf[::4096] = b"x" * len(buf[::4096])
                print(json.dumps({"killed": False}))
            except MemoryError:
                print(json.dumps({"killed": True}))
            """
        )
        spec = make_spec(tmp_path, code, address_space_bytes=512 * (1 << 20))
        outcome = BwrapBackend().execute(spec, b"")
        assert not outcome.timed_out
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
        assert last_json(outcome) == {"killed": True}


class TestArgvConstruction:
    def test_argv_profile(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        spec = SandboxSpec(
            worker_cmd=(sys.executable, "-c", "print('hi')"),
            ro_binds=(project, *interpreter_ro_binds()),
            rw_out_dir=out_dir,
            rlimits=Rlimits(cpu_seconds=60, address_space_bytes=GIB, nproc=64),
            wall_clock_s=30.0,
        )
        argv = build_bwrap_argv("/usr/bin/bwrap", spec)
        for flag in (
            "--unshare-net",
            "--unshare-pid",
            "--unshare-user",
            "--unshare-ipc",
            "--unshare-uts",
            "--clearenv",
            "--die-with-parent",
        ):
            assert flag in argv
        # exactly ONE rw bind: the out dir, identity-mapped
        rw_binds = [argv[i : i + 3] for i, a in enumerate(argv) if a == "--bind"]
        assert rw_binds == [("--bind", str(out_dir), str(out_dir))]
        # every ro_bind identity-mapped
        ro_pairs = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--ro-bind"]
        for bind in (project.resolve(), *interpreter_ro_binds()):
            assert (str(bind), str(bind)) in ro_pairs
        # remount-ro seals the root AFTER the binds; worker_cmd is the tail
        assert argv.index("--remount-ro") > argv.index("--bind")
        assert argv[-3:] == (sys.executable, "-c", "print('hi')")
        # no host environment forwarded: only fixed --setenv pairs
        setenv_keys = {argv[i + 1] for i, a in enumerate(argv) if a == "--setenv"}
        assert setenv_keys == {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONDONTWRITEBYTECODE"}

    def test_missing_out_dir_rejected(self, tmp_path: Path) -> None:
        spec = SandboxSpec(
            worker_cmd=(sys.executable, "-c", "pass"),
            ro_binds=interpreter_ro_binds(),
            rw_out_dir=tmp_path / "does-not-exist",
            rlimits=Rlimits(cpu_seconds=60, address_space_bytes=GIB, nproc=64),
            wall_clock_s=30.0,
        )
        with pytest.raises(ValueError, match="rw_out_dir"):
            build_bwrap_argv("/usr/bin/bwrap", spec)

    def test_missing_ro_bind_rejected(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        spec = SandboxSpec(
            worker_cmd=(sys.executable, "-c", "pass"),
            ro_binds=(tmp_path / "gone",),
            rw_out_dir=out_dir,
            rlimits=Rlimits(cpu_seconds=60, address_space_bytes=GIB, nproc=64),
            wall_clock_s=30.0,
        )
        with pytest.raises(ValueError, match="ro_bind"):
            build_bwrap_argv("/usr/bin/bwrap", spec)


class TestInterpreterBinds:
    """The bind set must be correct BY CONSTRUCTION, not by guessing prefixes."""

    def test_binds_cover_the_interpreters_final_symlink_target(self) -> None:
        binds = interpreter_ro_binds()
        # sys.executable is typically .venv/bin/python -> ... -> the real binary;
        # the directory holding the FINAL target must be exposed.
        final_dir = Path(os.path.realpath(sys.executable)).parent
        assert any(final_dir == b or b in final_dir.parents for b in binds), (
            f"no bind exposes the real interpreter directory {final_dir}: {binds}"
        )

    def test_binds_cover_site_packages(self) -> None:
        binds = interpreter_ro_binds()
        purelib = Path(sysconfig.get_path("purelib"))
        assert any(purelib == b or b in purelib.parents for b in binds), (
            f"no bind exposes site-packages {purelib}: {binds}"
        )

    def test_binds_cover_every_hop_of_the_executable_chain(self) -> None:
        binds = interpreter_ro_binds()
        hop = Path(sys.executable)
        for _ in range(64):
            parent = hop.parent
            assert any(parent == b or b in parent.parents for b in binds), (
                f"symlink hop {hop} is not exposed by any bind: {binds}"
            )
            if not os.path.islink(hop):
                break
            target = os.readlink(hop)
            hop = Path(os.path.normpath(os.path.join(hop.parent, target)))

    def test_binds_are_deterministic_and_non_nested(self) -> None:
        binds = interpreter_ro_binds()
        assert binds == interpreter_ro_binds()
        assert len(set(binds)) == len(binds)
        for a in binds:
            for b in binds:
                assert a == b or a not in b.parents, f"{b} nests inside bound {a}"

    def test_prune_drops_nested_paths_and_sorts(self) -> None:
        pruned = prune_binds([Path("/a/b/c"), Path("/a"), Path("/z"), Path("/a/b"), Path("/a")])
        assert pruned == (Path("/a"), Path("/z"))

    def test_argv_keeps_the_stated_form_of_a_symlinked_bind(self, tmp_path: Path) -> None:
        """worker_cmd names STATED paths; binding only the resolved target
        leaves the stated path dangling inside the sandbox."""
        real = tmp_path / "real"
        real.mkdir()
        (real / "data.txt").write_text("x")
        link = tmp_path / "link"
        link.symlink_to(real)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        spec = SandboxSpec(
            worker_cmd=(sys.executable, "-c", "pass"),
            ro_binds=(link,),
            rw_out_dir=out_dir,
            rlimits=Rlimits(cpu_seconds=60, address_space_bytes=GIB, nproc=64),
            wall_clock_s=30.0,
        )
        argv = build_bwrap_argv("/usr/bin/bwrap", spec)
        ro_pairs = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--ro-bind"]
        assert (str(link), str(link)) in ro_pairs
        assert (str(real), str(real)) in ro_pairs


class TestBaseOsLayout:
    """The regression that broke CI: /lib64's shape is distro-specific.

    Arch has ``/lib64 -> usr/lib``; Debian/Ubuntu has ``/lib64 -> usr/lib64``,
    a real directory holding only ``ld-linux-x86-64.so.2``. CPython's PT_INTERP
    is the absolute ``/lib64/ld-linux-x86-64.so.2``, so hardcoding the Arch
    shape made the dynamic loader unreachable on Ubuntu runners and bwrap
    reported ``execvp <python>: No such file or directory``.
    """

    def test_top_level_entries_mirror_the_host(self) -> None:
        argv = base_os_argv()
        assert argv[:3] == ("--ro-bind", "/usr", "/usr")
        for entry in ("/lib", "/lib64", "/bin", "/sbin"):
            if os.path.islink(entry):
                assert ("--symlink", os.readlink(entry), entry) == tuple(
                    argv[argv.index(entry) - 2 : argv.index(entry) + 1]
                ), f"{entry} must reproduce the host symlink"
            elif os.path.isdir(entry):
                assert ("--ro-bind", entry, entry) == tuple(
                    argv[argv.index(entry) - 2 : argv.index(entry) + 1]
                ), f"{entry} is a real directory on this host and must be bound"

    def test_dynamic_loader_is_reachable_inside_the_sandbox(self, tmp_path: Path) -> None:
        """End-to-end: the loader path named by PT_INTERP must exist in-sandbox."""
        code = textwrap.dedent(
            """
            import json, os
            print(json.dumps({"loader": os.path.exists("/lib64/ld-linux-x86-64.so.2")}))
            """
        )
        outcome = BwrapBackend().execute(make_spec(tmp_path, code), b"")
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
        assert last_json(outcome)["loader"] is True

    def test_real_build123d_build_with_project_dir_in_a_tmp_path(self, tmp_path: Path) -> None:
        """The CI shape: the sandboxed project dir lives in a tmp path that
        shares NO ancestor with the venv, so the interpreter binds alone must
        carry the build."""
        project = tmp_path / "proj"
        project.mkdir()
        code = textwrap.dedent(
            """
            import json
            from build123d import Box
            part = Box(4, 3, 2)
            print(json.dumps({"volume": part.volume}))
            """
        )
        spec = make_spec(tmp_path, code, extra_ro=(project,))
        outcome = BwrapBackend().execute(spec, b"")
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
        assert last_json(outcome)["volume"] == pytest.approx(24.0, abs=1e-6)


class TestDiagnostics:
    def test_describe_argv_reports_binds_and_truncates(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        spec = SandboxSpec(
            worker_cmd=(sys.executable, "-c", "pass"),
            ro_binds=interpreter_ro_binds(),
            rw_out_dir=out_dir,
            rlimits=Rlimits(cpu_seconds=60, address_space_bytes=GIB, nproc=64),
            wall_clock_s=30.0,
        )
        described = describe_argv(build_bwrap_argv("/usr/bin/bwrap", spec))
        assert described.startswith("argv=")
        assert "binds=[" in described
        assert str(out_dir) in described
        assert "/usr" in described

    def test_probe_failure_reason_carries_the_mount_plan(self, tmp_path: Path) -> None:
        """A failing probe must be diagnosable from the CI log alone.

        The regression that broke CI reported only ``execvp <python>: No such
        file or directory`` — which blamed the interpreter for a missing
        dynamic loader. The mount plan is what actually identifies the fault.
        """
        from hephaestus.core.executor.sandbox import probe as probe_mod

        class FailingBackend(BwrapBackend):
            def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
                return ExecOutcome(
                    exit_code=1,
                    stdout=b"",
                    stderr=b"bwrap: execvp /somewhere/python: No such file or directory\n",
                    timed_out=False,
                )

        report = probe_mod.probe_bwrap(FailingBackend(), scratch_dir=tmp_path)
        assert not report.available
        reason = report.reason or ""
        assert "argv=" in reason and "binds=[" in reason
        # the plan names the base-OS mounts, where the real fault lived
        assert "/usr" in reason
