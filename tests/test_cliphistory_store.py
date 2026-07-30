"""Persistent clipboard-history store (dedup/cap via ClipboardRing) — ADR-v2-060."""
from __future__ import annotations

from yazses.cliphistory import store


def test_add_is_newest_first_and_persists(tmp_path):
    p = store.cliphistory_path(tmp_path)
    store.add_item(p, "first")
    store.add_item(p, "second")
    items = store.add_item(p, "third")
    assert items == ["third", "second", "first"]
    assert store.load_items(p) == ["third", "second", "first"]


def test_consecutive_duplicate_ignored(tmp_path):
    p = store.cliphistory_path(tmp_path)
    store.add_item(p, "x")
    store.add_item(p, "x")  # consecutive dup — dropped by the ring
    assert store.load_items(p) == ["x"]


def test_capacity_caps_oldest(tmp_path):
    p = store.cliphistory_path(tmp_path)
    for i in range(5):
        store.add_item(p, f"item{i}", capacity=3)
    assert store.load_items(p) == ["item4", "item3", "item2"]


def test_load_missing_and_garbage(tmp_path):
    p = store.cliphistory_path(tmp_path)
    assert store.load_items(p) == []
    p.write_text("not json", encoding="utf-8")
    assert store.load_items(p) == []
