"""Verbatim mode switches formatting off. It must not switch Redaction Ink off.

Verbatim is implemented by running the whole transform chain and then restoring the text
captured before it (`tests/test_verbatim_bypasses_every_transform.py`). Redaction Ink
(ADR-v2-046) sat inside that chain, so the restore threw the masking away with the
formatting, and an enabled `[redaction]` typed the secret. All three ways into verbatim
did it, including Focus-Class Auto-Profile, which selects verbatim in a terminal or an
editor without the user asking for it.

The same promise, "masks secrets before they are typed", was missed by the other places
that put dictated words on screen: live streaming partials, the spoken capabilities,
Spoken Edit and Punch-In. They are covered here too.

Every value below is synthetic. Injected fakes only: no microphone, model or display.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.inject.streaming import StreamingInjector
from yazses.platform import get_platform
from yazses.spokencmd.router import SpokenHandler, SpokenResult
from yazses.stt.streaming import PartialHypothesis

SECRET = "123-45-6789"
SPOKEN = f"my number is {SECRET}"
MASKED = "my number is [SSN]"
EMAIL = "bob@example.com"


class _Recorder:
    def stop(self):
        return np.full(16000, 0.5, dtype="float32")


class _Engine:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return self.text


class _Injector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inject(self, text: str) -> None:
        self.calls.append(text)

    def inject_backspaces(self, count: int) -> None:
        pass

    def inject_key_sequence(self, keys: list[str]) -> None:
        pass


class _Corpus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def write(self, event, audio=None, sample_rate=16000) -> None:
        self.events.append(dict(event))


def _config(*, redaction: bool = True) -> Config:
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.redaction.enabled = redaction
    return cfg


def _daemon(cfg: Config, text: str = SPOKEN) -> Daemon:
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Recorder()
    d._engine = _Engine(text)
    d._padding_buffer = None
    d._injector = _Injector()
    d._corpus = _Corpus()
    return d


def _by_app_profile(cfg: Config, text: str = SPOKEN) -> Daemon:
    cfg.profiles.app = {"*term*": "verbatim"}
    d = _daemon(cfg, text)
    d._state.app_class = "xterm"
    return d


def _by_focus_profile(cfg: Config, text: str = SPOKEN) -> Daemon:
    cfg.focusprofile.enabled = True
    d = _daemon(cfg, text)
    d._state.app_class = "kitty"
    return d


def _by_spoken_command(cfg: Config, text: str = SPOKEN) -> Daemon:
    cfg.verbatim.enabled = True
    d = _daemon(cfg, "dictate verbatim")
    d._on_hold_end()
    assert d._injector.calls == [], "the mode command itself must not be typed"
    d._corpus.events.clear()
    d._engine.text = text
    return d


WAYS_IN = pytest.mark.parametrize(
    "enter", [_by_app_profile, _by_focus_profile, _by_spoken_command],
    ids=["app-profile", "focus-profile", "spoken-command"],
)


@WAYS_IN
def test_verbatim_still_masks_what_is_typed_and_recorded(enter) -> None:
    d = enter(_config())
    d._on_hold_end()
    assert d._injector.calls == [MASKED]
    [event] = d._corpus.events
    assert event["verbatim"] is True
    assert event["final_text"] == MASKED


@WAYS_IN
def test_verbatim_without_redaction_types_the_literal(enter) -> None:
    d = enter(_config(redaction=False))
    d._on_hold_end()
    assert d._injector.calls == [SPOKEN]


@WAYS_IN
def test_verbatim_with_redaction_still_bypasses_formatting(enter) -> None:
    cfg = _config()
    cfg.gec.enabled = True
    d = enter(cfg, f"a apple and {SECRET}")
    d._on_hold_end()
    assert d._injector.calls == ["a apple and [SSN]"]


def test_the_undo_and_send_to_records_hold_the_masked_text() -> None:
    cfg = _config()
    cfg.revise.enabled = True
    cfg.sendto.enabled = True
    d = _by_app_profile(cfg)
    d._on_hold_end()
    assert d._ledger.last_text() == MASKED
    assert d._sendto_last_burst == MASKED


def test_the_staged_buffer_holds_the_masked_text(monkeypatch) -> None:
    cfg = _config()
    cfg.staged.enabled = True
    d = _by_app_profile(cfg)
    monkeypatch.setattr(d, "_notify_staged", lambda message: None)
    d._on_hold_end()
    assert d._staged.text == MASKED
    assert d._injector.calls == []


def test_safeglyph_reads_the_literal_that_will_be_typed(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "yazses.safeglyph.confusables.scan_confusables",
        lambda text: seen.append(text) or [],
    )
    cfg = _config(redaction=False)
    cfg.safeglyph.enabled = True
    cfg.gec.enabled = True
    d = _by_app_profile(cfg, "a apple")
    d._on_hold_end()
    assert seen == ["a apple"]


# ---- streaming ---------------------------------------------------------------


class _OnePartial:
    """Offers one partial, then ends the poll loop on the next read."""

    def __init__(self, text: str, stop: threading.Event) -> None:
        self._pending: PartialHypothesis | None = PartialHypothesis(text, True, len(text))
        self._stop = stop

    def get_partial(self) -> PartialHypothesis | None:
        partial, self._pending = self._pending, None
        if partial is None:
            self._stop.set()
        return partial


@pytest.mark.parametrize(
    "redaction,mode,typed",
    [(True, "mask", []), (False, "mask", ["123-45"]), (True, "hold", ["123-45"])],
    ids=["masking", "off", "hold-mode"],
)
def test_live_partials_are_typed_only_when_nothing_masks(redaction, mode, typed) -> None:
    cfg = _config(redaction=redaction)
    cfg.redaction.mode = mode
    d = _daemon(cfg)
    stop = threading.Event()
    d._stream_engine = _OnePartial("123-45", stop)
    d._stream_injector = StreamingInjector(d._injector)
    d._partial_poll_loop(stop)
    assert d._injector.calls == typed


class _Committing:
    def commit(self) -> str:
        return SPOKEN

    def request_stop(self) -> None:
        pass


def test_a_streamed_verbatim_burst_commits_the_masked_text() -> None:
    cfg = _config()
    cfg.streaming.enabled = True
    d = _by_app_profile(cfg)
    d._stream_engine = _Committing()
    d._stream_injector = StreamingInjector(d._injector)
    d._on_hold_end()
    assert d._injector.calls == [MASKED]


# ---- other paths that type dictated words ------------------------------------


def _handler(slug: str) -> SpokenHandler:
    return SpokenHandler(slug=slug, match=lambda _t: SpokenResult(slug=slug, text=EMAIL))


@pytest.mark.parametrize("slug,typed", [("spelling", "[EMAIL]"), ("snippets", EMAIL)])
def test_spoken_capabilities_mask_dictated_text_but_not_stored_snippets(slug, typed) -> None:
    d = _daemon(_config())
    d._spoken_handlers = [_handler(slug)]
    assert d._try_spoken("anything", {}, can_type=True) is True
    assert d._injector.calls == [typed]


def test_spoken_edit_masks_the_new_words() -> None:
    d = _daemon(_config())
    d._ledger.record("send it to foo")
    assert d._try_spoken_edit(f"replace foo with {EMAIL}", {}) is True
    assert d._injector.calls == ["send it to [EMAIL]"]
    assert d._ledger.last_text() == "send it to [EMAIL]"


@pytest.mark.parametrize("apply", [True, False], ids=["apply", "preview"])
def test_punch_in_masks_the_respoken_phrase(apply) -> None:
    cfg = _config()
    cfg.punch_in.enabled = True
    d = _daemon(cfg)
    d._ledger.record("mail bob@exmple today")
    result = d._apply_punch_in(EMAIL, apply=apply)
    assert result["new"] == "mail [EMAIL] today"
    assert EMAIL not in [c["new"] for c in result["candidates"]]
    assert d._injector.calls == (["mail [EMAIL] today"] if apply else [])
