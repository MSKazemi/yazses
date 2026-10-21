"""FA-09 (#518): the text-only fa-en code-switch scorer, protocol ``fa-en-cs-v1``.

Every expectation is a hand-countable number on synthetic text -- no audio, no model, no
mock. The fixture `tests/fixtures/codeswitch/synthetic_fa_en.jsonl` was written for this
test: twelve invented prompts, two per protocol category, each paired with an invented
"hypothesis" carrying one known defect (or none). No real person's speech or text is in
it. The definitions under test are in `design/specs/persian-code-switch-evaluation.md`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmark_deps import load

FIXTURE = Path(__file__).parent / "fixtures" / "codeswitch" / "synthetic_fa_en.jsonl"
ZWNJ = "‌"


@pytest.fixture(scope="module")
def cs():
    return load("codeswitch_metrics", "codeswitch_metrics.py")


@pytest.fixture(scope="module")
def rows(cs):
    return cs.load_rows(FIXTURE)


# ------------------------------------------------------------------ script tags


@pytest.mark.parametrize(
    ("token", "tag"),
    [
        ("GitHub", "en"),
        ("that's", "en"),
        ("kheili", "en"),          # Finglish is Latin script, so it is tagged en
        ("گیت‌هاب", "fa"),    # an English name in Persian script is tagged fa
        ("می‌خواهم", "fa"),
        ("لطفاً", "fa"),           # tanween is a mark, not a letter
        ("PRها", "mixed"),
        ("3.12", "neutral"),
        ("۱۴۰۳", "neutral"),       # Persian digits are digits, not letters
        ("،", "neutral"),
    ],
)
def test_script_tag(cs, token, tag):
    assert cs.script_tag(token) == tag


def test_boundaries_skip_neutral_and_mixed_tokens(cs):
    tags = ["fa", "neutral", "en", "mixed", "en", "fa"]
    assert cs.boundaries(tags) == [(0, 2, "fa", "en"), (4, 5, "en", "fa")]


# --------------------------------------------------------------- edit distance


def test_edit_distance_and_alignment_basics(cs):
    assert cs.edit_distance("abc", "abc") == 0
    assert cs.edit_distance("abc", "axc") == 1
    assert cs.edit_distance(["a", "b"], []) == 2
    assert cs.align(["a", "b", "c"], ["a", "c"]) == [(0, 0), (1, None), (2, 1)]
    assert cs.align([], ["x"]) == [(None, 0)]


# ------------------------------------------------------------ per-utterance scores


def test_a_perfect_rapid_switch_scores_zero_everywhere(cs):
    s = cs.score_utterance("این PR را merge کن", "این PR را merge کن")
    assert (s.ref_tokens, s.token_errors) == (5, 0)
    assert (s.ref_boundaries, s.hyp_boundaries, s.matched_boundaries) == (4, 4, 4)
    assert (s.en_ref_tokens, s.en_preserved) == (2, 2)
    assert (s.fa_ref_chars, s.fa_char_errors) == (9, 0)


def test_transliterating_an_english_term_costs_every_metric(cs):
    """`PR` written in Persian script: one token error, both boundaries around it
    lost, the English token transliterated, and five Persian letters plus a space
    inserted into the Persian stream (`این را کن` -> `این پی‌آر را کن`)."""
    s = cs.score_utterance("این PR را merge کن", f"این پی{ZWNJ}آر را merge کن")
    assert s.token_errors == 1
    assert (s.ref_boundaries, s.hyp_boundaries, s.matched_boundaries) == (4, 2, 2)
    assert (s.en_ref_tokens, s.en_preserved, s.en_transliterated) == (2, 1, 1)
    assert (s.fa_ref_chars, s.fa_char_errors) == (9, 6)
    assert (s.lang_aligned, s.lang_agree) == (5, 4)
    summary = cs.summarize([s])
    assert summary["mer"] == 0.2
    assert summary["boundary_error_rate"] == 0.5
    assert summary["boundary_recall"] == 0.5
    assert summary["boundary_precision"] == 1.0
    assert summary["fa_cer"] == round(6 / 9, 4)


def test_finglish_loses_the_persian_clause_entirely(cs):
    s = cs.score_utterance("I told him خیلی ممنون and left", "I told him kheili mamnoon and left")
    assert s.token_errors == 2
    assert (s.ref_boundaries, s.hyp_boundaries, s.matched_boundaries) == (2, 0, 0)
    assert (s.fa_ref_chars, s.fa_char_errors) == (10, 10)
    assert s.en_preserved == s.en_ref_tokens == 5


def test_a_deleted_middle_still_credits_the_surviving_switch(cs):
    """`fa en fa en` -> `fa en`: the hypothesis switch brackets the first reference
    boundary, so one of three is recovered and none is spurious."""
    s = cs.score_utterance("سلام hello دنیا world", "سلام world")
    assert (s.ref_boundaries, s.hyp_boundaries, s.matched_boundaries) == (3, 1, 1)
    assert cs.summarize([s])["boundary_error_rate"] == round(2 / 3, 4)


def test_a_spurious_switch_shows_in_precision_when_the_reference_has_none(cs):
    s = cs.score_utterance("این را بفرست", "این را send")
    summary = cs.summarize([s])
    assert summary["boundary_error_rate"] is None  # no reference boundary to divide by
    assert summary["boundary_precision"] == 0.0
    assert summary["en_preservation"] is None      # no English in the reference


def test_case_and_punctuation_in_english_preservation(cs):
    s = cs.score_utterance("از pip استفاده کن", "از Pip استفاده کن")
    assert (s.en_preserved, s.en_preserved_casefold) == (0, 1)
    s = cs.score_utterance("در GitHub، گذاشتم", "در GitHub گذاشتم")
    assert s.token_errors == 1          # MER is strict: fa-eval-v1 keeps punctuation
    assert s.en_preserved == 1          # preservation compares the token's core


def test_arabic_yeh_is_a_raw_error_and_not_a_normalized_one(cs, rows):
    row = next(r for r in rows if r["id"] == "fa-en-0005")
    s = cs.score_utterance(row["reference"], row["hypothesis"])
    assert (s.raw_token_errors, s.token_errors) == (1, 0)


def test_mixed_tokens_are_counted_not_silently_dropped(cs):
    s = cs.score_utterance("این PRها را ببین", "این PRها را ببین")
    assert s.mixed_ref_tokens == 1
    assert s.en_ref_tokens == 0
    assert s.ref_boundaries == 0


# ------------------------------------------------------------------- the fixture


def test_the_fixture_covers_all_six_categories(cs, rows):
    assert len(cs.CATEGORIES) == 6
    seen = {r["category"] for r in rows}
    assert seen == set(cs.CATEGORIES)


def test_fixture_aggregate_matches_the_hand_counts(cs, rows):
    overall = cs.run(rows, "all")["overall"]
    c = overall["counts"]
    assert overall["n"] == 12
    assert (c["ref_tokens"], c["token_errors"], c["raw_token_errors"]) == (81, 7, 8)
    assert (c["ref_boundaries"], c["hyp_boundaries"], c["matched_boundaries"]) == (32, 24, 24)
    assert (c["en_ref_tokens"], c["en_preserved"], c["en_transliterated"]) == (30, 25, 3)
    assert (c["fa_ref_chars"], c["fa_char_errors"]) == (197, 31)


# ------------------------------------------------------------------------ split


def test_split_is_pinned_for_the_fixture_ids(cs, rows):
    """A known-answer vector: if the hash, seed or fraction changes, this fails, and
    that change is protocol `fa-en-cs-v2`, not an edit to v1."""
    heldout = sorted(r["id"] for r in rows if cs.split_of(r["id"]) == "heldout")
    assert heldout == ["fa-en-0003", "fa-en-0008", "fa-en-0009", "fa-en-0010"]


def test_split_ignores_order_and_membership(cs):
    ids = [f"p-{i}" for i in range(200)]
    before = {i: cs.split_of(i) for i in ids}
    after = {i: cs.split_of(i) for i in reversed(ids + ["p-new-1", "p-new-2"])}
    assert all(before[i] == after[i] for i in ids)


def test_split_fraction_is_close_to_the_frozen_value(cs):
    n = 10_000
    heldout = sum(cs.split_of(f"p-{i}") == "heldout" for i in range(n))
    assert abs(heldout / n - cs.HELDOUT_FRACTION) < 0.02


def test_split_refuses_an_id_that_could_name_a_person(cs):
    with pytest.raises(ValueError):
        cs.split_of("Speaker Ali 01")


def test_split_digest_is_order_independent(cs):
    assert cs.split_digest(["b", "a"]) == cs.split_digest(["a", "b", "a"])
    assert cs.split_digest(["a"]) != cs.split_digest(["b"])


# ------------------------------------------------------- aggregate-only submission


def test_the_submission_block_carries_no_text_and_no_ids(cs, rows, tmp_path):
    out = tmp_path / "agg.json"
    assert cs.main([str(FIXTURE), "--split", "all", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["protocol"] == "fa-en-cs-v1"
    assert report["normalizer"] == "fa-eval-v1"
    assert set(report["by_category"]) == set(cs.CATEGORIES)
    for row in rows:
        assert row["id"] not in text
        for token in (row["reference"] + " " + row["hypothesis"]).split():
            if len(token) >= 4:
                assert token not in text, token


def test_the_default_split_is_heldout(cs, rows):
    report = cs.run(rows)
    assert report["split"]["name"] == "heldout"
    assert report["overall"]["n"] == 4


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"id": "x-1", "category": "chit_chat", "reference": "a", "hypothesis": "a"}, "category"),
        ({"id": "Ali Rezaei", "category": "rapid_switch", "reference": "a", "hypothesis": "a"}, "opaque"),
        ({"id": "x-1", "category": "rapid_switch", "reference": "a"}, "hypothesis"),
    ],
)
def test_load_rows_refuses_malformed_rows(cs, tmp_path, row, message):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        cs.load_rows(path)
