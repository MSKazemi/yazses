import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.audio.vad import is_silent
from yazses.postprocess.cjk import is_han
from yazses.postprocess.cleaner import clean_text

# --- text cleaner ---

def test_strips_leading_trailing_whitespace():
    assert clean_text("  hello world  ") == "hello world"


def test_removes_blank_audio_artefact():
    assert clean_text("[BLANK_AUDIO]") == ""


def test_removes_leading_ellipsis():
    assert clean_text("... hello") == "hello"


def test_removes_leading_period():
    assert clean_text(". hello") == "hello"


def test_empty_string_returns_empty():
    assert clean_text("") == ""


def test_normal_text_is_unchanged():
    assert clean_text("Hello, how are you?") == "Hello, how are you?"


def test_strips_whitespace_around_artefact():
    assert clean_text("  [BLANK_AUDIO]  ") == ""


# --- CJK: Han text, ASCII names, numbers, Chinese punctuation (#501) ---
#
# `clean_text` runs on every dictation burst and every imported-file utterance, before
# anything else sees the text. Its whole job is the edges: surrounding whitespace, a
# whole-burst blank marker, and a leading run of ASCII "." / U+2026 (Whisper artefacts).
# Mandarin would break here if an English-oriented rule were ever added -- collapsing
# "extra" spaces, dropping a space before punctuation, stripping a leading mark -- so
# these pin that everything between the edges arrives exactly as the recogniser wrote
# it. Synthetic text written for this file; no recorded speech.
#
# A leading 。 or ， is deliberately NOT stripped (contract vector
# `mandarin-leading-fullwidth-stop-kept` in scripts/gen-contract-vectors.py):
# only ASCII "." and U+2026 are known Whisper artefacts, and removing real punctuation
# is not this unit's job.

_CJK_UNCHANGED = [
    # Han text and full-width punctuation
    "你好，世界。",
    "今天天气很好！你呢？",
    "第一、第二；第三：完成。",
    "他说：「这是测试」。",
    "我读过《三体》和『红楼梦』（两本）。",
    "【通知】明天开会……",
    "我想想……",
    "你好...世界",
    # Traditional characters and an astral (extension B) ideograph
    "我們今天測試。",
    "𠮷野家的牛肉饭很好吃。",
    # ASCII names and identifiers inside Han text -- the spaces are the recogniser's
    "今天测试 YazSes 的效果。",
    "我们用YazSes测试。",
    "请打开 config.toml 文件，然后运行 uv sync。",
    "用 Python 3.12 和 C++ 写的。",
    "联系 user@example.com 或者看 /usr/local/bin。",
    # Numbers: dates, decimals, percentages, signs, full-width digits
    "2026年10月21日下午3点开会。",
    "圆周率是3.14159。",
    "增长了12.5%，比去年高。",
    "温度是-5度。",
    "版本 v2.43.1 已经发布。",
    "编号１２３４５。",
    "3.14是圆周率。",
    # Interior whitespace, including the ideographic space U+3000, is kept as written
    "你好　世界",
    "你好  世界",
]


@pytest.mark.parametrize("text", _CJK_UNCHANGED)
def test_cjk_text_is_unchanged(text):
    assert clean_text(text) == text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  你好，世界。  ", "你好，世界。"),
        ("　你好　", "你好"),  # the ideographic space is whitespace too
        ("\n今天测试 YazSes。\t", "今天测试 YazSes。"),
        ("...你好", "你好"),  # the ASCII leading-ellipsis artefact
        ("……你好", "你好"),  # two U+2026, the Chinese ellipsis
        ("… 你好", "你好"),
        (". 2026年开始", "2026年开始"),
    ],
)
def test_cjk_edges_are_cleaned_and_nothing_else(raw, expected):
    assert clean_text(raw) == expected


@pytest.mark.parametrize("text", ["。然后我们继续", "，然后呢", "、第二点"])
def test_leading_cjk_punctuation_is_not_treated_as_an_artefact(text):
    assert clean_text(text) == text


# The characters those vectors mix: Han (including Traditional and an astral
# ideograph), ASCII letters, digits and ".", the marks a Mandarin decode emits, and
# both kinds of space.
_MIXED = st.text(
    alphabet=st.sampled_from(
        [*"你好世界今天测试我們發佈𠮷", *"YazSesv0123.", *"，。！？、；：「」《》（）…", " ", "　"]
    ),
    max_size=40,
)


@given(_MIXED)
def test_the_han_span_survives_byte_for_byte(text):
    """Whatever the edges hold, the text from the first to the last Han character is kept.

    So the cleaner cannot delete, insert, reorder or re-space anything inside a Mandarin
    sentence -- only trim around it.
    """
    positions = [i for i, ch in enumerate(text) if is_han(ch)]
    if not positions:
        return
    span = text[positions[0] : positions[-1] + 1]
    assert span in clean_text(text)


# --- VAD ---

def test_silence_detected_for_near_zero_audio():
    audio = np.zeros(16000, dtype="float32")
    assert is_silent(audio) is True


def test_speech_not_silent():
    rng = np.random.default_rng(42)
    audio = rng.uniform(-0.5, 0.5, 16000).astype("float32")
    assert is_silent(audio) is False


def test_empty_audio_is_silent():
    assert is_silent(np.array([], dtype="float32")) is True
