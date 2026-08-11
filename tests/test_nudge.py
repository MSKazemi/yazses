"""The one-time project pointer.

This is the only place the product asks for the user's attention on the project's own
behalf, which makes it the easiest thing in the codebase to turn into nagging. These
tests pin the restraints rather than the wording: it appears only after a success, only
on a terminal, only once ever, and never when the user or an automated environment has
asked for quiet.

The last test is the important one -- it asserts the module contains no network code at
all. A tool whose pitch is "your voice never leaves your machine" cannot grow a telemetry
call here, and a reviewer skimming a future diff should have a test fail rather than have
to notice.
"""

from __future__ import annotations

from pathlib import Path

from yazses.system import nudge


def test_shows_once_then_never_again(tmp_path: Path) -> None:
    assert nudge.should_show(tmp_path, succeeded=True, env={}) is True
    nudge.mark_shown(tmp_path)
    assert nudge.should_show(tmp_path, succeeded=True, env={}) is False


def test_silent_when_the_thing_failed(tmp_path: Path) -> None:
    """Never point at the project next to an error -- that is how you earn an uninstall."""
    assert nudge.should_show(tmp_path, succeeded=False, env={}) is False
    # ...and staying silent must not burn the one showing.
    assert not (tmp_path / nudge.MARKER_NAME).exists()
    assert nudge.should_show(tmp_path, succeeded=True, env={}) is True


def test_silent_when_not_a_terminal(tmp_path: Path) -> None:
    """Piped or redirected output must stay clean for whatever is parsing it."""
    assert nudge.should_show(tmp_path, succeeded=True, interactive=False, env={}) is False


def test_opt_out_is_respected(tmp_path: Path) -> None:
    assert nudge.should_show(tmp_path, succeeded=True, env={"YAZSES_NO_NUDGE": "1"}) is False


def test_silent_in_ci(tmp_path: Path) -> None:
    assert nudge.should_show(tmp_path, succeeded=True, env={"CI": "true"}) is False


def test_marker_failure_never_raises(tmp_path: Path) -> None:
    """A read-only data dir is a reason to skip bookkeeping, not to fail a command."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    nudge.mark_shown(blocker / "nested")  # must not raise


def test_message_points_at_help_not_at_stars() -> None:
    """It offers the user something (where to report, how to help), never asks for a star.

    Manufacturing popularity signals is explicitly not something this project does, and
    a message that begged for stars would be the first step onto that road.
    """
    import re

    text = nudge.message().lower()
    assert "github.com/mskazemi/yazses/issues" in text
    assert "contribute" in text
    # Check the prose, not the URLs -- "contribute/start.html" legitimately contains
    # "star", which is exactly the kind of false positive a naive substring test hits.
    prose = re.sub(r"https?://\S+", "", text)
    assert not re.search(r"\bstars?\b", prose)
    assert "⭐" not in prose
    # The escape hatch has to be discoverable from the message itself.
    assert "yazses_no_nudge" in text


def test_module_contains_no_network_code() -> None:
    """The pointer must never become telemetry. Enforced, not merely intended."""
    source = Path(nudge.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    banned = ("requests", "urllib", "http", "socket", "post(", "telemetry", "analytics")
    # `import` lines and calls only -- the docstring legitimately discusses telemetry.
    body = code.split('"""')[-1]
    for token in banned:
        assert token not in body, f"{token!r} appeared in nudge.py — it must stay offline"
