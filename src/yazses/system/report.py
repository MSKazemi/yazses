"""Build a diagnostic bundle locally. Nothing is ever sent anywhere.

When something goes wrong, the useful reply to "it doesn't work" is a file the user can
read, decide about, and attach to an issue themselves — not a background upload. YazSes'
whole reason to exist is that audio and text stay on the machine, so a daemon that phones
home with diagnostics would trade away the one property it is chosen for. The bundle is
therefore user-initiated, written to a path that is printed, and reviewable before it goes
anywhere.

What goes in is decided by the same rule: everything that helps explain a failure, nothing
that reveals what was dictated. The daemon's log is already metadata-only by design (it
records levels, durations and word *counts*, never transcripts), the config is filtered for
anything path- or identity-shaped, the daemon's live status is filtered by the same rules
(it carries the staged buffer, which is dictated text verbatim), and the corpus — which
does hold text and audio — is summarised by size and never opened.

Each of those four is filtered *here*, on the way in, rather than at whichever surface
consumes the bundle. Redacting per-consumer is how the halves drift, and the daemon status
is the proof: it was the one part with no filter at all, and it was the part holding a
transcript.
"""
from __future__ import annotations

import json
import platform as py_platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from yazses.system.logtail import starts_record, tail_records

# Config keys whose values are paths, addresses or identifiers rather than settings. The
# value is replaced, not the key: knowing that a socket is configured is diagnostic, and
# knowing where it points is nobody's business.
_REDACT_KEYS = re.compile(
    r"(path|dir|file|socket|host|address|endpoint|port|token|key|secret|user|email"
    r"|model_path)",
    re.IGNORECASE,
)
_REDACTED = "<redacted>"
# A home directory leaks the account name wherever it appears in free text.
_HOME = re.compile(re.escape(str(Path.home())))

# ...but the account name also appears in paths that are NOT under $HOME, and those
# survived home-only redaction. Real examples on an ordinary Linux desktop:
#
#     /media/<account>/USB-STICK        a file being transcribed off a drive
#     /run/media/<account>/...          the same, on other distributions
#     /tmp/pytest-of-<account>/...      how this was noticed
#
# The comment above already says the thing being protected is the *account name*;
# only the home-path spelling of it was implemented.
#
# Names too short or too generic are left alone, and that is not a compromise: a
# machine whose account is "root" or "ubuntu" is not identified by it, while
# blanking a three-letter common word would shred the surrounding log into
# unreadable diagnostics. Redaction that destroys the report defeats its purpose
# as surely as redaction that misses.
_GENERIC_ACCOUNTS = frozenset({
    "root", "user", "users", "admin", "administrator", "test", "guest", "default",
    "ubuntu", "debian", "fedora", "runner", "build", "builder", "ci", "jenkins",
    "docker", "vagrant", "pi", "nobody", "localadmin", "developer",
})


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _account_pattern() -> re.Pattern[str] | None:
    r"""A word-boundary matcher for this account name, or None if not worth hiding.

    The boundary is applied only at an edge that is a word character, because `\b`
    asserts a *transition* — put it next to a non-word character and it demands a word
    character on the other side, which is the opposite of what is wanted. An account
    called `yz-win2$` produced `\byz\-win2\$\b`, and in

        yz-win2$'s AirPods Pro

    the `'` after the `$` is not a word character either, so the pattern could not
    match and the name went into the report in clear. Found on a Windows host, where
    it is not a corner case: a machine account is `<hostname>$` by convention, and a
    Bluetooth microphone is named after its owner.

    Dropping the boundary at a non-word edge over-matches a longer token
    (`yz-win2$extra`) — which contains the account name, so redacting it is right.
    For a privacy filter the safe direction is to redact more, not less; the `\b` is
    kept wherever it does its real job, which is stopping `ada` matching inside
    `adam`.
    """
    try:
        import getpass

        name = (getpass.getuser() or "").strip()
    except Exception:
        return None
    if len(name) < 3 or name.lower() in _GENERIC_ACCOUNTS:
        return None
    head = r"\b" if _is_word_char(name[0]) else ""
    tail = r"\b" if _is_word_char(name[-1]) else ""
    return re.compile(rf"{head}{re.escape(name)}{tail}", re.IGNORECASE)


_ACCOUNT = _account_pattern()


@dataclass(frozen=True)
class Bundle:
    """A written report and a one-line summary of what it contains."""

    path: Path
    summary: str


def redact_text(text: str) -> str:
    """Replace the user's home directory and account name, everywhere.

    Home first: it is the longer and more specific match, so `/home/ada/x` becomes
    `~/x` rather than `/home/<redacted>/x`.
    """
    text = _HOME.sub("~", text)
    if _ACCOUNT is not None:
        text = _ACCOUNT.sub(_REDACTED, text)
    return text


#: Config keys whose value is **the user's own prose**, not a setting. Their contents
#: are replaced wholesale rather than filtered, because partial redaction here is worse
#: than none: it leaves the field looking handled.
#:
#: `[stt] initial_prompt` is the case that showed it. It holds the personal dictionary —
#: names, employers, project names, email addresses — and `yazses tune` proposes writing
#: to it, so a tuned install has one. Filtered, a real value came back as:
#:
#:     "<redacted> Seyedkazemi Ardebili, <redacted>.seyedkazemi@gmail.com, KubeIntellect…"
#:
#: The account name matched and nothing else did, so the surname, the email domain, the
#: employer and two project names travelled into a bug report **wearing a `<redacted>`
#: marker** that invites the reader to believe the field was cleaned.
#:
#: `[learning] redact_patterns` is the subtler one: those are regexes the user wrote to
#: scrub their *own* secrets from the corpus, so the patterns describe what they consider
#: secret. Publishing the rule is a smaller leak than publishing the data, not no leak.
#: Only the **string-valued** prose keys are named here. The collection-valued ones —
#: `[learning] redact_patterns`, `[snippets] entries`, `[profiles.app]` — are already
#: covered by the generic "summarise every list and dict" rule below, so naming them
#: too was redundant. It was also actively wrong: `tests/test_config_keys_are_read.py`
#: keeps a ledger of config keys **no code reads**, and naming the snippets table
#: here made that unwired field register as wired. A redaction rule must not make a
#: feature look implemented.
_FREE_TEXT_KEYS = frozenset({
    "initial_prompt",       # [stt] — the personal dictionary
    "llm_system_prompt",    # [filters.disfluency] — may be rewritten by hand
    "author",               # [macros] — config.py: "value substituted for ${author}"
    "device_name",          # [bridge] — a paired phone is usually named after its owner
})


#: Every *other* string-valued config field is kept verbatim, because that is what
#: makes a bundle worth reading: a backend name, a language code, a log level.
#:
#: The list of which fields those are lives in
#: `tests/test_report_classifies_every_config_string.py`, not here, and deliberately.
#: Naming them in `src/` would make `scripts/config_status.py` count them as *read* --
#: it decides that by looking for the key name in the source -- and seven of them
#: (`vad_source`, `lsp_editor`, `evdev_device`, `lora_base_model`, `embed_model`,
#: `partial_marker`, `delimiter`) are on the ledger of keys **no code reads**. A
#: redaction rule must not make a feature look implemented. That is the same trap the
#: note above `_FREE_TEXT_KEYS` describes, and it caught this change too.
#:
#: The obligation is a build-time one anyway, not a runtime one: nothing here needs the
#: safe list, since falling through *is* keeping the value. What the guard adds is that
#: the three-way classification is **total** over the config dataclasses, so a new
#: string field fails the build until someone decides whether it is an identifier, the
#: user's prose, or a published setting. A guard that lists what was wrong on the day it
#: was written says nothing about the next field; one that demands a decision for every
#: field does.


#: Values that come from a small, **published** set of names, keyed by
#: ``(section, key)``. The key-name filter above blanks them by substring -- ``key``
#: matches both ``[hotkey] key`` and ``command_key`` -- and blanking them protects
#: nothing: `doctor`, `status`, `quickstart`, `hotkey show` and the tray tooltip all
#: print the very same value unredacted, and the twelve names are in the CLI's own
#: `--help`.
#:
#: What it cost was a diagnosis. The bundle already carries `daemon.hotkey`, the key the
#: running daemon is actually listening on, so a report from a machine whose daemon
#: never re-read a changed config held **both halves** of that comparison and blanked
#: one of them -- the single failure ("the hotkey does nothing") that a support reader
#: cannot otherwise tell from a broken keyboard.
#:
#: Two properties keep this from becoming a hole. It is keyed by section, so a future
#: ``[api] key`` is still redacted; and it is gated on the value being *in* the set, so
#: an unrecognised value -- precisely the case where nobody knows what it is -- falls
#: through to redaction rather than out of it.
_FIXED_SET_VALUES: dict[tuple[str, str], frozenset[str]] = {}


def _load_fixed_set_values() -> dict[tuple[str, str], frozenset[str]]:
    """Built lazily so `report` keeps importing without the hotkey layer present."""
    if not _FIXED_SET_VALUES:
        from yazses.hotkeys.names import SETTABLE_HOTKEYS

        names = frozenset(SETTABLE_HOTKEYS)
        _FIXED_SET_VALUES[("hotkey", "key")] = names
        # `""` is deliberately absent: an unset command key already skips the redaction
        # branch below on its `value not in ("", None)` guard and comes out as `""`.
        # Adding it here would read like a guard and guard nothing.
        _FIXED_SET_VALUES[("hotkey", "command_key")] = names
    return _FIXED_SET_VALUES


def _summarise(value: object) -> str:
    """Describe a value's shape without its content.

    "Configured, and this big" is the diagnostic half — it distinguishes an empty
    vocabulary from a 400-term one, which is a real difference when reading a bug
    report — and none of it identifies anyone.
    """
    if isinstance(value, dict):
        return f"{_REDACTED} ({len(value)} entr{'y' if len(value) == 1 else 'ies'})"
    if isinstance(value, (list, tuple)):
        return f"{_REDACTED} ({len(value)} item{'' if len(value) == 1 else 's'})"
    text = str(value)
    return f"{_REDACTED} ({len(text)} chars)" if text else ""


def redact_config(raw: dict) -> dict:
    """Keep the shape of the config, drop values that identify the machine or the user.

    Whether a setting is *set* is what explains a bug; what it is set to rarely is. The
    exception is booleans and numbers, which are the settings that actually change
    behaviour and cannot identify anyone.

    Two rules beyond the key-name filter, both closing holes that were invisible:

    * **Free-text keys are replaced, not filtered** (see `_FREE_TEXT_KEYS`).
    * **Every list and dict is summarised by size.** They used to pass through
      *verbatim* — the `else` branch below returned them untouched — and they are
      precisely where user prose lives: a snippet table, a per-app profile map, a list
      of redaction patterns. No configuration list is diagnostic for its contents; the
      count answers what a reader actually needs.
    """
    out: dict = {}
    for section, values in raw.items():
        if not isinstance(values, dict):
            out[section] = values
            continue
        clean: dict[str, object] = {}
        for key, value in values.items():
            if isinstance(value, bool | int | float):
                clean[key] = value
            elif str(key) in _FREE_TEXT_KEYS:
                clean[key] = _summarise(value)
            elif str(value) in _load_fixed_set_values().get((str(section), str(key)), ()):
                clean[key] = value
            elif _REDACT_KEYS.search(str(key)) and value not in ("", None):
                clean[key] = _REDACTED
            elif isinstance(value, str):
                clean[key] = redact_text(value)
            elif isinstance(value, dict | list | tuple):
                clean[key] = _summarise(value)
            else:
                clean[key] = value
        out[section] = clean
    return out


#: Daemon-status fields that carry **what the user said**, as opposed to what the daemon
#: is doing. Same rule as `_FREE_TEXT_KEYS` one layer up, and the same reason for
#: replacing rather than filtering: a partially-scrubbed transcript looks handled.
#:
#: `staged.preview` is the case that showed it, and it is not an edge case — staged mode
#: exists so you can *review* text before it is typed, so the field is populated exactly
#: when a person is mid-sentence. It is the pending buffer verbatim, up to 240 characters.
#: Through a real bundle:
#:
#:     "preview": "My bank card is 4539 1488 0343 6467 and the PIN is 8812. Tell Sarah…"
#:
#: while `yazses report --help` says, in the same breath as inviting the user to attach
#: the file to an issue: *"Your dictated text and the learning corpus are never
#: included."*
_STATUS_PROSE_KEYS = frozenset({
    "preview",  # [staged] the pending buffer, as it would be typed
})


def redact_status(status: dict) -> dict:
    """Clean the daemon's status payload for the bundle. Recursive.

    The config half of this file has been hardened four times; the daemon half went in
    **verbatim** — `report["daemon"] = status`, no filter of any kind — and it is the
    same kind of data from the same machine. `summarise_for_issue` even states the
    invariant that was not true: *"Everything in report has already been through
    `redact_text`/`redact_config` in `collect`."*

    So the rules are deliberately the config rules, not a second scheme:

    * numbers and booleans pass — they are the fields that explain a failure and cannot
      identify anyone;
    * prose is replaced by its shape (see `_STATUS_PROSE_KEYS`);
    * nested dicts recurse, because `staged`, `outcomes` and `decode_latency` are all
      dicts whose *numbers* are the diagnostic part and summarising them wholesale would
      throw away the reason to collect a report at all;
    * lists are summarised by size — `notifications` is a list of queued toast bodies,
      and a toast quotes whatever it is reporting on;
    * every remaining string goes through `redact_text`.

    That last rule is what makes this more than a `preview` patch. `last_error` is an
    exception message, and exception messages are mostly paths (`FileNotFoundError:
    /home/<you>/…`); `input_device` and `last_good_device` are microphone names, and a
    Bluetooth microphone is usually named after its owner. Both are kept rather than
    blanked — which mic is in use is the first question any audio bug asks — on exactly
    the trade this module already makes for the log tail: redact the account, keep the
    diagnosis.
    """
    out: dict = {}
    for key, value in status.items():
        if isinstance(value, bool | int | float):
            out[key] = value
        elif str(key) in _STATUS_PROSE_KEYS:
            out[key] = _summarise(value)
        elif isinstance(value, dict):
            out[key] = redact_status(value)
        elif isinstance(value, list | tuple):
            out[key] = _summarise(value)
        elif isinstance(value, str):
            out[key] = redact_text(value)
        else:
            out[key] = value
    return out


def collect(*, config_file: Path, log_file: Path, data_dir: Path,
            status: dict | None, log_lines: int = 200) -> dict:
    """Gather the report as a plain dict, so it can be inspected before it is written."""
    from yazses import tomlio
    from yazses.config import load_config_checked

    report: dict = {"generated_by": "yazses report"}

    report["system"] = {
        "platform": sys.platform,
        "release": py_platform.release(),
        "python": py_platform.python_version(),
        "session_type": _env("XDG_SESSION_TYPE"),
        "desktop": _env("XDG_CURRENT_DESKTOP"),
    }
    try:
        from yazses import __version__

        report["system"]["yazses"] = __version__
    except Exception:  # noqa: BLE001
        report["system"]["yazses"] = "unknown"

    report["daemon"] = (
        redact_status(status) if status is not None else {"reachable": False}
    )

    if config_file.exists():
        try:
            report["config"] = redact_config(tomlio.read(config_file))
        except Exception as exc:  # noqa: BLE001
            report["config"] = {"error": f"unreadable: {exc}"}
        try:
            report["config_problems"] = [
                str(p) for p in load_config_checked(config_file).problems
            ]
        except Exception:  # noqa: BLE001
            report["config_problems"] = ["could not be checked"]
    else:
        report["config"] = {"note": "no config file — running on defaults"}

    report["log_tail"] = _log_tail(log_file, log_lines)

    # The learning corpus holds real transcripts and audio. Size only; never opened.
    #
    # Sized through the same helper the store prunes against, because the audio
    # clips are almost all of it: this counted `corpus.db` alone and reported 3.0 MB
    # for a corpus `yazses corpus status` measured at 1294.9 MB. That number lands in
    # bug reports, and it is the one a user checks against `[learning] max_corpus_mb`.
    #
    # Mebibytes, matching what the cap actually enforces (`max_mb * 1024 * 1024`) and
    # what `yazses corpus status` prints. Dividing by 1e6 here instead made the two
    # surfaces disagree -- 1357.8 against 1294.9 for one corpus -- which reads as a
    # bug in one of them, and leaves the reported number not comparable to the cap it
    # exists to be compared against.
    from yazses.learning.store import corpus_disk_bytes

    corpus = data_dir / "corpus.db"
    report["corpus"] = {
        "present": corpus.exists(),
        "size_mb": round(corpus_disk_bytes(data_dir) / 1_048_576, 1) if corpus.exists() else 0,
        "note": "contents deliberately not included",
    }
    return report


#: Lines at this level carry dictated text. `core/daemon.py` says so where it writes them:
#: "INFO: metadata only (length); DEBUG: the actual text." The default is INFO, which is why
#: a normal log holds no transcripts -- verified across 1422 of them against a real 5465-line
#: log, with zero hits.
#:
#: But `[general] log_level = "DEBUG"` is a supported setting, and it is exactly what someone
#: turns on to investigate the problem they are about to report. This bundle is designed to
#: be attached to a public issue, and this module's own docstring promises the tail "records
#: levels, durations and word *counts*, never transcripts" -- true at INFO, false at DEBUG.
#:
#: So they are dropped rather than warned about. A bundle that is safe to share only if the
#: reader noticed a warning is not safe to share; the point of this file is that it is safe
#: BY CONSTRUCTION. The count of dropped lines is reported, so nothing is hidden and anyone
#: who wants them can attach the log deliberately.
_CONTENT_LEVEL = "DEBUG"


def _log_tail(log_file: Path, lines: int) -> list[str]:
    if not log_file.exists():
        return ["<no log file>"]
    try:
        content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"<unreadable: {exc}>"]
    # Drop whole *records*, not lines. A log record is not one line: every `exc_info=True`
    # call writes a header plus a traceback, and a filter that tests each line drops the
    # header -- the only line carrying the level -- while keeping the body, which carries
    # the frames and the exception message. Reproduced on a synthetic log: two DEBUG
    # headers removed, five of their own lines emitted, and the bundle reported "2 omitted".
    # A record whose level was judged unsafe cannot have a safe remainder.
    tail, _note = tail_records(content, lines)
    kept: list[str] = []
    dropped = 0
    # Conservative until a header proves otherwise: a continuation line at the very start
    # of the window belongs to a record whose level we cannot see, so it cannot be shown
    # to be safe. `tail_records` makes that rare -- it survives only a rotation that cut
    # the header away -- but the default has to be the safe one either way.
    #
    # Unless the window carries no record headers at all. Then it is not this format --
    # a plain-text log, or a rotation that kept only bodies -- and there are no
    # level-tagged records for the filter to protect against. Defaulting to unsafe there
    # would empty the bundle rather than protect it, so the filter stands down and
    # `redact_text` remains the guard, exactly as before.
    unsafe = any(starts_record(line) for line in tail)
    for line in tail:
        if starts_record(line):
            unsafe = f" {_CONTENT_LEVEL} " in line
        if unsafe:
            dropped += 1
        else:
            kept.append(redact_text(line))
    out = kept
    if dropped:
        out.append(
            f"<{dropped} line(s) omitted: whole DEBUG records, which can contain dictated "
            f"text, and this bundle is meant to be shareable. Attach the log yourself if "
            f"you need them.>"
        )
    return out


def _env(name: str) -> str:
    import os

    return os.environ.get(name, "")


# GitHub's new-issue form. The body travels as a query parameter, so the constraint
# is the length of the *encoded URL* — and a URL that is too long produces an empty
# form rather than a truncated one, so the failure is total.
ISSUE_URL = "https://github.com/MSKazemi/yazses/issues/new"

#: Practical ceiling for the whole URL. Browsers and proxies start rejecting well
#: below the theoretical limit; 8 kB is the number every implementation clears.
ISSUE_URL_LIMIT = 8000

#: Budget for the **percent-encoded** body, leaving room for the base URL, the
#: parameter names and an encoded title.
#:
#: Measured rather than assumed, and the measurement is the point. This was first
#: written as a limit on the *raw* body, which is the wrong quantity: percent-encoding
#: expands text by ~1.27x for a typical log line, ~1.45x for a Markdown heading, and 3x
#: for punctuation-dense text, because a space, a colon and a newline each become three
#: characters — and 9x for non-Latin script, where every UTF-8 byte becomes three. A
#: 6000-character body, comfortably "within the limit", produced a **12,972-character
#: URL** on a real report from this machine. The trimming loop measures what travels.
ISSUE_BODY_LIMIT = 6800


def summarise_for_issue(
    report: dict,
    *,
    diagnosis=None,
    limit: int = ISSUE_BODY_LIMIT,
    log_lines: int = 40,
) -> str:
    """A Markdown issue body from *report*, bounded so it survives a URL.

    ADR-v2-132 option (b): **prepare, never send.** This produces text for a form the
    *user* submits from their own browser and account, having read every word. YazSes
    makes no request, so ADR-019's egress inventory is unchanged — if implementing this
    ever required editing `tests/test_egress_inventory.py`, it would have gone wrong.

    Redaction is not repeated here. Everything in *report* has already been through
    `redact_text`/`redact_config` in `collect`, and a second implementation is how the
    two drift — which is this repo's most frequent defect. The one thing added is the
    diagnosis, whose text is written in this file and contains nothing about the user.

    The log tail is the part that has to give: it is the largest field by far and the
    *most recent* lines are the ones that matter, so it is cut from the front and the
    cut is stated rather than silent. A body that quietly loses its ending would have
    the user file a report they believe is complete.
    """
    tail = list(report.get("log_tail") or [])[-log_lines:]
    body = _render_issue_body(report, diagnosis, tail, trimmed=False)
    if _encoded_len(body) <= limit:
        return body

    # Too long. Drop log lines from the *oldest* end until it fits, and say so — a
    # body that quietly loses its ending would have the user file a report they
    # believe is complete. Cutting mid-line is avoided for the same reason a
    # truncated path looks like a real one.
    #
    # Measured **encoded**, because that is what travels: see ISSUE_BODY_LIMIT.
    while tail:
        tail = tail[1:]
        body = _render_issue_body(report, diagnosis, tail, trimmed=True)
        if _encoded_len(body) <= limit:
            return body

    # Nothing left to trim: the non-log sections alone exceed the budget, which means
    # a pathological config-problem list. Cut hard rather than return an unusable URL
    # — and cut against the encoded length, or the result looks trimmed and still
    # will not open.
    while body and _encoded_len(body) > limit:
        body = body[: max(1, int(len(body) * limit / _encoded_len(body)) - 1)]
    return body


def _encoded_len(text: str) -> int:
    """How many characters *text* occupies once it is in the URL."""
    return len(_percent_encode(text))


def _render_issue_body(report: dict, diagnosis, tail: list[str], *, trimmed: bool) -> str:
    """Render the issue body for one specific log tail. Pure."""
    system = report.get("system") or {}
    daemon = report.get("daemon") or {}
    lines: list[str] = []

    if diagnosis is not None:
        lines += [
            "## What happened",
            "",
            f"**{getattr(diagnosis, 'title', '')}**",
            "",
            str(getattr(diagnosis, "what", "")),
            "",
            f"_Suggested fix shown to me:_ {getattr(diagnosis, 'fix', '')}",
            "",
            f"_Diagnosis id:_ `{getattr(diagnosis, 'slug', 'unknown')}`",
            "",
        ]

    lines += [
        "## What I expected instead",
        "",
        "<!-- please add: what you were doing, and what should have happened -->",
        "",
        "## Environment",
        "",
        f"- YazSes: {system.get('yazses', 'unknown')}",
        f"- Platform: {system.get('platform', '?')} {system.get('release', '')}".rstrip(),
        f"- Python: {system.get('python', '?')}",
        f"- Session: {system.get('session_type') or '?'} / "
        f"{system.get('desktop') or '?'}",
        f"- Daemon state: {daemon.get('state', 'unreachable')}",
        f"- Model: {daemon.get('model', '?')}",
        "",
    ]

    problems = report.get("config_problems") or []
    if problems:
        lines += ["## Config problems", "", *(f"- {p}" for p in problems), ""]

    if tail:
        lines += ["## Recent log (metadata only — never transcripts)", "", "```"]
        lines += tail
        lines += ["```", ""]
        if trimmed:
            lines += ["_(older log lines were trimmed so this fits the issue form)_", ""]

    lines += [
        "---",
        "",
        "_Prepared by `yazses report`. Everything above was assembled on my machine "
        "and is visible to me in this form before I submit it._",
    ]
    return "\n".join(lines)


#: RFC 3986 unreserved set — the characters a query value may carry literally.
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _percent_encode(value: str) -> str:
    """Percent-encode *value* for a URL query, without importing `urllib`.

    Hand-rolled for one specific reason, and it is not aesthetics. `ADR-019`'s egress
    guard scans this package for network-shaped imports and is **deliberately**
    conservative: `urllib.parse` cannot open a socket, but `urllib` is on its list, so
    `from urllib.parse import urlencode` fails the build here. The designed remedy is
    to register the module in the inventory — and doing that would be a lie. This file
    neither fetches nor sends; its first line is *"Nothing is ever sent anywhere"*, and
    ADR-v2-132 chose option (b) precisely so the inventory would not change.

    Weakening the guard to permit `urllib.parse` would trade a real protection for a
    convenience, in the one module where the protection is most load-bearing.

    The encoding itself is pinned against `urllib.parse.quote` in the tests, which are
    outside the scanned tree — so the stdlib still defines correctness, it just is not
    imported here.
    """
    out: list[str] = []
    for char in value:
        if char in _UNRESERVED:
            out.append(char)
        else:
            out.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
    return "".join(out)


def issue_url(title: str, body: str, *, base: str = ISSUE_URL) -> str:
    """The pre-filled GitHub new-issue URL. Opens a form; files no issue.

    The user lands on GitHub's own page with the fields filled in, reads them, and
    presses submit themselves — consent to a specific payload they have seen, rather
    than to a category.

    Be precise about what that consent covers, because the earlier wording ("submits
    nothing") invited the wrong reading. *Title and body are in the query string of the
    GET that opens the page*, so they reach github.com **when the page opens**, before
    the user has read a line of it. Pressing submit creates the issue; declining leaves
    no issue, not no transmission. The payload is `report.collect`'s redacted output
    either way — no dictated text, no paths, no identifiers — and this is declared in
    the ADR-019 inventory as a handoff for exactly this reason.
    """
    return f"{base}?title={_percent_encode(title)}&body={_percent_encode(body)}"


def write(report: dict, out: Path) -> Bundle:
    """Write the report as JSON and describe it in one line."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    problems = len(report.get("config_problems") or [])
    daemon = report.get("daemon") or {}
    state = daemon.get("state", "unreachable")
    return Bundle(
        path=out,
        summary=(
            f"daemon={state}, config problems={problems}, "
            f"log lines={len(report.get('log_tail') or [])}"
        ),
    )
