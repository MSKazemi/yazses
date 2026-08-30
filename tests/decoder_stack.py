"""One place that knows which tests need a decoder FreeBSD cannot install.

`faster-whisper` pulls in `ctranslate2`, which publishes no FreeBSD wheel and does not
build from source there without a toolchain the CI image does not carry; `moonshine-onnx`
and `huggingface_hub` arrive through the same install and are absent for the same reason.
The advisory `freebsd` job therefore runs a real machine with a real, permanent hole in
it, and every test that reaches the decoder fails there — 50 of them, once the job was
fixed far enough to run at all (#306).

Fifty failures are worse than useless: they are indistinguishable from fifty defects, so
the one leg that covers `platform/bsd/` reads as broken and stops being read. The right
answer is to skip precisely the tests that cannot run and let the other 14,600 report.

Why a shared module rather than the `pytest.importorskip(...)` line that was copied,
with its four-line comment, into seven files:

- **Most of these files are not decoder files.** `test_stt_download.py` has 24 tests and
  5 need the decoder; `test_shipped_backends.py` has 36 and needs it for 2. A module-scope
  `importorskip` is the only tool those seven files needed and it is the wrong tool here —
  it would drop 19 and 34 passing tests on FreeBSD to silence 5 and 2, which is trading
  the coverage this job exists to provide for a green tick.
- **The reason is one fact, so it should have one home.** Seven copies of a rationale is
  seven copies that can disagree, and the copies already differed in wording.

Use `needs_faster_whisper` (and friends) as a decorator on the individual test. Where a
whole module cannot even be *imported* without the package — a module-scope
`from yazses.stt.faster_whisper import …` — a marker is too late, because collection has
already raised; those files keep `pytest.importorskip` at module scope, which is what it
is for.

⚠ These markers are a statement that the package is genuinely unavailable on some
supported platform, not a way to quieten a test that fails for another reason. On every
machine where the package *is* installed — Linux, macOS, Windows, all of CI's blocking
legs — the marker is inert and the test runs exactly as before, which is what keeps a
skip from becoming a hiding place.
"""

from __future__ import annotations

import importlib.util

import pytest

__all__ = [
    "installed",
    "needs_ctranslate2",
    "needs_faster_whisper",
    "needs_huggingface_hub",
    "needs_moonshine",
]

_WHY = (
    "{module} has no FreeBSD build -- ctranslate2 publishes no wheel and the CI image "
    "carries no toolchain to build one, so the decoder stack is absent there (#306)"
)


def installed(module: str) -> bool:
    """Is *module* importable here?

    `find_spec` rather than a real import: importing `faster_whisper` costs seconds and
    loads a native library, and this runs at collection time for every marked test.

    The `except` is not defensive padding. A namespace-package parent raises `ValueError`,
    and on a machine where the package is genuinely missing `find_spec` raises
    `ModuleNotFoundError` rather than returning `None` whenever a *parent* is missing too
    — both of which mean "not available here", which is the only question being asked.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def needs(module: str) -> pytest.MarkDecorator:
    """Skip the decorated test where *module* is not installed."""
    return pytest.mark.skipif(not installed(module), reason=_WHY.format(module=module))


needs_faster_whisper = needs("faster_whisper")
needs_ctranslate2 = needs("ctranslate2")
needs_moonshine = needs("moonshine_onnx")
needs_huggingface_hub = needs("huggingface_hub")
