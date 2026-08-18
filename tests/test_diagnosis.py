"""Failures are explained to the person, not just to the log.

The gap this closes is not detection — the daemon already catches these. It is that
nothing tells the user. Measured on the build before this landed: a microphone that
will not open is caught, logged, written to `last_error`, and then the state goes
back to `IDLE`, which the tray paints **idle blue**. So you hold the key, speak a
sentence, nothing is typed, and every surface you can see reports a healthy daemon.

Two things are worth guarding separately. The classifier is pure and total — the
interesting cases are the *unrecognised* error and the *repeat*, not the happy match.
And the wiring is what makes it real: a diagnosis nothing calls is a nicely worded
module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.system.diagnosis import (
    CAPTURE,
    INJECT,
    MEETING,
    STARTUP,
    TRANSCRIBE,
    Diagnosis,
    diagnose,
    should_notify,
)

ROOT = Path(__file__).resolve().parent.parent


# ---- the classifier is total ----------------------------------------------


@pytest.mark.parametrize(
    "where", [CAPTURE, TRANSCRIBE, INJECT, MEETING, STARTUP, "", "something-new"]
)
def test_an_unrecognised_error_still_produces_advice(where):
    """The case the module exists for.

    A classifier that returned None for the unexpected error would go silent in
    exactly the situation the user most needs a message — and "unexpected" is the
    normal state of a bug report.
    """
    found = diagnose(RuntimeError("gzzt 0x8004"), where=where)
    assert isinstance(found, Diagnosis)
    assert found.title and found.what and found.fix
    assert found.slug


def test_every_diagnosis_names_something_to_do():
    """A message with no next step is a nicer-sounding dead end.

    Checked by demanding either a command or an imperative — the whole point of the
    module is that "Microphone unavailable" is a label and not advice.
    """
    samples = [
        "device unavailable",
        "Invalid device",
        "no default input device",
        "Permission denied",
        "PortAudioError",
        "ydotool not found",
        "xdotool: command not found",
        "/dev/uinput: Permission denied",
        "No space left on device",
        "CUDA out of memory",
        "model 'base.en' could not be opened",
        "something nobody predicted",
    ]
    for text in samples:
        found = diagnose(text, where=CAPTURE)
        assert "`yazses" in found.fix or re.match(
            r"(Close|Plug|Grant|Install|Free|Run|On Linux)", found.fix
        ), f"{text!r} -> {found.fix!r}"


@pytest.mark.parametrize(
    "text,slug",
    [
        ("Error opening InputStream: Device unavailable", "mic-busy"),
        ("[Errno -9985] Device unavailable", "mic-busy"),
        ("Invalid device index", "mic-missing"),
        ("No default input device available", "mic-missing"),
        ("Permission denied accessing the audio device", "mic-permission"),
        ("ydotoold is not running", "inject-tool-missing"),
        ("xdotool: not found", "inject-tool-missing"),
        ("cannot open /dev/uinput", "inject-permission"),
        ("OSError: [Errno 28] No space left on device", "disk-full"),
        ("RuntimeError: CUDA out of memory", "out-of-memory"),
    ],
)
def test_the_known_failures_are_recognised(text, slug):
    assert diagnose(text, where=CAPTURE).slug == slug


def test_the_class_name_is_matched_too_not_only_the_message():
    """Some libraries put every useful word in the type and nothing in the message.

    `sounddevice.PortAudioError` can arrive carrying only an errno, so matching the
    string alone would fall through to the generic wording for the one audio error
    that is most specifically diagnosable.
    """

    class PortAudioError(Exception):
        pass

    assert diagnose(PortAudioError("-9996"), where=CAPTURE).slug == "audio-backend-missing"


def test_a_recognised_failure_is_recognised_wherever_it_is_caught():
    """`where` picks the fallback wording only.

    The same missing ydotool produces the same advice on any code path, so a rule
    that fired only in the "right" stage would go generic exactly when a caller was
    added somewhere new.
    """
    for where in (CAPTURE, TRANSCRIBE, INJECT, MEETING, STARTUP):
        assert diagnose("ydotool missing", where=where).slug == "inject-tool-missing"


def test_the_generic_slug_carries_the_stage():
    """Otherwise rate-limiting a failing mic would silence a failing injector too.

    Two unrelated faults sharing one slug means the second is never reported.
    """
    assert diagnose("???", where=CAPTURE).slug != diagnose("???", where=INJECT).slug


def test_diagnose_never_raises_on_junk():
    for value in (None, "", 0, object()):
        found = diagnose(value, where=CAPTURE)  # type: ignore[arg-type]
        assert found.title


def test_the_body_says_what_happened_then_what_to_do():
    found = diagnose("device unavailable", where=CAPTURE)
    assert found.body == f"{found.what}\n{found.fix}"


# ---- the links ship inside a binary ---------------------------------------


def test_every_doc_link_points_at_a_page_that_exists():
    """These strings are compiled into the .exe; a 404 is found by the user alone.

    Not hypothetical — the first draft of this module linked three how-to pages that
    have never existed (`no-text-appears`, `microphone-not-detected`,
    `model-download-fails`). This test is why they were caught before the commit.

    Note the site sets `use_directory_urls: false`, so a page is `<name>.html`, never
    `<name>/` — the mistake that once nearly shipped a 404 into a release.
    """
    from yazses.system import diagnosis as mod

    links = {doc for *_rest, doc in mod._RULES if doc}
    assert links, "the guard must not pass by iterating an empty set"
    for link in links:
        assert link.endswith(".html"), f"{link}: the site does not use directory URLs"
        path = link.split("/yazses/", 1)[1].removesuffix(".html") + ".md"
        assert (ROOT / "docs" / path).is_file(), f"{link} -> docs/{path} does not exist"


# ---- the repeat policy -----------------------------------------------------


def test_the_same_failure_is_reported_once_then_held():
    """A broken mic fails on every burst; five identical toasts train dismissal."""
    seen: dict[str, float] = {}
    assert should_notify("mic-busy", 100.0, seen) is True
    assert should_notify("mic-busy", 120.0, seen) is False
    assert should_notify("mic-busy", 200.0, seen) is False


def test_it_speaks_again_once_the_silence_has_elapsed():
    seen: dict[str, float] = {}
    assert should_notify("mic-busy", 100.0, seen) is True
    assert should_notify("mic-busy", 100.0 + 301.0, seen) is True


def test_a_different_failure_is_never_silenced_by_an_earlier_one():
    """The bug this ordering prevents: one fault masking a second, unrelated one."""
    seen: dict[str, float] = {}
    assert should_notify("mic-busy", 100.0, seen) is True
    assert should_notify("inject-tool-missing", 101.0, seen) is True


def test_the_window_is_configurable_so_the_policy_is_testable_without_waiting():
    seen: dict[str, float] = {}
    assert should_notify("x", 0.0, seen, silence_s=10.0) is True
    assert should_notify("x", 5.0, seen, silence_s=10.0) is False
    assert should_notify("x", 11.0, seen, silence_s=10.0) is True


# ---- the wiring: a diagnosis nothing calls is just prose -------------------


def _daemon():
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    return Daemon(config=Config(), platform=get_platform())


def test_the_daemon_reports_a_failure_to_the_user(mocker):
    shown = mocker.patch("yazses.system.notify.notify")
    daemon = _daemon()

    found = daemon._report_failure(OSError("Device unavailable"), CAPTURE)

    assert found is not None and found.slug == "mic-busy"
    shown.assert_called_once()
    title, body = shown.call_args.args
    assert "microphone" in title.lower()
    assert "yazses audio devices" in body


def test_the_daemon_holds_a_repeat_of_the_same_failure(mocker):
    shown = mocker.patch("yazses.system.notify.notify")
    daemon = _daemon()

    assert daemon._report_failure(OSError("Device unavailable"), CAPTURE) is not None
    assert daemon._report_failure(OSError("Device unavailable"), CAPTURE) is None
    assert shown.call_count == 1


def test_reporting_a_failure_never_raises_into_the_failing_path(mocker):
    """It runs from code that is already handling an error, on a background thread.

    An exception here would replace a fixable problem with an unfixable one.
    """
    mocker.patch("yazses.system.notify.notify", side_effect=RuntimeError("no dbus"))
    daemon = _daemon()
    assert daemon._report_failure(OSError("Device unavailable"), CAPTURE) is None


def test_a_failing_microphone_now_tells_the_user(mocker):
    """The end-to-end case, driven through the real hold-to-talk path.

    `_on_hold_start` caught the error, logged it, set `last_error`, and returned the
    state to IDLE — which the tray paints blue. Nothing the user could see said a
    word, which is the whole reason this module exists.
    """
    shown = mocker.patch("yazses.system.notify.notify")
    daemon = _daemon()

    class _DeadRecorder:
        def start(self):
            raise OSError("Error opening InputStream: Device unavailable")

    daemon._recorder = _DeadRecorder()
    daemon._on_hold_start(0)

    assert "Microphone unavailable" in (daemon._state.last_error or "")
    shown.assert_called_once()
    assert "yazses audio devices" in shown.call_args.args[1]


def test_the_tray_is_still_blue_when_that_happens(mocker):
    """Recorded deliberately, because it is the finding that motivated the toast.

    `_on_hold_start` returns the state to IDLE after a capture failure, and
    `icon_spec` colours on state — not on `last_error`. So the badge says "ready"
    while the microphone is unusable. Making the icon red for a per-burst failure
    would leave it red long after the fault cleared, so the notification is the fix
    and this test pins the reason rather than the behaviour.
    """
    from yazses.tray.menu import icon_spec

    mocker.patch("yazses.system.notify.notify")
    daemon = _daemon()

    class _DeadRecorder:
        def start(self):
            raise OSError("Device unavailable")

    daemon._recorder = _DeadRecorder()
    daemon._on_hold_start(0)

    colour, _tooltip = icon_spec({"state": daemon._state.state.value})
    assert colour == "#1a73e8", "if this ever goes red, the toast can be reconsidered"


def test_the_daemon_calls_the_reporter_from_every_stage_it_catches():
    """A stage that catches an error and does not report it is invisible again.

    Read from the source rather than exercised, because two of the three sites need
    a live audio device or a meeting to reach. What is checked is that each `except`
    that sets `last_error` or logs a stage failure is followed by a report — the
    thing that silently regresses when a new failure path is added next to an old one.
    """
    source = (ROOT / "src/yazses/core/daemon.py").read_text(encoding="utf-8")
    for marker in (
        "self._report_failure(exc, CAPTURE)",
        "self._report_failure(exc, INJECT)",
        "self._report_failure(exc, MEETING)",
    ):
        assert marker in source, f"no stage reports via {marker}"


# ---- the report offer (ADR-v2-132 option b: prepare, never send) -----------


def test_the_report_button_appears_only_when_yazses_could_not_identify_the_fault(mocker):
    """ADR-v2-132's third open question, answered from the diagnosis rather than a counter.

    The ADR wondered whether to wait for a *repeated* fault. The better rule falls out
    of the classifier: a recognised failure already carries the command that fixes it,
    and an issue about a missing ydotool helps nobody — least of all the person who now
    has two things to do instead of one.
    """
    shown = mocker.patch("yazses.system.notify.notify")
    daemon = _daemon()

    daemon._report_failure(OSError("ydotool is not installed"), INJECT)
    assert shown.call_args.kwargs["actions"] is None, "a fixable fault needs no issue"

    shown.reset_mock()
    daemon._report_failure(RuntimeError("gzzt 0x8004"), INJECT)
    actions = shown.call_args.kwargs["actions"]
    assert actions and actions[0].label == "Prepare a bug report"


def test_preparing_a_report_opens_a_form_and_sends_nothing(mocker):
    """The whole basis of ADR-v2-132 (b): the browser makes the request, not YazSes.

    That is why this adds no entry to ADR-019's egress inventory — and why
    `tests/test_egress_inventory.py` must keep passing untouched.
    """
    opened = mocker.patch("yazses.system.browser.open_url", return_value=True)
    daemon = _daemon()

    assert daemon._prepare_bug_report(diagnose("gzzt", where=INJECT)) is True

    url = opened.call_args.args[0]
    assert url.startswith("https://github.com/MSKazemi/yazses/issues/new?")
    assert "title=" in url and "body=" in url


def test_preparing_a_report_never_raises_from_a_toast_button(mocker):
    mocker.patch("yazses.system.report.collect", side_effect=OSError("no config dir"))
    daemon = _daemon()
    assert daemon._prepare_bug_report(diagnose("x", where=INJECT)) is False


def test_the_issue_body_carries_the_diagnosis_and_the_environment():
    from yazses.system.report import summarise_for_issue

    body = summarise_for_issue(
        {
            "system": {"yazses": "2.27.0", "platform": "linux", "python": "3.12.0"},
            "daemon": {"state": "idle", "model": "base.en"},
            "log_tail": ["one", "two"],
        },
        diagnosis=diagnose("gzzt", where=INJECT),
    )
    assert "2.27.0" in body and "base.en" in body
    assert "unknown-inject" in body, "the diagnosis id groups duplicate reports"
    assert "What I expected instead" in body, "the user still has to say what broke"


def test_the_issue_body_is_bounded_so_the_url_survives():
    """A URL that exceeds what the browser accepts yields an EMPTY form, not a short one.

    So the failure of an unbounded body is total rather than partial — the user clicks
    the button and lands on a blank issue.
    """
    from yazses.system.report import ISSUE_BODY_LIMIT, summarise_for_issue

    huge = {"system": {}, "daemon": {}, "log_tail": [f"line {i} " + "x" * 200 for i in range(500)]}
    body = summarise_for_issue(huge, log_lines=500)
    assert len(body) <= ISSUE_BODY_LIMIT


def test_trimming_is_stated_rather_than_silent():
    """A body that quietly loses its ending has the user file a report they think is whole."""
    from yazses.system.report import summarise_for_issue

    huge = {"system": {}, "daemon": {}, "log_tail": [f"line {i} " + "x" * 200 for i in range(500)]}
    body = summarise_for_issue(huge, log_lines=500)
    assert "trimmed" in body


def test_trimming_keeps_the_newest_lines_not_the_oldest():
    """The recent lines are the ones that explain the failure."""
    from yazses.system.report import summarise_for_issue

    tail = [f"line-{i} " + "x" * 200 for i in range(200)]
    body = summarise_for_issue(
        {"system": {}, "daemon": {}, "log_tail": tail}, log_lines=200
    )
    assert "line-199" in body
    assert "line-0 " not in body


def test_the_issue_body_adds_no_second_redaction_implementation():
    """Redaction has one implementation, in `collect`. Two would drift.

    Guarded by source, because the failure is an *addition* — someone adding a
    `redact_text` call here to be safe is how the two copies begin.
    """
    from pathlib import Path

    source = Path("src/yazses/system/report.py").read_text(encoding="utf-8")
    body_fn = source.split("def _render_issue_body")[1].split("\ndef ")[0]
    assert "redact_text" not in body_fn
    assert "redact_config" not in body_fn


def test_the_url_encoder_matches_the_stdlib_it_is_not_allowed_to_import():
    """`report.py` hand-rolls percent-encoding; the stdlib still defines correctness.

    ADR-019's egress guard scans `src/yazses/` for network-shaped imports and lists
    `urllib` among them — conservatively, since `urllib.parse` cannot open a socket.
    Registering `report.py` in the egress inventory to satisfy it would be a lie, and
    relaxing the guard would trade a real protection for a convenience in the one
    module whose docstring is "Nothing is ever sent anywhere".

    So the encoder is written by hand *there* and checked against `urllib.parse.quote`
    *here* — this file is outside the scanned tree.
    """
    from urllib.parse import quote

    from yazses.system.report import _percent_encode

    samples = [
        "hello world",
        "a&b=c?d#e",
        "YazSes — could not open your microphone",
        "بسیار خوب",
        "100% sure",
        "```\nlog line\n```",
        "~unreserved-._",
        "",
    ]
    for text in samples:
        assert _percent_encode(text) == quote(text, safe=""), text


def test_the_issue_url_survives_a_body_with_url_metacharacters():
    """A body is Markdown: it is full of `#`, `&` and `?`. Unencoded, the URL breaks."""
    from yazses.system.report import issue_url

    url = issue_url("t?1", "## head\n- a & b\n#anchor")
    assert url.count("?") == 1, "only the query separator may be a literal ?"
    assert url.count("&") == 1, "only the field separator may be a literal &"
    assert "#" not in url, "an unencoded # truncates the URL at the fragment"
