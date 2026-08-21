"""Turn a caught failure into something the user can act on.

`stt/errors.py` did this for exactly one failure — a missing speech model — and the
shape was right: *"failures the user can fix, phrased so they can fix them."* This
generalises it to the rest, because every other error in the daemon ends in a log
line and a `last_error` string that only `yazses status` can read.

**The gap this closes is not detection. It is telling anyone.** Measured on the
current build: a microphone that will not open is caught, logged, and written to
`last_error` — and then the daemon sets its state back to `IDLE`, which the tray
paints **idle blue**. A pipeline error does the same. So the user holds the key,
speaks a whole sentence, nothing is typed, and every surface they can see reports a
healthy daemon. The failure was noticed by the program and by nobody else.

Three rules hold this together:

* **Every failure gets a diagnosis, including the ones not listed here.** An
  unrecognised error falls through to a generic one that still names where it
  happened and still offers the report command. A classifier that returns None for
  the unexpected case would go quiet in exactly the situation the user most needs a
  message.
* **A diagnosis is advice, never a decision.** Nothing here changes what the daemon
  does — a wrong guess costs the user a misleading sentence, not a working feature.
  That is the same rule `looks_like_a_blocked_network` already follows.
* **Say the next command, not the category.** "Microphone unavailable" is a label.
  "Another program is using it — close it, or pick a different mic with `yazses
  audio devices`" is something to do.

Pure and dependency-free: no Qt, no notify-send, no config. The caller decides
whether to show it, which is what makes the rate-limit policy below testable
without a clock.
"""

from __future__ import annotations

from dataclasses import dataclass

# How long the same failure stays quiet after it has been reported once. A mic that
# will not open fails on *every* burst, and a user who holds the key five times in
# frustration must not collect five identical toasts — that trains people to dismiss
# YazSes notifications, which costs more than the missing repeats are worth.
REPEAT_SILENCE_S = 300.0


@dataclass(frozen=True)
class Diagnosis:
    """One failure, phrased for the person in front of the screen."""

    #: Stable identifier. Used to rate-limit repeats and, if the user ever chooses
    #: to file a report, to group them. Never shown.
    slug: str
    #: Notification title. Short enough for a toast on every OS.
    title: str
    #: What happened, in the user's terms — not the exception's.
    what: str
    #: The concrete next step. A command, a setting, or a physical action.
    fix: str
    #: A docs page with more, where one exists.
    doc: str | None = None

    @property
    def body(self) -> str:
        """The toast body: what happened, then what to do about it."""
        return f"{self.what}\n{self.fix}"


#: Where the failure was caught. Kept coarse — this names the *stage*, and a stage
#: is something a user can reason about ("it never heard me" vs "it heard me and
#: nothing appeared"), unlike a module path.
CAPTURE = "capture"
TRANSCRIBE = "transcribe"
INJECT = "inject"
MEETING = "meeting"
STARTUP = "startup"

# The site sets `use_directory_urls: false`, so every page is `<name>.html`
# and NOT `<name>/`. These strings ship inside the binary, where a 404 is
# discovered by the user and by nobody else — `tests/test_diagnosis.py`
# checks each one against a real file in `docs/`.
_DOCS = "https://mskazemi.com/yazses"

# (slug, markers, title, what, fix, doc). Ordered most specific first; the first
# rule whose markers all appear wins. Markers are matched case-insensitively
# against the exception text *and* its class name, because the useful signal is
# sometimes only in one of them (`PortAudioError` carries a numeric message).
_RULES: tuple[tuple[str, tuple[str, ...], str, str, str, str | None], ...] = (
    (
        "mic-busy",
        ("device unavailable",),
        "YazSes could not open your microphone",
        "Another program is using it, or the system took it away.",
        "Close whatever else is recording, then hold the key again. "
        "`yazses audio devices` lists what is available.",
        f"{_DOCS}/troubleshooting.html",
    ),
    (
        "mic-busy",
        ("errno -9985",),  # PortAudio: device unavailable
        "YazSes could not open your microphone",
        "Another program is using it, or the system took it away.",
        "Close whatever else is recording, then hold the key again. "
        "`yazses audio devices` lists what is available.",
        f"{_DOCS}/troubleshooting.html",
    ),
    (
        # Harvested from a real machine's log rather than imagined: this is the *only*
        # warning a nine-hour session produced, five times, and the classifier written
        # the day before fell through to the generic wording for it. PortAudio index
        # -1 is "the default device", so this is the default failing to resolve — which
        # on PipeWire/ALSA happens while the default is being reconfigured (a Bluetooth
        # headset connecting, a monitor waking). `AudioRecorder.start` retries three
        # times, and on this machine it has always recovered.
        "mic-default-unresolved",
        ("error querying device",),
        "YazSes could not reach your default microphone",
        "The system's default input could not be read — usually because it was being "
        "switched at that moment.",
        "It retries, and this normally passes on its own. If it keeps happening, pin "
        "the microphone you want with `yazses audio use <name>` so a change of default "
        "cannot interrupt dictation.",
        f"{_DOCS}/known-good-microphones.html",
    ),
    (
        "mic-missing",
        ("invalid device",),
        "YazSes cannot find the microphone it was told to use",
        "The pinned input device is not on this machine right now — unplugged, "
        "or renamed.",
        "Run `yazses audio use <name>` to pin a different one, or "
        "`yazses audio use \"\"` to follow the system default again.",
        f"{_DOCS}/known-good-microphones.html",
    ),
    (
        "mic-missing",
        ("no default input",),
        "YazSes cannot find a microphone",
        "The system reports no default input device.",
        "Plug one in, or select one in your sound settings, then run "
        "`yazses restart`.",
        f"{_DOCS}/known-good-microphones.html",
    ),
    (
        "mic-permission",
        ("permission",),
        "YazSes is not allowed to use the microphone",
        "The operating system refused access to audio input.",
        "Grant microphone permission to YazSes in your system privacy settings, "
        "then run `yazses restart`. `yazses doctor` shows what is missing.",
        f"{_DOCS}/known-good-microphones.html",
    ),
    (
        "audio-backend-missing",
        ("portaudio",),
        "YazSes cannot reach your sound system",
        "The audio backend PortAudio could not be loaded or found no devices.",
        "On Linux install it with `sudo apt install libportaudio2`, then run "
        "`yazses doctor`.",
        f"{_DOCS}/known-good-microphones.html",
    ),
    (
        "inject-tool-missing",
        ("ydotool",),
        "YazSes transcribed your speech but could not type it",
        "The tool that types text into other windows is missing or not running.",
        "Run `yazses doctor` — it names the exact command to install and start "
        "ydotool. Your words were not lost; the transcript is in the log.",
        f"{_DOCS}/troubleshooting.html",
    ),
    (
        "inject-tool-missing",
        ("xdotool",),
        "YazSes transcribed your speech but could not type it",
        "The tool that types text into other windows is missing.",
        "Install it (`sudo apt install xdotool`) or switch the injection backend "
        "in Settings. `yazses doctor` checks both.",
        f"{_DOCS}/troubleshooting.html",
    ),
    (
        "inject-permission",
        ("uinput",),
        "YazSes is not allowed to type",
        "Typing into other windows needs access to the input device, and it was "
        "refused.",
        "Run `yazses doctor` for the exact permission fix on this machine.",
        f"{_DOCS}/troubleshooting.html",
    ),
    (
        "disk-full",
        ("no space left",),
        "YazSes ran out of disk space",
        "There is no room left to write audio, the transcript or the log.",
        "Free some space. If the learning corpus is large, "
        "`yazses corpus status` shows its size and can trim it.",
        None,
    ),
    (
        "out-of-memory",
        ("out of memory",),
        "YazSes ran out of memory",
        "The model needs more RAM than is free right now.",
        "Close some applications, or choose a smaller model in Settings "
        "(base.en needs far less than the large checkpoints).",
        None,
    ),
    (
        "model-missing",
        ("model",),
        "YazSes could not load the speech model",
        "The transcription model could not be opened.",
        "Run `yazses doctor` — it reports whether the model is present and "
        "downloadable on this machine.",
        f"{_DOCS}/how-to/air-gapped.html",
    ),
)

# The stage-specific fallbacks, for a failure none of the rules recognise. Still
# actionable, because "something went wrong" is the message this module exists to
# replace.
_GENERIC: dict[str, tuple[str, str, str]] = {
    CAPTURE: (
        "YazSes could not record",
        "Something went wrong while opening or reading the microphone.",
        "Run `yazses doctor` to check your audio setup.",
    ),
    TRANSCRIBE: (
        "YazSes could not transcribe that",
        "The speech model failed while decoding what you said.",
        "Try once more. If it keeps happening, `yazses report` collects the "
        "details — it stays on your machine until you send it.",
    ),
    INJECT: (
        "YazSes could not type that",
        "Your speech was transcribed, but the text could not be delivered to the "
        "focused window.",
        "Run `yazses doctor` to check the injection backend.",
    ),
    MEETING: (
        "YazSes could not run the meeting",
        "Meeting recording could not start or finish.",
        "Run `yazses doctor`, then `yazses meeting status` to see what was kept.",
    ),
    STARTUP: (
        "YazSes could not start properly",
        "Something failed while the daemon was starting.",
        "Run `yazses doctor` — it checks each prerequisite in turn.",
    ),
}

_UNKNOWN = (
    "YazSes hit a problem",
    "An unexpected error stopped that from working.",
    "Run `yazses doctor`. If it looks healthy, `yazses report` collects the "
    "details — it stays on your machine until you choose to send it.",
)


def diagnose(error: BaseException | str, *, where: str = "") -> Diagnosis:
    """Explain *error* in terms the user can act on. Never raises, never returns None.

    *where* is one of the stage constants above and only chooses the fallback
    wording — a recognised failure is recognised wherever it is caught, because the
    same missing ydotool produces the same advice on any code path.

    The class name is folded into the matched text because some libraries put every
    useful word there and nothing in the message: `sounddevice.PortAudioError` can
    arrive carrying only an errno.
    """
    text = str(error or "").lower()
    if isinstance(error, BaseException):
        text = f"{type(error).__name__.lower()} {text}"

    for slug, markers, title, what, fix, doc in _RULES:
        if all(marker in text for marker in markers):
            return Diagnosis(slug=slug, title=title, what=what, fix=fix, doc=doc)

    title, what, fix = _GENERIC.get(where, _UNKNOWN)
    # The stage travels in the slug so repeats are rate-limited per stage: a failing
    # microphone and a failing injector are two problems, and silencing the second
    # because the first was just reported would hide it completely.
    return Diagnosis(slug=f"unknown-{where or 'general'}", title=title, what=what, fix=fix)


def should_notify(
    slug: str,
    now: float,
    last_seen: dict[str, float],
    *,
    silence_s: float = REPEAT_SILENCE_S,
) -> bool:
    """Whether this failure is worth a toast right now. Pure; mutates *last_seen*.

    A broken microphone fails on every burst. Five identical toasts in a minute
    teach the user that YazSes notifications are noise, which costs more than the
    suppressed repeats are worth — and the state is still visible in the tray
    tooltip and `yazses status` throughout.

    Keyed by slug rather than by message text, so the same fault reported with a
    different errno each time is still one fault.
    """
    previous = last_seen.get(slug)
    if previous is not None and (now - previous) < silence_s:
        return False
    last_seen[slug] = now
    return True
