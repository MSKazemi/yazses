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
anything path- or identity-shaped, and the corpus — which does hold text and audio — is
summarised by size and never opened.
"""
from __future__ import annotations

import json
import platform as py_platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Config keys whose values are paths, addresses or identifiers rather than settings. The
# value is replaced, not the key: knowing that a socket is configured is diagnostic, and
# knowing where it points is nobody's business.
_REDACT_KEYS = re.compile(
    r"(path|dir|file|socket|host|address|port|token|key|secret|user|email|model_path)",
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


def _account_pattern() -> re.Pattern[str] | None:
    """A word-boundary matcher for this account name, or None if not worth hiding."""
    try:
        import getpass

        name = (getpass.getuser() or "").strip()
    except Exception:
        return None
    if len(name) < 3 or name.lower() in _GENERIC_ACCOUNTS:
        return None
    return re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)


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
})


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


def collect(*, config_file: Path, log_file: Path, data_dir: Path,
            status: dict | None, log_lines: int = 200) -> dict:
    """Gather the report as a plain dict, so it can be inspected before it is written."""
    import tomllib

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

    report["daemon"] = status if status is not None else {"reachable": False}

    if config_file.exists():
        try:
            with open(config_file, "rb") as fh:
                report["config"] = redact_config(tomllib.load(fh))
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


def _log_tail(log_file: Path, lines: int) -> list[str]:
    if not log_file.exists():
        return ["<no log file>"]
    try:
        content = log_file.read_text(errors="replace").splitlines()
    except OSError as exc:
        return [f"<unreadable: {exc}>"]
    return [redact_text(line) for line in content[-lines:]]


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
    """The pre-filled GitHub new-issue URL. Opens a form; submits nothing.

    The user lands on GitHub's own page with the fields filled in, reads them, and
    presses submit themselves — consent to a specific payload they have seen, rather
    than to a category.
    """
    return f"{base}?title={_percent_encode(title)}&body={_percent_encode(body)}"


def write(report: dict, out: Path) -> Bundle:
    """Write the report as JSON and describe it in one line."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
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
