"""Synthetic daemon CLI for process/race tests ONLY. No Docker or CAD execution."""

import hashlib
import json
import sys
import time
from pathlib import Path

# The launcher inserts source/test paths and the one private fixture directory.
from _execution_identity import runtime_inventory
from hephaestus.core.executor.sandbox.oci_protocol import PROBE_WORKER, manifest_bytes
from hephaestus.core.executor.sandbox.oci_storage_policy import DEFAULT_STORAGE
from hephaestus.core.executor.sandbox.oci_transfer import export
from test_sandbox_oci import (
    AUDITED_ENTRYPOINT,
    AUDITED_IMAGE_ENV,
    IMAGE,
    _valid_probe_response,
    synthetic_effective,
)

root = Path(sys.argv[1])
args = sys.argv[2:]


def emit(value):
    print(json.dumps(value), flush=True)


def save(path, value):
    temp = path.with_suffix(".next")
    temp.write_text(json.dumps(value))
    temp.replace(path)


def lookup(identity):
    path = root / (identity + ".json")
    if not path.exists():
        for candidate in root.glob("*.json"):
            value = json.loads(candidate.read_text())
            if value.get("name") == identity:
                path = candidate
                break
    if not path.exists():
        print("no such container", file=sys.stderr)
        sys.exit(1)
    return path, json.loads(path.read_text())


def state(value):
    return {"Running": value["running"], "ExitCode": value["exit"], "OOMKilled": False}


if "context" in args:
    emit({"Endpoints": {"docker": {"Host": "unix:///synthetic.sock"}}})
elif "info" in args:
    emit({"OSType": "linux", "Architecture": "amd64", "OperatingSystem": "Docker Desktop"})
elif "image" in args:
    emit(
        {
            "Id": "sha256:" + "e" * 64,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": [IMAGE],
            "Config": {
                "Cmd": [],
                "Volumes": None,
                "Entrypoint": list(AUDITED_ENTRYPOINT),
                "Env": list(AUDITED_IMAGE_ENV),
            },
        }
    )
elif "create" in args:
    name = args[args.index("--name") + 1]
    cid = hashlib.sha256(name.encode()).hexdigest()
    path = root / (cid + ".json")
    save(path, {"id": cid, "name": name, "args": args, "running": False, "exit": 0})
    if (root / "delay-create").exists():
        (root / "create-entered").touch()
        deadline = time.monotonic() + 10
        while not (root / "release-create").exists():
            if time.monotonic() > deadline:
                sys.exit(2)
            time.sleep(0.01)
    print(cid, flush=True)
elif "inspect" in args:
    path, value = lookup(args[-1])
    if "{{json .}}" in args:
        emit(synthetic_effective(value["args"]))
    else:
        emit(state(value))
elif "kill" in args:
    path, value = lookup(args[-1])
    value.update(running=False, exit=137)
    save(path, value)
    print(value["id"])
elif "rm" in args:
    path, value = lookup(args[-1])
    if (root / "fail-remove").exists():
        print("daemon error", file=sys.stderr)
        sys.exit(2)
    path.unlink()
    print(value["id"])
elif "start" in args:
    path, value = lookup(args[-1])
    create = value["args"]
    value["running"] = True
    save(path, value)
    if create[-1] == "manifest":
        sys.stdout.buffer.write(manifest_bytes(runtime_inventory()))
    else:
        module, nonce = create[-6], create[-1]
        payload = json.load(sys.stdin)
        if module == PROBE_WORKER:
            response = _valid_probe_response(payload["nonce"])
            cpu, memory, nproc = map(int, create[-5:-2])
            response["cgroup"].update(memory_max=memory, pids_max=nproc)
            for key, limit in (
                ("RLIMIT_AS", memory),
                ("RLIMIT_DATA", memory),
                ("RLIMIT_CPU", cpu),
                ("RLIMIT_NPROC", nproc),
            ):
                response["rlimits"][key] = [limit, limit]
        else:
            if (root / "hold-worker").exists():
                (root / "worker-entered").touch()
                deadline = time.monotonic() + 15
                while path.exists() and json.loads(path.read_text())["running"]:
                    if time.monotonic() > deadline:
                        sys.exit(3)
                    time.sleep(0.01)
                sys.exit(137)
            response = {"status": "failed", "artifacts": {}}
        export(sys.stdout.buffer, response, nonce, module, root, DEFAULT_STORAGE)
    value.update(running=False, exit=0)
    save(path, value)
else:
    raise AssertionError(args)
