"""Meeting/file transcript outputs with Han text, byte for byte (#501 COMP-05).

``tests/test_cjk_transcripts.py`` checks that every renderer keeps the Han *sentences*
intact. These pin the rest of each file: the timestamps, the speaker labels (a Han
display name among them), the Traditional script, and the round trip a stored meeting
takes through ``transcript.json`` when the user renames or merges speakers -- the path
``yazses meeting relabel`` re-renders from, where a ``" ".join`` would come back.

All text is synthetic and written for this file. No model is run.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yazses.meeting import store
from yazses.recimport.align import assign_words_to_turns, merge_utterances
from yazses.recimport.render import render_transcript

#: "你好，世界。今天測試 YazSes 123。" (Traditional) as Mandarin word tokens, glued.
_WORDS = ["你", "好，", "世", "界。", "今", "天", "測", "試", "YazSes", "123。"]
_TURNS = [(0.0, 0.8, "speaker_0"), (0.8, 2.0, "speaker_1")]
_NAMES = {"speaker_0": "張偉", "speaker_1": "Speaker 2"}


def _result():
    words = [(i * 0.2, i * 0.2 + 0.18, w) for i, w in enumerate(_WORDS)]
    assigned = assign_words_to_turns(words, _TURNS)
    return SimpleNamespace(
        text="你好，世界。今天測試 YazSes 123。",
        utterances=merge_utterances(assigned),
        assigned=assigned,
        language="zh",
        diarized=True,
        speaker_names=dict(_NAMES),
    )


_EXPECTED = {
    "md": "**張偉:** 你好，世界。\n**Speaker 2:** 今天測試 YazSes 123。\n",
    "txt": "張偉: 你好，世界。\nSpeaker 2: 今天測試 YazSes 123。\n",
    "srt": (
        "1\n00:00:00,000 --> 00:00:00,780\n張偉: 你好，世界。\n\n"
        "2\n00:00:00,800 --> 00:00:01,980\nSpeaker 2: 今天測試 YazSes 123。\n"
    ),
    "vtt": (
        "WEBVTT\n\n00:00:00.000 --> 00:00:00.780\n張偉: 你好，世界。\n\n"
        "00:00:00.800 --> 00:00:01.980\nSpeaker 2: 今天測試 YazSes 123。\n"
    ),
}


@pytest.mark.parametrize("fmt", sorted(_EXPECTED))
def test_each_human_format_renders_traditional_han_exactly(fmt):
    assert render_transcript(_result(), fmt).strip() == _EXPECTED[fmt].strip()


def test_json_keeps_han_text_timestamps_and_speaker_names():
    payload = json.loads(render_transcript(_result(), "json"))
    assert payload["language"] == "zh"
    assert payload["speakers"] == _NAMES
    assert [(u["speaker"], u["start"], u["end"], u["text"]) for u in payload["utterances"]] == [
        ("speaker_0", 0.0, 0.78, "你好，世界。"),
        ("speaker_1", 0.8, 1.98, "今天測試 YazSes 123。"),
    ]
    assert "".join(w["text"] for w in payload["words"]) == "".join(_WORDS)


def test_relabel_round_trip_keeps_han_intact(tmp_path):
    # Stored as the finalize pass leaves it, then re-rendered from transcript.json with
    # the two speakers merged and a Han display name given to the survivor.
    store.write_outputs(tmp_path, _result(), fmt="md")
    store.relabel(
        tmp_path, merges={"speaker_1": "speaker_0"}, renames={"speaker_0": "李娜"}, fmt="md"
    )
    md = (tmp_path / "transcript.md").read_text(encoding="utf-8")
    assert md.strip() == "**李娜:** 你好，世界。今天測試 YazSes 123。"
    payload = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert [u["text"] for u in payload["utterances"]] == ["你好，世界。今天測試 YazSes 123。"]


def test_live_markdown_line_keeps_han_and_the_timestamp():
    record = {"t": 75.4, "text": "  版本 v2.0，文件 test.py，编号 12345。 "}
    assert store.live_markdown_line(record) == "[01:15] 版本 v2.0，文件 test.py，编号 12345。"
