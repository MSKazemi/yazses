"""`yazses report` promised "never transcripts" and would have included them at DEBUG.

The bundle is designed to be attached to a public GitHub issue, and `system/report.py`'s
docstring says the log tail *"records levels, durations and word counts, never
transcripts."*

That is true at the default log level and false at one setting away from it.
`core/daemon.py` states the split where it writes them:

    # INFO: metadata only (length); DEBUG: the actual text.
    log.info("Injecting %d chars, %d words.", len(text), len(text.split()))
    log.debug("Injecting text: %r", text)

`[general] log_level = "DEBUG"` is supported, and it is exactly what someone turns on to
investigate the problem they are about to report. The tail took every line verbatim.

## Verified, not assumed

Searching this machine's real 5,465-line log for a distinctive four-word window of each of
1,262 recorded transcripts found **zero** hits — the default level really does keep dictation
out. The defect is the reachable exception, not the normal case.

## Dropped rather than warned about

A bundle that is safe to share *only if the reader noticed a warning* is not safe to share.
The value of this file is that its output is safe **by construction**, which is also why the
corpus is reported by size and never opened. So DEBUG lines are omitted and the count of
them is stated, so nothing is hidden from the person running it and anyone who needs those
lines can attach the log deliberately.
"""

from __future__ import annotations

from yazses.system.report import _log_tail

INFO = "2026-08-19 10:00:00,000 INFO yazses.core.daemon: Injecting 85 chars, 13 words."
WARN = "2026-08-19 10:00:00,002 WARNING yazses.core.daemon: Pipeline error: injector"
DEBUG = "2026-08-19 10:00:00,001 DEBUG yazses.core.daemon: Injecting text: 'my private sentence'"


def _tail(tmp_path, lines: list[str], n: int = 200) -> list[str]:
    path = tmp_path / "daemon.log"
    path.write_text("\n".join(lines), encoding="utf-8")
    return _log_tail(path, n)


def test_a_debug_line_is_not_included(tmp_path) -> None:
    out = _tail(tmp_path, [INFO, DEBUG, WARN])
    assert not any("my private sentence" in line for line in out)


def test_the_metadata_lines_are_kept(tmp_path) -> None:
    """The expensive direction: a filter that dropped everything would make the bundle
    useless, which is worse than the risk it removes."""
    out = _tail(tmp_path, [INFO, DEBUG, WARN])
    assert any("Injecting 85 chars" in line for line in out)
    assert any("Pipeline error" in line for line in out)


def test_the_omission_is_stated(tmp_path) -> None:
    """Nothing hidden from the person running it — they may still attach the log."""
    out = _tail(tmp_path, [INFO, DEBUG, DEBUG, WARN])
    note = [line for line in out if "omitted" in line]
    assert note, "DEBUG lines vanished with no mention"
    assert "2 line(s)" in note[0] and "DEBUG" in note[0]


def test_nothing_is_said_when_there_is_nothing_to_say(tmp_path) -> None:
    """A note on every report would train people to skim it."""
    out = _tail(tmp_path, [INFO, WARN])
    assert not any("omitted" in line for line in out)


def test_the_word_debug_inside_a_message_is_not_a_level(tmp_path) -> None:
    """The level is a field, not a substring: a message *about* debugging is metadata."""
    line = "2026-08-19 10:00:00,000 INFO yazses.cli: run with log_level=DEBUG to see more"
    out = _tail(tmp_path, [line])
    assert any("log_level=DEBUG" in item for item in out)
    assert not any("omitted" in item for item in out)


def test_a_missing_log_is_unchanged(tmp_path) -> None:
    assert _log_tail(tmp_path / "absent.log", 10) == ["<no log file>"]


def test_the_tail_limit_still_applies(tmp_path) -> None:
    """Filtering happens after the tail, so a huge DEBUG-heavy log cannot smuggle in
    older lines that the limit was meant to exclude."""
    lines = [f"2026-08-19 10:00:00,{i:03d} INFO x: line {i}" for i in range(100)]
    out = _tail(tmp_path, lines, n=10)
    assert len(out) == 10
    assert "line 99" in out[-1]


def test_the_daemon_still_splits_the_levels_this_way() -> None:
    """The whole filter rests on that split; if it changes, this must be revisited."""
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._on_hold_end)
    assert 'log.debug("Injecting text: %r", text)' in source
    assert 'log.info("Injecting %d chars, %d words."' in source


def test_the_default_log_level_is_still_info() -> None:
    """If the default ever became DEBUG, every user's log would hold their dictation."""
    from yazses.config import Config

    assert Config().general.log_level.upper() == "INFO"
