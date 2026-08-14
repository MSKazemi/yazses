"""The banner: the logo mark on a TTY, plain text otherwise.

Locks the whole degradation ladder — truecolor -> 256 -> mono, Unicode blocks ->
ASCII, animated -> static -> absent — because the failure mode of terminal art
is not an exception, it is mojibake in somebody's transcript.
"""
from __future__ import annotations

from typer.testing import CliRunner

from yazses import branding
from yazses.cli import app

runner = CliRunner()


def test_banner_shows_name_version_and_tagline() -> None:
    out = branding.banner(force=True, depth="mono", unicode_ok=True)
    assert branding.APP_NAME in out
    assert branding.version() in out
    # The tagline is split across two rows at its em dash; both halves survive.
    for part in branding._tagline_lines():
        assert part in out


def test_banner_draws_the_mark() -> None:
    out = branding.banner(force=True, depth="mono", unicode_ok=True)
    for line in branding.MARK_ART:
        assert line.strip() and line.strip() in out


def test_banner_plain_fallback_is_a_single_line() -> None:
    out = branding.banner(force=False)
    assert branding.APP_NAME in out
    assert branding.version() in out
    assert branding.BANNER_ART not in out
    assert out.count("\n") == 0


def test_no_color_env_disables_art(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert branding._supports_banner() is False
    assert branding.color_depth() == "mono"


def test_ascii_fallback_when_terminal_cannot_encode_blocks() -> None:
    out = branding.banner(force=True, depth="mono", unicode_ok=False)
    assert "▁" not in out
    assert out.isascii()
    for line in branding.MARK_ART_ASCII:
        assert line.strip() in out


def test_plain_fallback_goes_ascii_when_the_stream_cannot_encode() -> None:
    """ASCII art is not enough on its own — our own tagline carries an em dash,
    so the *text* has to degrade too or a cp437 console still breaks."""
    out = branding.banner(force=False, unicode_ok=False)
    assert out.isascii()
    assert branding.APP_NAME in out
    assert "—" not in out


def test_ascii_safe_preserves_meaning() -> None:
    assert branding.ascii_safe("a — b · c") == "a - b * c"
    assert branding.ascii_safe("plain").isascii()


def test_can_encode_rejects_blocks_on_a_legacy_codepage() -> None:
    class _Cp437:
        encoding = "cp437"

    assert branding._can_encode("".join(branding.MARK_ART), _Cp437()) is False
    assert branding._can_encode("".join(branding.MARK_ART_ASCII), _Cp437()) is True


def test_mark_lines_pick_the_form_the_stream_can_encode() -> None:
    class _Cp437:
        encoding = "cp437"

    class _Utf8:
        encoding = "utf-8"

    assert branding.mark_lines(stream=_Cp437()) == branding.MARK_ART_ASCII
    assert branding.mark_lines(stream=_Utf8()) == branding.MARK_ART


def test_mono_leaves_the_art_untouched() -> None:
    assert branding.colorize_mark(branding.MARK_ART, "mono") == list(branding.MARK_ART)


def test_truecolor_and_256_emit_their_own_escapes() -> None:
    true_rows = branding.colorize_mark(branding.MARK_ART, "truecolor")
    ansi_rows = branding.colorize_mark(branding.MARK_ART, "256")
    assert any("\033[38;2;" in row for row in true_rows)
    assert any("\033[38;5;" in row for row in ansi_rows)
    # Colour never changes what is actually drawn, only how it is painted.
    for rows in (true_rows, ansi_rows):
        stripped = [_strip_ansi(row) for row in rows]
        assert stripped == list(branding.MARK_ART)


def test_gradient_runs_diagonally_from_brand_top_to_brand_bottom() -> None:
    rows = branding.colorize_mark(branding.MARK_ART, "truecolor")
    first = rows[0][rows[0].index("\033"):][:24]
    last = rows[-1][rows[-1].index("\033"):][:24]
    assert first != last, "a diagonal sweep must not paint every row the same colour"


def test_text_beside_the_mark_is_never_coloured() -> None:
    """Per-character ANSI in the wordmark would break every `"YazSes" in out`
    assertion downstream — and read badly on a light theme."""
    out = branding.banner(force=True, depth="truecolor", unicode_ok=True)
    assert f"{branding.APP_NAME} {branding.version()}" in out


def test_compose_lays_text_beside_art_without_counting_escapes() -> None:
    art = ["ab", "cd"]
    rows = branding.compose_banner(art, ["", "X"], gutter=2, art_width=2)
    assert rows == ["ab", "cd  X"]


def test_visible_width_ignores_colour_escapes() -> None:
    colored = branding.colorize_mark(["ab"], "truecolor")[0]
    assert len(colored) > 2, "the escapes really are in the string"
    assert branding.visible_width(colored) == 2


def test_text_column_is_flush_across_rows_of_unequal_art_width() -> None:
    """The regression that shipped ragged output: padding coloured art with
    ljust counts escape bytes as columns, so the pad collapses and every row
    starts its text somewhere different. Art rows of DIFFERING widths are the
    only case that catches it — equal-width rows pass either way."""
    colored = branding.colorize_mark(["ab", "c", "defg"], "truecolor")
    rows = branding.compose_banner(colored, ["X", "Y", "Z"], gutter=2)
    columns = {_strip_ansi(row).index(letter) for row, letter in zip(rows, "XYZ")}
    assert len(columns) == 1, f"text must start in one column, got {columns}"


def test_real_banner_text_is_flush() -> None:
    """The end-to-end version: the shipped banner, in colour, must line its name
    and both tagline rows up in one column."""
    rows = [_strip_ansi(r) for r in branding.banner_lines(depth="truecolor", unicode_ok=True)]
    expected = [f"{branding.APP_NAME} {branding.version()}", *branding._tagline_lines()]
    columns = set()
    for text in expected:
        row = next(r for r in rows if text in r)
        columns.add(row.index(text))
    assert len(columns) == 1, f"ragged banner, text starts at columns {columns}:\n" + "\n".join(rows)


def test_ripple_settles_exactly_onto_the_resting_wave() -> None:
    frames = branding.ripple_frames(6)
    assert len(frames) == 6
    resting = "".join(branding._WAVE_RAMP[level] for level in branding._WAVE_REST)
    assert frames[-1] == resting, "the animation must land on the logo, not snap to it"
    assert frames[0] != resting, "and it must actually move before it lands"
    assert all(len(f) == len(resting) for f in frames), "a frame must not change width"


def test_ripple_collapses_to_one_resting_frame_without_unicode() -> None:
    assert len(branding.ripple_frames(6, unicode_ok=False)) == 1


def test_ripple_is_deterministic() -> None:
    assert branding.ripple_frames(6) == branding.ripple_frames(6)


def test_should_not_animate_in_ci_or_without_a_tty(monkeypatch) -> None:
    monkeypatch.setenv("CI", "1")
    assert branding.should_animate() is False
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert branding.should_animate() is False


def test_play_ripple_redraws_in_place_and_clears() -> None:
    written: list[str] = []
    slept: list[float] = []
    branding.play_ripple(
        write=written.append,
        sleep=slept.append,
        frames=["aaa", "bbb", "ccc"],
        depth="mono",
    )
    # One write per frame plus the final clear; every frame rewinds the line so
    # the animation occupies exactly one row.
    assert len(written) == 4
    assert all(chunk.startswith("\r") for chunk in written)
    assert len(slept) == 2, "no sleep after the last frame"
    assert "aaa" in written[0] and "ccc" in written[2]


def test_play_ripple_never_sleeps_on_a_single_frame() -> None:
    slept: list[float] = []
    branding.play_ripple(write=lambda _s: None, sleep=slept.append, frames=["x"], depth="mono")
    assert slept == []


def test_about_command_shows_branding_and_contact() -> None:
    result = runner.invoke(app, ["about"])
    assert result.exit_code == 0
    assert branding.APP_NAME in result.stdout
    assert branding.AUTHOR in result.stdout
    assert branding.ISSUES in result.stdout


def test_quickstart_shows_the_banner() -> None:
    result = runner.invoke(app, ["quickstart"], env={"COLUMNS": "220"})
    assert result.exit_code == 0
    assert branding.APP_NAME in result.stdout


def _strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)
