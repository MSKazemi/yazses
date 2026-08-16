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


def redact_config(raw: dict) -> dict:
    """Keep the shape of the config, drop values that identify the machine or the user.

    Whether a setting is *set* is what explains a bug; what it is set to rarely is. The
    exception is booleans and numbers, which are the settings that actually change
    behaviour and cannot identify anyone.
    """
    out: dict = {}
    for section, values in raw.items():
        if not isinstance(values, dict):
            out[section] = values
            continue
        clean: dict[str, object] = {}
        for key, value in values.items():
            if isinstance(value, (bool, int, float)):
                clean[key] = value
            elif _REDACT_KEYS.search(str(key)) and value not in ("", None):
                clean[key] = _REDACTED
            elif isinstance(value, str):
                clean[key] = redact_text(value)
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
    corpus = data_dir / "corpus.db"
    report["corpus"] = {
        "present": corpus.exists(),
        "size_mb": round(corpus.stat().st_size / 1e6, 1) if corpus.exists() else 0,
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
