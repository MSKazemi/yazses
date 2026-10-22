"""Capability counts on hand-written pages come from the registry, never from a hand.

Issue #646 (ADR-030 Pillar 1.4): "counts come from the registry
(yazses.system.features), never by hand." When this was written, four user-facing
pages carried a typed number and every one was wrong: `docs/research/directions.md`
said 30 capabilities were unreachable, `framework-gaps.md` 30, `glossary.md` 29, and
`docs/architecture.md` spoke of "~200 capabilities", against a registry of 149 with 25
unwired. Nothing checked any of them. `ROADMAP.md` and `docs/mobile/index.md` were
checked -- by a regex in `test_docs_current_version_claims.py` -- but checked is not
written: someone still had to retype the number.

So the number is now written by `scripts/gen-docs.py` (`make docs`) between
`<!-- registry:KIND -->` and `<!-- /registry -->`, and this file holds three things:

* every marker on every listed page carries the live count (regenerate, compare);
* a marker on a page the generator does not visit is a failure, not a frozen number;
* a count phrase written **outside** a marker, on any user-facing page, fails -- so a
  new page cannot reintroduce a hand-typed "N capabilities".

The hand-drawn diagrams under `docs/diagrams/` are the one exception, because a
comment would break their Mermaid blocks; `test_gen_arch_figures.py` checks those.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen-docs.py"


@pytest.fixture(scope="module")
def gen():
    """Import the hyphenated script by path, as test_gen_docs.py does."""
    spec = importlib.util.spec_from_file_location("gen_docs_counts", GEN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the generator's own contract --------------------------------------------


def test_the_counts_are_the_registry_s(gen):
    """`wired` is the same flag `features enable` refuses on, not a second opinion."""
    from yazses.config import Config
    from yazses.system.features import feature_status, unwired_slugs

    counts = gen.registry_counts()
    feats = feature_status(Config())
    assert counts["total"] == len(feats)
    assert counts["unwired"] == len(unwired_slugs())
    assert counts["wired"] == counts["total"] - counts["unwired"]
    assert counts["wired"] == sum(1 for f in feats if f.wired)


def test_fill_rewrites_only_the_number_between_the_markers(gen):
    stale = (
        "We ship **<!-- registry:total -->1<!-- /registry --> capabilities** "
        "(<!-- registry:wired -->2<!-- /registry --> wired, "
        "<!-- registry:unwired --><!-- /registry --> planned). 30 apples."
    )
    counts = {"total": 149, "wired": 124, "unwired": 25}
    got = gen.fill_registry_counts(stale, counts)
    assert got == (
        "We ship **<!-- registry:total -->149<!-- /registry --> capabilities** "
        "(<!-- registry:wired -->124<!-- /registry --> wired, "
        "<!-- registry:unwired -->25<!-- /registry --> planned). 30 apples."
    )
    assert gen.fill_registry_counts(got, counts) == got, "filling must be idempotent"


def test_fill_leaves_text_without_markers_untouched(gen):
    text = "149 capabilities, written by hand."
    assert gen.fill_registry_counts(text, {"total": 1, "wired": 1, "unwired": 0}) == text


# --- the committed pages ------------------------------------------------------


def _pages(gen) -> list[str]:
    return list(gen.REGISTRY_COUNT_PAGES)


def test_every_listed_page_exists_and_carries_a_marker(gen):
    """A listed page with no marker means the count was moved out of the generator's
    reach -- most likely retyped by hand."""
    assert _pages(gen), "REGISTRY_COUNT_PAGES is empty; nothing is being generated"
    for rel in _pages(gen):
        path = ROOT / rel
        assert path.is_file(), f"{rel} is listed in REGISTRY_COUNT_PAGES but missing"
        assert gen.REGISTRY_MARKER.search(path.read_text(encoding="utf-8")), (
            f"{rel} has no `<!-- registry:KIND -->N<!-- /registry -->` marker"
        )


def test_every_marker_carries_the_live_count(gen):
    """The drift guard: regenerate in memory and compare with what is committed."""
    counts = gen.registry_counts()
    stale = []
    for rel in _pages(gen):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if gen.fill_registry_counts(text, counts) != text:
            found = sorted(set(gen.REGISTRY_MARKER.findall(text)))
            stale.append(f"{rel}: {found}")
    assert not stale, (
        f"these pages state stale registry counts (live: {counts}): {stale}. Run "
        "`uv run python scripts/gen-docs.py` (or `make docs`) and commit the result."
    )


def _user_pages() -> list[Path]:
    """Every user-facing Markdown page a count could be typed into.

    Excluded: release notes (a dated record of what was true then), the generated
    reference pages (their numbers come from the registry already), and the
    hand-drawn diagrams (guarded by `test_gen_arch_figures.py`).
    """
    generated = {"features.md", "configuration.md", "command-index.md"}
    pages = [ROOT / "ROADMAP.md"]
    for path in sorted((ROOT / "docs").rglob("*.md")):
        parts = path.relative_to(ROOT / "docs").parts
        if parts[0] in ("releases", "diagrams"):
            continue
        if len(parts) == 1 and parts[0] in generated:
            continue
        pages.append(path)
    return pages


def test_no_page_outside_the_list_carries_a_marker(gen):
    """The generator only visits the listed pages; a marker anywhere else is a number
    that looks generated and is frozen."""
    listed = set(_pages(gen))
    strays = sorted(
        p.relative_to(ROOT).as_posix()
        for p in _user_pages()
        if "<!-- registry:" in p.read_text(encoding="utf-8")
        and p.relative_to(ROOT).as_posix() not in listed
    )
    assert not strays, f"add these to REGISTRY_COUNT_PAGES in scripts/gen-docs.py: {strays}"


#: A count of capabilities, wired, unwired or designed-but-unbuilt ones, typed as a
#: digit. Matched over the whole page so a phrase wrapped across lines is still seen.
HAND_COUNT = re.compile(
    r"\b\d+\+?\s+capabilities\b"
    r"|\b\d+\s+wired\b"
    r"|\b\d+\s+(?:of\s+\d+\s+)?(?:are\s+)?unwired\b"
    r"|\b\d+\s+designed[- ]but[- ](?:not[- ]yet[- ])?(?:un)?wired\b"
    r"|\b\d+\s+of\s+them\s+are\s+not\s+reachable\b",
    re.IGNORECASE,
)


def hand_counts(text: str, marker: re.Pattern[str]) -> list[str]:
    """Count phrases in *text* whose number is not inside a registry marker."""
    return [m.group(0) for m in HAND_COUNT.finditer(marker.sub("N", text))]


def test_the_sweep_finds_a_hand_typed_count_and_excuses_a_marked_one(gen):
    """A sweep that finds nothing reports compliance; prove it can find something."""
    marker = gen.REGISTRY_MARKER
    assert hand_counts("YazSes ships 149 capabilities.", marker) == ["149 capabilities"]
    assert hand_counts("29 of 149 are unwired", marker) == ["29 of 149 are unwired"]
    assert hand_counts("the 30\ndesigned-but-unwired ones", marker)
    assert hand_counts("149 capabilities and 30 of them are\nnot reachable", marker)
    assert not hand_counts(
        "<!-- registry:total -->149<!-- /registry --> capabilities, "
        "<!-- registry:wired -->124<!-- /registry --> wired", marker,
    )
    assert not hand_counts("a 2.06 % WER and 72 of them in v2.14.0", marker)


def test_no_user_facing_page_types_a_count_by_hand(gen):
    pages = _user_pages()
    assert len(pages) > 50, f"only {len(pages)} pages swept -- the glob lost its corpus"
    offences = []
    for path in pages:
        for phrase in hand_counts(path.read_text(encoding="utf-8"), gen.REGISTRY_MARKER):
            offences.append(f"{path.relative_to(ROOT).as_posix()}: {' '.join(phrase.split())!r}")
    assert not offences, (
        "hand-typed capability counts -- wrap the number in "
        "`<!-- registry:total|wired|unwired -->N<!-- /registry -->`, add the page to "
        "REGISTRY_COUNT_PAGES in scripts/gen-docs.py, and run it:\n  "
        + "\n  ".join(offences)
    )
