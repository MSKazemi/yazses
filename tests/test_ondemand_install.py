"""A dormant feature offers its install as one action, at the moment it is found.

A feature switched on by editing `config.toml` (or `--no-install`, or before an update
rebuilt the environment) used to be announced with a sentence telling the user to go
and type `yazses features enable <name>`. Now each surface that finds it offers the
install itself — the daemon toast's **Install now**, the `yazses start`/`restart`
prompt, and `yazses features install` — and each still asks first: nothing here
downloads without a click, a typed yes, or the command being typed.

Nothing is fetched: the installer is replaced throughout.
"""

from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config
from yazses.system import deps, dormant, ondemand

runner = CliRunner()


def _item(slug="denoise", *, installable=True, command=""):
    return dormant.DormantFeature(
        slug=slug, name=slug.title(), missing=("noisereduce",),
        packages=("noisereduce>=3.0.3",),
        remedy="Install them with:  yazses features enable " + slug if installable
        else "this is a snap, …",
        installable=installable,
        command=command or f"yazses features enable {slug}",
    )


# ---- the finding carries whether an install can work -------------------------------


def test_dormant_marks_a_blocked_environment_not_installable():
    feat = types.SimpleNamespace(
        slug="denoise", name="Denoise", on=True, wired=True, tier="opt",
        check_modules=("noisereduce",), pip_packages=("noisereduce>=3.0.3",),
    )
    found = dormant.dormant_features(
        None, features=[feat], missing=lambda m: list(m),
        blocked=lambda p: "this is a snap", graphical=lambda: True,
    )
    assert found[0].installable is False
    ok = dormant.dormant_features(
        None, features=[feat], missing=lambda m: list(m),
        blocked=lambda p: None, graphical=lambda: True,
    )
    assert ok[0].installable is True and ok[0].command == "yazses features enable denoise"


def test_the_command_carries_force_for_an_experimental_feature():
    feat = types.SimpleNamespace(
        slug="cocktail", name="Cocktail", on=True, wired=True, tier="experimental",
        check_modules=("speechbrain",), pip_packages=("speechbrain>=1.1",),
    )
    from yazses.system.features import EXPERIMENTAL

    feat.tier = EXPERIMENTAL
    found = dormant.dormant_features(
        None, features=[feat], missing=lambda m: list(m),
        blocked=lambda p: None, graphical=lambda: True,
    )
    assert found[0].command.endswith("--force")
    title, body = ondemand.result_message(found[0], False)
    assert "yazses features enable cocktail --force" in body


# ---- the toast ------------------------------------------------------------------------


def test_an_installable_feature_gets_an_install_button():
    keys = [a.key for a in ondemand.toast_actions(_item())]
    assert keys == [ondemand.INSTALL, ondemand.LATER]


def test_a_feature_that_can_never_install_gets_no_button():
    assert ondemand.toast_actions(_item(installable=False)) is None


def test_the_toast_names_the_download_before_the_click(monkeypatch):
    monkeypatch.setattr("yazses.system.depsize.download_note",
                        lambda slug, missing: "downloads ~6.0 MB")
    assert "Install now: downloads ~6.0 MB" in ondemand.toast_body(_item())


def test_clicking_install_installs_and_reports_how_to_apply_it():
    calls, toasts = [], []

    def install(packages, *, check_modules, echo):
        calls.append((packages, check_modules))
        return True

    ok = ondemand.handle_action(ondemand.INSTALL, _item(), install=install,
                                notify=lambda t, b: toasts.append((t, b)))
    assert ok is True
    assert calls == [(("noisereduce>=3.0.3",), ("noisereduce",))]
    assert "installed" in toasts[0][0] and "yazses restart" in toasts[0][1]


def test_not_now_installs_nothing():
    def install(*a, **k):
        raise AssertionError("must not install")

    assert ondemand.handle_action(ondemand.LATER, _item(), install=install,
                                  notify=lambda t, b: None) is None


def test_a_failed_install_says_dormant_and_how_to_retry():
    toasts = []
    ok = ondemand.handle_action(ondemand.INSTALL, _item(),
                                install=lambda *a, **k: False,
                                notify=lambda t, b: toasts.append((t, b)))
    assert ok is False
    assert "could not be installed" in toasts[0][0]
    assert "dormant" in toasts[0][1] and "yazses features enable denoise" in toasts[0][1]


def test_an_installer_that_raises_is_a_failure_not_a_crash():
    def boom(*a, **k):
        raise RuntimeError("disk full")

    toasts = []
    assert ondemand.handle_action(ondemand.INSTALL, _item(), install=boom,
                                  notify=lambda t, b: toasts.append(t)) is False
    assert toasts and "could not be installed" in toasts[0]


def test_a_second_click_during_an_install_is_refused():
    started, release = threading.Event(), threading.Event()
    toasts = []

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return True

    worker = threading.Thread(target=ondemand.handle_action, args=(ondemand.INSTALL, _item()),
                              kwargs={"install": slow, "notify": lambda t, b: None})
    worker.start()
    assert started.wait(5)
    second = ondemand.handle_action(ondemand.INSTALL, _item("tray"),
                                    install=lambda *a, **k: pytest.fail("ran twice"),
                                    notify=lambda t, b: toasts.append(t))
    release.set()
    worker.join(5)
    assert second is None and "already running" in toasts[0]


def test_the_daemon_toast_carries_the_buttons_and_wires_the_handler(monkeypatch):
    from yazses.core.daemon import Daemon
    from yazses.system import notify as notify_mod

    item = _item()
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: [item])
    shown = []
    monkeypatch.setattr(notify_mod, "notify",
                        lambda title, body, **k: shown.append((title, body, k)))
    handled = []
    monkeypatch.setattr(ondemand, "handle_action", lambda key, it: handled.append((key, it)))
    stub = types.SimpleNamespace(
        _config=Config(), _lock=threading.Lock(), _diagnosed_at={},
        _persist_shown_notices=lambda: None,
    )
    Daemon._announce_dormant_features(stub)
    (_title, _body, kwargs), = shown
    assert [a.key for a in kwargs["actions"]] == [ondemand.INSTALL, ondemand.LATER]
    kwargs["on_action"](ondemand.INSTALL)
    assert handled == [(ondemand.INSTALL, item)]


def test_the_daemon_toast_has_no_button_where_nothing_can_install(monkeypatch):
    from yazses.core.daemon import Daemon
    from yazses.system import notify as notify_mod

    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: [_item(installable=False)])
    shown = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **k: shown.append(k))
    stub = types.SimpleNamespace(
        _config=Config(), _lock=threading.Lock(), _diagnosed_at={},
        _persist_shown_notices=lambda: None,
    )
    Daemon._announce_dormant_features(stub)
    assert shown[0]["actions"] is None and shown[0]["on_action"] is None


# ---- `yazses features install` ------------------------------------------------------


def _cli(monkeypatch, tmp_path, items, *, ok=True):
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(
            config_file=tmp_path / "config.toml")),
    )
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: list(items))
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")
    calls: list = []

    def install(packages, *, check_modules=(), echo=print):
        calls.append(tuple(packages))
        return ok

    monkeypatch.setattr(deps, "install_feature", install)
    return calls


def test_features_install_asks_and_installs_on_yes(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item()])
    result = runner.invoke(cli.app, ["features", "install"], input="y\n")
    assert result.exit_code == 0, result.output
    assert calls == [("noisereduce>=3.0.3",)]
    assert "noisereduce>=3.0.3" in result.output, "what will be fetched is shown first"
    assert "yazses restart" in result.output


def test_features_install_installs_nothing_on_no(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item()])
    result = runner.invoke(cli.app, ["features", "install"], input="n\n")
    assert result.exit_code == 1 and calls == []
    assert "Nothing installed" in result.output


def test_features_install_yes_does_not_ask(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item()])
    result = runner.invoke(cli.app, ["features", "install", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls and "[y/N]" not in result.output


def test_features_install_with_nothing_dormant_is_a_quiet_success(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [])
    result = runner.invoke(cli.app, ["features", "install"])
    assert result.exit_code == 0 and calls == []
    assert "Nothing to install" in result.output


def test_features_install_names_only_the_ones_asked_for(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item("denoise"), _item("prosody")])
    result = runner.invoke(cli.app, ["features", "install", "prosody", "--yes"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1 and "Prosody" in result.output


def test_features_install_refuses_a_name_that_is_not_dormant(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item("denoise")])
    result = runner.invoke(cli.app, ["features", "install", "gaze", "--yes"])
    assert result.exit_code == 1 and calls == []
    assert "yazses features enable" in result.output


def test_features_install_reports_a_blocked_environment_and_fails(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item(installable=False)])
    result = runner.invoke(cli.app, ["features", "install", "--yes"])
    assert result.exit_code == 1 and calls == []
    assert "snap" in result.output


def test_features_install_exits_non_zero_when_an_install_fails(monkeypatch, tmp_path):
    _cli(monkeypatch, tmp_path, [_item()], ok=False)
    result = runner.invoke(cli.app, ["features", "install", "--yes"])
    assert result.exit_code == 1
    assert "Still dormant: denoise" in result.output


def test_the_listing_names_the_one_command(monkeypatch, tmp_path):
    item = _item()
    monkeypatch.setattr(cli, "_dormant_shown", lambda cfg, shown: {item.slug: item})
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(
            config_file=tmp_path / "config.toml")),
    )
    result = runner.invoke(cli.app, ["features"])
    assert "yazses features install" in result.output


# ---- `yazses start` / `restart` ask, in a terminal only --------------------------------


def _platform(tmp_path: Path):
    return types.SimpleNamespace(paths=types.SimpleNamespace(config_file=tmp_path / "c.toml"))


def test_start_does_not_prompt_without_a_terminal(monkeypatch, tmp_path):
    """An autostart entry, a service unit or a script has no one to answer."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(dormant, "dormant_features",
                        lambda cfg: pytest.fail("no terminal: must not even probe"))
    cli._offer_dormant_install(_platform(tmp_path))  # returns quietly


def _tty(monkeypatch):
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)


def test_start_in_a_terminal_installs_on_yes(monkeypatch, tmp_path):
    _tty(monkeypatch)
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: [_item()])
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")
    monkeypatch.setattr(cli.typer, "confirm", lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(deps, "install_feature",
                        lambda p, *, check_modules=(), echo=print: calls.append(p) or True)
    cli._offer_dormant_install(_platform(tmp_path))
    assert calls == [("noisereduce>=3.0.3",)]


def test_start_in_a_terminal_defaults_to_no(monkeypatch, tmp_path):
    _tty(monkeypatch)
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: [_item()])
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")
    seen = {}

    def confirm(text, default):
        seen["default"] = default
        return default

    monkeypatch.setattr(cli.typer, "confirm", confirm)
    monkeypatch.setattr(deps, "install_feature", lambda *a, **k: pytest.fail("installed"))
    cli._offer_dormant_install(_platform(tmp_path))
    assert seen == {"default": False}


def test_start_never_fails_because_the_offer_did(monkeypatch, tmp_path):
    _tty(monkeypatch)

    def boom(cfg):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(dormant, "dormant_features", boom)
    cli._offer_dormant_install(_platform(tmp_path))  # must not raise


def test_start_and_restart_both_make_the_offer():
    import ast
    import inspect

    for fn in (cli.start, cli.restart):
        tree = ast.parse(inspect.getsource(fn))
        names = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_offer_dormant_install" in names, fn.__name__
