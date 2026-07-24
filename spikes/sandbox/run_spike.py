"""Drive the full Spike F suite and write structured results to out/.

Runs on the HOST (uv venv python 3.13). It:
  * starts a host TCP listener on 127.0.0.1 (target for the loopback-escape probe)
  * exports a sentinel env var (target for the host-env-leak probe)
  * runs the escape-probe suite under bwrap and asserts every probe passed
  * runs the wall-clock and memory-limit terminations
  * runs fail-closed capability detection, including a simulated bwrap-absent host
  * writes out/results.json and prints a one-line PASS/FAIL summary
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sandbox_runner as sr  # noqa: E402

PROJECT = os.path.join(HERE, "fixtures", "project")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

SENTINEL = "HEPH_SANDBOX_SENTINEL"


def start_host_listener() -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]

    def _serve():
        while True:
            try:
                c, _ = srv.accept()
                c.close()
            except OSError:
                break

    threading.Thread(target=_serve, daemon=True).start()
    return port


def main() -> int:
    os.environ[SENTINEL] = "leaked-secret-value-should-never-reach-child"
    port = start_host_listener()
    results: dict = {"host": {}, "escape_probes": {}, "limits": {}, "capability": {}}
    results["host"] = {
        "sentinel_env": SENTINEL,
        "loopback_port": port,
        "host_pid": os.getpid(),
        "runner_python": sys.version.split()[0],
    }

    cfg = {
        "host_pid": os.getpid(),
        "sentinel_name": SENTINEL,
        "localhost_port": port,
        "project_dir": "/project",
        "expect_file": ["data.txt", "hello from project fixture\n"],
    }

    # 1+2. Escape-probe suite
    res = sr.run_sandboxed(PROJECT, ["probe", json.dumps(cfg)],
                          wall_timeout=30.0, mem_bytes=512 * 1024 * 1024)
    results["escape_probes"] = {
        "argv": res.argv,
        "returncode": res.returncode,
        "all_ok": bool(res.parsed and res.parsed.get("ok")),
        "probes": res.parsed.get("probes") if res.parsed else None,
        "stderr_tail": res.stderr[-500:],
    }
    with open(os.path.join(OUT, "bwrap_argv.txt"), "w") as f:
        f.write(" ".join(res.argv) + "\n")

    # 3a. wall-clock timeout on an infinite loop
    spin = sr.run_sandboxed(PROJECT, ["spin"], wall_timeout=3.0,
                           mem_bytes=256 * 1024 * 1024)
    results["limits"]["wall_timeout"] = {
        "timed_out": spin.timed_out,
        "wall_seconds": round(spin.wall_seconds, 3),
        "returncode": spin.returncode,
        "ok": spin.timed_out and spin.wall_seconds < 6.0,
    }

    # 3b. memory over-allocation killed by RLIMIT_AS
    over = 2 * 1024 * 1024 * 1024  # try to allocate 2 GiB with a 256 MiB cap
    alloc = sr.run_sandboxed(PROJECT, ["alloc", str(over)], wall_timeout=30.0,
                            mem_bytes=256 * 1024 * 1024)
    alloc_killed = bool(alloc.parsed and alloc.parsed.get("killed")) or alloc.returncode not in (0,)
    results["limits"]["memory_cap"] = {
        "requested_bytes": over,
        "cap_bytes": 256 * 1024 * 1024,
        "returncode": alloc.returncode,
        "parsed": alloc.parsed,
        "ok": alloc_killed,
    }

    # 4a. capability detection on a healthy host
    cap = sr.detect_capability(PROJECT)
    results["capability"]["healthy_host"] = cap

    # 4b. simulate bwrap absence -> must fail closed
    saved_path = os.environ.get("PATH", "")
    saved_which = sr.shutil.which
    try:
        os.environ["PATH"] = "/nonexistent-dir-only"
        # shutil.which honors PATH; belt-and-suspenders monkeypatch too
        cap_absent = sr.detect_capability(PROJECT)
    finally:
        os.environ["PATH"] = saved_path
        sr.shutil.which = saved_which
    results["capability"]["bwrap_absent_simulated"] = cap_absent
    results["capability"]["fail_closed_ok"] = (cap_absent.get("usable") is False)

    # aggregate
    ok = (
        results["escape_probes"]["all_ok"]
        and results["limits"]["wall_timeout"]["ok"]
        and results["limits"]["memory_cap"]["ok"]
        and results["capability"]["healthy_host"].get("usable") is True
        and results["capability"]["fail_closed_ok"]
    )
    results["overall_ok"] = ok

    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps({
        "overall_ok": ok,
        "escape_all_ok": results["escape_probes"]["all_ok"],
        "wall_timeout_ok": results["limits"]["wall_timeout"]["ok"],
        "memory_cap_ok": results["limits"]["memory_cap"]["ok"],
        "cap_healthy_usable": results["capability"]["healthy_host"].get("usable"),
        "cap_fail_closed_ok": results["capability"]["fail_closed_ok"],
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
