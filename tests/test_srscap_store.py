"""Persistent SRS card store + SM-2 review — ADR-v2-112."""
from __future__ import annotations

import pytest

from yazses.srscap import store
from yazses.srscap.cards import detect_fact, to_cloze


def test_add_and_load(tmp_path):
    p = store.srscap_path(tmp_path)
    card = to_cloze(detect_fact("remember that the capital of France is Paris"))
    deck = store.add_card(p, card)
    assert len(deck) == 1
    loaded = store.load_cards(p)
    assert loaded[0]["back"] == "Paris"
    assert loaded[0]["reps"] == 0 and loaded[0]["ease"] == 2.5


def test_review_advances_and_lapses(tmp_path):
    p = store.srscap_path(tmp_path)
    store.add_card(p, to_cloze(detect_fact("remember that pi is 3.14159")))
    c = store.review_card(p, 0, 5)      # good grade → reps 1, interval 1
    assert c["reps"] == 1 and c["interval"] == 1
    c = store.review_card(p, 0, 5)      # reps 2 → interval 6
    assert c["reps"] == 2 and c["interval"] == 6
    c = store.review_card(p, 0, 1)      # lapse → reps 0, interval 1
    assert c["reps"] == 0 and c["interval"] == 1


def test_review_out_of_range(tmp_path):
    p = store.srscap_path(tmp_path)
    with pytest.raises(IndexError):
        store.review_card(p, 0, 5)


def test_load_missing_and_garbage(tmp_path):
    p = store.srscap_path(tmp_path)
    assert store.load_cards(p) == []
    p.write_text("not json", encoding="utf-8")
    assert store.load_cards(p) == []
