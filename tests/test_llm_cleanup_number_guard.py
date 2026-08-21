"""An LLM rewrite that changed a number passed the guard meant to catch it.

`_tokens_preserved` checked that each meaning-critical token from the input still appeared
in the output, with a plain substring test:

    all(tok in output for tok in _critical_tokens(input_text))

That is right for a word and wrong for a number. ``"100" in "1000"`` is True, so:

    "transfer 100 dollars"  ->  "Transfer 1000 dollars."   accepted
    "upgrade to v2.1"       ->  "Upgrade to v2.10."        accepted

An amount changed by an order of magnitude, in text the user dictated, waved through by
the one check whose stated purpose is that such tokens survive.

A token carrying a digit now has to match on a word boundary. Anything else keeps the
lenient test on purpose: "API" surviving as "APIs" is ordinary reformatting, and
tightening that would reject rewrites this feature exists to make.

## The boundary that nearly broke it

My first version also excluded a following ``.``. That rejects
``"deploy at 0900" -> "Deploy at 0900."`` — a trailing sentence period is the commonest
thing this cleanup *adds*, so the guard would have refused the feature's main job. Three
existing tests caught it immediately. The digit case it was meant to cover (`v2.1` ->
`v2.10`) is already handled by `\\w`, so the `.` was pure cost.
"""

from __future__ import annotations

import dataclasses

import pytest

from yazses.config import Config
from yazses.postprocess.llm_cleanup import LlmCleaner, _token_present, _tokens_preserved


@pytest.fixture
def cleaner():
    cfg = dataclasses.replace(
        Config().filters.disfluency,
        llm_enabled=True,
        llm_endpoint="http://localhost:11434",
    )
    return LlmCleaner(cfg)


def _rewrite(cleaner, src: str, out: str) -> str:
    cleaner._complete = lambda _t, _p=None: out
    return cleaner.cleanup(src)


@pytest.mark.parametrize(
    "src,out",
    [
        pytest.param("transfer 100 dollars", "Transfer 1000 dollars.", id="digit-appended"),
        pytest.param("upgrade to v2.1 today", "Upgrade to v2.10 today.", id="version-extended"),
        pytest.param("call 555 now", "Call 5551 now.", id="phone-extended"),
    ],
)
def test_a_changed_number_is_rejected(cleaner, src: str, out: str) -> None:
    assert _rewrite(cleaner, src, out) == src, "a rewritten number was accepted"


@pytest.mark.parametrize(
    "src,out",
    [
        pytest.param("deploy at 0900", "Deploy at 0900.", id="trailing-period"),
        pytest.param("transfer 100 dollars", "Transfer $100 dollars.", id="currency-prefix"),
        pytest.param("about 50 done", "About 50% done.", id="percent-suffix"),
        pytest.param("meet at 3 PM", "Meet at 3 PM.", id="time"),
        pytest.param("the API is ready", "The APIs are ready.", id="word-pluralised"),
    ],
)
def test_a_legitimate_rewrite_is_still_accepted(cleaner, src: str, out: str) -> None:
    """A guard that refused these would reject the reformatting this feature is for."""
    assert _rewrite(cleaner, src, out) == out


def test_the_trailing_period_case_specifically() -> None:
    """The one my first boundary broke. Kept as its own test, not just a parameter."""
    assert _tokens_preserved("deploy at 0900", "Deploy at 0900.")


def test_words_keep_the_lenient_test() -> None:
    """Deliberate asymmetry: a word may gain a suffix, a number may not."""
    assert _token_present("API", "The APIs are ready.")
    assert not _token_present("100", "Transfer 1000 dollars.")


def test_a_dropped_token_is_still_rejected(cleaner) -> None:
    """The pre-existing behaviour, pinned so the new path cannot lose it."""
    assert _rewrite(cleaner, "transfer 100 dollars", "Transfer some dollars.") == (
        "transfer 100 dollars"
    )


def test_the_length_guards_still_apply(cleaner) -> None:
    """A fix that accepted everything numeric-clean would pass the tests above."""
    src = "send the API key to Bob at 3 PM"
    assert _rewrite(cleaner, src, "Send it.") == src, "too short was accepted"
    long = "Send the API key to Bob at 3 PM. " * 6
    assert _rewrite(cleaner, src, long) == src, "too long was accepted"
    assert _rewrite(cleaner, src, "") == src, "empty was accepted"
