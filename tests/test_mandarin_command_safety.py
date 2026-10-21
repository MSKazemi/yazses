"""Mandarin command safety: negative corpus, destructive triggers, review state (#499).

AGENTS.md rule 9: a command path is judged on how rarely it fires on ordinary
speech. The negative corpus is ordinary Mandarin prose that *contains* command
words (删除, 发送, 保存, 复制 …) and must stay dictation; it is measured as a
false-trigger count, and the release criterion (design/chinese/
test-and-validation-plan.md §5.3) is zero. A missed command is typed text; a false
one changes application state, so every near-miss here deliberately falls to
dictation.

All phrases are provisional pending native review (#505); see ``zh.PHRASE_REVIEW``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yazses.commands import edit_ops
from yazses.commands.grammar import IntentType, classify
from yazses.commands.grammars import zh
from yazses.commands.grammars.registry import resolve_command_language
from yazses.config import Config
from yazses.language.profiles import get_profile

FIXTURES = Path(__file__).parent / "fixtures" / "commands"

#: Command-like lexemes per shipped action (Simplified and Traditional). The corpus
#: must exercise each one in ordinary prose, or it cannot show that action is safe.
ACTION_LEXEMES: dict[str, tuple[str, ...]] = {
    "undo": ("撤销", "撤銷", "復原"),
    "undo_n": ("撤销", "撤銷", "復原"),
    "save": ("保存", "儲存", "存檔"),
    "copy": ("复制", "複製"),
    "cut": ("剪切", "剪下"),
    "paste": ("粘贴", "黏貼", "贴上", "貼上"),
    "delete_words": ("删除", "刪除"),
    "delete_lines": ("删除", "刪除"),
    "comment": ("注释", "註釋", "註解"),
    "select_lines": ("选择", "選擇", "选取", "選取"),
    "select_to_end": ("选择到结尾", "選取到結尾", "结尾"),
    "select_all": ("全选", "全選"),
    "press_enter": ("回车", "回車", "换行", "換行", "新的一行"),
    "press_tab": ("Tab", "制表"),
    "press_escape": ("Escape", "esc"),
    "press_backspace": ("退格",),
    "go_to_line": ("转到第", "跳到第", "第一百", "第九百", "行"),
    "page_up": ("上一页", "上一頁"),
    "page_down": ("下一页", "下一頁"),
    "line_home": ("行首",),
    "line_end": ("行尾",),
    "arrow_up": ("光标向上", "游標向上"),
    "arrow_down": ("光标向下", "游標向下", "光标"),
    "arrow_left": ("光标向左", "游標向左", "向左"),
    "arrow_right": ("光标向右", "游標向右", "向右"),
    "go_to_function": ("函数", "函數", "函式"),
    "go_to_class": ("类 ", "類 ", "类别"),
    "go_to_file": ("打开文件", "開啟檔案", "文件"),
}
#: Words with no Mandarin command at all; prose with them must obviously stay prose.
UNREGISTERED_LEXEMES = ("发送", "發送", "运行", "執行")


def _negative_corpus() -> list[str]:
    text = (FIXTURES / "zh_dictation.txt").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def _positive_cases() -> list[dict]:
    return json.loads((FIXTURES / "zh_core.json").read_text(encoding="utf-8"))


def _false_triggers(lines: list[str]) -> list[tuple[str, str, dict]]:
    out = []
    for text in lines:
        got = classify(text, language="zh")
        if got.intent is not IntentType.DICTATE:
            out.append((text, got.action, got.args))
    return out


# --- negative corpus -----------------------------------------------------------


def test_negative_corpus_false_trigger_count_is_zero():
    lines = _negative_corpus()
    assert len(lines) >= 80
    bad = _false_triggers(lines)
    rate = len(bad) / len(lines)
    assert bad == [], f"false-trigger rate {len(bad)}/{len(lines)} = {rate:.1%}: {bad}"


def test_every_negative_line_contains_a_command_like_word():
    """An inert corpus (prose with no command words) would pass vacuously."""
    every = {lex for lexes in ACTION_LEXEMES.values() for lex in lexes}
    every.update(UNREGISTERED_LEXEMES)
    inert = [line for line in _negative_corpus() if not any(lex in line for lex in every)]
    assert inert == []


def test_every_shipped_action_has_a_relevant_negative():
    """CHN-23: each shipped Tier-1 action is represented by a relevant negative."""
    assert set(ACTION_LEXEMES) == set(zh.SAFE_CORE_ACTIONS)
    lines = _negative_corpus()
    missing = [
        action
        for action, lexes in ACTION_LEXEMES.items()
        if not any(lex in line for line in lines for lex in lexes)
    ]
    assert missing == []
    assert sum(any(lex in line for lex in ("发送", "發送")) for line in lines) >= 3


@pytest.mark.parametrize(
    "text",
    [
        "打开文件 config.toml 之后再修改端口",
        "查找函数 main 的定义花了很久",
        "跳到类 Parser 的说明之前先读概述",
        "打开文件夹里的config.toml",
    ],
)
def test_a_navigation_name_cannot_swallow_the_rest_of_a_sentence(text):
    """Regression: an open-ended ``(.+)`` made these go_to_file/function/class."""
    assert classify(text, language="zh").intent is IntentType.DICTATE


def test_no_mandarin_rule_has_an_open_ended_capture():
    for rule in zh.MANDARIN_GRAMMAR.rules:
        source = rule.pattern.pattern
        assert source.startswith("^") and source.endswith("$"), source
        assert "(.+)" not in source and "(.*)" not in source, source


# --- destructive commands ------------------------------------------------------


def test_destructive_rules_require_the_checkable_delete_last_prefix():
    destructive = [r for r in zh.MANDARIN_GRAMMAR.rules if r.action in zh.DESTRUCTIVE_ACTIONS]
    assert {r.action for r in destructive} == zh.DESTRUCTIVE_ACTIONS
    for rule in destructive:
        source = rule.pattern.pattern
        assert source.startswith(zh.DESTRUCTIVE_TRIGGER_PREFIX), source
        assert source.endswith(("词|詞|单词|單詞)$", "行$")), source
        if rule.arg_names:
            assert f"({zh._COUNT})" in source, "destructive counts stay capped at 99"


def test_every_text_removing_action_in_the_mandarin_grammar_is_declared_destructive():
    shipped = set(zh.SAFE_CORE_ACTIONS)
    assert edit_ops.DESTRUCTIVE & shipped <= zh.DESTRUCTIVE_ACTIONS
    deletes = {r.action for r in zh.MANDARIN_GRAMMAR.rules if "删除" in r.pattern.pattern}
    assert deletes == zh.DESTRUCTIVE_ACTIONS


@pytest.mark.parametrize(
    "text",
    [
        "删除",
        "刪除",
        "删除最后",
        "删除这一行",
        "删除这个",
        "删除所有内容",
        "全部删除",
        "删除最后一段",
        "删除最后一句",
        "删除文件",
        "删除最后一百行",
        "删除最后两百个词",
        "请删除最后一行",
        "删除最后一行吧",
        "发送",
        "发送邮件",
        "發送訊息",
    ],
)
def test_destructive_and_send_near_misses_stay_dictation(text):
    got = classify(text, language="zh")
    assert got.intent is IntentType.DICTATE
    assert got.action == "inject"


# --- positive coverage, parity and opt-in ----------------------------------------


@pytest.mark.parametrize("suffix", ["。", "！", "？", "　", "；"])
def test_every_positive_phrase_survives_trailing_chinese_punctuation(suffix):
    """CHN-23: a punctuation variant for every shipped phrase."""
    wrong = []
    for case in _positive_cases():
        got = classify(case["text"] + suffix, language="zh")
        if (got.action, got.args) != (case["action"], case["args"]):
            wrong.append((case["text"], got.action, got.args))
    assert wrong == []


@pytest.mark.parametrize(
    ("english", "mandarin"),
    [
        ("undo", "撤销"),
        ("undo 3 times", "撤销三次"),
        ("save file", "儲存檔案"),
        ("copy", "复制"),
        ("delete the last word", "删除最后一个词"),
        ("delete the last 2 lines", "删除最后两行"),
        ("delete the last 12 words", "删除最后十二个单词"),
        ("select 2 lines", "選取兩行"),
        ("select all", "全选"),
        ("new line", "换行"),
        ("go to line 123", "转到第一百二十三行"),
        ("go to line 105", "轉到第一百零五行"),
        ("page down", "下一页"),
        ("open file README.md", "打开文件 README.md"),
        ("go to class Parser", "转到类 Parser"),
    ],
)
def test_mandarin_emits_the_same_semantic_intent_as_english(english, mandarin):
    en = classify(english, language="en")
    zh_intent = classify(mandarin, language="zh")
    assert en.intent is not IntentType.DICTATE
    assert (zh_intent.intent, zh_intent.action, zh_intent.args) == (en.intent, en.action, en.args)


def test_mandarin_grammar_is_opt_in():
    shipped = Config()
    assert resolve_command_language(shipped.commands.language, shipped.stt.language) == "en"
    assert classify("删除最后一行").intent is IntentType.DICTATE
    for profile_id in ("zh-CN", "zh-TW"):
        profile = get_profile(profile_id)
        assert resolve_command_language("auto", profile.speech_language) == "zh"
        assert profile.command_language == "zh"


# --- native-review state -------------------------------------------------------


def test_every_shipped_action_declares_its_native_review_state():
    assert set(zh.PHRASE_REVIEW) == set(zh.SAFE_CORE_ACTIONS)
    assert set(zh.PHRASE_REVIEW.values()) <= set(zh.REVIEW_STATES)
    assert zh.NUMERAL_REVIEW in zh.REVIEW_STATES


def test_fixture_review_markers_match_the_grammar():
    for case in _positive_cases():
        assert case["review"] == zh.PHRASE_REVIEW[case["action"]], case["text"]


def test_nothing_is_marked_native_reviewed_before_505_records_it():
    """Flip this (and the entries) only alongside the #505 review record."""
    assert set(zh.PHRASE_REVIEW.values()) == {zh.REVIEW_PROVISIONAL}
    assert zh.NUMERAL_REVIEW == zh.REVIEW_PROVISIONAL
