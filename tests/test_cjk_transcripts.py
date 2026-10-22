"""Mandarin through file transcription and Meeting Mode (#501 COMP-04/05).

The word path is where a Mandarin transcript was quietly corrupted: faster-whisper
splits a Chinese decode into per-character word tokens with no spaces, and every
consumer glued them back with ``" ".join`` -- so diarized utterances, the JSON, and every
SRT/VTT caption read ``你 好 ， 世 界``. Captions were also measured in code points and
broken only at spaces, so a Han caption was one unbreakable line twice the width a
player can show.

All text here is synthetic and written for this file. No model is run: the word tokens
are shaped like faster-whisper 1.2.1's code-point split for ``zh``
(``Tokenizer.split_to_word_tokens``), with its punctuation merging applied.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.meeting.notes import _split_long_text
from yazses.meeting.quality import tokenize
from yazses.meeting.store import live_text
from yazses.postprocess.cjk import display_width
from yazses.recimport.align import assign_words_to_turns, merge_utterances
from yazses.recimport.subtitles import (
    CAPTION_LINE_CHARS,
    merge_word_timestamps,
    wrap_caption,
    write_srt,
    write_vtt,
)

#: "你好，世界。今天测试 YazSes 123。" as Mandarin word tokens, already glued.
_SENTENCE_WORDS = ["你", "好，", "世", "界。", "今", "天", "测", "试", "YazSes", "123。"]


def _timed(words, step=0.2):
    return [(w, i * step, i * step + step * 0.9) for i, w in enumerate(words)]


# --- caption segmentation and wrapping -------------------------------------------------


def test_caption_segment_rebuilds_the_mandarin_sentence_exactly():
    segs = merge_word_timestamps(_timed(_SENTENCE_WORDS))
    assert [text for _, _, text in segs] == ["你好，世界。今天测试 YazSes 123。"]


def test_caption_segment_budget_is_measured_in_display_columns():
    # 60 Han characters is 120 columns: over the 80-column segment budget, so it must
    # split. Measured in code points (the old rule) it fitted, and was one caption.
    words = list("我们今天讨论一下项目的进度和下一步的计划然后确定每个人负责的部分" * 2)[:60]
    segs = merge_word_timestamps(_timed(words, step=0.1))
    assert len(segs) >= 2
    assert all(display_width(text) <= 80 for _, _, text in segs)
    assert "".join(text for _, _, text in segs) == "".join(words)


def test_mandarin_caption_is_wrapped_between_characters():
    text = "我们今天讨论一下项目的进度和下一步的计划，然后确定每个人负责的部分。"
    wrapped = wrap_caption(text)
    lines = wrapped.split("\n")
    assert len(lines) == 2
    assert all(display_width(line) <= CAPTION_LINE_CHARS for line in lines)
    assert "".join(lines) == text            # nothing lost, nothing added
    assert not lines[1].startswith(("，", "。"))


def test_mixed_caption_never_splits_a_latin_word():
    text = "这次发布的版本是 YazSes v2.0，请大家下载以后在自己的电脑上测试一下语音输入功能"
    lines = wrap_caption(text).split("\n")
    assert all(display_width(line) <= CAPTION_LINE_CHARS for line in lines)
    assert "YazSes" in "\n".join(lines) and "v2.0，" in "\n".join(lines)
    rebuilt = "".join(lines)
    # The only change a break may make is to drop the space it replaced.
    assert rebuilt.replace(" ", "") == text.replace(" ", "")


def test_english_caption_wrapping_is_unchanged():
    text = "the quick brown fox jumps over the lazy dog and keeps running far away"
    assert wrap_caption(text) == "the quick brown fox jumps over the\nlazy dog and keeps running far away"


def test_srt_and_vtt_carry_han_text_and_timestamps():
    segs = merge_word_timestamps(_timed(_SENTENCE_WORDS))
    srt = write_srt(segs)
    vtt = write_vtt(segs)
    assert "00:00:00,000 --> 00:00:01,980\n你好，世界。今天测试 YazSes 123。" in srt
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.980\n你好，世界。今天测试")


# --- diarized utterances ------------------------------------------------------------------


def test_diarized_utterances_join_han_words_without_spaces():
    words = [(s, e, w) for w, s, e in _timed(_SENTENCE_WORDS)]
    turns = [(0.0, 0.8, "speaker_0"), (0.8, 2.0, "speaker_1")]
    utterances = merge_utterances(assign_words_to_turns(words, turns))
    assert [(u.speaker, u.text) for u in utterances] == [
        ("speaker_0", "你好，世界。"),
        ("speaker_1", "今天测试 YazSes 123。"),
    ]


def test_english_utterances_still_join_with_spaces():
    words = [(0.0, 0.3, "hello"), (0.4, 0.7, "there"), (0.8, 1.0, "friend.")]
    utterances = merge_utterances(assign_words_to_turns(words, [(0.0, 2.0, "speaker_0")]))
    assert utterances[0].text == "hello there friend."


# --- the rendered files, end to end ----------------------------------------------------------


def _result(diarized: bool):
    from yazses.recimport.align import Utterance

    words = [(s, e, w) for w, s, e in _timed(_SENTENCE_WORDS)]
    turns = [(0.0, 0.8, "speaker_0"), (0.8, 2.0, "speaker_1")] if diarized else []
    if diarized:
        assigned = assign_words_to_turns(words, turns)
        utterances = merge_utterances(assigned)
    else:
        assigned = [("", s, e, w) for s, e, w in words]
        utterances = [Utterance("", 0.0, 2.0, "你好，世界。今天测试 YazSes 123。")]
    return SimpleNamespace(
        text="你好，世界。今天测试 YazSes 123。",
        utterances=utterances,
        assigned=assigned,
        language="zh",
        diarized=diarized,
        speaker_names={"speaker_0": "说话人一", "speaker_1": "Speaker 2"} if diarized else {},
    )


@pytest.mark.parametrize("fmt", ["md", "txt", "srt", "vtt", "json"])
def test_every_renderer_keeps_the_han_text_intact(fmt):
    from yazses.recimport.render import render_transcript as render

    out = render(_result(diarized=True), fmt)
    assert "你 好" not in out and "世 界" not in out
    if fmt == "json":
        payload = json.loads(out)
        assert [u["text"] for u in payload["utterances"]] == ["你好，世界。", "今天测试 YazSes 123。"]
        assert payload["language"] == "zh"
        assert "说话人一" in out  # a Han speaker name survives ensure_ascii=False
    else:
        assert "你好，世界。" in out and "今天测试 YazSes 123。" in out


# --- Meeting Mode accounting -------------------------------------------------------------------


def test_meeting_quality_counts_han_characters_not_whitespace_runs():
    # One whitespace "word" per sentence would make a healthy Mandarin meeting look empty.
    assert len(tokenize("你好，世界。今天测试 YazSes 123。")) == 9  # 8 Han characters + "yazses"
    assert len("你好，世界。今天测试 YazSes 123。".split()) == 3


def test_live_text_joins_mandarin_lines_without_a_space(tmp_path):
    lines = [{"text": "你好，世界。"}, {"text": "今天测试。"}, {"text": "   "}]
    (tmp_path / "live.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8"
    )
    assert live_text(tmp_path) == "你好，世界。今天测试。"


def test_notes_window_splits_a_long_mandarin_turn_within_budget():
    turn = "我们今天讨论一下项目的进度，" * 20  # 280 characters, no whitespace at all
    pieces = _split_long_text(turn, 50)
    assert len(pieces) > 1
    assert all(len(p) <= 50 for p in pieces)
    assert "".join(pieces) == turn


def test_notes_window_split_is_unchanged_for_english():
    text = "alpha beta gamma delta epsilon zeta eta theta"
    assert _split_long_text(text, 12) == ["alpha beta", "gamma delta", "epsilon zeta", "eta theta"]


# --- the decoder's word tokens -------------------------------------------------------------------


def _fw_word(text, start, end, p=0.9):
    return SimpleNamespace(word=text, start=start, end=end, probability=p)


@pytest.fixture
def fw():
    return pytest.importorskip("yazses.stt.faster_whisper", reason="the decoder stack has no FreeBSD build")


def _engine(fw, segments, language):
    eng = fw.FasterWhisperEngine.__new__(fw.FasterWhisperEngine)
    eng._language = ""
    eng._model = SimpleNamespace(
        transcribe=lambda audio, **kw: (iter(segments), SimpleNamespace(language=language))
    )
    return eng


def test_mandarin_word_tokens_come_back_as_written(fw):
    seg = SimpleNamespace(
        text="今天测试 YazSes 123。",
        words=[
            _fw_word("今", 0.0, 0.2), _fw_word("天", 0.2, 0.4), _fw_word("测", 0.4, 0.6),
            _fw_word("试", 0.6, 0.8), _fw_word(" Yaz", 0.9, 1.1, 0.8), _fw_word("Ses", 1.1, 1.3, 0.6),
            _fw_word(" 1", 1.4, 1.5), _fw_word("23。", 1.5, 1.8),
        ],
    )
    text, words = _engine(fw, [seg], "zh").transcribe_words(np.ones(10, dtype="float32"))
    assert text == "今天测试 YazSes 123。"
    assert [w.text for w in words] == ["今", "天", "测", "试", "YazSes", "123。"]
    yazses = words[4]
    assert (yazses.start, yazses.end, yazses.probability) == (0.9, 1.3, 0.6)


def test_english_word_tokens_are_not_regrouped(fw):
    seg = SimpleNamespace(
        text=" Hello there; friend.",
        words=[_fw_word(" Hello", 0.0, 0.3), _fw_word(" there", 0.3, 0.6),
               _fw_word(";", 0.6, 0.6), _fw_word(" friend.", 0.7, 1.0)],
    )
    _, words = _engine(fw, [seg], "en").transcribe_words(np.ones(10, dtype="float32"))
    assert [w.text for w in words] == ["Hello", "there", ";", "friend."]


def test_detected_language_decides_not_only_the_configured_one(fw):
    # `[stt] language` unset: faster-whisper detected Mandarin, and split by code point.
    seg = SimpleNamespace(text="版本 v2.0", words=[
        _fw_word("版", 0.0, 0.2), _fw_word("本", 0.2, 0.4), _fw_word(" v", 0.5, 0.6),
        _fw_word("2", 0.6, 0.7), _fw_word(".0", 0.7, 0.8),
    ])
    _, words = _engine(fw, [seg], "zh").transcribe_words(np.ones(10, dtype="float32"))
    assert [w.text for w in words] == ["版", "本", "v2.0"]


# --- [stt] chinese_script reaches the engines built off the daemon path ---------------------


def test_transcribe_file_builds_its_engine_with_the_stt_section(monkeypatch):
    """`meeting recover` (and any caller without an engine) gets the script setting."""
    import yazses.recimport.pipeline as pipeline

    seen = {}

    class _Engine:
        def transcribe_words(self, audio, sample_rate=16000, task=None):
            return "你好", []

    def fake_build(config, stt=None):
        seen["stt"] = stt
        return _Engine()

    monkeypatch.setattr(pipeline, "_build_engine", fake_build)
    monkeypatch.setattr(pipeline, "build_diarizer", lambda *_a, **_k: None)
    stt = SimpleNamespace(chinese_script="simplified")
    cfg = SimpleNamespace(language="zh", model="small")
    pipeline.transcribe_file(None, cfg, audio=np.full(16000, 0.1, dtype="float32"), stt=stt)
    assert seen["stt"] is stt


def test_finalize_and_recover_thread_the_stt_section(monkeypatch, tmp_path):
    import yazses.meeting.finalize as fin
    import yazses.recimport.pipeline as pipeline

    captured = {}

    def fake_transcribe_file(*_a, **kw):
        captured.update(kw)
        raise RuntimeError("stop here")

    monkeypatch.setattr(pipeline, "transcribe_file", fake_transcribe_file)
    stt = SimpleNamespace(chinese_script="traditional")
    with pytest.raises(RuntimeError, match="stop here"):
        fin.finalize_meeting(np.zeros(10, dtype="float32"), SimpleNamespace(), stt=stt)
    assert captured["stt"] is stt


def test_cli_recover_passes_the_stt_section():
    # The CLI is the only caller of recover_meeting; read the call rather than run a
    # model. A refactor that drops the argument turns this red.
    import inspect

    from yazses import cli

    assert "recover_meeting(d, cfg.meeting, stt=cfg.stt)" in inspect.getsource(cli)
