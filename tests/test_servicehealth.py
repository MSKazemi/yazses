"""The launch-layer diagnoser: unit state + journal text -> cause, commands, packages."""

import subprocess

import pytest

from yazses.system import servicehealth as sh
from yazses.system.servicehealth import ServiceState, classify_log, classify_service


@pytest.mark.parametrize(
    ("os_release", "family"),
    [
        ('ID=ubuntu\nID_LIKE=debian', "debian"),
        ('ID=fedora', "fedora"),
        ('ID=endeavouros\nID_LIKE=arch', "arch"),
        ('ID="opensuse-tumbleweed"\nID_LIKE="suse opensuse"', "suse"),
        ('ID=nixos', "unknown"),
    ],
)
def test_distro_family(os_release, family):
    assert sh.distro_family(os_release) == family


def test_install_command_is_distro_correct():
    assert sh.install_command("xcb-cursor", "debian") == "sudo apt install libxcb-cursor0"
    assert sh.install_command("xcb-cursor", "fedora") == "sudo dnf install xcb-util-cursor"
    assert sh.install_command("portaudio", "arch") == "sudo pacman -S portaudio"
    hint = sh.install_command("portaudio", "unknown")
    assert "libportaudio2" in hint and "package manager" in hint


def test_missing_exec_is_named_with_the_repair():
    state = ServiceState(load_state="loaded", active_state="failed", result="exit-code",
                         exec_status=203, exec_path="/usr/bin/yazses-daemon", exec_exists=False)
    [finding] = classify_service(state)
    assert finding.slug == "exec-missing"
    assert "yazses autostart enable" in finding.commands
    assert "/usr/bin/yazses-daemon" in finding.cause


def test_start_limit_hit_says_why_and_how_to_reset():
    state = ServiceState(load_state="loaded", active_state="failed", result="start-limit-hit")
    [finding] = classify_service(state)
    assert finding.slug == "start-limit"
    assert "systemctl --user reset-failed yazses.service" in finding.commands


def test_root_cause_from_the_journal_comes_first():
    state = ServiceState(
        load_state="loaded", active_state="failed", result="start-limit-hit",
        journal=("OSError: PermissionError: [Errno 13] Permission denied: '/dev/input/event3'",),
    )
    slugs = [f.slug for f in classify_service(state)]
    assert slugs == ["input-permission", "start-limit"]


def test_crash_loop_reports_the_restart_count():
    state = ServiceState(load_state="loaded", active_state="activating", sub_state="auto-restart", n_restarts=3)
    [finding] = classify_service(state)
    assert finding.slug == "crash-loop" and "#3" in finding.problem


def test_healthy_service_yields_nothing():
    assert classify_service(ServiceState(load_state="loaded", active_state="active", sub_state="running")) == []


@pytest.mark.parametrize(
    ("text", "slug", "fragment"),
    [
        ("Permission denied: '/dev/input/event14'", "input-permission", "usermod -aG input"),
        ("qt.qpa.plugin: Could not load the Qt platform plugin xcb ... libxcb-cursor.so.0", "qt-xcb-missing", "libxcb-cursor0"),
        ("OSError: PortAudio library not found", "portaudio-missing", "libportaudio2"),
        ("ydotool: failed to connect socket /tmp/.ydotool_socket: No such file", "ydotoold-down", "ydotoold"),
        ("ModuleNotFoundError: No module named 'faster_whisper'", "module-missing", "pipx reinstall yazses"),
        ("OSError: [Errno 98] Address already in use", "already-running", "yazses stop"),
    ],
)
def test_log_signatures(text, slug, fragment):
    finding = classify_log(text, "debian")
    assert finding is not None and finding.slug == slug
    assert fragment in " ".join(finding.commands)


def test_unknown_log_is_none_not_a_guess():
    assert classify_log("everything is fine, just a normal line") is None


def test_known_runtime_rule_is_reused():
    finding = classify_log("MemoryError")
    assert finding is not None and finding.slug == "out-of-memory"


def test_render_lists_commands_to_copy():
    text = sh.render(classify_service(ServiceState(load_state="loaded", active_state="failed", result="start-limit-hit")))
    assert "why:" in text and "fix:" in text and "reset-failed" in text


def _fake_run(show: str, journal: str = "", code: int = 0):
    def run(argv, **_kw):
        out = show if argv[0] == "systemctl" else journal
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")
    return run


def test_collect_parses_systemctl_show(tmp_path):
    real = tmp_path / "yazses-daemon"
    real.write_text("", encoding="utf-8")
    show = (
        "LoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\n"
        f"ExecMainStatus=203\nNRestarts=4\nExecStart={{ path={real} ; argv[]={real} ; }}\n"
    )
    state = sh.collect_service_state(_fake_run(show, "line one\nline two"))
    assert state is not None
    assert (state.active_state, state.exec_status, state.n_restarts) == ("failed", 203, 4)
    assert state.exec_path == str(real) and state.exec_exists is True
    assert state.journal == ("line one", "line two")


def test_collect_returns_none_without_a_unit():
    assert sh.collect_service_state(_fake_run("LoadState=not-found\n")) is None
    assert sh.collect_service_state(_fake_run("", code=1)) is None


def test_collect_survives_missing_systemctl():
    def boom(*_a, **_k):
        raise FileNotFoundError("systemctl")
    assert sh.collect_service_state(boom) is None
    assert sh.explain_service_failure(boom) == ""
