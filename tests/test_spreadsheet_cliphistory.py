"""Spoken Spreadsheet (ADR-v2-059) + Clipboard-History by Voice (ADR-v2-060) — pure cores."""
from __future__ import annotations

from yazses.cliphistory.history import ClipboardRing, resolve_reference
from yazses.spreadsheet.grid import parse_cell_reference, parse_grid_move

# ---- spreadsheet -----------------------------------------------------------

def test_grid_moves():
    assert parse_grid_move("next row") == ["Return"]
    assert parse_grid_move("next cell") == ["Tab"]
    assert parse_grid_move("cell down") == ["Down"]
    assert parse_grid_move("top of column") == ["ctrl+Up"]


def test_grid_move_unknown():
    assert parse_grid_move("hello there") is None


def test_cell_reference_a1_and_words():
    assert parse_cell_reference("go to B7") == "B7"
    assert parse_cell_reference("cell aa12") == "AA12"
    assert parse_cell_reference("column C row 42") == "C42"


def test_cell_reference_requires_anchor():
    # a bare word+number is NOT read as a cell without an anchor keyword
    assert parse_cell_reference("i love mp3 files") is None
    assert parse_cell_reference("nothing here") is None


# ---- clipboard history -----------------------------------------------------

def test_ring_newest_first_and_dedup():
    r = ClipboardRing(capacity=3)
    r.add("a")
    r.add("b")
    r.add("b")          # consecutive dup ignored
    r.add("c")
    r.add("d")          # evicts "a" (cap 3)
    assert r.items() == ["d", "c", "b"]


def test_ring_ignores_empty():
    r = ClipboardRing()
    r.add("")
    assert r.items() == []


def test_resolve_ordinals():
    items = ["newest", "middle", "oldest"]
    assert resolve_reference("paste the last thing I copied", items) == "newest"
    assert resolve_reference("the second thing", items) == "middle"
    assert resolve_reference("the first thing I copied", items) == "oldest"


def test_resolve_keyword_filters():
    items = ["just text", "visit https://example.com", "mail me at a@b.com"]
    assert resolve_reference("paste the url I copied", items) == "visit https://example.com"
    assert resolve_reference("the email I copied", items) == "mail me at a@b.com"


def test_resolve_number_and_default_and_empty():
    items = ["one", "two", "three"]
    assert resolve_reference("paste number 2", items) == "two"
    assert resolve_reference("just paste", items) == "one"      # default newest
    assert resolve_reference("number 9", items) is None          # out of range
    assert resolve_reference("anything", []) is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "spreadsheet" in slugs and "cliphistory" in slugs
    assert Config().spreadsheet.enabled is False and Config().cliphistory.enabled is False
