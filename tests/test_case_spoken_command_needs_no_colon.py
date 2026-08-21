"""A voice command must not require punctuation that cannot be spoken.

`yazses case` documents its spoken form as *"make this snake case: …"*, and the CLI
stripped the directive with:

    if ":" in src:
        payload = src.split(":", 1)[1]

**A colon cannot be dictated.** Said aloud, the directive was recased along with the
text, and the command answered confidently:

    make this snake case: hello world  ->  hello_world                       ✓
    make this snake case hello world   ->  make_this_snake_case_hello_world  ✗

Not an error — a plausible wrong answer, which is exactly the failure mode `gitvoice`
takes care to avoid ("a misheard command produces an error, not a plausible wrong
command"). It is also the same defect class as the `gitvoice` branch separators fixed
alongside it: **the voice path required punctuation the voice cannot produce.**

`split_style_command` locates the style phrase and takes the remainder, so the colon
became optional rather than mandatory. Two details are load-bearing:

* the payload is sliced from the **original** string, not the lower-cased copy used for
  matching, or `make this snake case MyThing` would lose its capitals before
  `transform_case` ever sees them;
* phrases are tried **longest first**, so `snake case` wins over the bare `snake` that
  `_STYLES` also contains — otherwise the payload keeps a stray "case".
"""

from __future__ import annotations

import pytest

from yazses.casetransform.transform import (
    _STYLES,
    detect_style_command,
    split_style_command,
    transform_case,
)


def _spoken(text: str) -> str:
    """What `yazses case <text>` prints, without going through Typer."""
    style, payload = split_style_command(text)
    assert style is not None, f"no style detected in {text!r}"
    return transform_case(payload.strip(), style)


@pytest.mark.parametrize(
    "said,expected",
    [
        # The defect: identical to the documented form but without the colon.
        ("make this snake case hello world", "hello_world"),
        ("make this snake case: hello world", "hello_world"),
        ("make this camel case my variable name", "myVariableName"),
        ("make this kebab case Fix Tray Crash", "fix-tray-crash"),
        ("convert to constant case max retries", "MAX_RETRIES"),
        ("change to pascal case user profile", "UserProfile"),
        ("make this upper case hello", "HELLO"),
        # The directive trailing the text it applies to, which is also spoken.
        ("hello world in snake case", "hello_world"),
        ("hello world as constant case", "HELLO_WORLD"),
    ],
)
def test_the_directive_never_reaches_the_output(said: str, expected: str) -> None:
    assert _spoken(said) == expected


def test_the_colon_form_and_the_spoken_form_agree() -> None:
    """The whole point: punctuation may help, but must not be required."""
    assert _spoken("make this snake case: hello world") == _spoken(
        "make this snake case hello world"
    )


def test_the_payload_keeps_its_original_case() -> None:
    """Sliced from the raw string, not the lower-cased copy used for matching.

    `transform_case` splits camelCase to find word boundaries, so losing the capitals
    first would silently change the result — `MyThing` -> `mything` -> `mything`.
    """
    style, payload = split_style_command("make this snake case MyThing")
    assert payload.strip() == "MyThing"
    assert transform_case(payload.strip(), style) == "my_thing"


def test_the_longest_style_phrase_wins() -> None:
    """`_STYLES` holds both "snake case" and a bare "snake"."""
    assert {"snake", "snake case"} <= set(_STYLES), "premise gone; revisit the ordering"
    _style, payload = split_style_command("make this snake case hello")
    assert "case" not in payload, f"a shorter phrase matched first: {payload!r}"


def test_plain_text_is_still_refused() -> None:
    """No directive means no style — the CLI exits 1 rather than guessing one."""
    style, payload = split_style_command("just some ordinary words")
    assert style is None
    assert payload == "just some ordinary words"


def test_the_old_accessor_still_answers() -> None:
    """`detect_style_command` is the published name; it now delegates."""
    assert detect_style_command("make this kebab case hello") == "kebab"
    assert detect_style_command("nothing here") is None
