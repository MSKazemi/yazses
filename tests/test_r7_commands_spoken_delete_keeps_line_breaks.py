"""A spoken delete must not rewrite the whitespace of the words it keeps.

Spoken Edit (`commands/edit_ops.py`) computes the new text of the last dictated burst,
and the daemon erases that burst and re-types the result (`_try_spoken_edit`). Voice
punctuation (`postprocess/voice_punctuation.py`) puts real line breaks into a burst
("new line" -> ``\\n``, "new paragraph" -> ``\\n\\n``). The delete operations used to
rebuild the kept text with ``" ".join(...)``, so "delete the last word" on a two-paragraph
burst also flattened the paragraph break into a space -- an edit the user never asked
for, to words they did not mean to touch. Synthetic, pure-function evidence.
"""
from __future__ import annotations

from yazses.commands.edit_ops import apply_edit, delete_last_sentence, delete_last_words


def test_delete_last_word_keeps_a_paragraph_break_before_it() -> None:
    r = delete_last_words("Dear Sam,\n\nthanks for the note", 1)
    assert r.changed
    assert r.text == "Dear Sam,\n\nthanks for the"


def test_delete_last_words_across_a_line_break_keeps_earlier_lines() -> None:
    r = delete_last_words("milk\neggs\nbread and butter", 3)
    assert r.text == "milk\neggs"


def test_delete_last_sentence_keeps_a_paragraph_break_between_kept_sentences() -> None:
    r = delete_last_sentence("Hi there.\n\nFirst point. Second point.")
    assert r.changed
    assert r.text == "Hi there.\n\nFirst point."


def test_delete_last_sentence_after_a_paragraph_break_drops_only_that_sentence() -> None:
    r = delete_last_sentence("Hi there.\n\nOne more thing.")
    assert r.text == "Hi there."


def test_spoken_phrase_end_to_end_keeps_the_line_break() -> None:
    r = apply_edit("Line one\nline two words", "delete the last word.")
    assert r.text == "Line one\nline two"


def test_existing_counting_behaviour_is_unchanged() -> None:
    assert delete_last_words("one two three four", 2).text == "one two"
    assert delete_last_words("one two", 5).text == ""
    assert delete_last_words("nothing", 0).changed is False
    assert delete_last_words("   ", 1).changed is False
    assert delete_last_sentence("First one. Second one. Third one.").text == (
        "First one. Second one."
    )
    assert delete_last_sentence("Only sentence here").text == ""
    assert delete_last_sentence("  ").changed is False
