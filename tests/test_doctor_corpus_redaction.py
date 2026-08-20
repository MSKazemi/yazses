"""`[learning] redact_patterns` scrubs the text; `capture_audio` keeps the sound.

The two settings sit one field apart in the same config section, and nothing in the tree
compared them. `CorpusStore.redact` runs at `_enc` — the one place text becomes a stored
blob, so every transcript column really is covered, and a comment there records that this
placement was itself a fix. `capture_audio` defaults to **true** and writes the source
audio beside the row.

So someone who added `redact_patterns = ['\\b\\d{16}\\b']` to keep a card number out of the
corpus has the number scrubbed from six text columns and themselves reading it aloud in
`clips/<id>.wav.enc`, encrypted with a key in the same directory.

Nothing here is broken and nothing here is a code fix. No redaction can reach into a
waveform, and the clip is exactly what `yazses tune --retranscribe` needs in order to
produce ground truth. The defect is that the promise and its limit were never stated in the
same place. `yazses doctor` is where someone looks when they want to know what is stored,
so that is where the two settings are now read together.

## Why it stays quiet

Doctor should not grow a row per dormant feature — the `_llm_endpoint_check` above it makes
the same argument in its own docstring. This check says nothing unless learning is on *and*
a pattern is actually set, which is the only configuration in which the user has asked for
something the audio undoes.
"""

from __future__ import annotations

from dataclasses import replace

from yazses.config import Config, LearningConfig
from yazses.system.doctor import _corpus_redaction_check


def _cfg(**kw) -> Config:
    cfg = Config()
    cfg.learning = replace(LearningConfig(), **kw)
    return cfg


def _row(cfg):
    rows = _corpus_redaction_check(cfg)
    assert len(rows) <= 1, rows
    return rows[0] if rows else None


# --- the finding ---------------------------------------------------------------

def test_it_warns_when_the_patterns_are_undone_by_the_recording():
    row = _row(_cfg(enabled=True, redact_patterns=[r"\b\d{16}\b"], capture_audio=True))
    assert row is not None
    name, status, detail = row
    assert status == "WARN"
    assert "capture_audio = true" in detail, (
        "the warning must name the setting that causes it -- naming only the remedy "
        f"leaves the reader guessing what is true now: {detail}"
    )
    assert "capture_audio = false" in detail, "and the one that fixes it"
    assert name == "Corpus redaction"


def test_it_is_satisfied_when_the_audio_is_not_kept():
    row = _row(_cfg(enabled=True, redact_patterns=[r"\b\d{16}\b"], capture_audio=False))
    assert row is not None
    assert row[1] == "OK"


def test_it_counts_the_patterns_it_is_talking_about():
    one = _row(_cfg(enabled=True, redact_patterns=["a"], capture_audio=True))
    many = _row(_cfg(enabled=True, redact_patterns=["a", "b", "c"], capture_audio=True))
    assert "1 pattern" in one[2] and "patterns" not in one[2]
    assert "3 patterns" in many[2]


def test_doctor_actually_runs_the_check(tmp_path):
    """A check nobody calls is worth nothing, and the function passes its own tests."""
    from yazses.system.doctor import _config_summary

    cfg = _cfg(enabled=True, redact_patterns=[r"\b\d{16}\b"], capture_audio=True)
    rows = _config_summary(cfg, tmp_path / "config.toml")

    assert any(name == "Corpus redaction" for name, _, _ in rows), (
        f"doctor never asks: {[n for n, _, _ in rows]}"
    )


# --- and it stays out of the way ------------------------------------------------

def test_silent_when_learning_is_off():
    assert _corpus_redaction_check(
        _cfg(enabled=False, redact_patterns=["a"], capture_audio=True)
    ) == []


def test_silent_when_no_redaction_was_asked_for():
    assert _corpus_redaction_check(
        _cfg(enabled=True, redact_patterns=[], capture_audio=True)
    ) == []


def test_a_blank_pattern_is_not_a_pattern():
    """`configcheck` keeps a list it cannot repair; an empty string asks for nothing."""
    assert _corpus_redaction_check(
        _cfg(enabled=True, redact_patterns=["", "   "], capture_audio=True)
    ) == []


def test_it_survives_a_config_object_without_the_section():
    class Bare:
        pass

    assert _corpus_redaction_check(Bare()) == []


# --- the premise it rests on ----------------------------------------------------

def test_redaction_really_does_only_touch_text(tmp_path):
    """If the clip were scrubbed too, this check would be nonsense and should go."""
    import numpy as np

    from yazses.learning.crypto import Cipher, load_or_create_key
    from yazses.learning.store import CorpusStore

    store = CorpusStore(tmp_path, Cipher(load_or_create_key(tmp_path)),
                        redact_patterns=(r"\d{4}",))
    try:
        audio = np.full(1600, 0.25, dtype=np.float32)
        store.add_event({"ts": 1.0, "raw_text": "the code is 1234", "final_text": "x"},
                        audio=audio)
        [event] = store.events()
        assert "1234" not in event.raw_text, "the text is not being redacted at all"
        assert list((tmp_path / "clips").glob("*.wav.enc")), (
            "the clip was not written, so this test proves nothing about it"
        )
    finally:
        store.close()


def test_capture_audio_still_defaults_to_on():
    """The reason the warning is worth having rather than an edge case."""
    assert LearningConfig().capture_audio is True
