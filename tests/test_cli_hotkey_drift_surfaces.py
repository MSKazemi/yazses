"""Three surfaces answer "which key do I hold?"; two of them read the wrong source.

`doctor` was fixed first, because it is the command a user is *told* to run. It was not
the only one. The daemon binds its hotkey once, at start, and never re-reads the file, so
`yazses hotkey set` without a `yazses restart` leaves the file and the running process
disagreeing -- and every surface that reads only the file then instructs the user to hold
a key that does nothing.

Measured on this machine while the drift was live (`config key = "right_alt"`,
`command_key = "right_ctrl"`, daemon bound to `right_ctrl`):

    yazses status       ->  hotkey: right_ctrl                  (correct -- reads IPC)
    yazses hotkey show  ->  Hold-to-talk key: right_alt
                            Command key:      right_ctrl        (both labels wrong)
    yazses quickstart   ->  Hold  right_alt  , speak            (does nothing)

`hotkey show` is the worse of the two: its entire job is to answer this question, and mid-
drift it printed the two keys with their labels **swapped** -- naming the key that actually
dictates as the command key. `quickstart` is the more costly: it is the first screen a new
user meets, its step 3 is a single imperative, and following it produces silence with no
error anywhere to explain why.

Both now consult the daemon. The rule itself is not restated here -- it is
`system/doctor.py::hotkey_drift_note`, shared, because three copies of one comparison is
how two of them end up disagreeing.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yazses import cli


class _Client:
    """An IPC client that answers `status` with whatever the test wants."""

    def __init__(self, payload: dict | None, *, reachable: bool = True, boom: bool = False):
        self._payload, self._reachable, self._boom = payload, reachable, boom

    def is_reachable(self) -> bool:
        return self._reachable

    def call(self, method: str, **params) -> dict:
        if self._boom:
            raise OSError("socket went away mid-call")
        return dict(self._payload or {})


def _platform(config_file: Path, *, live: dict | None = None, running: bool = True,
              reachable: bool = True, boom: bool = False, default: str = "space"):
    return types.SimpleNamespace(
        default_hotkey=default,
        paths=types.SimpleNamespace(config_file=config_file, ipc_socket=config_file.parent / "s"),
        lifecycle=types.SimpleNamespace(is_running=lambda: running),
        ipc_client_factory=lambda _sock: _Client(live, reachable=reachable, boom=boom),
    )


@pytest.fixture
def drifted(tmp_path):
    """The exact state this machine was in: configured right_alt, daemon on right_ctrl."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[hotkey]\nkey = "right_alt"\ncommand_key = "right_ctrl"\n')
    return cfg


# ---- the seam ---------------------------------------------------------------


def test_the_live_key_comes_from_the_running_daemon(drifted):
    assert cli._live_hotkey(_platform(drifted, live={"hotkey": "right_ctrl"})) == "right_ctrl"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"live": {"hotkey": "right_ctrl"}, "reachable": False},   # no daemon listening
        {"live": {"hotkey": "right_ctrl"}, "boom": True},          # socket dies mid-call
        {"live": {}},                                              # a daemon too old to say
        {"live": {"hotkey": ""}},                                  # ...or one that says nothing
    ],
    ids=["unreachable", "raises", "older-daemon", "empty-answer"],
)
def test_no_second_opinion_is_silence_not_an_error(drifted, kwargs):
    """A diagnostic that fails because the diagnosis was unavailable is worse than one
    that quietly says less -- and every one of these is an ordinary state, not a fault."""
    assert cli._live_hotkey(_platform(drifted, **kwargs)) == ""
    assert cli._hotkey_drift_note(_platform(drifted, **kwargs)) == ""


def test_agreement_is_silent(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[hotkey]\nkey = "right_alt"\n')
    assert cli._hotkey_drift_note(_platform(cfg, live={"hotkey": "right_alt"})) == ""


def test_auto_is_resolved_before_it_is_compared(tmp_path):
    """`key = "auto"` means the platform default. Comparing the literal string would
    have fired the warning on every correctly configured machine."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[hotkey]\nkey = "auto"\n')
    agreeing = _platform(cfg, live={"hotkey": "space"}, default="space")
    assert cli._hotkey_drift_note(agreeing) == ""
    disagreeing = _platform(cfg, live={"hotkey": "right_ctrl"}, default="space")
    assert "space" in cli._hotkey_drift_note(disagreeing)


# ---- the two surfaces -------------------------------------------------------


def test_hotkey_show_warns_and_names_both_keys(monkeypatch, drifted):
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(drifted, live={"hotkey": "right_ctrl"}))
    out = CliRunner().invoke(cli.app, ["hotkey", "show"]).output
    assert "right_alt" in out and "right_ctrl" in out
    assert "yazses restart" in out, "a warning with no fix is a warning to dismiss"
    assert "will do nothing" in out


def test_hotkey_show_stays_quiet_when_they_agree(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[hotkey]\nkey = "right_alt"\n')
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(cfg, live={"hotkey": "right_alt"}))
    out = CliRunner().invoke(cli.app, ["hotkey", "show"]).output
    assert "yazses restart" not in out, "a correctly configured machine must stay green"


def test_quickstart_tells_you_to_hold_the_key_that_works(monkeypatch, drifted):
    """Step 3 is one imperative. It has to name the key that actually dictates."""
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(drifted, live={"hotkey": "right_ctrl"}))
    out = CliRunner().invoke(cli.app, ["quickstart"]).output
    assert "Hold  right_ctrl" in out, out
    assert "Hold  right_alt" not in out
    assert "yazses restart" in out, "and it has to say why the file disagrees"


def test_quickstart_uses_the_configured_key_when_nothing_is_running(monkeypatch, drifted):
    """Before the first start there is no second opinion, and the file is the truth."""
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: _platform(drifted, live=None, running=False, reachable=False),
    )
    out = CliRunner().invoke(cli.app, ["quickstart"]).output
    assert "Hold  right_alt" in out, out
    assert "yazses restart" not in out
