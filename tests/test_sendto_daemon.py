"""Send to (ADR-031) wired into the daemon: which text goes, and what happens to it.

The pure planning is covered in `test_sendto_targets.py` and the opener in
`test_sendto_handoff.py`. What is tested here is the daemon's half of the promise:

* the staged buffer is the text when staged mode is on, and it is cleared **only** after
  a successful hand-off — a refusal or a client that did not open leaves every word;
* without staged mode, the last burst the daemon typed is the text;
* off by default, the IPC method refuses and opens nothing;
* the spoken phrase is handled before staged dictation (which would swallow it) and the
  last burst is only remembered while the feature is on.

The opener is the daemon's `_sendto_opener` seam, so nothing is launched.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

from yazses.config import Config, SendtoConfig, StagedConfig
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.sendto.targets import CLAUDE_MAX_CHARS


class _Opener:
    def __init__(self, result: bool = True):
        self.calls: list[str] = []
        self.result = result

    def __call__(self, url: str) -> bool:
        self.calls.append(url)
        return self.result


def _daemon(mocker, *, sendto: bool = True, staged: bool = False, opener=None):
    cfg = replace(
        Config(),
        sendto=SendtoConfig(enabled=sendto),
        staged=StagedConfig(enabled=staged),
    )
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_sendto = mocker.MagicMock()
    d._notify_staged = mocker.MagicMock()
    d._sendto_opener = opener if opener is not None else _Opener()
    return d


def _ipc(d, target):
    return d._handle_send_to(Request(method="send_to", params={"target": target}, id=1))


# ---- staged mode: the buffer is the text -------------------------------------------


def test_the_staged_buffer_is_handed_off_and_then_cleared(mocker):
    opener = _Opener()
    d = _daemon(mocker, staged=True, opener=opener)
    d._staged.stage("refactor the parser")
    d._staged.stage("and add a test")

    out = d._send_to("claude")

    assert out["ok"] is True and out["source"] == "staged"
    assert opener.calls == [
        "claude://claude.ai/new?q=refactor%20the%20parser%20and%20add%20a%20test"
    ]
    assert d._staged.is_empty
    assert "text" not in out and "refactor" not in repr(out)


def test_a_refused_hand_off_keeps_the_staged_buffer(mocker):
    opener = _Opener()
    d = _daemon(mocker, staged=True, opener=opener)
    long_text = "x" * (CLAUDE_MAX_CHARS + 1)
    d._staged.stage(long_text)

    out = d._send_to("claude")

    assert out["ok"] is False and out["reason"] == "too_long"
    assert opener.calls == []
    assert d._staged.text == long_text
    assert "still in the staged buffer" in str(out["message"])


def test_a_client_that_did_not_open_keeps_the_staged_buffer(mocker):
    d = _daemon(mocker, staged=True, opener=_Opener(result=False))
    d._staged.stage("keep me")

    out = d._send_to("codex")

    assert out["ok"] is False and out["reason"] == "open_failed"
    assert d._staged.text == "keep me"


def test_an_empty_buffer_is_refused_rather_than_sending_an_older_burst(mocker):
    opener = _Opener()
    d = _daemon(mocker, staged=True, opener=opener)
    d._sendto_last_burst = "an older burst"

    out = d._send_to("claude")

    assert out["ok"] is False and out["reason"] == "empty"
    assert opener.calls == []


# ---- no staged mode: the last burst ---------------------------------------------


def test_without_staged_mode_the_last_burst_is_handed_off(mocker):
    opener = _Opener()
    d = _daemon(mocker, staged=False, opener=opener)
    d._sendto_last_burst = " what does this function return"  # continuation space

    out = d._send_to("claude-code")

    assert out["ok"] is True and out["source"] == "last_burst"
    assert opener.calls == [
        "claude://code/new?q=what%20does%20this%20function%20return"
    ]


def test_nothing_dictated_yet_is_refused(mocker):
    opener = _Opener()
    d = _daemon(mocker, staged=False, opener=opener)
    out = d._send_to("codex")
    assert out["reason"] == "empty"
    assert opener.calls == []


def test_the_user_is_told_what_happened(mocker):
    d = _daemon(mocker, staged=False)
    d._sendto_last_burst = "hello there"
    d._send_to("codex")
    d._notify_sendto.assert_called_once()
    message = d._notify_sendto.call_args.args[0]
    assert "Codex" in message and "hello" not in message


# ---- the IPC method ------------------------------------------------------------


def test_the_ipc_method_refuses_while_the_feature_is_off(mocker):
    opener = _Opener()
    d = _daemon(mocker, sendto=False, staged=True, opener=opener)
    d._staged.stage("do not open")

    out = _ipc(d, "claude")

    assert out["ok"] is False and out["reason"] == "disabled"
    assert opener.calls == []
    assert d._staged.text == "do not open"


def test_the_ipc_method_hands_off_when_on(mocker):
    opener = _Opener()
    d = _daemon(mocker, staged=True, opener=opener)
    d._staged.stage("hi")
    out = _ipc(d, "codex")
    assert out["ok"] is True
    assert opener.calls == ["codex://new?prompt=hi"]


def test_the_ipc_method_takes_no_text_parameter(mocker):
    """No local caller can make the daemon open a URL with text of its choosing."""
    opener = _Opener()
    d = _daemon(mocker, staged=False, opener=opener)
    d._handle_send_to(Request(method="send_to",
                              params={"target": "claude", "text": "injected"}, id=1))
    assert opener.calls == []  # nothing dictated, and the injected text was ignored


def test_send_to_is_registered_on_the_ipc_server():
    source = inspect.getsource(Daemon._start_ipc_server)
    assert 'server.register("send_to", self._handle_send_to)' in source


# ---- the spoken path, by its position in the pipeline ------------------------------


def test_the_phrase_is_handled_before_staged_dictation_could_swallow_it():
    source = inspect.getsource(Daemon._on_hold_end)
    gate = source.index("if is_dictation and self._config.sendto.enabled:")
    phrase = source.index("parse_send_phrase(text)")
    staged = source.index("self._stage_or_commit(")
    assert gate < phrase < staged


def test_the_phrase_returns_without_reaching_the_injector():
    """The trigger phrase itself must never be typed into the focused window."""
    source = inspect.getsource(Daemon._on_hold_end)
    start = source.index("parse_send_phrase(text)")
    branch = source[start:source.index("return", start) + len("return")]
    assert "self._send_to(send_target)" in branch
    assert ".inject(" not in branch


def test_the_last_burst_is_kept_only_while_the_feature_is_on():
    source = inspect.getsource(Daemon._on_hold_end)
    assert (
        "if self._config.sendto.enabled:\n"
        "                    self._sendto_last_burst = text"
    ) in source


def test_a_default_daemon_keeps_no_burst(mocker):
    d = Daemon(config=Config(), platform=get_platform())
    assert d._config.sendto.enabled is False
    assert d._sendto_last_burst == ""
