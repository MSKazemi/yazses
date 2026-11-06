"""Meeting minutes must size a Mandarin window in tokens, not in English characters (#501).

``meeting/notes.py`` turns its token budget into a character budget with
``CHARS_PER_TOKEN = 3.0``, a ratio for English prose. A Han character is not a third of
a token. With the shipped ``notes_ctx_tokens = 4096`` and ``notes_max_tokens = 1024``
the budget is 8,616 characters, and 8,616 Han characters fit the 2,872 tokens left for
transcript only if a tokenizer packs three Han characters into one token. Past that,
llama.cpp either raises (the window is skipped) or silently clips ``max_tokens`` (the
JSON is cut off) -- the two failures ``window_budget_chars`` exists to prevent.

The rule these tests pin: a CJK character is charged its UTF-8 length in tokens. That
is an upper bound for any tokenizer in which every token covers at least one byte of
input (byte-level BPE, and SentencePiece with byte fallback); it is not a measurement
of a real model, and no model is run here. Text holding no CJK is charged exactly
``len(text)``, so the English path is unchanged.

The Han text is synthetic, written for this file.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.meeting.notes import (
    _PROMPT_OVERHEAD_TOKENS,
    CHARS_PER_TOKEN,
    Minutes,
    _merge_partials,
    _minutes_to_json,
    _split_long_text,
    batch_partials,
    budget_len,
    format_turns,
    generate_minutes,
    line_overhead_chars,
    window_budget_chars,
    window_turns,
)
from yazses.postprocess.cjk import is_cjk
from yazses.recimport.align import Utterance

CTX, OUT = 4096, 1024
USABLE_TOKENS = CTX - OUT - _PROMPT_OVERHEAD_TOKENS  # 2,872 with the shipped defaults


def _token_upper_bound(text: str) -> float:
    """Independent oracle: UTF-8 bytes per CJK character, the English ratio otherwise."""
    return sum(
        len(ch.encode("utf-8")) if is_cjk(ch) else 1.0 / CHARS_PER_TOKEN for ch in text
    )


_CLAUSE = "我们今天讨论一下项目的进度和下一步的计划。"  # 21 characters, synthetic


def _mandarin_turns(n: int, clauses_per_turn: int) -> list[Utterance]:
    return [
        Utterance(f"speaker_{i % 2}", float(i), float(i) + 1.0, _CLAUSE * clauses_per_turn)
        for i in range(n)
    ]


@dataclass
class _Cfg:
    notes_window_turns: int = 40
    notes_ctx_tokens: int = CTX
    notes_max_tokens: int = OUT


# --- the cost rule itself ------------------------------------------------------------------


def test_a_han_character_is_charged_its_utf8_length_in_tokens():
    # 3 bytes -> 3 tokens -> 9 budget characters at 3.0 characters per token.
    assert budget_len("你") == 9
    assert budget_len("，") == 9  # a full-width mark is three UTF-8 bytes as well
    assert budget_len("你好 v2") == 9 + 9 + 3


def test_an_astral_han_character_is_charged_four_bytes():
    assert budget_len("\U00020000") == 12  # CJK Extension B


@given(st.text(alphabet=st.characters(max_codepoint=0x2000), max_size=200))
def test_text_without_cjk_costs_exactly_its_length(text):
    # The English path must not move: below U+2000 nothing is CJK.
    assert budget_len(text) == len(text)


# --- the map step ---------------------------------------------------------------------------


def test_every_mandarin_window_fits_the_model_context():
    budget = window_budget_chars(CTX, OUT)
    turns = _mandarin_turns(60, 4)  # 84 Han characters a turn
    windows = window_turns(turns, 40, budget)
    assert len(windows) > 1
    for w in windows:
        tokens = _token_upper_bound(format_turns(w))
        assert tokens <= USABLE_TOKENS, tokens


def test_a_long_mandarin_monologue_is_split_into_pieces_that_fit():
    budget = window_budget_chars(CTX, OUT)
    turn = Utterance("speaker_0", 0.0, 600.0, _CLAUSE * 200)  # 4,200 characters, no spaces
    windows = window_turns([turn], 40, budget)
    assert len(windows) > 1
    assert "".join(p.text for w in windows for p in w) == turn.text
    for w in windows:
        assert _token_upper_bound(format_turns(w)) <= USABLE_TOKENS


def test_split_long_text_budget_is_in_budget_characters():
    pieces = _split_long_text(_CLAUSE * 10, 90)  # 90 budget characters = 10 Han characters
    assert len(pieces) > 1
    assert all(budget_len(p) <= 90 for p in pieces)
    assert "".join(pieces) == _CLAUSE * 10


def test_a_han_speaker_name_is_charged_as_han():
    names = {"speaker_0": "说话人一号同学"}  # 7 Han characters
    assert line_overhead_chars(names) == budget_len(names["speaker_0"]) + 3


def test_generate_minutes_hands_the_model_mandarin_prompts_that_fit():
    prompts: list[str] = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return '{"summary": "好", "decisions": [], "action_items": []}'

    generate_minutes(_mandarin_turns(80, 4), _Cfg(), llm=llm)
    map_prompts = [p for p in prompts if p.startswith("You are taking minutes")]
    assert len(map_prompts) > 1
    for prompt in map_prompts:
        # The English boilerplate is charged at the English ratio by the oracle and the
        # 200-token overhead covers it; the transcript is what must fit.
        assert _token_upper_bound(prompt) <= USABLE_TOKENS + _PROMPT_OVERHEAD_TOKENS


def test_english_windows_are_unchanged():
    turns = [
        Utterance("speaker_0", float(i), float(i) + 1.0, " ".join(["word"] * 120))
        for i in range(40)
    ]
    budget = window_budget_chars(CTX, OUT)
    windows = window_turns(turns, 40, budget)
    # 599 characters a turn plus a 16-character label; 14 turns fill 8,610 of 8,616.
    assert [len(w) for w in windows] == [14, 14, 12]


# --- the reduce step ------------------------------------------------------------------------


def test_mandarin_partials_are_batched_by_token_cost():
    partial = _minutes_to_json(Minutes(summary=_CLAUSE * 20))  # ~420 Han characters
    rendered = [partial] * 6
    budget = window_budget_chars(CTX, OUT)
    for batch in batch_partials(rendered, budget):
        body = "\n\n".join(rendered[i] for i in batch)
        assert len(batch) == 1 or _token_upper_bound(body) <= budget / CHARS_PER_TOKEN


@pytest.mark.parametrize(
    "summaries,expected",
    [
        (["会议讨论了进度。", "决定下周发布。"], "会议讨论了进度。决定下周发布。"),
        (["We discussed progress.", "Release next week."],
         "We discussed progress. Release next week."),
        (["会议讨论了 YazSes。", "Release next week."], "会议讨论了 YazSes。Release next week."),
    ],
    ids=["han", "english", "mixed"],
)
def test_merged_summaries_are_joined_script_aware(summaries, expected):
    # The lossless fallback when a reduce call fails. `" ".join` put a space between
    # two Mandarin sentences.
    merged = _merge_partials([Minutes(summary=s) for s in summaries])
    assert merged.summary == expected
