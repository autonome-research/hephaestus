"""Execute every ```python fence in opstore/README.md against a tmpdir store root.

Convention (documented in the README): ``ROOT`` is a ``pathlib.Path`` to a
fresh empty directory. The runner substitutes it by injecting ``ROOT`` into
each fence's globals; every fence runs in its own namespace and tmpdir and
must complete without raising.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "opstore" / "README.md"

_FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _fences() -> list[str]:
    return _FENCE_RE.findall(README.read_text(encoding="utf-8"))


FENCES = _fences()


def test_readme_has_runnable_examples() -> None:
    assert 3 <= len(FENCES) <= 5, "README must carry 3-5 runnable python fences"
    assert all("ROOT" in fence for fence in FENCES)


@pytest.mark.parametrize("index", range(len(FENCES)), ids=lambda i: f"fence{i}")
def test_readme_example_executes(index: int, tmp_path: Path) -> None:
    root = tmp_path / f"example-{index}"
    root.mkdir()
    code = compile(FENCES[index], f"{README.name}:fence{index}", "exec")
    namespace: dict[str, object] = {"ROOT": root, "__name__": f"readme_fence_{index}"}
    exec(code, namespace)
