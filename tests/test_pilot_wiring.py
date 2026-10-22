"""The Voice Pilot reaches the daemon (ADR-v2-007, #164): phrase -> read -> decide -> act or ask.

The pure decision is pinned in `test_pilot_decide.py`; the AT-SPI backend in
`test_atspi_accessibility.py`. This file pins what joins them, and the direction that
matters most is the one that does nothing: a held click never runs without the confirm
word, an unrelated utterance drops it rather than leaving the daemon modal, a stale one
expires, and nothing here ever types or logs a label.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging

import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.pilot.service import PENDING_TTL_S, PilotService, elements_from_candidates
from yazses.platform import get_platform
from yazses.spokencmd.registry import build_handlers, enabled_slugs
from yazses.spokencmd.router import route
from yazses.system import features


def cand(label: str | None, eid: str, actions: tuple[str, ...] = ("click",),
         role: str = "push button") -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role=role, captured_at_s=0.0, confidence=1.0, label=label,
                             actions=actions)


SCREEN = (
    cand("Save", "n0"),
    cand("Save As", "n1"),
    cand("Delete", "n2"),
    cand("Aoife's Secret Project", "n3"),
    cand("Save", "n4", actions=(), role="label"),   # a static label: never clickable
)


class FakeReader:
    """Duck-types `OnScreenReader`: `read()` and `perform()`, recorded."""

    def __init__(self, cands=SCREEN, *, ok: bool = True) -> None:
        self.cands = cands
        self.ok = ok
        self.reads = 0
        self.performed: list[tuple[str, str]] = []

    def read(self):
        self.reads += 1
        return self.cands

    def perform(self, entity_id: str, action: str) -> bool:
        self.performed.append((entity_id, action))
        return self.ok


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def svc(reader=None, **kw) -> tuple[PilotService, FakeReader, Clock]:
    reader = reader or FakeReader()
    clock = Clock()
    return PilotService(reader, clock=clock, **kw), reader, clock


# ---- the service: act ---------------------------------------------------------------------


def test_one_exact_match_is_clicked_at_once():
    s, reader, _ = svc()
    out = s.command("click the save button")
    assert out.verdict == "act" and out.consumed
    assert reader.performed == [("n0", "click")]
    assert out.message == "Clicked 'Save'."
    assert not s.pending


def test_a_control_that_does_not_respond_is_reported():
    s, reader, _ = svc(FakeReader(ok=False))
    out = s.command("click save")
    assert out.verdict == "failed" and "did not respond" in out.message


def test_nothing_matching_clicks_nothing_and_says_so():
    s, reader, _ = svc()
    out = s.command("click frobnicate")
    assert out.verdict == "none" and out.consumed
    assert reader.performed == []
    assert "No control on screen matches" in out.message


def test_a_phrase_that_is_not_a_pilot_command_is_not_consumed():
    s, reader, _ = svc()
    out = s.command("hello there")
    assert out.consumed is False and reader.reads == 0


def test_an_unreadable_window_says_why_and_clicks_nothing():
    reader = FakeReader()
    reader.read = lambda: None  # type: ignore[method-assign]
    s = PilotService(reader, unavailable_reason="pyatspi is not installed")
    out = s.command("click save")
    assert out.verdict == "none" and out.consumed
    assert "pyatspi is not installed" in out.message
    assert reader.performed == []


# ---- the service: hold, confirm, cancel, drop, expire ------------------------------------


def test_a_destructive_label_is_held_until_confirm():
    s, reader, _ = svc()
    out = s.command("click delete")
    assert out.verdict == "confirm"
    assert reader.performed == [], "a destructive click ran without a confirm"
    assert s.pending
    assert "confirm" in out.message and "'Delete'" in out.message

    done = s.answer("Confirm.")
    assert done.verdict == "confirmed" and done.consumed
    assert reader.performed == [("n2", "click")]
    assert not s.pending


def test_a_partial_match_is_held_and_confirm_acts_on_that_node():
    s, reader, _ = svc()
    out = s.command("click save copy")  # only "Save As" / "Save" partially match
    assert out.verdict == "confirm"
    s.answer("confirm")
    assert len(reader.performed) == 1


def test_cancel_drops_it_and_clicks_nothing():
    s, reader, _ = svc()
    s.command("click delete")
    out = s.answer("cancel")
    assert out.verdict == "cancelled" and out.consumed
    assert reader.performed == [] and not s.pending


def test_anything_else_drops_it_and_is_not_consumed():
    """No modal state: the utterance carries on down the command path."""
    s, reader, _ = svc()
    s.command("click delete")
    out = s.answer("open the pod bay doors")
    assert out.consumed is False
    assert out.verdict == "discarded" and "Discarded" in out.message
    assert reader.performed == [] and not s.pending


def test_a_new_pilot_command_drops_it_silently():
    s, reader, _ = svc()
    s.command("click delete")
    out = s.answer("click the second save")
    assert out.consumed is False and out.message is None
    assert reader.performed == [] and not s.pending


def test_a_held_click_expires():
    s, reader, clock = svc()
    s.command("click delete")
    clock.now += PENDING_TTL_S + 1
    assert not s.pending
    out = s.answer("confirm")
    assert out.consumed is False
    assert reader.performed == [], "a confirm long after the prompt clicked a stale node"


def test_the_command_safety_words_are_the_confirm_words():
    s, reader, _ = svc(confirm_words=["do it"], cancel_words=["stop"])
    s.command("click delete")
    assert s.answer("confirm").consumed is False      # not a configured word: dropped
    assert reader.performed == []
    s.command("click delete")
    assert s.answer("do it").verdict == "confirmed"
    assert reader.performed == [("n2", "click")]


def test_a_new_command_replaces_a_held_one():
    s, reader, _ = svc()
    s.command("click delete")
    s.command("click save")
    assert reader.performed == [("n0", "click")]
    assert not s.pending


def test_answer_with_nothing_held_is_not_consumed():
    s, _reader, _ = svc()
    assert s.answer("confirm").consumed is False


def test_a_confirmed_click_that_fails_is_reported():
    s, reader, _ = svc(FakeReader(ok=False))
    s.command("click delete")
    assert s.answer("confirm").verdict == "failed"


def test_no_label_is_ever_logged(caplog):
    caplog.set_level(logging.DEBUG)
    s, _reader, _ = svc()
    s.command("click aoife's secret project")
    s.command("click delete")
    s.answer("confirm")
    assert "Aoife" not in caplog.text and "Secret" not in caplog.text
    assert "Delete" not in caplog.text


def test_elements_carry_the_snapshot_id_and_skip_unlabelled_candidates():
    els = elements_from_candidates([cand("Save", "s1n0"), cand(None, "s1n1")])
    assert [(e.label, e.entity_id, e.actions) for e in els] == [("Save", "s1n0", ("click",))]


# ---- the phrase door ---------------------------------------------------------------------


def _on() -> Config:
    cfg = Config()
    cfg.pilot.enabled = True
    return cfg


def test_off_by_default_and_claims_nothing():
    assert Config().pilot.enabled is False
    assert "pilot" not in enabled_slugs(Config())
    assert route("click save", list(build_handlers(Config()))) is None


def test_enabling_it_enables_nothing_else():
    assert enabled_slugs(_on()) == ("pilot",)


@pytest.mark.parametrize(
    ("phrase", "carried"),
    [
        ("click save", "click save"),
        ("Click the Save button.", "Click the Save button"),
        ("press OK", "press OK"),
        ("toggle dark mode", "toggle dark mode"),
        ("check the third box", "check the third box"),
    ],
)
def test_a_pilot_phrase_becomes_an_action_and_never_text(phrase, carried):
    result = route(phrase, list(build_handlers(_on())))
    assert result is not None and result.slug == "pilot"
    assert result.action == ("pilot", carried)
    assert result.text is None


@pytest.mark.parametrize("phrase", ["focus the terminal", "activate Firefox"])
def test_window_focus_phrases_are_left_to_the_window_grammar(phrase):
    assert route(phrase, list(build_handlers(_on()))) is None


@pytest.mark.parametrize("prose", ["I will click save later", "clicking is fun",
                                   "the save button", "click"])
def test_prose_is_never_claimed(prose):
    assert route(prose, list(build_handlers(_on()))) is None


def test_it_runs_with_no_text_target_because_it_types_nothing():
    assert route("click save", list(build_handlers(_on())), can_type=False) is not None


# ---- the daemon --------------------------------------------------------------------------


class FakeBackend:
    def __init__(self, cands=SCREEN) -> None:
        self.cands = cands
        self.performed: list[tuple[str, str]] = []

    def snapshot(self, *, window_id=None, region=None):
        return self.cands

    def perform(self, entity_id, action):
        self.performed.append((entity_id, action))
        return True


def _daemon(cfg: Config, backend=None, *, reason: str | None = None) -> Daemon:
    platform = dataclasses.replace(
        get_platform(),
        accessibility_factory=(lambda: backend) if backend is not None else None,
        accessibility_unavailable_reason=reason,
    )
    return Daemon(config=cfg, platform=platform)


def test_a_default_daemon_builds_no_pilot_and_ignores_the_phrase():
    d = _daemon(Config(), FakeBackend())
    assert d._pilot is None
    assert d._try_spoken("click save", {}, can_type=True) is False
    assert d._pilot is None


def test_the_daemon_clicks_an_exact_match_without_typing(mocker):
    backend = FakeBackend()
    d = _daemon(_on(), backend)
    injector = mocker.MagicMock()
    mocker.patch.object(d, "_active_injector", return_value=injector)
    said = mocker.patch.object(d, "_notify_spoken")

    event: dict = {}
    assert d._try_spoken("click save", event, can_type=True) is True
    assert event["spoken_action"] == "pilot"
    assert event["pilot_verdict"] == "act"
    assert backend.performed == [("n0", "click")]
    injector.inject.assert_not_called()
    injector.inject_key_sequence.assert_not_called()
    said.assert_called_once_with("Clicked 'Save'.")


def test_the_daemon_holds_a_destructive_click_until_the_next_burst_confirms(mocker):
    backend = FakeBackend()
    d = _daemon(_on(), backend)
    mocker.patch.object(d, "_notify_spoken")

    event: dict = {}
    assert d._try_spoken("click delete", event, can_type=False) is True
    assert event["pilot_verdict"] == "confirm"
    assert backend.performed == []
    assert d._pilot is not None and d._pilot.pending

    answer: dict = {}
    assert d._pilot_answer("confirm", answer) is True
    assert answer["pilot_verdict"] == "confirmed"
    assert backend.performed == [("n2", "click")]


def test_the_daemon_drops_a_held_click_on_an_unrelated_burst(mocker):
    backend = FakeBackend()
    d = _daemon(_on(), backend)
    mocker.patch.object(d, "_notify_spoken")
    d._try_spoken("click delete", {}, can_type=True)
    assert d._pilot_answer("new paragraph", {}) is False
    assert not d._pilot.pending and backend.performed == []


def test_with_no_accessibility_backend_the_reason_is_said_and_nothing_happens(mocker, caplog):
    d = _daemon(_on(), None, reason="no desktop session was detected")
    said = mocker.patch.object(d, "_notify_spoken")
    caplog.set_level(logging.WARNING)
    assert d._try_spoken("click save", {}, can_type=True) is True
    assert "no desktop session was detected" in said.call_args.args[0]
    assert "[pilot] is enabled but inactive" in caplog.text


def test_backend_none_in_config_keeps_it_dormant(mocker):
    backend = FakeBackend()
    cfg = _on()
    cfg.pilot.backend = "none"
    d = _daemon(cfg, backend)
    said = mocker.patch.object(d, "_notify_spoken")
    d._try_spoken("click save", {}, can_type=True)
    assert backend.performed == []
    assert '[pilot] backend is "none"' in said.call_args.args[0]


def test_the_held_click_is_answered_before_command_mode_discards_the_burst():
    """"confirm" is not a command; without this check it is dropped as unmatched."""
    source = inspect.getsource(Daemon._on_hold_end)
    assert "self._pilot_answer(text, event)" in source
    answer = source.index("self._pilot_answer(text, event)")
    assert answer < source.index('event["discard_reason"] = "command_unmatched"')
    assert answer < source.index("self._try_spoken(text, event, can_type=can_type)")


# ---- registry ----------------------------------------------------------------------------


def test_the_feature_is_wired_and_a_spoken_command():
    assert "pilot" not in features.unwired_slugs()
    assert "pilot" in features.SPOKEN_COMMAND_SLUGS


def test_enabling_it_without_pyatspi_says_so(monkeypatch):
    import importlib.util

    cfg = Config()
    cfg.hotkey.command_key = "right_ctrl"  # past the command-key caveat
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name == "pyatspi" else object())
    caveat = features.enable_caveat("pilot", cfg) or ""
    assert "pyatspi" in caveat and "python3-pyatspi" in caveat
