# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""A real ``heph serve --web`` with **no** ``providers.json`` (§7A.12 case 6).

§7A.12's sixth case is "serve with no ``providers.json``; the composer renders
disabled with ``data-disabled-reason="agent_unavailable"`` and the named
``cause``". That is a property of a **differently configured serve**, not of a
different page, so it needs its own process — the main G4 harness deliberately
writes a provider config, because every other clause needs a working sidecar.

It is also why this is a second fixture rather than a flag on the first.
§7A.9's TIGHTENING is emphatic that G4.8's fixture keeps starting its session
from the CLI and that "the composer's coverage is a **separate** e2e case…
the two never share a fixture"; a harness that could turn the runtime off under
the running gate would put both clauses in one process and one of them would
end up asserting the other's state.

Prints one line to stdout — ``READY <base_url> <token> <project_root>`` — and
then holds the world up until it is signalled, the same shape
``serve_fixture.py`` uses. Started and stopped by ``composer.spec.ts``.
"""

from __future__ import annotations

import signal
import sys
import tempfile
import time
from pathlib import Path

# Reuse the sibling harness's own process helpers rather than a second copy of
# "start a serve and read its entry URL" — mission rule 6 applies to test
# harnesses too, and a divergent copy would be a second definition of what
# "the shipped serve" means.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from serve_fixture import (  # the sys.path insert above is what makes this resolve
    await_ready,
    log,
    read_entry,
    start_server,
    stop,
)


def main() -> int:
    from hephaestus.testing.workspace_fixture import materialize_workspace_fixture

    scratch = Path(tempfile.mkdtemp(prefix="heph-noagent-e2e-"))
    project_root = scratch / "workspace"
    log(f"materializing a runtime-less fixture at {project_root}")
    materialize_workspace_fixture(project_root)
    # DELIBERATELY NOT BUILT and DELIBERATELY NOT CONFIGURED. §7A.8's subject is
    # a serve that still answers every read, mutation, artifact and git route
    # and simply has no sessions; building would only slow the case down, and
    # writing `.heph/providers.json` would remove the state under test.

    server = start_server(project_root)
    try:
        base_url, token = read_entry(server)
        await_ready(base_url, token)
        print(f"READY {base_url} {token} {project_root}", flush=True)
        stopping = {"now": False}

        def _stop(_signum: int, _frame: object) -> None:
            stopping["now"] = True

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, _stop)
        while not stopping["now"]:
            if server.poll() is not None:
                raise SystemExit(f"heph serve exited unexpectedly with {server.returncode}")
            time.sleep(0.25)
    finally:
        stop(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
