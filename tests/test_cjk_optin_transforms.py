"""Opt-in text transforms leave Mandarin alone (#501 COMP-01/02).

``tests/test_cjk_pipeline_vectors.py`` drives the *default-on* chain. The transforms
below ship off (AGENTS.md rule 2), so a Mandarin user meets them only after turning one
on. ``design/chinese/postprocess-compatibility.md`` §2 used to list them as "classified
from code, not run"; this file runs each over the issue's test strings and the CJK
identity vectors and pins the result: none of them inserts, deletes or rewrites a
character of Han text.

Spoken punctuation (``postprocess/voice_punctuation.py``) is deliberately not pinned
here; its Mandarin behaviour is recorded in the compatibility audit instead.

All text is synthetic and written for this file.
"""
from __future__ import annotations

from datetime import datetime

import pytest

_VECTORS = [
    "你好，世界。今天测试 YazSes 123。",
    "你好，世界。今天測試 YazSes 123。",
    "版本 v2.0，文件 test.py，编号 12345。",
    "我用Python写了一个脚本。",
    "今天是2026年10月15日",
    "他说：“你好！”",
    "价格是￥100.50元（含税）",
    "「引用」和『书名』《红楼梦》",
    "温度是36.5℃，比例50%，网址 https://example.com/a_b。",
    "在 Python 中 使用 GPU 加速",
    "苹果、香蕉、橙子；还有梨？",
    "他沉默了……然后走了。",
]


def _itn(text):
    from yazses.itn.normalize import normalize_entities

    return normalize_entities(text)


def _symbols(text):
    from yazses.symbols.lookup import apply_symbols

    return apply_symbols(text)


def _convert(text):
    from yazses.convert.units import apply_conversions

    return apply_conversions(text)


def _temporal(text):
    from yazses.temporal.resolve import resolve_temporal

    return resolve_temporal(text, datetime(2026, 10, 15, 9, 30))


def _gec(text):
    from yazses.gec.guard import fix_articles

    return fix_articles(text)


def _diacritize(text):
    from yazses.diacritize.restore import restore_diacritics

    return restore_diacritics(text)


def _sembr(text):
    from yazses.sembr.breaks import semantic_breaks

    return semantic_breaks(text)


def _autopair(text):
    from yazses.autopair.balance import balance_delimiters

    return balance_delimiters(text)


def _selfrepair(text):
    from yazses.selfrepair.repair import apply_self_repair

    return apply_self_repair(text)


_TRANSFORMS = [
    ("itn", _itn),
    ("symbols", _symbols),
    ("convert", _convert),
    ("temporal", _temporal),
    ("gec", _gec),
    ("diacritize", _diacritize),
    ("sembr", _sembr),
    ("autopair", _autopair),
    ("selfrepair", _selfrepair),
]


@pytest.mark.parametrize("name,transform", _TRANSFORMS, ids=[n for n, _ in _TRANSFORMS])
@pytest.mark.parametrize("text", _VECTORS)
def test_optin_transform_leaves_han_text_unchanged(name, transform, text):
    assert transform(text) == text


_VOCAB = ["YazSes", "Kubernetes", "PyTorch", "测试"]


@pytest.mark.parametrize("text", _VECTORS)
def test_vocabulary_correction_leaves_han_text_unchanged(text):
    from yazses.postprocess.vocab_correct import correct

    assert correct(text, _VOCAB) == (text, [])


def test_vocabulary_correction_fixes_a_spaced_latin_term_inside_han():
    from yazses.postprocess.vocab_correct import correct

    assert correct("我用 PyTorc 训练", _VOCAB)[0] == "我用 PyTorch 训练"


def test_vocabulary_correction_does_not_reach_a_latin_term_glued_to_han():
    # Whitespace tokens: `我用Kubernets部署。` is one token, so the misspelling is left
    # alone. A miss, not a corruption -- recorded in the compatibility audit.
    from yazses.postprocess.vocab_correct import correct

    assert correct("我用Kubernets部署。", _VOCAB) == ("我用Kubernets部署。", [])
