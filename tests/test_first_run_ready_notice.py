"""The first-run model wait ends with a desktop notice, not only a log line.

`_announce_model_download` tells a user on their first run that YazSes is fetching its
speech model. The end of that wait was only `log.info("YazSes ready...")`, so someone
who started YazSes from an app grid or a `.dmg` -- no terminal, perhaps no tray -- was
told a download had started and never told that dictation now works.

The ready notice fires on one specific, checkable signal (AGENTS.md rule 9): a download
was announced *this run*. A cached model, an offline install, or a notice already shown
(the persisted shown-notices record) keeps it silent.

Synthetic seams only: no model, no microphone, no keyboard, no desktop. Whether a real
GNOME/KDE/macOS/Windows desktop displays the toast is NOT measured here.
"""

from __future__ import annotations

import threading

import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.stt import download as download_mod
from yazses.system import hfcache
from yazses.system import notify as notify_mod

_JOIN_S = 5.0

#: Everything `run()` starts after the pipeline exists, except the shown-notices load,
#: which the ready notice reads.
_OPTIONAL_STARTUP = (
    "_maybe_launch_overlay", "_maybe_launch_tray", "_start_update_watcher",
    "_announce_permissions", "_announce_dormant_features",
    "_warm_portal_session", "_start_portal_idle_reaper", "_start_stt_idle_unloader",
    "_start_latency_pool_evictor", "_start_headpointer", "_start_gesture",
    "_start_morsevox",
)


class _Hotkey:
    key_id = "right_alt"

    def run(self) -> None:  # returns at once: the daemon then shuts down
        return None

    def stop(self) -> None:
        return None


@pytest.fixture
def toasts(monkeypatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    def _notify(title, body, *a, **k):
        sent.append((title, body))

    monkeypatch.setattr(notify_mod, "notify", _notify)
    return sent


def _seams(monkeypatch, *, cached: bool, offline: bool = False) -> None:
    monkeypatch.setattr(download_mod, "is_cached", lambda name, *a, **k: cached)
    monkeypatch.setattr(hfcache, "offline_requested", lambda *a, **k: offline)


def _start(monkeypatch) -> Daemon:
    """Run one daemon start through `run()` with a pipeline build that only announces."""
    d = Daemon(config=Config(), platform=get_platform())
    monkeypatch.setattr(d, "_start_ipc_server", lambda: None)
    monkeypatch.setattr(d, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(d, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(d, "_configure_logging", lambda: None)
    monkeypatch.setattr(d, "_shutdown", lambda: None)
    for name in _OPTIONAL_STARTUP:
        monkeypatch.setattr(d, name, lambda *a, **k: None)

    def build() -> None:
        # The real build announces, then loads the engine (the slow part, faked away).
        d._announce_model_download(d._config)
        d._hotkey = _Hotkey()
        d._engine = d._recorder = d._injector = object()

    monkeypatch.setattr(d, "_build_pipeline", build)
    t = threading.Thread(target=d.run, daemon=True, name="test-ready-notice-run")
    t.start()
    t.join(_JOIN_S)
    assert not t.is_alive(), "the daemon start did not finish"
    return d


def _ready(sent: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [s for s in sent if "ready" in s[0].lower()]


def test_an_uncached_first_run_says_when_dictation_is_ready(
    monkeypatch, sandbox_paths, toasts
) -> None:
    _seams(monkeypatch, cached=False)
    d = _start(monkeypatch)
    ready = _ready(toasts)
    assert len(ready) == 1, toasts
    title, body = ready[0]
    assert d._resolved_hotkey() in title + body
    # The download notice came first, the ready notice after it.
    assert toasts.index(ready[0]) > 0
    assert "downloading" in toasts[0][0].lower()


def test_a_cached_model_starts_silently(monkeypatch, sandbox_paths, toasts) -> None:
    _seams(monkeypatch, cached=True)
    _start(monkeypatch)
    assert toasts == []


def test_an_offline_install_starts_silently(monkeypatch, sandbox_paths, toasts) -> None:
    _seams(monkeypatch, cached=False, offline=True)
    _start(monkeypatch)
    assert toasts == []


def test_a_second_start_does_not_repeat_the_ready_notice(
    monkeypatch, sandbox_paths, toasts
) -> None:
    # Two uncached starts back to back (a crash loop under Restart=on-failure that
    # re-enters the download): the persisted shown-notices record keeps it to one.
    _seams(monkeypatch, cached=False)
    _start(monkeypatch)
    _start(monkeypatch)
    assert len(_ready(toasts)) == 1, toasts


def test_a_failing_notifier_does_not_stop_startup(monkeypatch, sandbox_paths) -> None:
    _seams(monkeypatch, cached=False)

    def _boom(*a, **k):
        raise RuntimeError("no notification daemon")

    monkeypatch.setattr(notify_mod, "notify", _boom)
    d = _start(monkeypatch)
    assert d._state.ready is True


def test_the_download_notice_states_no_fixed_size(monkeypatch, sandbox_paths, toasts) -> None:
    # The old text said "a few hundred MB" for every model. base.en measured 148 MB on
    # disk (141 MiB) and large models are gigabytes, so one figure is wrong for most.
    _seams(monkeypatch, cached=False)
    Daemon(config=Config(), platform=get_platform())._announce_model_download(Config())
    assert toasts, "the download notice was not sent"
    assert "MB" not in toasts[0][1]
