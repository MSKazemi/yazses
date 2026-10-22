"""Code mode promised cased identifiers, and nothing ever cased one.

`yazses features info code` said "word-groups become cased identifiers (snake/camel/pascal)",
and ADR-v2-031 names two cores: `spoken_symbols` and `to_case`. Only the first had a
caller. "code def get user name open paren user id close paren colon" typed
`def get user name(user id):`, and `docs/v2-features.md` had to say so.

`spoken_identifiers` is the missing grammar between the spoken words and `to_case`, and
the `code` handler now runs it. What these tests hold:

* **The signal is narrow** (ADR-021). Only the two-word keyword "<style> case" followed by
  a word starting with a letter fires. A keyword with nothing usable after it, a style
  `to_case` does not know ("title case"), or a word that merely contains "case"
  ("showcase", "uppercase") leaves the text exactly as it was.
* **The boundary is explicit**: "end case" (consumed), the next keyword, any symbol or
  punctuation, or the end of the phrase.
* **Order with `spoken_symbols`**: symbols first, so a symbol word ends an identifier
  rather than becoming part of it. Reversing the two in the handler fails
  `test_a_symbol_word_ends_the_identifier_through_the_real_handler`.
* **Prose is never reached**: the grammar only runs inside "code ..." while the command
  key is held; ordinary dictation that mentions camel case is not claimed.
"""

from __future__ import annotations

import pytest

from yazses.code.spoken import (
    _CASE_STYLE_WORDS,
    _STYLES,
    spoken_identifiers,
    spoken_symbols,
)
from yazses.config import Config
from yazses.spokencmd.registry import build_handlers
from yazses.spokencmd.router import route


def _code_handlers():
    cfg = Config()
    cfg.code.enabled = True
    return list(build_handlers(cfg))


def _typed(phrase: str) -> str | None:
    result = route(phrase, _code_handlers())
    return None if result is None else result.text


# ---- every style is speakable, and only real styles are ---------------------


def test_every_spoken_style_names_a_style_to_case_knows():
    assert set(_CASE_STYLE_WORDS.values()) <= set(_STYLES)


def test_every_style_to_case_knows_can_be_spoken():
    assert set(_STYLES) <= set(_CASE_STYLE_WORDS.values())


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("camel case user name", "userName"),
        ("pascal case http server", "HttpServer"),
        ("snake case max retries", "max_retries"),
        ("kebab case main menu", "main-menu"),
        ("constant case max size", "MAX_SIZE"),
        ("screaming case max size", "MAX_SIZE"),
        ("screaming snake case max size", "MAX_SIZE"),
    ],
)
def test_each_style_keyword_cases_the_words_after_it(spoken, expected):
    assert spoken_identifiers(spoken) == expected


def test_screaming_snake_is_one_keyword_not_screaming_then_a_snake_run():
    """Longest style first: otherwise "screaming" stays a word and the run is snake."""
    assert spoken_identifiers("x = screaming snake case max size") == "x = MAX_SIZE"


# ---- the spellings Whisper writes for the keyword ----------------------------


@pytest.mark.parametrize(
    "keyword",
    ["camel case", "Camel Case", "CAMEL CASE", "camelCase", "camel-case", "camel_case",
     "camel  case"],
)
def test_the_keyword_survives_how_whisper_writes_it(keyword):
    assert spoken_identifiers(f"{keyword} user name") == "userName"


def test_whisper_capitalisation_of_the_words_is_normalised():
    assert spoken_identifiers("Pascal case HTTP Server") == "HttpServer"


def test_whisper_trailing_full_stop_is_kept_after_the_identifier():
    assert spoken_identifiers("camel case user name.") == "userName."


def test_digits_inside_an_identifier_are_kept():
    assert spoken_identifiers("camel case item 2") == "item2"


# ---- the boundary ------------------------------------------------------------


def test_end_case_ends_the_identifier_and_is_not_typed():
    assert (
        spoken_identifiers("return camel case user name end case if ready")
        == "return userName if ready"
    )


def test_end_case_at_the_very_end_is_consumed():
    assert spoken_identifiers("camel case user name end case") == "userName"


def test_end_case_is_case_insensitive():
    assert spoken_identifiers("snake case a b End Case c") == "a_b c"


def test_end_alone_is_an_ordinary_word():
    assert spoken_identifiers("camel case end user") == "endUser"


def test_the_next_keyword_starts_a_new_identifier():
    assert (
        spoken_identifiers("snake case user id camel case account name")
        == "user_id accountName"
    )


def test_a_symbol_ends_the_identifier():
    assert spoken_identifiers("camel case user name = none") == "userName = none"


def test_punctuation_ends_the_identifier():
    assert spoken_identifiers("camel case first name, then") == "firstName, then"


def test_text_around_an_identifier_is_preserved_exactly():
    assert spoken_identifiers("x = snake case max retries + 1") == "x = max_retries + 1"


def test_several_identifiers_in_one_phrase():
    assert (
        spoken_identifiers("camel case first name , camel case last name")
        == "firstName , lastName"
    )


# ---- what must be left alone (ADR-021: fire only on the specific signal) ------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "just talking normally",
        # The keyword with nothing to case after it.
        "I prefer camel case",
        "camel case",
        # The keyword followed by punctuation, not a word.
        "camel case, please",
        "use snake case. It reads well",
        # The keyword followed by a number: not a valid identifier start.
        "snake case 2 factor",
        # The terminator with no words before it.
        "camel case end case",
        # Words that contain a style word or "case" but are not the keyword.
        "a camels case study",
        "the showcase is in uppercase and lowercase",
        "my_snake case is long",
        "camel cases are common",
        # Styles `to_case` does not support are not keywords.
        "title case my heading",
        "upper case the name",
        "lower case foo",
        # Style word without "case".
        "a camel and a snake",
        "constant value",
    ],
)
def test_text_without_the_signal_is_left_exactly_as_it_was(text):
    assert spoken_identifiers(text) == text


def test_none_is_treated_as_empty():
    assert spoken_identifiers(None) == ""  # type: ignore[arg-type]


def test_a_rejected_keyword_does_not_stop_a_later_one_firing():
    assert spoken_identifiers("camel case, then snake case max size") == (
        "camel case, then max_size"
    )


# ---- composition with spoken_symbols (the order the handler uses) -------------


def test_symbols_first_then_identifiers_lets_a_symbol_word_end_the_run():
    spoken = "camel case user name equals none"
    assert spoken_identifiers(spoken_symbols(spoken)) == "userName = none"


def test_the_reverse_order_would_swallow_the_symbol_word():
    """Why the handler runs symbols first — pinned so the rationale stays checkable."""
    spoken = "camel case user name equals none"
    assert spoken_symbols(spoken_identifiers(spoken)) == "userNameEqualsNone"


def test_a_symbol_word_right_after_the_keyword_leaves_the_keyword_alone():
    """A symbol word ("star") is always a symbol in code mode, never an identifier word."""
    assert spoken_identifiers(spoken_symbols("pascal case star wars")) == "pascal case * wars"


def test_casing_output_is_not_reread_as_symbol_words():
    """An identifier that contains a symbol word is not split by a second symbol pass."""
    cased = spoken_identifiers("snake case get dot")
    assert cased == "get_dot"
    assert spoken_symbols(cased) == "get_dot"


# ---- through the real `code` handler ------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("code self dot camel case user name equals none", "self.userName = none"),
        ("code def snake case load config open paren self close paren colon",
         "def load_config(self):"),
        ("code class pascal case http server colon", "class HttpServer:"),
        ("code constant case max size equals 10", "MAX_SIZE = 10"),
        ("code camel case first name comma camel case last name", "firstName, lastName"),
        ("code return camel case user name end case if ready", "return userName if ready"),
        ("Code self dot camel case user name equals None.", "self.userName = None"),
        # The pre-existing symbol-only phrase is unchanged.
        ("code def foo open paren x comma y close paren colon", "def foo(x, y):"),
    ],
)
def test_the_code_handler_types_cased_identifiers(phrase, expected):
    assert _typed(phrase) == expected


def test_a_symbol_word_ends_the_identifier_through_the_real_handler():
    """Fails if `_code` ever runs `spoken_identifiers` before `spoken_symbols`."""
    assert _typed("code camel case user name equals none") == "userName = none"


@pytest.mark.parametrize(
    "prose",
    [
        "I prefer camel case for variable names",
        "we use snake case in Python and camel case in JavaScript",
        "please write that in pascal case user name",
        "the code uses camel case user names",
    ],
)
def test_ordinary_dictation_that_mentions_a_case_style_is_not_claimed(prose):
    """Only "code ..." at the start of the phrase reaches the grammar at all."""
    assert route(prose, _code_handlers()) is None


def test_with_code_mode_off_a_casing_phrase_is_not_claimed():
    assert route("code camel case user name", list(build_handlers(Config()))) is None
