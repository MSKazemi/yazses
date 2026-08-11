"""Tests for the offline disfluency filter."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import filter_transcript

CORPUS_PATH = Path(__file__).parent / "fixtures" / "disfluency" / "corpus.json"


def load_corpus():
    with open(CORPUS_PATH) as f:
        return json.load(f)


@pytest.mark.parametrize("entry", load_corpus(), ids=lambda e: e["notes"][:40])
def test_corpus(entry):
    config = DisfluencyConfig()
    result = filter_transcript(entry["input"], config)
    assert result.text == entry["expected"], (
        f"Input: {entry['input']!r}\n"
        f"Expected: {entry['expected']!r}\n"
        f"Got: {result.text!r}"
    )


def test_runtime_under_10ms():
    config = DisfluencyConfig()
    text = "um so I uh need to basically uh you know delete last line uh right okay so"
    t0 = time.perf_counter()
    for _ in range(100):
        filter_transcript(text, config)
    elapsed_ms = (time.perf_counter() - t0) / 100 * 1000
    assert elapsed_ms < 10, f"filter_transcript took {elapsed_ms:.2f} ms (> 10 ms)"


def test_proper_nouns_unchanged():
    config = DisfluencyConfig()
    text = "Hello Python is great"
    result = filter_transcript(text, config)
    assert "Python" in result.text


def test_code_identifiers_unchanged():
    config = DisfluencyConfig()
    text = "call the function_name here"
    result = filter_transcript(text, config)
    assert "function_name" in result.text


def test_disabled_filter_passthrough():
    config = DisfluencyConfig(enabled=False)
    text = "um hello um world"
    result = filter_transcript(text, config)
    assert result.text == text
    assert result.chars_removed == 0


def test_chars_removed_counted():
    config = DisfluencyConfig()
    text = "um hello world"
    result = filter_transcript(text, config)
    assert result.chars_removed > 0


def test_empty_input():
    config = DisfluencyConfig()
    result = filter_transcript("", config)
    assert result.text == ""
    assert result.chars_removed == 0


def test_custom_filler_words():
    config = DisfluencyConfig(filler_words=["actually", "honestly"])
    text = "I actually honestly think this is good"
    result = filter_transcript(text, config)
    assert "actually" not in result.text
    assert "honestly" not in result.text
    assert "think this is good" in result.text


# ---- Dysfluency-Friendly Mode: collapse passes (ADR-015) ------------------

from yazses.stt.filters.disfluency import (  # noqa: E402
    _collapse_prolongations,
    _collapse_repetitions,
)


def test_collapse_prolongation_basic():
    assert _collapse_prolongations("sooo good", 3) == "so good"


def test_collapse_prolongation_leaves_double_letters():
    assert _collapse_prolongations("see the tree", 3) == "see the tree"


def test_collapse_prolongation_protects_caps_and_code():
    assert _collapse_prolongations("HELLOOO obj.attr", 3) == "HELLOOO obj.attr"


def test_collapse_prolongation_noop_below_min_run():
    assert _collapse_prolongations("soo good", 3) == "soo good"


def test_collapse_hyphen_false_start():
    assert _collapse_repetitions("b-b-because i can", 2) == "because i can"


def test_collapse_space_fragment_run():
    assert _collapse_repetitions("st st stop now", 2) == "stop now"


def test_collapse_unigram_triple():
    assert _collapse_repetitions("the the the cat", 2) == "the cat"


def test_repetition_preserves_intentional_hyphenation():
    assert _collapse_repetitions("re-read the co-op file", 2) == "re-read the co-op file"


def test_repetition_preserves_emphasis_pair():
    assert _collapse_repetitions("very very good", 2) == "very very good"


def test_repetition_protects_caps_and_code():
    assert _collapse_repetitions("I I think foo_bar", 2) == "I I think foo_bar"


# ---- Dysfluency collapse integrated into filter_transcript (ADR-015) ------

def test_filter_default_does_not_collapse():
    cfg = DisfluencyConfig()
    assert filter_transcript("b-b-because sooo good", cfg).text == "b-b-because sooo good"


def test_filter_collapses_when_enabled():
    cfg = DisfluencyConfig(collapse_repetitions=True, collapse_prolongations=True)
    assert filter_transcript("b-b-because it is sooo good", cfg).text == "because it is so good"


def test_filter_collapse_respects_protection_end_to_end():
    cfg = DisfluencyConfig(collapse_repetitions=True, collapse_prolongations=True)
    out = filter_transcript("call FooBar and re-read obj.attr", cfg).text
    assert "FooBar" in out and "re-read" in out and "obj.attr" in out


# ---- Filler matching must respect word and token boundaries ----------------
# Regression tests for two bugs found by the cross-platform contract vectors
# (docs/mobile/adr/adr-mob-008-cross-platform-contract.md). Both corrupted text
# the user actually dictated, silently.

def test_filler_does_not_match_a_word_that_merely_starts_with_one():
    # "like" matched the prefix of "likely" and left "ly" behind: the filler
    # group had \b only at the start.
    assert filter_transcript("that is likely correct").text == "that is likely correct"
    assert filter_transcript("we err on the side of erring").text.endswith("erring")


def test_filler_inside_a_code_identifier_is_left_alone():
    # "basically_fn" became "_fn": the protection guard tested the matched
    # filler ("basically") instead of the token containing it.
    out = filter_transcript("call basically_fn in um main.py").text
    assert out == "call basically_fn in main.py"


def test_filler_inside_a_url_is_left_alone():
    out = filter_transcript("um see https://example.com/actually for details").text
    assert out == "see https://example.com/actually for details"


def test_ordinary_fillers_still_removed_after_the_boundary_fix():
    assert filter_transcript("um the meeting is at noon").text == "the meeting is at noon"
    assert filter_transcript("the meeting you know is at noon").text == (
        "the meeting is at noon"
    )


def test_sentence_initial_content_words_survive():
    assert filter_transcript("Right turn at the corner").text == "Right turn at the corner"
    assert filter_transcript("Like button is broken").text == "Like button is broken"
    assert filter_transcript("Actually is a strong word").text == (
        "Actually is a strong word"
    )


def test_sentence_initial_unambiguous_fillers_still_stripped():
    assert filter_transcript("Um the meeting is at noon").text == "the meeting is at noon"
    assert filter_transcript("Uh so I think").text == "so I think"


def test_sentence_initial_multiword_filler_stays_protected():
    # "You know the meeting is at noon" can be a real sentence addressed to
    # someone, so the #117 relaxation does not apply to multi-word fillers.
    assert filter_transcript("You know the meeting is at noon").text == (
        "You know the meeting is at noon"
    )


def test_err_is_a_verb_not_a_filler():
    # "err" was in the default filler list and is an ordinary English verb, so
    # this deleted a real word mid-sentence (issue #125). Lowercase and
    # mid-utterance, so none of the #117-#122 position-0 guards ever applied.
    assert filter_transcript("To err is human").text == "To err is human"
    assert filter_transcript("Err on the side of caution").text == (
        "Err on the side of caution"
    )
    assert filter_transcript("err on the side of caution").text == (
        "err on the side of caution"
    )


def test_ah_remains_a_filler():
    # The line is lexical: "ah" is an interjection in every dictionary sense, so
    # removing it costs tone and never meaning. "err" has a verb sense and does
    # not qualify. Decided alongside #125 rather than left to be rediscovered.
    assert filter_transcript("Ah yes the meeting").text == "yes the meeting"
    assert filter_transcript("ah well").text == "well"


def test_err_fix_does_not_regress_the_hesitation_chain():
    # Everything the #117 -> #119 -> #121 -> #122 chain settled must still hold.
    assert filter_transcript("Um the meeting is at noon").text == "the meeting is at noon"
    assert filter_transcript("So um the meeting is at noon").text == (
        "the meeting is at noon"
    )
    assert filter_transcript("Uh... so I think").text == "so I think"
    assert filter_transcript("Right turn at the corner").text == "Right turn at the corner"
    assert filter_transcript("Okay so the meeting is at noon").text == (
        "Okay so the meeting is at noon"
    )
    # "er" is still a particle -- only "err" was removed.
    assert filter_transcript("Er I forgot").text == "I forgot"


def test_hyphenated_all_filler_token_is_dropped_whole():
    # #144: each "um" inside "um-um" used to be stripped independently, leaving
    # an orphaned hyphen glued to the next word ("-the meeting").
    assert filter_transcript("um-um the meeting").text == "the meeting"
    assert filter_transcript("uh-uh no").text == "no"


def test_stuttered_content_word_is_never_opened_up():
    # #144 is an accessibility bug: a hyphenated repeat is what a stutter looks
    # like once Whisper has transcribed it, and this filter is dysfluency-friendly
    # mode. Destroying the real word is worse than not filtering at all.
    assert filter_transcript("a-a-actually the meeting").text == (
        "a-a-actually the meeting"
    )
    assert filter_transcript("b-b-basically the meeting").text == (
        "b-b-basically the meeting"
    )
    assert filter_transcript("I w-w-want that").text == "I w-w-want that"


def test_hyphenated_real_words_survive_a_filler_part():
    # The same bug hit ordinary vocabulary whenever a user configured a filler
    # that appears in a compound: "right-click" must not become "-click".
    cfg = DisfluencyConfig(
        enabled=True, filler_words=["um", "uh", "so", "like", "well", "right"]
    )
    for text in (
        "right-click the icon",
        "the so-called fix",
        "a well-known issue",
        "like-minded people",
    ):
        assert filter_transcript(text, cfg).text == text


def test_filler_removal_still_works_next_to_a_hyphenated_token():
    # The guard must not switch Rule A off for the rest of the line.
    cfg = DisfluencyConfig(enabled=True, filler_words=["um", "uh", "right"])
    assert filter_transcript("um-um right-click um the icon", cfg).text == (
        "right-click the icon"
    )


def test_self_correction_consumes_the_triggers_own_period():
    # #145: "delete that." as a complete sentence — the ordinary phrasing — used
    # to leave a bare ". " in the middle of the typed output.
    assert filter_transcript("send it to Bob. delete that. send it to Alice").text == (
        "send it to Bob. send it to Alice"
    )
    assert filter_transcript("the budget is fine. forget that. the budget is tight").text == (
        "the budget is fine. the budget is tight"
    )


def test_self_correction_resolves_in_text_order_not_config_order():
    # #145: "no wait" is declared before "scratch that" in the default trigger
    # list, and used to win regardless of which the user actually said first.
    assert filter_transcript("scratch that. no wait meet at four").text == "meet at four"
    assert filter_transcript(
        "meet at three. scratch that. no wait meet at four"
    ).text == "meet at three. meet at four"


def test_self_correction_without_punctuation_still_rolls_back():
    # Regression guard: the punctuation fix must not disturb the plain path.
    assert filter_transcript("send it to Bob delete that send it to Alice").text == (
        "send it to Alice"
    )
    assert filter_transcript("meet at three, scratch that, meet at four").text == (
        "meet at four"
    )


def test_text_without_any_trigger_is_untouched():
    assert filter_transcript("no trigger here at all").text == "no trigger here at all"


def test_filler_removal_never_synthesises_a_new_hyphen_token():
    """@YossiMH's metamorphic invariant from #144.

    With repetition collapse disabled, filler removal must never produce a
    hyphen-bearing token that was not already a complete token in the input.
    That is the property the old code violated: it manufactured "-", "--" and
    "-cat" out of tokens the speaker never uttered.
    """
    cfg = DisfluencyConfig(
        enabled=True,
        collapse_repetitions=False,
        filler_words=["um", "uh", "er", "ah", "hmm", "so", "right", "well"],
    )
    corpus = [
        "um-um the meeting",
        "uh-uh no",
        "um-um-um yes",
        "er-er-er hello",
        "so um-um well",
        "um-hmm okay",
        "the um-um cat",
        "a-a-actually the meeting",
        "b-b-basically the meeting",
        "I w-w-want that",
        "right-click the icon",
        "the so-called fix",
        "a well-known issue",
        "um the meeting",
        "state-of-the-art um results",
    ]
    for text in corpus:
        original_tokens = set(text.split())
        out_tokens = filter_transcript(text, cfg).text.split()
        invented = [
            t for t in out_tokens if "-" in t and t not in original_tokens
        ]
        assert not invented, f"{text!r} synthesised {invented!r}"


def test_hyphen_token_is_kept_whole_or_dropped_whole():
    """@YossiMH's sharpened whole-token invariant from #144.

    The test above catches the *symptom* the original bug showed — a synthesised
    hyphen-bearing token. It cannot catch a partial destructuring whose result
    happens to contain no hyphen: "um-actually" -> "actually" passes it, because
    "actually" is not hyphen-bearing, yet Rule A has still deleted a component
    from inside a token.

    The property being asserted is the stronger one:

        Rule A may preserve a hyphen-linked token intact, or delete it intact
        when every lexical component is independently removable. It must never
        build the output by deleting only selected internal components.
    """
    cfg = DisfluencyConfig(
        enabled=True,
        collapse_repetitions=False,
        filler_words=["um", "uh", "er", "ah", "hmm", "so", "right", "well"],
    )
    # (input, whether every component is a filler -> whole-token deletion allowed)
    corpus = [
        ("um-um the meeting", True),
        ("um-hmm okay", True),
        ("um-um-um yes", True),
        ("um-actually the meeting", False),
        ("actually-um the meeting", False),
        ("the well-um-known case", False),
        ("a-a-actually the meeting", False),
        ("right-click the icon", False),
        ("a well-known issue", False),
        ("state-of-the-art um results", False),
    ]
    for text, all_filler in corpus:
        out = filter_transcript(text, cfg).text
        out_tokens = out.split()
        for token in text.split():
            if "-" not in token:
                continue
            if token in out_tokens:
                continue  # preserved intact — always allowed
            # Not intact: the only legal alternative is that it vanished whole,
            # leaving no component of it behind anywhere in the output.
            assert all_filler, (
                f"{text!r} -> {out!r}: dropped {token!r}, but not every "
                "component of it is a filler"
            )
            survivors = [
                part for part in token.split("-")
                if part and part in out_tokens
            ]
            assert not survivors, (
                f"{text!r} -> {out!r}: partially destructured {token!r}, "
                f"leaving {survivors!r}"
            )
