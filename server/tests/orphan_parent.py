#!/usr/bin/env python3
"""Helper: start a supervised fake sidecar, print its pid, then block forever.

Used by the orphan-free test: the parent test SIGKILLs *this* process and then
asserts the sidecar child is gone (PR_SET_PDEATHSIG die-with-parent).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hephaestus.agent_bridge.supervisor import Supervisor, SupervisorConfig

FAKE = Path(__file__).with_name("fake_sidecar.py")


def main() -> None:
    sup = Supervisor(SupervisorConfig(argv=[sys.executable, str(FAKE)]))
    sup.start()
    # Hand the child pid to the parent test on stdout.
    print(sup.child_pid, flush=True)
    while True:
        time.sleep(0.5)


if __name__ == "__main__":
    os.setpgrp()
    main()
