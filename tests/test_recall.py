"""Spoken Recall & Ambient Scratch (ADR-v2-005) — pure query/parse + scratch pad."""
from __future__ import annotations

from yazses.recall.query import RecallHit, parse_recall, rank_events
from yazses.recall.scratch import ScratchPad, parse_scratch

# ---- parse_recall ----------------------------------------------------------

def test_parse_recall_extracts_query():
    assert parse_recall("what did I say about kubernetes?") == "kubernetes"
    assert parse_recall("recall the deployment plan") == "the deployment plan"


def test_parse_recall_trigger_only_returns_empty():
    assert parse_recall("recall") == ""


def test_parse_recall_non_recall_is_none():
    assert parse_recall("just some ordinary dictation") is None


# ---- rank_events -----------------------------------------------------------

def _rec(text, ts):
    return (text, ts)


def test_rank_events_orders_by_overlap_then_recency():
    records = [
        _rec("deploy the kubernetes cluster", 100.0),
        _rec("kubernetes pod restart kubernetes", 90.0),
        _rec("unrelated grocery list", 80.0),
    ]
    hits = rank_events(records, "kubernetes", limit=5)
    # the grocery record has zero overlap → dropped
    assert all("grocery" not in h.text for h in hits)
    assert len(hits) == 2
    # both mention kubernetes once (dedup by set) → tie broken by recency
    assert hits[0].ts >= hits[1].ts


def test_rank_events_empty_query_returns_recent():
    records = [_rec("a", 1.0), _rec("b", 3.0), _rec("c", 2.0)]
    hits = rank_events(records, "", limit=2)
    assert [h.ts for h in hits] == [3.0, 2.0]


def test_rank_events_respects_limit_and_skips_blank():
    records = [_rec("alpha term", 1.0), _rec("   ", 2.0), _rec("alpha again", 3.0)]
    hits = rank_events(records, "alpha", limit=1)
    assert len(hits) == 1
    assert isinstance(hits[0], RecallHit)


def test_rank_events_accepts_objects_with_final_text():
    class E:
        def __init__(self, final_text, ts):
            self.final_text = final_text
            self.ts = ts
    hits = rank_events([E("redis cache warmup", 5.0)], "redis")
    assert hits and hits[0].text == "redis cache warmup"


# ---- parse_scratch ---------------------------------------------------------

def test_parse_scratch_extracts_note():
    assert parse_scratch("note to self buy milk") == "buy milk"
    assert parse_scratch("remember that the key is under the mat") == \
        "the key is under the mat"


def test_parse_scratch_trigger_only_is_empty():
    assert parse_scratch("note to self") == ""


def test_parse_scratch_non_note_is_none():
    assert parse_scratch("this is regular dictation") is None


# ---- ScratchPad ------------------------------------------------------------

def test_scratchpad_add_list_clear_roundtrip(tmp_path):
    pad = ScratchPad(tmp_path / "notes" / "scratch.jsonl")
    assert pad.list() == []
    assert pad.add("buy milk", 1.0) is True
    assert pad.add("call alice", 2.0) is True
    assert pad.add("   ", 3.0) is False  # empty ignored
    notes = pad.list()
    assert [n.text for n in notes] == ["buy milk", "call alice"]
    assert pad.clear() == 2
    assert pad.list() == []


def test_scratchpad_skips_malformed_lines(tmp_path):
    p = tmp_path / "scratch.jsonl"
    p.write_text('{"ts": 1.0, "text": "ok"}\nnot json\n\n', encoding="utf-8")
    notes = ScratchPad(p).list()
    assert [n.text for n in notes] == ["ok"]
