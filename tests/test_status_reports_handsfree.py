"""`yazses status` said nothing about any camera input — EYE-OBS-001 (#416).

`doctor` can answer "could this work?" — it reads the config, the packages, the permission
and the calibration. It structurally cannot answer "is it working *now*?", because the
consumers live in another process. That second question is the one a hands-free user has
when the cursor stops moving, and the daemon was publishing nothing about it.

Three things held here.

**The field says nothing on an ordinary install.** `status` is polled continuously by the
tray and the overlay and its payload has fourteen readers, so this must not change what any
of them sees. Every camera capability ships off, so the value is `null` and no line is
printed. `null` rather than an absent key because the key has to stay a literal inside the
dict `_handle_status` returns — see the last test in this file for what moving it broke.

**An older daemon does not read as "everything is fine".** The daemon keeps running the
build it started with until `yazses restart`, so a new CLI against an old daemon is an
ordinary post-upgrade state. A missing field must print no line, not a green one.

**Nothing expensive happens on a poll.** No disk read, no subprocess: the calibration check
and the camera-permission probe stay in `doctor`, and the payload reports them as *not
determined* rather than paying for them on every tick of the tray.
"""

from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses.cli import app
from yazses.config import Config
from yazses.core.daemon import Daemon

BASE = {
    "state": "idle",
    "hotkey": "right_ctrl",
    "model": "base.en",
    "injection_backend": "XdotoolInjector",
    "uptime_s": 60.0,
    "ready": True,
}


class _Client:
    def __init__(self, status):
        self._status = status

    def is_reachable(self):
        return True

    def call(self, _method, **_kw):
        return self._status


@pytest.fixture
def run(monkeypatch):
    from yazses import cli

    def _go(status_extra):
        class _Lifecycle:
            def read_pid(self):
                return 1234

            def is_running(self):
                return True

        class _Paths:
            ipc_socket = "/tmp/nope.sock"
            data_dir = "/tmp"
            config_file = "/tmp/config.toml"

        class _Platform:
            name = "linux"
            lifecycle = _Lifecycle()
            paths = _Paths()

            @staticmethod
            def ipc_client_factory(_s):
                return _Client({**BASE, **status_extra})

        monkeypatch.setattr(cli, "get_platform", lambda: _Platform())
        return CliRunner().invoke(app, ["status"])

    return _go


# --- the CLI side --------------------------------------------------------------------


def test_a_local_install_with_no_camera_feature_says_nothing(run) -> None:
    result = run({})
    assert result.exit_code == 0, result.output
    for label in ("hands-free", "face switch", "pointer output"):
        assert label not in result.output.lower()


def test_an_older_daemon_without_the_field_says_nothing(run) -> None:
    """A payload predating the field must not read as "hands-free is healthy"."""
    result = run({"handsfree": None})
    assert result.exit_code == 0, result.output
    assert "hands-free" not in result.output.lower()


def test_a_faulted_face_switch_is_reported_with_its_reason(run) -> None:
    result = run({"handsfree": {
        "features_requested": ["facegesture"],
        "camera_ready": True,
        "perception_state": "running",
        "perception_consumers": 1,
        "face_wired": True,
        "safety_configured": True,
        "safety_window_ms": 500,
        "safety": {
            "state": "faulted",
            "reason": "facegesture: the camera was taken by another application",
            "terminal": False,
            "user_paused": False,
            "epoch": 3,
            "sources": [{
                "name": "facegesture", "armed": False, "stale": False, "faulted": True,
                "reason": "the camera was taken by another application",
                "age_ms": 120.0, "epoch": 3,
            }],
        },
    }})
    assert result.exit_code == 0, result.output
    assert "face switch:" in result.output
    assert "taken by another application" in result.output
    assert "hands-free safety:" in result.output


def test_a_malformed_hands_free_field_does_not_break_status(run) -> None:
    """The payload comes from another process. A `status` that tracebacks against a running
    daemon is worse than a missing line."""
    for junk in ("a string", 17, {"features_requested": "gaze"}, {"safety": []}):
        result = run({"handsfree": junk})
        assert result.exit_code == 0, result.output


def test_no_sensor_value_can_be_printed_even_if_the_daemon_sends_one(run) -> None:
    """The renderer reads a whitelist, so an unknown key on the wire reaches nothing.

    Worth its own test because the daemon is the untrusted end here as far as this code is
    concerned: a future field added there must not become printable by existing.
    """
    result = run({"handsfree": {
        "features_requested": ["gaze"],
        "camera_ready": True,
        "last_gaze_x": 0.418273,
        "blendshapes": {"jawOpen": 0.913744},
    }})
    assert result.exit_code == 0, result.output
    assert "0.418273" not in result.output
    assert "0.913744" not in result.output
    assert "jawOpen" not in result.output


# --- the daemon side -----------------------------------------------------------------


class _FaceSourceStandIn:
    """Stands in for `facegesture/backend.py`'s source, identified the way the daemon does.

    By module and not by class name, and not with `isinstance`: the name is a string two
    files can agree on by accident, and importing the real backend to compare types would
    pull a camera module into a status poll.
    """


_FaceSourceStandIn.__module__ = "yazses.facegesture.backend"


class _EmgSourceStandIn:
    """The other kind of activation source. It must not be counted as a camera consumer."""


_EmgSourceStandIn.__module__ = "yazses.emg.backend"


def _fake_daemon(cfg, *, gaze=False, face=False, emg=False):
    """Just enough of a daemon for the real payload method: it reads three attributes."""
    sources: list[object] = []
    if face:
        sources.append(_FaceSourceStandIn())
    if emg:
        sources.append(_EmgSourceStandIn())
    return types.SimpleNamespace(
        _config=cfg,
        _gaze_targeter=object() if gaze else None,
        _extra_activations=sources,
    )


def test_the_daemon_publishes_nothing_on_a_default_install() -> None:
    assert Daemon._handsfree_payload(_fake_daemon(Config())) is None


def test_the_daemon_reports_a_camera_consumer_it_actually_built() -> None:
    cfg = Config()
    cfg.facegesture.enabled = True
    payload = Daemon._handsfree_payload(_fake_daemon(cfg, face=True))
    assert payload is not None
    assert payload["perception_state"] == "running"
    assert payload["perception_consumers"] == 1
    assert payload["face_wired"] is True


def test_a_feature_that_is_on_and_was_never_constructed_is_not_reported_as_wired() -> None:
    """The distinction that matters: "your face switch is broken" and "your face switch was
    never built because the webcam deps are missing" send a reader to two different places.
    """
    cfg = Config()
    cfg.facegesture.enabled = True
    payload = Daemon._handsfree_payload(_fake_daemon(cfg, face=False))
    assert payload is not None
    assert payload["perception_state"] == "stopped"
    assert payload["face_wired"] is False
    assert "yazses doctor" in str(payload["perception_reason"])


def test_a_non_camera_activation_source_is_not_counted_as_a_camera_consumer() -> None:
    """EMG shares the activation-source list with the face switch. Counting a wrist band as
    a camera consumer would report a running camera on a machine whose lid is shut."""
    cfg = Config()
    cfg.facegesture.enabled = True
    payload = Daemon._handsfree_payload(_fake_daemon(cfg, face=False, emg=True))
    assert payload is not None
    assert payload["perception_state"] == "stopped"
    assert payload["perception_consumers"] == 0


def test_the_payload_claims_nothing_the_daemon_did_not_measure() -> None:
    """No disk read and no subprocess on a poll, so these stay undetermined here."""
    cfg = Config()
    cfg.gaze.enabled = True
    payload = Daemon._handsfree_payload(_fake_daemon(cfg, gaze=True))
    assert payload is not None
    assert payload["camera_ready"] is None
    assert payload["calibration_validity"] == ""
    assert payload["perception_channels"] is None


def test_the_status_handler_publishes_the_field_from_the_dict_it_returns() -> None:
    """Two things at once, and the second is why the key is a literal with a null value.

    `tests/test_report_redacts_the_daemon_block.py` walks this function's AST for the dict
    it *returns* and classifies every literal key as machine fact or user prose. Building
    the payload into a local and adding the key afterwards found six keys instead of
    thirty-seven and switched that privacy guard off without failing anything — so the key
    stays inside the returned literal and carries `None` when there is nothing to say.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._handle_status)))
    returned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            returned |= {
                key.value for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    assert "handsfree" in returned, (
        "the hands-free field is not a literal key of the dict `_handle_status` returns; "
        f"found {sorted(returned)}"
    )
    assert len(returned) >= 30, f"the returned dict was not found intact: {sorted(returned)}"


def test_the_payload_is_null_and_not_a_missing_key_on_a_default_install() -> None:
    """`None` is the "nothing to report" value every reader already treats as falsy."""
    assert Daemon._handsfree_payload(_fake_daemon(Config())) is None
