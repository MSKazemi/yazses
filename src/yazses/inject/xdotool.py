import subprocess

# xdotool sleeps this long between keystrokes. `type` is given it explicitly;
# `key` uses the same value as its own built-in default.
_DELAY_MS = 12

# Seconds of headroom per keystroke when sizing a timeout. Far above the 0.012 s
# xdotool actually spends, so a loaded machine cannot drift into a false timeout.
_SECONDS_PER_KEYSTROKE = 0.03


def _timeout_for(keystrokes: int) -> float:
    """Timeout for a command that sends *keystrokes* keys, one at a time.

    A **fixed** timeout is the bug this replaces. At 12 ms per keystroke a plain
    ``timeout=10`` expires around 833 characters — and it expires *after* xdotool
    has already typed part of the text, so the caller sees a failure for work
    that partly happened. ``LinuxInjector`` reads that as "this backend is
    broken" and falls back to the clipboard, which types the text a second time;
    the streaming commit then selects a span computed from the first copy and
    deletes the wrong text. ``YdotoolInjector`` has scaled its timeout for this
    reason since the Wayland flood fix — the X11 path simply never got it.
    """
    return 10.0 + max(keystrokes, 0) * _SECONDS_PER_KEYSTROKE


class XdotoolInjector:
    def inject(self, text: str) -> None:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", str(_DELAY_MS), "--", text],
            check=True,
            timeout=_timeout_for(len(text)),
        )

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        subprocess.run(
            ["xdotool", "key", "--repeat", str(count), "BackSpace"],
            check=True,
            timeout=_timeout_for(count),
        )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        # A run of one repeated key — which is exactly what the streaming commit
        # sends, `["shift+Left"] * len(partial)` — goes as a single `--repeat`
        # spec rather than N argv entries. Same keystrokes, but it keeps a
        # thousand-character correction off the argv length limit and matches how
        # `inject_backspaces` has always done it.
        if len(keys) > 1 and len(set(keys)) == 1:
            cmd = ["xdotool", "key", "--clearmodifiers", "--repeat", str(len(keys)), keys[0]]
        else:
            cmd = ["xdotool", "key", "--clearmodifiers"] + keys
        subprocess.run(cmd, check=True, timeout=_timeout_for(len(keys)))
