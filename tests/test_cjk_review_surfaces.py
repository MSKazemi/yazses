"""Opt-in review, correction and counting surfaces keep Mandarin intact (#501).

``test_cjk_pipeline_vectors.py`` drives the default-on chain and
``test_cjk_optin_transforms.py`` the transforms that leave Han text alone. This file covers
the opt-in features that did not: staged dictation added a space between two Chinese
bursts, Punch-In treated a Chinese clause as one word, the two pause-driven formatters
attached pauses to the wrong place, and every "N words" count saw a sentence as one word.

Each fix is inert for text with no CJK in it. All text is synthetic and written for this
file; no model, audio or desktop is involved.
"""
from __future__ import annotations

import string
from dataclasses import replace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config, StagedConfig
from yazses.core.daemon import Daemon
from yazses.fieldaware.profile import apply_profile, profile_for_role
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.postprocess.cjk import count_words
from yazses.postprocess.prosody import Word, annotate
from yazses.postprocess.punch_in import apply_top_candidate
from yazses.postprocess.spacing import continuation_prefix
from yazses.prosodypunct.apply import punctuate_text
from yazses.staged.buffer import StagedBuffer, describe, join_chunks
from yazses.wordgoal.tracker import count_words as goal_count_words

#: Latin, Persian, accented text, emoji and every kind of whitespace -- nothing CJK.
_NOT_CJK = st.text(alphabet=string.printable + "éßسلام…“”—🙂 ‌", max_size=60)

# --- counting --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,count",
    [
        ("你好，世界。今天测试 YazSes 123。", 10),      # 8 Han + YazSes + 123
        ("你好，世界。今天測試 YazSes 123。", 10),
        ("版本 v2.0，文件 test.py，编号 12345。", 9),   # 6 Han + v2.0, test.py, 12345
        ("我用Python写代码", 6),                        # a Latin word glued to Han
        ("ＡＢＣ１２３很好", 3),                        # a full-width run is one word
        ("。，！", 0),
        ("𠮷野家", 3),                                  # an astral Han character
        ("", 0),
    ],
)
def test_count_words_counts_han_characters(text, count):
    assert count_words(text) == count
    assert goal_count_words(text) == count


@settings(max_examples=200)
@given(_NOT_CJK)
def test_count_words_is_the_whitespace_count_without_cjk(text):
    assert count_words(text) == len(text.split())


def test_wordgoal_cli_counts_chinese_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_wordgoal_path", lambda: tmp_path / "wordgoal.json")
    result = CliRunner().invoke(cli.app, ["wordgoal", "add", "今天天气很好。"])
    assert result.exit_code == 0, result.output
    assert "6 words so far." in result.output


def test_staged_commit_message_counts_chinese_characters(monkeypatch):
    monkeypatch.setattr(
        cli, "_staged_call", lambda action: {"committed": True, "text": "今天天气很好。"}
    )
    result = CliRunner().invoke(cli.app, ["staged", "commit"])
    assert result.exit_code == 0, result.output
    assert "Committed 6 words." in result.output


# --- staged dictation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "chunks,joined",
    [
        (["你好，世界。", "今天测试。"], "你好，世界。今天测试。"),
        (["你好", "世界"], "你好世界"),
        (["我们开始", "，然后结束"], "我们开始，然后结束"),
        (["他说", "“你好”"], "他说“你好”"),
        (["今天测试", "YazSes"], "今天测试 YazSes"),     # a Han-Latin seam keeps its space
        (["今天测试", " ", "版本"], "今天测试版本"),
    ],
)
def test_staged_chunks_join_as_chinese(chunks, joined):
    assert join_chunks(chunks) == joined


@pytest.mark.parametrize(
    "first,second",
    [("你好。", "今天"), ("测试", "，然后"), ("测试", "YazSes"), ("hello", "world")],
)
def test_staged_join_matches_unstaged_continuation_spacing(first, second):
    typed = first + continuation_prefix(
        second, had_recent_injection=True, previous_tail=first[-1]
    ) + second
    assert join_chunks([first, second]) == typed


@settings(max_examples=200)
@given(st.lists(_NOT_CJK, max_size=4))
def test_staged_join_is_unchanged_without_cjk(chunks):
    expected = ""
    for piece in (c.strip() for c in chunks):
        if not piece:
            continue
        if expected and piece[0] not in ",.;:!?)]}":
            expected += " "
        expected += piece
    assert join_chunks(chunks) == expected


def test_staged_summary_counts_chinese_characters():
    buffer = StagedBuffer()
    buffer.stage("今天天气")
    buffer.stage("很好。")
    summary = describe(buffer)
    assert "6 words" in summary and "2 bursts" in summary


def test_daemon_staged_counts_and_commits_chinese(mocker):
    cfg = replace(Config(), staged=StagedConfig(enabled=True, spoken_commit=True))
    daemon = Daemon(config=cfg, platform=get_platform())
    daemon._notify_staged = mocker.MagicMock()
    event: dict = {}
    daemon._stage_or_commit("今天天气", event)
    assert event["staged_pending_words"] == 4
    daemon._stage_or_commit("很好。", {})
    assert daemon.staged_state()["words"] == 6
    assert daemon._stage_or_commit("commit that", {}) == "今天天气很好。"

    daemon._stage_or_commit("你好", {})
    reply = daemon._handle_staged(
        Request(method="staged", params={"action": "discard"}, id=1)
    )
    assert reply["discarded_words"] == 2


# --- Punch-In --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "burst,respoken,corrected",
    [
        ("今天我们讨论欲算问题。", "讨论预算", "今天我们讨论预算问题。"),
        ("我用 PyTorc 训练模型", "PyTorch", "我用 PyTorch 训练模型"),
    ],
)
def test_punch_in_replaces_part_of_a_chinese_clause(burst, respoken, corrected):
    result, candidates = apply_top_candidate(burst, respoken)
    assert result == corrected
    # The span is part of the clause, never the whole of it.
    assert len(candidates[0].old_text) < len(burst)


def test_daemon_punch_in_retypes_chinese_without_new_spaces():
    class _Injector:
        def __init__(self):
            self.backspaces = 0
            self.injected: list[str] = []

        def inject(self, text):
            self.injected.append(text)

        def inject_backspaces(self, count):
            self.backspaces += count

        def inject_key_sequence(self, keys):
            pass

    cfg = Config()
    cfg.punch_in.enabled = True
    daemon = Daemon(config=cfg, platform=get_platform())
    injector = _Injector()
    daemon._injector = injector
    burst = "今天我们讨论欲算问题。"
    daemon._ledger.record(burst)
    assert daemon._apply_punch_in("讨论预算")["ok"] is True
    assert injector.backspaces == len(burst)
    assert injector.injected == ["今天我们讨论预算问题。"]


# --- pause-driven formatting -------------------------------------------------------------

#: A mixed burst as faster-whisper reports it: one token per Han character, so the second
#: whitespace token of the text ("YazSes") lines up with the second *character*.
_MIXED = "测试 YazSes 版本"
_MIXED_WORDS = [
    Word("测", 0.0, 0.2),
    Word("试", 1.5, 1.7),       # a long gap inside the first Chinese word
    Word("YazSes", 1.7, 2.1),
    Word("版", 2.1, 2.3),
    Word("本", 2.3, 2.5),
]


@pytest.mark.parametrize("text", [_MIXED, "你好，世界。\n今天测试。"])
def test_prosody_ink_leaves_chinese_untouched(text):
    cfg = Config().prosody
    cfg.pause_sentence_ms = 500
    result = annotate(text, np.zeros(1600, dtype="float32"), 16000, _MIXED_WORDS, cfg)
    assert result.text == text
    assert (result.paragraph_breaks, result.emphasized) == (0, 0)


def test_prosodic_punctuation_adds_no_ascii_mark_to_chinese():
    # Counts agree here, so only the script check stops "好. Hello".
    result = punctuate_text("好 hello", [(0.0, 0.3), (1.5, 1.9)])
    assert result.text == "好 hello"
    assert (result.sentences, result.commas) == (0, 0)


# --- field-aware shaping ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,shaped",
    [("打开文件。", "打开文件"), ("天气怎么样？", "天气怎么样"), ("苹果，香蕉、", "苹果，香蕉")],
)
def test_search_field_drops_trailing_fullwidth_punctuation(text, shaped):
    assert apply_profile(text, profile_for_role("searchbox")) == shaped


def test_prose_field_keeps_chinese_punctuation():
    assert apply_profile("打开文件。", profile_for_role("entry")) == "打开文件。"
