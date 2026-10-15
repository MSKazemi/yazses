"""Prosodic Auto-Punctuation (ADR-v2-104): the pure applier and its daemon hook.

The decision rule is covered in test_spatialvad_prosodypunct.py. This file covers what makes it
safe to run on real dictation: it fills gaps only, keeps whitespace, refuses to guess when the
words and the timings disagree, composes with Prosody Ink, and costs nothing while disabled.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.postprocess.prosody import Word, annotate
from yazses.prosodypunct.apply import punctuate_text


def _spans(words: list[str], gaps_s: dict[int, float] | None = None):
    """Evenly spaced 0.3 s words; ``gaps_s[i]`` is the silence after word i (default 0.05 s)."""
    gaps_s = gaps_s or {}
    out, t = [], 0.0
    for i, _ in enumerate(words):
        out.append((t, t + 0.3))
        t += 0.3 + gaps_s.get(i, 0.05)
    return out


PROSE = (
    "I looked at the quarterly numbers again this morning and they are better than we feared "
    "but the churn figure still worries me so let us talk about it on Thursday"
)


def test_sentence_and_comma_marks_from_pauses():
    words = PROSE.split()
    i_feared = words.index("feared")
    i_morning = words.index("morning")
    spans = _spans(words, {i_feared: 0.9, i_morning: 0.4})
    res = punctuate_text(PROSE, spans)
    assert "morning, and" in res.text
    assert "feared. But the churn" in res.text          # next word capitalised
    assert (res.sentences, res.commas) == (1, 1)
    # Nothing else changed: removing the two marks and the capital gives the input back.
    restored = res.text.replace("morning,", "morning").replace("feared.", "feared")
    assert restored.replace("But", "but") == PROSE


def test_no_pauses_means_text_unchanged():
    words = PROSE.split()
    res = punctuate_text(PROSE, _spans(words))
    assert res.text == PROSE and (res.sentences, res.commas) == (0, 0)


def test_existing_punctuation_is_never_doubled():
    text = "Well, that went fine. Now the next part is harder, I think."
    words = text.split()
    spans = _spans(words, {i: 1.0 for i in range(len(words))})   # a long pause after every word
    res = punctuate_text(text, spans)
    for bad in (",.", "..", ".,", ",,", ".?"):
        assert bad not in res.text
    assert res.text.lower().endswith("think.")                  # the final word never gains a mark
    low = res.text.lower()
    assert "well," in low and "fine. now" in low and "harder, i" in low
    assert res.text.lower().count("think") == 1


def test_whitespace_and_newlines_survive():
    text = "first item\n\nsecond   item here"
    spans = _spans(text.split(), {1: 0.9})
    res = punctuate_text(text, spans)
    assert res.text == "first item.\n\nSecond   item here"


def test_mismatched_word_count_refuses_to_guess():
    text = "I have twenty five apples"
    spans = _spans(["i", "have", "twenty", "five", "apples", "x"], {2: 1.0})
    res = punctuate_text(text, spans)
    assert res.text == text


def test_degenerate_inputs():
    assert punctuate_text("", []).text == ""
    assert punctuate_text("one", [(0.0, 0.2)]).text == "one"
    # overlapping timestamps (a negative gap) are a zero gap, not a crash
    assert punctuate_text("a b", [(0.0, 1.0), (0.5, 1.5)]).text == "a b"


def test_marks_only_go_after_a_letter_or_digit():
    # A bullet, a flag, a bracket-only token and a markdown span must not take a mark.
    text = "- item ) **bold** (see above) done"
    spans = _spans(text.split(), {0: 1.0, 2: 1.0, 3: 1.0, 5: 1.0})
    res = punctuate_text(text, spans)
    assert res.text.startswith("- item")                 # a bare "-" takes no mark
    assert ") **bold**" in res.text                      # a lone bracket and a markdown span neither
    assert "(see above)." in res.text                    # a closing bracket takes it after the bracket


def test_does_not_capitalise_mixed_case_or_non_letters():
    text = "ship it iPhone next 3d"
    res = punctuate_text(text, _spans(text.split(), {1: 0.9, 3: 0.9}))
    assert res.text == "ship it. iPhone next. 3d"
    res2 = punctuate_text("ok then 3d", _spans(["ok", "then", "3d"], {1: 0.9}))
    assert res2.text == "ok then. 3d"


def test_composes_with_prosody_ink():
    """Prosody Ink renders after us; it must keep our marks and not add a second period."""
    words = PROSE.split()
    spans = _spans(words, {words.index("feared"): 0.9})
    wlist = [Word(w, s, e) for w, (s, e) in zip(words, spans)]
    cfg = Config().prosody
    cfg.format = "none"
    cfg.pause_sentence_ms = 500        # Prosody Ink's own period step also fires at this gap
    cfg.pause_paragraph_ms = 5000
    punct = punctuate_text(PROSE, spans).text
    out = annotate(punct, np.zeros(1600, dtype="float32"), 16000, wlist, cfg).text
    assert "feared. But" in out and "feared.." not in out
    assert out.count(".") == 1


# ---- daemon hook -----------------------------------------------------------------------------

class _Rec:
    def stop(self):
        return np.full(16000, 0.5, dtype="float32")


class _Engine:
    def __init__(self, text, words):
        self.text, self.words = text, words
        self.word_calls = self.plain_calls = 0

    def transcribe(self, *a, **k):
        self.plain_calls += 1
        return self.text

    def transcribe_words(self, *a, **k):
        self.word_calls += 1
        return self.text, self.words


class _Inj:
    def __init__(self):
        self.calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(enabled: bool, text: str, words):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.prosodypunct.enabled = enabled
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Rec()
    d._engine = _Engine(text, words)
    d._padding_buffer = None
    d._injector = _Inj()
    return d


def _words_for(text, gaps):
    toks = text.split()
    return [Word(w, s, e) for w, (s, e) in zip(toks, _spans(toks, gaps))]


def test_daemon_punctuates_when_enabled():
    text = "the build is green we can ship"
    d = _daemon(True, text, _words_for(text, {3: 0.9}))
    d._on_hold_end()
    assert d._injector.calls == ["the build is green. We can ship"]
    assert d._engine.word_calls == 1


def test_daemon_default_is_untouched_and_skips_the_word_path():
    text = "the build is green we can ship"
    d = _daemon(False, text, _words_for(text, {3: 0.9}))
    d._on_hold_end()
    assert d._injector.calls == [text]
    assert (d._engine.word_calls, d._engine.plain_calls) == (0, 1)


def test_default_config_is_off_and_feature_is_enableable():
    from yazses.system.features import unwired_slugs

    assert Config().prosodypunct.enabled is False
    assert "prosodypunct" not in unwired_slugs()
