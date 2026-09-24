"""The cask must declare its macOS floor in SYMBOL form, not string comparison.

Homebrew deprecated `depends_on macos: ">= :big_sur"` in 5.1.15 and now prints a
deprecation warning on **every** `brew` call that touches a tap still using it.
Two separate field reports on #182 pasted that warning back at us, which means it
is not a lint nit: it is the first thing a new macOS user sees, and it names this
project.

The symbol form is not a different requirement. Homebrew's own warning names
`depends_on macos: :big_sur` as the replacement, and the cookbook defines the
symbol as "the minimum compatible macOS release" -- so big_sur-or-newer, exactly
what the string said.

Guarded here because of *where* the fix has to live. @slegarraga opened
homebrew-yazses#1 against the published tap, and the publish job does
`cp packaging/homebrew/yazses.rb tap/Casks/yazses.rb` -- a whole-file overwrite.
A fix that lands only in the tap is reverted by the next release, silently, and
the warning returns. The source of truth is this file, so this is what is tested.

Derived, never hand-listed: it scans every `.rb` under `packaging/` rather than
naming the cask, so a second cask or formula is covered the day it is added.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"

# `depends_on macos:` followed by a QUOTED value -- i.e. the string comparison
# format (">= :big_sur", "<= :ventura", "== :sonoma"). The symbol form has no
# quotes, so this cannot match it.
_STRING_FORM = re.compile(r"""depends_on\s+macos:\s*["']""")
_ANY_MACOS = re.compile(r"""depends_on\s+macos:""")


def _ruby_files() -> list[Path]:
    return sorted(PACKAGING.rglob("*.rb"))


def test_the_scan_actually_reaches_a_macos_declaration() -> None:
    """A guard that iterates is green on an empty collection.

    If `packaging/` is ever restructured and the cask moves, every assertion
    below passes by finding nothing -- reporting compliance it never checked.
    """
    files = _ruby_files()
    assert files, f"no .rb files under {PACKAGING} -- the scan cannot prove anything"
    declaring = [p for p in files if _ANY_MACOS.search(p.read_text(encoding="utf-8"))]
    assert declaring, (
        "no file under packaging/ declares `depends_on macos:` -- either the cask "
        "moved or the declaration was dropped; this guard is inert either way"
    )


def test_no_packaging_ruby_uses_the_deprecated_string_comparison() -> None:
    offenders = []
    for path in _ruby_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _STRING_FORM.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "deprecated Homebrew string-comparison form for `depends_on macos:` "
        "(warns on every brew call since Homebrew 5.1.15). Use the symbol form, "
        "e.g. `depends_on macos: :big_sur`:\n  " + "\n  ".join(offenders)
    )
