"""The second wiring batch off #164 — seven capabilities that had no caller.

Each is covered three ways, the shape the first batch settled on: it does nothing
while off, it does the right thing when on, and the precondition it depends on is
real rather than assumed. The negative cases carry most of the weight here: four of
the seven answer to a *phrase*, and an over-eager trigger does not fail visibly — it
silently eats a sentence the user meant to type.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.spokencmd.registry import build_handlers
from yazses.spokencmd.router import route

SPOKEN = ("condense", "diagramvox", "spreadsheet", "echo")
STATE_DRIVEN = ("fieldaware", "srpace", "suggestmode")


# --------------------------------------------------------------------------- off

@pytest.mark.parametrize("slug", SPOKEN + STATE_DRIVEN)
def test_every_wired_capability_is_off_in_a_default_config(slug: str) -> None:
    assert getattr(Config(), slug).enabled is False


def test_no_spoken_handler_exists_until_its_flag_is_set() -> None:
    """A stock install pays for none of them — not even the import."""
    assert build_handlers(Config()) == []


# ------------------------------------------------------------------- the router

def _handlers(*slugs: str):
    config = Config()
    for slug in slugs:
        getattr(config, slug).enabled = True
    return config, build_handlers(config)


def test_condense_keeps_the_sentences_that_carry_the_content() -> None:
    _config, handlers = _handlers("condense")
    result = route(
        "condense We should ship it. Right. The wheel is broken and needs a bearing. Okay.",
        handlers,
    )
    assert result is not None and result.slug == "condense"
    # The interjections are exactly what the core's content-word floor exists to drop.
    assert "Right." not in result.text
    assert "Okay." not in result.text
    assert "wheel is broken" in result.text


def test_a_diagram_needs_an_edge_and_not_merely_the_word() -> None:
    """`parse_graph_utterance` answers a one-node graph for any prose at all.

    Without the edge check in the handler, "diagram the release process" types a
    flowchart wrapper around a fragment of the user's own sentence.
    """
    _config, handlers = _handlers("diagramvox")

    claimed = route("diagram login goes to dashboard if valid", handlers)
    assert claimed is not None
    assert "flowchart" in claimed.text
    assert "-->|valid|" in claimed.text

    assert route("diagram the release process", handlers) is None


def test_the_diagram_flavor_switches_the_rendered_syntax() -> None:
    config = Config()
    config.diagramvox.enabled = True
    config.diagramvox.flavor = "dot"
    result = route("diagram a goes to b", build_handlers(config))
    assert result is not None
    assert result.text.startswith("digraph G {")


def test_a_grid_move_is_a_key_sequence_and_never_typed_text() -> None:
    _config, handlers = _handlers("spreadsheet")
    result = route("next cell", handlers)
    assert result is not None
    assert result.text is None, "a movement must not be typed as words"
    assert result.action == ("keys", ["Tab"])


@pytest.mark.parametrize(
    "sentence",
    [
        "I want to move up in the company",
        "the next cell in the culture had died",
        "we should move left of the entrance",
    ],
)
def test_a_sentence_containing_a_movement_phrase_is_not_a_movement(sentence: str) -> None:
    """The trigger is a whole-utterance lookup, which is stricter than the anchor.

    "move up" and "next cell" are ordinary English. A `search`-based trigger would
    claim all three of these and type nothing while silently pressing a key.
    """
    _config, handlers = _handlers("spreadsheet")
    assert route(sentence, handlers) is None


def test_echo_runs_without_a_text_target_because_it_types_nothing() -> None:
    _config, handlers = _handlers("echo")
    assert route("play that back", handlers, can_type=False) is not None


def test_echo_keeps_the_quotes_that_choose_the_word() -> None:
    """`tidy` strips outer quotes; the payload must not be tidied.

    `resolve_playback_target` reads "play the word 'weather'" by its *quoted* token.
    A stripped closing quote drops it to the bare-token branch, where the leading
    apostrophe stops it matching the span text — so the request degrades in silence
    to replaying the whole clip instead of the one word asked for.
    """
    from yazses.echo.span import build_span_index, resolve_playback_target

    _config, handlers = _handlers("echo")
    result = route("play 'weather'", handlers, can_type=False)
    assert result is not None
    payload = result.action[1]
    assert payload == "play 'weather'"

    spans = build_span_index(
        [("the", 0.0, 0.2), ("weather", 0.2, 0.7), ("is", 0.7, 0.9), ("here", 0.9, 1.3)]
    )
    assert resolve_playback_target(payload, spans) == (0.2, 0.7)


@pytest.mark.parametrize(
    "sentence", ["we should play the album tonight", "the replay was close", "repeat business"]
)
def test_ordinary_speech_is_not_a_playback_request(sentence: str) -> None:
    _config, handlers = _handlers("echo")
    assert route(sentence, handlers, can_type=False) is None


def test_the_keys_action_reaches_the_injector_as_a_key_sequence() -> None:
    """The daemon half: `("keys", [...])` must drive `inject_key_sequence`, not `inject`."""
    typed: list[str] = []
    keys: list[list[str]] = []
    fake = SimpleNamespace(
        _timers=None,
        _active_injector=lambda: SimpleNamespace(
            inject=typed.append, inject_key_sequence=keys.append
        ),
        _notify_spoken=lambda message: None,
    )
    event: dict = {}
    Daemon._run_spoken_action(
        fake, SimpleNamespace(action=("keys", ["Tab"]), message=None), event
    )
    assert keys == [["Tab"]]
    assert typed == [], "a movement was typed as text"
    assert event["spoken_action"] == "keys"


# -------------------------------------------------------------- fieldaware

def _fieldaware_daemon(role: str):
    config = Config()
    config.fieldaware.enabled = True
    notes: list[str] = []
    fake = SimpleNamespace(
        _config=config,
        _lock=__import__("threading").Lock(),
        _state=SimpleNamespace(field_role=role),
        _notify_spoken=notes.append,
    )
    return fake, notes


def test_dictation_is_refused_into_a_password_field() -> None:
    """The gap this closes: a password box *is* editable text.

    `target_ok` looks at one and correctly says "yes, type here", so the no-text-target
    guard cannot catch this. Only the role can.
    """
    fake, notes = _fieldaware_daemon("password text")
    event: dict = {}
    assert Daemon._fieldaware_shape(fake, "hunter two", event) is None
    assert event["discard_reason"] == "fieldaware_refused"
    assert notes, "the user was given no reason for the missing text"


def test_a_refusal_does_not_put_the_text_on_the_clipboard() -> None:
    """The no-text-target guard rescues words to the clipboard. This one must not.

    That guard is saving words from a window that cannot hold them; this one is
    refusing a destination the user chose, and the text it holds is what they were
    about to put in a password field. `_fieldaware_shape` therefore has no clipboard
    call at all — asserted on the source so the behaviour cannot be added quietly.
    """
    import inspect

    source = inspect.getsource(Daemon._fieldaware_shape)
    assert "clipboard" not in source.lower().replace("clipboard for the next", "")
    assert "set_clipboard" not in source


def test_a_number_field_gets_digits_and_nothing_else() -> None:
    fake, _notes = _fieldaware_daemon("spin button")
    assert Daemon._fieldaware_shape(fake, "four two", {}) == ""
    assert Daemon._fieldaware_shape(fake, "42", {}) == "42"


def test_an_unknown_role_leaves_the_text_completely_alone() -> None:
    """No accessibility bus means no role, and that must be inert, not a guess."""
    fake, _notes = _fieldaware_daemon("")
    event: dict = {}
    assert Daemon._fieldaware_shape(fake, "hello there", event) == "hello there"
    assert "field_role" not in event


def test_the_role_read_has_no_x11_fallback() -> None:
    """X11 reports a *window* class, never the focused widget's role.

    A fallback could only guess, and guessing "not a password field" is the one
    direction that turns this guard off exactly when it is needed.
    """
    from yazses.inject.target import TargetDetector

    detector = TargetDetector(atspi=None, xdotool_fn=lambda: True,
                              xdotool_class_fn=lambda: "gnome-terminal")
    assert detector.get_field_role() == ""


# ------------------------------------------------------------------ srpace

def test_paced_injection_arrives_in_clause_order() -> None:
    from yazses.srpace.schedule import plan_injection_schedule

    schedule = plan_injection_schedule("First clause, then a second one. And a third.")
    assert len(schedule) >= 2
    assert schedule[0].delay_ms == 0
    delays = [c.delay_ms for c in schedule]
    assert delays == sorted(delays), "chunks must be scheduled forward in time"


def test_pacing_and_streaming_injection_are_mutually_exclusive() -> None:
    """Both write progressively; running them together interleaves two writers."""
    import inspect

    source = inspect.getsource(Daemon._on_hold_end)
    stream = source.index("stream_injector.commit(text)")
    paced = source.index("elif self._config.srpace.enabled:")
    assert stream < paced, "srpace must be an elif on the streaming branch, not a second if"


# ------------------------------------------------------------- suggestmode

def test_a_suggestion_is_marked_up_rather_than_typed_as_final_text() -> None:
    from yazses.suggestmode.critic import to_criticmarkup

    assert to_criticmarkup("insert", "ship it") == "{++ship it++}"


def test_the_continuation_space_stays_outside_the_marker() -> None:
    """The separating space belongs between the suggestions, not inside one."""
    text = " ship it"
    lead = text[: len(text) - len(text.lstrip())]
    body = text.strip()
    from yazses.suggestmode.critic import to_criticmarkup

    assert lead + to_criticmarkup("insert", body) == " {++ship it++}"


def test_a_rewrite_becomes_a_tracked_change_not_a_silent_replacement() -> None:
    from yazses.suggestmode.critic import diff_to_critic

    out = diff_to_critic("the quick brown fox", "the slow brown fox")
    assert "{~~quick~>slow~~}" in out
    assert "the" in out and "brown fox" in out
