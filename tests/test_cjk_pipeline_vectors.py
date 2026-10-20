"""CJK regression vectors through the real default dictation pipeline (#501, COMP-02).

Every vector is synthetic text written for this file (no recorded speech, nothing from a
real user). Each is driven through ``Daemon._on_hold_end`` with the engine, recorder and
injector faked and the configuration left at its **shipped defaults** — so the default-on
transforms (``clean_text``, the disfluency filter, the command classifier, continuation
spacing) all run exactly as they do for a user.

The contract these vectors pin: text a recogniser could plausibly return for Mandarin
reaches the injector **byte-for-byte**. No space inserted or deleted, no full-width mark
rewritten. The per-transform classification behind them is
``design/chinese/postprocess-compatibility.md``.

A vector that fails on current behaviour is not weakened: it is an ``xfail(strict=True)``
carrying the reason, so it turns red the day it is fixed and the marker has to go. Those
are findings, not accepted behaviour. English behaviour is pinned elsewhere
(``tests/test_cleaner.py``, ``tests/test_continuation_spacing_daemon.py``, the contract
vectors); nothing here changes it.
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.config import Config, HallucinationConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.postprocess.hallucination import drop_reason


class _FakeRecorder:
    def stop(self):
        # Loud audio so the silence gate never discards the burst.
        return np.full(16000, 0.5, dtype="float32")


class _FakeEngine:
    def __init__(self):
        self.text = ""

    def transcribe(self, *args, **kwargs):
        return self.text


class _RecordingInjector:
    def __init__(self):
        self.calls: list = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        self.calls.append(("backspaces", count))

    def inject_key_sequence(self, keys):
        self.calls.append(("keys", keys))


def _daemon(language: str):
    cfg = Config()  # shipped defaults: nothing is switched off
    cfg.stt.language = language
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder()
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _RecordingInjector()
    d._injector = inj
    return d, inj


def _dictate(language: str, *bursts: str) -> list:
    d, inj = _daemon(language)
    for text in bursts:
        d._engine.text = text
        d._on_hold_end()
    return inj.calls


# --- vectors that must reach the injector unchanged ---------------------------------------

#: (id, text). ``text`` is what the recogniser hands back; it is also the expected output.
_IDENTITY = [
    ("han-latin-no-space", "我用Python写了一个脚本。"),
    ("date-numerals", "今天是2026年10月15日"),
    ("issue-simplified", "你好，世界。今天测试 YazSes 123。"),
    ("issue-traditional", "你好，世界。今天測試 YazSes 123。"),
    ("issue-mixed", "版本 v2.0，文件 test.py，编号 12345。"),
    ("curly-quotes", "他说：“你好！”"),
    ("fullwidth-parens-yen", "价格是￥100.50元（含税）"),
    ("corner-brackets", "「引用」和『书名』《红楼梦》"),
    ("enumeration-comma", "苹果、香蕉、橙子；还有梨？"),
    ("fullwidth-latin-digits", "ＡＢＣ１２３"),
    ("units-percent", "温度是36.5℃，比例50%，网址 https://example.com/a_b。"),
    ("code-identifier", "把test_file.py改成main.py"),
    ("authored-spaces-kept", "在 Python 中 使用 GPU 加速"),
    ("mid-ellipsis", "他沉默了……然后走了。"),
    ("middle-dot-name", "乔治·华盛顿"),
    ("ascii-punct-after-han", "你好,世界.OK!"),
    # Chinese lexical items an English filter list must not touch.
    ("zh-filler-char", "嗯，我觉得这个很好。"),
    ("zh-filler-bare", "呃我们开始吧"),
    ("zh-triple-repeat", "我觉得我觉得我觉得很好"),
    ("zh-reduplication", "然后然后然后"),
    ("zh-trigger-lookalike", "我说不用了算了"),
    ("zh-two-gram-repeat", "重复重复 重复重复"),
    ("latin-in-han-untouched", "测试uh测试"),
]


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("name,text", _IDENTITY, ids=[n for n, _ in _IDENTITY])
def test_han_text_reaches_the_injector_unchanged(language, name, text):
    # `en` is the shipped default: a Chinese user who has not yet switched language must
    # not see a different pipeline from one who has.
    assert _dictate(language, text) == [text]


# --- findings: current behaviour corrupts the text; xfail(strict) until fixed -----------------

_FINDING = "#501 COMP-02 finding — see design/chinese/postprocess-compatibility.md"


@pytest.mark.xfail(strict=True, reason=_FINDING + ": F1 continuation spacing between Han bursts")
def test_second_han_burst_gets_no_inserted_space():
    # `continuation_prefix` prepends " " to any burst that is not closing punctuation. The
    # space is right between two English words and wrong between two Han clauses.
    assert _dictate("zh", "你好，世界。", "今天测试。") == ["你好，世界。", "今天测试。"]


@pytest.mark.xfail(strict=True, reason=_FINDING + ": F2 full-width closer not in the no-space set")
def test_burst_opening_with_a_fullwidth_comma_hugs_the_previous_text():
    # The ASCII comma is in `_NO_LEADING_SPACE_BEFORE`; U+FF0C is not, so it is typed " ，".
    assert _dictate("zh", "你好", "，然后") == ["你好", "，然后"]


@pytest.mark.xfail(strict=True, reason=_FINDING + ": F3 ASCII-only comma consumption in Rule A")
def test_english_filler_before_a_fullwidth_comma_leaves_no_orphan():
    # "Uh, let's go" -> "let's go" in English; the full-width comma is left stranded.
    assert _dictate("zh", "Uh，我们开始吧") == ["我们开始吧"]


@pytest.mark.xfail(strict=True, reason=_FINDING + ": F3 ASCII-only comma consumption in Rule A")
def test_english_filler_between_fullwidth_commas_leaves_one_comma():
    assert _dictate("zh", "我觉得，um，很好") == ["我觉得，很好"]


@pytest.mark.xfail(strict=True, reason=_FINDING + ": F4 self-correction boundary is ASCII '. '")
def test_english_correction_phrase_keeps_the_previous_han_sentence():
    # English: "I am busy. Scratch that I am free" keeps "I am busy." (boundary '. ').
    # The full-width stop '。' is not a boundary, so the whole prior sentence is discarded.
    assert _dictate("zh", "我今天很忙。 scratch that 我很闲") == ["我今天很忙。 我很闲"]


# --- opt-in Hallucination Guard (off by default; fixed here) ----------------------------------

_GUARD = HallucinationConfig(enabled=True)


@pytest.mark.parametrize(
    "text",
    ["我们 thanks for watching 然后", "好的 please subscribe 谢谢", "我们 no no no no no 然后"],
    ids=["ghost-in-han", "ghost-in-han-2", "loop-in-han"],
)
def test_guard_does_not_judge_han_text_by_its_latin_remainder(text):
    assert drop_reason(text, _GUARD) is None


@pytest.mark.parametrize(
    "text,rule",
    [("Thanks for watching", "ghost_phrase"), ("no no no no no no", "repetition_loop")],
    ids=["ghost", "loop"],
)
def test_guard_still_drops_english_ghosts(text, rule):
    # The Han carve-out must not weaken the English behaviour it sits beside.
    assert drop_reason(text, _GUARD) == rule


# --- the STT segment join (first text step of the live path) ---------------------------------


class _Seg:
    def __init__(self, text):
        self.text = text
        self.words = []


class _FakeWhisper:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, audio, **kwargs):
        return iter(self._segments), None


def _engine(monkeypatch, segments, language="zh"):
    from yazses.stt import faster_whisper as fw

    monkeypatch.setattr(fw, "_load_model", lambda *a, **k: _FakeWhisper(segments))
    return fw.FasterWhisperEngine(model_name="small", language=language)


@needs_faster_whisper
def test_english_segments_are_joined_with_one_space(monkeypatch):
    eng = _engine(monkeypatch, [_Seg(" Hello there."), _Seg(" General Kenobi.")], "en")
    assert eng.transcribe(np.ones(10, dtype="float32")) == "Hello there. General Kenobi."


@needs_faster_whisper
@pytest.mark.xfail(strict=True, reason=_FINDING + ": F5 segments joined with ' ' regardless of script")
def test_han_segments_are_not_joined_with_a_space(monkeypatch):
    eng = _engine(monkeypatch, [_Seg("你好，世界。"), _Seg("今天测试。")])
    assert eng.transcribe(np.ones(10, dtype="float32")) == "你好，世界。今天测试。"


# --- COMP-03: `yazses transcribe` applies [stt] chinese_script -------------------------------


class _Opencc:
    """Stand-in for OpenCC: t2s by a two-character table, so no dictionary is needed."""

    def __init__(self, conf):
        self.conf = conf

    def convert(self, text):
        return text.replace("測試", "测试").replace("體", "体")


class _CaptureEngine:
    built: list = []

    def __init__(self, *a, **k):
        type(self).built.append(k)

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "你好，世界。今天測試", []


def _run_transcribe(tmp_path, monkeypatch, script):
    from typer.testing import CliRunner

    from yazses import cli

    cfg = Config()
    cfg.stt.chinese_script = script
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.stt.faster_whisper.FasterWhisperEngine", _CaptureEngine)
    monkeypatch.setitem(sys.modules, "opencc", types.SimpleNamespace(OpenCC=_Opencc))
    rng = np.random.default_rng(0)
    monkeypatch.setattr(
        "yazses.recimport.audio_io.load_audio",
        lambda *_a, **_k: ((rng.standard_normal(16000) * 1e-2).astype("float32"), 16000),
    )
    monkeypatch.setattr("yazses.recimport.pipeline.build_diarizer", lambda *_a, **_k: None)
    _CaptureEngine.built.clear()
    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF")
    r = CliRunner().invoke(
        cli.app,
        ["transcribe", str(f), "--no-diarize", "--model", "small", "--language", "zh"],
        env={"COLUMNS": "220", "TERM": "dumb"},
    )
    assert r.exit_code == 0, r.output
    return f.with_suffix(".txt").read_text(encoding="utf-8").strip()


@needs_faster_whisper
def test_transcribe_converts_to_the_configured_script(tmp_path, monkeypatch):
    assert _run_transcribe(tmp_path, monkeypatch, "simplified") == "你好，世界。今天测试"


@needs_faster_whisper
def test_transcribe_leaves_the_script_alone_when_unset(tmp_path, monkeypatch):
    assert _run_transcribe(tmp_path, monkeypatch, "") == "你好，世界。今天測試"


@needs_faster_whisper
def test_transcribe_passes_the_language_to_the_decoder(tmp_path, monkeypatch):
    _run_transcribe(tmp_path, monkeypatch, "")
    assert _CaptureEngine.built[-1]["language"] == "zh"
