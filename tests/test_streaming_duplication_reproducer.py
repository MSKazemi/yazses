"""#153 end to end: a long streaming dictation on X11 must leave exactly the final text.

`test_streaming_correction_safety.py` pins the three defects of #153 one at a time
(the xdotool timeout, the repeated-key argv, the unsynchronised injector). None of
those tests looks at what the *user* reported -- text typed twice, then a correction
pass that deleted text they wanted to keep -- because none of them has a screen.

This file has one. `_Screen` is a minimal model of a text field driven through the
real argv that `XdotoolInjector` and `ClipboardInjector` build, and it charges
xdotool's 12 ms per keystroke against the timeout the caller passed. When the budget
runs out it does what `subprocess.run` does to a real xdotool: the keystrokes
already sent stay on screen, and `TimeoutExpired` is raised for work that partly
happened. That is the whole mechanism of #153, so the reproducer needs nothing else.

Under the fixed `timeout=10` that `XdotoolInjector` had before `e0debe7e`
("fix(streaming): stop the correction pass deleting text it never typed (#153)"), a
long text is typed once by the killed xdotool and again by the clipboard paste, and
the commit's selection runs past the partials into text the user had already
written. The last two tests pin exactly that, so the model cannot quietly stop
charging for keystrokes. The long-dictation test is green since that commit and goes
red again if `xdotool._timeout_for` is put back to a fixed 10 s.

The model is deliberately small: one line, a cursor, a shift-selection anchor, and a
clipboard. It does not model the literal `DDDD` flood, which #153 records as still
unexplained; it models the duplication and the deletion, which are explained.
"""

from __future__ import annotations

import subprocess

import pytest

from yazses.inject.streaming import StreamingInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.platform.linux.injector import LinuxInjector

# xdotool's real per-keystroke delay (`type --delay 12`, and `key`'s default).
_SECONDS_PER_KEYSTROKE = 0.012


class _Screen:
    """One line of text, a cursor, an optional shift-selection, and a clipboard."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.cursor = len(text)
        self.anchor: int | None = None  # set while a shift-selection is active
        self.clipboard = ""

    # -- editing primitives ----------------------------------------------------

    def _selection(self) -> tuple[int, int] | None:
        if self.anchor is None or self.anchor == self.cursor:
            return None
        return min(self.anchor, self.cursor), max(self.anchor, self.cursor)

    def _delete_selection(self) -> bool:
        sel = self._selection()
        self.anchor = None
        if sel is None:
            return False
        start, end = sel
        self.text = self.text[:start] + self.text[end:]
        self.cursor = start
        return True

    def type_char(self, ch: str) -> None:
        self._delete_selection()
        self.text = self.text[: self.cursor] + ch + self.text[self.cursor :]
        self.cursor += 1

    def key(self, spec: str) -> None:
        if spec == "shift+Left":
            if self.anchor is None:
                self.anchor = self.cursor
            self.cursor = max(0, self.cursor - 1)
        elif spec == "BackSpace":
            if not self._delete_selection() and self.cursor > 0:
                self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
                self.cursor -= 1
        elif spec == "ctrl+v":
            for ch in self.clipboard:
                self.type_char(ch)
        else:  # pragma: no cover - a key this model was never asked to press
            raise AssertionError(f"unmodelled key {spec!r}")

    # -- the fake subprocess.run -----------------------------------------------

    def run(self, cmd, check=False, timeout=None, input=None, **_kw):
        """Apply *cmd* to the screen, honouring *timeout* the way a real tool does."""
        tool = cmd[0]
        if tool == "xclip":
            self.clipboard = input.decode()
            return subprocess.CompletedProcess(cmd, 0)
        assert tool == "xdotool", cmd
        if cmd[1] == "type":
            text = cmd[cmd.index("--") + 1]
            steps = [lambda ch=ch: self.type_char(ch) for ch in text]
        else:
            assert cmd[1] == "key", cmd
            args = [a for a in cmd[2:] if a != "--clearmodifiers"]
            repeat = 1
            if args[:1] == ["--repeat"]:
                repeat, args = int(args[1]), args[2:]
            steps = [lambda k=k: self.key(k) for k in args * repeat]
        budget = len(steps) if timeout is None else int(timeout / _SECONDS_PER_KEYSTROKE)
        for step in steps[:budget]:
            step()
        if len(steps) > budget:
            # The keystrokes already sent stay sent -- exactly what a killed xdotool leaves.
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0)


@pytest.fixture
def x11_linux_injector(monkeypatch):
    """`LinuxInjector` on X11: xdotool primary, clipboard fallback, both on `_Screen`."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("YAZSES_INJECT_FALLBACK", "1")
    monkeypatch.setattr("yazses.platform.linux.injector.get_injector", XdotoolInjector)
    screen = _Screen("KEEP THIS. ")
    # Both backends do `import subprocess` and call `subprocess.run`.
    monkeypatch.setattr(subprocess, "run", screen.run)
    return LinuxInjector(), screen


def _dictate(injector, partials: list[str], final: str) -> None:
    stream = StreamingInjector(injector)
    for piece in partials:
        stream.inject_partial(piece)
    stream.commit(final)


def _sentence_partials(n_sentences: int) -> tuple[list[str], str]:
    """Partials the way a streaming decoder emits them, and a final that differs."""
    partials = [f"partial number {i} of a long dictation. " for i in range(n_sentences)]
    final = "".join(f"final sentence {i} of a long dictation. " for i in range(n_sentences))
    return partials, final


def test_short_dictation_leaves_exactly_the_final_text(x11_linux_injector):
    injector, screen = x11_linux_injector
    partials, final = _sentence_partials(3)
    _dictate(injector, partials, final)
    assert screen.text == "KEEP THIS. " + final


def test_long_dictation_is_neither_duplicated_nor_eats_the_prefix(x11_linux_injector):
    """The #153 report, end to end: >833 characters is where a fixed 10 s expired.

    Before `e0debe7e` this ended with "KEEP THIS. " partly selected away by the
    fallback's second `shift+Left` pass, and the final text typed once by a killed
    xdotool and again by the clipboard paste.
    """
    injector, screen = x11_linux_injector
    partials, final = _sentence_partials(40)
    assert len("".join(partials)) > 1000 and len(final) > 1000  # past the old wall
    _dictate(injector, partials, final)
    assert screen.text.count(final) == 1, "the final text was typed more than once"
    assert screen.text == "KEEP THIS. " + final


def _fixed_ten_second_timeout(monkeypatch):
    """Put `XdotoolInjector` back to the fixed `timeout=10` it had before `e0debe7e`."""
    monkeypatch.setattr("yazses.inject.xdotool._timeout_for", lambda _n: 10.0)


def test_the_model_types_twice_under_a_fixed_timeout(x11_linux_injector, monkeypatch):
    """The red half of the red/green, for the duplication.

    Kept in the suite so a later edit to `_Screen` that stopped charging for
    keystrokes fails here, rather than turning the tests above green for the wrong
    reason. A killed xdotool leaves ~833 characters on screen; `LinuxInjector` reads
    the timeout as a broken backend and the clipboard pastes the whole text again.
    """
    injector, screen = x11_linux_injector
    _fixed_ten_second_timeout(monkeypatch)
    _partials, final = _sentence_partials(40)
    injector.inject(final)
    assert screen.text == "KEEP THIS. " + final[:833] + final


def test_the_model_selects_the_prefix_under_a_fixed_timeout(x11_linux_injector, monkeypatch):
    """The red half for the deletion: the correction selects text it never typed.

    The commit's `shift+Left` pass is killed at ~833 keystrokes, the clipboard
    fallback replays the *whole* sequence on top of it, and the selection runs past
    the start of the partials into "KEEP THIS. ". Whatever is typed next -- the
    final text, or the user's own next keystroke -- deletes it.

    Whether the commit then *raises* depends on the fallback's own timeout: while
    `ClipboardInjector`'s key paths had a fixed 10 s too (until QA-004) the replay
    was killed as well and the commit raised with the prefix still selected; with
    them scaled the replay completes and the final text types straight over the
    prefix. The damage is the same either way, so the test asserts the damage.
    """
    injector, screen = x11_linux_injector
    _fixed_ten_second_timeout(monkeypatch)
    partials, final = _sentence_partials(40)
    stream = StreamingInjector(injector)
    for piece in partials:
        stream.inject_partial(piece)
    try:
        stream.commit(final)
    except subprocess.TimeoutExpired:
        pass
    prefix = "KEEP THIS. "
    deleted = not screen.text.startswith(prefix)
    selected = screen.anchor is not None and min(screen.anchor, screen.cursor) < len(prefix)
    assert deleted or selected, "the correction left the prefix the user kept alone"
