"""Persistent acronym glossary store + document expansion — ADR-v2-114."""
from __future__ import annotations

import pytest

from yazses.acronyms import store
from yazses.acronyms.glossary import expand_document


def test_add_load_remove_roundtrip(tmp_path):
    p = store.glossary_path(tmp_path)
    store.add_entry(p, "api", "Application Programming Interface")
    store.add_entry(p, "CPU", "Central Processing Unit")
    g = store.load_glossary(p)
    assert g == {
        "API": "Application Programming Interface",
        "CPU": "Central Processing Unit",
    }
    store.remove_entry(p, "api")  # case-insensitive
    assert store.load_glossary(p) == {"CPU": "Central Processing Unit"}


def test_add_normalises_and_validates(tmp_path):
    p = store.glossary_path(tmp_path)
    store.add_entry(p, "a-p-i", "Application Programming Interface")
    assert "API" in store.load_glossary(p)
    with pytest.raises(ValueError):
        store.add_entry(p, "", "nope")
    with pytest.raises(ValueError):
        store.add_entry(p, "API", "   ")


def test_load_missing_is_empty(tmp_path):
    assert store.load_glossary(store.glossary_path(tmp_path)) == {}


def test_load_tolerates_garbage(tmp_path):
    p = store.glossary_path(tmp_path)
    p.write_text("not json", encoding="utf-8")
    assert store.load_glossary(p) == {}


def test_expand_document_first_use_only():
    defs = {"API": "Application Programming Interface", "CPU": "Central Processing Unit"}
    out = expand_document("The API and the API plus the CPU.", defs)
    assert out == (
        "The Application Programming Interface (API) and the API "
        "plus the Central Processing Unit (CPU)."
    )


def test_expand_document_unknown_passes_through():
    assert expand_document("The XYZ thing", {"API": "Application Programming Interface"}) == "The XYZ thing"
