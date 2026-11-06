"""Synthetic mixed-script (Persian+English, Han+ASCII) vectors through the default pipeline.

All text is synthetic, written for this file. These are text-only regression vectors: they
show the shipped-default dictation pipeline does not lose, reorder or rewrite characters
(ZWNJ, bidi marks, version strings, file names). They are NOT evidence of recognition
quality or of code-switch support. Complements ``test_cjk_pipeline_vectors`` and
``test_persian_pipeline_preservation``, which do not exercise bidi controls or
Persian/Han text mixed with versions and file names.
"""
from __future__ import annotations

import pytest

from tests.test_cjk_pipeline_vectors import _dictate

ZWNJ = "‌"
LRM = "‎"
RLM = "‏"
LRI, RLI, PDI = "⁦", "⁧", "⁩"

_FA = [
    ("fa-product-version", "من از YazSes نسخه v2.49.0 استفاده می‌کنم."),
    ("fa-filename", "فایل config.toml را در notes_2026.md ذخیره کن."),
    ("fa-english-clause", "او گفت: this is a test of the system، و من رفتم."),
    ("fa-zwnj-next-to-latin", f"می{ZWNJ}خواهم Python{ZWNJ}نویسی یاد بگیرم."),
    ("fa-rlm-after-latin", f"نسخه Docker{RLM} را نصب کن."),
    ("fa-lrm-around-version", f"نسخه {LRM}v2.49.0{LRM} آمد."),
    ("fa-isolates", f"برنامه {LRI}YazSes 2.49{PDI} و {RLI}کتاب‌ها{PDI} آماده است."),
    ("fa-url-and-email", "به https://example.com/fa/v2.49.0 یا a.b@example.com بنویس."),
]

_ZH = [
    ("zh-version", "版本 v2.49.0 已经发布。"),
    ("zh-filename", "打开 config.toml 和 notes_2026.md 文件。"),
    ("zh-han-ascii-numbers", "我有3个GPU，共48GB显存，版本2.49.0。"),
    ("zh-lrm", f"版本{LRM}v2.49.0{LRM}发布了。"),
    ("zh-zwnj", f"测试{ZWNJ}YazSes{ZWNJ}通过。"),
    ("zh-english-clause", "他说 this is fine 然后走了。"),
]


@pytest.mark.parametrize("language", ["fa", "en"])
@pytest.mark.parametrize("name,text", _FA, ids=[n for n, _ in _FA])
def test_persian_mixed_text_reaches_the_injector_unchanged(language, name, text):
    assert _dictate(language, text) == [text]


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("name,text", _ZH, ids=[n for n, _ in _ZH])
def test_han_mixed_text_reaches_the_injector_unchanged(language, name, text):
    assert _dictate(language, text) == [text]


@pytest.mark.parametrize("name,text", _FA + _ZH, ids=[n for n, _ in _FA + _ZH])
def test_no_control_character_is_lost(name, text):
    out = "".join(_dictate("fa" if name.startswith("fa") else "zh", text))
    for ch in (ZWNJ, LRM, RLM, LRI, RLI, PDI):
        assert out.count(ch) == text.count(ch), (name, hex(ord(ch)))


def test_second_persian_burst_after_latin_keeps_exactly_one_space():
    assert _dictate("fa", "نسخه v2.49.0", "منتشر شد.") == ["نسخه v2.49.0", " منتشر شد."]
