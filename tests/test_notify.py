"""Desktop-notification helper: argv assembly, action parsing, graceful degradation."""
from yazses.system import notify as N
from yazses.system.notify import NotifyAction, build_notify_argv, parse_action_result


def test_build_argv_plain():
    argv = build_notify_argv("Title", "Body", urgency="critical", icon="mic")
    assert argv[0] == "notify-send"
    assert "--urgency" in argv and "critical" in argv
    assert "--icon" in argv and "mic" in argv
    assert argv[-2:] == ["Title", "Body"]
    assert "--wait" not in argv


def test_build_argv_with_actions_and_wait():
    actions = [NotifyAction("recalibrate", "Re-calibrate"), NotifyAction("ignore", "Ignore")]
    argv = build_notify_argv("T", "B", actions=actions, wait=True)
    assert "--wait" in argv
    assert "--action=recalibrate=Re-calibrate" in argv
    assert "--action=ignore=Ignore" in argv


def test_parse_action_result():
    actions = [NotifyAction("pin", "Pin"), NotifyAction("ignore", "Ignore")]
    assert parse_action_result("pin\n", actions) == "pin"
    assert parse_action_result("", actions) is None  # dismissed / expired
    assert parse_action_result("bogus", actions) is None
    assert parse_action_result(None, actions) is None


def test_notifier_available_uses_which():
    assert N.notifier_available(which=lambda _: "/usr/bin/notify-send") is True
    assert N.notifier_available(which=lambda _: None) is False


def test_notify_logs_only_when_unavailable(mocker):
    runner = mocker.MagicMock()
    N.notify("T", "B", available=False, runner=runner)
    runner.assert_not_called()  # no notify-send → nothing spawned, no raise


def test_notify_plain_toast_calls_runner(mocker):
    runner = mocker.MagicMock()
    N.notify("T", "B", available=True, actions_supported=False, runner=runner)
    runner.assert_called_once()
    argv = runner.call_args.args[0]
    assert argv[0] == "notify-send" and "--wait" not in argv


def test_notify_actionable_dispatches_clicked_key(mocker):
    proc = mocker.MagicMock()
    proc.stdout = "pin\n"
    runner = mocker.MagicMock(return_value=proc)
    got = []
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("pin", "Pin this mic")],
        on_action=got.append,
        available=True,
        actions_supported=True,
        runner=runner,
        spawn=False,  # run inline so the assertion is deterministic
    )
    argv = runner.call_args.args[0]
    assert "--wait" in argv and "--action=pin=Pin this mic" in argv
    assert got == ["pin"]


def test_notify_actionable_no_action_on_dismiss(mocker):
    proc = mocker.MagicMock()
    proc.stdout = ""  # user dismissed without clicking
    runner = mocker.MagicMock(return_value=proc)
    got = []
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("pin", "Pin")],
        on_action=got.append,
        available=True,
        actions_supported=True,
        runner=runner,
        spawn=False,
    )
    assert got == []


def test_notify_never_raises_on_runner_error(mocker):
    runner = mocker.MagicMock(side_effect=OSError("boom"))
    # Must not propagate — a broken notifier can't take down the daemon.
    N.notify("T", "B", available=True, actions_supported=False, runner=runner)
