"""The mic guard may not ask a question only a pointer can answer.

The mic-change guard is the one part of the pipeline that *asks*: it offers
[Re-calibrate] [Pin this mic] [Ignore] as buttons, and only as buttons. So the
daemon interrupts you with a question about your microphone that needs a mouse, in
an application whose reason to exist is that some people cannot use one — and the
person seeing it is the one whose dictation has just stopped working.

ADR-022 counts this as one of two daemon-initiated states with no voice-only exit.
This is the half that needs no change to the command-safety gate.

What these tests mostly guard is the *not firing*: "ignore" and "pin" are ordinary
English, and a control word that eats prose is worse than no control word.
"""

from __future__ import annotations

from yazses.audio.mic_prompt import (
    ANSWERS,
    DEFAULT_WINDOW_S,
    MicPrompt,
    match_mic_answer,
)

# --------------------------------------------------------------------------
# matching — and, more importantly, not matching
# --------------------------------------------------------------------------

def test_every_button_can_be_said():
    """The keys must be the ones the click handler already dispatches on.

    If these drift, the spoken route silently answers nothing: `_on_mic_action`
    ignores an unknown key rather than raising.
    """
    assert set(ANSWERS) == {"recalibrate", "pin", "ignore"}
    for key, phrases in ANSWERS.items():
        assert phrases, f"{key} has no spoken form"
        for phrase in phrases:
            assert match_mic_answer(phrase) == key


def test_no_answer_is_also_a_command_safety_control_word():
    """The two vocabularies must stay disjoint, and once they were not.

    `_mic_answer_gate`'s docstring claimed they did not overlap. They did:
    "never mind" was in this module's `ignore` list *and* in
    `DEFAULT_CANCEL_WORDS`, where it means *discard the held command*. Because the
    mic gate runs second, saying it with both pending cancelled the command and left
    the toast unanswered — so the same words did different things depending on state
    the user cannot see, which is what ADR-021's one-phrase rule exists to prevent.

    The claim is now enforced rather than asserted, in both directions: adding a
    phrase to either list re-runs this.
    """
    from yazses.cmdsafety.spoken import (
        DEFAULT_CANCEL_WORDS,
        DEFAULT_CONFIRM_WORDS,
        normalise_utterance,
    )

    control = {normalise_utterance(w) for w in DEFAULT_CONFIRM_WORDS + DEFAULT_CANCEL_WORDS}
    mine = {normalise_utterance(p) for phrases in ANSWERS.values() for p in phrases}
    clash = sorted(control & mine)
    assert not clash, (
        f"{clash} mean both a mic answer and a command-safety control word — with both "
        "pending the user cannot tell which one they just released"
    )


def test_whisper_punctuation_does_not_defeat_an_answer():
    """The decoder punctuates freely; "Ignore." is the same answer as "ignore"."""
    assert match_mic_answer("Ignore.") == "ignore"
    assert match_mic_answer("  Pin this mic!  ") == "pin"
    assert match_mic_answer("Re-calibrate") == "recalibrate"


def test_prose_containing_the_word_is_still_prose():
    """The whole utterance must be the answer.

    This is the lesson `commands/revise.py` already learned by anchoring at both
    ends: a suffix match swallows "click undo" instead of typing it.
    """
    for prose in (
        "please ignore the second paragraph",
        "ignore that for now and move on",
        "pin this mic to the wall",
        "we should pin the mic down before Friday",
        "I had to recalibrate the whole rig afterwards",
    ):
        assert match_mic_answer(prose) is None, f"{prose!r} was eaten as a control word"


def test_empty_and_junk_are_not_answers():
    assert match_mic_answer("") is None
    assert match_mic_answer("   ") is None
    assert match_mic_answer("...") is None


# --------------------------------------------------------------------------
# the window — an answer only counts while the question is open
# --------------------------------------------------------------------------

def test_an_unasked_question_cannot_be_answered():
    """Otherwise "ignore" is a live control word from daemon start."""
    assert MicPrompt().is_open(now=100.0, window_s=DEFAULT_WINDOW_S) is False


def test_the_window_closes():
    prompt = MicPrompt()
    prompt.ask(now=1000.0)
    assert prompt.is_open(1000.0, 45.0) is True
    assert prompt.is_open(1044.9, 45.0) is True
    assert prompt.is_open(1045.1, 45.0) is False, (
        "a toast from a minute ago still arms the word 'ignore'"
    )


def test_answering_closes_the_question():
    prompt = MicPrompt()
    prompt.ask(now=0.0)
    prompt.close()
    assert prompt.is_open(0.0, 45.0) is False


def test_a_zero_window_disables_the_spoken_route_entirely():
    prompt = MicPrompt()
    prompt.ask(now=0.0)
    assert prompt.is_open(0.0, 0.0) is False


def test_a_backwards_clock_leaves_the_question_open():
    """Being stranded with an unanswerable prompt is worse than a wide window.

    `time.time()` is wall-clock and can step backwards; the failure mode to avoid
    is the user saying "ignore" and being ignored.
    """
    prompt = MicPrompt()
    prompt.ask(now=1000.0)
    assert prompt.is_open(now=990.0, window_s=45.0) is True


def test_a_later_question_replaces_the_earlier_one():
    """The toast is replaced rather than stacked, so there is one open question."""
    prompt = MicPrompt()
    prompt.ask(now=0.0)
    prompt.ask(now=1000.0)
    assert prompt.is_open(1030.0, 45.0) is True
