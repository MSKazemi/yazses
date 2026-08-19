"""The privacy statement is a promise, and it used to make one it could not keep.

It said, unconditionally:

    The one time YazSes *does* need the network is the **first** run, to download the
    speech model from Hugging Face. After that it never needs it again. `yazses update`
    is the only other outbound action, and only when you run it yourself.

True of the default configuration, and false the moment you enable anything. ADR-019's own
inventory lists five modules that download on `user enables X`, plus four dependencies that
resolve a model id against huggingface.co -- one of them carrying the user's HF token. A
reader who turned on read-back, or diarization, or gaze, and then watched a connection open
would have caught the project in a falsifiable sentence on its privacy page.

That is worse for the project than the accurate version, and the accurate version is barely
weaker: nothing you *said* ever leaves, which is the claim that matters and is still true.

These tests pin the shape of the correction, not its prose. They fail if the unconditional
claim comes back, if the enumeration stops being reachable from the page, or if the one
credentialed fetch loses its own sentence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PRIVACY = REPO / "docs" / "privacy-statement.md"
ADR = REPO / "design" / "adr" / "adr-019-egress-inventory-and-escalation.md"


@pytest.fixture(scope="module")
def page() -> str:
    """The page with its line wrapping collapsed.

    Every assertion here quotes a *sentence*, and a sentence in this file is wrapped at
    whatever column it happened to reach. Matching the raw text makes a test that passes
    or fails on a re-wrap, which is a reformat, not a change of meaning -- and the first
    version of this file failed exactly that way.
    """
    return " ".join(PRIVACY.read_text(encoding="utf-8").split())


def test_the_first_run_claim_is_scoped_to_the_default_configuration(page: str) -> None:
    """The sentence is only true with every optional feature off, so it must say so."""
    assert "The one time YazSes *does* need the network is the **first** run" not in page, (
        "the unconditional first-run claim is back. Enabling read-back, diarization, "
        "gaze, a different speech engine or LLM cleanup each downloads a model later."
    )
    assert "in its **default** configuration is the **first**" in page


def test_the_page_says_optional_features_fetch_their_own_models(page: str) -> None:
    assert "downloads that model once, when you enable it" in page
    assert "none of them sends anything" in page, (
        "the correction must keep the strong half of the claim -- these are downloads, "
        "not uploads -- or it reads as an admission that something is being sent"
    )


def test_the_credentialed_fetch_has_its_own_sentence(page: str) -> None:
    """An anonymous model GET and one carrying your account token are different facts.

    Everything else on this page can honestly say the request identifies nobody. This one
    cannot, and burying it in a list of downloads is how a true page becomes a misleading
    one.
    """
    assert "pyannote" in page
    assert "Hugging Face token" in page
    assert "who** is asking" in page


def test_the_release_watcher_is_not_described_as_manual_only(page: str) -> None:
    """`[general] update_check` is opt-in, but when it is on it is genuinely automatic.

    "Update checks are a manual, explicit action" was the whole answer before; a user who
    switched the watcher on and then read this page would have been told their machine
    does something it does not do.
    """
    assert "update_check" in page
    assert "makes no automatic outbound connections in its default configuration" in page


def test_the_page_points_at_the_enforced_inventory(page: str) -> None:
    """The page's authority is that the list is enforced, not that it is long."""
    assert "adr-019-egress-inventory-and-escalation.md" in page
    assert "a test fails the build" in page
    assert ADR.is_file(), "the page links at an inventory that must exist to be checked"


def test_every_feature_the_page_names_as_a_downloader_really_is_one() -> None:
    """The correction lists five capabilities by name. If one of them stopped fetching, the
    page would be overstating what leaves -- the opposite failure, and just as wrong."""
    from tests.test_egress_inventory import DEPENDENCY_FETCH, FETCH

    declared = set(FETCH) | set(DEPENDENCY_FETCH)
    for module in (
        "tts/download.py",              # read-back
        "gaze/download.py",             # gaze targeting
        "recimport/download.py",        # speaker diarization
        "commands/model_manager.py",    # offline LLM cleanup
        "stt/parakeet.py",              # a different speech engine
    ):
        assert module in declared, (
            f"{module} is named on the privacy page as a feature that downloads a model, "
            f"but it is no longer in the egress inventory"
        )
