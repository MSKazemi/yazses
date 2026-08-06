"""Self-Learning Correction Dictionary (ADR-v2-079) + Voice Fuzzy File Open (ADR-v2-080) — pure cores."""
from __future__ import annotations

from yazses.corrdict.mine import apply_corrections, mine_substitutions
from yazses.fileopen.match import fuzzy_rank, resolve_open

# ---- correction dictionary -------------------------------------------------

def test_mine_keeps_supported_dominant():
    events = [("yaz says", "YazSes")] * 3 + [("teh", "the")] * 2
    table = mine_substitutions(events, min_support=3)
    assert table == {"yaz says": "YazSes"}     # "teh" below support


def test_mine_drops_ambiguous():
    events = [("lead", "led"), ("lead", "lead metal"), ("lead", "led"), ("lead", "lead metal")]
    # two rival corrections tie → dropped
    assert mine_substitutions(events, min_support=2) == {}


def test_mine_ignores_noop_and_blank():
    assert mine_substitutions([("same", "same"), ("", "x"), ("y", "")], min_support=1) == {}


def test_apply_corrections_boundary_and_longest():
    table = {"yaz": "YazSes", "yaz says": "YazSes said"}
    # longest key wins; boundary-guarded so "yazoo" is untouched
    assert apply_corrections("yaz says hi and yazoo", table) == "YazSes said hi and yazoo"


def test_apply_corrections_empty():
    assert apply_corrections("hello", {}) == "hello"
    assert apply_corrections("", {"a": "b"}) == ""


# ---- fuzzy file open -------------------------------------------------------

FILES = ["mortgage-notes.md", "grocery-list.txt", "2024-taxes.pdf", "mortgage_application.docx"]


def test_fuzzy_rank_prefers_content_match():
    ranked = fuzzy_rank("open the notes about the mortgage", FILES)
    assert ranked[0][0] == "mortgage-notes.md"


def test_resolve_open_threshold():
    assert resolve_open("open the mortgage notes", FILES) == "mortgage-notes.md"
    assert resolve_open("something totally unrelated zzz", FILES, threshold=0.6) is None


def test_resolve_open_empty():
    assert resolve_open("anything", []) is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "corrdict" in slugs and "fileopen" in slugs
    assert Config().corrdict.enabled is False and Config().fileopen.enabled is False
