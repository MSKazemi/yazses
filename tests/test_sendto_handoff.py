"""Send to (ADR-031): the opener seam, and what may and may not reach a log.

`sendto/handoff.py` is the one impure step. Its opener is injected here, so nothing is
launched. Three promises are pinned:

* **The text never reaches a log** — not on success, not on a refusal, not when the
  opener raises an exception whose message quotes the URL. The URL *is* the text,
  percent-encoded, so a test text made only of unreserved characters appears verbatim in
  it and any leak is visible to a plain substring check.
* **The opener is the inventoried browser hand-off**, called with `log_url=False`, and
  the package imports no network primitive and spawns nothing itself (ADR-019).
* **How Linux opens it** — `webbrowser`'s `xdg-open` launcher gets the URL as one argv
  element with no shell. That is the argv exposure ADR-031 §3 records; this pins it
  against the standard library rather than describing it from memory.

Not covered, and cannot be from here: whether a real Claude or Codex install pre-fills
without submitting. ADR-031 §5 requires a validation row per client and OS for that.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

import yazses.sendto as sendto_pkg
from yazses.sendto import handoff
from yazses.sendto.handoff import DISABLED_MESSAGE, default_opener, disabled_result, hand_off
from yazses.sendto.targets import CLAUDE_MAX_CHARS
from yazses.system.browser import open_url

#: Only RFC 3986 unreserved characters, so it is identical inside the encoded URL.
SECRET = "SECRET-PROMPT-zebra-7731"


class _Opener:
    def __init__(self, result=True, exc: Exception | None = None):
        self.calls: list[str] = []
        self._result = result
        self._exc = exc

    def __call__(self, url: str) -> bool:
        self.calls.append(url)
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


# ---- success -------------------------------------------------------------------


def test_a_hand_off_opens_the_planned_url_once():
    opener = _Opener()
    result = hand_off("claude", f"fix {SECRET}", opener=opener)
    assert result.ok
    assert opener.calls == [f"claude://claude.ai/new?q=fix%20{SECRET}"]
    assert (result.target, result.label, result.chars) == ("claude", "Claude", 4 + len(SECRET))


def test_the_message_says_it_was_not_sent_and_holds_no_text():
    result = hand_off("codex", SECRET, opener=_Opener())
    assert "press Enter" in result.message and "did not send" in result.message
    assert SECRET not in result.message
    assert SECRET not in repr(result.as_dict())


def test_success_logs_the_target_and_length_but_never_the_text(logs):
    hand_off("claude-code", SECRET, opener=_Opener())
    assert SECRET not in logs.text
    assert "claude-code" in logs.text and str(len(SECRET)) in logs.text


# ---- refusals never open anything -----------------------------------------------


@pytest.mark.parametrize(
    ("target", "text", "reason"),
    [
        ("claude", "x" * (CLAUDE_MAX_CHARS + 1), "too_long"),
        ("claude", "   ", "empty"),
        ("chatgpt", "hello", "unknown_target"),
        ("claude", "a\x00b", "invalid_text"),
        ("claude", "🎤" * 3000, "url_too_long"),
    ],
)
def test_a_refusal_never_calls_the_opener(target, text, reason):
    opener = _Opener()
    result = hand_off(target, text, opener=opener)
    assert not result.ok
    assert result.reason == reason
    assert opener.calls == []


def test_a_refusal_logs_no_text(logs):
    hand_off("claude", SECRET * 1000, opener=_Opener())
    assert SECRET not in logs.text


def test_an_unknown_target_name_is_not_logged_as_typed(logs):
    """A CLI argument is free text: a slip could put a prompt where the name goes."""
    hand_off(SECRET, "hello", opener=_Opener())
    assert SECRET not in logs.text


def test_a_staged_refusal_says_the_text_is_still_staged():
    result = hand_off("claude", "x" * (CLAUDE_MAX_CHARS + 1), opener=_Opener(), staged=True)
    assert "still in the staged buffer" in result.message
    empty = hand_off("claude", "", opener=_Opener(), staged=True)
    assert empty.message == "Nothing to send — nothing is staged."


# ---- the opener failing ---------------------------------------------------------


def test_an_opener_that_reports_false_is_a_failed_hand_off():
    result = hand_off("codex", SECRET, opener=_Opener(result=False))
    assert not result.ok
    assert result.reason == "open_failed"
    assert "Nothing was sent" in result.message


def test_an_opener_that_raises_with_the_url_in_its_message_leaks_nothing(logs):
    """An exception's message can quote its argument, and its argument is the text."""
    url_echo = RuntimeError(f"cannot open claude://claude.ai/new?q={SECRET}")
    result = hand_off("claude", SECRET, opener=_Opener(exc=url_echo))
    assert not result.ok
    assert result.reason == "open_failed"
    assert SECRET not in logs.text
    assert "RuntimeError" in logs.text


def test_disabled_result_opens_nothing_and_names_the_key():
    result = disabled_result("claude")
    assert not result.ok and result.reason == "disabled"
    assert result.message == DISABLED_MESSAGE
    assert "[sendto]" in DISABLED_MESSAGE and "enabled = true" in DISABLED_MESSAGE


# ---- the default opener is the inventoried browser hand-off -------------------------


def test_the_default_opener_is_open_url_with_logging_of_the_url_off(monkeypatch):
    seen: list[tuple[str, dict]] = []

    def fake_open_url(url, **kwargs):
        seen.append((url, kwargs))
        return True

    monkeypatch.setattr("yazses.system.browser.open_url", fake_open_url)
    assert default_opener("claude://claude.ai/new?q=x") is True
    assert seen == [("claude://claude.ai/new?q=x", {"log_url": False})]


def test_hand_off_without_an_opener_uses_the_default(monkeypatch):
    opener = _Opener()
    monkeypatch.setattr(handoff, "default_opener", opener)
    assert hand_off("codex", "hi").ok
    assert opener.calls == ["codex://new?prompt=hi"]


def test_open_url_with_log_url_off_does_not_log_the_url(logs):
    url = f"claude://claude.ai/new?q={SECRET}"

    def boom(u: str) -> bool:
        raise OSError(f"no handler for {u}")

    assert open_url(url, opener=boom, log_url=False) is False
    assert SECRET not in logs.text
    assert "OSError" in logs.text


def test_open_url_still_logs_the_url_for_everyone_else(logs):
    """The existing callers pass constant docs URLs; their failure log is unchanged."""
    def boom(_u: str) -> bool:
        raise OSError("no browser")

    assert open_url("https://example.test/docs", opener=boom) is False
    assert "https://example.test/docs" in logs.text


# ---- how Linux opens it -----------------------------------------------------------


def test_the_linux_launcher_gets_the_url_as_one_argv_element_and_no_shell(monkeypatch):
    """`webbrowser` registers `xdg-open` as a BackgroundBrowser on an X11/Wayland desktop.

    The URL is one argument — so hostile text cannot become a second argument or a shell
    command — and it IS in the child's argument list, the local exposure ADR-031 §3
    records. The standard library is exercised for real; only `Popen` is replaced.
    """
    import webbrowser

    spawned: list[tuple[list, dict]] = []

    class _Proc:
        def poll(self):
            return None  # still running: webbrowser reports that as handed off

    def fake_popen(cmdline, **kwargs):
        spawned.append((list(cmdline), kwargs))
        return _Proc()

    monkeypatch.setattr(webbrowser.subprocess, "Popen", fake_popen)
    url = handoff.plan_handoff("claude", "a; rm -rf ~ && echo $HOME `id`\n#x").url
    launcher = webbrowser.BackgroundBrowser("xdg-open")

    assert open_url(url, opener=launcher.open, log_url=False) is True
    assert len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv == ["xdg-open", url]
    assert not kwargs.get("shell")


# ---- no new egress primitive ----------------------------------------------------


def test_the_package_imports_no_network_primitive_and_spawns_nothing():
    """ADR-019: reuse the inventoried hand-off; add no outbound primitive of its own."""
    forbidden = {"webbrowser", "subprocess", "urllib", "socket", "http", "requests",
                 "httpx", "asyncio", "os"}
    package_dir = Path(sendto_pkg.__file__).parent
    sources = sorted(package_dir.glob("*.py"))
    assert len(sources) >= 3, "the scan found the package's modules"
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name} imports {name}"
