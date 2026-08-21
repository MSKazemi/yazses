"""The settings window's help text — pure, so it runs without PySide6.

The window is skipped everywhere PySide6 is absent (CI included), so the wording
users read has to be testable on its own. This file owns that: what a row says,
that it says it in escaped rich text, and that the plain-text form a screen
reader announces carries the same content with no markup in it.
"""

from yazses.config import Config
from yazses.settingsui.help import (
    H_CHANGES,
    H_DEFAULT,
    H_EXAMPLE,
    H_NEEDS,
    H_WHAT,
    H_WHEN,
    SUMMARY_MAX,
    accessible_description,
    help_html,
    help_sections,
    help_text,
    reset_message,
    summary_line,
)
from yazses.settingsui.model import SettingRow, build_settings_model


def _row(**kw) -> SettingRow:
    base = dict(
        slug="demo",
        label="Demo capability",
        tier_label="optional",
        enabled=False,
        toggleable=True,
        experimental=False,
        why="Does a thing. Then it does another thing.",
    )
    base.update(kw)
    return SettingRow(**base)  # type: ignore[arg-type]


def _headings(row) -> list[str]:
    return [head for head, _body in help_sections(row)]


def test_summary_leads_with_the_tier_then_the_first_sentence():
    assert summary_line(_row()) == "optional — Does a thing."


def test_summary_stays_on_one_line():
    row = _row(why="A " + "very " * 80 + "long sentence with no full stop")
    assert len(summary_line(row)) <= len("optional — ") + SUMMARY_MAX
    assert summary_line(row).endswith("…")


def test_summary_survives_a_capability_with_no_description():
    assert summary_line(_row(why="")) == "optional"


def test_a_decimal_does_not_cut_the_lead_sentence_in_half():
    row = _row(why="Lowers the gate to 0.004 for quiet speech. More detail here.")
    assert summary_line(row) == "optional — Lowers the gate to 0.004 for quiet speech."


def test_help_answers_what_when_how_and_what_it_writes():
    row = _row(
        use_case="When you want live text as you speak.",
        example="hold the key and talk",
        on_writes=(("streaming", "enabled", "true", False),),
    )
    sections = dict(help_sections(row))
    assert sections[H_WHAT].startswith("Does a thing.")
    assert sections[H_WHEN] == "When you want live text as you speak."
    assert sections[H_EXAMPLE] == "hold the key and talk"
    # The concrete answer to "what does ticking this actually change?".
    assert "[streaming] enabled = true" in sections[H_CHANGES]
    assert "restart" in sections[H_CHANGES]


def test_a_multi_key_toggle_names_every_key_it_writes():
    row = _row(on_writes=(
        ("audio", "device_change_notify", "true", False),
        ("audio", "silent_streak_notify", "true", False),
    ))
    changes = dict(help_sections(row))[H_CHANGES]
    assert "[audio] device_change_notify = true" in changes
    assert "[audio] silent_streak_notify = true" in changes


def test_packages_are_named_so_a_tick_is_not_a_surprise_download():
    row = _row(packages=("mediapipe", "opencv-python"))
    needs = dict(help_sections(row))[H_NEEDS]
    assert "mediapipe opencv-python" in needs
    assert "on your machine" in needs


def test_empty_sections_are_dropped_not_left_as_blank_headings():
    heads = _headings(_row())
    assert H_WHEN not in heads
    assert H_EXAMPLE not in heads
    assert H_NEEDS not in heads
    assert H_WHAT in heads


def test_default_state_is_stated_plainly():
    assert "On by default." in dict(help_sections(_row(default_enabled=True)))[H_DEFAULT]
    assert "Off by default." in dict(help_sections(_row(default_enabled=False)))[H_DEFAULT]


def test_a_core_row_explains_that_it_is_not_a_switch():
    row = _row(toggleable=False, default_enabled=None)
    assert "not a switch" in dict(help_sections(row))[H_DEFAULT]


def test_an_unwired_row_explains_why_it_cannot_be_enabled():
    row = _row(toggleable=False, wired=False)
    body = dict(help_sections(row))[H_DEFAULT]
    assert "not wired into this build" in body
    assert "nothing reads" in body


def test_a_non_toggleable_row_never_claims_to_write_config():
    assert H_CHANGES not in _headings(_row(
        toggleable=False, on_writes=(("x", "y", "true", False),)
    ))


def test_help_html_escapes_the_markup_capability_text_is_full_of():
    row = _row(why="Run `yazses transcribe <file>` for A & B.", label="A <b>bold</b> name")
    rendered = help_html(row)
    assert "&lt;file&gt;" in rendered
    assert "A &amp; B" in rendered
    assert "<b>bold</b>" not in rendered, "a feature name must not inject markup"
    # ...while the structural markup this module adds is still real.
    assert rendered.startswith("<p><b>")


def test_plain_text_help_carries_the_same_content_without_markup():
    row = _row(use_case="When you need it.", example="say 'go'")
    text = help_text(row)
    assert "<" not in text and ">" not in text
    assert "Demo capability" in text
    assert "Use when: When you need it." in text
    assert "Example: say 'go'" in text


def test_the_accessible_description_is_one_speakable_line():
    spoken = accessible_description(_row(use_case="When you need it."))
    assert "\n" not in spoken
    assert "<" not in spoken
    assert "Demo capability" in spoken


def test_reset_message_names_every_row_it_would_touch():
    labels = {"a": "Alpha", "b": "Bravo", "c": "Charlie"}
    body = reset_message([("a", True), ("b", False), ("c", False)], labels)
    assert "Turn ON (1):  Alpha" in body
    assert "Turn OFF (2):  Bravo, Charlie" in body
    # It must also say what it will NOT touch — that is the reassurance that
    # makes a "restore defaults" button safe to press.
    assert "hotkey, microphone" in body
    assert "Apply" in body


def test_reset_message_with_nothing_to_do_says_so():
    assert "already at its default" in reset_message([], {})


def test_reset_message_falls_back_to_the_slug_for_an_unknown_label():
    assert "mystery" in reset_message([("mystery", True)], {})


def test_every_real_capability_produces_help_a_person_can_read():
    """No row in the shipped registry may render an empty or markup-broken card."""
    for row in build_settings_model(Config()).rows():
        rendered = help_html(row)
        assert rendered.startswith("<p><b>"), row.slug
        assert help_sections(row), f"{row.slug} has nothing to say"
        assert summary_line(row).strip(), row.slug
        # Every toggleable row must answer "what does this change?".
        if row.toggleable:
            assert H_CHANGES in _headings(row), row.slug


def test_an_abbreviation_does_not_end_the_lead_sentence():
    """"(e.g." as a summary reads as a bug, not as a description."""
    row = _row(why="Auto-heals when the mic switches (e.g. a monitor steals it). More.")
    assert summary_line(row) == (
        "optional — Auto-heals when the mic switches (e.g. a monitor steals it)."
    )


def test_a_description_that_is_one_sentence_with_no_full_stop_is_kept_whole():
    assert summary_line(_row(why="Does one thing")) == "optional — Does one thing"


def test_no_shipped_capability_summarises_to_a_dangling_abbreviation():
    for row in build_settings_model(Config()).rows():
        summary = summary_line(row)
        assert not summary.rstrip("…").endswith(("(e.g.", "e.g.", "i.e.")), row.slug
