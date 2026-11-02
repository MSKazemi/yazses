"""Two Persian text defects found by running the real functions on Persian sentences.

* Sentence splitters knew ``. ! ?`` but not the Arabic question mark ``؟`` (U+061F), so a
  Persian paragraph of questions was one "sentence": "delete the last sentence" emptied it.
* The Persian normaliser's POSIX-path protection matched the slash in "و/یا" ("and/or"),
  so the Arabic Yeh next to it was never corrected.
"""

from __future__ import annotations

from yazses.commands.edit_ops import delete_last_sentence
from yazses.condense.extract import _sentences as condense_sentences
from yazses.postprocess.persian_text import normalise_persian
from yazses.reflow.outline import _sentences as reflow_sentences
from yazses.sembr.breaks import semantic_breaks

QUESTIONS = "کجا می‌روی؟ چرا نمی‌آیی؟ کی برمی‌گردی؟"


def test_delete_last_sentence_drops_only_the_last_question() -> None:
    result = delete_last_sentence(QUESTIONS)
    assert result.text.endswith("نمی‌آیی؟")
    assert "کی" not in result.text


def test_english_sentence_edit_is_unchanged() -> None:
    assert delete_last_sentence("One. Two. Three.").text == "One. Two."


def test_other_splitters_see_three_questions() -> None:
    assert len(condense_sentences(QUESTIONS)) == 3
    assert len(reflow_sentences(QUESTIONS)) == 3
    assert semantic_breaks(QUESTIONS).count("\n") == 2


def test_slash_between_persian_words_is_not_a_path() -> None:
    assert normalise_persian("کتاب و/يا مجله") == "کتاب و/یا مجله"
    assert normalise_persian("ي/ك") == "ی/ک"


def test_real_paths_stay_byte_for_byte() -> None:
    for text in ("/home/user/project", "پوشه /home/user/ي را باز کن", "(/tmp/x.txt)"):
        assert normalise_persian(text) == text
