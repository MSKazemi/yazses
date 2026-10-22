"""Screen-Grounded Dictation reaches the decode (ADR-v2-051, #164).

The term miner (`screengrounded/harvest.py`) is pinned in `test_screengrounded_headpointer.py`
and the AT-SPI producer in `test_atspi_accessibility.py`. What is pinned here is the
wiring and its three promises from the ADR: the read never delays recording (it runs at
hold start, off the hot path, and the decode waits only briefly), its terms bias **one**
burst and are then forgotten, and nothing it read is logged. The prompt is composed
against a stand-in daemon whose paths point at ``tmp_path``, so no test reads the
developer's own vocabulary file.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import threading
from types import SimpleNamespace

from yazses.config import Config, load_config
from yazses.core.daemon import Daemon
from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.platform import get_platform
from yazses.screengrounded.sampler import ScreenTermSampler, terms_from_candidates
from yazses.system import features


def cand(label: str, role: str = "label", eid: str = "n0") -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role=role, captured_at_s=0.0, confidence=1.0, label=label)


SCREEN = (
    cand("File", role="menu item"),
    cand("Edit", role="menu"),
    cand("Reply to Aoife Nguyen about useAuthContext", role="paragraph"),
    cand("Send", role="push button"),
)


class Reader:
    def __init__(self, cands=SCREEN, *, gate: threading.Event | None = None) -> None:
        self.cands = cands
        self.gate = gate
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.gate is not None:
            self.gate.wait(5)
        return self.cands


# ---- the pure step -----------------------------------------------------------------------


def test_window_chrome_is_skipped_so_content_names_get_the_slots():
    terms = terms_from_candidates(SCREEN, 32)
    assert "File" not in terms and "Edit" not in terms
    assert {"Aoife", "Nguyen", "useAuthContext", "Send"} <= set(terms)


def test_the_term_cap_holds_and_zero_means_none():
    assert len(terms_from_candidates(SCREEN, 2)) == 2
    assert terms_from_candidates(SCREEN, 0) == []


# ---- the sampler -------------------------------------------------------------------------


def test_a_hold_reads_once_and_the_decode_takes_its_terms():
    reader = Reader()
    sampler = ScreenTermSampler(reader, max_terms=32)
    sampler.begin()
    terms = sampler.take(wait_s=2.0)
    assert "Aoife" in terms and reader.reads == 1


def test_terms_bias_one_burst_and_are_then_forgotten():
    sampler = ScreenTermSampler(Reader(), max_terms=32)
    sampler.begin()
    assert sampler.take(wait_s=2.0)
    assert sampler.take(wait_s=0.0) == []


def test_take_without_a_hold_is_empty_and_does_not_wait():
    assert ScreenTermSampler(Reader(), max_terms=32).take(wait_s=5.0) == []


def test_an_unreadable_window_gives_no_terms():
    sampler = ScreenTermSampler(Reader(cands=None), max_terms=32)
    sampler.begin()
    assert sampler.take(wait_s=2.0) == []


def test_a_slow_read_costs_this_burst_its_terms_and_never_leaks_into_the_next():
    gate = threading.Event()
    slow = Reader(gate=gate)
    sampler = ScreenTermSampler(slow, max_terms=32)
    sampler.begin()
    try:
        assert sampler.take(wait_s=0.01) == [], "the decode waited for a slow window"
    finally:
        gate.set()
    # The late read finishes now; it belonged to a burst already decoded.
    sampler._done.wait(2.0)
    assert sampler.take(wait_s=0.0) == []


def test_a_new_hold_replaces_the_previous_holds_terms():
    sampler = ScreenTermSampler(Reader(cands=(cand("Zarquon"),)), max_terms=32)
    sampler.begin()
    sampler._done.wait(2.0)
    sampler._reader = Reader(cands=(cand("Betelgeuse"),))  # the screen changed
    sampler.begin()
    assert sampler.take(wait_s=2.0) == ["Betelgeuse"]


def test_nothing_read_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    sampler = ScreenTermSampler(Reader(), max_terms=32)
    sampler.begin()
    sampler.take(wait_s=2.0)
    assert "Aoife" not in caplog.text and "useAuthContext" not in caplog.text


# ---- the prompt --------------------------------------------------------------------------


def _stand_in(tmp_path, *, enabled: bool, terms: list[str]):
    cfg = load_config(None)
    cfg.screengrounded.enabled = enabled
    primed = SimpleNamespace(take=lambda: list(terms))
    return SimpleNamespace(
        _config=cfg,
        _platform=SimpleNamespace(paths=SimpleNamespace(config_file=tmp_path / "config.toml")),
        _personal_bias_terms=lambda: [],
        _screen_terms=primed,
    )


def test_enabled_terms_reach_the_initial_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    fake = _stand_in(tmp_path, enabled=True, terms=["Aoife", "useAuthContext"])
    prompt = Daemon._effective_initial_prompt(fake) or ""
    assert "Aoife" in prompt and "useAuthContext" in prompt
    assert "YazSes" in prompt


def test_disabled_terms_never_reach_the_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    fake = _stand_in(tmp_path, enabled=False, terms=["Aoife"])
    assert "Aoife" not in (Daemon._effective_initial_prompt(fake) or "")


def test_a_sampler_that_raises_never_breaks_the_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    fake = _stand_in(tmp_path, enabled=True, terms=[])

    def boom():
        raise RuntimeError("accessibility bus vanished")

    fake._screen_terms = SimpleNamespace(take=boom)
    assert "YazSes" in (Daemon._effective_initial_prompt(fake) or "")


# ---- the daemon --------------------------------------------------------------------------


class FakeBackend:
    def __init__(self) -> None:
        self.snapshots = 0

    def snapshot(self, *, window_id=None, region=None):
        self.snapshots += 1
        return SCREEN

    def perform(self, entity_id, action):  # pragma: no cover - never called here
        raise AssertionError("screen grounding must never act")


def _daemon(cfg: Config, backend=None, reason: str | None = None) -> Daemon:
    platform = dataclasses.replace(
        get_platform(),
        accessibility_factory=(lambda: backend) if backend is not None else None,
        accessibility_unavailable_reason=reason,
    )
    return Daemon(config=cfg, platform=platform)


def _on() -> Config:
    cfg = Config()
    cfg.screengrounded.enabled = True
    return cfg


def test_the_daemon_reads_the_window_at_hold_start_and_never_acts():
    backend = FakeBackend()
    d = _daemon(_on(), backend)
    d._begin_screen_terms()
    assert d._screen_terms is not None
    terms = d._screen_terms.take(wait_s=2.0)
    assert "Aoife" in terms and backend.snapshots == 1


def test_a_default_daemon_never_touches_the_accessibility_backend():
    backend = FakeBackend()
    d = _daemon(Config(), backend)
    assert d._screen_terms is None
    source = inspect.getsource(Daemon._on_hold_start)
    call = source.index("self._begin_screen_terms()")
    assert "self._config.screengrounded.enabled" in source[max(0, call - 200):call]
    assert backend.snapshots == 0


def test_with_no_backend_the_reason_is_logged_once_and_no_sampler_is_built(caplog):
    d = _daemon(_on(), None, reason="no desktop session was detected")
    caplog.set_level(logging.WARNING)
    d._begin_screen_terms()
    d._begin_screen_terms()
    assert d._screen_terms is None
    assert caplog.text.count("[screengrounded] is enabled but inactive") == 1
    assert "no desktop session was detected" in caplog.text


def test_the_feature_is_wired():
    assert "screengrounded" not in features.unwired_slugs()
