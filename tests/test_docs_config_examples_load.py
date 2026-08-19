"""Every `config.toml` example in the docs must survive the real loader.

A documented snippet is copy-pasted, not read. If it names a key that does not exist, or
gives a value of the wrong type, `configcheck` does exactly what it was built to do — drops
the key, repairs what it can, and carries on — so the user gets a config that loads cleanly
and a setting that never applies. Nothing errors, and the doc is what taught them to write
it.

The suite checked the config loader and it checked the docs build. Nothing put the two
together.

## What it found

62 `config.toml` examples across the documentation, zero problems. This ships as a guard
rather than a fix: the value is that the next example cannot be wrong silently.

## Two exclusions, both narrow and both asserted

**Blockquoted blocks.** `docs/windows-install.md` puts a TOML block inside a `>` callout.
The `> ` prefixes are Markdown, not TOML, and reach the parser as `Invalid statement (at
line 1, column 1)` unless stripped. That is a defect in the extractor, not the doc, and it
is the kind of thing that would otherwise get "fixed" by loosening the assertion.

**Deliberately wrong illustrations.** `docs/troubleshooting.md` shows the same key twice on
purpose:

    vad_threshold = "0.004"   # wrong — this is a string
    vad_threshold = 0.004     # right — bare number

That is the point of the passage. Blocks whose comment says "wrong" are skipped, and the
count of skipped blocks is pinned — an exemption that can grow silently is not an exemption,
it is a hole.

Files that are not `config.toml` (`macros.toml`, house-style rule files) are skipped by
their own header comment and by array-of-tables syntax, which `config.toml` never uses.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from yazses.config import load_config_checked

DOCS = Path(__file__).resolve().parent.parent / "docs"

_BLOCK = re.compile(r"```toml\n(.*?)```", re.S)
#: A header comment naming a file that is not config.toml.
_OTHER_FILE = re.compile(r"#\s*~?[\w/.\\-]*\b(macros|house-style|rules)\b[\w.]*\.toml", re.I)
#: A comment marking a value as deliberately incorrect.
_ILLUSTRATIVE = re.compile(r"#.*\bwrong\b", re.I)

#: Exactly one block in the docs teaches by showing a wrong value next to a right one.
#: Pinned so the exemption cannot quietly become a way to ignore a broken example.
EXPECTED_ILLUSTRATIVE = 1


def _strip_blockquote(body: str) -> str:
    """Remove Markdown `> ` callout prefixes, which are not TOML."""
    lines = body.splitlines()
    if lines and all(ln.startswith("> ") or ln.strip() in ("", ">") for ln in lines):
        return "\n".join(ln[2:] if ln.startswith("> ") else "" for ln in lines)
    return body


def _examples() -> list[tuple[str, str]]:
    """`(location, toml)` for every config.toml example in the docs."""
    found: list[tuple[str, str]] = []
    for md in sorted(DOCS.rglob("*.md")):
        if "releases/" in str(md):
            continue  # historical notes, not instructions
        text = md.read_text(encoding="utf-8")
        for match in _BLOCK.finditer(text):
            body = _strip_blockquote(match.group(1))
            if _OTHER_FILE.search(body) or "[[" in body:
                continue
            line = text[: match.start()].count("\n") + 1
            found.append((f"{md.relative_to(DOCS.parent)}:{line}", body))
    return found


def _config_examples() -> list[tuple[str, str]]:
    return [(loc, body) for loc, body in _examples() if not _ILLUSTRATIVE.search(body)]


def test_the_extractor_finds_examples() -> None:
    """Guard the guard: a changed fence style would make every test below vacuous."""
    assert len(_config_examples()) >= 40, (
        "far fewer TOML examples than expected — the extractor is broken, not the docs"
    )


@pytest.mark.parametrize("location,body", _config_examples(), ids=lambda v: v if isinstance(v, str) and ":" in v else "")
def test_a_documented_example_loads_without_problems(location: str, body: str) -> None:
    """A key that does not exist is dropped silently, and the doc taught it."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(body, encoding="utf-8")
    result = load_config_checked(path)
    assert not result.problems, (
        f"{location} — a copy-pasted example produces config problems:\n  "
        + "\n  ".join(str(p) for p in result.problems)
    )


def test_only_the_known_illustrative_block_is_skipped() -> None:
    """An exemption that can grow silently is a hole, not an exemption."""
    skipped = [loc for loc, body in _examples() if _ILLUSTRATIVE.search(body)]
    assert len(skipped) == EXPECTED_ILLUSTRATIVE, (
        f"blocks skipped as 'deliberately wrong' changed: {skipped}. If a new example "
        f"genuinely teaches by counter-example, raise EXPECTED_ILLUSTRATIVE and say why; "
        f"otherwise the word 'wrong' in a comment is now hiding a real broken example."
    )


def test_a_blockquoted_example_is_still_checked() -> None:
    """The exclusion that would have silently dropped coverage.

    Stripping `> ` is what lets the Windows install page be checked at all; without it
    that example fails to parse and the natural "fix" is to skip blockquotes entirely.
    """
    quoted = [loc for loc, _b in _config_examples() if "windows-install" in loc]
    assert quoted, "the blockquoted Windows example is no longer being checked"


def test_the_check_can_fail() -> None:
    """Proof the assertion is real: a plausible-looking wrong example must be caught."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[stt]\nmodel = "base.en"\nnot_a_real_key = 1\n', encoding="utf-8")
    assert load_config_checked(path).problems
