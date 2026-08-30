#!/usr/bin/env python3
"""Run the test suite with named modules made unimportable.

The FreeBSD CI leg installs the project with ``--no-deps``: PyPI publishes neither a
wheel nor an sdist of ``ctranslate2`` for FreeBSD, so ``faster-whisper`` and everything
under it simply cannot be there. Every test that reaches the decoder therefore fails on
that leg and nowhere else, which is the worst shape a red job can have -- it is real,
it is invisible from any developer machine, and it takes ~14 minutes of VM time to see.

This reproduces that environment locally in the time one pytest run takes::

    uv run python scripts/simulate-missing-deps.py            # the FreeBSD set
    uv run python scripts/simulate-missing-deps.py --modules numpy -- -x

Anything after ``--`` is passed to pytest.

The block is a ``sys.meta_path`` finder installed from a generated ``sitecustomize``,
so it is in place before pytest imports the first test module -- a fixture cannot do
this, because collection has already happened by the time fixtures run. It raises
``ModuleNotFoundError`` rather than ``ImportError``: ``pytest.importorskip`` and every
``try: import x except ImportError`` in this project catch the parent class, so a
blocker raising the wrong type would make guarded code look guarded when it is not.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: What FreeBSD cannot install, measured from the job's own log rather than guessed.
#: `ctranslate2` is the root -- no FreeBSD wheel and no sdist on PyPI -- and
#: `faster_whisper` imports it. `moonshine_onnx` and `huggingface_hub` are absent for
#: the same reason the job installs `--no-deps` at all.
FREEBSD_MISSING = ("ctranslate2", "faster_whisper", "moonshine_onnx", "huggingface_hub")

_SITECUSTOMIZE = '''\
import sys

BLOCKED = {blocked!r}


class _Blocker:
    """Refuse the blocked names the way a machine without them would."""

    def find_module(self, fullname, path=None):  # legacy API, harmless
        return None

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".")[0]
        if root in BLOCKED:
            raise ModuleNotFoundError(f"No module named {{fullname!r}}", name=fullname)
        return None


sys.meta_path.insert(0, _Blocker())
for name in list(sys.modules):
    if name.split(".")[0] in BLOCKED:
        del sys.modules[name]
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modules",
        nargs="+",
        default=list(FREEBSD_MISSING),
        help="module names to make unimportable (default: the FreeBSD set)",
    )
    args, pytest_args = parser.parse_known_args()
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "sitecustomize.py").write_text(
            _SITECUSTOMIZE.format(blocked=set(args.modules)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([tmp, env.get("PYTHONPATH", "")]).rstrip(
            os.pathsep
        )
        print(f"blocking: {', '.join(sorted(args.modules))}", file=sys.stderr)
        return subprocess.call(
            [sys.executable, "-m", "pytest", *(pytest_args or ["tests/", "-q"])],
            env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
