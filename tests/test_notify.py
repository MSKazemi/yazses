"""Desktop-notification helper: argv assembly, action parsing, graceful degradation."""
from yazses.system import notify as N
from yazses.system.notify import NotifyAction, build_notify_argv, parse_action_result


# conftest's autouse `_no_test_may_pop_a_toast_on_the_users_desktop` replaces
# `N.notifier_available` for every test, so that no unrelated test can reach the real
# `notify-send`. This file is the one that tests the probe itself, so it needs the real
# function.
#
# It used to capture the module attribute at import time, on the stated assumption that
# imports happen "before the fixture is in effect". That assumption was observed to fail:
# in one full-suite run `test_notifier_available_uses_which` failed with `assert False is
# True`, which is exactly what the conftest stub (`lambda *a, **k: False`) returns when
# handed the injected `which` — so the alias was holding the stub, not the real function.
# It passed alone and passed on the next full run, i.e. it is order-dependent and rare.
#
# The mechanism was not pinned down (nothing reloads the module, and pytest collects
# before it runs), so rather than reason further the assumption is removed: the module is
# executed into a private namespace, untouched by any patch of the installed one and
# independent of when anything is imported. A flaky test in a 5,000-test suite costs more
# than the few milliseconds this takes.
def _load_pristine_notify():
    """`system/notify.py` executed into a throwaway module — never `sys.modules`."""
    import importlib.util
    import sys

    name = "_notify_pristine"
    spec = importlib.util.spec_from_file_location(name, N.__file__)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered during exec and removed after: `@dataclass` resolves its own module
    # through `sys.modules[cls.__module__]`, so executing unregistered raises
    # `AttributeError: 'NoneType' object has no attribute '__dict__'`. Removing it
    # afterwards keeps the real `yazses.system.notify` the only installed copy.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


_real_notifier_available = _load_pristine_notify().notifier_available


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
    assert _real_notifier_available(which=lambda _: "/usr/bin/notify-send") is True
    assert _real_notifier_available(which=lambda _: None) is False


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
    proc.communicate.return_value = ("pin\n", "")
    spawner = mocker.MagicMock(return_value=proc)
    got = []
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("pin", "Pin this mic")],
        on_action=got.append,
        available=True,
        actions_supported=True,
        spawner=spawner,
        spawn=False,  # run inline so the assertion is deterministic
    )
    argv = spawner.call_args.args[0]
    assert "--wait" in argv and "--action=pin=Pin this mic" in argv
    assert got == ["pin"]


def test_notify_actionable_no_action_on_dismiss(mocker):
    proc = mocker.MagicMock()
    proc.communicate.return_value = ("", "")  # user dismissed without clicking
    spawner = mocker.MagicMock(return_value=proc)
    got = []
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("pin", "Pin")],
        on_action=got.append,
        available=True,
        actions_supported=True,
        spawner=spawner,
        spawn=False,
    )
    assert got == []


def test_notify_forgets_a_toast_once_it_closes(mocker):
    """A finished toast must leave `_inflight`, or shutdown kills a reaped pid.

    The set is what `_kill_inflight` speaks for at exit; a toast that is answered and
    never discarded turns every later exit into a kill against a pid the OS may well
    have handed to someone else.
    """
    proc = mocker.MagicMock()
    proc.communicate.return_value = ("pin\n", "")
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("pin", "Pin")],
        available=True,
        actions_supported=True,
        spawner=mocker.MagicMock(return_value=proc),
        spawn=False,
    )
    assert proc not in N._inflight


def test_notify_actionable_never_raises_when_the_spawn_fails(mocker):
    """`notify()` is called from the dictation hot path; a broken spawn is not fatal."""
    N.notify(
        "T",
        "B",
        actions=[NotifyAction("pin", "Pin")],
        available=True,
        actions_supported=True,
        spawner=mocker.MagicMock(side_effect=OSError("boom")),
        spawn=False,
    )
    assert not N._inflight  # a failed spawn must not leave a ghost behind


def test_notify_never_raises_on_runner_error(mocker):
    runner = mocker.MagicMock(side_effect=OSError("boom"))
    # Must not propagate — a broken notifier can't take down the daemon.
    N.notify("T", "B", available=True, actions_supported=False, runner=runner)
