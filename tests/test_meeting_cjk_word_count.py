"""Meeting Mode must not count a contiguous run of Han text as one word (#501).

Chinese is written without spaces between words, so any count that splits on
whitespace or on regex word runs sees a whole Mandarin clause as a single "word". In
Meeting Mode that count is load-bearing: ``quality.assess`` calls a long recording
*thin* below 25 words a minute, and compares the batch transcript against the live
decode by the same count. A healthy ten-minute Mandarin meeting measured that way reads
as ~10 words a minute -- flagged as unusable, its recording kept and the user warned --
and a batch pass that lost most of the meeting slips under the minimum the live/batch
comparison needs.

``quality.tokenize`` already counts each Han ideograph as one quality unit (6ac8f152).
``tests/test_meeting_quality.py`` and ``tests/test_cjk_transcripts.py`` pin the
tokenizer itself; these pin the *stored-meeting* path that reaches it --
``store.live_word_count`` over ``live.jsonl`` and ``store.ensure_quality`` over
``transcript.json`` and ``meeting.json`` -- so a future change to either side of that
path (a different join, a different counter) cannot bring the one-word-per-clause
count back. Each test here fails against the pre-6ac8f152 regex tokenizer.

The Han text is synthetic: distinct ideographs from the unified block in clauses of
24 characters ended by ``。``. That is a counting fixture, not Mandarin prose; it is
the clause length, not the vocabulary, that the defect depends on.
"""
from __future__ import annotations

import json
import sys
import unicodedata

from yazses.meeting import quality as q
from yazses.meeting import store
from yazses.postprocess.cjk import is_han

_CLAUSE = 24  # characters between full stops; Mandarin clauses commonly run 15-30


def _han_clauses(n_chars: int, start: int = 0) -> list[str]:
    """``n_chars`` distinct Han ideographs, cut into ``。``-terminated clauses."""
    chars = [chr(0x4E00 + start + i) for i in range(n_chars)]
    return [
        "".join(chars[i : i + _CLAUSE]) + "。" for i in range(0, n_chars, _CLAUSE)
    ]


def _stored_meeting(tmp_path, batch_text: str, live_lines: list[str], duration_s: float):
    """A finished meeting folder as the controller leaves it, minus the audio."""
    d = tmp_path / "20261021-100000"
    d.mkdir()
    store.write_meta(d, {"id": d.name, "status": "done", "duration_s": duration_s})
    (d / "transcript.json").write_text(
        json.dumps({"text": batch_text, "words": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    for i, line in enumerate(live_lines):
        store.append_live_line(d, line, t=float(i))
    return d


def test_live_word_count_counts_each_han_character(tmp_path):
    store.append_live_line(tmp_path, "今天我们讨论发布计划。")
    store.append_live_line(tmp_path, "明天继续。")
    # 10 + 4 ideographs. A whitespace or regex-word count says 2: one per line.
    assert store.live_word_count(tmp_path) == 14


def test_live_word_count_keeps_an_ascii_name_inside_mandarin_whole(tmp_path):
    store.append_live_line(tmp_path, "我们用YazSes测试。")
    store.append_live_line(tmp_path, "版本2.43很稳定。")
    # 我 们 用 yazses 测 试 | 版 本 很 稳 定 -- digits are not quality units.
    assert store.live_word_count(tmp_path) == 11


def test_a_healthy_mandarin_meeting_is_not_judged_thin(tmp_path):
    clauses = _han_clauses(2400)  # 240 characters a minute over ten minutes
    d = _stored_meeting(tmp_path, "".join(clauses), clauses, duration_s=600.0)

    result = store.ensure_quality(d)

    assert result["words"] == 2400
    assert result["verdict"] == q.QUALITY_OK, result["reasons"]
    assert result["suspect"] is False
    # The verdict is persisted where the listing reads it, so a healthy Mandarin
    # meeting is not re-offered for recovery on every `yazses meeting list`.
    assert store.read_quality(d)["verdict"] == q.QUALITY_OK
    assert store.read_meta(d)["quality_suspect"] is False


def test_a_mandarin_batch_that_lost_the_meeting_is_caught_by_the_live_decode(tmp_path):
    clauses = _han_clauses(2400)
    # The batch pass kept the first 300 characters; the live decode heard all of it.
    d = _stored_meeting(tmp_path, "".join(clauses)[:300], clauses, duration_s=600.0)

    result = store.ensure_quality(d)

    assert result["live_words"] == 2400
    assert result["live_disagrees"] is True
    assert result["suspect"] is True
    assert any("live transcript" in r for r in result["reasons"]), result["reasons"]


def test_live_and_batch_agree_however_the_clauses_were_joined(tmp_path):
    """The live/batch ratio must not depend on whether a join inserted spaces.

    ``store.live_text`` joins Han lines without a space (#501); a batch transcript from
    an older decode joined its segments with ``" "``. Counting whitespace runs gave the
    two different totals for identical words -- a disagreement about punctuation, not
    about what was said.
    """
    lines = ["我们用YazSes测试。", "今天讨论发布计划。", "明天继续讨论。"] * 10
    d = _stored_meeting(tmp_path, " ".join(lines), lines, duration_s=60.0)

    result = store.ensure_quality(d)

    assert result["words"] == result["live_words"] == 200  # (6 + 8 + 6) x 10
    assert result["live_ratio"] == 1.0


def test_the_quality_unit_and_the_pipeline_agree_on_what_han_is():
    """``quality._is_han`` and ``postprocess.cjk.is_han`` are two hand-written range sets.

    If they drift, Meeting Mode counts a character one way while spacing, captions and
    injection treat it another. Checked over every *assigned* code point from the CJK
    radicals to the end of extension H, after the same NFKC + lower-casing ``tokenize``
    applies; only letters reach the per-character branch, so the comparison is against
    ``is_han(c) and c.isalpha()``.
    """
    disagreements = []
    for cp in range(0x2E80, min(0x323AF, sys.maxunicode) + 1):
        if unicodedata.category(chr(cp)) == "Cn":
            continue
        for c in unicodedata.normalize("NFKC", chr(cp)).lower():
            if q._is_han(c) != (is_han(c) and c.isalpha()):
                disagreements.append(f"U+{cp:04X}->U+{ord(c):04X}")
    assert not disagreements, disagreements[:20]
