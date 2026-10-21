"""Chinese Han-script normalisation (`[stt] chinese_script`).

The pure parts (alias resolution, the Han fast path, the engine wrapper) are
tested without opencc so they run on every CI machine; the conversions
themselves are skipped when the optional `chinese` extra is absent.
"""
from __future__ import annotations

import dataclasses
import functools
import importlib.util

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.config import SttConfig
from yazses.postprocess.cjk import is_han
from yazses.postprocess.han_script import (
    SIMPLIFIED,
    TRADITIONAL,
    build_han_normaliser,
    contains_han,
    resolve_script,
)

needs_opencc = pytest.mark.skipif(
    importlib.util.find_spec("opencc") is None,
    reason="the optional `chinese` extra (opencc) is not installed",
)


@pytest.mark.parametrize(
    "value",
    ["simplified", "Simplified", " SIMP ", "hans", "zh-Hans", "zh_hans", "zh-CN", "cn"],
)
def test_simplified_aliases_resolve(value):
    assert resolve_script(value) == SIMPLIFIED


@pytest.mark.parametrize(
    "value", ["traditional", "trad", "hant", "zh-Hant", "zh-TW", "zh-HK", "tw"]
)
def test_traditional_aliases_resolve(value):
    assert resolve_script(value) == TRADITIONAL


@pytest.mark.parametrize("value", ["", None, "off", "none", "auto", "false", "  "])
def test_disabled_values_resolve_to_off(value):
    assert resolve_script(value) == ""


def test_unknown_value_disables_rather_than_raising(caplog):
    """No config value may stop the daemon starting (config.py's total-load rule)."""
    assert resolve_script("pinyin") == ""
    assert "not recognised" in caplog.text


def test_contains_han_detects_chinese():
    assert contains_han("你好")
    assert contains_han("hello 世界")


def test_contains_han_is_false_for_plain_english():
    assert not contains_han("hello world")
    assert not contains_han("")
    assert not contains_han("123 !?")


def test_normaliser_is_none_when_disabled():
    assert build_han_normaliser(SttConfig()) is None


def test_normaliser_is_none_for_unknown_script():
    assert build_han_normaliser(SttConfig(chinese_script="klingon")) is None


@needs_opencc
def test_converts_traditional_to_simplified():
    normalise = build_han_normaliser(SttConfig(chinese_script="simplified"))
    # The exact failure measured on ASCEND: correct recognition, wrong script.
    assert normalise("但是我們的房租就到了") == "但是我们的房租就到了"


@needs_opencc
def test_converts_simplified_to_traditional():
    normalise = build_han_normaliser(SttConfig(chinese_script="traditional"))
    assert normalise("但是我们的房租就到了") == "但是我們的房租就到了"


@needs_opencc
def test_english_text_is_untouched():
    normalise = build_han_normaliser(SttConfig(chinese_script="simplified"))
    text = "hold a key, speak, release"
    assert normalise(text) is text  # fast path returns the same object


@needs_opencc
def test_already_simplified_text_is_unchanged():
    normalise = build_han_normaliser(SttConfig(chinese_script="simplified"))
    assert normalise("你好世界") == "你好世界"


# --- the engine wrapper -------------------------------------------------------


@dataclasses.dataclass
class _FakeWord:
    text: str
    start: float = 0.0
    end: float = 1.0
    probability: float = 0.9


class _FakeEngine:
    """Minimal SttEngine stand-in that returns fixed Traditional output."""

    name = "fake"

    def __init__(self, text="但是我們的房租就到了"):
        self.text = text
        self.calls = []

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        self.calls.append(("transcribe", initial_prompt, task))
        return self.text

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None,
                         task=None):
        return self.text, [_FakeWord("房租"), _FakeWord("到了")]

    def decode_window(self, audio):
        return self.text


def _wrap(script="simplified", inner=None):
    from yazses.stt.factory import _with_han_script

    return _with_han_script(inner or _FakeEngine(), SttConfig(chinese_script=script))


def test_wrapper_absent_when_feature_off():
    inner = _FakeEngine()
    assert _wrap("", inner) is inner


@needs_opencc
def test_wrapper_converts_transcribe():
    assert _wrap().transcribe(None) == "但是我们的房租就到了"


@needs_opencc
def test_wrapper_converts_decode_window():
    """Streaming goes through decode_window, so it must convert too."""
    assert _wrap().decode_window(None) == "但是我们的房租就到了"


@needs_opencc
def test_wrapper_converts_each_word_not_just_joined_text():
    """Subtitles and speaker labels re-render from words, not the joined text."""
    text, words = _wrap().transcribe_words(None)
    assert text == "但是我们的房租就到了"
    assert [w.text for w in words] == ["房租", "到了"]


@needs_opencc
def test_wrapper_preserves_word_timestamps():
    _, words = _wrap().transcribe_words(None)
    assert [(w.start, w.end, w.probability) for w in words] == [
        (0.0, 1.0, 0.9), (0.0, 1.0, 0.9)
    ]


@needs_opencc
def test_wrapper_forwards_arguments_to_the_inner_engine():
    inner = _FakeEngine()
    _wrap("simplified", inner).transcribe(None, 16000, "词汇表", "translate")
    assert inner.calls == [("transcribe", "词汇表", "translate")]


@needs_opencc
def test_wrapper_delegates_unknown_attributes():
    assert _wrap().name == "fake"


@needs_opencc
def test_english_only_model_warns_that_the_setting_cannot_do_anything(caplog):
    """`features enable chinese-script` does not touch [stt] model, so the
    default landing spot is chinese_script + base.en — a silent no-op."""
    from yazses.stt.factory import _with_han_script

    with caplog.at_level("WARNING"):
        _with_han_script(
            _FakeEngine(), SttConfig(model="base.en", chinese_script="simplified")
        )
    assert "English-only" in caplog.text
    assert "base" in caplog.text  # names the fix


@needs_opencc
def test_multilingual_model_does_not_warn(caplog):
    from yazses.stt.factory import _with_han_script

    with caplog.at_level("WARNING"):
        _with_han_script(
            _FakeEngine(), SttConfig(model="small", chinese_script="simplified")
        )
    assert "English-only" not in caplog.text


def test_no_warning_when_the_feature_is_off(caplog):
    """A default install must not be nagged about a feature it never enabled."""
    from yazses.stt.factory import _with_han_script

    with caplog.at_level("WARNING"):
        _with_han_script(_FakeEngine(), SttConfig(model="base.en"))
    assert "chinese_script" not in caplog.text


# --- mixed Han / ASCII / punctuation vectors (#501) -----------------------------
#
# Script conversion is meant to touch Han characters and nothing else. Dictated
# Mandarin is full of things it must leave alone: product names, file names, version
# strings, numbers, URLs, and the full-width punctuation the recogniser chose. The
# normaliser hands the whole string to OpenCC, so these pin what OpenCC actually does
# to those neighbours, in both directions. Synthetic text written for this file.

# (Traditional, Simplified): each converts to the other, and every non-Han character
# is identical on both sides.
_MIXED_PAIRS = [
    ("我們用YazSes v2.43.1發佈了", "我们用YazSes v2.43.1发布了"),
    ("請打開config.toml檔案，然後輸入123。", "请打开config.toml档案，然后输入123。"),
    ("請執行 uv sync 然後 pytest -q", "请执行 uv sync 然后 pytest -q"),
    ("「這是測試」……對嗎？", "「这是测试」……对吗？"),
    ("《紅樓夢》（第1卷）：開始！", "《红楼梦》（第1卷）：开始！"),
    ("網址是 https://example.com/a_b?x=1 。", "网址是 https://example.com/a_b?x=1 。"),
    ("溫度-5.5度，增長12.5%", "温度-5.5度，增长12.5%"),
    ("編號１２３４５，ＡＢＣ", "编号１２３４５，ＡＢＣ"),
    ("x86_64和arm64都支援", "x86_64和arm64都支援"),
    ("API_KEY=abc 我們", "API_KEY=abc 我们"),
    ("他說“你好”", "他说“你好”"),
    ("時間　到了", "时间　到了"),
]


@needs_opencc
@pytest.mark.parametrize(("traditional", "simplified"), _MIXED_PAIRS)
def test_to_simplified_rewrites_only_the_han_characters(traditional, simplified):
    normalise = build_han_normaliser(SttConfig(chinese_script="simplified"))
    assert normalise(traditional) == simplified


@needs_opencc
@pytest.mark.parametrize(("traditional", "simplified"), _MIXED_PAIRS)
def test_to_traditional_rewrites_only_the_han_characters(traditional, simplified):
    # Not every pair round-trips (支援 stays 支援; s2t is not t2s's inverse), so the
    # assertion is on the non-Han characters, which is what this section is about.
    normalise = build_han_normaliser(SttConfig(chinese_script="traditional"))
    out = normalise(simplified)
    assert [c for c in out if not is_han(c)] == [c for c in simplified if not is_han(c)]


@pytest.mark.parametrize(
    "text",
    [
        "YazSes v2.43.1",
        "config.toml, 12.5%, -5",
        "，。！？、；：「」《》（）……",  # CJK punctuation alone holds no Han
        "ＡＢＣ１２３",  # full-width Latin and digits are not Han
        "ありがとう",  # kana is not Han
        "https://example.com/?q=1",
    ],
)
def test_contains_han_is_false_without_an_ideograph(text):
    """No Han means the converter is never called -- the fast path holds for these."""
    assert not contains_han(text)


@pytest.mark.parametrize("text", ["v2.43 版本", "，好。", "𠮷", "ＡＢＣ中"])
def test_contains_han_finds_one_ideograph_among_anything(text):
    assert contains_han(text)


@needs_opencc
@pytest.mark.parametrize("script", [SIMPLIFIED, TRADITIONAL])
@pytest.mark.parametrize("text", ["YazSes v2.43.1", "，。！？「」", "ＡＢＣ１２３", "ありがとう"])
def test_text_without_han_is_returned_as_the_same_object(script, text):
    normalise = build_han_normaliser(SttConfig(chinese_script=script))
    assert normalise(text) is text


@needs_opencc
def test_wrapper_leaves_ascii_word_tokens_alone():
    """Word tokens are converted one by one; an ASCII or numeric token must not move."""
    inner = _FakeEngine()
    inner.transcribe_words = lambda *a, **k: (  # type: ignore[method-assign]
        "我們用 YazSes 2.43 發佈了",
        [_FakeWord("我們"), _FakeWord("YazSes"), _FakeWord("2.43"), _FakeWord("發佈了")],
    )
    text, words = _wrap("simplified", inner).transcribe_words(None)
    assert text == "我们用 YazSes 2.43 发布了"
    assert [w.text for w in words] == ["我们", "YazSes", "2.43", "发布了"]


@functools.cache
def _normaliser(script: str):
    return build_han_normaliser(SttConfig(chinese_script=script))


_MIXED_TEXT = st.text(
    alphabet=st.sampled_from(
        [
            *"我們们發发佈布測测試试網网開开後后這这說说𠮷",
            *"YazSesv0123456789._-/:%=?@",
            *"，。！？、；：「」『』《》（）…“”",
            *"ＡＢＣ１２３",
            " ",
            "　",
        ]
    ),
    max_size=40,
)


@needs_opencc
@pytest.mark.parametrize("script", [SIMPLIFIED, TRADITIONAL])
@given(text=_MIXED_TEXT)
def test_non_han_characters_survive_conversion_in_order(script, text):
    out = _normaliser(script)(text)
    assert [c for c in out if not is_han(c)] == [c for c in text if not is_han(c)]
