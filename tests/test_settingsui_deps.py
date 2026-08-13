"""Settings window dependency install — the decisions, without Qt (#135).

The window used to write `enabled = true` and stop, which for the 15 rows that
need an extra produced a config the daemon could not honour. All of the
decisions moved into `settingsui/deps.py` precisely so the failure matrix could
be exercised with no display, no network, and no minutes-long pip run.
"""

from __future__ import annotations

import pytest

from yazses.settingsui.deps import (
    InstallOutcome,
    InstallPlan,
    describe_failure,
    describe_skipped,
    describe_summary,
    plan_installs,
    run_installs,
    total_packages,
)

MISSING = {
    "gaze": ("mediapipe", "opencv-python"),
    "cocktail": ("speechbrain",),
}


# ---- planning --------------------------------------------------------------


def test_plan_covers_every_slug_with_missing_packages():
    plans = plan_installs(MISSING, auto_install=True)
    assert [p.slug for p in plans] == ["cocktail", "gaze"]        # sorted
    assert plans[1].packages == ("mediapipe", "opencv-python")


def test_plan_is_deterministic():
    """A run should be diffable; nothing may depend on dict ordering."""
    assert plan_installs(MISSING, auto_install=True) == plan_installs(
        dict(reversed(list(MISSING.items()))), auto_install=True
    )


def test_opting_out_plans_nothing():
    """The window's equivalent of the CLI's --no-install."""
    assert plan_installs(MISSING, auto_install=False) == []


def test_slug_with_no_missing_packages_is_not_planned():
    assert plan_installs({"undo": ()}, auto_install=True) == []


def test_nothing_missing_plans_nothing():
    assert plan_installs({}, auto_install=True) == []


def test_total_packages_counts_across_plans():
    assert total_packages(plan_installs(MISSING, auto_install=True)) == 3


# ---- running ---------------------------------------------------------------


def test_successful_run_reports_every_slug_ok():
    calls = []
    summary = run_installs(
        plan_installs(MISSING, auto_install=True),
        install=lambda pkgs: calls.append(tuple(pkgs)) or True,
    )
    assert summary.ok and not summary.failed
    assert calls == [("speechbrain",), ("mediapipe", "opencv-python")]


def test_installer_returning_false_is_a_failure_not_a_crash():
    summary = run_installs(
        plan_installs({"gaze": ("mediapipe",)}, auto_install=True),
        install=lambda pkgs: False,
    )
    assert not summary.ok
    assert summary.failed[0].slug == "gaze"
    assert summary.failed[0].error


def test_installer_raising_is_recorded_and_does_not_abort_the_rest():
    """One capability failing must not abandon the ones after it."""
    def flaky(pkgs):
        if "speechbrain" in pkgs:
            raise RuntimeError("network unreachable")
        return True

    summary = run_installs(plan_installs(MISSING, auto_install=True), install=flaky)
    assert [o.slug for o in summary.outcomes] == ["cocktail", "gaze"]
    assert [o.ok for o in summary.outcomes] == [False, True]
    assert "network unreachable" in summary.failed[0].error


def test_progress_is_reported_before_each_install_starts():
    seen = []
    run_installs(
        plan_installs(MISSING, auto_install=True),
        install=lambda pkgs: True,
        on_start=lambda plan: seen.append(plan.slug),
    )
    assert seen == ["cocktail", "gaze"]


def test_an_empty_plan_runs_nothing():
    summary = run_installs([], install=lambda pkgs: pytest.fail("must not install"))
    assert summary.ok and summary.outcomes == []


# ---- what the user is told -------------------------------------------------
#
# The chosen rule: on a failed install the config key STANDS and the message
# says so. Rolling back would silently undo a switch the user just moved, and a
# transient network failure would look like a broken window.


def test_failure_message_says_the_feature_is_on_but_dormant():
    message = describe_failure(
        InstallOutcome("gaze", ("mediapipe",), ok=False, error="exit 1")
    )
    assert "switched on" in message
    assert "dormant" in message
    assert "mediapipe" in message, "must name the packages that failed"
    assert "exit 1" in message, "must carry the real error, not just 'failed'"
    assert "yazses features enable gaze" in message, "must give the retry"


def test_summary_names_what_succeeded_and_what_did_not():
    summary = run_installs(
        plan_installs(MISSING, auto_install=True),
        install=lambda pkgs: "speechbrain" not in pkgs,
    )
    message = describe_summary(summary)
    assert "gaze" in message and "cocktail" in message
    assert "dormant" in message


def test_summary_of_nothing_is_empty_not_noise():
    assert describe_summary(run_installs([], install=lambda p: True)) == ""


def test_skipped_message_lists_what_stays_dormant():
    message = describe_skipped(MISSING)
    assert "gaze" in message and "mediapipe" in message
    assert "dormant" in message


def test_skipped_message_is_empty_when_nothing_was_missing():
    assert describe_skipped({}) == ""
    assert describe_skipped({"undo": ()}) == ""


# ---- the worker's own logic, still without Qt ------------------------------


def test_worker_runs_the_plan_through_an_injected_installer():
    """The worker imports cleanly and works with no PySide6 present."""
    from yazses.settingsui.worker import InstallWorker

    calls = []
    worker = InstallWorker(
        plan_installs({"gaze": ("mediapipe",)}, auto_install=True),
        installer=lambda pkgs: calls.append(tuple(pkgs)) or True,
    )
    worker.run()
    assert calls == [("mediapipe",)]


def test_worker_emits_nothing_dangerous_without_qt():
    """Signal emission must degrade to a no-op, never an AttributeError."""
    from yazses.settingsui.worker import InstallWorker

    worker = InstallWorker([InstallPlan("gaze", ("mediapipe",))], installer=lambda p: False)
    worker.run()   # must not raise
