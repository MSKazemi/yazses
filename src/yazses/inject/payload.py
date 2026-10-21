"""Keep the text being typed out of the errors a keystroke backend raises. Pure.

Every command-line backend hands the transcript to its tool as an argument after
``--`` (``wtype -- <text>``, ``xdotool type ... -- <text>``, ``ydotool type ... --
<text>``, ``wl-copy -- <text>``). When the tool fails, ``subprocess.run(check=True)``
raises ``CalledProcessError`` and a timeout raises ``TimeoutExpired``, and the
``str()`` of both is the **whole command line**:

    Command '['wtype', '--', '<everything you just said>']' returned non-zero exit status 1.

That string does not stay in the backend. ``LinuxInjector`` logs it at WARNING before
falling back to the clipboard, the daemon logs it again as ``Pipeline error: …`` and
copies it into ``last_error``, which ``yazses status`` prints and the ``yazses report``
bundle carries. ``redact_text`` there removes paths and the account name, not prose, so
a single failed keystroke put a transcript into the default-level log and into a file
the user is invited to attach to a public issue (SEC-002,
``tests/test_no_log_record_carries_dictated_text.py``).

So the payload is described here by its length and nothing else. The tool name and
every flag before ``--`` are kept, because they are what diagnoses the failure
(``system/diagnosis.py`` matches on ``ydotool`` / ``xdotool``) and none of them is
something the user said.

Only the command line is rewritten. A tool's own stderr is left as the tool wrote it;
none of the tools above is known to echo its input there, and nothing here claims to
scrub it.
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

#: The argument after which every backend in this package puts the text it types.
END_OF_OPTIONS = "--"


def describe_argv(argv: Sequence[object]) -> list[str]:
    """*argv* with every argument after the first ``--`` replaced by its length.

    ``["wtype", "--", "hello"]`` becomes ``["wtype", "--", "<5 chars>"]``. An argv with
    no ``--`` comes back unchanged (as strings): key names and counts are not dictation.
    """
    out: list[str] = []
    payload = False
    for arg in argv:
        text = str(arg)
        if payload:
            out.append(f"<{len(text)} chars>")
            continue
        out.append(text)
        payload = text == END_OF_OPTIONS
    return out


@contextmanager
def hide_payload() -> Iterator[None]:
    """Re-raise a failed or timed-out command with its payload described, not quoted.

    The **same** exception object propagates -- same type, same return code, same
    traceback -- so every ``except CalledProcessError`` / ``except TimeoutExpired``
    downstream behaves exactly as before. What is rewritten is ``cmd``, which both
    classes format into ``str()``, and the matching entry of ``args``, which is a
    separate copy taken at construction and is what ``repr()`` shows -- a log call
    written with ``%r`` would otherwise still quote the transcript.
    """
    try:
        yield
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        original = exc.cmd
        if isinstance(original, list | tuple):
            shown = describe_argv(original)
            exc.cmd = shown
            exc.args = tuple(shown if arg is original else arg for arg in exc.args)
        raise
