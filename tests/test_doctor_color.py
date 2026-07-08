"""Doctor output colourisation — the actionable command must stand out."""
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


def test_ok_status_not_red(monkeypatch):
    monkeypatch.setattr(doctor, "_color_enabled", lambda: True)
    line = doctor._format_check("Microphone", "OK", "ok")
    assert "\033[32m" in line                    # green tag
    assert "\033[31m" not in line                # no red on a healthy line
