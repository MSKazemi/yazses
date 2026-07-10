"""On-device meeting minutes (map-reduce, pure parsing) — ADR-v2-128."""
from __future__ import annotations

import json

from yazses.config import MeetingConfig
from yazses.meeting.notes import (
    ActionItem,
    Minutes,
    SpeakerNote,
    generate_minutes,
    render_minutes_md,
    window_turns,
)
from yazses.recimport.align import Utterance

UTTS = [
    Utterance("speaker_0", 0.0, 2.0, "Let's ship Friday."),
    Utterance("speaker_1", 2.0, 4.0, "I'll write the release notes."),
]


def test_window_turns_splits():
    assert window_turns([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert window_turns([], 3) == []


def test_generate_minutes_single_window():
    reply = json.dumps({
        "summary": "Team agreed to ship Friday.",
        "decisions": ["Ship on Friday"],
        "action_items": [{"owner": "speaker_1", "task": "Write release notes"}],
    })
    m = generate_minutes(UTTS, MeetingConfig(notes=True), llm=lambda p: reply)
    assert m.summary == "Team agreed to ship Friday."
    assert m.decisions == ["Ship on Friday"]
    assert m.action_items == [ActionItem("speaker_1", "Write release notes")]


def test_generate_minutes_map_reduce():
    calls = {"reduce": 0}

    def fake_llm(prompt):
        if prompt.startswith("Combine"):
            calls["reduce"] += 1
            return json.dumps({
                "summary": "Combined.",
                "decisions": ["Ship Friday"],
                "action_items": [{"owner": "Bob", "task": "Notes"}],
                "per_speaker": [{"name": "Bob", "points": ["owns notes"]}],
            })
        return json.dumps({"summary": "part", "decisions": [], "action_items": []})

    cfg = MeetingConfig(notes=True, notes_window_turns=1)  # 2 utts -> 2 windows -> reduce
    m = generate_minutes(UTTS, cfg, llm=fake_llm)
    assert calls["reduce"] == 1
    assert m.summary == "Combined."
    assert m.per_speaker == [SpeakerNote("Bob", ["owns notes"])]


def test_dormant_without_llm_returns_none():
    assert generate_minutes(UTTS, MeetingConfig(notes=True), llm=None) is None
    assert generate_minutes([], MeetingConfig(notes=True), llm=lambda p: "{}") is None


def test_parses_json_inside_prose_and_fences():
    reply = "Sure!\n```json\n{\"summary\": \"ok\", \"decisions\": [\"d1\"]}\n```\nHope that helps"
    m = generate_minutes(UTTS[:1], MeetingConfig(notes=True), llm=lambda p: reply)
    assert m.summary == "ok"
    assert m.decisions == ["d1"]


def test_render_minutes_md():
    md = render_minutes_md(Minutes(
        summary="S", decisions=["d1"],
        action_items=[ActionItem("Bob", "task")],
        per_speaker=[SpeakerNote("Bob", ["p1"])],
    ))
    assert "## Summary" in md and "S" in md
    assert "- d1" in md
    assert "- [ ] Bob: task" in md
    assert "**Bob**" in md and "- p1" in md
