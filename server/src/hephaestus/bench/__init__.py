"""``hephaestus.bench`` — the Tier 3 golden-prompt benchmark (verification.md §Tier 3).

Two modules carry the whole gate:

* :mod:`hephaestus.bench.harness` runs one corpus task end to end — a fresh
  project seeded from the task spec, a real :class:`~hephaestus.agent_bridge.app.
  BridgeRuntime` orchestrator session against a configurable provider, tool-call
  budget accounting, then grading (build every part -> install the task's required
  CHECKS -> run them project-scoped -> validate the required exports/renders);
* :mod:`hephaestus.bench.scoring` turns run records into the gate statistic: the
  one-sided lower 90% Wilson bound of the aggregate pass rate (never the raw
  fraction) plus the per-task table written to ``bench/results/<model>/<date>.json``.

``hephaestus.bench.cli_bench`` registers the ``heph bench run`` / ``heph bench
score`` verbs; ``hephaestus.bench.cli`` is the standalone dispatcher
(``python -m hephaestus.bench.cli ...``).

Submodules are imported explicitly (nothing is re-exported here) so that
``hephaestus.bench.scoring`` stays importable without the agent-bridge stack.
"""

from __future__ import annotations
