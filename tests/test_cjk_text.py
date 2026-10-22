"""Pure script-aware text helpers for unspaced CJK text (#501, ``postprocess/cjk.py``).

Two kinds of test. Example tests pin what a seam, a width or a break looks like in
realistic Mandarin and mixed Han/Latin prose (all synthetic, written for this file).
Property tests pin the promise every caller relies on: **for text with no CJK in it,
each helper returns exactly what the whitespace-only code returned**, so the English
pipeline cannot move.
"""
from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from yazses.postprocess.cjk import (
    break_units,
    contains_cjk,
    display_width,
    glue_word_tokens,
    is_cjk_punct,
    is_han,
    is_unspaced_letter,
    join_pieces,
    needs_space,
    render_units,
)
from yazses.postprocess.spacing import continuation_prefix

# --- character classes ---------------------------------------------------------------


@pytest.mark.parametrize("ch", ["你", "測", "〇", "\U00020bb7", "\U00030000"])
def test_han_includes_the_astral_extensions(ch):
    assert is_unspaced_letter(ch)


def test_astral_ideograph_is_han():
    # A BMP-only range check called 𠮷 "not Chinese".
    assert is_han("\U00020bb7")


@pytest.mark.parametrize("ch", ["，", "。", "、", "；", "：", "！", "？", "「", "」", "《", "》", "（", "）", "　"])
def test_fullwidth_marks_are_cjk_punctuation(ch):
    assert is_cjk_punct(ch)


@pytest.mark.parametrize("ch", ["a", "Z", "1", ",", ".", "é", "ß", "س", "“", "…", "🙂", " "])
def test_latin_persian_emoji_and_shared_punctuation_are_not_cjk(ch):
    assert not contains_cjk(ch)


# --- seams -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "left,right,space",
    [
        ("你好，世界。", "今天测试。", False),   # after a full-width stop
        ("世界", "今天", False),                 # Han-Han
        ("测试", "，然后", False),              # before a full-width comma
        ("他说", "“你好”", False),     # Han then a curly quote
        ("”", "然后", False),               # curly quote then Han
        ("测试", "YazSes", True),                # Han-Latin keeps its space
        ("YazSes", "很好", True),
        ("版本", "v2.0", True),
        ("日本", "ありがとう", False),           # Han-kana
        ("hello", "world", True),                # English: always
        ("well", ",", True),                     # English: unchanged (the caller decides)
    ],
)
def test_needs_space(left, right, space):
    assert needs_space(left, right) is space


def test_join_pieces_mandarin_segments():
    assert join_pieces(["你好，世界。", "今天测试 YazSes 123。"]) == "你好，世界。今天测试 YazSes 123。"


def test_join_pieces_mixed_words_from_a_mandarin_decode():
    words = ["版本", "v2.0，", "文件", "test.py，", "编号", "12345。"]
    assert join_pieces(words) == "版本 v2.0，文件 test.py，编号 12345。"


def test_join_pieces_skips_empty_segments_inside_mandarin():
    assert join_pieces(["你好。", "", "再见。"]) == "你好。再见。"


# --- display width and line-break units ---------------------------------------------


def test_display_width_counts_han_as_two_columns():
    assert display_width("你好") == 4
    assert display_width("你好 ok") == 7
    assert display_width("ＡＢＣ") == 6


def test_break_units_split_han_but_keep_latin_words_whole():
    units = break_units("我用Python写了脚本。")
    assert [u for _, u in units] == ["我", "用", "Python", "写", "了", "脚", "本。"]
    assert render_units(units) == "我用Python写了脚本。"


def test_break_units_never_start_a_line_with_a_closer_or_end_one_with_an_opener():
    units = [u for _, u in break_units("他说：「你好！」然后走了。")]
    closers = set("，。、；：！？」』》）")
    assert not any(u[0] in closers for u in units[1:])
    assert not any(u[-1] in "「『《（" for u in units)
    assert render_units(break_units("他说：「你好！」然后走了。")) == "他说：「你好！」然后走了。"


def test_break_units_keep_authored_spaces():
    text = "在 Python 中 使用 GPU 加速"
    assert render_units(break_units(text)) == text


# --- recogniser word tokens ----------------------------------------------------------


def test_glue_word_tokens_rebuilds_a_latin_word_split_in_bpe_pieces():
    # What faster-whisper's code-point split returns for "今天测试 YazSes 123。".
    raws = ["今", "天", "测", "试", " Yaz", "Ses", " 1", "23。"]
    groups = glue_word_tokens(raws)
    words = ["".join(raws[i].strip() for i in g) for g in groups]
    assert words == ["今", "天", "测", "试", "YazSes", "123。"]
    assert join_pieces(words) == "今天测试 YazSes 123。"


def test_glue_word_tokens_keeps_han_characters_separate_and_glues_unspaced_digits():
    raws = ["今", "天", "是", "20", "26", "年", "10", "月"]
    words = ["".join(raws[i].strip() for i in g) for g in glue_word_tokens(raws)]
    # Every seam written without a space comes back without one: a number written
    # against Han glues to it, rather than gaining a space the speaker never had.
    assert join_pieces(words) == "今天是2026年10月"
    assert words == ["今", "天", "是2026年10月"]
    # Two Han characters never merge: each keeps its own timestamp.
    raws = ["我", "们", "开", "会"]
    assert glue_word_tokens(raws) == [[0], [1], [2], [3]]


def test_glue_word_tokens_skips_blank_tokens():
    assert glue_word_tokens(["你", "  ", "好"]) == [[0], [2]]


# --- the English pipeline is unchanged, for every input ------------------------------

_LATIN = st.text(
    alphabet=st.sampled_from(string.ascii_letters + string.digits + " .,!?;:'\"()-%…éßñøçü“”سلام🙂‌"),
    max_size=40,
)


@settings(max_examples=300, deadline=None)
@given(st.lists(_LATIN, max_size=8))
def test_join_pieces_is_space_join_without_cjk(pieces):
    assert join_pieces(pieces) == " ".join(pieces)


@settings(max_examples=300, deadline=None)
@given(_LATIN)
def test_width_and_units_are_len_and_split_without_cjk(text):
    assert display_width(text) == len(text)
    assert [u for _, u in break_units(text)] == text.split()
    assert render_units(break_units(text)) == " ".join(text.split())


@settings(max_examples=300, deadline=None)
@given(_LATIN, _LATIN, st.booleans())
def test_previous_tail_never_changes_a_non_cjk_seam(text, previous, recent):
    before = continuation_prefix(text, had_recent_injection=recent)
    assert continuation_prefix(text, had_recent_injection=recent, previous_tail=previous) == before
