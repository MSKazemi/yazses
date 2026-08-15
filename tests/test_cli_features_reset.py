"""CLI: `yazses features reset` — Restore defaults for machines with no window.

The settings window's button needs a graphical session, PySide6 and a Qt that
the distribution can actually load. This command is the same operation with none
of that, so an SSH box, a server, or a distribution too old for PySide6 is not
cut off from it.

Every test points the CLI at a temporary config file: a `features reset` that
escaped into the developer's own `~/.config/yazses/config.toml` would rewrite
their real settings.
"""
from __future__ import annotations

import types
from pathlib import Path

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system.features import default_state

runner = CliRunner()
WIDE = {"COLUMNS": "220", "TERM": "dumb"}


def _use_config(monkeypatch, path: Path):
    """Point the CLI at *path* and never at the real user config."""
    monkeypatch.setattr(
        cli,
        "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(config_file=path)),
    )
    # Optional-dependency installs are the one side effect that reaches the
    # network; a reset test must never trigger one.
    monkeypatch.setattr(cli, "_install_feature_deps", lambda feat, skip: None)
    monkeypatch.setattr(cli, "_feature_deps_blocked", lambda feat: None)
    return path


def _config_text(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def test_dry_run_lists_the_changes_and_writes_nothing(monkeypatch, tmp_path):
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text('[streaming]\nenabled = true\n')

    r = runner.invoke(cli.app, ["features", "reset", "--dry-run"], env=WIDE)

    assert r.exit_code == 0
    assert "Streaming transcription" in r.output
    assert "Dry run" in r.output
    assert _config_text(cfg) == '[streaming]\nenabled = true\n'


def test_reset_turns_an_opt_in_capability_back_off(monkeypatch, tmp_path):
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text('[streaming]\nenabled = true\n')

    r = runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)

    assert r.exit_code == 0, r.output
    assert "enabled = false" in _config_text(cfg)
    assert "yazses restart" in r.output


def test_reset_turns_a_recommended_capability_back_on(monkeypatch, tmp_path):
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text('[commands]\nenabled = false\n')

    r = runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)

    assert r.exit_code == 0, r.output
    assert "[commands]" in _config_text(cfg)
    assert "enabled = true" in _config_text(cfg)


def test_declining_the_prompt_writes_nothing(monkeypatch, tmp_path):
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text('[streaming]\nenabled = true\n')

    r = runner.invoke(cli.app, ["features", "reset"], input="n\n", env=WIDE)

    assert r.exit_code == 1
    assert "Cancelled" in r.output
    assert _config_text(cfg) == '[streaming]\nenabled = true\n'


def test_reset_leaves_settings_that_are_not_feature_switches_alone(monkeypatch, tmp_path):
    """A reset of the switchboard is not a reset of the config file."""
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text(
        "# my notes\n"
        '[hotkey]\nkey = "right_alt"\n\n'
        '[audio]\ndevice = "Yeti"\n\n'
        '[accessibility]\nvad_threshold = 0.004\n\n'
        "[streaming]\nenabled = true\n"
    )

    r = runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)

    assert r.exit_code == 0, r.output
    text = _config_text(cfg)
    assert 'key = "right_alt"' in text
    assert 'device = "Yeti"' in text
    assert "vad_threshold = 0.004" in text
    assert "# my notes" in text, "the comment-preserving writer must stay in the path"


def test_reset_writes_only_the_rows_that_are_off_default(monkeypatch, tmp_path):
    """Rewriting all ~200 keys would churn the whole file to change one line."""
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text('[streaming]\nenabled = true\n')
    written: list[tuple] = []
    monkeypatch.setattr(
        cli, "_apply_feature_writes", lambda path, writes: written.extend(writes)
    )

    r = runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)

    assert r.exit_code == 0, r.output
    sections = {section for section, _k, _v, _q in written}
    assert "streaming" in sections
    assert len(written) < len(default_state()), "a reset must not rewrite every key"


def test_a_config_already_at_the_defaults_is_a_no_op(monkeypatch, tmp_path):
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    # Seed the file with the shipped defaults, then reset twice: the second run
    # must find nothing left to do.
    cfg.write_text("")
    runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)
    before = _config_text(cfg)

    r = runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)

    assert r.exit_code == 0, r.output
    assert "already at its default" in r.output
    assert _config_text(cfg) == before


def test_a_capability_whose_libraries_can_never_arrive_is_skipped(monkeypatch, tmp_path):
    """Same refusal `features enable` makes: never write a key nothing can honour."""
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text('[tray]\nenabled = false\n')
    monkeypatch.setattr(
        cli,
        "_feature_deps_blocked",
        lambda feat: "this snap is read-only" if feat.slug == "tray" else None,
    )

    r = runner.invoke(cli.app, ["features", "reset", "--yes"], env=WIDE)

    assert r.exit_code == 0, r.output
    assert "Skipped System-tray icon" in r.output
    assert "read-only" in r.output
    assert "enabled = false" in _config_text(cfg)
