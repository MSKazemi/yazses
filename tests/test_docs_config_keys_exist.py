"""Every config key the documentation names must exist in `Config`.

Two adjacent guards already stand here and neither covers this:
`test_docs_flags_exist.py` checks `--flags`, and
`test_docs_do_not_promise_unwired_features.py` checks that docs do not tell you to
enable a capability `features enable` refuses. A key that simply **does not exist** was
unguarded — and this project has shipped one: a documented setting that nothing read
and nothing defined, found by hand.

It is the cheapest half of the "documented as designed, not as built" family, and the
only half a machine can settle. A reader who copies a key that does not exist gets no
error at all: `configcheck` drops unknown keys deliberately, so the setting silently
does nothing and the file still loads.

## Both ways docs name a key

* backticked prose — ``[audio] device`` — the convention used across these pages;
* a ```` ```toml ```` block, which is worse to get wrong because it is copied verbatim.

Both are scanned. `docs/releases/` and `docs/research/` are excluded for the same
reasons the command guard excludes them: a release note describes what a past version
had, and a research page may name something that does not exist on purpose.

**The result today is zero across 218 mentions**, which is why it is worth pinning now
rather than after it drifts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.config import Config

DOCS = Path(__file__).resolve().parents[1] / "docs"
SKIP_TREES = {"releases", "research"}

#: ``[section] key`` inside backticks. Anchored on the backtick because that is what
#: marks "this is a setting" rather than prose; matching a bare `[word] word` would
#: hit Markdown link syntax and ordinary sentences.
_INLINE = re.compile(r"`\[([a-z][a-z0-9_.]*)\]\s+([a-z][a-z0-9_]*)`")
_TOML_BLOCK = re.compile(r"```toml\n(.*?)```", re.S)
_SECTION_LINE = re.compile(r"\[([a-z][a-z0-9_.]*)\]")
_ASSIGN_LINE = re.compile(r"([a-z][a-z0-9_]*)\s*=")


def _pages() -> list[Path]:
    """The documentation pages this guard reads."""
    return [
        p for p in sorted(DOCS.rglob("*.md")) if not (SKIP_TREES & set(p.parts))
    ]


def _resolves(section: str, key: str) -> bool:
    """True when `[section] key` exists on a real `Config`.

    Traverses a live object rather than guessing a class name: dotted sections such as
    `filters.disfluency` are real, and a guessed mapping would silently resolve nothing
    and pass everything.
    """
    node: object = Config()
    for part in section.split("."):
        node = getattr(node, part, None)
        if node is None:
            return False
    return hasattr(node, key)


def _documented_keys() -> list[tuple[Path, str, str]]:
    """`(path, section, key)` for every config key the docs name, both forms."""
    found: list[tuple[Path, str, str]] = []
    for path in sorted(DOCS.rglob("*.md")):
        if SKIP_TREES & set(path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for section, key in _INLINE.findall(text):
            found.append((path, section, key))
        for body in _TOML_BLOCK.findall(text):
            section: str | None = None
            for raw in body.splitlines():
                line = raw.split("#", 1)[0].strip()
                if m := _SECTION_LINE.fullmatch(line):
                    section = m.group(1)
                    continue
                if section and (m := _ASSIGN_LINE.match(line)):
                    found.append((path, section, m.group(1)))
    return found


@pytest.fixture(scope="module")
def documented() -> list[tuple[Path, str, str]]:
    return _documented_keys()


def test_the_scan_finds_the_documented_settings(documented) -> None:
    """A guard over an empty set passes on everything — this repo's most repeated
    self-inflicted wound. Both extraction paths must be producing results."""
    assert len(documented) > 150, f"only {len(documented)} config mentions found"

    # Both paths must contribute. Counted rather than probed with a chosen pair: my
    # first version asserted `("audio", "device")` was present, which it is not in
    # that exact backticked form — the sentinel was wrong, not the scan, and a
    # sentinel that happens to be absent turns a working guard into a red one.
    inline = sum(len(_INLINE.findall(p.read_text(encoding="utf-8"))) for p in _pages())
    blocks = len(documented) - inline
    assert inline > 20, f"the inline `[section] key` form found {inline}"
    assert blocks > 20, f"the ```toml block form found {blocks}"


def test_every_config_key_named_in_the_docs_exists(documented) -> None:
    """The defect: a documented setting nothing defines.

    `configcheck` drops unknown keys on purpose, so a reader who copies one gets no
    error — the setting just does nothing, and the file still loads.
    """
    bad = sorted({
        f"{path.relative_to(DOCS.parent)}: [{section}] {key}"
        for path, section, key in documented
        if not _resolves(section, key)
    })
    assert not bad, (
        "these settings are documented but do not exist in Config:\n  "
        + "\n  ".join(bad)
        + "\n\nAdd the key, or fix the docs. An unknown key is dropped silently by "
        "configcheck, so a reader who copies it sees no error and no effect."
    )


def test_the_check_can_fail() -> None:
    """Only worth having if it fires. Uses the same resolver as the guard."""
    assert _resolves("audio", "device") is True
    assert _resolves("audio", "no_such_setting") is False
    assert _resolves("no_such_section", "device") is False


def test_dotted_sections_resolve() -> None:
    """`filters.disfluency` is real, and a naive title-cased guess would miss it —
    silently, which is the failure mode that makes a guard stop guarding."""
    assert _resolves("filters.disfluency", "enabled") is True
