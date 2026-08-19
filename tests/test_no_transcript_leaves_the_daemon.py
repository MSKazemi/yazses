"""Nothing but DEBUG may carry what the user said.

Two promises in this project are made in prose and enforced by nothing:

* `yazses logs` is *"Show daemon diagnostic log (metadata only)"*, and `core/daemon.py`
  states the split where it writes them — *"INFO: metadata only (length); DEBUG: the actual
  text."*
* Desktop notifications describe what happened, never what was said. Nothing checked that
  either, and a notification body is both shown on screen and written to the log.

They held. Measured on a real 5,465-line log against 1,262 recorded transcripts, searching
for a distinctive four-word window of each: **zero** hits. Of 30 notification call sites,
**zero** pass transcript text.

But `yazses report` bundles that log tail for a public issue, and at
`[general] log_level = "DEBUG"` it would have carried dictated text — fixed separately. That
is what a promise kept by care rather than by a check eventually costs, so this makes both
mechanical.

## What counts as metadata

`len(text)` and `len(text.split())` are counts, and counts are the whole point of the INFO
line. Passing the variable **whole** is content. `log.debug` may do it, deliberately and
documented; nothing else may.

## Deliberately conservative

The variable names below are the ones this codebase uses for a transcript. A new one escapes
the scan — which is why the empirical check above matters and why this is a second line of
defence rather than the only one. A false positive costs one entry in `ALLOWED`; a false
negative costs the promise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yazses

SRC = Path(yazses.__file__).resolve().parent

#: Names this codebase uses for text the user dictated.
TRANSCRIPT = frozenset({
    "text", "raw_text", "cleaned_text", "filtered_text", "final_text",
    "transcript", "utterance", "spoken", "phrase", "correction_text", "retx_text",
})
#: Logging methods that write to the file a user is invited to share.
SHAREABLE_LEVELS = frozenset({"info", "warning", "error", "exception", "critical"})
#: Notification entry points — shown on screen *and* logged.
NOTIFIERS = frozenset({
    "notify", "_notify_mic", "_notify_cmdsafety", "_notify_rewrite", "_report_failure",
})

#: Known, reviewed exceptions. Empty, and that is the point: it should stay that way.
ALLOWED: frozenset[tuple[str, int]] = frozenset()


def _carries_transcript(node: ast.AST) -> set[str]:
    """The transcript-shaped names a call argument passes WHOLE.

    `len(text)` is a count and therefore metadata; the argument is only content when the
    name is used bare or as an attribute, not wrapped in a length.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
        return set()
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "len":
            continue
        if isinstance(child, ast.Name) and child.id in TRANSCRIPT:
            found.add(child.id)
        elif isinstance(child, ast.Attribute) and child.attr in TRANSCRIPT:
            found.add(child.attr)
    return found


def _scan():
    """`(kind, file, lineno, names)` for every call that carries a transcript."""
    out, sites = [], {"log": 0, "notify": 0}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attr = getattr(node.func, "attr", getattr(node.func, "id", ""))
            is_log = (
                attr in SHAREABLE_LEVELS
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ("log", "logger")
            )
            is_notify = attr in NOTIFIERS
            if not (is_log or is_notify):
                continue
            sites["log" if is_log else "notify"] += 1
            args = node.args[1:] if is_log else node.args
            names: set[str] = set()
            for arg in args:
                names |= _carries_transcript(arg)
            if names and (rel, node.lineno) not in ALLOWED:
                out.append(("log" if is_log else "notify", rel, node.lineno, sorted(names)))
    return out, sites


FINDINGS, SITES = _scan()


def test_the_scan_found_something_to_check() -> None:
    """Guard the guard: an empty scan would read as a clean bill of health."""
    assert SITES["log"] > 50, f"only {SITES['log']} shareable log calls found — scan broken"
    assert SITES["notify"] > 10, f"only {SITES['notify']} notification calls found"


def test_no_shareable_log_line_carries_what_was_said() -> None:
    leaks = [f for f in FINDINGS if f[0] == "log"]
    assert not leaks, (
        "these write dictated text at a level that reaches the log file `yazses logs` "
        f"shows and `yazses report` bundles: {leaks}\n\n"
        "Use `len(text)` / `len(text.split())` for the metadata line and `log.debug` for "
        "the content, as `core/daemon.py` does."
    )


def test_no_notification_carries_what_was_said() -> None:
    leaks = [f for f in FINDINGS if f[0] == "notify"]
    assert not leaks, (
        "these put dictated text in a desktop notification, which is shown on screen and "
        f"written to the log: {leaks}"
    )


def test_debug_may_still_carry_it() -> None:
    """The documented exception; a scan that also caught DEBUG would force the daemon to
    stop logging the one thing that makes a transcription bug diagnosable."""
    import inspect

    from yazses.core.daemon import Daemon

    assert 'log.debug("Injecting text: %r", text)' in inspect.getsource(Daemon._on_hold_end)


def test_the_allow_list_is_empty() -> None:
    """It exists so a reviewed exception is visible, not so one accumulates."""
    assert not ALLOWED, f"reviewed exceptions have appeared: {sorted(ALLOWED)}"
