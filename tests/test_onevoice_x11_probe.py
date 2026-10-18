"""OneVoice X11 read-only feasibility tests; no desktop, X11 or xdotool required."""

from __future__ import annotations

import subprocess

import pytest

from yazses.onevoice import x11_probe as p

X11 = {"DISPLAY": ":77", "XDG_SESSION_TYPE": "x11"}


class FakeRunner:
    def __init__(self, *, pids=None, classes=None, bad_cmd=None):
        self.pids = pids or {"41": "1001", "42": "1002"}
        self.classes = classes or {"41": "DemoEditor", "42": "DemoEditor"}
        self.bad_cmd = bad_cmd
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        assert kwargs == {"capture_output": True, "text": True, "timeout": 1.0, "check": False}
        # Any new OS write/focus side effect must break every test immediately.
        assert command[0:2] in (["xdotool", "getwindowpid"],
                                ["xdotool", "getwindowclassname"])
        if self.bad_cmd == command[1]:
            return subprocess.CompletedProcess(command, 1, "", "private text")
        if command[1] == "getwindowpid":
            result = self.pids.get(command[2], "")
        else:
            result = self.classes.get(command[2], "")
        return subprocess.CompletedProcess(command, 0 if result else 1, result, "")


def _probe(window="41", *, runner=None, env=X11):
    return p.probe_window(window, env=env, which=lambda _: "/bin/xdotool",
                          runner=runner or FakeRunner())


@pytest.mark.parametrize(("raw", "parsed"), [
    ("41", 41), ("0041", 41), ("0x29", 41), ("0X29", 41),
    ("4294967295", 0xFFFFFFFF),
    ("", None), ("0", None), ("-1", None), ("+42", None),
    ("0x", None), ("0xG", None), ("xyz", None),
    ("4294967296", None), (" 42 ", None), ("1e5", None),
])
def test_parse_window_ids_strictly(raw, parsed):
    assert p.parse_window_id(raw) == parsed


def test_two_distinct_realistic_windows_can_be_observed_without_reading_contents():
    reader = FakeRunner()
    a = _probe("41", runner=reader)
    b = _probe("42", runner=reader)
    assert a.status is b.status is p.ProbeStatus.OBSERVED
    assert a.identity is not None and b.identity is not None
    assert a.identity.window_id != b.identity.window_id
    assert not a.field_verified and not b.field_verified
    assert len(reader.commands) == 6


@pytest.mark.parametrize("env", [
    {}, {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"},
    {"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"},
])
def test_refuse_non_x11_sessions_without_external_calls(env):
    reader = FakeRunner()
    result = _probe(env=env, runner=reader)
    assert result.status is p.ProbeStatus.UNSUPPORTED_SESSION
    assert reader.commands == []


def test_missing_xdotool_refuses_without_actions():
    reader = FakeRunner()
    result = p.probe_window("41", env=X11, which=lambda _: None, runner=reader)
    assert result.status is p.ProbeStatus.UNAVAILABLE
    assert reader.commands == []


def test_invalid_id_does_not_spawn_process():
    reader = FakeRunner()
    result = _probe("123;rm -rf /", runner=reader)
    assert result.status is p.ProbeStatus.INVALID_WINDOW_ID
    assert reader.commands == []


@pytest.mark.parametrize(("bad", "status"), [
    ("getwindowpid", p.ProbeStatus.UNAVAILABLE),
    ("getwindowclassname", p.ProbeStatus.UNAVAILABLE),
])
def test_missing_metadata_does_not_guess(bad, status):
    assert _probe(runner=FakeRunner(bad_cmd=bad)).status is status


def test_pid_race_fails_closed():
    class Race(FakeRunner):
        def __init__(self):
            super().__init__()
            self.pid_calls = 0

        def __call__(self, command, **kwargs):
            if command[1] == "getwindowpid":
                self.pid_calls += 1
                if self.pid_calls > 1:
                    self.pids[command[2]] = "1003"
            return super().__call__(command, **kwargs)

    assert _probe(runner=Race()).status is p.ProbeStatus.UNAVAILABLE


@pytest.mark.parametrize("bad_pid", ["0", "-2", "ABC"])
def test_invalid_process_identifiers_cannot_pass(bad_pid):
    assert _probe(runner=FakeRunner(pids={"41": bad_pid})).status is p.ProbeStatus.UNAVAILABLE


def test_missing_window_refuses():
    assert _probe("404", runner=FakeRunner()).status is p.ProbeStatus.UNAVAILABLE


def test_subprocess_errors_are_not_exposed():
    def raises(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    result = p.probe_window("41", env=X11, which=lambda _: "xdotool", runner=raises)
    assert result.status is p.ProbeStatus.UNAVAILABLE
    assert result.identity is None


def test_pin_verification_detects_process_replacement():
    initial = _probe(runner=FakeRunner()).identity
    assert initial is not None
    changed = p.revalidate_pin(initial, env=X11, which=lambda _: "xdotool",
                               runner=FakeRunner(pids={"41": "9999"}))
    assert changed.status is p.ProbeStatus.STALE_PIN
    assert changed.identity is None


def test_pin_verification_detects_class_replacement():
    initial = _probe(runner=FakeRunner()).identity
    assert initial is not None
    changed = p.revalidate_pin(initial, env=X11, which=lambda _: "xdotool",
                               runner=FakeRunner(classes={"41": "DifferentApp"}))
    assert changed.status is p.ProbeStatus.STALE_PIN


def test_identical_pin_still_does_not_verify_field():
    initial = _probe(runner=FakeRunner()).identity
    assert initial is not None
    same = p.revalidate_pin(initial, env=X11, which=lambda _: "xdotool",
                            runner=FakeRunner())
    assert same.status is p.ProbeStatus.OBSERVED
    assert same.identity == initial
    assert same.field_verified is False


def test_cli_invalid_or_duplicate_id_abstains(capsys):
    assert p.main(["--window-a", "41", "--window-b", "0x29"]) == 2
    assert capsys.readouterr().out == "selection: invalid_or_duplicate_window_ids\n"


def test_cli_does_not_print_private_pid_or_wm_class(monkeypatch, capsys):
    def stub(wid):
        identity = p.WindowIdentity(int(wid), 9001, "PrivateEditor")
        return p.ProbeResult(p.ProbeStatus.OBSERVED, identity)

    monkeypatch.setattr(p, "probe_window", stub)
    assert p.main(["--window-a", "41", "--window-b", "42"]) == 0
    output = capsys.readouterr().out
    assert "PrivateEditor" not in output and "9001" not in output
    assert "field=unverified" in output or "exact_field=unverified" in output
    assert "routing_and_insertion_not_authorized" in output


def test_cli_failure_status_stays_accurate(monkeypatch, capsys):
    def stub(wid):
        if wid == "42":
            return p.ProbeResult(p.ProbeStatus.UNAVAILABLE)
        return p.ProbeResult(p.ProbeStatus.OBSERVED, p.WindowIdentity(41, 100, "A"))

    monkeypatch.setattr(p, "probe_window", stub)
    assert p.main(["--window-a", "41", "--window-b", "42"]) == 2
    out = capsys.readouterr().out
    assert "window_identity_unavailable" in out
    assert "two_windows_observed" not in out


def test_no_caller_can_mark_x11_window_as_verified_field():
    identity = p.WindowIdentity(41, 9001, "Editor")
    result = p.ProbeResult(p.ProbeStatus.OBSERVED, identity)
    assert result.field_verified is False
    with pytest.raises((AttributeError, TypeError)):
        result.field_verified = True
    with pytest.raises(TypeError):
        p.ProbeResult(p.ProbeStatus.OBSERVED, identity, True)


@pytest.mark.parametrize("status", [p.ProbeStatus.UNAVAILABLE, p.ProbeStatus.STALE_PIN])
def test_refusal_cannot_carry_stale_identity(status):
    with pytest.raises(ValueError):
        p.ProbeResult(status, p.WindowIdentity(41, 9001, "Editor"))


def test_observed_result_requires_actual_window_metadata():
    with pytest.raises(ValueError):
        p.ProbeResult(p.ProbeStatus.OBSERVED)


@pytest.mark.parametrize("window_id,pid,wm_class", [
    (0, 100, "App"), (41, 0, "App"), (41, 10, ""), (41, 10, "  "),
])
def test_invalid_window_identity_cannot_be_constructed(window_id, pid, wm_class):
    with pytest.raises(ValueError):
        p.WindowIdentity(window_id, pid, wm_class)
