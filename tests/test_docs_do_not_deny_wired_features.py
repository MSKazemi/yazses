"""Docs must not tell you a capability is unwired after it has been wired.

`tests/test_docs_do_not_promise_unwired_features.py` guards one direction: a page
that hands you `yazses features enable <slug>` for something `features enable`
refuses. This guards the other, and the other one is the direction that costs
Mohsen something — a page that **denies** a capability the daemon now has.

It is not hypothetical. `docs/comparison.md` told every reader that the modality
role router "is written and unit-tested but **not yet wired into the daemon**" for
weeks after `core/daemon.py::_resolve_modality_roles` started calling it, the
`modality` slug left `_UNWIRED`, and `yazses doctor` grew a row that prints the
resolved map. Nothing failed, because a wiring pass moves a slug *out* of a set and
no test asked which prose still referred to it. Understating the product on its own
comparison page is the one class of error the honesty rule cannot catch by itself:
every individual sentence was written true, and stayed on the page after it stopped
being.

The rule is narrow on purpose: **a sentence that says something is not wired must
not name a wired slug.** Mentioning a wired capability is fine anywhere else; so is
saying an *unwired* one is unwired, which is what `_UNWIRED` is for. Both sets come
from `system/features.py`, so wiring a capability arms this the same day and
retires the other guard's requirement — neither list is maintained by hand.

If a legitimate sentence trips this, the sentence is ambiguous to a reader too:
"voice commands are not wired to the tray" reads, to someone scanning the page,
exactly like "the `commands` capability is not wired". Rewording is the fix.
"""
from __future__ import annotations

import re
from pathlib import Path

from yazses.config import Config
from yazses.system.features import _UNWIRED, grouped_features

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Release notes describe what a version did at the time and must not be rewritten.
SKIP_DIRS = {"releases"}

#: The phrasings that assert a capability has no runtime path. Deliberately about
#: *wiring*: "not implemented" and "not supported" are ordinary prose about other
#: software, while "not wired" is this project's own word for this exact state.
DENIAL = re.compile(
    r"\b(?:not|never|isn't|is\s+not|aren't|are\s+not|nothing)\b[^.;]{0,60}?"
    r"\bwired\b|\bunwired\b|\bwired\s*[:=]\s*False\b",
    re.I,
)


def _registry() -> list[tuple[str, str]]:
    """``(slug, display name)`` for every capability, from the registry itself."""
    return [
        (f.slug, f.name) for _cat, _blurb, feats in grouped_features(Config()) for f in feats
    ]


def wired_slugs() -> set[str]:
    """Capability slugs that have a runtime path today."""
    return {slug for slug, _name in _registry()} - set(_UNWIRED)


def _patterns(slug: str, name: str) -> list[re.Pattern[str]]:
    """How a page can name this capability *as a capability*.

    Half of these slugs are ordinary English words — `code`, `context`, `commands`,
    `staged`, `dictation` — so a bare word-boundary match reads "the editor-context
    prompt is not wired" as a claim about the `context` capability. Two forms are
    unambiguous: the slug written as a slug (backticked, as a `[section]`, or after
    `features enable`), and the registry's own **display name**, which is a
    capitalised multi-word phrase nobody writes by accident.
    """
    return [
        re.compile(rf"`\[?{re.escape(slug)}\]?`"),
        re.compile(rf"\[{re.escape(slug)}\]"),
        re.compile(rf"features\s+(?:enable|disable)\s+{re.escape(slug)}\b"),
        re.compile(rf"\b{re.escape(name)}\b", re.I),
    ]


def _names(unit: str, slugs) -> list[str]:
    return [s for s, n in _registry() if s in slugs and any(p.search(unit) for p in _patterns(s, n))]


def _pages() -> list[Path]:
    return [
        p
        for p in DOCS.rglob("*.md")
        if not (set(p.relative_to(DOCS).parts) & SKIP_DIRS)
    ]


def _units(text: str):
    """Yield ``(line_number, sentence)`` over a markdown page.

    Sentence-level rather than paragraph-level, because a paragraph about a wired
    feature may legitimately end by naming something else that is not wired.

    A **table row is its own unit**, and that is the whole reason this is not a
    two-line regex. A capability table has no sentence-ending punctuation, so a
    naive split swallows the entire table into one chunk — and then one row marked
    *(planned — not yet wired)* accuses every other row in the table. The first
    version of this test did exactly that and produced 19 findings, 16 of them
    that shape.
    """
    para: list[str] = []
    start = 1
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("|") or not line.strip():
            if para:
                yield from _split(start, "\n".join(para))
                para = []
            if line.lstrip().startswith("|"):
                yield lineno, line
            continue
        if not para:
            start = lineno
        para.append(line)
    if para:
        yield from _split(start, "\n".join(para))


def _split(start: int, para: str):
    line = start
    for chunk in re.split(r"(?<=[.;:!?])\s+", para):
        yield line, chunk
        line += chunk.count("\n")


def _offences() -> list[tuple[Path, int, str, str]]:
    wired = wired_slugs()
    unwired = set(_UNWIRED)
    hits: list[tuple[Path, int, str, str]] = []
    for page in _pages():
        for lineno, unit in _units(page.read_text(encoding="utf-8")):
            if not DENIAL.search(unit):
                continue
            # The denial has a legitimate subject: something that really is unwired.
            # A capability table row and a feature entry both look like this, and the
            # wired capability named alongside is incidental.
            if _names(unit, unwired):
                continue
            for slug in _names(unit, wired):
                hits.append((page, lineno, slug, " ".join(unit.split())[:160]))
    return hits


def test_the_scan_reads_pages_and_knows_which_slugs_are_wired() -> None:
    """A guard that iterates is green on an empty collection (see MEMORY)."""
    pages = _pages()
    assert len(pages) > 50, f"only {len(pages)} docs pages found — the scan lost its corpus"
    wired = wired_slugs()
    assert len(wired) > 50, f"only {len(wired)} wired slugs — the registry was not read"
    assert not (wired & set(_UNWIRED)), "a slug cannot be both wired and unwired"


def test_the_denial_pattern_actually_matches_a_denial() -> None:
    """The exact sentence that shipped on the comparison page for weeks."""
    stale = (
        "The modality role router that assigns commands to one channel and dictation "
        "to another is written and unit-tested but not yet wired into the daemon."
    )
    assert DENIAL.search(stale)
    assert "modality" in wired_slugs()
    assert re.search(r"\bmodality\b", stale, re.I)


def test_the_denial_pattern_does_not_fire_on_ordinary_prose() -> None:
    for benign in (
        "The tray icon turns yellow when dictation has no text target.",
        "An EMG sensor is wired to the command callbacks when a device port is set.",
        "Meeting Mode is off by default.",
    ):
        assert not DENIAL.search(benign), benign


def test_a_capability_named_only_in_prose_is_still_matched() -> None:
    """The display name is what catches a denial that never spells the slug.

    Removing the display-name pattern and restoring the stale comparison sentence
    still failed, because that paragraph happens to also write `[modality]`. So the
    pattern's contribution is pinned here instead, where nothing else can supply it.
    """
    prose = "The Modality Role Router is written and unit-tested but not wired."
    assert DENIAL.search(prose)
    assert _names(prose, wired_slugs()) == ["modality"]
    assert not _names("The modality of the input is a design question.", wired_slugs())


def test_an_unwired_subject_excuses_the_denial() -> None:
    """A capability table row marked planned must not accuse its neighbours."""
    row = (
        "| Breath-Paced Dictation | `yazses features enable breath` "
        "*(planned — not yet wired)* | Pacing around breath |"
    )
    assert DENIAL.search(row)
    assert _names(row, set(_UNWIRED)), "the row's own subject must be recognised as unwired"


def test_no_docs_page_denies_a_wired_capability() -> None:
    offences = _offences()
    assert not offences, "\n".join(
        f"{p.relative_to(ROOT)}:~{n} calls the wired capability {slug!r} unwired — {s}"
        for p, n, slug, s in offences
    )
