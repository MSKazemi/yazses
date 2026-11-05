"""Send to pre-fills a client; it never submits (ADR-031, issues #800 and #637).

The guarantee under test is structural, so the tests are pure and synthetic:

* the only thing the hand-off emits is ONE URL, to an injected opener, and that URL is
  inert text: no raw CR/LF/control byte, so no line break can reach the client except as
  the percent-encoded data the user dictated;
* the package never imports a keystroke-injection backend, a subprocess or a socket, and
  its code names no Enter/Return/submit key, so no key event can be synthesised there;
* the platform UrlOpener seam is the only door, and the daemon's hand-off method does
  not touch the injector.

NOT proven here (no real client was run; ADR-031 section 5 wants a row per client and
OS): that Claude, Claude Code or Codex, on Linux, macOS or Windows, actually leave the
prompt unsubmitted when handed the URL. Linux-only, no-client, synthetic evidence.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from yazses.sendto import handoff, targets
from yazses.sendto.handoff import hand_off
from yazses.sendto.targets import TARGETS, plan_handoff

SENDTO_DIR = Path(targets.__file__).parent

HOSTILE_TEXTS = [
    "plain dictation",
    "line one\nline two\r\nline three",
    "\n",  # only whitespace, refused as empty
    "ends with newline\n",
    "tab\tseparated",
    "press enter\n\n\n",
    "x%0Ay&submit=1#frag",
    "unicode   line sep   para \u0085 nel ‏ rtl",
    "﻿bom and é中文",
]


@pytest.mark.parametrize("slug", sorted(TARGETS))
@pytest.mark.parametrize("text", HOSTILE_TEXTS)
def test_handed_url_is_one_inert_line_and_opener_is_called_at_most_once(slug, text):
    seen: list[str] = []

    def opener(url: str) -> bool:
        seen.append(url)
        return True

    result = hand_off(slug, text, opener=opener)
    assert len(seen) <= 1
    if not seen:
        assert not result.ok
        return
    url = seen[0]
    # Nothing but printable ASCII: no raw space, line break or control byte of any kind.
    assert re.fullmatch(r"[\x21-\x7e]+", url), "URL holds a raw space or control char"
    t = TARGETS[slug]
    assert url.startswith(f"{t.scheme}://{t.path}?{t.param}=")
    query = url.partition("?")[2]
    assert "&" not in query and "#" not in url and query.count("=") == 1
    assert "did not send it" in result.message


def test_embedded_newline_reaches_the_client_only_as_percent_encoded_data():
    plan = plan_handoff("claude", "a\nb\r\nc")
    assert plan.ok
    assert "%0A" in plan.url and "%0D%0A" in plan.url
    assert "\n" not in plan.url and "\r" not in plan.url


def test_a_failed_or_raising_opener_sends_nothing_and_never_retries():
    calls: list[str] = []

    def boom(url: str) -> bool:
        calls.append(url)
        raise OSError("secret prompt text")

    result = hand_off("codex", "dictated words", opener=boom)
    assert not result.ok and len(calls) == 1
    assert "secret prompt text" not in result.message


def test_default_opener_refuses_anything_outside_the_target_table(monkeypatch):
    def forbidden():  # pragma: no cover - must not be reached
        raise AssertionError("platform opener reached for a non-target URL")

    monkeypatch.setattr("yazses.platform.factory.get_url_opener", forbidden)
    for url in ("https://example.com/?q=x", "file:///etc/passwd", "javascript:1", "x"):
        assert handoff.default_opener(url) is False


_FORBIDDEN_IMPORT_ROOTS = (
    "subprocess", "os", "socket", "ctypes", "webbrowser", "urllib", "http",
    "pynput", "evdev", "uinput", "pyautogui", "keyboard", "yazses.inject",
    "yazses.audio", "yazses.platform.linux", "yazses.platform.windows",
    "yazses.platform.macos",
)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


@pytest.mark.parametrize("path", sorted(SENDTO_DIR.glob("*.py")), ids=lambda p: p.name)
def test_sendto_package_imports_no_key_injection_or_process_or_network(path):
    bad = {
        name for name in _imports(path)
        if any(name == r or name.startswith(r + ".") for r in _FORBIDDEN_IMPORT_ROOTS)
    }
    assert not bad, f"{path.name} imports {sorted(bad)}"


_KEY_WORDS = re.compile(
    r"\b(kp_enter|vk_return|keysym|sendkeys?|press_key|key_event|keycode)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", sorted(SENDTO_DIR.glob("*.py")), ids=lambda p: p.name)
def test_sendto_code_names_no_key_event_identifier_or_literal(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and _KEY_WORDS.search(n.id):
            hits.append((n.lineno, n.id))
        elif isinstance(n, ast.Attribute) and _KEY_WORDS.search(n.attr):
            hits.append((n.lineno, n.attr))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            if _KEY_WORDS.search(n.value) or n.value.strip() in {"Return", "Enter"}:
                hits.append((n.lineno, n.value[:40]))
    assert not hits, f"{path.name}: {hits}"


def test_daemon_send_to_method_never_touches_the_injector():
    src = Path(handoff.__file__).parents[1] / "core" / "daemon.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    methods = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name != "__init__"
        and "hand_off(" in ast.unparse(n)
    ]
    assert methods, "daemon hand-off method not found; update this test"
    for fn in methods:
        text = ast.unparse(fn)
        assert not re.search(r"inject|type_text|send_key|press", text, re.IGNORECASE), (
            f"{fn.name} touches the injector"
        )
