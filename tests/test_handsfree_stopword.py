"""The voice stop word: pure matching, config, preset and daemon glue (ADR-v2-148).

A hands-free user says "pause hands free" and every camera input stops, without touching a
thing. The hazard is the other direction: a stop word that fires on ordinary dictation teaches
people to switch it off (AGENTS.md rule 9). So most of this file is near-misses -- sentences that
contain the words and must be typed -- plus the two properties that make a stop safe: it only ever
pauses, and the words are never typed.

Synthetic text transcripts only; no audio, no camera, no socket. Whether the recogniser reliably
transcribes the phrase is NOT tested here and is not known (see docs/how-to/hands-free-voice-stop.md).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import types
from pathlib import Path

import pytest

from yazses.config import Config, load_config_checked
from yazses.core.daemon import Daemon
from yazses.handsfree import preset, stopword
from yazses.handsfree.safety import HandsFreeSafety, SafetyState
from yazses.handsfree.stopword import DEFAULT_STOP_PHRASE, matches, normalise, problem

PHRASE = DEFAULT_STOP_PHRASE


# --------------------------------------------------------------------------- pure matching


@pytest.mark.parametrize(
    "heard",
    [
        "pause hands free",
        "Pause hands free",
        "Pause hands free.",
        "  pause   hands   free  ",
        "PAUSE HANDS FREE!",
        "Pause hands-free.",
        "pause handsfree",
        "Pause, hands free",          # a recogniser's comma inside the phrase
        "pause hands‑free",     # non-breaking hyphen
        "ｐause hands free",     # full-width letter: NFKC folds it
    ],
)
def test_the_phrase_and_its_spacing_variants_match(heard):
    assert matches(heard, PHRASE), heard


@pytest.mark.parametrize(
    "dictated",
    [
        # the sentences the task names: contain "pause" and "hands free"
        "I will pause hands free mode while I type this",
        "please pause hands free",
        "pause hands free please",
        "Let's pause hands free for a second and think",
        "to pause hands free input, press the Pause button",
        "pause the hands free kit",
        "hands free pause",
        "pause hands",
        "hands free",
        "pause",
        "free",
        "pause hands free pause hands free",     # doubled: not the phrase
        "pause hands free and resume",
        "unpause hands free",
        "pause hands freedom",
        "pausing hands free",
        "pause hands free, then open the browser",
        "he said pause hands free",
        "",
        "   ",
        "...",
    ],
)
def test_a_sentence_that_merely_contains_the_words_is_never_a_stop(dictated):
    assert not matches(dictated, PHRASE), dictated


def test_the_match_is_equality_on_the_whole_utterance_not_a_search():
    # The structural guarantee behind the near-miss list: no `in`/`re.search` on the transcript.
    tree = ast.parse(textwrap.dedent(inspect.getsource(stopword.matches)))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr in {"search", "findall", "finditer"}]
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
                and any(isinstance(op, (ast.In, ast.NotIn)) for op in n.ops)]
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
            and any(isinstance(op, ast.Eq) for op in n.ops)]


def test_a_configured_phrase_other_than_the_default_works_and_the_default_stops_working():
    custom = "freeze the pointer"
    assert matches("Freeze the pointer.", custom)
    assert not matches("pause hands free", custom)
    assert not matches("I want to freeze the pointer now", custom)


def test_off_and_unusable_phrases_never_match_anything():
    assert not matches("pause hands free", "")
    assert not matches("pause hands free", "   ")
    assert not matches("stop", "stop")                 # one word: refused, not honoured loosely
    assert not matches("", "")
    assert not matches("pause hands free", None)       # type: ignore[arg-type]


def test_a_long_dictated_corpus_never_fires_on_ordinary_prose():
    # Rule 9 in numbers: not one of these ordinary sentences may be a stop. Generated from words
    # that include every word of the phrase, in every order, so only the exact whole utterance passes.
    import itertools

    words = ["pause", "hands", "free", "the", "please"]
    fired = []
    for n in range(1, 5):
        for combo in itertools.permutations(words, n):
            text = " ".join(combo)
            if matches(text, PHRASE):
                fired.append(text)
    assert fired == ["pause hands free"]


def test_normalise_is_plain_casefold_and_whitespace():
    assert normalise("  Pause  Hands-Free. ") == "pause hands free"
    assert normalise("") == "" == normalise(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize("ok", ["", "pause hands free", "freeze the pointer", "a b c d e f", "pause hands-free"])
def test_usable_phrases(ok):
    assert problem(ok) is None


@pytest.mark.parametrize(
    "bad",
    ["stop", "pause", "  stop  ", "one two three four five six seven", "!!! ???", "---", 5, None, ["a", "b"]],
)
def test_unusable_phrases_say_why(bad):
    assert problem(bad)


def test_the_default_phrase_is_itself_valid():
    assert problem(DEFAULT_STOP_PHRASE) is None


# --------------------------------------------------------------------------- it can only pause


def test_the_module_offers_no_way_to_resume():
    public = {n for n in dir(stopword) if not n.startswith("_")}
    assert not [n for n in public if "resume" in n.lower()]
    names = {n.id for n in ast.walk(ast.parse(Path(stopword.__file__).read_text(encoding="utf-8")))
             if isinstance(n, ast.Name)}
    assert "resume" not in names


def test_the_module_imports_only_the_standard_library():
    tree = ast.parse(Path(stopword.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    import sys

    assert imported <= set(sys.stdlib_module_names), imported


# --------------------------------------------------------------------------- config


def _load(tmp_path: Path, text: str, name: str = "c.toml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_config_checked(path)


def test_off_by_default_everywhere():
    assert Config().handsfree_safety.stop_phrase == ""
    assert Config().handsfree.voice_stop is True  # a component switch; inert until enabled


def test_a_plain_install_has_no_stop_phrase(tmp_path):
    loaded = _load(tmp_path, "[stt]\nmodel = 'tiny'\n")
    assert loaded.config.handsfree_safety.stop_phrase == ""
    loaded = _load(tmp_path, "[handsfree_safety]\nenabled = true\n", "g.toml")
    assert loaded.config.handsfree_safety.stop_phrase == "", "the global stop alone does not turn the voice stop on"


def test_the_preset_supplies_the_provisional_phrase(tmp_path):
    loaded = _load(tmp_path, "[handsfree]\nenabled = true\n")
    assert loaded.problems == []
    assert loaded.config.handsfree_safety.stop_phrase == "pause hands free"
    item = next(r for r in preset.expand({"handsfree": {"enabled": True}}).resolved
                if r.setting.key == "stop_phrase")
    assert item.source == "preset" and not item.setting.protected
    assert "provisional" in item.setting.why


def test_the_users_own_phrase_wins_over_the_preset(tmp_path):
    loaded = _load(tmp_path, '[handsfree]\nenabled = true\n[handsfree_safety]\nstop_phrase = "freeze the pointer"\n')
    assert loaded.config.handsfree_safety.stop_phrase == "freeze the pointer"
    assert loaded.config.handsfree_safety.enabled is True, "the preset still supplies the rest of the safety floor"


def test_the_user_can_turn_the_voice_stop_off_inside_the_preset_two_ways(tmp_path):
    a = _load(tmp_path, "[handsfree]\nenabled = true\nvoice_stop = false\n", "a.toml")
    assert a.config.handsfree_safety.stop_phrase == ""
    b = _load(tmp_path, '[handsfree]\nenabled = true\n[handsfree_safety]\nstop_phrase = ""\n', "b.toml")
    assert b.config.handsfree_safety.stop_phrase == ""
    assert a.config.headpointer.enabled and b.config.headpointer.enabled, "only the voice stop is off"


def test_the_stop_phrase_is_not_a_protected_setting(tmp_path):
    # Weakening it must not refuse the whole preset; the safety floor is the gate, not the phrase.
    loaded = _load(tmp_path, '[handsfree]\nenabled = true\n[handsfree_safety]\nstop_phrase = ""\n')
    assert preset.expand({"handsfree": {"enabled": True}, "handsfree_safety": {"stop_phrase": ""}}).refusal == ""
    assert loaded.config.handsfree_safety.enabled


@pytest.mark.parametrize("bad", ['"stop"', '"pause"', '"a b c d e f g"', '"???"', "5"])
def test_an_unusable_phrase_is_reported_at_load_and_leaves_the_stop_word_off(tmp_path, bad):
    loaded = _load(tmp_path, f"[handsfree_safety]\nstop_phrase = {bad}\n")
    assert loaded.config.handsfree_safety.stop_phrase == ""
    assert any(p.section == "handsfree_safety" and p.key == "stop_phrase" for p in loaded.problems)


def test_an_unusable_phrase_inside_the_preset_is_off_not_the_default(tmp_path):
    # A bad value must never become a looser one or silently revert to the preset's phrase.
    loaded = _load(tmp_path, '[handsfree]\nenabled = true\n[handsfree_safety]\nstop_phrase = "stop"\n')
    assert loaded.config.handsfree_safety.stop_phrase == ""
    assert loaded.problems


def test_explain_lists_the_voice_stop_and_says_it_cannot_resume():
    text = "\n".join(preset.render(preset.expand({}, assume_enabled=True), enabled_in_file=False))
    assert "stop_phrase" in text and "pause hands free" in text
    assert "only pauses" in text and "yazses handsfree resume" in text


# --------------------------------------------------------------------------- daemon glue


class _Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def _daemon(mocker, *, phrase=PHRASE, armed=True):
    clock = _Clock()
    gate = HandsFreeSafety(("headpointer", "facegesture"), clock=clock)
    if armed:
        gate.sample("headpointer")
        gate.sample("facegesture")
        assert gate.resume().ok
    cfg = Config()
    cfg.handsfree_safety.enabled = True
    cfg.handsfree_safety.stop_phrase = phrase
    d = types.SimpleNamespace(
        _config=cfg, _handsfree_safety=gate, _headpointer=None,
        _earcon=mocker.MagicMock(), _gaze_targeter=None, _extra_activations=[],
    )
    d._handle_handsfree = lambda request: Daemon._handle_handsfree(d, request)
    notify = mocker.patch("yazses.system.notify.notify")
    return d, gate, notify


def _stop(d, text, event=None):
    return Daemon._try_voice_stop(d, text, {} if event is None else event)


def test_the_stop_phrase_pauses_every_source_and_is_consumed(mocker):
    d, gate, notify = _daemon(mocker)
    event: dict = {}
    assert _stop(d, "Pause hands free.", event) is True
    assert gate.status().state is SafetyState.PAUSED
    assert gate.gate("headpointer").allowed is False and gate.gate("facegesture").allowed is False
    assert event["intent_type"] == "handsfree_stop" and event["command_mode"] is True


def test_it_gives_feedback_through_the_notification_and_earcon_paths(mocker):
    d, _gate, notify = _daemon(mocker)
    _stop(d, "pause hands free")
    notify.assert_called_once()
    title, body = notify.call_args.args
    assert "hands-free" in title and "Paused by voice" in body
    assert "yazses handsfree resume" in body, "the way back must be named, since voice cannot do it"
    d._earcon.play.assert_called_once()


@pytest.mark.parametrize("dictated", [
    "I will pause hands free mode while I type this",
    "please pause hands free",
    "hands free",
    "pause",
])
def test_dictation_that_contains_the_words_pauses_nothing_and_is_not_consumed(mocker, dictated):
    d, gate, notify = _daemon(mocker)
    event: dict = {}
    assert _stop(d, dictated, event) is False
    assert gate.status().state is SafetyState.ACTIVE
    assert gate.gate("headpointer").allowed is True
    assert event == {}, "a non-match must not even annotate the burst"
    notify.assert_not_called()


def test_with_no_phrase_configured_nothing_is_consumed_even_the_default_words(mocker):
    d, gate, notify = _daemon(mocker, phrase="")
    assert _stop(d, "pause hands free") is False
    assert gate.status().state is SafetyState.ACTIVE
    notify.assert_not_called()


def test_it_works_while_everything_is_already_paused_and_still_consumes(mocker):
    d, gate, notify = _daemon(mocker, armed=False)   # never armed: the gate starts PAUSED
    assert gate.status().state is SafetyState.PAUSED
    assert _stop(d, "pause hands free") is True
    assert gate.status().state is SafetyState.PAUSED
    notify.assert_called_once()


def test_it_works_from_faulted_too(mocker):
    d, gate, _ = _daemon(mocker)
    _Clock.now += 60_000.0   # the camera went quiet
    assert gate.status().state is SafetyState.FAULTED
    try:
        assert _stop(d, "pause hands free") is True
    finally:
        _Clock.now = 1000.0
    assert gate.status().state is SafetyState.PAUSED


def test_saying_it_never_resumes_anything(mocker):
    d, gate, _ = _daemon(mocker)
    _stop(d, "pause hands free")
    gate.sample("headpointer")
    gate.sample("facegesture")        # the camera is healthy again
    for _ in range(3):
        _stop(d, "pause hands free")
    assert gate.status().state is SafetyState.PAUSED, "only an explicit resume may re-arm"
    for word in ("resume hands free", "resume", "start hands free", "continue hands free"):
        assert _stop(d, word) is False
    assert gate.status().state is SafetyState.PAUSED


def test_a_stop_that_cannot_pause_is_still_consumed_and_says_so(mocker):
    # Global stop off and no pointer: nothing to pause. The words must not be typed, and the
    # user must be told it did not take effect (they would otherwise believe they were stopped).
    d, _gate, notify = _daemon(mocker)
    d._handsfree_safety = None
    assert _stop(d, "pause hands free") is True
    body = notify.call_args.args[1]
    assert "did not pause" in body and "global stop is off" in body


def test_a_failing_notification_cannot_break_dictation(mocker):
    d, gate, notify = _daemon(mocker)
    notify.side_effect = RuntimeError("no notifier")
    assert _stop(d, "pause hands free") is True
    assert gate.status().state is SafetyState.PAUSED


def test_a_failing_pause_is_consumed_and_reported(mocker):
    d, _gate, notify = _daemon(mocker)

    def boom(_request):
        raise RuntimeError("gate exploded")

    d._handle_handsfree = boom
    assert _stop(d, "pause hands free") is True
    assert "did not pause" in notify.call_args.args[1]


# --------------------------------------------------------------------------- position in the pipeline


def _calls_in_on_hold_end() -> list[tuple[str, int]]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    return sorted(
        (n.func.attr, n.lineno) for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    )


def test_the_stop_is_checked_before_anything_can_type_or_reinterpret_the_utterance():
    calls = _calls_in_on_hold_end()
    first = {}
    for name, line in calls:
        first.setdefault(name, line)
    assert "_try_voice_stop" in first
    for later in ("_try_deixis", "_try_window_action", "_cmdsafety_gate", "_stage_or_commit", "inject"):
        if later in first:
            assert first["_try_voice_stop"] < first[later], later


def test_a_consumed_stop_returns_before_the_injector_is_reached():
    src = textwrap.dedent(inspect.getsource(Daemon._on_hold_end))
    tree = ast.parse(src)
    guard = next(
        n for n in ast.walk(tree) if isinstance(n, ast.If)
        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "_try_voice_stop" for c in ast.walk(n.test))
    )
    assert any(isinstance(n, ast.Return) for n in guard.body), "a stop must end the burst"


def test_the_daemon_glue_can_only_ask_for_a_pause():
    """A resume phrase is a separate risk and is not part of this feature."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._try_voice_stop)))
    actions = [
        v.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
        for k, v in zip(n.keys, n.values, strict=True)
        if isinstance(k, ast.Constant) and k.value == "action" and isinstance(v, ast.Constant)
    ]
    assert actions == ["pause"], actions


def test_the_bug_report_does_not_carry_the_users_chosen_phrase_verbatim():
    # A phrase the user picked may be personal (a name, a private word): classified as the
    # user's own prose, so `yazses report` replaces it and keeps only a length.
    from yazses.system.report import redact_config

    out = redact_config({"handsfree_safety": {"stop_phrase": "freeze Alice's pointer"}})
    assert "Alice" not in str(out) and "chars" in str(out["handsfree_safety"]["stop_phrase"])
