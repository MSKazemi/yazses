"""`[polyglot]` says what it does: code-switch routing is designed, not wired (ADR-v2-008).

The daemon used to build a `PolyglotRouter` from `[polyglot]` and, with a pair and an
`adapter_path` set, log "Polyglot code-switch routing active" -- while nothing in `src/`
ever called `should_route`, and `yazses features enable polyglot` succeeded. The router
decides from per-span language IDs, and no decode path produces them (the `SttEngine`
seam returns text only; faster-whisper reports one language per call), so every burst
was decoded by the `[stt]` model whatever the config said.

Producing that input is new design, so the feature was made honest rather than wired.
Pinned here:

* the registry calls `polyglot` unwired, `features enable` refuses it and writes
  nothing, and `features info` says an `on` config does nothing;
* a daemon with a *fully configured* `[polyglot]` logs the not-wired warning, never
  claims routing is active, and never imports `yazses.polyglot`;
* a default daemon says nothing about polyglot at all;
* `yazses doctor` warns on `enabled` alone -- with or without an adapter, since the old
  row's "set adapter_path" advice implied that would make it work.

`tests/test_feature_wiring_honesty.py` independently recomputes reachability and fails
if `polyglot` is flagged unwired while an entry point imports its package, so wiring the
feature for real later forces every pin above to be revisited.
"""
from __future__ import annotations

import dataclasses
import logging
import types
from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_dormant_features_stay_unimported import _DaemonImports
from yazses.config import Config, PolyglotConfig
from yazses.core.daemon import POLYGLOT_NOT_WIRED_WARNING, Daemon
from yazses.platform import get_platform
from yazses.system.doctor import _polyglot_check
from yazses.system.features import _UNWIRED, feature_status

_FULL = PolyglotConfig(enabled=True, pair="fa-en", adapter_path="/nonexistent/cs-adapter")


# --------------------------------------------------------------------------- #
# Registry + CLI
# --------------------------------------------------------------------------- #
def test_the_registry_calls_polyglot_unwired() -> None:
    assert "polyglot" in _UNWIRED
    feat = {f.slug: f for f in feature_status(Config())}["polyglot"]
    assert feat.wired is False
    assert "not yet wired" in feat.tier_label


def test_the_registry_text_says_nothing_routes() -> None:
    """The description used to read "Handles dictation that mixes two languages."."""
    feat = {f.slug: f for f in feature_status(Config())}["polyglot"]
    assert "Not wired" in feat.why
    assert "[stt] model" in feat.why
    assert not feat.why.startswith("Handles")


def _fake_platform(tmp_path: Path):
    return types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
    )


def _combined_output(result) -> str:
    try:
        return result.output + result.stderr
    except ValueError:  # older click mixes stderr into output
        return result.output


def test_features_enable_polyglot_refuses_and_writes_nothing(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    import yazses.cli as cli

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = CliRunner().invoke(cli.app, ["features", "enable", "polyglot"])
    assert result.exit_code == 1
    assert "not yet wired" in _combined_output(result)
    assert not (tmp_path / "config.toml").exists()


def test_features_info_says_an_on_config_does_nothing(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    import yazses.cli as cli

    (tmp_path / "config.toml").write_text(
        '[polyglot]\nenabled = true\npair = "fa-en"\nadapter_path = "/x/adapter"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = CliRunner().invoke(
        cli.app, ["features", "info", "polyglot"], env={"COLUMNS": "220", "TERM": "dumb"}
    )
    assert result.exit_code == 0, _combined_output(result)
    out = result.output
    assert "not yet wired" in out
    assert "nothing reads that key" in out
    assert "yazses features disable polyglot" in out


def test_features_disable_polyglot_still_clears_an_old_config(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    import yazses.cli as cli

    cfg = tmp_path / "config.toml"
    cfg.write_text("[polyglot]\nenabled = true\n", encoding="utf-8")
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = CliRunner().invoke(cli.app, ["features", "disable", "polyglot"])
    assert result.exit_code == 0, _combined_output(result)
    assert "enabled = false" in cfg.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Daemon start-up
# --------------------------------------------------------------------------- #
@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch):
    """A daemon after `__init__` and the real `_build_pipeline()`.

    The stubs of `tests/test_dormant_features_stay_unimported.py::started`, for the same
    reasons: no speech model, no OS hotkey listener, no injector env vars left behind.
    """
    import yazses.core.daemon as daemon_mod
    import yazses.inject.auto as inject_auto

    monkeypatch.setattr(daemon_mod, "build_engine", lambda stt: types.SimpleNamespace(name="stub"))
    monkeypatch.setattr(inject_auto, "apply_injection_config", lambda injection: None)
    platform = dataclasses.replace(
        get_platform(),
        injector_factory=lambda: types.SimpleNamespace(name="stub"),
        hotkey_factory=lambda *args: types.SimpleNamespace(run=lambda: None, stop=lambda: None),
    )
    monkeypatch.setattr(platform.lifecycle, "clear_pid", lambda: None)
    made: list[Daemon] = []

    def build(cfg: Config) -> Daemon:
        daemon = Daemon(config=cfg, platform=platform)
        made.append(daemon)
        monkeypatch.setattr(daemon, "_announce_model_download", lambda cfg: None)
        daemon._build_pipeline()
        return daemon

    yield build
    for daemon in made:
        daemon._shutdown()


def _daemon_messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "yazses.core.daemon"]


def test_a_fully_configured_polyglot_is_reported_as_not_wired(started, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="yazses.core.daemon")
    started(replace(Config(), polyglot=_FULL))
    messages = _daemon_messages(caplog)
    assert POLYGLOT_NOT_WIRED_WARNING in messages
    assert not [m for m in messages if "routing active" in m], messages
    warning = [
        r for r in caplog.records
        if r.name == "yazses.core.daemon" and r.getMessage() == POLYGLOT_NOT_WIRED_WARNING
    ]
    assert warning and all(r.levelno == logging.WARNING for r in warning)


def test_the_daemon_never_imports_the_polyglot_package(started, monkeypatch) -> None:
    """Even with `[polyglot]` fully on: importing it is what made the slug look wired."""
    import builtins

    recorder = _DaemonImports(frozenset({"polyglot"}))
    monkeypatch.setattr(builtins, "__import__", recorder)
    started(replace(Config(), polyglot=_FULL))
    assert recorder.packages() == set(), recorder.lookups


def test_a_default_daemon_says_nothing_about_polyglot(started, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="yazses.core.daemon")
    started(Config())
    assert not [m for m in _daemon_messages(caplog) if "polyglot" in m.lower()]


def test_the_warning_names_what_really_happens() -> None:
    text = POLYGLOT_NOT_WIRED_WARNING
    assert "not wired" in text
    assert "[stt] model" in text
    assert "yazses features disable polyglot" in text
    assert "active" not in text


# --------------------------------------------------------------------------- #
# Doctor
# --------------------------------------------------------------------------- #
def test_doctor_is_silent_while_polyglot_is_off() -> None:
    assert _polyglot_check(Config()) is None


@pytest.mark.parametrize(
    "section",
    [
        PolyglotConfig(enabled=True),
        PolyglotConfig(enabled=True, pair="fa-en"),
        _FULL,
    ],
    ids=["enabled-only", "with-pair", "with-pair-and-adapter"],
)
def test_doctor_warns_whenever_polyglot_is_on(section) -> None:
    row = _polyglot_check(replace(Config(), polyglot=section))
    assert row is not None
    name, status, detail = row
    assert "polyglot" in name
    assert status == "WARN"
    assert "not wired" in detail
    assert "yazses features disable polyglot" in detail
    # The old row told the user to set adapter_path, as if that would make it work.
    assert "set [polyglot] adapter_path" not in detail


def test_doctor_tolerates_a_config_without_the_section() -> None:
    assert _polyglot_check(types.SimpleNamespace()) is None
