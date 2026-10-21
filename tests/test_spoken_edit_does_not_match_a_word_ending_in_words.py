"""`delete the last passwords` is dictation, not a request to delete one word.

Spoken Edit Mode's parser (`commands/edit_ops.py`, ADR-v2-003) recognised the delete
command with

    ^delete\\s+(?:the\\s+)?last\\s+(\\w+)?\\s*words?$

Every piece is anchored, and it still matched a *suffix*: `\\s*` lets the optional
count run straight into `words?` with no space, so the regex backtracks until the
count is the front of a longer word and `words` is its tail --

    "delete the last passwords"   ->  count "pass",   op delete_words
    "delete the last keywords"    ->  count "key",    op delete_words
    "delete the last swords"      ->  count "s",      op delete_words

and an unknown count silently becomes 1. The daemon tries this parser on a command-key
utterance no other command claimed (`[commands] spoken_edit`, off by default).
`delete_words` is in `DESTRUCTIVE`, so with `spoken_edit_destructive` also on, "delete
the last passwords" erased the last word of the previous dictation; with it off, the
event was logged as a skipped destructive edit rather than an unmatched command. The
count now has to be its own word: `(?:(\\w+)\\s+)?words?`.

The phrases that should work still do, and are held below so the fix cannot be a
regex that simply matches less.
"""

from __future__ import annotations

import pytest

from yazses.commands.edit_ops import apply_edit, parse_edit

#: Real words that end in "word"/"words". Each is something a person dictates.
COMPOUNDS = (
    "passwords",
    "password",
    "keywords",
    "keyword",
    "swords",
    "sword",
    "crosswords",
    "buzzwords",
    "watchwords",
    "afterwords",
)


@pytest.mark.parametrize("word", COMPOUNDS)
@pytest.mark.parametrize("article", ["the ", ""], ids=["the", "bare"])
def test_a_word_ending_in_words_is_not_a_delete_command(word: str, article: str) -> None:
    phrase = f"delete {article}last {word}"
    assert parse_edit(phrase) is None, f"{phrase!r} parsed as an edit command"


def test_the_last_word_of_the_dictation_survives_such_a_phrase() -> None:
    """End to end through `apply_edit`: unchanged text, not one word shorter."""
    result = apply_edit("my old passwords are here", "delete the last passwords")
    assert result.changed is False
    assert result.text == "my old passwords are here"


@pytest.mark.parametrize(
    ("phrase", "n"),
    [
        ("delete the last word", 1),
        ("delete last word", 1),
        ("delete the last words", 1),
        ("delete the last three words", 3),
        ("delete the last two words.", 2),
        ("delete last 4 words", 4),
        ("Delete The Last Word", 1),
        ("delete  the  last   2   words", 2),
    ],
)
def test_the_real_delete_commands_still_parse(phrase: str, n: int) -> None:
    assert parse_edit(phrase) == ("delete_words", {"n": n})
