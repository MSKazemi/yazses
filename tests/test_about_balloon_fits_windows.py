"""The Windows About notification must fit the buffer Windows gives it.

The Windows tray has no dialog, so About is rendered as a balloon notification:
``icon.notify(body, title)``. pystray's win32 backend writes that body into
``NOTIFYICONDATA.szInfo``, a **256-wide-character** field including the terminator.

The full About body is 347 characters. It overran, and the tray's ``_notify`` wrapper
swallows every exception into ``log.debug`` — so on Windows the About entry did nothing
visible and left no trace anyone would find. That is the reported symptom: *"the about
GUI does not work, it does not show anything"*.

The fix drops whole lines rather than cutting mid-string, because a truncated URL still
looks like a link and is not one.
"""
from __future__ import annotations

from yazses.tray.about import BALLOON_LIMIT, about_lines, balloon_body


def test_the_full_about_body_really_does_overrun():
    """The premise. If this ever stops being true the trimming is dead weight."""
    full = "\n".join(about_lines())
    assert len(full) > BALLOON_LIMIT, (
        f"About is now {len(full)} chars, within the {BALLOON_LIMIT}-char balloon — "
        "the trimming below is no longer load-bearing and can be reconsidered."
    )


def test_it_fits():
    assert len(balloon_body()) <= BALLOON_LIMIT


def test_the_version_always_survives():
    """The one thing About is opened for."""
    first = next(ln for ln in about_lines() if ln.strip())
    assert balloon_body().splitlines()[0] == first


def test_it_drops_whole_lines_rather_than_cutting_one():
    """A half-printed URL looks clickable and is not."""
    body = balloon_body()
    kept = set(body.splitlines())
    originals = {ln for ln in about_lines() if ln.strip()}
    assert kept <= originals, f"a line was cut mid-way: {kept - originals}"


def test_a_generous_limit_keeps_everything():
    body = balloon_body(limit=10_000)
    assert body.splitlines() == [ln for ln in about_lines() if ln.strip()]


def test_an_absurd_limit_still_returns_something_bounded():
    body = balloon_body(limit=12)
    assert 0 < len(body) <= 12
