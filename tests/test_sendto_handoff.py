"""Send to (ADR-031): the opener seam, and what may and may not reach a log.

`sendto/handoff.py` is the one impure step. Its opener is injected here, so nothing is
launched. Three promises are pinned:

* **The text never reaches a log** — not on success, not on a refusal, not when the
  opener raises an exception whose message quotes the URL. The URL *is* the text,
  percent-encoded, so a test text made only of unreserved characters appears verbatim in
  it and any leak is visible to a plain substring check.
* **The default opener is the platform seam** — `platform.get_url_opener()`, the
  `UrlOpener` beside `FileOpener` (ADR-031 §3) — reached only for a scheme from the closed
  target table, and the package imports no network primitive and spawns nothing itself
  (ADR-019).
* **How Linux opens it without a portal** — `LinuxUrlOpener` tries the desktop portal's
  `OpenURI` over D-Bus first (no argv holds the URL); `tests/conftest.py` refuses the
  session bus to every test, so here it takes the fallback, passing the planned URL,
  hostile text and all, to `xdg-open` as one argv element with no shell. That fallback is
  the argv exposure ADR-031's implementation notes record; the portal path and the other
  per-OS backends are pinned in `test_platform_url_opener_seam.py`.

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


# ---- the default opener is the platform seam --------------------------------------


class _FakeUrlOpener:
    def __init__(self, exc: Exception | None = None):
        self.urls: list[str] = []
        self._exc = exc

    def open_url(self, url: str) -> None:
        self.urls.append(url)
        if self._exc is not None:
            raise self._exc


def test_the_default_opener_goes_through_the_platform_url_opener(monkeypatch):
    fake = _FakeUrlOpener()
    monkeypatch.setattr("yazses.platform.factory.get_url_opener", lambda: fake)
    assert default_opener("claude://claude.ai/new?q=x") is True
    assert fake.urls == ["claude://claude.ai/new?q=x"]


@pytest.mark.parametrize(
    "url",
    [
        f"https://claude.ai/new?q={SECRET}",
        f"http://claude.ai/new?q={SECRET}",
        f"file:///tmp/{SECRET}",
        f"javascript:alert('claude://{SECRET}')",
        f"chatgpt://new?q={SECRET}",
        SECRET,
    ],
)
def test_the_default_opener_refuses_a_scheme_outside_the_target_table(monkeypatch, logs, url):
    """The allow-list at the caller: the platform seam is never even asked."""
    fake = _FakeUrlOpener()
    monkeypatch.setattr("yazses.platform.factory.get_url_opener", lambda: fake)
    assert default_opener(url) is False
    assert fake.urls == []
    assert SECRET not in logs.text


def test_the_target_schemes_are_exactly_the_closed_table_s():
    assert handoff._TARGET_SCHEMES == {"claude", "codex"}


@pytest.mark.parametrize(
    "exc",
    [
        OSError(f"xdg-open could not open claude://claude.ai/new?q={SECRET}"),
        NotImplementedError("Unsupported platform: aix7"),
        ValueError(f"refused claude://claude.ai/new?q={SECRET}"),
    ],
)
def test_a_platform_failure_is_a_failed_hand_off_that_leaks_nothing(monkeypatch, logs, exc):
    """No backend for this OS, no registered program, a refusal: all reported by type."""
    monkeypatch.setattr("yazses.platform.factory.get_url_opener",
                        lambda: _FakeUrlOpener(exc=exc))
    result = hand_off("claude", SECRET)
    assert not result.ok
    assert result.reason == "open_failed"
    assert SECRET not in logs.text
    assert SECRET not in repr(result.as_dict())
    assert type(exc).__name__ in logs.text


def test_an_os_with_no_url_opener_is_a_failed_hand_off_not_a_browser(monkeypatch, logs):
    """The real factory on an OS it has no backend for: refused, and nothing else tried."""
    import sys

    monkeypatch.setattr(sys, "platform", "aix7")
    result = hand_off("codex", SECRET)
    assert not result.ok and result.reason == "open_failed"
    assert "NotImplementedError" in logs.text
    assert SECRET not in logs.text


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
    """Through the real `default_opener` and the real factory, with only `Popen` faked.

    With no session bus (conftest's default, and the production fallback) the URL is one
    argument — so hostile text cannot become a second argument or a shell command — and
    it IS in the child's argument list, the local exposure ADR-031 records for the
    fallback. Its output goes to /dev/null: `xdg-open` quotes its argument when it fails.
    """
    import subprocess
    import sys

    from yazses.platform.linux import fileopen as linux_fileopen

    spawned: list[tuple[list, dict]] = []

    class _Proc:
        def wait(self, timeout=None):
            return 0

    def fake_popen(cmdline, **kwargs):
        spawned.append((list(cmdline), kwargs))
        return _Proc()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(linux_fileopen.subprocess, "Popen", fake_popen)
    url = handoff.plan_handoff("claude", "a; rm -rf ~ && echo $HOME `id`\n#x").url

    assert default_opener(url) is True
    assert len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv == ["xdg-open", url]
    assert not kwargs.get("shell")
    assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL


# ---- no new egress primitive ----------------------------------------------------


def test_the_package_imports_no_network_primitive_and_spawns_nothing():
    """ADR-019: no outbound primitive of its own — processes and OS calls stay behind the
    platform seam, where `sys.platform` may be read."""
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
