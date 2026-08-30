"""The Android content-logging gate must scan log *statements*, not lines.

`checkNoContentLogging` (ADR-MOB-007) fails the build when a log call mentions a
transcript or raw audio, because logcat is readable by the user, by any bug report
and by anything holding `READ_LOGS`. It scanned the file a line at a time, so it saw
only leaks that fit on one line:

    Log.d("tag", "got $transcript")          // caught
    Log.d(                                   // was not caught
        "tag",
        "got $transcript",
    )

Those are the same leak. Worse, the second is the shape a log call takes the moment
it grows past a line-length rule -- these sources already wrap 26 calls -- so the
most likely formatting was the one the gate could not see.

Verified against the real task, five cases: the wrapped leak now fails, the
single-line one still fails, a `)` inside the message no longer truncates the scan,
metadata-only logging still passes, and the repository still passes.

This file cannot run Gradle, so it is a **tripwire, not a proof**: it holds the two
properties whose loss would silently restore the hole -- reading whole text rather
than lines, and a paren scan that treats string literals as opaque. The failure mode
being guarded is a copy-paste from an older revision, which is how the desktop's
`comment` rule and the disfluency guard both regressed in the port.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRIVACY = ROOT / "android/gradle/privacy.gradle.kts"


def _gate_body() -> str:
    """The `checkNoContentLogging` registration, to the end of the file."""
    text = PRIVACY.read_text(encoding="utf-8")
    start = text.index("val checkNoContentLogging by tasks.registering")
    return text[start:]


def test_the_gate_still_exists() -> None:
    """Guards against every test below passing on a file that lost the task."""
    assert "checkNoContentLogging" in PRIVACY.read_text(encoding="utf-8"), (
        f"{PRIVACY.relative_to(ROOT)} no longer registers the content-logging gate"
    )


def test_the_gate_does_not_scan_line_by_line() -> None:
    body = _gate_body()
    assert "readLines()" not in body, (
        "checkNoContentLogging is reading the source line by line again. A log call "
        "wrapped across lines -- which is what one becomes as soon as it passes a "
        "line-length rule -- then carries a transcript past the gate unseen."
    )
    assert "readText()" in body, (
        "checkNoContentLogging no longer reads whole file text, so it cannot see a "
        "log call that spans lines."
    )


def test_the_scanner_treats_string_literals_as_opaque() -> None:
    """Without this, one `)` in a message ends the argument list early and every
    later call in the file is read at the wrong offset -- a gate that reports
    nothing while scanning the wrong bytes."""
    text = PRIVACY.read_text(encoding="utf-8")
    assert "fun logCallArguments" in text, (
        "the statement-level scanner is gone; see this file's docstring for what it "
        "was for."
    )
    scanner = text[text.index("fun logCallArguments"):]
    scanner = scanner[: scanner.index("\nval checkNoContentLogging")]
    for marker in ("inString", "inRawString", "depth"):
        assert marker in scanner, (
            f"logCallArguments no longer tracks `{marker}`. Parentheses inside a "
            "string literal do not nest, and a raw string may contain anything; a "
            "scan that ignores either finds the wrong closing paren."
        )


@pytest.mark.parametrize(
    "identifier", ["transcript", "utterance", "pcm", "samples", "audioBuffer"],
)
def test_the_identifiers_that_name_speech_are_still_listed(identifier: str) -> None:
    """The list is hand-written, which is its weakness -- so at minimum the ones
    naming recognised speech and raw audio must not quietly leave it."""
    text = PRIVACY.read_text(encoding="utf-8")
    listing = text[text.index("val contentIdentifiers"):]
    listing = listing[: listing.index(")")]
    assert f'"{identifier}"' in listing, (
        f"`{identifier}` was removed from contentIdentifiers. It names recognised "
        "speech or raw audio; a log line carrying it is the same leak as sending it."
    )


def test_the_log_call_pattern_covers_the_forms_in_use() -> None:
    """`println` matters as much as `Log.d` here: the `:core:*` modules are plain
    `kotlin("jvm")` and have no `android.util.Log` to call."""
    text = PRIVACY.read_text(encoding="utf-8")
    match = re.search(r'val logCall = Regex\("""(.+?)"""\)', text)
    assert match, "the log-call pattern is no longer declared as `val logCall`"
    pattern = match.group(1)
    for form in ("Log.d(\"t\", \"x\")", "logger.info(\"x\")", "println(\"x\")"):
        assert re.search(pattern, form), (
            f"the log-call pattern no longer matches {form!r}, so that form of "
            "logging is exempt from the gate entirely."
        )
