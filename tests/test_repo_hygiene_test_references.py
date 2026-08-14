"""A comment in `src/` that names a test must name one that exists.

`recimport/pyannote_backend.py` explained a non-obvious API choice with
"a faked pipeline cannot catch that — see test_pyannote_from_pretrained_signature",
and that test had been renamed before the branch merged. The pointer survived the
rename and pointed at nothing.

This kind of reference is worth *more* than an ordinary comment and rots more
quietly. It is written precisely where the code looks wrong on purpose, so the
next reader follows it to understand why — and a dangling one costs them the
search before they conclude the comment is stale and stop trusting the next one.
Nothing else notices: it is a comment, so no import breaks, no linter objects, and
the test suite is just as green with it wrong as with it right.

The check is deliberately narrow. It only reports a `test_…` name that matches
neither a test function nor a test *module* (plenty of comments legitimately cite
`tests/test_feature_wiring_honesty.py`), and it only reads `src/`, because a
reference from a test to a test is already next to the thing it names.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Long enough to be a real test name rather than a fragment like `test_x`.
_REFERENCE = re.compile(r"\btest_[a-z0-9_]{6,}")
_DEFINITION = re.compile(r"^\s*def (test_[a-z0-9_]+)", re.MULTILINE)


def _tracked(pattern: str) -> list[Path]:
    """Tracked files matching *pattern*, deduplicated and ordered.

    Note git pathspecs are not shell globs: `*` matches `/` too, so `src/*.py`
    already covers every nested module and pairing it with `src/**/*.py` yields
    each file twice — which is how the first run of this check reported its one
    offender twice over.
    """
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return sorted({ROOT / line for line in out.splitlines() if line})


def _known_test_names() -> set[str]:
    """Every test function name, plus every test module stem.

    Module stems count because citing the file that owns a behaviour is the more
    useful reference of the two — `tests/test_feature_wiring_honesty.py` says
    where to look without pinning one function name that may reasonably change.
    """
    names: set[str] = set()
    for path in _tracked("tests/*.py"):
        names.add(path.stem)
        names.update(_DEFINITION.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_test_named_in_src_actually_exists() -> None:
    """The defect this exists for: a renamed test leaves the pointer behind."""
    known = _known_test_names()
    assert known, "found no tests to compare against — the glob is wrong, not the repo"

    dangling: list[str] = []
    for path in _tracked("src/*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name in _REFERENCE.findall(line):
                if name not in known:
                    rel = path.relative_to(ROOT)
                    dangling.append(f"{rel}:{lineno}  names {name}, which does not exist")

    assert not dangling, (
        "a comment in src/ points at a test that no longer exists — rename the "
        "reference or drop it:\n  " + "\n  ".join(dangling)
    )
