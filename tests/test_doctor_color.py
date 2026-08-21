"""Doctor output colourisation — the actionable command must stand out."""
import sys

from yazses.system import doctor


def test_format_check_plain_when_color_disabled(monkeypatch):
    monkeypatch.setattr(doctor, "_color_enabled", lambda: False)
    line = doctor._format_check("Keyboard capture", "FAIL",
                                "denied\n    sudo usermod -aG input $USER")
    assert "\033[" not in line  # no ANSI when piped/redirected
    assert "[FAIL]" in line and "sudo usermod -aG input $USER" in line


def test_format_check_highlights_sudo_command_when_color_enabled(monkeypatch):
    monkeypatch.setattr(doctor, "_color_enabled", lambda: True)
    line = doctor._format_check("Keyboard capture", "FAIL",
                                "denied\n    sudo usermod -aG input $USER")
    assert "\033[" in line                      # ANSI present
    # the FAIL tag and the command line each carry styling
    assert "\033[1;97;41m[FAIL]\033[0m" in line
    cmd_line = [ln for ln in line.split("\n") if "usermod" in ln][0]
    assert cmd_line.startswith("\033[")         # command line is styled, not plain


def test_color_disabled_when_stdout_is_none(monkeypatch):
    """A windowed PyInstaller build has no console, so PyInstaller sets
    sys.stdout to None. `sys.stdout.isatty()` then raises AttributeError and
    Windows renders it as a crash dialog — which is how `yazses doctor` died on
    the 2.18.2 installer. No stream means no colour, not an exception.
    """
    monkeypatch.setattr(sys, "stdout", None)
    assert doctor._color_enabled() is False


def test_format_check_survives_a_missing_stdout(monkeypatch):
    """The whole doctor report must still render — _format_check is called for
    every check, so a raise here takes the entire command down."""
    monkeypatch.setattr(sys, "stdout", None)
    line = doctor._format_check("Microphone", "OK", "ok")
    assert "[OK]" in line
    assert "\033[" not in line


def test_ok_status_not_red(monkeypatch):
    monkeypatch.setattr(doctor, "_color_enabled", lambda: True)
    line = doctor._format_check("Microphone", "OK", "ok")
    assert "\033[32m" in line                    # green tag
    assert "\033[31m" not in line                # no red on a healthy line
