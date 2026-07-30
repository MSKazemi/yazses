"""Persistent outline store — (de)serialisation roundtrip — ADR-v2-124."""
from __future__ import annotations

from yazses.outline import store
from yazses.outline.tree import apply_outline_op, new_outline, render


def test_roundtrip_preserves_items_and_cursor(tmp_path):
    p = store.outline_path(tmp_path)
    state = new_outline()
    state = apply_outline_op(state, "add", "Chapter 1")
    state = apply_outline_op(state, "add", "Section A")
    state = apply_outline_op(state, "indent")
    store.save_outline(p, state)

    loaded = store.load_outline(p)
    assert [(i.text, i.level) for i in loaded["items"]] == [("Chapter 1", 0), ("Section A", 1)]
    assert loaded["cursor"] == state["cursor"]
    # renders identically after a load
    assert render(loaded, "markdown") == render(state, "markdown")


def test_load_missing_is_empty(tmp_path):
    assert store.load_outline(store.outline_path(tmp_path)) == new_outline()


def test_load_garbage_is_empty(tmp_path):
    p = store.outline_path(tmp_path)
    p.write_text("not json", encoding="utf-8")
    assert store.load_outline(p) == new_outline()
