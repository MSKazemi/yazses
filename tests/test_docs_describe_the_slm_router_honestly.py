"""A page that mentions the Tier-2 SLM router must describe it as it now is (#164).

This file used to assert the exact opposite, and the history is the point.

`commands/slm_router.py` sat in `test_orphan_modules.py::KNOWN_ORPHANS` for two
releases: *"grammar.py takes an `slm_router` parameter and nothing ever constructs
one — a plumbed seam never filled."* Seven doc pages nonetheless presented Tier 2 as
an available capability — the front door, the FAQ written for answer engines, the
competitive table in `comparison.md`, a benchmarks page that put it next to a
measured command-recognition number it did not contribute to — so this guard demanded
a *"designed, not wired"* caveat next to every mention.

It also wrote down what should happen when the premise expired:

> Tied to `KNOWN_ORPHANS`, so this stops demanding a caveat the day the router is
> actually wired — a guard that outlives its premise starts forcing a lie.

The daemon now builds a router (`core/daemon.py::_build_slm_router`) and passes it to
both `classify()` call sites, so the premise has expired. Deleting the file would
have discarded the property along with the caveat, and the property is the valuable
half: *the docs must agree with the code about whether this feature exists*. So it is
inverted rather than removed, and it now guards **both** ways it can go wrong:

* no page may still say the router is unwired (`test_no_page_still_says_it_is_unwired`)
  — under-claiming is the cheaper error but the more durable one, because a caveat is
  written once and nobody re-reads it when the code catches up;
* and the pages must still say it needs a local model
  (`test_the_pages_say_it_needs_a_model`) — Tier 2 runs a language model on the
  dictation path, and a reader who thinks natural-language commands work out of the
  box has been misled in the more expensive direction.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
#: Release notes describe what a past version claimed; rewriting them would be a
#: different kind of untruth.
SKIP_TREES = {"releases"}

#: "Tier 2" with no other qualifier is enough: in this project it names one thing,
#: and the caveats that went stale were written as `!!! warning "Tier 2 is designed,
#: not wired"` — an admonition title that never spells "SLM router" at all.
_MENTION = re.compile(r"slm[ _-]?router|tier[ -]?2", re.IGNORECASE)
#: The project's own phrasings for "this does not run", collected while the guard
#: pointed the other way. They are now the thing being searched *for*.
_DENIAL = re.compile(
    r"not wired|not yet wired|designed, not|no caller|nothing constructs", re.IGNORECASE
)
#: …and the phrasings that correctly say "on, but only if you turn it on".
_CONDITION = re.compile(
    r"opt-in|slm_model_path|off unless|needs a (?:local )?model", re.IGNORECASE
)


def _pages() -> list[Path]:
    return [
        p
        for p in sorted(list(DOCS.rglob("*.md")) + list(DOCS.rglob("*.mmd")))
        if not (SKIP_TREES & set(p.parts))
    ]


def test_the_router_is_wired_now() -> None:
    """The premise. If this fails, this whole file should be inverted back.

    Two independent facts, because either alone can be true while Tier 2 is dead:
    the module left the orphan ledger, and the daemon actually hands a router to
    `classify()`. The ledger is a human-maintained list; the call sites are the code.
    """
    from test_orphan_modules import KNOWN_ORPHANS

    assert "commands.slm_router" not in KNOWN_ORPHANS, (
        "commands.slm_router is back in the orphan ledger — if Tier 2 was unwired "
        "again, restore the 'designed, not wired' caveats to the docs and invert "
        "this file back to demanding them"
    )
    daemon = (ROOT / "src" / "yazses" / "core" / "daemon.py").read_text(encoding="utf-8")
    assert "slm_router=self._slm_router" in daemon, (
        "the daemon no longer passes a router to classify() — Tier 2 is unreachable "
        "again, and every page this file blesses now overclaims"
    )


def test_the_scan_finds_the_mentions() -> None:
    """A guard over an empty set passes on everything."""
    pages = _pages()
    assert len(pages) > 50, f"only {len(pages)} doc pages found"
    mentioning = [p for p in pages if _MENTION.search(p.read_text(encoding="utf-8"))]
    assert len(mentioning) >= 3, f"only {len(mentioning)} pages mention the router"


#: A new list item, a blank line, or an admonition title starts a new subject.
_NEW_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s")
_ADMONITION = re.compile(r"^\s*(?:!!!|\?\?\?)")


def _blocks(text: str) -> list[list[tuple[int, str]]]:
    """Split a page into subject-sized blocks of ``(line number, line)``.

    The unit has to be the paragraph, not a line window, and `architecture.md` is
    why. Its pipeline step 6 says an editor-context prefix "is **not wired**" — a
    true statement about the LSP bridge — ten lines above step 8's description of the
    router. A +/-15 line rule read that denial as a stale router caveat and demanded
    the removal of a sentence that is correct.

    An admonition is folded into one block with its indented body, because that is
    where both of the real stale caveats lived: the denial is in the *title* and the
    subject is named in the body.
    """
    out: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    in_admonition = False
    for i, line in enumerate(text.splitlines(), 1):
        if _ADMONITION.match(line):
            if cur:
                out.append(cur)
            cur, in_admonition = [(i, line)], True
            continue
        if in_admonition:
            if not line.strip() or line.startswith((" ", "\t")):
                cur.append((i, line))
                continue
            out.append(cur)
            cur, in_admonition = [], False
        if not line.strip() or _NEW_ITEM.match(line):
            if cur:
                out.append(cur)
            cur = []
        if line.strip():
            cur.append((i, line))
    if cur:
        out.append(cur)
    return out


def test_no_page_still_says_it_is_unwired() -> None:
    bad: list[str] = []
    for path in _pages():
        for block in _blocks(path.read_text(encoding="utf-8")):
            body = "\n".join(line for _, line in block)
            if _MENTION.search(body) and _DENIAL.search(body):
                first, text = block[0]
                bad.append(f"{path.relative_to(ROOT)}:{first}: {text.strip()[:70]}")
    bad = sorted(bad)
    assert not bad, (
        "these pages still describe the Tier-2 SLM router as unwired; the daemon "
        "builds one whenever `[commands] slm_model_path` names a model:\n  "
        + "\n  ".join(bad)
        + "\n\nSay it is opt-in and needs a local GGUF, rather than that it does "
        "not exist."
    )


def test_the_pages_say_it_needs_a_model() -> None:
    """The opposite failure: dropping the caveat and promising it works by default."""
    pages = [p for p in _pages() if _MENTION.search(p.read_text(encoding="utf-8"))]
    bare = [
        p.relative_to(ROOT)
        for p in pages
        if not _CONDITION.search(p.read_text(encoding="utf-8"))
    ]
    assert not bare, (
        "these pages mention the Tier-2 SLM router without saying anywhere that it "
        "needs a local model configured:\n  " + "\n  ".join(map(str, sorted(bare)))
        + "\n\nTier 2 is off for everyone who sets no `[commands] slm_model_path`; "
        "a page that omits that reads as though it is on by default."
    )


@pytest.mark.parametrize(
    "text,stale",
    [
        # the two real shapes this file was written to catch
        ('!!! warning "Tier 2 is designed, not wired"\n\n    Nothing constructs '
         "the router these two keys configure.", True),
        ("A Tier-2 SLM router was designed\nto catch those and is **not wired**.", True),
        ("the Tier 2 SLM router has **no caller**", True),
        # the fixes
        ("an optional SLM router, off unless slm_model_path is set", False),
        ("a regex grammar plus an opt-in SLM router", False),
        ("a regex grammar maps phrases to keys", False),
        # a true denial about a different subject, in its own block: must not fire
        ("8. A Tier 2 SLM router runs when you configure one.\n"
         "9. An editor-context prefix was designed and is **not wired**.", False),
    ],
)
def test_the_check_catches_a_stale_denial_and_allows_the_fix(
    text: str, stale: bool
) -> None:
    """Only worth having if it fires — and only keepable if it does not cry wolf.

    The last case is the false positive that a line-proximity rule produced against
    the real `architecture.md`, kept here so the block rule cannot quietly regress
    into one.
    """
    hits = [
        b for b in _blocks(text)
        if _MENTION.search("\n".join(line for _, line in b))
        and _DENIAL.search("\n".join(line for _, line in b))
    ]
    assert bool(hits) is stale
