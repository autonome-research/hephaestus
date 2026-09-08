# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The permissive delegation gate — **test support only** (J-agent-wiring-6).

``DelegationService`` used to default its pre-admission gate to a private
allow-everything implementation, with a comment saying tests inject their own.
No production call site injected one either, so the gate actually in force in
every shipped runtime was the one that admits a delegation to a part that does
not exist — the defect the ledger item names.

The fix removes the default, which makes a gate-less service a type error, and
moves the permissive implementation *here*: a package the product may never
import (see :mod:`hephaestus.testing`'s own docstring, and the structural test
that enforces it). A suite whose subject is the state machine rather than the
policy asks for :class:`AllowAllGate` by name, so "this test does not exercise
the gate" is written down at the call site instead of being the silent default
for the whole repository.

``hephaestus.agent_bridge.wiring.ProjectDelegationGate`` is the real one.
"""

from __future__ import annotations

from hephaestus.agent_bridge.delegation import Delivery, RejectionReason

__all__ = ["AllowAllGate"]


class AllowAllGate:
    """A :class:`~hephaestus.agent_bridge.delegation.DelegationGate` that never rejects.

    Use it only where the gate is genuinely not the subject: the durable
    state-machine suites (crash/recovery, admission accounting, session edges).
    Anything asserting *policy* wants the real gate or a stub of its own.
    """

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason | None:
        return None
