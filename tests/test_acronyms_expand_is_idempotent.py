"""Running `yazses acronyms expand` twice must not corrupt the document.

`expand_document` writes an acronym's first use as ``Full Name (ACR)``. It did not notice
when the text *already* said that, so it expanded the ``ACR`` inside its own parentheses:

    once   The Application Programming Interface (API) is stable.
    twice  The Application Programming Interface (Application Programming Interface (API)) is stable.
    thrice ... (Application Programming Interface (Application Programming Interface (API)))

Each run nested one level deeper, and nothing warned. Running the command again after
editing a document is the ordinary thing to do, so this was reachable by simply using the
feature as intended.

## The fix was already in the module

`AcronymState.observe` is documented as *"Learn 'Full Name (ACR)' definitions already
present in text (**marks them expanded**)"* — written for precisely this, and never
called by `expand_document`. The repair is that one call, so the rule for "already
expanded" stays in one place rather than becoming a second, subtly different check.
"""

from __future__ import annotations

import pytest

from yazses.acronyms.glossary import AcronymState, expand_document

DEFS = {
    "API": "Application Programming Interface",
    "CPU": "Central Processing Unit",
}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("The API is stable. We use the API daily.", id="single-acronym"),
        pytest.param("The API and the CPU. Later the API and the CPU again.", id="two"),
        pytest.param("No acronyms here at all.", id="none"),
        pytest.param("The GPU is not in the glossary.", id="unknown-acronym"),
        pytest.param("", id="empty"),
    ],
)
def test_expanding_twice_changes_nothing(text: str) -> None:
    once = expand_document(text, DEFS)
    twice = expand_document(once, DEFS)
    assert once == twice, (
        "a second expansion altered the document — the acronym inside its own "
        f"parentheses was expanded again:\n  once : {once}\n  twice: {twice}"
    )
    assert expand_document(twice, DEFS) == once, "it compounds on the third run"


def test_text_that_is_already_expanded_is_left_alone() -> None:
    """The shape a user's document is in after they ran it once, or wrote it by hand."""
    text = "Application Programming Interface (API) already expanded, then API."
    assert expand_document(text, DEFS) == text


def test_first_use_is_still_expanded() -> None:
    """The feature must still do its job — a fix that expanded nothing would pass above."""
    out = expand_document("The API is stable. We use the API daily.", DEFS)
    assert out.startswith("The Application Programming Interface (API) is stable.")
    assert out.count("Application Programming Interface") == 1, "expanded more than once"
    assert out.endswith("We use the API daily."), "later uses must stay contracted"


def test_an_acronym_with_no_definition_passes_through() -> None:
    assert expand_document("The GPU is fine.", DEFS) == "The GPU is fine."


def test_observe_is_what_marks_them_expanded() -> None:
    """Pin the seam the fix uses, so a refactor that drops it fails here with the reason."""
    state = AcronymState()
    state.define("API", "Application Programming Interface")
    state.observe("Application Programming Interface (API) appears here")
    assert state.resolve("API") == "API", (
        "observe no longer marks an already-written expansion as expanded, so "
        "expand_document will start nesting again"
    )


def test_a_fresh_state_still_expands() -> None:
    """The counterpart: without observing, the first resolve expands. Both halves matter."""
    state = AcronymState()
    state.define("API", "Application Programming Interface")
    assert state.resolve("API") == "Application Programming Interface (API)"
    assert state.resolve("API") == "API"
