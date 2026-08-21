"""`redact_patterns` scrubbed four of the six stored text fields.

`[learning] redact_patterns` is documented as *"Regexes scrubbed (→ `[REDACTED]`) from
text before storage"*. It was applied by `CorpusWriter._redact` over a hand-written
tuple:

    _REDACTABLE = ("raw_text", "cleaned_text", "filtered_text", "final_text")

but the store persists **six**, and three of its methods write text without ever going
near the writer:

    mark_wrong()               -> correction_text
    update_correction_for()    -> correction_text
    set_retx()                 -> retx_text

So `correction_text` and `retx_text` were stored unscrubbed. `retx_text` is the one that
matters: it is a **re-transcription of the same audio** the patterns were added to
protect, so a user who scrubbed a card number or a password out of `raw_text` had
`yazses tune --retranscribe` write it straight back into the corpus.

Found by a machine sweep for "one rule, two implementations" — the fourth defect of that
shape in this audit, after the gitvoice separators, the reflow/disfluency filler lists,
and the two TOML value renderers.

## The fix is structural, not another list

Redaction moved to `CorpusStore._enc`, the single point at which text becomes a stored
blob. "Encrypted" and "redacted" are now the same set **by construction** rather than by
two lists agreeing. `CorpusWriter` still scrubs before enqueuing, so a secret does not
sit in an in-memory queue — but it now scrubs *every* string value rather than a listed
subset, because the subset is exactly what failed.
"""

from __future__ import annotations

import dataclasses

import pytest

from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import _TEXT_FIELDS, CorpusStore

SECRET = "1234567812345678"
PATTERN = r"\b\d{16}\b"


@pytest.fixture
def store(tmp_path):
    s = CorpusStore(tmp_path, Cipher(load_or_create_key(tmp_path)), (PATTERN,))
    yield s
    s.close()


def test_every_stored_text_field_is_reachable_by_redaction(store) -> None:
    """The whole point: the set is the schema's, not a copy of it.

    Driven through the three writers so each stored field is actually populated —
    asserting over `_TEXT_FIELDS` alone would pass while two of them stayed empty.
    """
    store.add_event(
        {
            "raw_text": f"raw {SECRET}",
            "cleaned_text": f"cleaned {SECRET}",
            "filtered_text": f"filtered {SECRET}",
            "final_text": f"final {SECRET}",
        },
        None,
        16000,
    )
    event = store.events()[0]
    store.mark_wrong(event.id, f"correction {SECRET}")
    store.set_retx(event.id, f"retranscribed {SECRET}", 0.5)

    stored = store.events()[0]
    leaked = []
    for field in _TEXT_FIELDS:
        value = getattr(stored, field, "")
        if not value:
            leaked.append(f"{field}: never written — this test proves nothing about it")
        elif SECRET in value:
            leaked.append(f"{field}: {value!r}")
    assert not leaked, (
        "these stored text fields kept the secret the user asked to be scrubbed:\n  "
        + "\n  ".join(leaked)
    )


def test_the_retranscription_path_specifically(store) -> None:
    """The one that mattered most: `tune --retranscribe` re-derives it from the audio."""
    store.add_event({"raw_text": f"card {SECRET}", "final_text": "x"}, None, 16000)
    event = store.events()[0]
    assert SECRET not in event.raw_text, "the original was never the problem"

    store.set_retx(event.id, f"card {SECRET}", 0.4)
    assert SECRET not in store.events()[0].retx_text, (
        "tune wrote the secret back into the corpus that raw_text had it scrubbed from"
    )


def test_the_correction_path(store) -> None:
    store.add_event({"raw_text": "hello", "final_text": "hello"}, None, 16000)
    store.mark_wrong(store.events()[0].id, f"no I said {SECRET}")
    assert SECRET not in store.events()[0].correction_text


def test_the_field_list_still_matches_the_record(store) -> None:
    """`_TEXT_FIELDS` must name real record attributes, or the sweep above is empty."""
    store.add_event({"raw_text": "a", "final_text": "b"}, None, 16000)
    record = store.events()[0]
    names = {f.name for f in dataclasses.fields(record)}
    missing = sorted(set(_TEXT_FIELDS) - names)
    assert not missing, f"_TEXT_FIELDS names fields the record does not have: {missing}"
    assert len(_TEXT_FIELDS) >= 6


def test_no_patterns_means_no_change(tmp_path) -> None:
    """Redaction is opt-in; an empty pattern list must not touch anything."""
    s = CorpusStore(tmp_path, Cipher(load_or_create_key(tmp_path)))
    try:
        s.add_event({"raw_text": f"card {SECRET}", "final_text": "x"}, None, 16000)
        assert s.events()[0].raw_text == f"card {SECRET}"
    finally:
        s.close()


def test_redact_is_exposed_for_inspection(store) -> None:
    """Pure and callable, so the rule can be checked without writing a row."""
    assert store.redact(f"x {SECRET} y") == "x [REDACTED] y"
    assert store.redact("") == ""
    assert store.redact("nothing to scrub") == "nothing to scrub"
